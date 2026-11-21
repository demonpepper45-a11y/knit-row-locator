"""图像读写工具（Windows 中文路径安全）。"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np


class ImageInputError(ValueError):
    """图片无法读取或格式不受支持。消息面向最终用户。"""


def load_image(path: str | Path) -> np.ndarray:
    """读取图片为 BGR 数组；支持中文/空格路径。"""
    path = Path(path)
    if not path.exists():
        raise ImageInputError(f"找不到图片：{path}")
    data = np.fromfile(str(path), dtype=np.uint8)
    if data.size == 0:
        raise ImageInputError(f"图片文件为空：{path}")
    return decode_image_bytes(data.tobytes(), source=path.name)


def decode_image_bytes(data: bytes, *, source: str = "上传的图片") -> np.ndarray:
    """把 PNG/JPEG 字节解码为 BGR 数组。"""
    if not data:
        raise ImageInputError(f"{source}为空。")
    buf = np.frombuffer(data, dtype=np.uint8)
    image = cv2.imdecode(buf, cv2.IMREAD_COLOR)
    if image is None:
        raise ImageInputError(
            f"无法解码{source}：请确认文件是 PNG 或 JPEG，且没有损坏。"
        )
    return ensure_bgr(image)


def ensure_bgr(image: np.ndarray) -> np.ndarray:
    """把灰度/BGRA/普通 BGR 统一成 3 通道 BGR uint8。"""
    arr = np.asarray(image)
    if arr.ndim == 2:
        arr = cv2.cvtColor(arr, cv2.COLOR_GRAY2BGR)
    elif arr.ndim == 3 and arr.shape[2] == 4:
        arr = cv2.cvtColor(arr, cv2.COLOR_BGRA2BGR)
    elif arr.ndim == 3 and arr.shape[2] == 3:
        pass
    else:
        raise ImageInputError(f"不支持的图像形状：{arr.shape}，需要灰度、BGR 或 BGRA。")
    if arr.dtype != np.uint8:
        arr = np.clip(arr, 0, 255).astype(np.uint8)
    return np.ascontiguousarray(arr)


def encode_png(image: np.ndarray) -> bytes:
    ok, buf = cv2.imencode(".png", ensure_bgr(image))
    if not ok:
        raise ImageInputError("PNG 编码失败。")
    return buf.tobytes()


def to_rgb(image: np.ndarray) -> np.ndarray:
    """BGR → RGB，供 Streamlit / PIL 显示。"""
    return cv2.cvtColor(ensure_bgr(image), cv2.COLOR_BGR2RGB)
