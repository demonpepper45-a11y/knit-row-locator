from __future__ import annotations

import cv2
import numpy as np
import pytest

from core.chart import read_chart
from core.synth import DEFAULT_PALETTE, render_chart_image
from core.types import GridInputError


def _read(cells, **kwargs):
    image, rect = render_chart_image(cells, palette=DEFAULT_PALETTE, **kwargs)
    result = read_chart(image, rect, cells.shape[0], cells.shape[1])
    return image, rect, result


def _canonical(cells: np.ndarray, reference: np.ndarray) -> np.ndarray:
    """允许整体交换颜色标签。"""
    if np.array_equal(cells, reference):
        return cells
    if np.array_equal(cells, 1 - reference):
        return 1 - cells
    raise AssertionError("矩阵既不相同也不互补")


def test_reads_asymmetric_pattern_with_correct_orientation() -> None:
    cells = np.array(
        [
            [1, 0, 0, 0],  # 内部第 0 行 = 图解最下面一行
            [0, 0, 1, 0],
            [0, 1, 0, 1],  # 内部第 2 行 = 图解最上面一行
        ],
        dtype=np.int8,
    )
    image, rect, result = _read(cells, cell_px=24, margin=20, grid_px=2)
    got = result.chart.cells
    assert got.shape == (3, 4)
    canonical = got if np.array_equal(got, cells) else 1 - got
    assert np.array_equal(canonical, cells)
    # 左下角对应内部 [0, 0]：底部行最左格与顶部行最右格确实不同
    assert canonical[0, 0] == 1
    assert canonical[2, 3] == 1
    assert canonical[0, 0] != canonical[0, 1]

    # cell_boxes 按内部行号：内部第 0 行在图像下方，第 0 列在左侧
    boxes = result.cell_boxes
    assert boxes[0, 0][1] > boxes[2, 0][1]
    assert boxes[0, 0][0] < boxes[0, 3][0]
    assert result.preview.shape == image.shape
    assert len(result.notes) >= 2


def test_grid_lines_and_margins_are_ignored() -> None:
    cells = np.array(
        [
            [1, 1, 0, 1, 0],
            [0, 1, 1, 0, 0],
            [1, 0, 1, 0, 1],
            [0, 0, 1, 1, 0],
        ],
        dtype=np.int8,
    )
    image, rect, result = _read(cells, cell_px=18, margin=24, grid_px=4)
    assert np.array_equal(_canonical(result.chart.cells, cells), cells)


def test_accepts_grayscale_image() -> None:
    cells = np.array([[0, 1, 1], [1, 0, 0], [0, 1, 0]], dtype=np.int8)
    image, rect = render_chart_image(cells, palette=DEFAULT_PALETTE, cell_px=20, margin=16)
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    result = read_chart(gray, rect, 3, 3)
    assert np.array_equal(_canonical(result.chart.cells, cells), cells)


def test_empty_selection_has_actionable_message() -> None:
    image, _ = render_chart_image(np.zeros((3, 3), dtype=np.int8), palette=DEFAULT_PALETTE)
    with pytest.raises(GridInputError, match="选区为空"):
        read_chart(image, (50, 10, 50, 80), 3, 3)
    with pytest.raises(GridInputError, match="选区为空"):
        read_chart(image, (40, 60, 80, 40), 3, 3)


def test_out_of_bounds_selection() -> None:
    image, _ = render_chart_image(np.zeros((3, 3), dtype=np.int8), palette=DEFAULT_PALETTE)
    with pytest.raises(GridInputError, match="超出图片范围"):
        read_chart(image, (-10, 0, 100, 100), 3, 3)


def test_invalid_grid_sizes() -> None:
    image, rect = render_chart_image(np.zeros((3, 3), dtype=np.int8), palette=DEFAULT_PALETTE)
    with pytest.raises(GridInputError, match="至少为 1"):
        read_chart(image, rect, 0, 3)
    with pytest.raises(GridInputError, match="至少为 1"):
        read_chart(image, rect, 3, 0)
    with pytest.raises(GridInputError, match="必须是整数"):
        read_chart(image, rect, 2.5, 3)


def test_selection_too_small() -> None:
    image, _ = render_chart_image(np.zeros((3, 3), dtype=np.int8), palette=DEFAULT_PALETTE)
    with pytest.raises(GridInputError, match="太小"):
        read_chart(image, (10, 10, 14, 14), 3, 3)


def test_single_color_chart_rejected() -> None:
    image = np.full((120, 120, 3), 230, dtype=np.uint8)
    with pytest.raises(GridInputError, match="只有一种颜色"):
        read_chart(image, (10, 10, 110, 110), 4, 4)
