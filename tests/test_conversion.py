"""End-to-end conversion tests against real .d data."""

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from tdf2mzml.cli import run_conversion
from tdf2mzml.models.config import ConversionConfig


def test_dda_conversion_produces_valid_mzml(pasef_dda_path: Path, tmp_path: Path) -> None:
    """Full DDA conversion produces a parseable indexed mzML file."""
    out = tmp_path / "dda_output.mzML"
    config = ConversionConfig(
        input=pasef_dda_path,
        output=out,
        ms1_type="centroid",
        ion_mobility="mean",
        end_frame=20,  # limit to first 20 frames for speed
    )
    run_conversion(config)

    assert out.exists()
    assert out.stat().st_size > 1000

    # Parse and verify structure
    tree = ET.parse(out)
    root = tree.getroot()
    ns = {"m": "http://psi.hupo.org/ms/mzml"}

    # indexedmzML root
    assert "indexedmzML" in root.tag

    # Has spectra
    spectrum_list = root.find(".//m:spectrumList", ns)
    assert spectrum_list is not None
    count = int(spectrum_list.attrib["count"])
    assert count > 0

    # Has index
    index = root.find(".//m:index", ns)
    assert index is not None

    # Has fileChecksum
    checksum = root.find(".//m:fileChecksum", ns)
    assert checksum is not None
    assert len(checksum.text or "") == 40  # SHA-1 hex


def test_config_zip_input(tmp_path: Path) -> None:
    """ConversionConfig raises ValueError for non-existent .d directory."""
    with pytest.raises(ValueError, match=r"analysis\.tdf"):
        ConversionConfig(
            input=tmp_path / "nonexistent.d",
            output=tmp_path / "out.mzML",
        )


def test_config_frame_range_validation(pasef_dda_path: Path, tmp_path: Path) -> None:
    """ConversionConfig rejects end_frame <= start_frame."""
    with pytest.raises(ValueError, match="end_frame"):
        ConversionConfig(
            input=pasef_dda_path,
            output=tmp_path / "out.mzML",
            start_frame=10,
            end_frame=5,
        )
