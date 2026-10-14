# -*- coding: utf-8 -*-
"""AI 结构化指标提取：把已入库 Exam 的 ocr_text → LLM 提取指标 JSON。

- 读取 exams 表中所有记录（按 id 升序）。
- 调用 app.llm.chat_text（当前启用的自定义模型 u2-flash@1，Anthropic 协议）。
- 每个 Exam 的提取结果：
    * exam.extracted_json = 指标 JSON 数组（硬性规则 7：与 OCR 文本一致）
    * metrics 表批量写入（先清空该 exam 已有 metrics，保证幂等）
- 数值型指标会用参考范围做二次校验 abnormal（比 LLM 判断更可靠）。

用法：
  python scripts/extract_metrics.py [--exam-id N] [--dry-run]
"""
import argparse
import asyncio
import json
import re
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from app import crud, llm  # noqa: E402

VALID_BODY_PARTS = {
    "heart", "liver", "kidney", "pancreas", "thyroid", "bone", "blood", "whole_body",
}

PROMPT_TEMPLATE = """你是一个体检报告结构化提取助手。请从下面的 OCR 文本中提取所有可测量的体检指标。

要求：
1. 只输出一个 JSON 数组，不要输出任何其他文字、解释或 Markdown 代码块标记。
2. 每个指标一个对象，字段如下：
   {{
     "name": "指标中文名",
     "value_text": "结果值（保留 OCR 原文写法，如 3.5、<0.1、阴性）",
     "unit": "单位（无单位填空字符串）",
     "ref_low": "参考范围下限（无则空字符串）",
     "ref_high": "参考范围上限（无则空字符串）",
     "abnormal": 0 或 1（结果异常=1，正常=0；定性结果如阳性/升高/降低视为异常=1，阴性/正常=0；数值超出参考范围=1）",
     "body_part": "部位英文（heart/liver/kidney/pancreas/thyroid/bone/blood/whole_body 之一）",
     "note": "当 OCR 模糊、数值可疑或不确定时填'低置信度，待核实'，否则空字符串"
   }}
3. body_part 映射参考：heart=血压/心率/心电图/总胆固醇/LDL；liver=ALT/AST/γ-GT/胆红素；kidney=肌酐/尿素氮/尿酸/尿蛋白/尿常规；pancreas=空腹血糖/糖化血红蛋白；thyroid=TSH/T3/T4；bone=血钙/维生素D/骨密度；blood=血常规白细胞/红细胞/血小板等；无法归入以上部位的用 whole_body。
4. 如果页面没有可测量的检验结果（如只有病历文字、开单指引），输出空数组 []。
5. 数值与参考范围单位不一致时以参考范围为准；OCR 明显的错字/乱码不要强行提取。

OCR 文本如下：
{ocr_text}"""


def _to_float(s: str) -> float | None:
    """从字符串中提取首个浮点数（处理 <0.1、>500、1.2-3.4、~ 等）。"""
    if not s:
        return None
    s = s.strip().replace(",", "").replace("，", "")
    m = re.search(r"-?\d+(?:\.\d+)?", s)
    if not m:
        return None
    try:
        return float(m.group(0))
    except ValueError:
        return None


def _parse_ref(ref: str) -> tuple[float | None, float | None]:
    """解析参考范围文本 → (low, high)。支持 '3.5-9.5'、'<0.1'、'>5'、'0-5.18'。"""
    if not ref:
        return None, None
    ref = ref.strip()
    m = re.match(r"^<\s*([\d.]+)", ref)
    if m:
        return None, float(m.group(1))
    m = re.match(r"^>\s*([\d.]+)", ref)
    if m:
        return float(m.group(1)), None
    m = re.match(r"^([\d.]+)\s*[-~至]\s*([\d.]+)", ref)
    if m:
        return float(m.group(1)), float(m.group(2))
    return None, None


def _qualitative_abnormal(value: str) -> int | None:
    """定性结果的异常判断：阳性/升高/降低/↑/↓ → 1；阴性/正常 → 0；无法判断返回 None。"""
    v = value.strip()
    if any(k in v for k in ("阳性", "升高", "降低", "增高", "减低", "↑", "↓", "异常", "弱阳性")):
        return 1
    if any(k in v for k in ("阴性", "正常", "未见", "无")):
        return 0
    return None


def sanitize_metric(m: dict) -> dict | None:
    """清洗 + 校验单条指标，返回符合 Metric 模型字段的 dict；非法则返回 None。"""
    name = str(m.get("name") or "").strip()
    value = str(m.get("value_text") or "").strip()
    if not name or not value:
        return None
    unit = str(m.get("unit") or "").strip()
    ref_low = str(m.get("ref_low") or "").strip()
    ref_high = str(m.get("ref_high") or "").strip()
    note = str(m.get("note") or "").strip()
    body_part = str(m.get("body_part") or "").strip().lower()
    if body_part not in VALID_BODY_PARTS:
        body_part = "whole_body"

    # 异常判断：先按 LLM 输出，数值型再用参考范围二次校验
    abnormal = 1 if m.get("abnormal") in (1, "1", True) else 0
    low, high = _parse_ref(ref_low + "-" + ref_high if ref_low and ref_high else (ref_low or ref_high))
    val = _to_float(value)
    if val is not None and (low is not None or high is not None):
        if (low is not None and val < low) or (high is not None and val > high):
            abnormal = 1
        else:
            abnormal = 0
    elif val is None:
        q = _qualitative_abnormal(value)
        if q is not None:
            abnormal = q

    return {
        "name": name,
        "value_text": value,
        "unit": unit,
        "ref_low": ref_low,
        "ref_high": ref_high,
        "abnormal": abnormal,
        "body_part": body_part,
        "note": note,
        "sort": 0,
    }


def parse_llm_json(text: str) -> list[dict]:
    """解析 LLM 输出为指标列表。容忍 Markdown 代码块包裹。"""
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z]*\s*", "", t)
        t = re.sub(r"\s*```$", "", t)
    # 去掉首尾非 JSON 部分
    start = t.find("[")
    end = t.rfind("]")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("LLM 输出中未找到 JSON 数组")
    data = json.loads(t[start : end + 1])
    if not isinstance(data, list):
        raise ValueError("LLM 输出不是数组")
    return data


async def extract_exam(session, llm_route: str, exam_id: int, ocr_text: str, retries: int = 2) -> dict:
    """对单个 Exam 调用 LLM 提取，失败自动重试，返回 {ok, metrics, error}。"""
    prompt = PROMPT_TEMPLATE.format(ocr_text=ocr_text[:12000])
    messages = [{"role": "user", "content": prompt}]

    for attempt in range(retries + 1):
        raw = ""
        try:
            # disable_thinking：u2-flash 是思考型模型，不禁用会把 max_tokens 全花在
            # thinking 块上导致无输出；禁用后直接返回结构化 JSON，更快更稳。
            raw = await llm.chat_text(
                llm_route, messages, max_tokens=8192, disable_thinking=True
            )
        except Exception as e:
            if attempt < retries:
                print(f"    [重试 {attempt + 1}] LLM 调用失败: {e.__class__.__name__}", flush=True)
                await asyncio.sleep(5)
                continue
            return {"ok": False, "error": f"LLM 调用失败: {e.__class__.__name__}: {e}"}

        try:
            data = parse_llm_json(raw)
        except Exception as e:
            if attempt < retries:
                print(f"    [重试 {attempt + 1}] JSON 解析失败（原文 {len(raw)} 字）", flush=True)
                await asyncio.sleep(5)
                continue
            return {"ok": False, "error": f"JSON 解析失败: {e}. 原文: {raw[:300]}"}

        metrics = []
        for item in data:
            if not isinstance(item, dict):
                continue
            m = sanitize_metric(item)
            if m:
                metrics.append(m)
        return {"ok": True, "metrics": metrics}
    return {"ok": False, "error": "重试后仍失败"}


async def run(exam_id: int | None, dry_run: bool, only_empty: bool = False) -> None:
    from sqlalchemy import select

    from app.db import SessionLocal
    from app.models import Exam, Metric

    async with SessionLocal() as session:
        llm_map = await crud.custom_models_map(session)
        llm.set_custom_models(llm_map)
        enabled = await crud.get_enabled_model(session)
        if enabled is None:
            print("错误：没有启用的模型，请先在模型管理中启用一个模型")
            return
        route = f"{enabled.name}@{enabled.id}" if enabled.kind == "custom" else enabled.name
        print(f"使用模型: {route}（{enabled.protocol}）")

        stmt = select(Exam).order_by(Exam.id)
        if exam_id is not None:
            stmt = stmt.where(Exam.id == exam_id)
        if only_empty:
            stmt = stmt.where(Exam.extracted_json == "")
        exams = list((await session.execute(stmt)).scalars())

        if dry_run:
            print(f"[dry-run] 共 {len(exams)} 条记录待提取")
            for exam in exams:
                print(f"  id={exam.id} {exam.exam_date} {exam.hospital} ocr_len={len(exam.ocr_text)}")
            return

        for exam in exams:
            print(f"\n[提取] id={exam.id} {exam.exam_date} {exam.hospital}（ocr {len(exam.ocr_text)} 字）...", flush=True)
            result = await extract_exam(session, route, exam.id, exam.ocr_text)
            if not result["ok"]:
                print(f"  ❌ {result['error']}")
                continue
            metrics = result["metrics"]
            print(f"  ✅ 提取 {len(metrics)} 项指标")

            # 写 extracted_json（与 OCR 文本对应，规则 7）
            exam.extracted_json = json.dumps(metrics, ensure_ascii=False)
            # 清空旧指标后批量写入（幂等）
            for old in list(await crud.list_metrics(session, exam.id)):
                await session.delete(old)
            for i, m in enumerate(metrics):
                data = dict(m)
                data["sort"] = i
                session.add(Metric(exam_id=exam.id, **data))
            await session.commit()

            for m in metrics:
                flag = "⚠️异常" if m["abnormal"] else ""
                print(f"    {m['name']} = {m['value_text']} {m['unit']} 参考{m['ref_low']}-{m['ref_high']} {flag}")


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--exam-id", type=int, default=None, help="只处理指定 exam id")
    parser.add_argument("--dry-run", action="store_true", help="只列出待处理记录，不调用 LLM")
    parser.add_argument("--only-empty", action="store_true", help="只处理 extracted_json 为空的记录（重试失败项）")
    args = parser.parse_args()
    asyncio.run(run(exam_id=args.exam_id, dry_run=args.dry_run, only_empty=args.only_empty))


if __name__ == "__main__":
    from app import llm  # noqa: E402  (确保 sys.path 已插入)
    main()