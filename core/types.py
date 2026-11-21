"""共享数据结构与坐标约定。

本文件是各模块之间的唯一契约，坐标约定如下（务必先读）：

* 矩阵形状为 ``(行数, 针数)``。
* 内部第 0 行 = 图解底部第 1 行；内部第 0 列 = 正面观察时最左侧的一针。
* 照片模块负责把屏幕坐标（图片第 0 行在顶部）翻转成内部顺序。
* 候选 ``start_row`` / ``end_row`` 是零基内部行号，覆盖图解第
  ``start_row + 1`` 至 ``end_row + 1`` 行。最近完成行为 ``end_row + 1``，
  下一行为 ``end_row + 2``。
* 逐格权重范围 0–1，0 表示该格没有可用证据。
* 所有图像数组均为 OpenCV 的 BGR 顺序（``uint8``），调色板同样以 BGR 保存。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

import numpy as np

Color = tuple[int, int, int]

STATUS_UNIQUE = "unique"
STATUS_MULTIPLE = "multiple"
STATUS_INSUFFICIENT = "insufficient"
STATUS_INPUT_ERROR = "input_error"

STATUS_LABELS: dict[str, str] = {
    STATUS_UNIQUE: "唯一候选",
    STATUS_MULTIPLE: "多个候选",
    STATUS_INSUFFICIENT: "证据不足",
    STATUS_INPUT_ERROR: "输入错误",
}

STATUS_HELP: dict[str, str] = {
    STATUS_UNIQUE: "只有一个位置能解释照片里看到的配色。",
    STATUS_MULTIPLE: "多个位置的可见配色相同或接近，仅凭当前照片无法区分。",
    STATUS_INSUFFICIENT: "证据不足以给出可信的行号，请检查选区、行数、拍摄质量或补拍。",
    STATUS_INPUT_ERROR: "输入尺寸或参数不匹配，请按提示修正后重试。",
}


class GridInputError(ValueError):
    """输入不合法（矩阵、选区、角点、行列数等）。消息面向最终用户。"""


def _as_binary_cells(cells: Any, name: str) -> np.ndarray:
    arr = np.asarray(cells)
    if arr.ndim != 2:
        raise GridInputError(f"{name} 必须是二维矩阵（行×针），当前是 {arr.ndim} 维。")
    if arr.shape[0] < 1 or arr.shape[1] < 1:
        raise GridInputError(f"{name} 至少要有 1 行 1 针，当前为 {arr.shape[0]} 行 × {arr.shape[1]} 针。")
    if arr.dtype == bool:
        return arr.astype(np.int8)
    if not np.issubdtype(arr.dtype, np.number):
        raise GridInputError(f"{name} 必须是数字矩阵（双色 0/1），当前类型为 {arr.dtype}。")
    if not np.all(np.isfinite(arr)):
        raise GridInputError(f"{name} 含有 NaN 或无穷大。")
    values = np.unique(arr)
    if values.size > 2 or not np.all(np.isin(values, (0, 1))):
        shown = ", ".join(f"{v:g}" for v in values[:6])
        raise GridInputError(f"{name} 只能包含两种颜色标签 0/1，发现取值：{shown}。")
    return arr.astype(np.int8)


def _as_weights(weights: Any, shape: tuple[int, int]) -> np.ndarray:
    arr = np.asarray(weights, dtype=np.float64)
    if arr.shape != shape:
        raise GridInputError(f"权重矩阵形状应为 {shape}，实际为 {arr.shape}。")
    if not np.all(np.isfinite(arr)):
        raise GridInputError("权重矩阵含有 NaN 或无穷大。")
    if arr.size and (arr.min() < -1e-9 or arr.max() > 1 + 1e-9):
        raise GridInputError("逐格权重必须位于 0–1 之间。")
    return np.clip(arr, 0.0, 1.0)


@dataclass(frozen=True, eq=False)
class ChartGrid:
    """图解参考矩阵。

    ``cells[0, 0]`` 是图解左下角的一格（内部行 0 = 图解第 1 行）。
    ``cell_boxes`` 可选，形状 ``(rows, stitches, 4)``，内容为
    ``(x0, y0, x1, y1)``，按内部行号索引；用于在源图上画出每个格子的位置。
    """

    cells: np.ndarray
    palette: tuple[Color, Color] = ((255, 255, 255), (40, 40, 40))
    source: str = ""
    cell_boxes: np.ndarray | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "cells", _as_binary_cells(self.cells, "图解矩阵"))
        palette = tuple(tuple(int(v) for v in color) for color in self.palette)
        if len(palette) != 2 or any(len(color) != 3 for color in palette):
            raise GridInputError("调色板必须包含两个 RGB/BGR 三元组。")
        if any(v < 0 or v > 255 for color in palette for v in color):
            raise GridInputError("调色板颜色分量必须在 0–255 之间。")
        object.__setattr__(self, "palette", palette)
        if self.cell_boxes is not None:
            boxes = np.asarray(self.cell_boxes, dtype=np.float64)
            if boxes.shape != (self.rows, self.stitches, 4):
                raise GridInputError(
                    f"cell_boxes 形状应为 {(self.rows, self.stitches, 4)}，实际为 {boxes.shape}。"
                )
            object.__setattr__(self, "cell_boxes", boxes)

    @property
    def rows(self) -> int:
        return int(self.cells.shape[0])

    @property
    def stitches(self) -> int:
        return int(self.cells.shape[1])

    @property
    def shape(self) -> tuple[int, int]:
        return self.rows, self.stitches

    def swapped(self) -> "ChartGrid":
        """整体交换两种颜色标签。"""
        return ChartGrid(
            cells=1 - self.cells,
            palette=(self.palette[1], self.palette[0]),
            source=self.source,
            cell_boxes=None if self.cell_boxes is None else self.cell_boxes.copy(),
        )

    def visual_cells(self) -> np.ndarray:
        """按人眼阅读顺序（顶部 = 图解最后一行）返回矩阵副本。"""
        return self.cells[::-1].copy()

    def row_number(self, internal_row: int) -> int:
        """内部零基行号 → 图解一基行号。"""
        return int(internal_row) + 1


@dataclass(frozen=True, eq=False)
class ObservedGrid:
    """从照片得到的观测矩阵（内部顺序：第 0 行 = 观测区最下面一行）。

    ``cells``：0/1 标签。
    ``weights``：逐格 0–1 置信度。
    ``palette``：两个标签在照片中的代表色（BGR）。
    """

    cells: np.ndarray
    weights: np.ndarray
    palette: tuple[Color, Color] = ((255, 255, 255), (40, 40, 40))
    source: str = ""
    notes: tuple[str, ...] = ()
    quality: Mapping[str, Any] = field(default_factory=dict)
    warped: np.ndarray | None = field(default=None, repr=False, compare=False)
    cell_boxes: np.ndarray | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        cells = _as_binary_cells(self.cells, "观测矩阵")
        weights = _as_weights(self.weights, cells.shape)
        object.__setattr__(self, "cells", cells)
        object.__setattr__(self, "weights", weights)
        object.__setattr__(self, "notes", tuple(str(n) for n in self.notes))
        palette = tuple(tuple(int(v) for v in color) for color in self.palette)
        object.__setattr__(self, "palette", palette)

    @property
    def rows(self) -> int:
        return int(self.cells.shape[0])

    @property
    def stitches(self) -> int:
        return int(self.cells.shape[1])

    @property
    def shape(self) -> tuple[int, int]:
        return self.rows, self.stitches

    @property
    def total_cells(self) -> int:
        return self.rows * self.stitches

    @property
    def valid_cells(self) -> int:
        return int(np.count_nonzero(self.weights > 0))

    @property
    def coverage(self) -> float:
        """有效覆盖率：权重 > 0 的格子占比。"""
        if self.total_cells == 0:
            return 0.0
        return self.valid_cells / self.total_cells

    @property
    def total_weight(self) -> float:
        return float(self.weights.sum())

    def swapped(self) -> "ObservedGrid":
        return ObservedGrid(
            cells=1 - self.cells,
            weights=self.weights,
            palette=(self.palette[1], self.palette[0]),
            source=self.source,
            notes=self.notes,
            quality=dict(self.quality),
            warped=self.warped,
            cell_boxes=None if self.cell_boxes is None else self.cell_boxes.copy(),
        )


@dataclass(frozen=True)
class Candidate:
    """一个与观测等高的连续行窗口。行号均为内部零基。"""

    start_row: int
    height: int
    score: float
    swapped: bool
    coverage: float
    matches: int
    valid_cells: int
    diff_cells: tuple[tuple[int, int], ...] = ()

    def __post_init__(self) -> None:
        if self.start_row < 0:
            raise GridInputError("候选起点不能为负数。")
        if self.height < 1:
            raise GridInputError("候选窗口高度必须 ≥ 1。")
        if not (0.0 <= self.score <= 1.0 + 1e-9):
            raise GridInputError("候选分数必须位于 0–1 之间。")
        if not (0.0 <= self.coverage <= 1.0 + 1e-9):
            raise GridInputError("有效覆盖率必须位于 0–1 之间。")

    @property
    def end_row(self) -> int:
        return self.start_row + self.height - 1

    @property
    def window_1based(self) -> tuple[int, int]:
        """覆盖的图解行号区间（一基，闭区间）。"""
        return self.start_row + 1, self.end_row + 1

    @property
    def last_completed_row(self) -> int:
        """最近完成的图解行号（一基）。"""
        return self.end_row + 1

    @property
    def next_row(self) -> int:
        """下一行图解行号（一基）；调用方需先判断是否已完成图解。"""
        return self.end_row + 2

    @property
    def diff_count(self) -> int:
        return len(self.diff_cells)

    @property
    def mapping_label(self) -> str:
        return "颜色互换" if self.swapped else "颜色一致"

    def describe(self) -> str:
        return (
            f"图解第 {self.window_1based[0]}–{self.window_1based[1]} 行，"
            f"最近完成 {self.last_completed_row}，吻合度 {self.score:.1%}"
        )


@dataclass(frozen=True)
class MatchResult:
    """定位结果。``status`` 取四种状态之一。"""

    status: str
    candidates: tuple[Candidate, ...]
    best: Candidate | None
    reason: str
    coverage: float
    observation_shape: tuple[int, int]
    chart_shape: tuple[int, int]
    row_range: tuple[int, int] | None = None
    thresholds: Mapping[str, float] = field(default_factory=dict)
    windows_searched: int = 0

    def __post_init__(self) -> None:
        if self.status not in STATUS_LABELS:
            raise GridInputError(f"未知状态：{self.status}")
        object.__setattr__(self, "candidates", tuple(self.candidates))
        object.__setattr__(self, "thresholds", dict(self.thresholds))

    @property
    def label(self) -> str:
        return STATUS_LABELS[self.status]

    @property
    def is_unique(self) -> bool:
        return self.status == STATUS_UNIQUE and self.best is not None

    @property
    def is_multiple(self) -> bool:
        return self.status == STATUS_MULTIPLE

    @property
    def is_insufficient(self) -> bool:
        return self.status == STATUS_INSUFFICIENT

    @property
    def is_input_error(self) -> bool:
        return self.status == STATUS_INPUT_ERROR

    @property
    def last_completed_row(self) -> int | None:
        return None if self.best is None else self.best.last_completed_row

    @property
    def next_row(self) -> int | None:
        """排名第一的候选的下一行；仅用于单候选场景。

        多候选界面必须按用户当前选中的候选判断，使用
        :func:`core.progress.candidate_progress`，否则会把“最佳候选已完成”
        误用于其他候选。
        """
        if self.best is None:
            return None
        return None if self.chart_complete else self.best.next_row

    @property
    def chart_complete(self) -> bool:
        """排名第一的候选是否到达图解末行；多候选请用候选级判断。"""
        return self.best is not None and self.best.end_row >= self.chart_shape[0] - 1

    @property
    def candidate_count(self) -> int:
        return len(self.candidates)

    @property
    def all_last_completed_rows(self) -> tuple[int, ...]:
        return tuple(c.last_completed_row for c in self.candidates)
