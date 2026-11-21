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
