"""集中配置：匹配阈值、图解读取与照片读取参数。

阈值初始取值依据（详见 README「分数与阈值」）：

* ``min_coverage = 0.60``
  照片中至少六成格子要能给出颜色证据。低于此值时，行号更多取决于少数
  清晰格子，容易因阴影/反光给出错误唯一答案；样例照片通常为 1.0。
* ``min_score = 0.82``
  加权配色吻合度（0–1）。干净合成样例接近 1.0；实拍吻合度尚无配对实测数据，
  0.82 是待实拍校准的保守初始值；随机双色图案期望约为 0.5。当前取值的目的是
  在缺少实拍依据时优先避免“自信地给出错误行号”，宁可提示证据不足。
* ``ambiguity_margin = 0.02``
  两个窗口的吻合度差 ≤ 2 个百分点时视为“相同或接近”，保留为多个候选，
  而不是按像素级小数差强行挑一个。插值、噪声造成的分差通常小于该值。
* ``min_cell_weight``：权重 ≤ 该值的格子不参与分数（视为无效证据）。
* ``low_weight``：低于该值的格子会在预览中标红，提示用户检查采样。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MatchConfig:
    min_coverage: float = 0.60
    min_score: float = 0.82
    ambiguity_margin: float = 0.02
    min_cell_weight: float = 0.15
    low_weight: float = 0.35

    def as_dict(self) -> dict[str, float]:
        return {
            "min_coverage": self.min_coverage,
            "min_score": self.min_score,
            "ambiguity_margin": self.ambiguity_margin,
            "min_cell_weight": self.min_cell_weight,
            "low_weight": self.low_weight,
        }


@dataclass(frozen=True)
class ChartConfig:
    """图解读取参数。"""

    sample_inner: float = 0.50  # 只采样每格中央 50% 区域，避开网格线
    min_cell_px: float = 2.0  # 每格至少 2×2 源像素
    min_color_separation: float = 8.0  # Lab 欧氏距离，低于此认为无法区分双色
    max_grid_cells: int = 600  # 行数/针数上限，防止误输入导致卡死

    def as_dict(self) -> dict[str, float]:
        return {
            "sample_inner": self.sample_inner,
            "min_cell_px": self.min_cell_px,
            "min_color_separation": self.min_color_separation,
        }


@dataclass(frozen=True)
class PhotoConfig:
    """照片校正与采样参数。"""

    cell_px: int = 48  # 校正后每格边长（像素）
    sample_grid: int = 5  # 每格采样 5×5 个点
    sample_inner: float = 0.60  # 采样点位于每格中央 60% 区域
    min_source_cell_px: float = 3.0  # 源图每格至少 3×3 像素，否则判定分辨率过低
    color_separation_min: float = 8.0  # 低于此认为双色无法区分
    color_separation_clear: float = 45.0  # 达到此色差时颜色置信度为 1
    blur_warn: float = 30.0  # 拉普拉斯方差的提醒阈值
    low_purity: float = 0.55  # 格内纯度低于此值视为“颜色混杂”
    min_weight: float = 0.15  # 低于此值的格子视为没有可用证据（权重置 0）
    max_cells: int = 20000  # 行数×针数上限

    def as_dict(self) -> dict[str, float]:
        return {
            "cell_px": float(self.cell_px),
            "sample_grid": float(self.sample_grid),
            "min_source_cell_px": self.min_source_cell_px,
            "color_separation_min": self.color_separation_min,
            "color_separation_clear": self.color_separation_clear,
            "blur_warn": self.blur_warn,
            "low_purity": self.low_purity,
        }


DEFAULT_MATCH_CONFIG = MatchConfig()
DEFAULT_CHART_CONFIG = ChartConfig()
DEFAULT_PHOTO_CONFIG = PhotoConfig()
