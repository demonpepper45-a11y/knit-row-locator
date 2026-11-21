"""把图解读取、照片校正与匹配串成一条可测试的流程。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .chart import ChartReadResult, read_chart
from .imageio import load_image
from .match import match
from .photo import PhotoReadResult, read_photo
from .render import render_chart
from .types import Candidate, ChartGrid, MatchResult


@dataclass(frozen=True)
class CaseSpec:
    case_dir: Path
    case_id: str
    name: str
    summary: str
    seed: int
    chart_path: Path
    chart_rows: int
    chart_cols: int
    chart_rect: tuple[float, float, float, float]
    photo_path: Path
    photo_rows: int
    photo_stitches: int
    photo_corners: tuple[tuple[float, float], ...]
    true_last_completed_row: int
    variants: dict[str, str]
    expected: dict


@dataclass(frozen=True)
class LocateResult:
    chart: ChartGrid
    chart_preview: np.ndarray
    photo: PhotoReadResult
    result: MatchResult
    chart_render: np.ndarray
    selected: Candidate | None

    def render_candidate(self, candidate: Candidate) -> np.ndarray:
        return render_chart(
            self.chart,
            candidate,
            diff_cells=candidate.diff_cells,
        )


def list_cases(examples_dir: str | Path) -> list[Path]:
    root = Path(examples_dir)
    if not root.exists():
        return []
    return sorted(
        path
        for path in root.iterdir()
        if path.is_dir() and (path / "case.json").exists() and (path / "expected.json").exists()
    )


def load_case(case_dir: str | Path) -> CaseSpec:
    case_dir = Path(case_dir)
    case_file = case_dir / "case.json"
    expected_file = case_dir / "expected.json"
    if not case_file.exists():
        raise FileNotFoundError(f"样例缺少 case.json：{case_dir}")
    if not expected_file.exists():
        raise FileNotFoundError(f"样例缺少 expected.json：{case_dir}")
    with case_file.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    with expected_file.open("r", encoding="utf-8") as handle:
        expected = json.load(handle)
    chart = data["chart"]
    photo = data["photo"]
    return CaseSpec(
        case_dir=case_dir,
        case_id=str(data.get("id", case_dir.name)),
        name=str(data.get("name", case_dir.name)),
        summary=str(data.get("summary", "")),
        seed=int(data.get("seed", 0)),
        chart_path=case_dir / chart["file"],
        chart_rows=int(chart["rows"]),
        chart_cols=int(chart["stitches"]),
        chart_rect=tuple(float(v) for v in chart["rect"]),  # type: ignore[arg-type]
        photo_path=case_dir / photo["file"],
        photo_rows=int(photo["rows"]),
        photo_stitches=int(photo.get("stitches", chart["stitches"])),
        photo_corners=tuple(tuple(float(v) for v in point) for point in photo["corners"]),
        true_last_completed_row=int(photo.get("true_last_completed_row", 0)),
        variants={str(k): str(v) for k, v in data.get("variants", {}).items()},
        expected=expected,
    )


def locate(
    chart_image: np.ndarray,
    chart_rect: tuple[float, float, float, float] | None,
    chart_rows: int,
    chart_cols: int,
    photo_image: np.ndarray,
    photo_corners,
    photo_rows: int,
    photo_stitches: int | None = None,
    row_range: tuple[int, int] | None = None,
) -> LocateResult:
    """执行完整流程。任一步输入非法时抛出 ``GridInputError``/``ImageInputError``。"""
    chart_result: ChartReadResult = read_chart(
        chart_image, chart_rect, chart_rows, chart_cols
    )
    photo_result: PhotoReadResult = read_photo(
        photo_image,
        photo_corners,
        chart_cols if photo_stitches is None else photo_stitches,
        photo_rows,
    )
    result = match(chart_result.chart, photo_result.observed, row_range)
    candidate = result.best
    chart_render = render_chart(
        chart_result.chart,
        candidate,
        diff_cells=candidate.diff_cells if candidate is not None else (),
    )
    return LocateResult(
        chart=chart_result.chart,
        chart_preview=chart_result.preview,
        photo=photo_result,
        result=result,
        chart_render=chart_render,
        selected=candidate,
    )


def run_case(
    case_dir: str | Path,
    row_range: tuple[int, int] | None = None,
) -> LocateResult:
    spec = load_case(case_dir)
    return locate(
        load_image(spec.chart_path),
        spec.chart_rect,
        spec.chart_rows,
        spec.chart_cols,
        load_image(spec.photo_path),
        spec.photo_corners,
        spec.photo_rows,
        spec.photo_stitches,
        row_range,
    )
