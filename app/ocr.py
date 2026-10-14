# ===============================================================
# 文件: ocr.py
# 项目: 健康数据监控（health-monitor）
# 说明: RapidOCR 本地识别（onnxruntime），不依赖外部服务
# ===============================================================
import logging

import numpy as np

logger = logging.getLogger(__name__)

# 引擎懒加载单例（RapidOCR 首次调用加载模型，约几百 ms）
_engine = None


def _get_engine():
    global _engine
    if _engine is None:
        from rapidocr_onnxruntime import RapidOCR

        _engine = RapidOCR()
    return _engine


def ocr_image_bytes(data: bytes) -> str:
    """对图片字节执行 OCR，返回按行拼接的文本（空图/失败返回 ""）。

    必须在线程池中调用（RapidOCR 为同步 CPU 推理，会阻塞事件循环）。
    """
    if not data:
        return ""
    import cv2

    arr = np.frombuffer(data, np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        logger.warning("OCR 输入不是可解码图片（长度 %d）", len(data))
        return ""
    try:
        result, _elapse = _get_engine()(img)
    except Exception:
        logger.exception("OCR 识别失败")
        return ""
    if not result:
        return ""
    lines = []
    for item in result:
        # item = [box(4点), text, score]
        text = str(item[1]).strip()
        if text:
            lines.append(text)
    return "\n".join(lines)