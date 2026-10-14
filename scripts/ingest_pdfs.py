# -*- coding: utf-8 -*-
"""批量入库官方 PDF 体检报告。

流程：读取 inbox/_rendered/{doc}/*.png（PyMuPDF 已渲染的高清页）→
  RapidOCR 逐页识别 → 每页创建一条 Exam 记录（含 OCR 文本 + 页面图片）→
  后续 LLM 提取指标时再回填 extracted_json/metrics。

说明：
- 按「一张图片（扫描页）= 一条体检记录」的既有数据模型，每页一条记录。
- exam_date 逐页解析：门诊病历取「就诊时间」，检验报告单取「采集」日期，
  失败则回落到整份文档解析出的日期 / 文件名日期。
- 同一 PDF 内像素完全相同的重复页自动去重（如连云港 20260930 的 p05=p07）。
- 中科大医院(1).pdf 是 中科大医院.pdf 的子集，默认跳过。

用法：
  python scripts/ingest_pdfs.py --dry-run   # 只 OCR 并打印，不写库
  python scripts/ingest_pdfs.py               # OCR 并写入数据库
"""
import argparse
import asyncio
import hashlib
import re
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

RENDER_DIR = Path(BASE_DIR) / "data" / "uploads" / "inbox" / "_rendered"
UPLOADS_DIR = Path(BASE_DIR) / "data" / "uploads"
OCR_DUMP_DIR = Path(BASE_DIR) / "data" / "uploads" / "inbox" / "_ocr"

# 参与入库的 PDF（官方清晰件）。扫描全能王等待重拍后另批处理。
TARGETS = [
    "中科大医院",
    "连云港一院20260731",
    "连云港第一人民医院20260930检查",
]

# 整份文档兜底日期（逐页解析失败时用）
FALLBACK_DATE = {
    "连云港一院20260731": "2026-07-31",
    "连云港第一人民医院20260930检查": "2026-09-30",
}

# 医院（整份文档统一）
HOSPITAL = {
    "中科大医院": "中国科学技术大学附属第一医院（安徽省立医院南区）",
    "连云港一院20260731": "连云港市第一人民医院",
    "连云港第一人民医院20260930检查": "连云港市第一人民医院",
}

_DATE_RE = re.compile(r"(\d{4})\s*[年/\-.]\s*(\d{1,2})\s*[月/\-.]\s*(\d{1,2})\s*日?")
_VISIT_RE = re.compile(r"就诊时间[:：]\s*(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日")
_COLLECT_RE = re.compile(r"采集[:：]\s*(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})")
_REPORT_RE = re.compile(r"报告[:：]\s*(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})")
_HOSPITAL_RE = re.compile(r"([一-鿿]{2,25}?(?:医院|卫生院|医疗中心|附属医院))")


def _fmt_date(y: int, m: int, d: int) -> str | None:
    if not (2000 <= y <= 2100 and 1 <= m <= 12 and 1 <= d <= 31):
        return None
    return f"{y:04d}-{m:02d}-{d:02d}"


def _match_date(m: re.Match) -> str | None:
    return _fmt_date(int(m.group(1)), int(m.group(2)), int(m.group(3)))


def parse_exam_date(text: str) -> str | None:
    """逐页解析日期：门诊病历取就诊时间，检验单取采集日期，再回落通用日期。"""
    for pat in (_VISIT_RE, _COLLECT_RE, _REPORT_RE):
        m = pat.search(text)
        if m:
            d = _match_date(m)
            if d:
                return d
    m = _DATE_RE.search(text)
    if m:
        return _match_date(m)
    return None


def page_type(text: str) -> str:
    """识别页面类型（用于 note 标注）。"""
    if "门诊病历" in text:
        return "门诊病历"
    if "指引单" in text:
        return "检验指引单"
    if "检验报告单" in text:
        return "检验报告单"
    return "报告页"


def page_md5(png: Path) -> str:
    return hashlib.md5(png.read_bytes()).hexdigest()


def unique_pages(doc: str) -> list[Path]:
    """返回去重后的页面 PNG 列表（按页序）。"""
    sub = RENDER_DIR / doc
    if not sub.is_dir():
        print(f"  [跳过] 未找到渲染目录: {sub}")
        return []
    pages = sorted(sub.glob("p*.png"))
    seen: set[str] = set()
    out: list[Path] = []
    for p in pages:
        h = page_md5(p)
        if h in seen:
            print(f"  [去重] {p.name} 与之前的页像素重复，跳过")
            continue
        seen.add(h)
        out.append(p)
    return out


async def ingest(dry_run: bool) -> None:
    from app import ocr
    from app.db import SessionLocal
    from app.models import Exam

    session = SessionLocal() if not dry_run else None
    try:
        for doc in TARGETS:
            pages = unique_pages(doc)
            if not pages:
                continue
            print(f"\n===== {doc}（{len(pages)} 个唯一页）=====")

            hospital = HOSPITAL.get(doc, "")
            combined_parts: list[str] = []
            for png in pages:
                text = ocr.ocr_image_bytes(png.read_bytes()) or ""
                combined_parts.append(f"---- {png.name} ----\n{text}")
            combined = "\n".join(combined_parts)
            doc_date = parse_exam_date(combined) or FALLBACK_DATE.get(doc, "")

            OCR_DUMP_DIR.mkdir(parents=True, exist_ok=True)
            (OCR_DUMP_DIR / f"{doc}.txt").write_text(combined, encoding="utf-8")

            for i, png in enumerate(pages, start=1):
                text = ocr.ocr_image_bytes(png.read_bytes()) or ""
                exam_date = parse_exam_date(text) or doc_date
                ptype = page_type(text)
                source = f"{doc}.pdf 第{i}/{len(pages)}页（{ptype}）"
                note = f"来源：{source}"
                # p03/p09 疑似同一份门诊病历的两次扫描，note 里提醒
                if doc == "中科大医院" and png.name == "p09.png":
                    note += "；疑似与 p03 重复，可删除"

                if dry_run:
                    head = text.split("\n", 1)[1][:120] if "\n" in text else text[:120]
                    print(f"  {png.name} 日期={exam_date} 类型={ptype}")
                    print(f"    {head!r}")
                    continue

                exam = Exam(
                    exam_date=exam_date,
                    hospital=hospital,
                    source_type="image",
                    note=note,
                    source=source,
                    image_path="",
                    ocr_text=text,
                )
                session.add(exam)
                await session.flush()
                out_dir = UPLOADS_DIR / str(exam.id)
                out_dir.mkdir(parents=True, exist_ok=True)
                out_path = out_dir / png.name
                out_path.write_bytes(png.read_bytes())
                exam.image_path = f"uploads/{exam.id}/{png.name}"
                print(f"  已入库 id={exam.id} {png.name} {exam_date} → {exam.image_path}")

            if not dry_run:
                await session.commit()
                print(f"  [完成] {doc}: {len(pages)} 条记录已提交")
    except Exception:
        if session is not None:
            await session.rollback()
        raise
    finally:
        if session is not None:
            await session.close()


def main() -> None:
    # Windows 控制台默认 GBK，强制 UTF-8 避免中文输出乱码
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="只 OCR 并打印，不写库")
    args = parser.parse_args()
    asyncio.run(ingest(dry_run=args.dry_run))


if __name__ == "__main__":
    main()