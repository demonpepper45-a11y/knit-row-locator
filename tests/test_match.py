from __future__ import annotations

import numpy as np
import pytest

from core.match import match
from core.types import (
    STATUS_INPUT_ERROR,
    STATUS_INSUFFICIENT,
    STATUS_MULTIPLE,
    STATUS_UNIQUE,
    ObservedGrid,
)


def _ones(shape) -> np.ndarray:
    return np.ones(shape, dtype=np.float64)


def test_unique_window_19_to_23(chart1) -> None:
    observed = ObservedGrid(cells=chart1.cells[18:23], weights=_ones((5, 12)))
    result = match(chart1, observed)
    assert result.status == STATUS_UNIQUE
    assert [c.window_1based for c in result.candidates] == [(19, 23)]
    assert result.best is not None
    assert result.best.score == pytest.approx(1.0)
    assert result.last_completed_row == 23
    assert result.next_row == 24
    assert result.chart_complete is False
    assert result.best.diff_cells == ()


def test_swapping_color_labels_keeps_rows(chart1) -> None:
    window = chart1.cells[18:23]
    observed = ObservedGrid(cells=1 - window, weights=_ones((5, 12)))
    result = match(chart1, observed)
    assert result.status == STATUS_UNIQUE
    candidate = result.candidates[0]
    assert candidate.window_1based == (19, 23)
    assert candidate.swapped is True
    assert candidate.score == pytest.approx(1.0)
    assert candidate.diff_cells == ()
    assert result.last_completed_row == 23


def test_periodic_pattern_keeps_all_equivalent_positions(chart2) -> None:
    observed = ObservedGrid(cells=chart2.cells[19:24], weights=_ones((5, 12)))
    result = match(chart2, observed)
    assert result.status == STATUS_MULTIPLE
    assert [c.window_1based for c in result.candidates] == [
        (4, 8),
        (12, 16),
        (20, 24),
        (28, 32),
    ]
    assert list(result.all_last_completed_rows) == [8, 16, 24, 32]
    assert result.best is not None
    assert result.best.score >= 0.99


def test_row_range_limits_last_completed_row(chart2) -> None:
    observed = ObservedGrid(cells=chart2.cells[19:24], weights=_ones((5, 12)))
    result = match(chart2, observed, row_range=(20, 26))
    assert result.status == STATUS_UNIQUE
    assert [c.window_1based for c in result.candidates] == [(20, 24)]
    assert result.last_completed_row == 24
    assert result.next_row == 25


def test_row_range_that_still_contains_true_position(chart1) -> None:
    observed = ObservedGrid(cells=chart1.cells[18:23], weights=_ones((5, 12)))
    result = match(chart1, observed, row_range=(20, 26))
    assert result.status == STATUS_UNIQUE
    assert result.last_completed_row == 23


def test_range_without_legal_window(chart1) -> None:
    observed = ObservedGrid(cells=chart1.cells[18:23], weights=_ones((5, 12)))
    result = match(chart1, observed, row_range=(1, 4))
    assert result.status == STATUS_INSUFFICIENT
    assert "没有合法窗口" in result.reason


def test_range_that_only_contains_wrong_window_fails_quality(chart1) -> None:
    observed = ObservedGrid(cells=chart1.cells[18:23], weights=_ones((5, 12)))
    result = match(chart1, observed, row_range=(1, 5))
    assert result.status == STATUS_INSUFFICIENT
    assert result.best is None


def test_window_covering_first_row(chart1) -> None:
    observed = ObservedGrid(cells=chart1.cells[0:5], weights=_ones((5, 12)))
    result = match(chart1, observed)
    assert result.status == STATUS_UNIQUE
    assert result.candidates[0].window_1based == (1, 5)
    assert result.last_completed_row == 5
    assert result.next_row == 6


def test_window_covering_last_row_signals_complete(chart1) -> None:
    observed = ObservedGrid(cells=chart1.cells[-5:], weights=_ones((5, 12)))
    result = match(chart1, observed)
    assert result.status == STATUS_UNIQUE
    assert result.candidates[0].window_1based == (28, 32)
    assert result.last_completed_row == 32
    assert result.chart_complete is True
    assert result.next_row is None


def test_zero_weights_is_insufficient(chart1) -> None:
    observed = ObservedGrid(cells=chart1.cells[18:23], weights=np.zeros((5, 12)))
    result = match(chart1, observed)
    assert result.status == STATUS_INSUFFICIENT
    assert "权重" in result.reason
    assert result.best is None


def test_low_coverage_is_insufficient(chart1) -> None:
    weights = _ones((5, 12))
    weights.ravel()[:30] = 0.0  # 覆盖率 50% < 60%
    observed = ObservedGrid(cells=chart1.cells[18:23], weights=weights)
    result = match(chart1, observed)
    assert result.status == STATUS_INSUFFICIENT
    assert "覆盖率" in result.reason


def test_poor_match_quality_is_insufficient(chart1) -> None:
    rng = np.random.default_rng(123)
    random_cells = rng.integers(0, 2, size=(5, 12), dtype=np.int8)
    observed = ObservedGrid(cells=random_cells, weights=_ones((5, 12)))
    result = match(chart1, observed)
    assert result.status == STATUS_INSUFFICIENT
    assert "吻合度" in result.reason


def test_invalid_cell_weight_is_ignored(chart1) -> None:
    cells = chart1.cells[18:23].copy()
    weights = _ones((5, 12))
    cells[0, 0] = 1 - cells[0, 0]
    weights[0, 0] = 0.0  # 该格无证据，不应影响分数与差异格
    result = match(chart1, ObservedGrid(cells=cells, weights=weights))
    assert result.status == STATUS_UNIQUE
    assert result.best is not None
    assert result.best.score == pytest.approx(1.0)
    assert result.best.diff_cells == ()


def test_diff_cell_reported_for_real_mismatch(chart1) -> None:
    cells = chart1.cells[18:23].copy()
    cells[1, 1] = 1 - cells[1, 1]
    result = match(chart1, ObservedGrid(cells=cells, weights=_ones((5, 12))))
    assert result.status == STATUS_UNIQUE
    assert result.best is not None
    assert result.best.score == pytest.approx(59 / 60)
    assert result.best.diff_cells == ((1, 1),)


def test_observation_taller_than_chart_is_input_error(chart1) -> None:
    observed = ObservedGrid(cells=np.zeros((33, 12), dtype=np.int8), weights=_ones((33, 12)))
    result = match(chart1, observed)
    assert result.status == STATUS_INPUT_ERROR
    assert "多于图解" in result.reason


def test_stitch_count_mismatch_is_input_error(chart1) -> None:
    observed = ObservedGrid(cells=np.zeros((5, 11), dtype=np.int8), weights=_ones((5, 11)))
    result = match(chart1, observed)
    assert result.status == STATUS_INPUT_ERROR
    assert "针数不一致" in result.reason


@pytest.mark.parametrize("row_range", [(26, 20), (0, 5), (1, 99)])
def test_invalid_row_ranges(chart1, row_range) -> None:
    observed = ObservedGrid(cells=chart1.cells[18:23], weights=_ones((5, 12)))
    result = match(chart1, observed, row_range=row_range)
    assert result.status == STATUS_INPUT_ERROR


def test_accepts_plain_arrays_and_tuples(chart1) -> None:
    window = chart1.cells[18:23]
    result = match(chart1.cells, window)
    assert result.status == STATUS_UNIQUE
    assert result.last_completed_row == 23
    result_tuple = match(chart1, (window, _ones((5, 12))))
    assert result_tuple.status == STATUS_UNIQUE


def test_near_tie_within_margin_is_multiple() -> None:
    rng = np.random.default_rng(42)
    base = rng.integers(0, 2, size=(5, 12), dtype=np.int8)
    cells = np.vstack([base, base])
    cells[5, 0] = 1 - cells[5, 0]  # 第二个窗口只差 1 格，分差约 1.7 个百分点
    observed = ObservedGrid(cells=base, weights=_ones((5, 12)))
    result = match(cells, observed)
    assert result.status == STATUS_MULTIPLE
    assert [c.window_1based for c in result.candidates] == [(1, 5), (6, 10)]
    assert result.candidates[0].score == pytest.approx(1.0)
    assert result.candidates[1].score == pytest.approx(59 / 60)
    assert result.candidates[0].score - result.candidates[1].score < 0.02


def test_candidates_sorted_by_score_then_row(chart2) -> None:
    observed = ObservedGrid(cells=chart2.cells[19:24], weights=_ones((5, 12)))
    result = match(chart2, observed)
    scores = [c.score for c in result.candidates]
    assert scores == sorted(scores, reverse=True)
    windows = [c.start_row for c in result.candidates]
    assert windows == sorted(windows)
