"""Tests for TdfReader metadata and SQL queries."""

from pathlib import Path

import pytest

from tdf2mzml.io.reader import TdfReader
from tdf2mzml.models.metadata import AcquisitionMetadata


def test_metadata_loads(pasef_dda_path: Path) -> None:
    """AcquisitionMetadata is populated with expected fields."""
    with TdfReader(pasef_dda_path) as reader:
        meta = reader.metadata

    assert isinstance(meta, AcquisitionMetadata)
    assert meta.instrument_name == "timsTOF Pro"
    assert meta.mz_acq_range_lower == pytest.approx(100.0)
    assert meta.mz_acq_range_upper == pytest.approx(1700.0)
    assert meta.one_over_k0_range_lower > 0
    assert meta.frame_count > 0
    assert meta.ms1_spectra_count > 0
    assert meta.total_spectra > 0


def test_metadata_has_pasef_dda(pasef_dda_path: Path) -> None:
    """DDA dataset is detected correctly."""
    with TdfReader(pasef_dda_path) as reader:
        meta = reader.metadata
    assert meta.has_pasef_dda is True
    assert meta.has_pasef_dia is False
    assert meta.ms2_dda_count > 0


def test_get_ms1_frames(pasef_dda_path: Path) -> None:
    """MS1 frames are returned and match the metadata count."""
    with TdfReader(pasef_dda_path) as reader:
        frames = reader.get_ms1_frames()
        meta = reader.metadata
    assert len(frames) == meta.ms1_spectra_count


def test_get_num_scans(pasef_dda_path: Path) -> None:
    """NumScans is a positive integer for the first frame."""
    with TdfReader(pasef_dda_path) as reader:
        frames = reader.get_ms1_frames()
        n = reader.get_num_scans(frames[0][0])
    assert isinstance(n, int)
    assert n > 0


def test_get_precursors_for_frame(pasef_dda_path: Path) -> None:
    """Precursors are returned for a DDA MS1 frame."""
    with TdfReader(pasef_dda_path) as reader:
        frames = reader.get_ms1_frames()
        # Find a frame that has precursors
        for frame in frames:
            precs = reader.get_precursors_for_frame(frame[0])
            if precs:
                assert "Id" in precs[0]
                assert "Parent" in precs[0]
                break
        else:
            pytest.skip("No frame with precursors found")
