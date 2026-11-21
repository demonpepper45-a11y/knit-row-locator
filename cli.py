#!/usr/bin/env python
"""KnitAlign 第一版可复现基线命令行。

用法示例::

    python cli.py --case case1_unique
    python cli.py --case case2_repeat --row-range 20-26 --json
    python cli.py --all --scenarios --json --out docs/baseline_results.json

输出约定
--------
* 候选按“行窗口集合”报告；重复花纹保留全部并列候选，不把任一个候选当作唯一真值。
* ``next_row`` 按**当前候选**计算：若该候选到图解末行则为 ``null``，
  ``next_label`` 会说明是唯一候选完成还是“若此候选正确，图解已完成”。
* 阈值、行列数、来源、预期答案和实际耗时都写入结构化结果，便于冻结配置与复验。
"""

from __future__ import annotations

import argparse
import json
import platform
import sys
import time
from collections import Counter
from pathlib import Path

import cv2
import numpy as np

from core import __version__
from core.config import DEFAULT_CHART_CONFIG, DEFAULT_MATCH_CONFIG, DEFAULT_PHOTO_CONFIG
from core.imageio import ImageInputError, load_image
from core.pipeline import CaseSpec, list_cases, load_case, locate, run_case
from core.progress import candidate_progress
from core.types import STATUS_LABELS, GridInputError

ROOT = Path(__file__).resolve().parent
SCHEMA_VERSION = "knitalign.baseline.v1"


def _display_path(path: Path) -> str:
    """尽量输出相对仓库根目录的路径，避免把本机绝对路径写进运行产物。"""
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return path.name


def _parse_row_range(text: str) -> tuple[int, int]:
    parts = text.replace(":", "-").split("-")
    if len(parts) != 2:
        raise argparse.ArgumentTypeError("范围格式应为 20-26（最近完成行的下限-上限）。")
    try:
        lo, hi = int(parts[0]), int(parts[1])
    except ValueError as exc:
        raise argparse.ArgumentTypeError("范围两端必须是整数。") from exc
    if lo < 1 or hi < 1:
        raise argparse.ArgumentTypeError("范围必须从第 1 行开始。")
    if lo > hi:
        raise argparse.ArgumentTypeError("范围下限不能大于上限。")
    return lo, hi


def _expected_for(spec: CaseSpec, row_range: tuple[int, int] | None):
    """返回 (预期字典, 场景名)。范围与 expected.scenarios 匹配时才比较。"""
    if row_range is None:
        return spec.expected, None
    for scenario in spec.expected.get("scenarios", []):
        if tuple(int(v) for v in scenario["row_range"]) == tuple(row_range):
            return scenario, str(scenario.get("name", ""))
    return None, None


def _candidate_record(result, candidate) -> dict:
    progress = candidate_progress(result, candidate)
    diff_cells = [list(cell) for cell in candidate.diff_cells[:50]]
    return {
        "window_1based": list(candidate.window_1based),
        "start_row_zero_based": candidate.start_row,
        "height": candidate.height,
        "last_completed_row": candidate.last_completed_row,
        "next_row": progress.next_row,
        "next_label": progress.next_label,
        "is_last_window": progress.is_last_window,
        "score": round(float(candidate.score), 6),
        "coverage": round(float(candidate.coverage), 6),
        "color_mapping": "swapped" if candidate.swapped else "direct",
        "matches": int(candidate.matches),
        "valid_cells": int(candidate.valid_cells),
        "diff_count": candidate.diff_count,
        "diff_cells": diff_cells,
        "diff_cells_truncated": candidate.diff_count > len(diff_cells),
    }


def _expected_check(result, expected: dict | None) -> dict | None:
    if expected is None:
        return None
    expected_windows = sorted(tuple(int(v) for v in pair) for pair in expected.get("windows_1based", []))
    actual_windows = sorted(tuple(c.window_1based) for c in result.candidates)
    status_ok = result.status == expected.get("status")
    windows_ok = actual_windows == expected_windows
    if len(expected_windows) > 1:
        comparison = "candidate_set"
        note = "按候选集比较；并列候选均可解释同一张照片，不把任一个当成唯一真值。"
    else:
        comparison = "single_window"
        note = "按单个候选窗口比较。"
    return {
        "matches": bool(status_ok and windows_ok),
        "comparison": comparison,
        "expected_status": expected.get("status"),
        "actual_status": result.status,
        "expected_windows_1based": [list(pair) for pair in expected_windows],
        "actual_windows_1based": [list(pair) for pair in actual_windows],
        "note": note,
    }


def _case_record(
    spec: CaseSpec,
    row_range: tuple[int, int] | None,
    *,
    expected: dict | None = None,
    scenario_name: str | None = None,
) -> dict:
    started = time.perf_counter()
    located = run_case(spec.case_dir, row_range)
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    result = located.result
    if expected is None and row_range is None:
        expected = spec.expected
    return {
        "case_id": spec.case_id,
        "case_dir": _display_path(spec.case_dir),
        "name": spec.name,
        "material": spec.material,
        "source": {
            "chart": _display_path(spec.chart_path),
            "photo": _display_path(spec.photo_path),
            "seed": spec.seed,
        },
        "ground_truth_last_completed_row": spec.true_last_completed_row,
        "inputs": {
            "chart_rows": spec.chart_rows,
            "chart_stitches": spec.chart_cols,
            "chart_rect": list(spec.chart_rect),
            "photo_rows": spec.photo_rows,
            "photo_stitches": spec.photo_stitches,
            "photo_corners": [list(point) for point in spec.photo_corners],
        },
        "scenario_name": scenario_name,
        "row_range": list(row_range) if row_range is not None else None,
        "expected": expected,
        "expected_check": _expected_check(result, expected),
        "result": {
            "status": result.status,
            "status_label": STATUS_LABELS[result.status],
            "reason": result.reason,
            "coverage": round(float(result.coverage), 6),
            "candidate_count": result.candidate_count,
            "windows_searched": result.windows_searched,
            "candidates": [_candidate_record(result, candidate) for candidate in result.candidates],
        },
        "elapsed_ms": round(elapsed_ms, 1),
    }


def _manifest_path(base_dir: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else (base_dir / path)


def _ground_truth_check(result, ground_truth_row: int) -> dict:
    candidate_rows = [candidate.last_completed_row for candidate in result.candidates]
    answered = result.status in ("unique", "multiple")
    covered = ground_truth_row in candidate_rows
    unique_correct = result.status == "unique" and candidate_rows == [ground_truth_row]
    if result.status == "unique":
        outcome = "unique_correct" if unique_correct else "unique_wrong"
    elif result.status == "multiple":
        outcome = "multiple_covers" if covered else "multiple_misses"
    elif result.status == "insufficient":
        outcome = "refused"
    else:
        outcome = "input_error"
    if outcome == "unique_correct":
        note = "唯一回答正确。"
    elif outcome == "multiple_covers":
        note = "保留的候选集覆盖真值；未把并列候选当成唯一真值。"
    elif outcome == "unique_wrong":
        note = "错误地给出了唯一行号；该失败样本应保留。"
    elif outcome == "multiple_misses":
        note = "候选集没有覆盖真值；应检查选区、角点或匹配质量。"
    elif outcome == "refused":
        note = "系统拒绝给出行号；不计为错误唯一回答，但仍是未自动回答。"
    else:
        note = "输入或尺寸错误，未产生行号。"
    return {
        "comparison": "ground_truth_row_membership",
        "matches": bool(covered) if answered else False,
        "answered": answered,
        "candidate_covers_truth": covered,
        "unique_correct": unique_correct,
        "outcome": outcome,
        "ground_truth_last_completed_row": ground_truth_row,
        "candidate_last_completed_rows": candidate_rows,
        "note": note,
    }


def _manifest_record(sample: dict, manifest_dir: Path) -> dict:
    required = (
        "sample_id",
        "chart",
        "chart_rows",
        "chart_stitches",
        "chart_rect",
        "photo",
        "photo_rows",
        "photo_stitches",
        "photo_corners",
        "true_last_completed_row",
    )
    missing = [key for key in required if key not in sample]
    if missing:
        raise ValueError(f"manifest 样本缺少字段：{', '.join(missing)}")
    sample_id = str(sample["sample_id"])
    chart_path = _manifest_path(manifest_dir, str(sample["chart"]))
    photo_path = _manifest_path(manifest_dir, str(sample["photo"]))
    corners = tuple(tuple(float(v) for v in point) for point in sample["photo_corners"])
    rect = tuple(float(v) for v in sample["chart_rect"])
    row_range = sample.get("row_range")
    if row_range is not None:
        row_range = (int(row_range[0]), int(row_range[1]))

    started = time.perf_counter()
    located = locate(
        load_image(chart_path),
        rect,
        int(sample["chart_rows"]),
        int(sample["chart_stitches"]),
        load_image(photo_path),
        corners,
        int(sample["photo_rows"]),
        int(sample["photo_stitches"]),
        row_range,
    )
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    result = located.result
    ground_truth_row = int(sample["true_last_completed_row"])
    return {
        "sample_id": sample_id,
        "group_id": str(sample.get("group_id", "")),
        "material": str(sample.get("material", "real")),
        "source": {
            "chart": _display_path(chart_path),
            "photo": _display_path(photo_path),
            "manifest": str(sample.get("chart", "")),
        },
        "ground_truth_last_completed_row": ground_truth_row,
        "notes": str(sample.get("notes", "")),
        "inputs": {
            "chart_rows": int(sample["chart_rows"]),
            "chart_stitches": int(sample["chart_stitches"]),
            "chart_rect": list(rect),
            "photo_rows": int(sample["photo_rows"]),
            "photo_stitches": int(sample["photo_stitches"]),
            "photo_corners": [list(point) for point in corners],
        },
        "row_range": list(row_range) if row_range is not None else None,
        "ground_truth_check": _ground_truth_check(result, ground_truth_row),
        "result": {
            "status": result.status,
            "status_label": STATUS_LABELS[result.status],
            "reason": result.reason,
            "coverage": round(float(result.coverage), 6),
            "candidate_count": result.candidate_count,
            "windows_searched": result.windows_searched,
            "candidates": [_candidate_record(result, candidate) for candidate in result.candidates],
        },
        "elapsed_ms": round(elapsed_ms, 1),
    }


def _manifest_entries(manifest_path: Path) -> list[dict]:
    if not manifest_path.exists():
        raise FileNotFoundError(f"找不到 manifest：{manifest_path}")
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    samples = data.get("samples")
    if not isinstance(samples, list) or not samples:
        raise ValueError("manifest 必须包含非空的 samples 数组。")
    base_dir = manifest_path.parent
    seen: set[str] = set()
    entries = []
    for sample in samples:
        if not isinstance(sample, dict):
            raise ValueError("manifest 的每个 sample 必须是对象。")
        sample_id = str(sample.get("sample_id", ""))
        if not sample_id:
            raise ValueError("manifest 的 sample 缺少 sample_id。")
        if sample_id in seen:
            raise ValueError(f"manifest 中 sample_id 重复：{sample_id}")
        seen.add(sample_id)
        entries.append(_manifest_record(sample, base_dir))
    return entries


def _build_payload(
    entries: list[dict],
    row_range: tuple[int, int] | None,
    *,
    mode: str = "builtin",
    manifest: str | None = None,
) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "mode": mode,
        "manifest": manifest,
        "tool": {"name": "knitalign-cli", "version": __version__},
        "environment": {
            "python": platform.python_version(),
            "numpy": np.__version__,
            "opencv": cv2.__version__,
            "platform": platform.platform(),
        },
        "config": {
            "match": DEFAULT_MATCH_CONFIG.as_dict(),
            "chart": DEFAULT_CHART_CONFIG.as_dict(),
            "photo": DEFAULT_PHOTO_CONFIG.as_dict(),
        },
        "row_range": list(row_range) if row_range is not None else None,
        "case_count": len(entries),
        "cases": entries,
    }


def _format_text(payload: dict) -> str:
    lines: list[str] = []
    lines.append(f"KnitAlign baseline v{payload['tool']['version']}（schema {payload['schema_version']}）")
    lines.append(f"模式：{payload.get('mode', 'builtin')}")
    if payload.get("manifest"):
        lines.append(f"manifest：{payload['manifest']}")
    match_cfg = payload["config"]["match"]
    lines.append(
        "阈值："
        f"min_coverage={match_cfg['min_coverage']:.2f} "
        f"min_score={match_cfg['min_score']:.2f} "
        f"ambiguity_margin={match_cfg['ambiguity_margin']:.2f}"
    )
    lines.append(f"row_range: {payload['row_range'] if payload['row_range'] is not None else 'full'}")
    if payload.get("mode") == "manifest":
        outcomes = Counter(
            case["ground_truth_check"]["outcome"]
            for case in payload["cases"]
            if case.get("ground_truth_check")
        )
        lines.append("结果分布：" + " ".join(f"{key}={value}" for key, value in sorted(outcomes.items())))
    for case in payload["cases"]:
        result = case["result"]
        lines.append("")
        title = f"[{case.get('sample_id') or case['case_id']}]"
        if case.get("group_id"):
            title += f" group={case['group_id']}"
        if case.get("scenario_name"):
            title += f" scenario={case['scenario_name']}"
        lines.append(title)
        source = case["source"]
        seed_text = f"，seed={source['seed']}" if "seed" in source else ""
        lines.append(
            f"  来源: {source['chart']} + {source['photo']}（{case['material']}{seed_text}）"
        )
        lines.append(
            f"  状态: {result['status']}（{result['status_label']}）"
            f"  候选数={result['candidate_count']}"
            f"  有效覆盖率={result['coverage']:.2%}"
            f"  耗时={case['elapsed_ms']:.1f} ms"
        )
        for candidate in result["candidates"]:
            first, last = candidate["window_1based"]
            next_text = candidate["next_label"]
            lines.append(
                f"  - 第 {first}–{last} 行 | 最近完成 {candidate['last_completed_row']}"
                f" | 下一行 {next_text}"
                f" | 吻合度 {candidate['score']:.3f}"
                f" | 有效覆盖 {candidate['coverage']:.0%}"
                f" | 差异格 {candidate['diff_count']}"
            )
        check = case.get("expected_check")
        truth_check = case.get("ground_truth_check")
        if truth_check is not None:
            lines.append(
                f"  真值: 最近完成 {truth_check['ground_truth_last_completed_row']}"
                f" | 候选覆盖: {'是' if truth_check['candidate_covers_truth'] else '否'}"
                f" | 结果: {truth_check['outcome']}"
            )
            lines.append(f"  说明: {truth_check['note']}")
        elif check is None:
            lines.append("  预期核对: 未提供（自定义范围）")
        else:
            verdict = "OK" if check["matches"] else "MISMATCH"
            lines.append(
                f"  预期核对: {verdict}  期望 {check['expected_status']} {check['expected_windows_1based']}"
                f"  实际 {check['actual_status']} {check['actual_windows_1based']}"
            )
            if check["comparison"] == "candidate_set":
                lines.append("  说明: 按候选集比较，未把并列候选当成唯一真值。")
    return "\n".join(lines)


def _select_specs(case_ids: list[str] | None, run_all: bool) -> list[CaseSpec]:
    available = {path.name: path for path in list_cases(ROOT / "examples")}
    if run_all:
        if not available:
            raise FileNotFoundError("examples/ 下没有可用案例。")
        return [load_case(available[name]) for name in sorted(available)]
    if not case_ids:
        raise ValueError("请用 --case 指定案例，或使用 --all。")
    missing = [case_id for case_id in case_ids if case_id not in available]
    if missing:
        raise ValueError(f"未知案例：{', '.join(missing)}；可用：{', '.join(sorted(available))}")
    return [load_case(available[case_id]) for case_id in case_ids]


def _entries(specs: list[CaseSpec], args) -> list[dict]:
    entries: list[dict] = []
    if args.scenarios:
        for spec in specs:
            expected, scenario_name = _expected_for(spec, None)
            entries.append(_case_record(spec, None, expected=expected, scenario_name=scenario_name))
            for scenario in spec.expected.get("scenarios", []):
                row_range = tuple(int(v) for v in scenario["row_range"])
                entries.append(
                    _case_record(
                        spec,
                        row_range,
                        expected=scenario,
                        scenario_name=str(scenario.get("name", "")),
                    )
                )
        return entries
    for spec in specs:
        expected, scenario_name = _expected_for(spec, args.row_range)
        entries.append(
            _case_record(spec, args.row_range, expected=expected, scenario_name=scenario_name)
        )
    return entries


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="KnitAlign 第一版基线：对内置案例输出结构化定位结果。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例：\n"
            "  python cli.py --all --scenarios --json\n"
            "  python cli.py --case case2_repeat --row-range 20-26 --json\n"
            "  python cli.py --manifest data/real_round1/manifest.json --json\n"
        ),
    )
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--case", action="append", metavar="CASE_ID", help="案例目录名，可重复。")
    target.add_argument("--all", action="store_true", help="运行 examples/ 下全部案例。")
    target.add_argument("--manifest", type=Path, metavar="PATH",
                        help="运行实拍/自定义样本清单（JSON，见采集模板）。")
    parser.add_argument("--row-range", type=_parse_row_range, default=None, metavar="LO-HI",
                        help="限定最近完成行范围（一基闭区间），如 20-26。")
    parser.add_argument("--scenarios", action="store_true",
                        help="额外运行 expected.json 中预注册的范围场景。不能与 --row-range 同用。")
    parser.add_argument("--json", action="store_true", help="输出结构化 JSON（默认输出可读文本）。")
    parser.add_argument("--out", type=Path, default=None, metavar="PATH",
                        help="同时把结构化 JSON 写入文件。")
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.scenarios and args.row_range is not None:
        parser.error("--scenarios 与 --row-range 不能同时使用。")
    if args.manifest is not None and (args.scenarios or args.row_range is not None):
        parser.error("--manifest 的每个样本自带 row_range，不能与 --scenarios/--row-range 同用。")

    try:
        if args.manifest is not None:
            manifest_path = args.manifest
            if not manifest_path.is_absolute():
                manifest_path = (Path.cwd() / manifest_path).resolve()
            entries = _manifest_entries(manifest_path)
            payload = _build_payload(
                entries,
                None,
                mode="manifest",
                manifest=_display_path(manifest_path),
            )
        else:
            specs = _select_specs(args.case, args.all)
            entries = _entries(specs, args)
            payload = _build_payload(entries, args.row_range)
    except (FileNotFoundError, ValueError, GridInputError, ImageInputError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if args.out is not None:
        out_path = args.out if args.out.is_absolute() else (Path.cwd() / args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(_format_text(payload))

    mismatches = [
        case.get("case_id") or case.get("sample_id")
        for case in entries
        if case.get("expected_check") and not case["expected_check"]["matches"]
    ]
    if mismatches:
        print(f"error: 以下案例与预期不一致：{', '.join(mismatches)}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
