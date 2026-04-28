"""Tests for MS1 spectrum extraction (centroid, profile, raw)."""

from pathlib import Path

import numpy as np

from tdf2mzml.io.reader import TdfReader
from tdf2mzml.models.spectrum import SpectrumArrays
from tdf2mzml.processing.ms1 import get_centroid_ms1, get_profile_ms1, get_raw_ms1


def _first_ms1_frame(reader: TdfReader) -> tuple[int, int]:
    frames = reader.get_ms1_frames()
    frame_id = frames[0][0]
    num_scans = reader.get_num_scans(frame_id)
    return frame_id, num_scans


def test_centroid_ms1_returns_spectrum_arrays(pasef_dda_path: Path) -> None:
    """Centroid MS1 returns a non-empty SpectrumArrays with matching lengths."""
    with TdfReader(pasef_dda_path) as reader:
        frame_id, num_scans = _first_ms1_frame(reader)
        result = get_centroid_ms1(reader, frame_id, num_scans)

    assert isinstance(result, SpectrumArrays)
    assert not result.is_empty
    assert len(result.mz) == len(result.intensity)
    assert result.mz.dtype == np.float64
    assert result.intensity.dtype == np.float32
    # m/z should be in reasonable range for a timsTOF acquisition
    assert result.mz[0] >= 50.0
    assert result.mz[-1] <= 2000.0


def test_profile_ms1_returns_spectrum_arrays(pasef_dda_path: Path) -> None:
    """Profile MS1 returns arrays of matching length."""
    with TdfReader(pasef_dda_path) as reader:
        frame_id, num_scans = _first_ms1_frame(reader)
        result = get_profile_ms1(reader, frame_id, num_scans)

    assert isinstance(result, SpectrumArrays)
    assert len(result.mz) == len(result.intensity)


def test_raw_ms1_vectorised(pasef_dda_path: Path) -> None:
    """Raw MS1 returns arrays with m/z sorted ascending."""
    with TdfReader(pasef_dda_path) as reader:
        frame_id, num_scans = _first_ms1_frame(reader)
        result = get_raw_ms1(reader, frame_id, num_scans, threshold=100.0)

    assert isinstance(result, SpectrumArrays)
    if not result.is_empty:
        assert np.all(np.diff(result.mz) >= 0), "m/z not sorted ascending"


def test_raw_ms1_threshold_filters(pasef_dda_path: Path) -> None:
    """Higher threshold produces fewer peaks than lower threshold."""
    with TdfReader(pasef_dda_path) as reader:
        frame_id, num_scans = _first_ms1_frame(reader)
        low = get_raw_ms1(reader, frame_id, num_scans, threshold=10.0)
        high = get_raw_ms1(reader, frame_id, num_scans, threshold=10000.0)

    assert len(low.mz) >= len(high.mz)
