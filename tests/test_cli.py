"""CLI 基线端到端测试：结构化输出、范围场景、与管线/界面的候选一致性。"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(
        [sys.executable, str(ROOT / "cli.py"), *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        timeout=120,
    )


def _payload(*args: str) -> dict:
    completed = _run_cli(*args)
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


def test_cli_all_json_reports_candidate_sets() -> None:
    payload = _payload("--all", "--json")
    assert payload["schema_version"] == "knitalign.baseline.v1"
    assert payload["case_count"] == 2
    assert payload["config"]["match"]["min_score"] == 0.82
    assert payload["config"]["match"]["min_coverage"] == 0.60
    assert payload["config"]["match"]["ambiguity_margin"] == 0.02

    cases = {case["case_id"]: case for case in payload["cases"]}
    case1 = cases["case1_unique"]
    assert case1["material"].startswith("程序生成的合成图像")
    assert case1["source"]["chart"] == "examples/case1_unique/chart.png"
    assert case1["ground_truth_last_completed_row"] == 23
    assert case1["expected_check"]["matches"] is True
    assert case1["result"]["status"] == "unique"
    candidate = case1["result"]["candidates"][0]
    assert candidate["window_1based"] == [19, 23]
    assert candidate["last_completed_row"] == 23
    assert candidate["next_row"] == 24
    assert candidate["next_label"] == "24"
    assert candidate["score"] == 1.0
    assert candidate["coverage"] == 1.0
    assert candidate["diff_count"] == 0

    case2 = cases["case2_repeat"]
    assert case2["expected_check"]["matches"] is True
    assert case2["expected_check"]["comparison"] == "candidate_set"
    assert case2["result"]["status"] == "multiple"
    windows = [candidate["window_1based"] for candidate in case2["result"]["candidates"]]
    assert windows == [[4, 8], [12, 16], [20, 24], [28, 32]]
    assert [c["last_completed_row"] for c in case2["result"]["candidates"]] == [8, 16, 24, 32]
    last = case2["result"]["candidates"][-1]
    assert last["is_last_window"] is True
    assert last["next_row"] is None
    assert last["next_label"] == "若此候选正确，图解已完成"


def test_cli_row_range_narrows_to_single_candidate() -> None:
    payload = _payload("--case", "case2_repeat", "--row-range", "20-26", "--json")
    case = payload["cases"][0]
    assert case["row_range"] == [20, 26]
    assert case["result"]["status"] == "unique"
    assert case["result"]["candidate_count"] == 1
    candidate = case["result"]["candidates"][0]
    assert candidate["window_1based"] == [20, 24]
    assert candidate["last_completed_row"] == 24
    assert candidate["next_row"] == 25
    assert candidate["is_last_window"] is False
    assert case["expected_check"]["matches"] is True


def test_cli_scenarios_match_expected(tmp_path: Path) -> None:
    out_file = tmp_path / "baseline.json"
    payload = _payload("--all", "--scenarios", "--json", "--out", str(out_file))
    assert out_file.exists()
    on_disk = json.loads(out_file.read_text(encoding="utf-8"))
    assert on_disk["case_count"] == 4
    assert payload["case_count"] == 4
    by_key = {(case["case_id"], tuple(case["row_range"] or [])): case for case in payload["cases"]}
    assert by_key[("case2_repeat", (20, 26))]["result"]["status"] == "unique"
    assert by_key[("case2_repeat", (20, 26))]["result"]["candidates"][0]["window_1based"] == [20, 24]
    for case in payload["cases"]:
        assert case["expected_check"]["matches"] is True


def test_cli_and_pipeline_produce_same_candidates() -> None:
    from core.pipeline import load_case, run_case

    cases = [
        ("case1_unique", None),
        ("case2_repeat", None),
        ("case2_repeat", (20, 26)),
    ]
    for case_id, row_range in cases:
        spec = load_case(ROOT / "examples" / case_id)
        pipeline_result = run_case(spec.case_dir, row_range).result
        args = ["--case", case_id, "--json"]
        if row_range is not None:
            args += ["--row-range", f"{row_range[0]}-{row_range[1]}"]
        payload = _payload(*args)
        cli_result = payload["cases"][0]["result"]
        assert cli_result["status"] == pipeline_result.status
        assert [c["window_1based"] for c in cli_result["candidates"]] == [
            list(c.window_1based) for c in pipeline_result.candidates
        ]
        assert [c["score"] for c in cli_result["candidates"]] == [
            round(float(c.score), 6) for c in pipeline_result.candidates
        ]


def test_cli_text_output_does_not_show_next_row_after_last() -> None:
    completed = _run_cli("--all")
    assert completed.returncode == 0, completed.stderr
    text = completed.stdout
    assert "KnitAlign baseline" in text
    assert "第 28–32 行 | 最近完成 32 | 下一行 若此候选正确，图解已完成" in text
    assert "下一行 33" not in text
    assert "按候选集比较" in text


def test_cli_manifest_runs_real_sample_schema(tmp_path: Path) -> None:
    examples = ROOT / "examples"
    case1 = json.loads((examples / "case1_unique" / "case.json").read_text(encoding="utf-8"))
    case2 = json.loads((examples / "case2_repeat" / "case.json").read_text(encoding="utf-8"))
    manifest = {
        "schema_version": "knitalign.samples.v1",
        "samples": [
            {
                "sample_id": "S1",
                "group_id": "case1",
                "material": "synthetic-check",
                "chart": str((examples / "case1_unique" / "chart.png").resolve()),
                "chart_rows": case1["chart"]["rows"],
                "chart_stitches": case1["chart"]["stitches"],
                "chart_rect": case1["chart"]["rect"],
                "photo": str((examples / "case1_unique" / "photo.png").resolve()),
                "photo_rows": case1["photo"]["rows"],
                "photo_stitches": case1["photo"]["stitches"],
                "photo_corners": case1["photo"]["corners"],
                "true_last_completed_row": 23,
            },
            {
                "sample_id": "S2",
                "group_id": "case2",
                "material": "synthetic-check",
                "chart": str((examples / "case2_repeat" / "chart.png").resolve()),
                "chart_rows": case2["chart"]["rows"],
                "chart_stitches": case2["chart"]["stitches"],
                "chart_rect": case2["chart"]["rect"],
                "photo": str((examples / "case2_repeat" / "photo.png").resolve()),
                "photo_rows": case2["photo"]["rows"],
                "photo_stitches": case2["photo"]["stitches"],
                "photo_corners": case2["photo"]["corners"],
                "true_last_completed_row": 24,
            },
            {
                "sample_id": "S3",
                "group_id": "case2",
                "material": "synthetic-check",
                "chart": str((examples / "case2_repeat" / "chart.png").resolve()),
                "chart_rows": case2["chart"]["rows"],
                "chart_stitches": case2["chart"]["stitches"],
                "chart_rect": case2["chart"]["rect"],
                "photo": str((examples / "case2_repeat" / "photo.png").resolve()),
                "photo_rows": case2["photo"]["rows"],
                "photo_stitches": case2["photo"]["stitches"],
                "photo_corners": case2["photo"]["corners"],
                "true_last_completed_row": 24,
                "row_range": [20, 26],
            },
        ],
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    payload = _payload("--manifest", str(manifest_path), "--json")
    assert payload["mode"] == "manifest"
    assert payload["case_count"] == 3
    samples = {case["sample_id"]: case for case in payload["cases"]}
    assert samples["S1"]["ground_truth_check"]["outcome"] == "unique_correct"
    assert samples["S1"]["result"]["candidates"][0]["window_1based"] == [19, 23]
    assert samples["S2"]["ground_truth_check"]["outcome"] == "multiple_covers"
    assert samples["S2"]["ground_truth_check"]["candidate_covers_truth"] is True
    assert samples["S3"]["ground_truth_check"]["outcome"] == "unique_correct"
    assert samples["S3"]["result"]["candidates"][0]["last_completed_row"] == 24
    assert samples["S3"]["row_range"] == [20, 26]


def test_cli_unknown_case_fails_cleanly() -> None:
    completed = _run_cli("--case", "does_not_exist", "--json")
    assert completed.returncode == 1
    assert "未知案例" in completed.stderr
