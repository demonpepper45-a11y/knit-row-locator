"""端到端稳健性测试：不同停织行、换色、较强透视与噪声。

所有素材仍是程序生成的合成织片；真实照片的验证情况见 ACCEPTANCE.md。
"""

from __future__ import annotations

import numpy as np
import pytest

from core.match import match
from core.photo import read_photo
from core.synth import DEFAULT_PALETTE, render_photo
from core.types import STATUS_UNIQUE, ChartGrid


@pytest.mark.parametrize("start_row", [0, 5, 10, 14, 18, 27])
def test_other_stop_rows_are_located(chart1, start_row) -> None:
    photo = render_photo(
        chart1,
        start_row,
        5,
        seed=500 + start_row,
        cell=40,
        perspective=2.0,
        noise_sigma=5.0,
        blur_sigma=0.8,
    )
    observed = read_photo(photo.image, photo.corners, chart1.stitches, 5)
    assert observed.observed.coverage == pytest.approx(1.0)
    result = match(chart1, observed.observed)
    assert result.status == STATUS_UNIQUE
    assert result.candidates[0].window_1based == (start_row + 1, start_row + 5)
    assert result.best is not None and result.best.score >= 0.99


def test_photo_with_swapped_yarn_colors(chart1) -> None:
    swapped_palette = (DEFAULT_PALETTE[1], DEFAULT_PALETTE[0])
    photo = render_photo(chart1, 18, 5, seed=777, palette=swapped_palette)
    observed = read_photo(photo.image, photo.corners, chart1.stitches, 5)
    result = match(chart1, observed.observed)
    assert result.status == STATUS_UNIQUE
    assert result.candidates[0].window_1based == (19, 23)
    assert result.candidates[0].swapped is True
    assert result.candidates[0].score >= 0.99


def test_pipeline_row_range_on_photo(chart1) -> None:
    photo = render_photo(chart1, 18, 5, seed=888)
    observed = read_photo(photo.image, photo.corners, chart1.stitches, 5)
    result = match(chart1, observed.observed, row_range=(20, 26))
    assert result.status == STATUS_UNIQUE
    assert result.candidates[0].window_1based == (19, 23)


def test_observed_grid_roundtrip_weights(chart1) -> None:
    photo = render_photo(chart1, 10, 5, seed=999)
    observed = read_photo(photo.image, photo.corners, chart1.stitches, 5).observed
    recreated = type(observed)(
        cells=observed.cells.copy(),
        weights=np.asarray(observed.weights, dtype=np.float64),
        palette=observed.palette,
    )
    result = match(chart1, recreated)
    assert result.status == STATUS_UNIQUE
    assert result.candidates[0].window_1based == (11, 15)
