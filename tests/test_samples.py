from __future__ import annotations

import csv
import json
from pathlib import Path

import numpy as np
import pytest

from core.imageio import load_image
from core.match import match
from core.photo import read_photo
from core.pipeline import list_cases, load_case, run_case
from core.types import STATUS_INSUFFICIENT

CASE_IDS = ("case1_unique", "case2_repeat")


def _read_csv(path: Path) -> tuple[list[str], np.ndarray]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.reader(handle))
    header = rows[0]
    data = np.array([[float(v) for v in row[1:]] for row in rows[1:]])
    return header, data


def _match_expected(result, expected: dict) -> None:
    got = result.result
    assert got.status == expected["status"]
    assert [list(c.window_1based) for c in got.candidates] == [
        list(w) for w in expected["windows_1based"]
    ]
    assert list(got.all_last_completed_rows) == expected["last_completed_rows"]
    assert [c.next_row for c in got.candidates] == list(expected["next_rows"])
    assert got.best is not None and got.best.score >= expected["min_best_score"]
    assert len(got.best.diff_cells) <= expected["max_diff_cells"]


def test_list_cases(examples_dir) -> None:
    cases = list_cases(examples_dir)
    assert [path.name for path in cases] == list(CASE_IDS)


@pytest.mark.parametrize("case_id", CASE_IDS)
def test_demo_results_match_expected(examples_dir, case_id) -> None:
    case_dir = examples_dir / case_id
    spec = load_case(case_dir)
    expected = spec.expected
    assert expected["material"] == "synthetic"
    assert "非实拍" in json.loads((case_dir / "case.json").read_text(encoding="utf-8"))["material"]
    result = run_case(case_dir)
    _match_expected(result, expected)

    for scenario in expected.get("scenarios", []):
        scenario_result = match(
            result.chart,
            result.photo.observed,
            tuple(scenario["row_range"]),
        )
        assert scenario_result.status == scenario["status"]
        assert [list(c.window_1based) for c in scenario_result.candidates] == [
            list(w) for w in scenario["windows_1based"]
        ]
        assert list(scenario_result.all_last_completed_rows) == scenario["last_completed_rows"]


@pytest.mark.parametrize("case_id", CASE_IDS)
def test_photo_observation_matches_chart_window(examples_dir, case_id) -> None:
    case_dir = examples_dir / case_id
    spec = load_case(case_dir)
    result = run_case(case_dir)
    observed = result.photo.observed.cells
    start = spec.true_last_completed_row - spec.photo_rows
    window = result.chart.cells[start : start + spec.photo_rows]
    if np.array_equal(observed, window):
        canonical = observed
    elif np.array_equal(observed, 1 - window):
        canonical = 1 - observed
    else:
        raise AssertionError("观测矩阵与真实图解窗口既不相同也不互补")
    assert np.array_equal(canonical, window)
    assert result.photo.observed.coverage == pytest.approx(1.0)
    assert result.photo.observed.weights.min() > 0.4


@pytest.mark.parametrize("case_id", CASE_IDS)
def test_chart_csv_matches_rendered_chart(examples_dir, case_id) -> None:
    directory = examples_dir / case_id
    result = run_case(directory)
    header, matrix = _read_csv(directory / "chart_grid.csv")
    assert header[0] == "row_1based"
    assert [int(v) for v in header[1:]] == list(range(1, result.chart.stitches + 1))
    assert matrix.shape == result.chart.shape
    visual = result.chart.visual_cells()
    if np.array_equal(matrix, visual):
        pass
    elif np.array_equal(matrix, 1 - visual):
        pass
    else:
        raise AssertionError("chart_grid.csv 与图解读取结果不一致（行序或列序错误）")
    assert (directory / "matrices.txt").read_text(encoding="utf-8").count("观测矩阵") == 1


@pytest.mark.parametrize("case_id", CASE_IDS)
def test_observation_csvs_match_observed_grid(examples_dir, case_id) -> None:
    directory = examples_dir / case_id
    result = run_case(directory)
    _, labels = _read_csv(directory / "observation_labels.csv")
    _, weights = _read_csv(directory / "observation_weights.csv")
    visual_cells = result.photo.observed.cells[::-1]
    visual_weights = result.photo.observed.weights[::-1]
    assert np.array_equal(labels.astype(np.int8), visual_cells)
    assert np.allclose(weights, visual_weights, atol=1e-3)


def test_low_contrast_variant_downgrades_evidence(examples_dir) -> None:
    directory = examples_dir / "case1_unique"
    spec = load_case(directory)
    result = run_case(directory)
    photo = read_photo(
        load_image(directory / spec.variants["low_contrast"]),
        spec.photo_corners,
        spec.photo_stitches,
        spec.photo_rows,
    )
    assert photo.quality["color_separation"] < 25
    assert photo.quality["coverage"] < 0.75
    joined = " ".join(photo.notes)
    assert "对比" in joined or "区分" in joined or "无证据" in joined
    degraded = match(result.chart, photo.observed)
    assert degraded.status == STATUS_INSUFFICIENT


def test_blurred_variant_triggers_quality_note(examples_dir) -> None:
    directory = examples_dir / "case1_unique"
    spec = load_case(directory)
    photo = read_photo(
        load_image(directory / spec.variants["blurred"]),
        spec.photo_corners,
        spec.photo_stitches,
        spec.photo_rows,
    )
    assert photo.quality["blur_score"] < 30
    assert any("模糊" in note for note in photo.notes)
    assert photo.observed.weights.mean() < 0.8
