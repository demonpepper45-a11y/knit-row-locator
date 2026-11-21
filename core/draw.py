"""绘制工具：中文文字、半透明色块、网格与标记。

OpenCV 的 ``putText`` 不支持中文，因此文字统一先转成 PIL 绘制一次再转回，
避免每个标签单独转换。所有颜色参数均为 BGR。
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

_FONT_CANDIDATES = (
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\msyhbd.ttc",
    r"C:\Windows\Fonts\simhei.ttf",
    r"C:\Windows\Fonts\simsun.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/System/Library/Fonts/PingFang.ttc",
)


@lru_cache(maxsize=64)
def _load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = list(_FONT_CANDIDATES)
    if bold:
        candidates.insert(0, r"C:\Windows\Fonts\msyhbd.ttc")
    for candidate in candidates:
        if Path(candidate).exists():
            try:
                return ImageFont.truetype(candidate, size=size)
            except OSError:
                continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # 旧版 Pillow
        return ImageFont.load_default()


def bgr_to_pil(image: np.ndarray) -> Image.Image:
    return Image.fromarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))


def pil_to_bgr(image: Image.Image) -> np.ndarray:
    return cv2.cvtColor(np.asarray(image.convert("RGB")), cv2.COLOR_RGB2BGR)


def draw_texts(
    image: np.ndarray,
    items: list[tuple[str, tuple[float, float], tuple[int, int, int], int, str]],
    *,
    bold: bool = False,
) -> np.ndarray:
    """批量绘制文字。

    ``items`` 每项为 ``(文本, (x, y), BGR 颜色, 字号, PIL anchor)``。
    """
    if not items:
        return image
    pil = bgr_to_pil(image)
    draw = ImageDraw.Draw(pil)
    for text, xy, color, size, anchor in items:
        font = _load_font(int(size), bold)
        rgb = (int(color[2]), int(color[1]), int(color[0]))
        draw.text((float(xy[0]), float(xy[1])), text, font=font, fill=rgb, anchor=anchor)
    return pil_to_bgr(pil)


def fill_polygon_alpha(
    image: np.ndarray,
    points: np.ndarray,
    color: tuple[int, int, int],
    alpha: float,
) -> np.ndarray:
    pts = np.asarray(points, dtype=np.int32).reshape(-1, 1, 2)
    overlay = image.copy()
    cv2.fillPoly(overlay, [pts], color)
    return cv2.addWeighted(overlay, alpha, image, 1 - alpha, 0)


def fill_rect_alpha(
    image: np.ndarray,
    rect: tuple[float, float, float, float],
    color: tuple[int, int, int],
    alpha: float,
) -> np.ndarray:
    x0, y0, x1, y1 = (int(round(v)) for v in rect)
    overlay = image.copy()
    cv2.rectangle(overlay, (x0, y0), (x1 - 1, y1 - 1), color, -1)
    return cv2.addWeighted(overlay, alpha, image, 1 - alpha, 0)


def draw_dashed_line(
    image: np.ndarray,
    p0: tuple[float, float],
    p1: tuple[float, float],
    color: tuple[int, int, int],
    thickness: int = 2,
    dash: int = 8,
) -> np.ndarray:
    p0 = np.asarray(p0, dtype=float)
    p1 = np.asarray(p1, dtype=float)
    length = float(np.linalg.norm(p1 - p0))
    if length < 1:
        return image
    direction = (p1 - p0) / length
    step = 0.0
    while step < length:
        a = p0 + direction * step
        b = p0 + direction * min(length, step + dash)
        cv2.line(image, tuple(np.round(a).astype(int)), tuple(np.round(b).astype(int)), color, thickness, cv2.LINE_AA)
        step += dash * 2
    return image


def draw_arrow(
    image: np.ndarray,
    start: tuple[float, float],
    end: tuple[float, float],
    color: tuple[int, int, int],
    thickness: int = 3,
) -> np.ndarray:
    cv2.arrowedLine(
        image,
        tuple(np.round(start).astype(int)),
        tuple(np.round(end).astype(int)),
        color,
        thickness,
        cv2.LINE_AA,
        tipLength=0.18,
    )
    return image
