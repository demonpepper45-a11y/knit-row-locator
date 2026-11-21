"""从配色方格图读取参考矩阵。

选区 ``rect`` 是图解网格的外边界（含最外圈网格线），坐标为源图像素：
``(x0, y0, x1, y1)``，右下边界不含在选区内。读取时只采样每格中央区域，
因此轻微网格线、抗锯齿不会污染颜色。返回的矩阵为内部顺序：第 0 行是
图解最下面一行。
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from .color import bgr_to_lab, cluster_palette, nearest_centers, separation, two_means
from .config import DEFAULT_CHART_CONFIG, ChartConfig
from .draw import draw_texts
from .imageio import ensure_bgr
from .types import ChartGrid, GridInputError


@dataclass(frozen=True)
class ChartReadResult:
    chart: ChartGrid
    preview: np.ndarray
    cell_boxes: np.ndarray
    notes: tuple[str, ...]
    sampled_colors: np.ndarray


def _check_grid_size(rows: int, cols: int, config: ChartConfig) -> tuple[int, int]:
    parsed: list[int] = []
    for name, value in (("图解行数", rows), ("图解针数", cols)):
        if isinstance(value, bool):
            raise GridInputError(f"{name}必须是整数。")
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise GridInputError(f"{name}必须是整数。") from exc
        if not np.isfinite(number) or abs(number - round(number)) > 1e-9:
            raise GridInputError(f"{name}必须是整数，当前为 {value}。")
        integer = int(round(number))
        if integer < 1:
            raise GridInputError(f"{name}至少为 1，当前为 {integer}。")
        if integer > config.max_grid_cells:
            raise GridInputError(
                f"{name}过大（{integer}）；请确认是否把针数/行数填反了，上限为 {config.max_grid_cells}。"
            )
        parsed.append(integer)
    return parsed[0], parsed[1]


def _parse_rect(
    rect: tuple[float, float, float, float] | None,
    width: int,
    height: int,
) -> tuple[float, float, float, float]:
    if rect is None:
        return 0.0, 0.0, float(width), float(height)
    try:
        values = [float(v) for v in rect]
    except (TypeError, ValueError) as exc:
        raise GridInputError("图解选区必须是 4 个数字：x0, y0, x1, y1。") from exc
    if len(values) != 4 or not all(np.isfinite(values)):
        raise GridInputError("图解选区必须是 4 个有限数字：x0, y0, x1, y1。")
    x0, y0, x1, y1 = values
    if x1 - x0 <= 1e-6 or y1 - y0 <= 1e-6:
        raise GridInputError(
            "图解选区为空：请框选包含完整配色图解的矩形区域，右/下边界要大于左/上边界。"
        )
    if x0 < -0.5 or y0 < -0.5 or x1 > width + 0.5 or y1 > height + 0.5:
        raise GridInputError(
            f"图解选区超出图片范围：图片为 {width}×{height} 像素，选区为 "
            f"({x0:.0f}, {y0:.0f})–({x1:.0f}, {y1:.0f})。请调整 x0/y0/x1/y1。"
        )
    x0 = float(np.clip(x0, 0, width))
    x1 = float(np.clip(x1, 0, width))
    y0 = float(np.clip(y0, 0, height))
    y1 = float(np.clip(y1, 0, height))
    if x1 - x0 <= 1e-6 or y1 - y0 <= 1e-6:
        raise GridInputError("图解选区为空或只有一条边，请重新框选。")
    return x0, y0, x1, y1


def _pixel_span(start: float, size: float, inner: float, limit: int) -> tuple[int, int]:
    """返回 ``[first, last)`` 像素索引，用于格内中央采样。"""
    inner_start = start + size * (1.0 - inner) / 2.0
    inner_end = start + size * (1.0 + inner) / 2.0
    first = int(np.ceil(inner_start - 0.5))
    last = int(np.floor(inner_end - 0.5)) + 1
    if last <= first:
        center = int(np.floor((inner_start + inner_end) / 2.0))
        first = int(np.clip(center, 0, limit - 1))
        last = first + 1
    first = int(np.clip(first, 0, limit - 1))
    last = int(np.clip(last, first + 1, limit))
    return first, last


def _sample_cell_color(
    image: np.ndarray,
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    inner: float,
) -> np.ndarray:
    height, width = image.shape[:2]
    xs0, xs1 = _pixel_span(x0, x1 - x0, inner, width)
    ys0, ys1 = _pixel_span(y0, y1 - y0, inner, height)
    patch = image[ys0:ys1, xs0:xs1].reshape(-1, 3)
    return np.median(patch, axis=0).astype(np.float64)


def _build_preview(
    image: np.ndarray,
    rect: tuple[float, float, float, float],
    labels_screen: np.ndarray,
    palette_bgr: tuple[tuple[int, int, int], tuple[int, int, int]],
    cell_w: float,
    cell_h: float,
) -> np.ndarray:
    preview = image.copy()
    rows, cols = labels_screen.shape
    x0, y0, x1, y1 = rect
    cv2.rectangle(preview, (round(x0), round(y0)), (round(x1), round(y1)), (0, 220, 0), 2, cv2.LINE_AA)

    # 逐格画出采样点，颜色即判定标签
    dot_radius = int(max(2, min(5, cell_w * 0.12, cell_h * 0.12)))
    for sr in range(rows):
        cy = y0 + (sr + 0.5) * cell_h
        for c in range(cols):
            cx = x0 + (c + 0.5) * cell_w
            color = palette_bgr[int(labels_screen[sr, c])]
            cv2.circle(preview, (round(cx), round(cy)), dot_radius, (255, 255, 255), -1, cv2.LINE_AA)
            cv2.circle(preview, (round(cx), round(cy)), max(1, dot_radius - 1), color, -1, cv2.LINE_AA)

    items: list[tuple[str, tuple[float, float], tuple[int, int, int], int, str]] = []
    font_size = int(np.clip(cell_h * 0.38, 10, 18))
    if rows <= 80:
        for sr in range(rows):
            row_number = rows - sr  # 屏幕最上面一行是图解最后一行
            cy = y0 + (sr + 0.5) * cell_h
            items.append((str(row_number), (x0 - 6, cy), (20, 20, 20), font_size, "rm"))
    if cols <= 80:
        for c in range(cols):
            cx = x0 + (c + 0.5) * cell_w
            items.append((str(c + 1), (cx, y0 - 4), (20, 20, 20), max(9, font_size - 2), "ms"))
    items.append(
        (
            f"图解网格：{rows} 行 × {cols} 针（行号自下而上）",
            (x0, y0 + (y1 - y0) + 6),
            (0, 110, 0),
            max(12, font_size),
            "la",
        )
    )
    return draw_texts(preview, items)


def read_chart(
    image: np.ndarray,
    rect: tuple[float, float, float, float] | None,
    rows: int,
    cols: int,
    *,
    config: ChartConfig | None = None,
) -> ChartReadResult:
    """从图中读取 ``rows × cols`` 的双色图解矩阵。

    参数
    ----
    image : BGR 图像
    rect : 图解网格外边界 ``(x0, y0, x1, y1)``；``None`` 表示整张图片
    rows, cols : 图解行数、针数

    异常
    ----
    GridInputError : 空选区、越界、尺寸不足、行列数非法、双色无法区分等。
    """
    config = config or DEFAULT_CHART_CONFIG
    image = ensure_bgr(image)
    height, width = image.shape[:2]
    rows, cols = _check_grid_size(rows, cols, config)
    x0, y0, x1, y1 = _parse_rect(rect, width, height)

    cell_w = (x1 - x0) / cols
    cell_h = (y1 - y0) / rows
    if cell_w < config.min_cell_px or cell_h < config.min_cell_px:
        raise GridInputError(
            f"图解选区太小：每格约 {cell_w:.1f}×{cell_h:.1f} 像素，至少需要 "
            f"{config.min_cell_px:.0f}×{config.min_cell_px:.0f} 像素。请放大图片、缩小行列数或重新框选。"
        )

    screen_colors = np.empty((rows, cols, 3), dtype=np.float64)
    for sr in range(rows):
        for c in range(cols):
            screen_colors[sr, c] = _sample_cell_color(
                image,
                x0 + c * cell_w,
                y0 + sr * cell_h,
                x0 + (c + 1) * cell_w,
                y0 + (sr + 1) * cell_h,
                config.sample_inner,
            )

    flat = screen_colors.reshape(-1, 3)
    lab = bgr_to_lab(flat)
    centers, labels = two_means(lab)
    color_sep = separation(centers)
    if color_sep < config.min_color_separation:
        raise GridInputError(
            "图解中几乎只有一种颜色（两种颜色过于接近，Lab 色差 ≈ "
            f"{color_sep:.0f}），无法提取双色矩阵。请确认选区包含完整图解，或换用对比更明显的双色图解。"
        )

    labels_screen = labels.reshape(rows, cols)
    palette = cluster_palette(flat, labels)
    sampled_internal = screen_colors[::-1].copy()
    cells_internal = labels_screen[::-1].copy()

    cell_boxes = np.empty((rows, cols, 4), dtype=np.float64)
    for internal_row in range(rows):
        sr = rows - 1 - internal_row
        for c in range(cols):
            cell_boxes[internal_row, c] = (
                x0 + c * cell_w,
                y0 + sr * cell_h,
                x0 + (c + 1) * cell_w,
                y0 + (sr + 1) * cell_h,
            )

    notes = [
        f"图解读取：{rows} 行 × {cols} 针；每格约 {cell_w:.1f}×{cell_h:.1f} 像素，"
        f"只采样中央 {config.sample_inner:.0%} 区域以避开网格线。",
        f"识别到两种颜色，Lab 色差 ≈ {color_sep:.0f}；内部第 0 行对应图解最下面一行（第 1 行）。",
    ]
    preview = _build_preview(image, (x0, y0, x1, y1), labels_screen, palette, cell_w, cell_h)
    chart = ChartGrid(
        cells=cells_internal,
        palette=palette,
        source="chart",
        cell_boxes=cell_boxes,
    )
    return ChartReadResult(
        chart=chart,
        preview=preview,
        cell_boxes=cell_boxes,
        notes=tuple(notes),
        sampled_colors=sampled_internal,
    )
