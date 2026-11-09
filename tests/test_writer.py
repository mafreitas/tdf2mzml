"""IndexedMzMLWriter file-structure tests (no Bruker SDK or data needed).

Guards the rules a strict mzML reader checks: the index offsets, the SHA-1 range,
valid XML IDs, escaping of text fields, and no complete-looking file after an error.
"""

from __future__ import annotations

import hashlib
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
import pytest

from tdf2mzml.models.metadata import AcquisitionMetadata
from tdf2mzml.models.spectrum import PrecursorInfo, SpectrumArrays
from tdf2mzml.output.writer import IndexedMzMLWriter
from tdf2mzml.output.xml_elements import xml_id

_NCNAME = re.compile(r"^[A-Za-z_][A-Za-z0-9._-]*$")


def _meta(**overrides: object) -> AcquisitionMetadata:
    values: dict[str, object] = {}
    for name, field in AcquisitionMetadata.model_fields.items():
        ann = str(field.annotation)
        if "list" in ann:
            values[name] = []
        elif ann == "<class 'str'>":
            values[name] = ""
        elif ann == "<class 'bool'>":
            values[name] = True
        elif ann == "<class 'int'>":
            values[name] = 0
        else:
            values[name] = 0.0
    values.update(overrides)
    return AcquisitionMetadata(**values)  # type: ignore[arg-type]


def _arrays() -> SpectrumArrays:
    return SpectrumArrays(
        mz=np.array([100.0, 200.0]), intensity=np.array([1.0, 2.0], dtype=np.float32)
    )


def _precursor() -> PrecursorInfo:
    return PrecursorInfo(mz=500.0, spectrum_reference="index=1", isolation_window_target=500.0)


def _write(path: Path, meta: AcquisitionMetadata, total: int = 2) -> bytes:
    with IndexedMzMLWriter(path, meta, path.parent / "s.d", total_spectra=total) as w:
        w.write_ms1_spectrum(_arrays(), 0.1, True)
        w.write_ms2_spectrum(_arrays(), 0.2, _precursor())
    return path.read_bytes()


class TestFileStructure:
    """Index, checksum and IDs follow the mzML 1.1 rules."""

    @pytest.fixture
    def data(self, tmp_path: Path) -> bytes:
        return _write(
            tmp_path / "o.mzML",
            _meta(sample_name="50ng HeLa (1)", acq_software="Bruker otofControl"),
        )

    def test_well_formed_and_count_matches(self, data: bytes) -> None:
        root = ET.fromstring(data)
        spectra = root.findall(".//{*}spectrum")
        assert len(spectra) == 2
        assert root.find(".//{*}spectrumList").attrib["count"] == "2"  # type: ignore[union-attr]

    def test_offsets_point_at_spectrum_tag(self, data: bytes) -> None:
        offsets = [int(o) for o in re.findall(rb">(\d+)</offset>", data)]
        assert len(offsets) == 2
        assert all(data[o : o + 9] == b"<spectrum" for o in offsets)

    def test_index_list_offset_points_at_index_list_tag(self, data: bytes) -> None:
        offset = int(re.search(rb"<indexListOffset>(\d+)<", data).group(1))  # type: ignore[union-attr]
        assert data[offset : offset + 10] == b"<indexList"

    def test_checksum_covers_file_up_to_and_including_open_tag(self, data: bytes) -> None:
        stored = re.search(rb"<fileChecksum>([0-9a-f]{40})</fileChecksum>", data).group(1)  # type: ignore[union-attr]
        end = data.rindex(b"<fileChecksum>") + len(b"<fileChecksum>")
        assert hashlib.sha1(data[:end]).hexdigest().encode() == stored

    def test_ids_are_valid_xml_ids(self, data: bytes) -> None:
        ids = re.findall(rb'<(?:run|sourceFile|software)\s+id="([^"]*)"', data)
        ids += re.findall(rb'defaultSourceFileRef="([^"]*)"', data)
        assert ids
        assert all(_NCNAME.match(i.decode()) for i in ids), ids

    def test_ms2_without_precursor_has_no_precursor_list(self, tmp_path: Path) -> None:
        out = tmp_path / "o.mzML"
        with IndexedMzMLWriter(out, _meta(), tmp_path / "s.d", total_spectra=1) as w:
            w.write_ms2_spectrum(_arrays(), 0.2, None)
        assert b"<precursorList" not in out.read_bytes()


class TestEscaping:
    """Text fields from the instrument must not break the XML."""

    def test_quotes_in_operator_method_and_timestamp(self, tmp_path: Path) -> None:
        meta = _meta(
            operator_name='John "JD" Smith & Co', method_name='a"b<c', acq_date_time='2026"01'
        )
        root = ET.fromstring(_write(tmp_path / "o.mzML", meta))
        params = {
            p.attrib["name"]: p.attrib["value"] for p in root.findall(".//{*}run/{*}userParam")
        }
        assert params["contact name"] == 'John "JD" Smith & Co'
        assert params["acquisition method"] == 'a"b<c'


class TestFailedRun:
    """A run that fails must not leave a file that looks complete."""

    def test_output_removed_on_error(self, tmp_path: Path) -> None:
        out = tmp_path / "o.mzML"
        with (
            pytest.raises(RuntimeError, match="boom"),
            IndexedMzMLWriter(out, _meta(), tmp_path / "s.d", total_spectra=5) as w,
        ):
            w.write_ms1_spectrum(_arrays(), 0.1, True)
            raise RuntimeError("boom")
        assert not out.exists()


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("200ng_HeLa", "_200ng_HeLa"),
        ("Bruker otofControl", "Bruker_otofControl"),
        (r"D:\data\x.d", "D__data_x.d"),
        ("", "_"),
        ("ok-1.2_x", "ok-1.2_x"),
    ],
)
def test_xml_id(raw: str, expected: str) -> None:
    """Text is turned into a valid XML ID: no spaces, colons, backslashes or leading digit."""
    assert xml_id(raw) == expected
    assert _NCNAME.match(xml_id(raw))
