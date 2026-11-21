"""候选级末行逻辑的回归测试。"""

from __future__ import annotations

import numpy as np

from core.match import match
from core.progress import candidate_progress
from core.types import ObservedGrid


def _ones(shape):
    return np.ones(shape, dtype=np.float64)


def test_non_last_candidate_reports_next_row(chart1) -> None:
    observed = ObservedGrid(cells=chart1.cells[18:23], weights=_ones((5, 12)))
    result = match(chart1, observed)
    assert result.best is not None
    progress = candidate_progress(result, result.best)
    assert progress.is_last_window is False
    assert progress.next_row == 24
    assert progress.next_label == "24"
    assert progress.note == ""
    assert progress.candidate_count == 1


def test_multiple_last_candidate_keeps_ambiguity(chart2) -> None:
    observed = ObservedGrid(cells=chart2.cells[19:24], weights=_ones((5, 12)))
    result = match(chart2, observed)
    assert [c.window_1based for c in result.candidates][-1] == (28, 32)
    last = result.candidates[-1]
    # 原始属性仍会得到 33，但展示层必须使用候选级判断，不能显示不存在的下一行。
    assert last.next_row == 33
    progress = candidate_progress(result, last)
    assert progress.is_last_window is True
    assert progress.next_row is None
    assert progress.next_label == "若此候选正确，图解已完成"
    assert "其他候选" in progress.note

    middle = result.candidates[2]
    assert middle.window_1based == (20, 24)
    middle_progress = candidate_progress(result, middle)
    assert middle_progress.is_last_window is False
    assert middle_progress.next_row == 25
    assert middle_progress.next_label == "25"


def test_unique_last_candidate_reports_complete(chart1) -> None:
    observed = ObservedGrid(cells=chart1.cells[-5:], weights=_ones((5, 12)))
    result = match(chart1, observed)
    assert result.best is not None
    assert result.candidates[0].window_1based == (28, 32)
    progress = candidate_progress(result, result.best)
    assert progress.is_last_window is True
    assert progress.next_row is None
    assert progress.next_label == "图解已完成"
    assert "没有下一行" in progress.note
