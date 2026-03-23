"""Shared test fixtures."""
from pathlib import Path

import pytest

TEST_DATA_DIR = Path(__file__).parent.parent / "test"


@pytest.fixture(scope="session")
def pasef_dda_path() -> Path:
    """Path to the 200ng HeLa PASEF DDA .d directory."""
    return TEST_DATA_DIR / "200ngHeLaPASEF_1min.d"


@pytest.fixture(scope="session")
def pasef_dia_path() -> Path:
    """Path to the 200ng HeLa PASEF DIA .d directory."""
    return TEST_DATA_DIR / "200ngHeLaPASEF_2min.d"
