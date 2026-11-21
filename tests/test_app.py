from __future__ import annotations

import hashlib
import json
from pathlib import Path

from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]


def _new_app() -> AppTest:
    return AppTest.from_file(str(ROOT / "app.py"), default_timeout=120).run()


def _assert_clean(app: AppTest) -> None:
    assert not app.exception, [str(item.value) for item in app.exception]


def test_home_offers_two_demos_and_upload() -> None:
    app = _new_app()
    _assert_clean(app)
    assert [title.value for title in app.title] == ["织到哪一行了？"]
    labels = [button.label for button in app.button]
    assert labels.count("运行演示") == 2
    assert "上传自己的图片" in labels
    assert any("首版适用范围" in markdown.value for markdown in app.markdown)


def test_demo1_unique_result_and_expected_check() -> None:
    app = _new_app()
    app.button(key="run_case1_unique").click().run()
    _assert_clean(app)
    result = app.session_state["result"]
    assert result.result.status == "unique"
    assert [c.window_1based for c in result.result.candidates] == [(19, 23)]
    metrics = {metric.label: metric.value for metric in app.metric}
    assert metrics["最近完成行"] == "23"
    assert metrics["下一行"] == "24"
    assert any("与演示预期一致" in item.value for item in app.success)
    assert any("已知停织行：第 23 行" in item.value for item in app.caption)


def test_demo2_multiple_candidates_switch_and_range() -> None:
    app = _new_app()
    app.button(key="run_case2_repeat").click().run()
    _assert_clean(app)
    result = app.session_state["result"]
    assert result.result.status == "multiple"
    assert [c.window_1based for c in result.result.candidates] == [
        (4, 8),
        (12, 16),
        (20, 24),
        (28, 32),
    ]
    assert len(app.selectbox) == 1
    options = app.selectbox[0].options
    assert len(options) == 4

    app.selectbox[0].select(options[2]).run()
    _assert_clean(app)
    metrics = {metric.label: metric.value for metric in app.metric}
    assert metrics["最近完成行"] == "24"
    assert metrics["下一行"] == "25"

    # 切到第 28–32 行：不能显示不存在的“下一行 33”，且要保留多候选歧义
    app.selectbox[0].select(options[3]).run()
    _assert_clean(app)
    metrics = {metric.label: metric.value for metric in app.metric}
    assert metrics["最近完成行"] == "32"
    assert metrics["下一行"] == "若此候选正确，图解已完成"
    assert "33" not in metrics["下一行"]
    assert any("若此候选正确，图解已完成" in item.value for item in app.info)
    assert not any("下一行：第 33 行" in item.value for item in app.caption)

    # 切回第 20–24 行：下一行应恢复为 25
    app.selectbox[0].select(options[2]).run()
    _assert_clean(app)
    metrics = {metric.label: metric.value for metric in app.metric}
    assert metrics["最近完成行"] == "24"
    assert metrics["下一行"] == "25"

    app.get_by_key("demo_range_enabled").check().run()
    _assert_clean(app)
    app.get_by_key("demo_lo").set_value(20)
    app.get_by_key("demo_hi").set_value(26)
    app.run()
    _assert_clean(app)
    narrowed = app.session_state["result"]
    assert narrowed.result.status == "unique"
    assert [c.window_1based for c in narrowed.result.candidates] == [(20, 24)]
    metrics = {metric.label: metric.value for metric in app.metric}
    assert metrics["最近完成行"] == "24"
    assert not app.selectbox
    assert any("与演示预期一致" in item.value for item in app.success)


def test_deep_link_opens_narrowed_demo() -> None:
    app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=120)
    app.query_params["case"] = "case2_repeat"
    app.query_params["range"] = "20-26"
    app.run()
    _assert_clean(app)
    assert app.session_state["mode"] == "demo"
    assert app.session_state["case_id"] == "case2_repeat"
    result = app.session_state["result"]
    assert result.result.status == "unique"
    assert [c.window_1based for c in result.result.candidates] == [(20, 24)]
    metrics = {metric.label: metric.value for metric in app.metric}
    assert metrics["最近完成行"] == "24"
    assert any("与演示预期一致" in item.value for item in app.success)


def test_unique_last_row_shows_complete(tmp_path: Path, monkeypatch) -> None:
    import cv2

    from core.chart import read_chart
    from core.imageio import load_image
    from core.synth import render_photo

    source = ROOT / "examples" / "case1_unique"
    source_case = json.loads((source / "case.json").read_text(encoding="utf-8"))
    chart = read_chart(
        load_image(source / "chart.png"),
        tuple(source_case["chart"]["rect"]),
        source_case["chart"]["rows"],
        source_case["chart"]["stitches"],
    ).chart
    photo = render_photo(chart, 27, 5, seed=9191)

    examples = tmp_path / "examples"
    case_dir = examples / "last_row_unique"
    case_dir.mkdir(parents=True)
    (case_dir / "chart.png").write_bytes((source / "chart.png").read_bytes())
    ok, buffer = cv2.imencode(".png", photo.image)
    assert ok
    (case_dir / "photo.png").write_bytes(buffer.tobytes())
    case = {
        "id": "last_row_unique",
        "name": "末行唯一候选",
        "summary": "唯一候选覆盖第 28–32 行，用于验证末行显示。",
        "seed": 9191,
        "material": "程序生成的合成图像（非实拍）",
        "chart": {
            "file": "chart.png",
            "rows": source_case["chart"]["rows"],
            "stitches": source_case["chart"]["stitches"],
            "rect": source_case["chart"]["rect"],
        },
        "photo": {
            "file": "photo.png",
            "rows": 5,
            "stitches": source_case["chart"]["stitches"],
            "corners": [[round(float(x), 3), round(float(y), 3)] for x, y in photo.corners],
            "true_last_completed_row": 32,
        },
        "variants": {},
    }
    expected = {
        "material": "synthetic",
        "description": "唯一候选到图解最后一行。",
        "status": "unique",
        "windows_1based": [[28, 32]],
        "last_completed_rows": [32],
        "next_rows": [],
        "min_best_score": 0.99,
        "max_diff_cells": 0,
        "scenarios": [],
    }
    (case_dir / "case.json").write_text(json.dumps(case, ensure_ascii=False), encoding="utf-8")
    (case_dir / "expected.json").write_text(json.dumps(expected, ensure_ascii=False), encoding="utf-8")

    monkeypatch.setenv("KNITALIGN_EXAMPLES_DIR", str(examples))
    app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=120)
    app.query_params["case"] = "last_row_unique"
    app.run()
    _assert_clean(app)
    result = app.session_state["result"]
    assert result.result.status == "unique"
    assert [c.window_1based for c in result.result.candidates] == [(28, 32)]
    metrics = {metric.label: metric.value for metric in app.metric}
    assert metrics["最近完成行"] == "32"
    assert metrics["下一行"] == "图解已完成"
    assert any("图解已完成" in item.value for item in app.info)
    assert any("与演示预期一致" in item.value for item in app.success)
    assert any("已知停织行：第 32 行" in item.value for item in app.caption)


def _upload_case1(app: AppTest, examples: Path) -> tuple[str, str]:
    case = json.loads((examples / "case1_unique" / "case.json").read_text(encoding="utf-8"))
    chart_bytes = (examples / "case1_unique" / "chart.png").read_bytes()
    photo_bytes = (examples / "case1_unique" / "photo.png").read_bytes()
    chart_hash = hashlib.sha1(chart_bytes).hexdigest()[:10]
    photo_hash = hashlib.sha1(photo_bytes).hexdigest()[:10]

    app.button(key="go_upload").click().run()
    _assert_clean(app)
    app.file_uploader[0].set_value(("chart.png", chart_bytes, "image/png"))
    app.file_uploader[1].set_value(("photo.png", photo_bytes, "image/png"))
    app.run()
    _assert_clean(app)

    for key, value in (
        (f"chart_x0_{chart_hash}", case["chart"]["rect"][0]),
        (f"chart_y0_{chart_hash}", case["chart"]["rect"][1]),
        (f"chart_x1_{chart_hash}", case["chart"]["rect"][2]),
        (f"chart_y1_{chart_hash}", case["chart"]["rect"][3]),
    ):
        app.get_by_key(key).set_value(float(value))
    for name, (x, y) in zip(("tl", "tr", "br", "bl"), case["photo"]["corners"]):
        app.get_by_key(f"corner_{name}_x_{photo_hash}").set_value(float(x))
        app.get_by_key(f"corner_{name}_y_{photo_hash}").set_value(float(y))
    app.run()
    _assert_clean(app)
    return chart_hash, photo_hash


def test_upload_path_locate_and_stale_result(project_root: Path) -> None:
    examples = project_root / "examples"
    app = _new_app()
    chart_hash, _ = _upload_case1(app, examples)
    assert not app.error, [item.value for item in app.error]

    app.button(key="locate_button").click().run()
    _assert_clean(app)
    result = app.session_state["result"]
    assert result.result.status == "unique"
    assert [c.window_1based for c in result.result.candidates] == [(19, 23)]
    metrics = {metric.label: metric.value for metric in app.metric}
    assert metrics["最近完成行"] == "23"

    # 修改上游输入（图解右边界）后，旧结论必须隐藏
    app.get_by_key(f"chart_x1_{chart_hash}").set_value(300.0)
    app.run()
    _assert_clean(app)
    assert any("旧结果已失效" in item.value for item in app.warning)
    assert not any(metric.label == "最近完成行" for metric in app.metric)

    # 恢复并重新定位
    case = json.loads((examples / "case1_unique" / "case.json").read_text(encoding="utf-8"))
    app.get_by_key(f"chart_x1_{chart_hash}").set_value(float(case["chart"]["rect"][2]))
    app.run()
    app.button(key="locate_button").click().run()
    _assert_clean(app)
    metrics = {metric.label: metric.value for metric in app.metric}
    assert metrics["最近完成行"] == "23"
