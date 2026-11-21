"""「织到哪一行了？」Streamlit 本地界面。

启动::

    python -m streamlit run app.py

支持两条路径：
* 首页两个一键演示（合成素材，答案已知）。
* 上传自己的配色图解和织片照片，框选、标点、预览并定位。

所有图片只在本机内存中处理，不发送到远端。
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import cv2
import numpy as np
import streamlit as st

from core.chart import read_chart
from core.draw import draw_texts
from core.imageio import ImageInputError, decode_image_bytes, encode_png, load_image, to_rgb
from core.photo import read_photo
from core.pipeline import LocateResult, list_cases, load_case, locate, run_case
from core.render import render_chart
from core.types import (
    STATUS_HELP,
    STATUS_LABELS,
    STATUS_MULTIPLE,
    STATUS_UNIQUE,
    Candidate,
    GridInputError,
)

ROOT = Path(__file__).resolve().parent
EXAMPLES = ROOT / "examples"

st.set_page_config(
    page_title="织到哪一行了？",
    page_icon="🧶",
    layout="wide",
    initial_sidebar_state="collapsed",
)


def _init_state() -> None:
    defaults = {
        "mode": "home",
        "case_id": None,
        "result": None,
        "result_signature": None,
        "result_error": None,
        "result_error_signature": None,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def _clear_result() -> None:
    st.session_state.result = None
    st.session_state.result_signature = None
    st.session_state.result_error = None
    st.session_state.result_error_signature = None


def _go_home() -> None:
    st.session_state.mode = "home"
    st.session_state.case_id = None
    _clear_result()
    for key in ("demo_range_enabled", "demo_lo", "demo_hi", "demo_sig"):
        st.session_state.pop(key, None)


def _start_demo(case_id: str) -> None:
    st.session_state.mode = "demo"
    st.session_state.case_id = case_id
    _clear_result()
    for key in ("demo_range_enabled", "demo_lo", "demo_hi", "demo_sig"):
        st.session_state.pop(key, None)


def _apply_query_params() -> None:
    if st.session_state.get("_qp_applied"):
        return
    params = st.query_params
    case_param = params.get("case")
    if not case_param:
        return
    st.session_state["_qp_applied"] = True
    case_ids = {path.name for path in list_cases(EXAMPLES)}
    if case_param not in case_ids:
        return
    st.session_state.mode = "demo"
    st.session_state.case_id = case_param
    _clear_result()
    range_param = params.get("range")
    if range_param:
        try:
            lo_text, hi_text = str(range_param).split("-", 1)
            lo, hi = int(lo_text), int(hi_text)
        except (ValueError, TypeError):
            return
        if 1 <= lo <= hi <= 120:
            st.session_state.demo_range_enabled = True
            st.session_state.demo_lo = lo
            st.session_state.demo_hi = hi


def _hash_bytes(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()


def _range_controls(prefix: str, chart_rows: int) -> tuple[tuple[int, int] | None, str | None]:
    enabled = st.checkbox(
        "限定最近完成行的范围（可选）",
        key=f"{prefix}_range_enabled",
        help="只在指定的“最近完成行”范围内搜索。适用于已知大概进度、或想排除重复花纹的情况。",
    )
    col1, col2 = st.columns(2)
    lo_key = f"{prefix}_lo"
    hi_key = f"{prefix}_hi"
    lo_kwargs = {
        "label": "最近完成行下限",
        "min_value": 1,
        "max_value": max(1, chart_rows),
        "step": 1,
        "key": lo_key,
        "disabled": not enabled,
    }
    hi_kwargs = {
        "label": "最近完成行上限",
        "min_value": 1,
        "max_value": max(1, chart_rows),
        "step": 1,
        "key": hi_key,
        "disabled": not enabled,
    }
    if lo_key not in st.session_state:
        lo_kwargs["value"] = 1
    if hi_key not in st.session_state:
        hi_kwargs["value"] = max(1, chart_rows)
    lo = col1.number_input(**lo_kwargs)
    hi = col2.number_input(**hi_kwargs)
    if not enabled:
        return None, None
    lo_i, hi_i = int(lo), int(hi)
    if lo_i > hi_i:
        return None, f"最近完成行范围的 lower bound（{lo_i}）大于 upper bound（{hi_i}），请调整。"
    if hi_i > chart_rows:
        return None, f"最近完成行范围上限（{hi_i}）超过图解总行数（{chart_rows}）。"
    return (lo_i, hi_i), None


def _expected_text(spec) -> str:
    expected = spec.expected
    if expected["status"] == STATUS_UNIQUE:
        first, last = expected["windows_1based"][0]
        return (
            f"演示预期：唯一候选，图解第 {first}–{last} 行；"
            f"最近完成第 {expected['last_completed_rows'][0]} 行，下一行第 {expected['next_rows'][0]} 行。"
        )
    if expected["status"] == STATUS_MULTIPLE:
        windows = "、".join(f"第 {a}–{b} 行" for a, b in expected["windows_1based"])
        return (
            f"演示预期：多个候选（{windows}）；这些位置的可见配色相同，"
            "仅凭这张照片无法区分，系统应保留全部候选。"
        )
    return f"演示预期：{STATUS_LABELS.get(expected['status'], expected['status'])}。"


def _expected_check(result, candidate: Candidate | None, expected: dict) -> None:
    if expected is None:
        return
    expected_windows = {tuple(pair) for pair in expected["windows_1based"]}
    if result.status != expected["status"]:
        st.error(f"与演示预期不一致：预期状态 {expected['status']}，实际 {result.status}。")
        return
    if result.status in (STATUS_UNIQUE, STATUS_MULTIPLE):
        actual_windows = {tuple(c.window_1based) for c in result.candidates}
        if actual_windows != expected_windows:
            st.error(f"与演示预期不一致：预期候选 {sorted(expected_windows)}，实际 {sorted(actual_windows)}。")
            return
        if candidate is not None and tuple(candidate.window_1based) not in expected_windows:
            st.error("当前候选不在演示预期范围内。")
            return
        st.success("与演示预期一致。✓")
    else:
        st.success("与演示预期一致。✓")


def _show_diff_cells(result: LocateResult, candidate: Candidate) -> None:
    observed = result.photo.observed
    diff = candidate.diff_cells
    with st.expander(f"差异格（{len(diff)} 个）", expanded=False):
        if not diff:
            st.write("没有差异格：照片中的配色与候选窗口完全一致。")
            return
        rows = [
            {
                "观测行（1=观测区最下面一行）": obs_row + 1,
                "图解行": candidate.start_row + obs_row + 1,
                "针（1=最左）": col + 1,
                "该格权重": round(float(observed.weights[obs_row, col]), 3),
            }
            for obs_row, col in diff
        ]
        st.dataframe(rows, use_container_width=True, hide_index=True)
        st.caption("差异格通常来自采样偏移、阴影或线材反光；如果数量很多，请先检查角点与光照。")


def _show_result(
    result: LocateResult,
    *,
    expected: dict | None = None,
    true_last_completed: int | None = None,
    signature: str = "",
) -> None:
    match_result = result.result
    if match_result.status == STATUS_UNIQUE:
        st.success(f"**{STATUS_LABELS[match_result.status]}**：{match_result.reason}")
    elif match_result.status == STATUS_MULTIPLE:
        st.warning(f"**{STATUS_LABELS[match_result.status]}**：{match_result.reason}")
    else:
        st.error(f"**{STATUS_LABELS[match_result.status]}**：{match_result.reason}")
        st.caption(STATUS_HELP[match_result.status])

    if match_result.status not in (STATUS_UNIQUE, STATUS_MULTIPLE) or not match_result.candidates:
        left, right = st.columns(2)
        with left:
            st.image(
                to_rgb(result.photo.overlay),
                caption="校正照片：顶行＝最近完成行；绿/黄/红格＝采样权重",
            )
        with right:
            st.image(
                to_rgb(render_chart(result.chart, None)),
                caption="完整图解（没有高亮：证据不足，无法给出可信行号）",
            )
        return

    candidates = list(match_result.candidates)
    candidate = candidates[0]
    if len(candidates) > 1:
        labels = [
            f"候选 {index + 1}：图解第 {c.window_1based[0]}–{c.window_1based[1]} 行"
            f"（最近完成 {c.last_completed_row}，吻合度 {c.score:.1%}）"
            for index, c in enumerate(candidates)
        ]
        chosen = st.selectbox(
            "切换候选（同一张照片可解释的位置）",
            labels,
            key=f"candidate_choice_{signature[:10]}",
            help="重复花纹会让多个位置拥有相同或接近的配色；逐个查看，或在上方限定行号范围。",
        )
        candidate = candidates[labels.index(chosen)]
        st.caption("下面显示的是当前所选候选的高亮；所有候选都保存在结果里。")

    metrics = st.columns(4)
    metrics[0].metric("最近完成行", candidate.last_completed_row)
    metrics[1].metric(
        "下一行",
        "图解已完成" if match_result.chart_complete else candidate.next_row,
    )
    metrics[2].metric("加权吻合度", f"{candidate.score:.1%}")
    metrics[3].metric("有效覆盖率", f"{match_result.coverage:.0%}")

    if match_result.status == STATUS_MULTIPLE:
        st.info(
            "**这些位置的可见配色相同或接近**，仅凭当前照片无法判断真实进度。"
            "可补拍包含更早行的照片、增加可见行数，或在上方限定最近完成行范围。"
        )
    if match_result.chart_complete:
        st.info("**图解已完成**：观测窗口覆盖到图解最后一行，没有下一行。")
    if candidate.swapped:
        st.caption("照片与图解的两种颜色整体互换；匹配时已自动尝试颜色映射，行号不受影响。")

    chart_render = render_chart(
        result.chart, candidate, diff_cells=candidate.diff_cells
    )
    left, right = st.columns(2)
    with left:
        st.image(
            to_rgb(result.photo.overlay),
            caption="校正照片：顶行＝最近完成行；绿/黄/红格＝权重 高/中/低",
        )
    with right:
        st.image(
            to_rgb(chart_render),
            caption="图解高亮：黄色窗口＝候选行；橙线＝最近完成行；绿线＝下一行",
        )

    _show_diff_cells(result, candidate)

    if true_last_completed:
        st.caption(f"该演示素材的已知停织行：第 {true_last_completed} 行（合成素材，用于核对）。")

    if expected is not None:
        _expected_check(match_result, candidate, expected)

    with st.expander("结果图下载", expanded=False):
        col1, col2 = st.columns(2)
        col1.download_button(
            "下载高亮图解 PNG",
            data=encode_png(chart_render),
            file_name="chart_highlight.png",
            mime="image/png",
            key=f"download_chart_{signature[:10]}",
        )
        col2.download_button(
            "下载校正照片 PNG",
            data=encode_png(result.photo.overlay),
            file_name="photo_overlay.png",
            mime="image/png",
            key=f"download_photo_{signature[:10]}",
        )

    with st.expander("分数与状态怎么读？", expanded=False):
        thresholds = match_result.thresholds
        st.markdown(
            f"""
- **加权吻合度**：颜色一致的格子权重之和 ÷ 有效格子权重之和（0–100%）。干净合成图接近 100%，
  正常实拍常在 85%–97%。低于 {thresholds.get('min_score', 0.82):.0%} 时不会给出候选。
- **有效覆盖率**：权重达到阈值的格子占比；低于 {thresholds.get('min_coverage', 0.60):.0%} 视为证据不足。
- **唯一 / 多个候选**：最佳候选与次佳候选的分差 ≤ {thresholds.get('ambiguity_margin', 0.02):.0%} 时，
  视为“相同或接近”，全部保留。
- 权重范围 0–1；绿框 ≥0.7，黄框 0.35–0.7，红框 <0.35，红叉表示该格无有效证据。
"""
        )


def _render_home() -> None:
    st.title("织到哪一行了？")
    st.caption("放下一块织到半途的双色提花织片，重新拿起时，找回该继续的那一行。")
    st.markdown(
        """
**它做什么**：同时读取配色图解和织片正面照片，在图解上高亮出最可能对应的连续行，
告诉你「最近完成哪一行」以及「下一行从哪里开始」。如果花纹重复，会保留所有可能位置。

**首版适用范围**：矩形、固定针数、双色平针提花；图解一格对应一针，图解宽度等于照片中织片完整针数；
拍完一整行后暂停；照片正面朝相机、针杆在上、能看到完整宽度。支持 PNG / JPEG。
文字图解、加减针、半行进度、只含一个横向重复单元的图解不支持。
"""
    )

    cases = list_cases(EXAMPLES)
    columns = st.columns(len(cases) + 1)
    for index, case_dir in enumerate(cases):
        spec = load_case(case_dir)
        with columns[index]:
            st.subheader(spec.name)
            st.write(spec.summary)
            try:
                st.image(
                    to_rgb(load_image(spec.photo_path)),
                    caption="合成织片照片（程序生成，非实拍）",
                )
            except ImageInputError:
                st.warning("演示图片缺失，请先运行 `python examples/build_examples.py`。")
            st.caption(_expected_text(spec))
            if st.button("运行演示", key=f"run_{spec.case_id}", type="primary"):
                _start_demo(spec.case_id)
                st.rerun()
    with columns[-1]:
        st.subheader("上传自己的图片")
        st.write("按提示框选图解区域、标记照片四角，再输入行数与针数。")
        if st.button("上传自己的图片", key="go_upload"):
            st.session_state.mode = "upload"
            _clear_result()
            st.rerun()

    st.divider()
    with st.expander("拍摄方法与选区示意", expanded=False):
        st.markdown(
            """
1. **正面拍摄**：镜头正对织片，针杆在上；不要从侧面或背面拍。
2. **完整宽度**：左右两侧最外一针都要在画面内；可以上下超过，但左右不能裁掉针目。
3. **平铺**：把织片放在平整、纯色的背景上，避免手指、阴影和强反光压住针目。
4. **标记四角**：左上 → 右上 → 右下 → 左下。**上方边**贴着最新完成的整行的上边缘；
   **下方边**落在更早一个完整行的下边缘。可见行数 = 两边之间的完整行数。
5. **输入行数/针数**：行数是可见的完整行数，针数是照片中织片的完整宽度针数。
"""
        )
        guide = ROOT / "docs" / "capture_guide.png"
        if guide.exists():
            st.image(to_rgb(load_image(guide)), caption="选区与角点示意（合成示意，非实拍）")

    st.divider()
    st.caption("图片仅在本机内存中处理；结果依赖于照片是否清晰、选区是否贴合行边缘。")


def _render_demo() -> None:
    case_id = st.session_state.case_id
    if not case_id:
        _go_home()
        st.rerun()
        return
    case_dir = EXAMPLES / case_id
    if not (case_dir / "case.json").exists():
        st.error("演示样例缺失。请在项目根目录运行 `python examples/build_examples.py` 后重试。")
        if st.button("← 返回首页"):
            _go_home()
            st.rerun()
        return
    spec = load_case(case_dir)

    top_left, top_right = st.columns([1, 5])
    with top_left:
        if st.button("← 返回首页", key="home_from_demo"):
            _go_home()
            st.rerun()
    with top_right:
        st.header(spec.name)
    st.caption(spec.summary)
    st.info(_expected_text(spec))

    with st.expander("查看演示素材（合成图像，非实拍）", expanded=False):
        col1, col2 = st.columns(2)
        col1.image(to_rgb(load_image(spec.chart_path)), caption="配色图解")
        col2.image(to_rgb(load_image(spec.photo_path)), caption="织片正面照片（合成渲染）")

    st.subheader("定位设置")
    row_range, range_error = _range_controls("demo", spec.chart_rows)
    if range_error:
        st.error(range_error)
        return

    signature = f"demo|{case_id}|{row_range}"
    if st.session_state.get("demo_sig") != signature or st.session_state.get("result") is None:
        try:
            with st.spinner("读取图解与照片并定位…"):
                result = run_case(case_dir, row_range)
        except (GridInputError, ImageInputError, ValueError) as exc:
            st.error(f"演示运行失败：{exc}")
            return
        st.session_state.result = result
        st.session_state.demo_sig = signature
        st.session_state.result_signature = signature

    result = st.session_state.result
    if result is None:
        st.warning("还没有结果，请稍后重试或返回首页重新运行演示。")
        return
    expected_for_check = spec.expected
    if row_range is not None:
        expected_for_check = None
        for scenario in spec.expected.get("scenarios", []):
            if tuple(scenario["row_range"]) == tuple(row_range):
                expected_for_check = scenario
                break
    _show_result(
        result,
        expected=expected_for_check,
        true_last_completed=spec.true_last_completed_row,
        signature=signature,
    )


def _draw_quad(image: np.ndarray, corners, color=(0, 200, 0)) -> np.ndarray:
    preview = image.copy()
    pts = np.round(np.asarray(corners, dtype=np.float64)).astype(np.int32)
    cv2.polylines(preview, [pts], True, color, 2, cv2.LINE_AA)
    for point in pts:
        cv2.circle(preview, tuple(point), 4, color, -1, cv2.LINE_AA)
    return preview


def _draw_rect(image: np.ndarray, rect) -> np.ndarray:
    preview = image.copy()
    x0, y0, x1, y1 = (int(round(v)) for v in rect)
    cv2.rectangle(preview, (x0, y0), (x1, y1), (0, 200, 0), 2, cv2.LINE_AA)
    return draw_texts(
        preview,
        [("图解选区", (x0 + 4, max(14, y0 + 16)), (0, 140, 0), 14, "la")],
    )


def _render_upload() -> None:
    if st.button("← 返回首页", key="home_from_upload"):
        _go_home()
        st.rerun()
    st.header("上传自己的图片")
    st.caption("先上传配色图解和织片正面照片，再按预览调整选区/角点。所有处理都在本机内存中完成。")

    upload_col1, upload_col2 = st.columns(2)
    chart_file = upload_col1.file_uploader(
        "1）配色图解（PNG / JPEG）",
        type=["png", "jpg", "jpeg"],
        key="chart_upload",
    )
    photo_file = upload_col2.file_uploader(
        "2）织片正面照片（PNG / JPEG）",
        type=["png", "jpg", "jpeg"],
        key="photo_upload",
    )
    if chart_file is None or photo_file is None:
        st.info("请同时上传图解和照片。缺少任一张时无法定位。")
        st.caption("也可以先返回首页，用两个演示案例熟悉操作。")
        return

    chart_bytes = chart_file.getvalue()
    photo_bytes = photo_file.getvalue()
    try:
        chart_image = decode_image_bytes(chart_bytes, source="配色图解")
        photo_image = decode_image_bytes(photo_bytes, source="织片照片")
    except ImageInputError as exc:
        st.error(str(exc))
        return
    chart_hash = _hash_bytes(chart_bytes)[:10]
    photo_hash = _hash_bytes(photo_bytes)[:10]
    chart_height, chart_width = chart_image.shape[:2]
    photo_height, photo_width = photo_image.shape[:2]

    st.divider()
    st.subheader("图解区域与行列数")
    grid_cols = st.columns(5)
    chart_rows = grid_cols[0].number_input(
        "图解行数", min_value=1, max_value=400, value=32, step=1, key="chart_rows_input"
    )
    chart_cols = grid_cols[1].number_input(
        "图解针数", min_value=1, max_value=400, value=12, step=1, key="chart_cols_input"
    )
    chart_rect = (
        grid_cols[2].number_input(
            "x0（左）", min_value=0.0, max_value=float(chart_width), value=0.0, step=1.0,
            key=f"chart_x0_{chart_hash}",
        ),
        grid_cols[3].number_input(
            "y0（上）", min_value=0.0, max_value=float(chart_height), value=0.0, step=1.0,
            key=f"chart_y0_{chart_hash}",
        ),
        grid_cols[4].number_input(
            "x1（右）", min_value=0.0, max_value=float(chart_width), value=float(chart_width), step=1.0,
            key=f"chart_x1_{chart_hash}",
        ),
    )
    y1 = st.number_input(
        "y1（下）", min_value=0.0, max_value=float(chart_height), value=float(chart_height), step=1.0,
        key=f"chart_y1_{chart_hash}",
    )
    chart_rect = (chart_rect[0], chart_rect[1], chart_rect[2], float(y1))
    st.caption(
        "选区是图解网格的**外边界**（含最外圈网格线）。如果图解有白边，请把选区收到网格范围内；"
        "预览中的白点是采样位置，左侧数字是图解行号。"
    )

    chart_result = None
    chart_error = None
    try:
        chart_result = read_chart(chart_image, chart_rect, int(chart_rows), int(chart_cols))
    except (GridInputError, ValueError) as exc:
        chart_error = str(exc)
    if chart_result is not None:
        st.image(
            to_rgb(chart_result.preview),
            caption=f"图解采样预览：{int(chart_rows)} 行 × {int(chart_cols)} 针；白点＝格内采样位置",
        )
        palette = chart_result.chart.palette
        st.caption(
            "识别到的两种颜色（BGR）："
            f"深色 {palette[0]}，浅色 {palette[1]}。"
            "行号自下而上，内部第 0 行 = 图解第 1 行。"
        )
    else:
        st.image(to_rgb(_draw_rect(chart_image, chart_rect)), caption="图解选区预览")
        st.error(chart_error)

    st.divider()
    st.subheader("照片四角与行列数")
    photo_row_cols = st.columns(3)
    photo_rows = photo_row_cols[0].number_input(
        "可见完整行数", min_value=1, max_value=400, value=5, step=1, key="photo_rows_input"
    )
    follow_chart = photo_row_cols[1].checkbox(
        "照片针数跟随图解针数",
        value=True,
        key="photo_stitches_follow",
        help="照片覆盖织片完整宽度时，针数通常与图解针数相同。取消勾选可单独输入。",
    )
    if follow_chart:
        photo_stitches = int(chart_cols)
        photo_row_cols[2].metric("照片针数", photo_stitches, help="跟随图解针数")
    else:
        photo_stitches = int(
            photo_row_cols[2].number_input(
                "照片针数", min_value=1, max_value=400, value=int(chart_cols), step=1,
                key="photo_stitches_input",
            )
        )
    st.caption(
        "角点顺序：左上 → 右上 → 右下 → 左下。**上边**贴着最新完成整行的上边缘，"
        "**下边**落在更早一整行的下边缘；可见行数就是这两条边之间的完整行数。"
    )

    inset = max(2, int(round(min(photo_width, photo_height) * 0.04)))
    default_corners = {
        "tl": (inset, inset),
        "tr": (max(inset, photo_width - 1 - inset), inset),
        "br": (max(inset, photo_width - 1 - inset), max(inset, photo_height - 1 - inset)),
        "bl": (inset, max(inset, photo_height - 1 - inset)),
    }
    corner_values: dict[str, tuple[float, float]] = {}
    corner_cols = st.columns(4)
    for index, (name, label) in enumerate(
        (("tl", "左上"), ("tr", "右上"), ("br", "右下"), ("bl", "左下"))
    ):
        with corner_cols[index]:
            st.markdown(f"**{label}**")
            x = st.number_input(
                f"{label} x", min_value=0.0, max_value=float(max(0, photo_width - 1)),
                value=float(default_corners[name][0]), step=1.0, key=f"corner_{name}_x_{photo_hash}",
            )
            y = st.number_input(
                f"{label} y", min_value=0.0, max_value=float(max(0, photo_height - 1)),
                value=float(default_corners[name][1]), step=1.0, key=f"corner_{name}_y_{photo_hash}",
            )
            corner_values[name] = (float(x), float(y))
    corners = (
        corner_values["tl"],
        corner_values["tr"],
        corner_values["br"],
        corner_values["bl"],
    )

    photo_result = None
    photo_error = None
    try:
        photo_result = read_photo(photo_image, corners, photo_stitches, int(photo_rows))
    except (GridInputError, ValueError) as exc:
        photo_error = str(exc)
    if photo_result is not None:
        st.image(
            to_rgb(photo_result.source_preview),
            caption="照片角点预览：橙线＝最新完整行上边缘；绿框＝选区",
        )
        st.image(
            to_rgb(photo_result.overlay),
            caption="校正与采样预览：顶行＝最近完成行；格边框 绿/黄/红＝权重 高/中/低",
        )
        with st.expander("质量提示与采样统计", expanded=True):
            quality = photo_result.quality
            stat_cols = st.columns(4)
            stat_cols[0].metric("有效覆盖率", f"{quality['coverage']:.0%}")
            stat_cols[1].metric("平均权重", f"{quality['mean_weight']:.2f}")
            stat_cols[2].metric("颜色色差（Lab）", f"{quality['color_separation']:.0f}")
            stat_cols[3].metric("清晰度指标", f"{quality['blur_score']:.0f}")
            for note in photo_result.notes:
                st.write(f"- {note}")
    else:
        st.image(to_rgb(_draw_quad(photo_image, corners)), caption="照片四角预览")
        st.error(photo_error)

    st.divider()
    st.subheader("定位")
    row_range, range_error = _range_controls("upload", int(chart_rows))
    if range_error:
        st.error(range_error)

    ready = chart_result is not None and photo_result is not None and range_error is None

    signature = "|".join(
        [
            "upload",
            chart_hash,
            photo_hash,
            str(int(chart_rows)),
            str(int(chart_cols)),
            ",".join(f"{v:.1f}" for v in chart_rect),
            str(int(photo_rows)),
            str(int(photo_stitches)),
            ",".join(f"{x:.1f}:{y:.1f}" for x, y in corners),
            str(row_range),
        ]
    )

    if st.button(
        "开始定位",
        type="primary",
        disabled=not ready,
        key="locate_button",
        help=None if ready else "请先修正上方图解/照片的错误。",
    ):
        try:
            with st.spinner("正在定位…"):
                result = locate(
                    chart_image,
                    chart_rect,
                    int(chart_rows),
                    int(chart_cols),
                    photo_image,
                    corners,
                    int(photo_rows),
                    int(photo_stitches),
                    row_range,
                )
        except (GridInputError, ImageInputError, ValueError) as exc:
            st.session_state.result = None
            st.session_state.result_signature = None
            st.session_state.result_error = str(exc)
            st.session_state.result_error_signature = signature
        else:
            st.session_state.result = result
            st.session_state.result_signature = signature
            st.session_state.result_error = None
            st.session_state.result_error_signature = None

    current_error = st.session_state.get("result_error")
    if current_error and st.session_state.get("result_error_signature") == signature:
        st.error(f"定位失败：{current_error}")

    stored = st.session_state.get("result")
    if stored is not None:
        if st.session_state.get("result_signature") == signature:
            _show_result(stored, signature=signature)
        else:
            st.warning(
                "输入或参数已改变，**旧结果已失效**，不会再显示旧结论。"
                "请确认上方预览后重新点击「开始定位」。"
            )

    if stored is None and not current_error:
        st.caption("确认图解采样预览和照片角点预览无误后，点击「开始定位」。")


def main() -> None:
    _init_state()
    _apply_query_params()
    mode = st.session_state.mode
    if mode == "demo":
        _render_demo()
    elif mode == "upload":
        _render_upload()
    else:
        _render_home()


main()
