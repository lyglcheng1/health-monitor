# ===============================================================
# 文件: body3d.py
# 项目: 健康数据监控（health-monitor）
# 说明: V0.3 3D 人体大屏——把体检指标按身体部位聚合，
#       生成前端 3D 大屏所需的「异常部位/全部部位」数据。
#       返回结构对齐 demo-anatomy 的 ABNORMALITIES 格式：
#         parts[]: { key, name, conceptIds[], abnormal, severity,
#                    issues[], records[], note }
#       聚合口径：
#         · 每个 (部位, 指标名) 只取「最近一次体检」的数值作为当前状态，
#           历史异常若最近已恢复正常（如吃药治好），不再标记异常；
#         · records 时间线仍保留全部历史异常记录，便于回顾；
#         · mode=all 时返回全部可映射部位（含暂无数据部位），左栏清单完整。
#       严重度判定：
#         · 默认按「当前异常指标数量」兜底（≥3 严重 / 2 中度 / 1 轻度）；
#         · 若模型设置页启用了自定义模型，
#           则调用大模型综合指标名称/数值/参考区间/历史记录判定严重程度，
#           结果带 severity_reason（AI 一句话理由），按异常指标指纹缓存；
#         · LLM 不可用/超时/返回非法 JSON → 自动回退数量兜底，大屏永远可用。
# ===============================================================
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import time

from sqlalchemy.ext.asyncio import AsyncSession

from app import crud, llm

logger = logging.getLogger(__name__)

# body_part → 3D 概念映射（conceptIds 为 atlas.json 中器官概念 ID；
# 'ALL' 表示全身，'SKELETAL' 表示骨骼系统——前端 body3d.js 特判）
BODY_PART_MAP: dict[str, dict] = {
    "kidney": {"name": "肾脏", "conceptIds": ["FMA7205", "FMA7204"]},
    "heart": {"name": "心脏", "conceptIds": ["FMA7088"]},
    "liver": {"name": "肝脏", "conceptIds": ["FMA7197"]},
    "lung": {"name": "肺部", "conceptIds": ["FMA7309", "FMA7310"]},
    "pancreas": {"name": "胰腺", "conceptIds": ["FMA7198"]},
    "stomach": {"name": "胃", "conceptIds": ["FMA7148"]},
    "spleen": {"name": "脾", "conceptIds": ["FMA7196"]},
    "brain": {"name": "脑", "conceptIds": ["FMA50801"]},
    "trachea": {"name": "气管", "conceptIds": ["FMA7394"]},
    "aorta": {"name": "主动脉", "conceptIds": ["FMA3734"]},
    "esophagus": {"name": "食管", "conceptIds": ["FMA7131"]},
    "gallbladder": {"name": "胆囊", "conceptIds": ["FMA7202"]},
    "adrenal": {"name": "肾上腺", "conceptIds": ["FMA9604"]},
    "bladder": {"name": "膀胱", "conceptIds": ["FMA15900"]},
    "prostate": {"name": "前列腺", "conceptIds": ["FMA9600"]},
    "testis": {"name": "睾丸", "conceptIds": ["FMA7210"]},
    "skull": {"name": "颅骨", "conceptIds": ["FMA46565"]},
    "bone": {"name": "骨骼", "conceptIds": ["SKELETAL"]},
    "blood": {"name": "血液", "conceptIds": ["ALL"]},
    "whole_body": {"name": "全身", "conceptIds": ["ALL"]},
}

# 无法映射的部位兜底：全身
_DEFAULT_PART = {"name": "全身", "conceptIds": ["ALL"]}

# LLM 严重度判定进程内缓存：key = f"{model}|{part_key}|{指纹}" → (ts, severity, reason)
_SEVERITY_CACHE_TTL = 24 * 3600
_severity_cache: dict[str, tuple[float, str, str]] = {}


def clear_severity_cache() -> None:
    """清空 LLM 严重度缓存（测试隔离用）。"""
    _severity_cache.clear()


def _to_float(s) -> float | None:
    """宽松转 float：去掉数值前的单位符号与比较符（<1.70 / >1.0 等）。"""
    if s is None:
        return None
    try:
        return float(str(s).replace("↑", "").replace("↓", "").lstrip("<>=≤≥ \t"))
    except (TypeError, ValueError):
        return None


def _status(value_text: str, ref_low: str, ref_high: str, abnormal: bool = False) -> str:
    """根据参考区间给数值打状态标签（偏高/偏低/正常/异常）。

    参考区间字段存在两种存储格式：
      · 常规：ref_low=下限, ref_high=上限（如 3.9 / 6.1）
      · 单侧：上限可能以 '<5.2' 存进 ref_low，下限可能以 '>1.0' 存进 ref_high
    这里按前缀符号把「带 < 的 low」解释为上限、把「带 > 的 high」解释为下限。
    数值可解析时按参考区间判断；不可解析（定性结果）时以 abnormal 标记为准，
    避免「颜色 淡黄色」这类定性正常项被误标为异常。
    """
    v = _to_float(value_text)
    if v is None:
        return "异常" if abnormal else "正常"
    rl = str(ref_low).strip() if ref_low else ""
    rh = str(ref_high).strip() if ref_high else ""
    lo: float | None
    hi: float | None
    if rl.startswith(("<", "≤")):
        hi = _to_float(rl)          # 上限存进了 low 字段
        lo = _to_float(rh)
    elif rh.startswith((">", "≥")):
        lo = _to_float(rh)          # 下限存进了 high 字段
        hi = _to_float(rl)
    else:
        lo = _to_float(rl)
        hi = _to_float(rh)
    if hi is not None and v > hi:
        return "偏高"
    if lo is not None and v < lo:
        return "偏低"
    return "异常" if abnormal else "正常"


def _is_abnormal(metric) -> bool:
    """指标是否异常：数据库 abnormal 标记 或 数值超出参考区间。"""
    status = _status(metric.value_text, metric.ref_low, metric.ref_high, bool(metric.abnormal))
    return bool(metric.abnormal) or status in ("偏高", "偏低", "异常")


def _severity_label(count: int) -> str:
    """数量兜底规则：按该部位当前异常指标条数定严重等级。"""
    if count >= 3:
        return "severe"
    if count == 2:
        return "moderate"
    return "mild"


def _record_type(hospital: str, source_type: str) -> str:
    if source_type == "pdf":
        return "体检报告"
    if hospital:
        return "体检"
    return "检查"


def _range_text(ref_low, ref_high) -> str:
    return "".join(
        [
            str(ref_low) if ref_low else "",
            "~" if (ref_low and ref_high) else "",
            str(ref_high) if ref_high else "",
        ]
    )


def _range_note(ref_low, ref_high) -> str:
    return "".join(
        [
            f"（参考 {ref_low}" if ref_low else "",
            "-" if (ref_low and ref_high) else "",
            f"{ref_high}" if ref_high else "",
            "）" if (ref_low or ref_high) else "",
        ]
    )


# ── LLM 严重度判定 ──


async def _llm_available(session: AsyncSession) -> bool:
    """LLM 是否可用：模型管理启用了自定义模型（且配置了端点）。"""
    enabled = await crud.get_enabled_model(session)
    return enabled is not None and enabled.kind == "custom" and bool(enabled.base_url)


def _parse_severity(text: str) -> tuple[str | None, str | None]:
    """解析 LLM 返回的 JSON：{"severity": "severe|moderate|mild", "reason": "..."}。

    返回 (severity, reason)，解析失败或 severity 不在白名单 → (None, None)。
    """
    data: dict | None = None
    try:
        data = json.loads(text)
    except Exception:
        m = re.search(r"\{.*\}", text, re.S)
        if m:
            try:
                data = json.loads(m.group(0))
            except Exception:
                data = None
    if not isinstance(data, dict):
        return None, None
    sev = str(data.get("severity", "")).strip().lower()
    if sev not in ("severe", "moderate", "mild"):
        return None, None
    reason = str(data.get("reason", "")).strip()
    return sev, reason


async def _judge_part_severity(
    model: str,
    part_name: str,
    issues: list[dict],
    records_count: int,
) -> tuple[str | None, str | None]:
    """调用 LLM 综合判断部位严重程度。失败/超时由上层捕获，这里只负责组装与解析。"""
    lines = [
        f"{i}. {issue['name']} = {issue['value']}{issue['unit']}"
        f"（参考 {issue['range'] or '无参考区间'}）{issue['status']}"
        for i, issue in enumerate(issues, 1)
    ]
    user = (
        "请评估下面身体部位最近的异常指标严重程度。\n\n"
        f"部位：{part_name}\n"
        f"异常指标：\n{chr(10).join(lines)}\n"
        f"历史异常记录：{records_count} 次\n\n"
        "请只返回 JSON：\n"
        '{"severity": "severe" | "moderate" | "mild", "reason": "一句话中文理由"}\n'
        "severity 含义：severe=严重需尽快就医；moderate=中度需近期复查；mild=轻度可观察。"
    )
    messages = [
        {"role": "system", "content": "你是资深体检报告解读医生。只输出 JSON，不要输出其他文字。"},
        {"role": "user", "content": user},
    ]
    text = await llm.chat_text(model, messages, max_tokens=300, disable_thinking=True)
    return _parse_severity(text)


def _severity_cache_key(model: str, part_key: str, issues: list[dict]) -> str:
    """缓存键：模型 + 部位 + 异常指标指纹（指标数据变化自动失效）。"""
    payload = json.dumps(
        [
            {
                "n": i["name"],
                "v": i["value"],
                "u": i["unit"],
                "r": i["range"],
                "s": i["status"],
            }
            for i in issues
        ],
        ensure_ascii=False,
        sort_keys=True,
    )
    fp = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"{model}|{part_key}|{fp}"


async def build_body3d_overview(
    session: AsyncSession, mode: str = "abnormal", use_llm: bool | None = None
) -> dict:
    """聚合全部体检指标 → 3D 大屏部位列表。

    mode:
      - abnormal（默认）：只输出当前有异常指标的部位
      - all：输出全部可映射部位（含正常部位与暂无数据部位）
    use_llm:
      - None（默认）：自动探测 LLM 可用性
      - True/False：强制启用/禁用 LLM 严重度判定（测试用）
    """
    rows = await crud.list_all_metrics_with_exam(session)

    # 按 (部位, 指标名) 分组，每组只取最近一次体检的值作为「当前状态」，
    # 历史异常若最近已恢复正常（吃药治好等），不再计入当前异常。
    groups: dict[tuple[str, str], list] = {}
    for metric, exam_date, hospital, source_type in rows:
        bp = (metric.body_part or "").strip().lower()
        if not bp:
            continue
        groups.setdefault((bp, metric.name), []).append(
            (exam_date, metric, hospital, source_type)
        )

    parts: dict[str, dict] = {}
    for (bp, _name), items in groups.items():
        items.sort(key=lambda x: str(x[0] or ""), reverse=True)
        meta = BODY_PART_MAP.get(bp) or _DEFAULT_PART
        part = parts.setdefault(
            bp,
            {
                "name": meta["name"],
                "conceptIds": meta["conceptIds"],
                "issues": [],
                "record_map": {},
                "abnormal_count": 0,
            },
        )
        # 当前状态：最近一次体检的数值
        _latest_date, metric, hospital, source_type = items[0]
        status = _status(metric.value_text, metric.ref_low, metric.ref_high, bool(metric.abnormal))
        part["issues"].append(
            {
                "name": metric.name,
                "value": metric.value_text,
                "unit": metric.unit or "",
                "range": _range_text(metric.ref_low, metric.ref_high),
                "status": status,
            }
        )
        if _is_abnormal(metric):
            part["abnormal_count"] += 1
        # 时间线：保留全部历史异常记录（含已恢复正常的既往异常）
        for exam_date, m, hospital, source_type in items:
            if not _is_abnormal(m):
                continue
            rec = part["record_map"].setdefault(
                exam_date,
                {"date": exam_date, "type": _record_type(hospital, source_type), "summary": []},
            )
            rec["summary"].append(
                f"{m.name} {m.value_text}{m.unit}{_range_note(m.ref_low, m.ref_high)}"
            )

    if mode == "all":
        # 全部模式：补全所有可映射部位（即使暂无数据），让左栏清单完整
        for bp, meta in BODY_PART_MAP.items():
            if bp not in parts:
                parts[bp] = {
                    "name": meta["name"],
                    "conceptIds": meta["conceptIds"],
                    "issues": [],
                    "record_map": {},
                    "abnormal_count": 0,
                }

    # 探测 LLM 可用性（仅异常部位需要判定；探测失败视为不可用）
    if use_llm is None:
        try:
            use_llm = await _llm_available(session)
        except Exception:
            use_llm = False
    model: str | None = None
    if use_llm:
        try:
            model = await llm.resolve_model(session, None)
        except Exception:
            model = None

    out: list[dict] = []
    pending: list[tuple[int, str, list[dict]]] = []  # (out 下标, part_key, 异常指标)
    for key, part in parts.items():
        abnormal = part["abnormal_count"] > 0
        if mode == "abnormal" and not abnormal:
            continue
        issues = part["issues"]
        abnormal_issues = [i for i in issues if i["status"] in ("偏高", "偏低", "异常")]
        # 异常模式只列当前异常指标；全部模式列该部位所有指标
        shown_issues = abnormal_issues if mode == "abnormal" else issues
        if mode == "abnormal" and not shown_issues:
            shown_issues = issues
        records = [
            {
                "date": r["date"],
                "type": r["type"],
                "summary": "；".join(r["summary"]),
                "conclusion": "",
            }
            for r in sorted(part["record_map"].values(), key=lambda x: str(x["date"] or ""), reverse=True)
        ]
        if abnormal:
            note = (
                f"「{part['name']}」最近一次检查发现 {part['abnormal_count']} 项异常指标，"
                f"历史共 {len(part['record_map'])} 次检查留有异常记录，建议结合临床随诊复查。"
            )
        elif part["record_map"]:
            note = (
                f"「{part['name']}」既往 {len(part['record_map'])} 次检查曾发现异常，"
                f"最近一次已恢复正常，建议继续保持并定期复查。"
            )
        elif issues:
            note = f"「{part['name']}」最近一次检查共 {len(issues)} 项指标，均在参考区间内。"
        else:
            note = f"「{part['name']}」暂无体检指标数据，点击可查看该器官结构信息。"

        idx = len(out)
        out.append(
            {
                "key": key,
                "name": part["name"],
                "conceptIds": part["conceptIds"],
                "abnormal": abnormal,
                "severity": _severity_label(part["abnormal_count"]) if abnormal else None,
                "severity_reason": "",
                "issues": shown_issues,
                "records": records,
                "note": note,
            }
        )
        if abnormal and model is not None and abnormal_issues:
            pending.append((idx, key, abnormal_issues))

    # 并发 LLM 判定（命中缓存直接复用；失败保留数量兜底）
    if pending:
        results = await asyncio.gather(
            *[_judge_one(out, model, idx, key, issues) for idx, key, issues in pending],
            return_exceptions=True,
        )
        for r in results:
            if isinstance(r, BaseException):
                logger.warning("LLM 严重度判定失败，回退数量规则：%s", r)
            elif r:
                idx, severity, reason = r
                out[idx]["severity"] = severity
                out[idx]["severity_reason"] = reason

    # 按 body_part 权重排序（肾脏/心脏优先），同权重再按严重程度
    order = [
        "kidney", "heart", "liver", "blood", "lung", "stomach", "spleen",
        "pancreas", "brain", "trachea", "aorta", "esophagus", "gallbladder",
        "adrenal", "bladder", "prostate", "testis", "skull", "bone", "whole_body",
    ]
    sev_order = {"severe": 0, "moderate": 1, "mild": 2}
    out.sort(
        key=lambda p: (
            order.index(p["key"]) if p["key"] in order else 99,
            sev_order.get(p["severity"], 3),
        )
    )
    return out


async def _judge_one(
    out: list[dict],
    model: str,
    idx: int,
    key: str,
    issues: list[dict],
) -> tuple[int, str, str] | None:
    """对单个部位做 LLM 严重度判定；命中缓存直接返回，失败返回 None。"""
    ck = _severity_cache_key(model, key, issues)
    hit = _severity_cache.get(ck)
    if hit and time.time() - hit[0] < _SEVERITY_CACHE_TTL:
        return idx, hit[1], hit[2]
    try:
        sev, reason = await asyncio.wait_for(
            _judge_part_severity(model, out[idx]["name"], issues, len(out[idx]["records"])),
            timeout=20,
        )
    except Exception as e:
        logger.warning("LLM 严重度判定异常，回退数量规则：%s", e)
        return None
    if not sev:
        return None
    _severity_cache[ck] = (time.time(), sev, reason or "")
    return idx, sev, reason or ""