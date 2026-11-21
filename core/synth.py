"""确定性合成素材：用于演示与自动化测试。

所有随机性均来自 ``numpy.random.default_rng(seed)``，同样的参数会生成完全
相同的图片，便于验收复现。素材为程序生成的合成织片，不是实拍照片。
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from .color import bgr_to_lab, separation, two_means
from .types import ChartGrid

DEFAULT_PALETTE: tuple[tuple[int, int, int], tuple[int, int, int]] = (
    (74, 104, 78),  # 深绿（BGR）
    (235, 232, 222),  # 米白（BGR）
)


def _ensure_unique_window(cells: np.ndarray, start: int, height: int) -> bool:
    window = cells[start : start + height]
    swapped = 1 - window
    for other in range(0, cells.shape[0] - height + 1):
        if other == start:
            continue
        candidate = cells[other : other + height]
        if np.array_equal(candidate, window) or np.array_equal(candidate, swapped):
            return False
    return True


def make_unique_chart(
    *,
    rows: int = 32,
    cols: int = 12,
    window_start: int = 18,
    window_height: int = 5,
    seed: int = 20261121,
    dark_ratio: float = 0.45,
) -> np.ndarray:
    """生成一个双色图解，使指定 5 行窗口在整张图中唯一（含互换颜色）。"""
    rng = np.random.default_rng(seed)
    for _ in range(200):
        cells = (rng.random((rows, cols)) < dark_ratio).astype(np.int8)
        if _ensure_unique_window(cells, window_start, window_height):
            return cells
    raise RuntimeError("无法生成唯一窗口的图解，请调整行列数或随机种子。")


def make_periodic_chart(
    *,
    rows: int = 32,
    cols: int = 12,
    period: int = 8,
    seed: int = 20261122,
) -> np.ndarray:
    """生成每 ``period`` 行重复一次的图解，并保证基本周期确为 ``period``。"""
    if rows % period != 0:
        raise ValueError("行数必须是周期的整数倍，方便演示重复花纹。")
    rng = np.random.default_rng(seed)
    for _ in range(200):
        base = (rng.random((period, cols)) < 0.5).astype(np.int8)
        ok = True
        for divisor in range(1, period):
            if period % divisor == 0 and np.array_equal(base[: period - divisor], base[divisor:]):
                ok = False
                break
        if ok:
            return np.tile(base, (rows // period, 1))
    raise RuntimeError("无法生成基本周期正确的重复图解。")


def render_chart_image(
    cells: np.ndarray,
    *,
    palette: tuple[tuple[int, int, int], tuple[int, int, int]] = DEFAULT_PALETTE,
    cell_px: int = 26,
    margin: int = 26,
    grid_px: int = 2,
    background: tuple[int, int, int] = (248, 248, 248),
    grid_color: tuple[int, int, int] = (198, 198, 198),
) -> tuple[np.ndarray, tuple[float, float, float, float]]:
    """把内部顺序的矩阵渲染成带外边距和网格线的图解 PNG。

    返回 ``(BGR 图像, rect)``；rect 是网格外边界 ``(x0, y0, x1, y1)``，
    可直接传给 :func:`core.chart.read_chart`。
    """
    cells = np.asarray(cells, dtype=np.int8)
    rows, cols = cells.shape
    width = margin * 2 + cols * cell_px
    height = margin * 2 + rows * cell_px
    image = np.full((height, width, 3), background, dtype=np.uint8)
    visual = cells[::-1]
    for v in range(rows):
        for c in range(cols):
            x0 = margin + c * cell_px
            y0 = margin + v * cell_px
            cv2.rectangle(
                image,
                (x0, y0),
                (x0 + cell_px - 1, y0 + cell_px - 1),
                palette[int(visual[v, c])],
                -1,
            )
    for c in range(cols + 1):
        x = margin + c * cell_px
        cv2.line(image, (x, margin), (x, margin + rows * cell_px), grid_color, grid_px)
    for v in range(rows + 1):
        y = margin + v * cell_px
        cv2.line(image, (margin, y), (margin + cols * cell_px, y), grid_color, grid_px)
    rect = (
        float(margin),
        float(margin),
        float(margin + cols * cell_px),
        float(margin + rows * cell_px),
    )
    return image, rect


def _shade(color: tuple[int, int, int], factor: float) -> tuple[int, int, int]:
    return tuple(int(np.clip(round(channel * factor), 0, 255)) for channel in color)


def _draw_stitch(
    image: np.ndarray,
    x0: int,
    y0: int,
    size: int,
    color: tuple[int, int, int],
    rng: np.random.Generator,
) -> None:
    cv2.rectangle(image, (x0, y0), (x0 + size - 1, y0 + size - 1), color, -1)
    dark = _shade(color, 0.70)
    darker = _shade(color, 0.55)
    light = _shade(color, 1.13)

    cx = x0 + size * 0.5
    cy = y0 + size * 0.54
    half_w = size * 0.37
    half_h = size * 0.43
    left = (int(round(cx - half_w)), int(round(cy - half_h * 0.75)))
    bottom = (int(round(cx)), int(round(cy + half_h)))
    right = (int(round(cx + half_w)), int(round(cy - half_h * 0.75)))
    thickness = max(2, int(round(size * 0.085)))
    points = np.array([left, bottom, right], dtype=np.int32)
    cv2.polylines(image, [points], False, dark, thickness, cv2.LINE_AA)
    highlight = points + np.array([0, -max(2, int(size * 0.07))], dtype=np.int32)
    cv2.polylines(image, [highlight], False, light, max(1, thickness - 1), cv2.LINE_AA)

    # 相邻针目之间的竖向连接，形成平针的“锁链”观感
    side_x = (int(round(cx - half_w * 1.05)), int(round(cx + half_w * 1.05)))
    for sx in side_x:
        cv2.line(
            image,
            (sx, int(round(cy - half_h * 0.55))),
            (sx, int(round(cy + half_h * 0.55))),
            darker,
            max(1, thickness - 1),
            cv2.LINE_AA,
        )

    # 细小纤维/绒毛
    for _ in range(6):
        fx = int(rng.integers(x0 + 2, x0 + size - 2))
        fy = int(rng.integers(y0 + 2, y0 + size - 2))
        dx = int(rng.integers(-3, 4))
        dy = int(rng.integers(-3, 4))
        jitter = int(rng.integers(-14, 15))
        fiber = tuple(int(np.clip(channel + jitter, 0, 255)) for channel in color)
        cv2.line(image, (fx, fy), (fx + dx, fy + dy), fiber, 1, cv2.LINE_AA)


@dataclass(frozen=True)
class SynthPhoto:
    image: np.ndarray
    corners: np.ndarray
    start_row: int
    rows: int
    stitches: int
    seed: int


def render_photo(
    chart: ChartGrid,
    start_row: int,
    rows: int,
    *,
    seed: int = 7,
    palette: tuple[tuple[int, int, int], tuple[int, int, int]] | None = None,
    cell: int = 46,
    margin: int = 46,
    top_extra: int = 110,
    blur_sigma: float = 0.55,
    noise_sigma: float = 3.0,
    perspective: float = 1.0,
    contrast_scale: float = 1.0,
) -> SynthPhoto:
    """渲染“织片正面照”：平针纹理、织针在上、轻微透视、噪声与光照。"""
    cells = chart.cells
    chart_rows, cols = cells.shape
    if start_row < 0 or start_row + rows > chart_rows:
        raise ValueError("start_row 超出图解范围。")
    palette = palette or chart.palette
    palette = tuple(tuple(int(v) for v in color) for color in palette)
    if contrast_scale != 1.0:
        mean = np.mean(np.array(palette, dtype=np.float64), axis=0)
        palette = tuple(
            tuple(int(round(v)) for v in np.clip(mean + (np.array(color, dtype=np.float64) - mean) * contrast_scale, 0, 255))
            for color in palette
        )

    rng = np.random.default_rng(seed)
    fabric_w = cols * cell
    fabric_h = rows * cell
    canvas_w = fabric_w + margin * 2
    canvas_h = fabric_h + top_extra + margin * 2
    fx = margin
    fy = top_extra + margin

    # 桌面/背景：低对比度布料纹理
    base = np.array([206, 201, 196], dtype=np.float64)
    yy, xx = np.mgrid[0:canvas_h, 0:canvas_w]
    low_freq = rng.normal(0, 6, size=(canvas_h // 8 + 2, canvas_w // 8 + 2)).astype(np.float32)
    low_freq = cv2.resize(low_freq, (canvas_w, canvas_h), interpolation=cv2.INTER_CUBIC)
    background = base[None, None, :] + low_freq[..., None] * 0.8
    background = np.clip(background, 0, 255).astype(np.uint8)
    canvas = np.ascontiguousarray(background)

    # 织片投影
    cv2.rectangle(
        canvas,
        (fx - 5, fy - 4),
        (fx + fabric_w + 6, fy + fabric_h + 9),
        (120, 118, 115),
        -1,
    )
    canvas = cv2.GaussianBlur(canvas, (0, 0), 5)
    cv2.rectangle(
        canvas,
        (fx - 1, fy - 1),
        (fx + fabric_w + 1, fy + fabric_h + 1),
        (150, 148, 145),
        -1,
    )

    # 织物格与针目纹理：屏幕最上面一行 = 图解最后一行
    for sr in range(rows):
        internal_row = start_row + (rows - 1 - sr)
        for c in range(cols):
            color = palette[int(cells[internal_row, c])]
            x0 = fx + c * cell
            y0 = fy + sr * cell
            _draw_stitch(canvas, x0, y0, cell, color, rng)

    # 织针（在选区上方）
    metal = (188, 193, 198)
    for offset in (20, 43):
        y = fy - offset
        cv2.line(canvas, (fx - 34, y), (fx + fabric_w + 34, y), (120, 124, 128), 8, cv2.LINE_AA)
        cv2.line(canvas, (fx - 34, y - 1), (fx + fabric_w + 34, y - 1), metal, 4, cv2.LINE_AA)
        cv2.line(canvas, (fx - 34, y - 2), (fx + fabric_w + 34, y - 2), (240, 244, 248), 1, cv2.LINE_AA)

    # 光照渐变
    grad_x = np.linspace(0.94, 1.05, canvas_w, dtype=np.float32)
    grad_y = np.linspace(1.03, 0.95, canvas_h, dtype=np.float32)
    light_map = grad_y[:, None] * grad_x[None, :]
    canvas = np.clip(canvas.astype(np.float32) * light_map[..., None], 0, 255).astype(np.uint8)

    # 轻微透视
    src = np.float32(
        [[0, 0], [canvas_w - 1, 0], [canvas_w - 1, canvas_h - 1], [0, canvas_h - 1]]
    )
    amount = float(np.clip(perspective, 0.0, 3.0))
    dst = np.float32(
        [
            [2 + amount * 7, 4 + amount * 9],
            [canvas_w - 3 - amount * 9, 1 + amount * 3],
            [canvas_w - 1 - amount * 3, canvas_h - 2 - amount * 7],
            [1 + amount * 4, canvas_h - 1 - amount * 2],
        ]
    )
    transform = cv2.getPerspectiveTransform(src, dst)
    warped = cv2.warpPerspective(
        canvas,
        transform,
        (canvas_w, canvas_h),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_REPLICATE,
    )

    corners_ortho = np.array(
        [
            [fx, fy],
            [fx + fabric_w, fy],
            [fx + fabric_w, fy + fabric_h],
            [fx, fy + fabric_h],
        ],
        dtype=np.float32,
    )
    corners = cv2.perspectiveTransform(corners_ortho.reshape(-1, 1, 2), transform).reshape(-1, 2)
    corners[:, 0] = np.clip(corners[:, 0], 1, canvas_w - 2)
    corners[:, 1] = np.clip(corners[:, 1], 1, canvas_h - 2)

    # 模糊、暗角与传感器噪声
    if blur_sigma > 0:
        warped = cv2.GaussianBlur(warped, (0, 0), blur_sigma)
    yy, xx = np.mgrid[0:canvas_h, 0:canvas_w]
    nx = (xx - canvas_w / 2) / (canvas_w / 2)
    ny = (yy - canvas_h / 2) / (canvas_h / 2)
    vignette = 1.0 - 0.13 * (nx**2 + ny**2) / 2.0
    warped = np.clip(
        warped.astype(np.float32) * vignette[..., None]
        + rng.normal(0, noise_sigma, warped.shape).astype(np.float32),
        0,
        255,
    ).astype(np.uint8)

    return SynthPhoto(
        image=warped,
        corners=corners.astype(np.float64),
        start_row=int(start_row),
        rows=int(rows),
        stitches=int(cols),
        seed=int(seed),
    )


def palette_separation(palette: tuple[tuple[int, int, int], tuple[int, int, int]]) -> float:
    """辅助：计算两个 BGR 颜色的 Lab 色差，便于挑选低对比度素材。"""
    lab = bgr_to_lab(np.array(palette, dtype=np.float64))
    _, _ = two_means(lab)
    return separation(lab)
