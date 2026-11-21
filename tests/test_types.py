from __future__ import annotations

import numpy as np
import pytest

from core.types import (
    STATUS_MULTIPLE,
    STATUS_UNIQUE,
    Candidate,
    ChartGrid,
    GridInputError,
    ObservedGrid,
)


def test_candidate_row_conversions() -> None:
    candidate = Candidate(
        start_row=18,
        height=5,
        score=1.0,
        swapped=False,
        coverage=1.0,
        matches=60,
        valid_cells=60,
    )
    assert candidate.end_row == 22
    assert candidate.window_1based == (19, 23)
    assert candidate.last_completed_row == 23
    assert candidate.next_row == 24
    assert candidate.diff_count == 0


def test_observed_coverage_and_validation() -> None:
    observed = ObservedGrid(cells=[[0, 1], [1, 0]], weights=[[1.0, 0.0], [0.5, 0.0]])
    assert observed.coverage == pytest.approx(0.5)
    assert observed.valid_cells == 2
    assert observed.total_weight == pytest.approx(1.5)

    with pytest.raises(GridInputError, match="只能包含两种颜色"):
        ObservedGrid(cells=[[0, 2]], weights=[[1.0, 1.0]])
    with pytest.raises(GridInputError, match="权重矩阵形状"):
        ObservedGrid(cells=[[0, 1]], weights=[[1.0]])
    with pytest.raises(GridInputError, match="0–1"):
        ObservedGrid(cells=[[0, 1]], weights=[[1.0, 1.5]])
    with pytest.raises(GridInputError, match="二维矩阵"):
        ChartGrid(cells=[0, 1, 0])


def test_chart_swap_and_visual_order() -> None:
    cells = np.array([[0, 1, 0], [1, 0, 1]], dtype=np.int8)  # 第 0 行 = 图解底部
    chart = ChartGrid(cells=cells)
    assert chart.visual_cells()[0].tolist() == [1, 0, 1]  # 视觉顶部 = 内部最后一行
    swapped = chart.swapped()
    assert np.array_equal(swapped.cells, 1 - cells)
    assert swapped.palette == (chart.palette[1], chart.palette[0])
    assert chart.row_number(0) == 1


def test_observed_swap_keeps_weights() -> None:
    observed = ObservedGrid(cells=[[0, 1]], weights=[[0.8, 0.3]], palette=((1, 2, 3), (4, 5, 6)))
    swapped = observed.swapped()
    assert swapped.cells.tolist() == [[1, 0]]
    assert np.array_equal(swapped.weights, observed.weights)
    assert swapped.palette == (observed.palette[1], observed.palette[0])


def test_status_labels_are_distinct() -> None:
    assert STATUS_UNIQUE != STATUS_MULTIPLE
