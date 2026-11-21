"""pytest 公共配置：把项目根目录加入导入路径，并提供样例 fixture。"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.synth import DEFAULT_PALETTE, make_periodic_chart, make_unique_chart  # noqa: E402
from core.types import ChartGrid  # noqa: E402


@pytest.fixture(scope="session")
def project_root() -> Path:
    return ROOT


@pytest.fixture(scope="session")
def examples_dir() -> Path:
    return ROOT / "examples"


@pytest.fixture(scope="session")
def palette():
    return DEFAULT_PALETTE


@pytest.fixture(scope="session")
def chart1() -> ChartGrid:
    cells = make_unique_chart(rows=32, cols=12, window_start=18, window_height=5, seed=20261121)
    return ChartGrid(cells=cells, palette=DEFAULT_PALETTE)


@pytest.fixture(scope="session")
def chart2() -> ChartGrid:
    cells = make_periodic_chart(rows=32, cols=12, period=8, seed=20261122)
    return ChartGrid(cells=cells, palette=DEFAULT_PALETTE)


@pytest.fixture
def ones_weights():
    def factory(shape):
        return np.ones(shape, dtype=np.float64)

    return factory
