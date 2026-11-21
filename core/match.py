"""纯函数定位：在参考图解中搜索与观测矩阵等高的连续行窗口。

评分（共享约定）
----------------
对每个候选窗口比较两种“整块一致”的颜色映射（相同 / 两种颜色互换）。
每种映射的分数 = 颜色一致的格子的权重之和 ÷ 有效格子的权重之和。
逐格权重 0–1；权重不超过 ``min_cell_weight`` 的格子视为无效证据。
最终分数取两种映射中的较大值，因此整体交换颜色标签不会改变行号。

结果状态
--------
* ``unique``：只有一个窗口达到最佳分数（分差 > ``ambiguity_margin``）。
* ``multiple``：多个窗口分数相同或接近，全部保留。
* ``insufficient``：覆盖不足、没有合法窗口或最佳吻合度低于阈值。
* ``input_error``：观测行数/针数与图解不匹配，或搜索范围非法。

函数不修改输入，也不依赖任何全局状态，便于脱离界面单独验证。
"""

from __future__ import annotations

import numpy as np

from .config import DEFAULT_MATCH_CONFIG, MatchConfig
from .types import (
    STATUS_INPUT_ERROR,
    STATUS_INSUFFICIENT,
    STATUS_MULTIPLE,
    STATUS_UNIQUE,
    Candidate,
    ChartGrid,
    GridInputError,
    MatchResult,
    ObservedGrid,
)


def _coerce_chart(chart) -> ChartGrid:
    if isinstance(chart, ChartGrid):
        return chart
    return ChartGrid(cells=chart)


def _coerce_observation(observation) -> ObservedGrid:
    if isinstance(observation, ObservedGrid):
        return observation
    if isinstance(observation, (tuple, list)) and len(observation) == 2:
        cells, weights = observation
        return ObservedGrid(cells=cells, weights=weights)
    arr = np.asarray(observation)
    if arr.ndim == 3 and arr.shape[2] == 2:
        return ObservedGrid(cells=arr[..., 0], weights=arr[..., 1])
    return ObservedGrid(cells=arr, weights=np.ones(arr.shape, dtype=np.float64))


def _parse_row_range(row_range, chart_rows: int) -> tuple[int, int] | str:
    if row_range is None:
        return 0, 0
    try:
        lo, hi = row_range
        lo = int(lo)
        hi = int(hi)
    except (TypeError, ValueError):
        return "最近完成行范围必须是两个整数（下限、上限）。"
    if lo > hi:
        return f"最近完成行范围下限（{lo}）大于上限（{hi}），请调整。"
    if lo < 1:
        return "最近完成行范围下限至少为 1。"
    if hi > chart_rows:
        return f"最近完成行范围上限（{hi}）超过图解总行数（{chart_rows}）。"
    return lo, hi


def _make_result(
    *,
    status: str,
    reason: str,
    chart: ChartGrid,
    observation: ObservedGrid,
    coverage: float,
    config: MatchConfig,
    row_range: tuple[int, int] | None,
    candidates: tuple[Candidate, ...] = (),
    best: Candidate | None = None,
    windows: int = 0,
) -> MatchResult:
    return MatchResult(
        status=status,
        candidates=candidates,
        best=best,
        reason=reason,
        coverage=float(coverage),
        observation_shape=observation.shape,
        chart_shape=chart.shape,
        row_range=row_range,
        thresholds=config.as_dict(),
        windows_searched=int(windows),
    )


def match(
    chart,
    observation,
    row_range: tuple[int, int] | None = None,
    *,
    config: MatchConfig | None = None,
) -> MatchResult:
    """在 ``chart`` 中定位 ``observation``。

    参数
    ----
    chart : ChartGrid 或二维 0/1 矩阵（内部顺序：行 0 = 图解底部）
    observation : ObservedGrid、``(cells, weights)`` 或二维 0/1 矩阵
        （二维矩阵等价于所有权重为 1）
    row_range : 可选 ``(下限, 上限)``，按**最近完成行**（一基）限制搜索范围
    config : 阈值配置，默认 ``DEFAULT_MATCH_CONFIG``

    返回
    ----
    MatchResult
    """
    config = config or DEFAULT_MATCH_CONFIG
    chart = _coerce_chart(chart)
    observation = _coerce_observation(observation)
    obs_rows, obs_stitches = observation.shape
    chart_rows, chart_stitches = chart.shape
    coverage = observation.coverage

    if observation.stitches != chart.stitches:
        return _make_result(
            status=STATUS_INPUT_ERROR,
            reason=(
                f"针数不一致：照片为 {obs_stitches} 针，图解为 {chart_stitches} 针。"
                "本版本要求照片覆盖图解完整宽度；请确认“完整针数”和图解宽度，并重新框选/标点。"
            ),
            chart=chart,
            observation=observation,
            coverage=coverage,
            config=config,
            row_range=None,
        )
    if obs_rows > chart_rows:
        return _make_result(
            status=STATUS_INPUT_ERROR,
            reason=(
                f"观测有 {obs_rows} 行，多于图解的 {chart_rows} 行。"
                "请检查“可见完整行数”是否填错，或确认框选的是同一张图解。"
            ),
            chart=chart,
            observation=observation,
            coverage=coverage,
            config=config,
            row_range=None,
        )

    parsed_range = _parse_row_range(row_range, chart_rows)
    if isinstance(parsed_range, str):
        return _make_result(
            status=STATUS_INPUT_ERROR,
            reason=parsed_range,
            chart=chart,
            observation=observation,
            coverage=coverage,
            config=config,
            row_range=None,
        )
    range_tuple = None if row_range is None else parsed_range

    valid = observation.weights > config.min_cell_weight
    valid_count = int(np.count_nonzero(valid))
    total = obs_rows * obs_stitches
    if valid_count == 0:
        return _make_result(
            status=STATUS_INSUFFICIENT,
            reason=(
                "所有格子的权重都为 0：照片里没有可用于判断颜色的证据。"
                "请检查选区是否落在织片上、光照是否太暗，或重新拍摄。"
            ),
            chart=chart,
            observation=observation,
            coverage=coverage,
            config=config,
            row_range=range_tuple,
        )
    coverage = valid_count / total
    if coverage < config.min_coverage:
        return _make_result(
            status=STATUS_INSUFFICIENT,
            reason=(
                f"有效覆盖率只有 {coverage:.0%}（阈值 {config.min_coverage:.0%}）："
                "权重过低的格子太多，无法可靠定位。请检查角点是否贴边、照片是否模糊或阴影过重，并补拍。"
            ),
            chart=chart,
            observation=observation,
            coverage=coverage,
            config=config,
            row_range=range_tuple,
        )

    weights = np.where(valid, observation.weights, 0.0)
    denominator = float(weights.sum())
    obs_cells = observation.cells
    height = obs_rows
    starts = list(range(0, chart_rows - height + 1))
    if range_tuple is not None:
        lo, hi = range_tuple
        starts = [s for s in starts if lo <= s + height <= hi]
    if not starts:
        if range_tuple is not None:
            reason = (
                f"在最近完成行 {range_tuple[0]}–{range_tuple[1]} 内没有合法窗口："
                f"图解共 {chart_rows} 行，观测高 {height} 行。请放宽范围或取消范围限制。"
            )
        else:
            reason = "图解高度小于观测高度，没有可用的行窗口。"
        return _make_result(
            status=STATUS_INSUFFICIENT,
            reason=reason,
            chart=chart,
            observation=observation,
            coverage=coverage,
            config=config,
            row_range=range_tuple,
            windows=0,
        )

    window_scores: list[tuple[int, float, bool, int]] = []
    for start in starts:
        window = chart.cells[start : start + height]
        equal = window == obs_cells
        matched_direct = float(weights[equal].sum())
        score_direct = matched_direct / denominator
        swapped = score_direct < 0.5
        score = 1.0 - score_direct if swapped else score_direct
        matched = valid_count - int(np.count_nonzero(equal & valid)) if swapped else int(np.count_nonzero(equal & valid))
        window_scores.append((start, min(1.0, max(0.0, score)), swapped, matched))

    best_score = max(item[1] for item in window_scores)
    if best_score < config.min_score:
        return _make_result(
            status=STATUS_INSUFFICIENT,
            reason=(
                f"最佳窗口的加权吻合度只有 {best_score:.1%}（阈值 {config.min_score:.0%}），"
                "无法确定行号。请检查图解行列数、照片角点与选区，或补拍更清晰的照片。"
            ),
            chart=chart,
            observation=observation,
            coverage=coverage,
            config=config,
            row_range=range_tuple,
            windows=len(starts),
        )

    threshold = max(best_score - config.ambiguity_margin, config.min_score)
    shortlist = [item for item in window_scores if item[1] >= threshold]
    shortlist.sort(key=lambda item: (-item[1], item[0]))

    candidates: list[Candidate] = []
    for start, score, swapped, matched in shortlist:
        window = chart.cells[start : start + height]
        equal = window == obs_cells
        # 直接映射：不相等即差异；互换映射：相等才是差异。
        mask = (valid & equal) if swapped else (valid & ~equal)
        diff_cells = tuple((int(r), int(c)) for r, c in np.argwhere(mask))
        candidates.append(
            Candidate(
                start_row=start,
                height=height,
                score=float(score),
                swapped=swapped,
                coverage=float(coverage),
                matches=int(matched),
                valid_cells=valid_count,
                diff_cells=diff_cells,
            )
        )

    best_candidate = candidates[0]
    if len(candidates) == 1:
        mapping_note = (
            "（照片与图解的两种颜色整体互换，行号不受影响。）" if best_candidate.swapped else ""
        )
        reason = (
            f"图解第 {best_candidate.window_1based[0]}–{best_candidate.window_1based[1]} 行，"
            f"最近完成第 {best_candidate.last_completed_row} 行，下一行第 {best_candidate.next_row} 行。"
            f"加权吻合度 {best_candidate.score:.1%}，有效覆盖率 {coverage:.0%}。{mapping_note}"
        )
        if best_candidate.end_row >= chart_rows - 1:
            reason = (
                f"图解第 {best_candidate.window_1based[0]}–{best_candidate.window_1based[1]} 行，"
                "已到图解最后一行，图解已完成。"
                f"加权吻合度 {best_candidate.score:.1%}，有效覆盖率 {coverage:.0%}。{mapping_note}"
            )
        return _make_result(
            status=STATUS_UNIQUE,
            reason=reason,
            chart=chart,
            observation=observation,
            coverage=coverage,
            config=config,
            row_range=range_tuple,
            candidates=candidates,
            best=best_candidate,
            windows=len(starts),
        )

    pieces = "、".join(
        f"第 {c.window_1based[0]}–{c.window_1based[1]} 行（最近完成 {c.last_completed_row}）"
        for c in candidates
    )
    reason = (
        f"有 {len(candidates)} 个位置的可见配色相同或接近：{pieces}。"
        f"最佳吻合度 {best_candidate.score:.1%}，候选分差 ≤ {config.ambiguity_margin:.0%}，"
        "仅凭当前可见区域无法区分。可以补拍更早的行、增加可见行数，或在下方指定最近完成行范围。"
    )
    return _make_result(
        status=STATUS_MULTIPLE,
        reason=reason,
        chart=chart,
        observation=observation,
        coverage=coverage,
        config=config,
        row_range=range_tuple,
        candidates=tuple(candidates),
        best=best_candidate,
        windows=len(starts),
    )
