#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
核对体检图片中的指标数值：裁剪小区域 + RapidOCR 高倍放大重识别，
不把整张大图读入上下文，用于抽查 AI 结构化提取的疑似错误值。

用法（在 health-monitor 根目录运行）：
    health-env/Scripts/python.exe scripts/verify_values.py --exam-id 16 --metric "平均红细胞血红蛋白含量"
    health-env/Scripts/python.exe scripts/verify_values.py --exam-id 5 --metric "平均红细胞血红蛋白含量" --ascii
    # 不带参数：列出所有带「低置信度/待核实」标记或 abnormal 的指标，供人工挑选
    health-env/Scripts/python.exe scripts/verify_values.py --list-suspicious

实现：
1. 从 data/health.db 读取 exam 的 image_path（相对 uploads 根，实际在 data/uploads/ 下）
2. 对整页做一次 RapidOCR，拿到所有文本框坐标（只跑一次，之后只裁小块）
3. 定位指标名的文本框，向右找单位框，确定「值单元格」= 名称末尾 ~ 单位左缘
4. 把值单元格放大 8 倍 + 二值化，再 OCR 一次，打印「库中值 vs 重识别值」
5. 裁剪后的 PNG 存到 scripts/_verify/，可用 --ascii 在终端直接看字形

注意：
- 中科大血常规的右列指标（如 MCH）值会紧贴名称末尾，OCR 常把首位数并进汉字，
  重识别可能仍读成 "含量1.4"；此时用 --ascii 看像素字形即可确认（如 31.4 的 "3"）。
- 本脚本只读不写数据库，修改请走管理接口或直接改 metrics/extracted_json。
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys

sys.stdout.reconfigure(encoding="utf-8")

import cv2
from rapidocr_onnxruntime import RapidOCR

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "data", "health.db")
UPLOADS_ROOT = os.path.join(BASE_DIR, "data", "uploads")
VERIFY_DIR = os.path.join(BASE_DIR, "scripts", "_verify")

# 常见单位，用于在指标行右侧定位单位框
KNOWN_UNITS = (
    "g/L", "pg", "fL", "%", "10^9/L", "10^12/L", "109/L", "1012/L", "10%/L",
    "mmol/L", "umol/L", "umo1/L", "mg/L", "mg/g", "ml/min", "mmHg", "bpm", "个/ul", "/LP",
)

_OCR_ENGINE: RapidOCR | None = None


def get_engine() -> RapidOCR:
    global _OCR_ENGINE
    if _OCR_ENGINE is None:
        _OCR_ENGINE = RapidOCR()
    return _OCR_ENGINE


def ocr_full(image_path: str):
    """返回 [(x0,y0,x1,y1,text), ...] 按 y 再按 x 排序。"""
    res, _ = get_engine()(image_path)
    boxes = []
    if not res:
        return boxes
    for box, text, _score in res:
        xs = [p[0] for p in box]
        ys = [p[1] for p in box]
        boxes.append((int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys)), text.strip()))
    boxes.sort(key=lambda b: (b[1], b[0]))
    return boxes


def find_metric_box(boxes, metric_name: str):
    """找包含指标名的文本框；返回 (x0,y0,x1,y1,text) 或 None。"""
    # 先精确匹配，再允许名称前有 * 号
    for b in boxes:
        if metric_name in b[4]:
            return b
    return None


def find_unit_box(boxes, name_box, row_tol=25):
    """在名称框右侧、同一行内找单位框。返回单位框 x0 或 None。"""
    nx0, ny0, nx1, ny1, _ = name_box
    candidates = []
    for b in boxes:
        if b[0] < nx1:  # 单位在名称右侧
            continue
        if abs(b[1] - ny0) > row_tol and abs(b[3] - ny1) > row_tol:
            continue
        # 行重叠
        if b[3] < ny0 or b[1] > ny1:
            continue
        for u in KNOWN_UNITS:
            if u in b[4]:
                candidates.append((b[0], b))
                break
    candidates.sort()
    return candidates[0][1] if candidates else None


def crop_value_cell(img, name_box, unit_box, pad_left=90, pad_right=6):
    """值单元格：名称右缘往左 pad_left（捕捉贴名首位数）~ 单位左缘往右 pad_right。"""
    nx0, ny0, nx1, ny1, _ = name_box
    x0 = max(0, nx1 - pad_left)
    x1 = unit_box[0] + pad_right if unit_box else min(img.shape[1], nx1 + 60)
    y0 = max(0, ny0 - 6)
    y1 = min(img.shape[0], ny1 + 6)
    return img[y0:y1, x0:x1], (x0, y0, x1, y1)


def reocr_crop(crop, scale=8, thresh=True):
    """把裁剪区域放大后重识别，返回识别文本列表。"""
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.ndim == 3 else crop
    big = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    if thresh:
        _, big = cv2.threshold(big, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    res, _ = get_engine()(big)
    if not res:
        return []
    return [t.strip() for _b, t, _s in res]


def ascii_render(crop, max_width=100):
    """把裁剪区域转成终端 ASCII 字形，便于直接看数字形状（不加载大图）。"""
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.ndim == 3 else crop
    _, th = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    h, w = th.shape
    # 等比例缩到 max_width 以内（按列抽样）
    step_c = max(1, w // max_width)
    print(f"  (值单元格 {w}x{h}px，ASCII 抽样 {step_c}px/列)")
    for r in range(0, h, 2):
        row = ""
        for c in range(0, w, step_c):
            dark = (th[r : r + 2, c : c + step_c] < 128).any()
            row += "#" if dark else " "
        print(row.rstrip())


def verify_one(exam_id: int, metric_name: str, ascii_flag: bool, scale: int):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT image_path FROM exams WHERE id=?", (exam_id,))
    row = cur.fetchone()
    if not row:
        print(f"  [跳过] exam {exam_id} 不存在")
        return
    cur.execute(
        "SELECT value_text, unit, ref_low, ref_high, abnormal FROM metrics "
        "WHERE exam_id=? AND name=?",
        (exam_id, metric_name),
    )
    m = cur.fetchone()
    conn.close()

    rel = row["image_path"].lstrip("/")
    if rel.startswith("uploads/"):
        img_path = os.path.join(UPLOADS_ROOT, rel[len("uploads/") :])
    else:
        img_path = os.path.join(UPLOADS_ROOT, rel)
    if not os.path.exists(img_path):
        print(f"  [跳过] 图片不存在 {img_path}")
        return

    print(f"===== exam {exam_id}: {metric_name} =====")
    print(f"  图片: {rel}")
    if m:
        flag = "⚠️异常" if m["abnormal"] else ""
        print(f"  库中值: {m['value_text']} {m['unit']}  参考 {m['ref_low']}-{m['ref_high']} {flag}")
    else:
        print("  库中值: (未提取到该指标)")

    boxes = ocr_full(img_path)
    name_box = find_metric_box(boxes, metric_name)
    if not name_box:
        print("  [失败] 整页 OCR 未找到指标名，无法定位。")
        return
    unit_box = find_unit_box(boxes, name_box)
    img = cv2.imread(img_path)
    if img is None:
        print(f"  [失败] cv2 无法读取 {img_path}")
        return
    crop, (x0, y0, x1, y1) = crop_value_cell(img, name_box, unit_box)
    os.makedirs(VERIFY_DIR, exist_ok=True)
    out_png = os.path.join(VERIFY_DIR, f"exam{exam_id}_{metric_name}.png")
    cv2.imwrite(out_png, crop)
    print(f"  名称框: {name_box[0]},{name_box[1]}-{name_box[2]},{name_box[3]}  {name_box[4]!r}")
    print(f"  值单元格: x[{x0},{x1}] y[{y0},{y1}]  单位框: {unit_box[4] if unit_box else None!r}")
    texts = reocr_crop(crop, scale=scale)
    print(f"  重识别({scale}x): {texts if texts else '(无文本)'}")
    print(f"  裁剪图已存: {out_png}")
    if ascii_flag:
        ascii_render(crop)


def list_suspicious():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    print("== 带「待核实」标记的指标 ==")
    cur.execute(
        "SELECT exam_id, name, value_text, unit FROM metrics WHERE note LIKE '%待核实%' OR note LIKE '%低置信度%' ORDER BY exam_id"
    )
    for r in cur.fetchall():
        print(f"  exam {r[0]:>3}  {r[1]} = {r[2]} {r[3]}")
    print()
    print("== 全部 abnormal 指标 ==")
    cur.execute(
        "SELECT exam_id, name, value_text, unit, ref_low, ref_high FROM metrics WHERE abnormal=1 ORDER BY exam_id"
    )
    for r in cur.fetchall():
        print(f"  exam {r[0]:>3}  {r[1]} = {r[2]} {r[3]}  参考 {r[4]}-{r[5]}")
    conn.close()


def main():
    ap = argparse.ArgumentParser(description="裁剪小区域 + RapidOCR 核对指标数值")
    ap.add_argument("--exam-id", type=int, help="体检记录 id")
    ap.add_argument("--metric", action="append", help="指标名，可多次传")
    ap.add_argument("--scale", type=int, default=8, help="放大倍数（默认 8）")
    ap.add_argument("--ascii", action="store_true", help="同时输出值单元格的 ASCII 字形")
    ap.add_argument("--list-suspicious", action="store_true", help="列出待核实/异常指标")
    args = ap.parse_args()

    if args.list_suspicious:
        list_suspicious()
        return
    if not args.exam_id:
        ap.error("需要 --exam-id")
    metrics = args.metric or [""]
    for name in metrics:
        verify_one(args.exam_id, name, args.ascii, args.scale)
        print()


if __name__ == "__main__":
    main()