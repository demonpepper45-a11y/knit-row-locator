"""图解高亮与结果预览渲染。"""

from __future__ import annotations

import cv2
import numpy as np

from .draw import draw_texts, fill_rect_alpha
from .types import Candidate, ChartGrid


def render_chart(
    chart: ChartGrid,
    candidate: Candidate | None = None,
    *,
    cell_px: int = 26,
    diff_cells: tuple[tuple[int, int], ...] = (),
) -> np.ndarray:
    """渲染完整图解，并高亮候选窗口、最近完成行与下一行。

    ``diff_cells`` 使用观测坐标 ``(观测行, 列)``；观测第 0 行对应候选窗口
    起点，因此会映射回图解中的实际行。
    """
    rows, cols = chart.shape
    cell_px = int(max(12, min(cell_px, 40)))
    left = 58
    top = 56
    right = 168 if candidate is not None else 26
    bottom = 48
    width = left + cols * cell_px + right
    height = top + rows * cell_px + bottom
    canvas = np.full((height, width, 3), 250, dtype=np.uint8)

    visual = chart.cells[::-1]
    palette = chart.palette

    # 网格与格子
    for v in range(rows):
        y0 = top + v * cell_px
        for c in range(cols):
            x0 = left + c * cell_px
            color = palette[int(visual[v, c])]
            cv2.rectangle(
                canvas,
                (x0, y0),
                (x0 + cell_px, y0 + cell_px),
                color,
                -1,
            )
    for c in range(cols + 1):
        x = left + c * cell_px
        cv2.line(canvas, (x, top), (x, top + rows * cell_px), (190, 190, 190), 1)
    for v in range(rows + 1):
        y = top + v * cell_px
        cv2.line(canvas, (left, y), (left + cols * cell_px, y), (190, 190, 190), 1)

    # 行号（自下而上）与列号
    label_size = int(np.clip(cell_px * 0.52, 10, 16))
    items: list[tuple[str, tuple[float, float], tuple[int, int, int], int, str]] = []
    for v in range(rows):
        row_number = rows - v
        y = top + (v + 0.5) * cell_px
        items.append((str(row_number), (left - 8, y), (55, 55, 55), label_size, "rm"))
    for c in range(cols):
        x = left + (c + 0.5) * cell_px
        items.append((str(c + 1), (x, top - 5), (55, 55, 55), max(9, label_size - 2), "ms"))

    items.append(
        (
            f"配色图解（{rows} 行 × {cols} 针，行号自下而上）",
            (6, 6),
            (25, 25, 25),
            15,
            "la",
        )
    )

    if candidate is not None:
        start = candidate.start_row
        end = candidate.end_row
        v_start = rows - 1 - end
        v_end = rows - 1 - start
        rect = (
            left,
            top + v_start * cell_px,
            left + cols * cell_px,
            top + (v_end + 1) * cell_px,
        )
        canvas = fill_rect_alpha(canvas, rect, (0, 220, 230), 0.26)
        cv2.rectangle(
            canvas,
            (int(rect[0]), int(rect[1])),
            (int(rect[2]) - 1, int(rect[3]) - 1),
            (0, 140, 255),
            3,
            cv2.LINE_AA,
        )

        # 最近完成行：橙色虚线 + 右侧标注
        y_last = top + (v_start + 0.5) * cell_px
        cv2.line(
            canvas,
            (left, round(y_last)),
            (left + cols * cell_px + 10, round(y_last)),
            (0, 120, 255),
            2,
            cv2.LINE_AA,
        )
        items.append(
            (
                f"最近完成：第 {candidate.last_completed_row} 行",
                (left + cols * cell_px + 16, y_last),
                (0, 100, 220),
                13,
                "lm",
            )
        )
        if candidate.end_row < rows - 1:
            y_next = top + (v_start - 0.5) * cell_px
            cv2.line(
                canvas,
                (left, round(y_next)),
                (left + cols * cell_px + 10, round(y_next)),
                (0, 160, 0),
                2,
                cv2.LINE_AA,
            )
            items.append(
                (
                    f"下一行：第 {candidate.next_row} 行",
                    (left + cols * cell_px + 16, y_next),
                    (0, 130, 0),
                    13,
                    "lm",
                )
            )
        else:
            items.append(
                (
                    "图解已完成",
                    (left + cols * cell_px + 16, top + 0.5 * cell_px),
                    (0, 100, 220),
                    14,
                    "lm",
                )
            )
        items.append(
            (
                f"候选：第 {candidate.window_1based[0]}–{candidate.window_1based[1]} 行",
                (left, top + rows * cell_px + 8),
                (0, 100, 200),
                13,
                "la",
            )
        )
        items.append(
            (
                f"吻合 {candidate.score:.1%}",
                (left + cols * cell_px + 16, top + rows * cell_px + 8),
                (70, 70, 70),
                12,
                "la",
            )
        )

        # 差异格：映射回图解行后画 ×
        for obs_row, col in diff_cells:
            chart_row = start + obs_row
            if 0 <= chart_row < rows and 0 <= col < cols:
                v = rows - 1 - chart_row
                cx = left + (col + 0.5) * cell_px
                cy = top + (v + 0.5) * cell_px
                r = cell_px * 0.28
                cv2.line(
                    canvas,
                    (round(cx - r), round(cy - r)),
                    (round(cx + r), round(cy + r)),
                    (200, 0, 200),
                    2,
                    cv2.LINE_AA,
                )
                cv2.line(
                    canvas,
                    (round(cx - r), round(cy + r)),
                    (round(cx + r), round(cy - r)),
                    (200, 0, 200),
                    2,
                    cv2.LINE_AA,
                )
        if diff_cells:
            items.append(
                (
                    f"× = 与照片不一致的格子（{len(diff_cells)} 个）",
                    (width - 6, top + rows * cell_px + 8),
                    (150, 0, 150),
                    12,
                    "ra",
                )
            )

    return draw_texts(canvas, items)
