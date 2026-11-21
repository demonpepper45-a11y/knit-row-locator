"""生成两组确定性演示样例（图片、矩阵、预期答案）。

运行方式::

    python examples/build_examples.py

素材全部为程序生成的合成图像（非实拍），随机种子固定，可重复生成。
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.color import bgr_to_lab, separation  # noqa: E402
from core.draw import draw_texts  # noqa: E402
from core.imageio import load_image  # noqa: E402
from core.match import match  # noqa: E402
from core.photo import read_photo  # noqa: E402
from core.pipeline import locate  # noqa: E402
from core.synth import (  # noqa: E402
    DEFAULT_PALETTE,
    make_periodic_chart,
    make_unique_chart,
    render_chart_image,
    render_photo,
)
from core.types import ChartGrid  # noqa: E402

PALETTE = DEFAULT_PALETTE
CHART_ROWS = 32
CHART_COLS = 12
PHOTO_ROWS = 5


def save_png(path: Path, image: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ok, buffer = cv2.imencode(".png", image)
    if not ok:
        raise RuntimeError(f"PNG 编码失败：{path}")
    buffer.tofile(str(path))


def save_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_chart_csv(path: Path, cells: np.ndarray) -> None:
    rows, cols = cells.shape
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["row_1based"] + [str(c + 1) for c in range(cols)])
        for row_number in range(rows, 0, -1):
            writer.writerow([row_number] + [int(v) for v in cells[row_number - 1]])


def write_observation_csvs(directory: Path, observed) -> None:
    rows, cols = observed.shape
    with (directory / "observation_labels.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["local_row_from_top"] + [str(c + 1) for c in range(cols)])
        for local_row in range(1, rows + 1):
            internal_row = rows - local_row
            writer.writerow([local_row] + [int(v) for v in observed.cells[internal_row]])
    with (directory / "observation_weights.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["local_row_from_top"] + [str(c + 1) for c in range(cols)])
        for local_row in range(1, rows + 1):
            internal_row = rows - local_row
            writer.writerow([local_row] + [f"{v:.3f}" for v in observed.weights[internal_row]])


def write_matrices_txt(path: Path, cells: np.ndarray, observed, start_row: int) -> None:
    rows, cols = cells.shape
    lines: list[str] = []
    lines.append("# 图解矩阵（人眼阅读顺序：顶部 = 图解最后一行；# = 深色/标签0，. = 浅色/标签1）")
    lines.append("# 行号   " + " ".join(f"{c + 1:>2d}" for c in range(cols)))
    for row_number in range(rows, 0, -1):
        visual = "".join("#" if v == 0 else "." for v in cells[row_number - 1])
        lines.append(f"{row_number:>4d}   " + " ".join(visual))
    lines.append("")
    lines.append(
        f"# 观测矩阵（顶部 = 最新完成行；实际对应图解第 {start_row + 1}–{start_row + observed.rows} 行）"
    )
    lines.append("# 本地行 " + " ".join(f"{c + 1:>2d}" for c in range(cols)))
    for local_row in range(1, observed.rows + 1):
        internal_row = observed.rows - local_row
        visual = "".join("#" if v == 0 else "." for v in observed.cells[internal_row])
        lines.append(f"{local_row:>4d}   " + " ".join(visual))
    lines.append("")
    lines.append("# 观测权重（顶部 = 最新完成行；9 = 权重≈0.9，0 = 无证据）")
    for local_row in range(1, observed.rows + 1):
        internal_row = observed.rows - local_row
        weights = "".join(str(min(9, int(round(v * 9)))) for v in observed.weights[internal_row])
        lines.append(f"{local_row:>4d}   " + " ".join(weights))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def check_result(label: str, result, expected: dict) -> None:
    got = result.result
    got_windows = [list(c.window_1based) for c in got.candidates]
    expected_windows = [list(w) for w in expected["windows_1based"]]
    assert got.status == expected["status"], f"{label}: 状态 {got.status} != {expected['status']}"
    assert got_windows == expected_windows, f"{label}: 候选窗口 {got_windows} != {expected_windows}"
    assert list(got.all_last_completed_rows) == expected["last_completed_rows"], label
    assert [c.next_row for c in got.candidates] == list(expected["next_rows"]), label
    assert got.best is not None and got.best.score >= expected["min_best_score"], (
        f"{label}: 最佳吻合度 {None if got.best is None else got.best.score:.3f} 低于预期"
    )
    assert len(got.best.diff_cells) <= expected["max_diff_cells"], f"{label}: 差异格过多"
    print(f"[OK] {label}: {got.label} -> {got_windows}, score={got.best.score:.3f}")


def build_case1(examples: Path) -> None:
    directory = examples / "case1_unique"
    directory.mkdir(parents=True, exist_ok=True)
    cells = make_unique_chart(
        rows=CHART_ROWS,
        cols=CHART_COLS,
        window_start=18,
        window_height=PHOTO_ROWS,
        seed=20261121,
    )
    chart = ChartGrid(cells=cells, palette=PALETTE)
    chart_image, rect = render_chart_image(cells, palette=PALETTE, cell_px=26, margin=26)
    save_png(directory / "chart.png", chart_image)

    photo = render_photo(chart, 18, PHOTO_ROWS, seed=101, perspective=1.0)
    save_png(directory / "photo.png", photo.image)
    blurred = render_photo(chart, 18, PHOTO_ROWS, seed=102, blur_sigma=2.5)
    save_png(directory / "photo_blurred.png", blurred.image)

    base_lab = bgr_to_lab(np.array(PALETTE, dtype=np.float64))
    base_sep = separation(base_lab)
    contrast_scale = max(0.05, 9.0 / base_sep)
    low = render_photo(
        chart,
        18,
        PHOTO_ROWS,
        seed=103,
        contrast_scale=contrast_scale,
        blur_sigma=1.2,
    )
    save_png(directory / "photo_lowcontrast.png", low.image)

    case = {
        "id": "case1_unique",
        "name": "演示一：唯一位置（第 19–23 行）",
        "summary": "5 行可见配色在图解中只出现一次；即使整体交换两种颜色，也没有其他等价窗口。",
        "seed": 20261121,
        "material": "程序生成的合成图像（非实拍）",
        "palette_bgr": [list(color) for color in PALETTE],
        "chart": {
            "file": "chart.png",
            "rows": CHART_ROWS,
            "stitches": CHART_COLS,
            "rect": [round(v, 3) for v in rect],
        },
        "photo": {
            "file": "photo.png",
            "rows": PHOTO_ROWS,
            "stitches": CHART_COLS,
            "corners": [[round(float(x), 3), round(float(y), 3)] for x, y in photo.corners],
            "true_last_completed_row": 23,
        },
        "variants": {
            "blurred": "photo_blurred.png",
            "low_contrast": "photo_lowcontrast.png",
        },
    }
    expected = {
        "material": "synthetic",
        "description": "第 19–23 行唯一；整体换色后仍无其他等价窗口。",
        "status": "unique",
        "windows_1based": [[19, 23]],
        "last_completed_rows": [23],
        "next_rows": [24],
        "min_best_score": 0.99,
        "max_diff_cells": 0,
        "scenarios": [
            {
                "name": "限定最近完成行 20–26",
                "row_range": [20, 26],
                "status": "unique",
                "windows_1based": [[19, 23]],
                "last_completed_rows": [23],
                "next_rows": [24],
            }
        ],
    }
    save_json(directory / "case.json", case)
    save_json(directory / "expected.json", expected)
    write_chart_csv(directory / "chart_grid.csv", cells)
    write_case_matrices(directory, cells, photo, 18, chart_image, rect)
    check_case_files(directory, expected, 18)


def write_case_matrices(
    directory: Path,
    cells: np.ndarray,
    photo,
    start_row: int,
    chart_image: np.ndarray,
    rect,
):
    from core.chart import read_chart

    chart_result = read_chart(chart_image, rect, CHART_ROWS, CHART_COLS)
    photo_result = read_photo(
        photo.image, photo.corners, CHART_COLS, PHOTO_ROWS
    )
    observed = photo_result.observed
    write_observation_csvs(directory, observed)
    write_matrices_txt(directory / "matrices.txt", cells, observed, start_row)
    return chart_result, observed


def check_case_files(directory: Path, expected: dict, start_row: int) -> None:
    case = json.loads((directory / "case.json").read_text(encoding="utf-8"))
    result = locate(
        load_image(directory / case["chart"]["file"]),
        tuple(case["chart"]["rect"]),
        case["chart"]["rows"],
        case["chart"]["stitches"],
        load_image(directory / case["photo"]["file"]),
        tuple(tuple(point) for point in case["photo"]["corners"]),
        case["photo"]["rows"],
        case["photo"]["stitches"],
    )
    check_result(directory.name, result, expected)
    for scenario in expected.get("scenarios", []):
        scenario_result = match(
            result.chart,
            result.photo.observed,
            tuple(scenario["row_range"]),
        )
        check_scenario(directory.name, scenario_result, scenario)


def check_scenario(label: str, got, expected: dict) -> None:
    windows = [list(c.window_1based) for c in got.candidates]
    assert got.status == expected["status"], f"{label}: 场景状态 {got.status}"
    assert windows == [list(w) for w in expected["windows_1based"]], f"{label}: 场景窗口 {windows}"
    assert list(got.all_last_completed_rows) == expected["last_completed_rows"], label
    print(f"[OK] {label} / {expected['name']}: {windows}")


def build_case2(examples: Path) -> None:
    directory = examples / "case2_repeat"
    directory.mkdir(parents=True, exist_ok=True)
    cells = make_periodic_chart(
        rows=CHART_ROWS,
        cols=CHART_COLS,
        period=8,
        seed=20261122,
    )
    chart = ChartGrid(cells=cells, palette=PALETTE)
    chart_image, rect = render_chart_image(cells, palette=PALETTE, cell_px=26, margin=26)
    save_png(directory / "chart.png", chart_image)

    photo = render_photo(chart, 19, PHOTO_ROWS, seed=201, perspective=1.0)
    save_png(directory / "photo.png", photo.image)

    case = {
        "id": "case2_repeat",
        "name": "演示二：重复花纹（每 8 行重复）",
        "summary": "花纹每 8 行重复一次，同一张照片可以在第 8、16、24、32 行结束；限定范围后只剩一个。",
        "seed": 20261122,
        "material": "程序生成的合成图像（非实拍）",
        "palette_bgr": [list(color) for color in PALETTE],
        "chart": {
            "file": "chart.png",
            "rows": CHART_ROWS,
            "stitches": CHART_COLS,
            "rect": [round(v, 3) for v in rect],
        },
        "photo": {
            "file": "photo.png",
            "rows": PHOTO_ROWS,
            "stitches": CHART_COLS,
            "corners": [[round(float(x), 3), round(float(y), 3)] for x, y in photo.corners],
            "true_last_completed_row": 24,
        },
        "variants": {},
    }
    expected = {
        "material": "synthetic",
        "description": "每 8 行重复一次；观测可在第 8、16、24、32 行结束。",
        "status": "multiple",
        "windows_1based": [[4, 8], [12, 16], [20, 24], [28, 32]],
        "last_completed_rows": [8, 16, 24, 32],
        "next_rows": [9, 17, 25, 33],
        "min_best_score": 0.99,
        "max_diff_cells": 0,
        "scenarios": [
            {
                "name": "限定最近完成行 20–26",
                "row_range": [20, 26],
                "status": "unique",
                "windows_1based": [[20, 24]],
                "last_completed_rows": [24],
                "next_rows": [25],
            }
        ],
    }
    save_json(directory / "case.json", case)
    save_json(directory / "expected.json", expected)
    write_chart_csv(directory / "chart_grid.csv", cells)
    write_case_matrices(directory, cells, photo, 19, chart_image, rect)
    check_case_files(directory, expected, 19)


def build_capture_guide(examples: Path) -> None:
    case1 = examples / "case1_unique"
    case = json.loads((case1 / "case.json").read_text(encoding="utf-8"))
    result = read_photo(
        load_image(case1 / case["photo"]["file"]),
        tuple(tuple(point) for point in case["photo"]["corners"]),
        case["photo"]["stitches"],
        case["photo"]["rows"],
    )
    preview = result.source_preview
    height, width = preview.shape[:2]
    header = 66
    canvas = np.full((height + header, width, 3), 250, dtype=np.uint8)
    canvas[header:] = preview
    canvas = draw_texts(
        canvas,
        [
            ("拍摄与选区示意（合成示意，非实拍）", (12, 8), (25, 25, 25), 17, "la"),
            (
                "正面拍摄 · 针杆在上 · 完整宽度 · 平铺无阴影；上边贴最新完整行上边缘，下边落更早一整行下边缘",
                (12, 36),
                (60, 60, 60),
                12,
                "la",
            ),
        ],
    )
    save_png(ROOT / "docs" / "capture_guide.png", canvas)


def build_previews(examples: Path) -> None:
    """把两个演示的实际结果渲染成文档截图（组件级预览）。"""
    from core.pipeline import run_case

    docs = ROOT / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    for case_id in ("case1_unique", "case2_repeat"):
        result = run_case(examples / case_id)
        save_png(docs / f"preview_{case_id}_chart.png", result.chart_render)
        save_png(docs / f"preview_{case_id}_photo.png", result.photo.overlay)


def main() -> None:
    examples = ROOT / "examples"
    build_case1(examples)
    build_case2(examples)
    build_capture_guide(examples)
    build_previews(examples)
    print("样例已生成：", examples)


if __name__ == "__main__":
    main()
