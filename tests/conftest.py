"""Shared test fixtures."""

from pathlib import Path

import pytest

# Skip SDK-dependent test modules when the Bruker shared library is unavailable
# (e.g. macOS, CI without SDK). These modules import TdfReader at collection
# time, which triggers ctypes.CDLL loading of libtimsdata.so.
try:
    from tdf2mzml.io import timsdata as _  # noqa: F401

    _SDK_AVAILABLE = True
except OSError:
    _SDK_AVAILABLE = False

collect_ignore_glob: list[str] = []
if not _SDK_AVAILABLE:
    collect_ignore_glob += ["test_conversion.py", "test_ms1.py", "test_reader.py"]

TEST_DATA_DIR = Path(__file__).parent.parent / "test_data" / "tdf"


@pytest.fixture(scope="session")
def pasef_dda_path() -> Path:
    """Path to the 200ng HeLa PASEF DDA .d directory."""
    return TEST_DATA_DIR / "200ngHeLaPASEF_1min.d"


@pytest.fixture(scope="session")
def pasef_dia_path() -> Path:
    """Path to the 200ng HeLa PASEF DIA .d directory."""
    return TEST_DATA_DIR / "200ngHeLaPASEF_2min.d"
