"""候选级进度：判断当前选中的候选是否到达图解末行。

界面、CLI 和测试共用这一处逻辑，避免“全局最佳候选已完成”误用于用户当前
选中的其他候选。多候选状态下，末行候选的下一行不写成不存在的行号，而是
明确提示“若此候选正确，图解已完成”。
"""

from __future__ import annotations

from dataclasses import dataclass

from .types import STATUS_MULTIPLE, Candidate, MatchResult


@dataclass(frozen=True)
class CandidateProgress:
    """当前候选的最近完成行与下一行展示信息。"""

    last_completed_row: int
    is_last_window: bool
    next_row: int | None
    next_label: str
    note: str
    status: str
    candidate_count: int


def candidate_progress(result: MatchResult, candidate: Candidate) -> CandidateProgress:
    """按**当前候选**判断是否到达图解末行，而不是按全局最佳候选。"""
    chart_rows = result.chart_shape[0]
    is_last = candidate.end_row >= chart_rows - 1
    if not is_last:
        return CandidateProgress(
            last_completed_row=candidate.last_completed_row,
            is_last_window=False,
            next_row=candidate.next_row,
            next_label=str(candidate.next_row),
            note="",
            status=result.status,
            candidate_count=result.candidate_count,
        )

    if result.status == STATUS_MULTIPLE:
        return CandidateProgress(
            last_completed_row=candidate.last_completed_row,
            is_last_window=True,
            next_row=None,
            next_label="若此候选正确，图解已完成",
            note="若此候选正确，图解已完成；其他候选可能仍有下一行。",
            status=result.status,
            candidate_count=result.candidate_count,
        )
    return CandidateProgress(
        last_completed_row=candidate.last_completed_row,
        is_last_window=True,
        next_row=None,
        next_label="图解已完成",
        note="图解已完成：观测窗口覆盖到图解最后一行，没有下一行。",
        status=result.status,
        candidate_count=result.candidate_count,
    )
