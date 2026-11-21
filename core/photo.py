"""从织片正面照片得到带权重的观测矩阵。

流程：四点透视校正 → 逐格多次采样 → 全图两种织线颜色聚类 → 逐格标签、
纯度与权重 → 网格叠加预览。

坐标：四角点顺序固定为 左上、右上、右下、左下；选区上边贴着最新完成的
一整行的上边缘，下边落在另一完整行的下边缘。校正后图像顶部是最新一行，
内部矩阵会把它翻转到第 0 行对应图解下部，符合 ``core.types`` 的约定。
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from .color import (
    bgr_to_lab,
    cluster_palette,
    nearest_centers,
    separation as color_separation,
    two_means,
)
from .config import DEFAULT_PHOTO_CONFIG, PhotoConfig
from .draw import draw_texts
from .imageio import ensure_bgr
from .types import GridInputError, ObservedGrid


@dataclass(frozen=True)
class PhotoReadResult:
    observed: ObservedGrid
    warped: np.ndarray
    overlay: np.ndarray
    source_preview: np.ndarray
    cell_boxes: np.ndarray
    quality: dict[str, float]
    notes: tuple[str, ...]
    homography: np.ndarray
    warp_size: tuple[int, int]


def _validate_counts(rows: int, stitches: int, config: PhotoConfig) -> tuple[int, int]:
    parsed: list[int] = []
    for name, value in (("可见完整行数", rows), ("完整针数", stitches)):
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
        parsed.append(integer)
    rows, stitches = parsed
    if rows * stitches > config.max_cells:
        raise GridInputError(
            f"行数×针数过大（{rows}×{stitches}）；请确认是否填反或填错，上限为 {config.max_cells}。"
        )
    return rows, stitches


def _validate_corners(corners, width: int, height: int) -> np.ndarray:
    try:
        pts = np.asarray(corners, dtype=np.float64)
    except (TypeError, ValueError) as exc:
        raise GridInputError("角点必须是 4×2 的数字：左上、右上、右下、左下。") from exc
    if pts.shape != (4, 2):
        raise GridInputError(f"角点形状应为 (4, 2)，实际为 {pts.shape}。")
    if not np.all(np.isfinite(pts)):
        raise GridInputError("角点坐标含有 NaN 或无穷大。")
    for index, (x, y) in enumerate(pts):
        if x < -0.5 or y < -0.5 or x > width - 0.5 or y > height - 0.5:
            label = ("左上", "右上", "右下", "左下")[index]
            raise GridInputError(
                f"{label}角点 ({x:.0f}, {y:.0f}) 超出照片范围（{width}×{height}）。请重新标点。"
            )
    pts[:, 0] = np.clip(pts[:, 0], 0, width - 1)
    pts[:, 1] = np.clip(pts[:, 1], 0, height - 1)

    crosses = []
    for i in range(4):
        a, b, c = pts[i], pts[(i + 1) % 4], pts[(i + 2) % 4]
        u = b - a
        v = c - b
        crosses.append(float(u[0] * v[1] - u[1] * v[0]))
    crosses_arr = np.asarray(crosses)
    if np.all(crosses_arr > 1e-6):
        pass
    elif np.all(crosses_arr < -1e-6):
        raise GridInputError(
            "角点顺序反了：请按 左上 → 右上 → 右下 → 左下 的顺序标记（当前看起来是反向的）。"
        )
    else:
        raise GridInputError(
            "四个角点没有围成一个凸四边形（可能重合、共线或交叉）。请按 左上、右上、右下、左下 重新标点。"
        )

    area = 0.5 * abs(
        float(
            np.dot(pts[:, 0], np.roll(pts[:, 1], -1))
            - np.dot(pts[:, 1], np.roll(pts[:, 0], -1))
        )
    )
    if area < 16:
        raise GridInputError(f"四边形选区面积太小（{area:.0f} 平方像素），请放大选区后重试。")
    return pts


def _source_cell_size(pts: np.ndarray, rows: int, stitches: int) -> tuple[float, float]:
    top = float(np.linalg.norm(pts[1] - pts[0]))
    bottom = float(np.linalg.norm(pts[2] - pts[3]))
    left = float(np.linalg.norm(pts[3] - pts[0]))
    right = float(np.linalg.norm(pts[2] - pts[1]))
    cell_w = min(top, bottom) / stitches
    cell_h = min(left, right) / rows
    return cell_w, cell_h


def _warp_size(rows: int, stitches: int, config: PhotoConfig) -> tuple[int, int, int]:
    max_side = 2400
    cell_px = min(
        int(config.cell_px),
        max(4, max_side // stitches),
        max(4, max_side // rows),
    )
    return stitches * cell_px, rows * cell_px, cell_px


def _sample_all_cells(
    warped: np.ndarray,
    rows: int,
    stitches: int,
    cell_px: int,
    config: PhotoConfig,
) -> np.ndarray:
    count = max(1, int(config.sample_grid))
    frac = np.linspace(
        (1.0 - config.sample_inner) / 2.0,
        (1.0 + config.sample_inner) / 2.0,
        count,
    )
    offsets = frac * cell_px
    height, width = warped.shape[:2]
    xs_by_col = np.clip(
        np.round(np.arange(stitches)[:, None] * cell_px + offsets[None, :]).astype(int),
        0,
        width - 1,
    )
    ys_by_row = np.clip(
        np.round(np.arange(rows)[:, None] * cell_px + offsets[None, :]).astype(int),
        0,
        height - 1,
    )
    samples = np.empty((rows, stitches, count * count, 3), dtype=np.uint8)
    for sr in range(rows):
        ys = ys_by_row[sr]
        for c in range(stitches):
            grid = warped[np.ix_(ys, xs_by_col[c])]
            samples[sr, c] = grid.reshape(-1, 3)
    return samples


def _build_overlay(
    warped: np.ndarray,
    labels_screen: np.ndarray,
    weights_screen: np.ndarray,
    palette: tuple[tuple[int, int, int], tuple[int, int, int]],
    quality: dict[str, float],
    cell_px: int,
) -> np.ndarray:
    height, width = warped.shape[:2]
    rows, cols = labels_screen.shape
    header, footer = 56, 46
    canvas = np.full((height + header + footer, width, 3), 246, dtype=np.uint8)
    canvas[header : header + height] = warped

    # 网格线与逐格权重边框
    for c in range(cols + 1):
        x = min(width - 1, c * cell_px)
        cv2.line(canvas, (x, header), (x, header + height - 1), (170, 170, 170), 1)
    for sr in range(rows + 1):
        y = min(header + height - 1, header + sr * cell_px)
        cv2.line(canvas, (0, y), (width - 1, y), (170, 170, 170), 1)

    for sr in range(rows):
        for c in range(cols):
            x0 = c * cell_px
            y0 = header + sr * cell_px
            weight = float(weights_screen[sr, c])
            if weight <= 0:
                color = (60, 60, 220)
            elif weight < 0.35:
                color = (0, 165, 255)
            elif weight < 0.7:
                color = (0, 210, 210)
            else:
                color = (0, 185, 0)
            cv2.rectangle(
                canvas,
                (x0, y0),
                (min(width - 1, x0 + cell_px - 1), min(header + height - 1, y0 + cell_px - 1)),
                color,
                1,
            )
            cx = x0 + cell_px // 2
            cy = y0 + cell_px // 2
            cv2.circle(canvas, (cx, cy), 4, (250, 250, 250), -1, cv2.LINE_AA)
            cv2.circle(canvas, (cx, cy), 2, palette[int(labels_screen[sr, c])], -1, cv2.LINE_AA)

    # 顶部一行 = 最近完成行：橙色粗框 + 指向箭头
    top_y0 = header + 1
    top_y1 = header + min(height - 1, cell_px - 1)
    cv2.rectangle(canvas, (0, top_y0), (width - 1, top_y1), (0, 120, 255), 3)
    cv2.arrowedLine(
        canvas,
        (width // 2, header - 4),
        (width // 2, top_y0 + 8),
        (0, 120, 255),
        3,
        cv2.LINE_AA,
        tipLength=0.35,
    )

    items: list[tuple[str, tuple[float, float], tuple[int, int, int], int, str]] = [
        ("校正后照片：顶行＝最近完成的一整行", (8, 7), (30, 30, 30), 14, "la"),
        ("格边框 绿/黄/红 = 权重 高/中/低", (width - 8, 7), (70, 70, 70), 12, "ra"),
        (
            f"有效覆盖 {quality['coverage']:.0%} · 平均权重 {quality['mean_weight']:.2f} · "
            f"色差 {quality['color_separation']:.0f}",
            (8, 31),
            (30, 30, 30),
            12,
            "la",
        ),
        ("白色圆点＝格内采样位置", (width - 8, 31), (70, 70, 70), 12, "ra"),
        (
            "顶部橙框所在行即“最近完成行”；下一行从它上方继续",
            (8, header + height + 12),
            (30, 30, 30),
            12,
            "la",
        ),
    ]
    return draw_texts(canvas, items)


def _build_source_preview(image: np.ndarray, corners: np.ndarray) -> np.ndarray:
    preview = image.copy()
    pts = np.round(corners).astype(np.int32)
    cv2.polylines(preview, [pts], True, (0, 210, 0), 3, cv2.LINE_AA)
    for index, point in enumerate(pts):
        cv2.circle(preview, tuple(point), 6, (0, 210, 0), -1, cv2.LINE_AA)
        cv2.circle(preview, tuple(point), 2, (255, 255, 255), -1, cv2.LINE_AA)
    cv2.line(preview, tuple(pts[0]), tuple(pts[1]), (0, 120, 255), 5, cv2.LINE_AA)

    top_mid = (pts[0] + pts[1]) / 2
    bottom_mid = (pts[3] + pts[2]) / 2
    label_y = max(20.0, float(top_mid[1]) - 58.0)
    cv2.arrowedLine(
        preview,
        (int(round(top_mid[0])), int(round(label_y + 8))),
        (int(round(top_mid[0])), int(round(top_mid[1] - 6))),
        (0, 120, 255),
        2,
        cv2.LINE_AA,
        tipLength=0.2,
    )
    items: list[tuple[str, tuple[float, float], tuple[int, int, int], int, str]] = [
        (
            "这条边＝最新完整行的上边缘",
            (float(top_mid[0]), label_y),
            (0, 90, 220),
            14,
            "ms",
        ),
        (
            "下面这条边＝更早的完整行下边缘",
            (float(bottom_mid[0]), float(min(image.shape[0] - 8, bottom_mid[1] + 22))),
            (0, 130, 0),
            13,
            "ma",
        ),
    ]
    labels = ("左上", "右上", "右下", "左下")
    for index, point in enumerate(pts):
        left_side = index in (0, 3)
        top_side = index in (0, 1)
        dx = -12 if left_side else 12
        dy = 16 if top_side else 22
        anchor = "ra" if left_side else "la"
        items.append(
            (
                labels[index],
                (float(point[0] + dx), float(point[1] + dy)),
                (0, 160, 0),
                13,
                anchor,
            )
        )
    return draw_texts(preview, items)


def read_photo(
    image: np.ndarray,
    corners,
    stitches: int,
    rows: int,
    *,
    config: PhotoConfig | None = None,
) -> PhotoReadResult:
    """校正照片并返回带权重的观测网格。

    参数
    ----
    image : BGR 照片
    corners : 4 个角点 ``[(x, y), ...]``，顺序 左上、右上、右下、左下
    stitches : 完整针数（照片中织片的宽度针数）
    rows : 可见完整行数

    异常
    ----
    GridInputError : 角点退化、分辨率过低、行列数非法等。
    """
    config = config or DEFAULT_PHOTO_CONFIG
    image = ensure_bgr(image)
    height, width = image.shape[:2]
    rows, stitches = _validate_counts(rows, stitches, config)
    pts = _validate_corners(corners, width, height)

    source_cell_w, source_cell_h = _source_cell_size(pts, rows, stitches)
    if min(source_cell_w, source_cell_h) < config.min_source_cell_px:
        raise GridInputError(
            f"选区分辨率过低：源图中每格约 {source_cell_w:.1f}×{source_cell_h:.1f} 像素，"
            f"至少需要 {config.min_source_cell_px:.0f}×{config.min_source_cell_px:.0f} 像素。"
            "请靠近拍摄、提高照片分辨率，或缩小行列数。"
        )

    warp_w, warp_h, cell_px = _warp_size(rows, stitches, config)
    dst = np.array(
        [[0, 0], [warp_w - 1, 0], [warp_w - 1, warp_h - 1], [0, warp_h - 1]],
        dtype=np.float32,
    )
    homography = cv2.getPerspectiveTransform(pts.astype(np.float32), dst)
    warped = cv2.warpPerspective(
        image,
        homography,
        (warp_w, warp_h),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_REPLICATE,
    )

    samples = _sample_all_cells(warped, rows, stitches, cell_px, config)
    sample_count = samples.shape[2]
    colors = samples.reshape(-1, sample_count, 3)
    cell_medians = np.median(colors, axis=1).reshape(rows, stitches, 3)
    lab_medians = bgr_to_lab(cell_medians.reshape(-1, 3))
    centers, _ = two_means(lab_medians)
    labels_med, dist_med = nearest_centers(lab_medians, centers)
    labels_screen = labels_med.reshape(rows, stitches)
    dist_screen = dist_med.reshape(rows, stitches)
    color_sep = color_separation(centers)

    lab_samples = bgr_to_lab(samples.reshape(-1, 3)).reshape(rows, stitches, sample_count, 3)
    d0 = np.linalg.norm(lab_samples - centers[0], axis=-1)
    d1 = np.linalg.norm(lab_samples - centers[1], axis=-1)
    sample_labels = (d1 < d0).astype(np.int8)
    purity = (sample_labels == labels_screen[..., None]).mean(axis=-1)

    gray = cv2.cvtColor(warped, cv2.COLOR_BGR2GRAY)
    gray = cv2.medianBlur(gray, 5)  # 抑制传感器噪声，避免把噪点当成“清晰”
    blur_score = float(cv2.Laplacian(gray, cv2.CV_64F).var())

    notes: list[str] = [
        f"透视校正：{stitches} 针 × {rows} 行；源图每格约 {source_cell_w:.1f}×{source_cell_h:.1f} 像素，"
        f"校正后每格 {cell_px} 像素，格内采样 {config.sample_grid}×{config.sample_grid} 点。",
        "照片顶行对应最近完成的整行；请确认选区上边缘贴着该行上边缘、下边缘落在更早一整行的下边缘。",
    ]

    if color_sep < config.color_separation_min or color_sep < 1e-6:
        weights_screen = np.zeros((rows, stitches), dtype=np.float64)
        notes.append(
            f"两种织线颜色在照片中几乎无法区分（Lab 色差 ≈ {color_sep:.0f}），"
            "所有格子的权重已置 0。请在自然光、无阴影条件下重拍，或让两种颜色对比更明显。"
        )
    else:
        color_conf = float(
            np.clip(
                (color_sep - config.color_separation_min)
                / (config.color_separation_clear - config.color_separation_min),
                0.0,
                1.0,
            )
        )
        dist_factor = np.clip(1.0 - dist_screen / (0.55 * color_sep + 1e-6), 0.35, 1.0)
        weights_screen = purity * color_conf * dist_factor

        if color_sep < 25:
            notes.append(
                f"两种颜色对比偏弱（Lab 色差 ≈ {color_sep:.0f}），已整体降权；"
                "建议使用自然光并避免阴影，或换一面拍摄。"
            )
        if blur_score < config.blur_warn:
            weights_screen = weights_screen * float(np.clip(blur_score / (config.blur_warn * 2), 0.4, 1.0))
            notes.append(
                f"照片偏模糊（清晰度指标 {blur_score:.0f} < {config.blur_warn:.0f}），已降权；"
                "请对焦后靠近拍摄。"
            )
        low_purity_cells = int(np.count_nonzero(purity < config.low_purity))
        if low_purity_cells:
            ratio = low_purity_cells / (rows * stitches)
            if ratio >= 0.10:
                notes.append(
                    f"{low_purity_cells} 个格子颜色混杂（平均纯度 {purity.mean():.2f}），这些格子已降权。"
                    "请让织片平铺、拉平针目，并避免手指、阴影或反光覆盖选区。"
                )
        weights_screen = np.where(weights_screen < config.min_weight, 0.0, weights_screen)
        weights_screen = np.clip(weights_screen, 0.0, 1.0)
        if weights_screen.mean() == 0:
            notes.append(
                "所有格子的颜色置信度都低于权重阈值，已被视为无证据。"
                "请让两种颜色在照片中更易区分，并确保每格中央没有被阴影、手指或反光覆盖。"
            )
        elif weights_screen.mean() < 0.45:
            notes.append("平均权重偏低，定位结果可能不稳定；建议检查角点是否贴合行边缘并重新拍摄。")

    palette = cluster_palette(cell_medians.reshape(-1, 3), labels_screen.reshape(-1))
    weights_internal = weights_screen[::-1].copy()
    cells_internal = labels_screen[::-1].copy()

    coverage = float(np.count_nonzero(weights_internal > 0) / weights_internal.size)
    quality = {
        "coverage": coverage,
        "mean_weight": float(weights_internal.mean()),
        "color_separation": float(color_sep),
        "mean_purity": float(purity.mean()),
        "blur_score": blur_score,
        "min_source_cell_px": float(min(source_cell_w, source_cell_h)),
        "source_cell_w": float(source_cell_w),
        "source_cell_h": float(source_cell_h),
        "cell_px": float(cell_px),
        "low_weight_cells": float(np.count_nonzero(weights_internal < 0.35)),
    }
    if coverage < 0.75:
        notes.append(
            f"有效覆盖率只有 {coverage:.0%}；权重过低的格子不参与匹配，"
            "可能需要在更均匀的光线下补拍。"
        )

    cell_boxes = np.empty((rows, stitches, 4), dtype=np.float64)
    for internal_row in range(rows):
        sr = rows - 1 - internal_row
        for c in range(stitches):
            cell_boxes[internal_row, c] = (
                c * cell_px,
                sr * cell_px,
                (c + 1) * cell_px,
                (sr + 1) * cell_px,
            )

    overlay = _build_overlay(warped, labels_screen, weights_screen, palette, quality, cell_px)
    source_preview = _build_source_preview(image, pts)
    observed = ObservedGrid(
        cells=cells_internal,
        weights=weights_internal,
        palette=palette,
        source="photo",
        notes=tuple(notes),
        quality=quality,
        warped=warped,
        cell_boxes=cell_boxes,
    )
    return PhotoReadResult(
        observed=observed,
        warped=warped,
        overlay=overlay,
        source_preview=source_preview,
        cell_boxes=cell_boxes,
        quality=quality,
        notes=tuple(notes),
        homography=homography,
        warp_size=(warp_w, warp_h),
    )
