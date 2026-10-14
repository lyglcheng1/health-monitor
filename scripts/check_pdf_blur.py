# -*- coding: utf-8 -*-
"""检查 PDF 拍照报告清晰度：逐页渲染 PNG + 拉普拉斯方差评估。
输出: 每页清晰度分数；低分页提醒重新上传。
"""
import sys
from pathlib import Path

import cv2
import fitz  # PyMuPDF
import numpy as np

SRC_DIR = Path(r"e:\nasvpn\health-monitor\data\uploads\inbox\CamScanner")
OUT_DIR = Path(r"e:\nasvpn\health-monitor\data\uploads\inbox\_rendered")
OUT_DIR.mkdir(parents=True, exist_ok=True)

ZOOM = 200 / 72  # 200 DPI


def variance_of_laplacian(gray: np.ndarray) -> float:
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def level(score: float) -> tuple[str, str]:
    if score < 60:
        return "❌ 很模糊", "red"
    if score < 110:
        return "⚠ 模糊", "yellow"
    if score < 200:
        return "◐ 偏模糊", "yellow"
    return "✅ 清晰", "green"


def main() -> None:
    pdfs = sorted(SRC_DIR.glob("*.pdf"))
    if not pdfs:
        print("未找到 PDF")
        return

    for pdf in pdfs:
        doc = fitz.open(pdf)
        print(f"\n=== {pdf.name} （{len(doc)} 页）===")
        out_sub = OUT_DIR / pdf.stem
        out_sub.mkdir(parents=True, exist_ok=True)
        for i, page in enumerate(doc):
            pix = page.get_pixmap(matrix=fitz.Matrix(ZOOM, ZOOM))
            png = out_sub / f"p{i + 1:02d}.png"
            pix.save(png)
            # Windows 中文路径需 imdecode 读取
            img = cv2.imdecode(np.fromfile(str(png), dtype=np.uint8), cv2.IMREAD_COLOR)
            if img is None:
                print(f"  p{i+1:02d}: 读取失败")
                continue
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            score = variance_of_laplacian(gray)
            tag, _ = level(score)
            print(f"  p{i+1:02d}: score={score:7.1f}  {tag}  ({png.stat().st_size//1024}KB)")
        doc.close()


if __name__ == "__main__":
    sys.exit(main())