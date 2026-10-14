# -*- coding: utf-8 -*-
"""生成缩略图（供人工查看）+ 对疑似模糊页跑 RapidOCR，判断是否影响可读性。"""
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

RENDER = Path(r"e:\nasvpn\health-monitor\data\uploads\inbox\_rendered")
THUMBS = RENDER / "thumbs"
THUMBS.mkdir(exist_ok=True)

# 疑似偏模糊页（基于拉普拉斯方差 < 210）
SUSPECT = [
    ("扫描全能王 2026-10-12 18.56", "p06"),
    ("扫描全能王 2026-10-12 18.58", "p02"),
    ("扫描全能王 2026-10-12 18.58", "p05"),
    ("扫描全能王 2026-10-12 18.58", "p06"),
    ("扫描全能王 2026-10-12 18.58", "p07"),
    ("扫描全能王 2026-10-12 18.58", "p11"),
    ("扫描全能王 2026-10-12 18.58", "p14"),
]


def make_thumb(png: Path, width: int = 640) -> Path:
    out = THUMBS / f"{png.parent.name}_{png.stem}.jpg"
    if out.exists():
        return out
    img = Image.open(png)
    ratio = width / img.width
    img = img.resize((width, int(img.height * ratio)), Image.LANCZOS)
    img.convert("RGB").save(out, quality=70)
    return out


def main() -> None:
    from rapidocr_onnxruntime import RapidOCR
    ocr = RapidOCR()

    for doc, page in SUSPECT:
        png = RENDER / doc / f"{page}.png"
        if not png.exists():
            continue
        thumb = make_thumb(png)
        print(f"\n### {doc} / {page}  thumb={thumb}")

        img = cv2.imdecode(np.fromfile(str(png), dtype=np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            print("  读取失败")
            continue
        result, _ = ocr(img)
        if not result:
            print("  OCR: 无结果")
            continue
        texts = [r[1] for r in result]
        joined = " | ".join(texts)
        print(f"  OCR字符数: {len(joined)}")
        print(f"  OCR前200字: {joined[:200]}")
        # 检查是否含数字与单位（指标识别的基础）
        import re
        nums = re.findall(r"\d+(?:\.\d+)?", joined)
        print(f"  数字数量: {len(nums)}  示例: {nums[:10]}")


if __name__ == "__main__":
    main()