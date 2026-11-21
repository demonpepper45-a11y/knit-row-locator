"""「织到哪一行了？」核心算法包。"""

from .chart import ChartReadResult, read_chart
from .config import (
    DEFAULT_CHART_CONFIG,
    DEFAULT_MATCH_CONFIG,
    DEFAULT_PHOTO_CONFIG,
    ChartConfig,
    MatchConfig,
    PhotoConfig,
)
from .match import match
from .photo import PhotoReadResult, read_photo
from .progress import CandidateProgress, candidate_progress
from .types import (
    STATUS_HELP,
    STATUS_INPUT_ERROR,
    STATUS_INSUFFICIENT,
    STATUS_LABELS,
    STATUS_MULTIPLE,
    STATUS_UNIQUE,
    Candidate,
    ChartGrid,
    GridInputError,
    MatchResult,
    ObservedGrid,
)

__version__ = "0.2.0"

__all__ = [
    "Candidate",
    "CandidateProgress",
    "ChartConfig",
    "ChartGrid",
    "ChartReadResult",
    "candidate_progress",
    "DEFAULT_CHART_CONFIG",
    "DEFAULT_MATCH_CONFIG",
    "DEFAULT_PHOTO_CONFIG",
    "GridInputError",
    "MatchConfig",
    "MatchResult",
    "ObservedGrid",
    "PhotoConfig",
    "PhotoReadResult",
    "STATUS_HELP",
    "STATUS_INPUT_ERROR",
    "STATUS_INSUFFICIENT",
    "STATUS_LABELS",
    "STATUS_MULTIPLE",
    "STATUS_UNIQUE",
    "match",
    "read_chart",
    "read_photo",
]
