import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from helpers import ZOOMBERG  # noqa: E402
from supportrl.pack import Pack  # noqa: E402
from supportrl.scorer import Scorer  # noqa: E402


@pytest.fixture(scope="session")
def zpack():
    return Pack(ZOOMBERG)


@pytest.fixture(scope="session")
def zscorer(zpack):
    return Scorer(zpack)
