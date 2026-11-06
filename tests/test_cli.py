"""CLI helper tests: output name, zip input, MS2 peak filter, reader queries.

The databases are built in memory and the zip files are tiny, so no Bruker data is needed.
"""

from __future__ import annotations

import sqlite3
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from test_writer import _meta

try:
    from tdf2mzml import cli
    from tdf2mzml.io.reader import TdfReader
    from tdf2mzml.io.tsf_reader import TsfReader
except OSError as exc:  # the Bruker SDK library cannot be loaded on this platform
    pytest.skip(f"Bruker SDK not available: {exc}", allow_module_level=True)

from tdf2mzml.models.config import ConversionConfig
from tdf2mzml.models.spectrum import SpectrumArrays
from tdf2mzml.processing.ms2 import activation_from_info, filter_peaks


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("/data/s.d", "/data/s.mzML"),
        ("/data/s.d/", "/data/s.mzML"),
        ("/data/s.D", "/data/s.mzML"),
        ("/data/s.d.zip", "/data/s.mzML"),
        ("/data/s.zip", "/data/s.mzML"),
        ("/data/a.baf", "/data/a.mzML"),
        ("/data/s", "/data/s.mzML"),  # never the same path as the input
    ],
)
def test_derive_output(given: str, expected: str) -> None:
    """The default output name never equals the input path (a zip input was overwritten once)."""
    assert cli._derive_output(given) == expected


def _make_d(path: Path) -> Path:
    path.mkdir()
    (path / "analysis.tdf").write_bytes(b"")
    return path


class TestConfig:
    """Input and output path rules."""

    def test_output_equal_to_input_is_refused(self, tmp_path: Path) -> None:
        d = _make_d(tmp_path / "s.d")
        with pytest.raises(ValueError, match="must not be the same path"):
            ConversionConfig(input=d, output=d)

    def test_zip_input_is_accepted_without_extracting(self, tmp_path: Path) -> None:
        z = tmp_path / "s.d.zip"
        with zipfile.ZipFile(z, "w") as zf:
            zf.writestr("s.d/analysis.tdf", b"")
        config = ConversionConfig(input=z, output=tmp_path / "o.mzML")
        assert config.input == z
        assert list(tmp_path.iterdir()) == [z]  # nothing extracted next to it

    def test_ms2_threshold_default_is_format_specific(self) -> None:
        config = ConversionConfig.model_construct(ms2_threshold=None)
        assert cli._ms2_threshold(config, 0.0) == 0.0
        assert cli._ms2_threshold(config, 10.0) == 10.0
        config = ConversionConfig.model_construct(ms2_threshold=5.0)
        assert cli._ms2_threshold(config, 10.0) == 5.0


class TestZipInput:
    """A zip input is extracted to a temporary folder that is always removed."""

    @staticmethod
    def _zip(tmp_path: Path) -> ConversionConfig:
        z = tmp_path / "s.d.zip"
        with zipfile.ZipFile(z, "w") as zf:
            zf.writestr("inner/s.d/analysis.tdf", b"")
        return ConversionConfig(input=z, output=tmp_path / "o.mzML")

    def test_converts_extracted_folder_and_removes_it(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen: list[Path] = []
        monkeypatch.setattr(cli, "_convert", lambda config: seen.append(config.input))

        cli.run_conversion(self._zip(tmp_path))

        assert seen[0].name == "s.d"
        assert (seen[0] / "analysis.tdf").name == "analysis.tdf"
        assert not seen[0].exists()

    def test_removes_folder_after_an_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen: list[Path] = []

        def fail(config: ConversionConfig) -> None:
            seen.append(config.input)
            raise RuntimeError("boom")

        monkeypatch.setattr(cli, "_convert", fail)
        with pytest.raises(RuntimeError, match="boom"):
            cli.run_conversion(self._zip(tmp_path))
        assert not seen[0].exists()

    def test_zip_without_d_folder_is_an_error(self, tmp_path: Path) -> None:
        z = tmp_path / "s.zip"
        with zipfile.ZipFile(z, "w") as zf:
            zf.writestr("readme.txt", b"x")
        with pytest.raises(ValueError, match=r"No \.d directory"):
            cli.run_conversion(ConversionConfig(input=z, output=tmp_path / "o.mzML"))


class TestFilterPeaks:
    """``--ms2_threshold`` and ``--ms2_nlargest`` for every format."""

    @staticmethod
    def _arrays() -> SpectrumArrays:
        return SpectrumArrays(
            mz=np.array([100.0, 200.0, 300.0, 400.0]),
            intensity=np.array([5.0, 50.0, 20.0, 30.0], dtype=np.float32),
        )

    def test_no_filter_returns_same_object(self) -> None:
        arrays = self._arrays()
        assert filter_peaks(arrays, 0.0, -1) is arrays

    def test_threshold_keeps_peaks_at_or_above(self) -> None:
        out = filter_peaks(self._arrays(), 20.0, -1)
        assert out.mz.tolist() == [200.0, 300.0, 400.0]

    def test_nlargest_keeps_mz_order(self) -> None:
        out = filter_peaks(self._arrays(), 0.0, 2)
        assert out.mz.tolist() == [200.0, 400.0]
        assert out.intensity.tolist() == [50.0, 30.0]

    def test_threshold_then_nlargest(self) -> None:
        out = filter_peaks(self._arrays(), 20.0, 2)
        assert out.mz.tolist() == [200.0, 400.0]

    def test_empty_spectrum(self) -> None:
        empty = SpectrumArrays(mz=np.empty(0), intensity=np.empty(0, dtype=np.float32))
        assert filter_peaks(empty, 10.0, 5).is_empty


def test_activation_from_info() -> None:
    """ExD when an electron energy is set, ETD with only a reaction time, else CID."""
    assert activation_from_info({"ElectronEnergy": 0.0, "ReactionTime": 30.0}) == ("ExD", 0.0, 30.0)
    assert activation_from_info({"ReactionTime": 50.0}) == ("ETD", None, 50.0)
    assert activation_from_info({"CollisionEnergy": 30.0}) == ("CID", None, None)


def _reader(conn: sqlite3.Connection) -> TdfReader:
    reader = TdfReader.__new__(TdfReader)
    reader._tims = SimpleNamespace(conn=conn)  # type: ignore[attr-defined]
    reader._metadata = None
    return reader


class TestDiaWindows:
    """DIA windows are read once for all frames, in the same order as before."""

    @staticmethod
    def _conn() -> sqlite3.Connection:
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE DiaFrameMsMsInfo (Frame INTEGER, WindowGroup INTEGER)")
        conn.execute(
            "CREATE TABLE DiaFrameMsMsWindows (WindowGroup INTEGER, ScanNumBegin INTEGER, "
            "ScanNumEnd INTEGER, IsolationMz REAL, IsolationWidth REAL, CollisionEnergy REAL)"
        )
        conn.executemany(
            "INSERT INTO DiaFrameMsMsInfo VALUES (?, ?)", [(2, 1), (3, 2), (4, 1), (5, 2)]
        )
        conn.executemany(
            "INSERT INTO DiaFrameMsMsWindows VALUES (?, ?, ?, ?, ?, ?)",
            [
                (1, 0, 10, 500.0, 25.0, 20.0),
                (1, 10, 20, 400.0, 25.0, 21.0),
                (2, 0, 10, 600.0, 25.0, 22.0),
            ],
        )
        return conn

    def test_windows_by_frame(self) -> None:
        windows = _reader(self._conn()).get_dia_windows_by_frame()

        assert sorted(windows) == [2, 3, 4, 5]
        assert [w[3] for w in windows[2]] == [500.0, 400.0]  # table order within a group
        assert windows[2] == windows[4]
        assert [w[3] for w in windows[3]] == [600.0]

    def test_one_window_query_per_group_not_per_frame(self) -> None:
        from unittest.mock import MagicMock

        conn = MagicMock(wraps=self._conn())
        _reader(conn).get_dia_windows_by_frame()
        assert conn.execute.call_count == 3  # 1 frame list + 2 groups, for 4 frames


def test_frame_rows_keep_the_column_positions_callers_use() -> None:
    """Frames are read with named columns, so f[1], f[4] and f[8] stay Time, MsMsType, NumScans."""
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE Frames (Id INTEGER, Time REAL, Polarity TEXT, ScanMode INTEGER, "
        "MsMsType INTEGER, TimsId INTEGER, MaxIntensity INTEGER, SummedIntensities INTEGER, "
        "NumScans INTEGER, NewColumn INTEGER)"
    )
    conn.execute("INSERT INTO Frames VALUES (1, 1.5, '+', 8, 0, 0, 10, 100, 671, 99)")

    (frame,) = _reader(conn).get_all_frames()

    assert (frame[0], frame[1], frame[4], frame[8]) == (1, 1.5, 0, 671)
    assert len(frame) == 9  # a column added to the table does not shift anything


def test_count_precursors_in_range() -> None:
    """Only precursors whose parent frame is in the range are counted."""
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE Precursors (Id INTEGER, Parent INTEGER)")
    conn.executemany("INSERT INTO Precursors VALUES (?, ?)", [(1, 1), (2, 1), (3, 5), (4, 9)])

    assert _reader(conn).count_precursors_in_range(1, 5) == 3


class TestTsfFragmentationInfo:
    """TSF schema v5: ExD frames are read from the Fragmentation tables."""

    @staticmethod
    def _reader(conn: sqlite3.Connection) -> TsfReader:
        reader = TsfReader.__new__(TsfReader)
        reader._tsf = SimpleNamespace(conn=conn)  # type: ignore[attr-defined]
        return reader

    @staticmethod
    def _v5_conn() -> sqlite3.Connection:
        conn = sqlite3.connect(":memory:")
        conn.executescript(
            """
            CREATE TABLE FragmentationFrameToExperiment (Frame INTEGER, GroupId INTEGER);
            CREATE TABLE FragmentationExperiment (GroupId INTEGER, FragmentationStep INTEGER);
            CREATE TABLE FragmentationStep (Id INTEGER PRIMARY KEY, IsolationWindow INTEGER,
                FragmentationType INTEGER, Precursor INTEGER, PrmTarget INTEGER);
            CREATE TABLE FragmentationIsolationWindow (Id INTEGER PRIMARY KEY, IsolationMz REAL,
                IsolationWidth REAL, ScanNumBegin INTEGER, ScanNumEnd INTEGER);
            CREATE TABLE FragmentationPrecursor (Id INTEGER PRIMARY KEY, Parent INTEGER,
                Charge INTEGER);
            CREATE TABLE FragmentationCid (FragmentationStepId INTEGER PRIMARY KEY,
                CollisionEnergy REAL);
            CREATE TABLE FragmentationExd (FragmentationStepId INTEGER PRIMARY KEY,
                ReactionTime INTEGER, ElectronEnergy REAL);
            CREATE TABLE FragmentationEtd (FragmentationStepId INTEGER PRIMARY KEY,
                ReactionTime INTEGER);
            CREATE TABLE FragmentationStepToStep (FragmentationStepId INTEGER PRIMARY KEY,
                FragmentationStepOriginId INTEGER);
            INSERT INTO FragmentationIsolationWindow VALUES (1, 700.5, 2.0, 0, 0);
            INSERT INTO FragmentationPrecursor VALUES (10, 3, 2);
            """
        )
        return conn

    def test_cid_frame(self) -> None:
        conn = self._v5_conn()
        conn.executescript(
            """
            INSERT INTO FragmentationFrameToExperiment VALUES (7, 1);
            INSERT INTO FragmentationExperiment VALUES (1, 1);
            INSERT INTO FragmentationStep VALUES (1, 1, 1, 10, NULL);
            INSERT INTO FragmentationCid VALUES (1, 30.0);
            """
        )

        info = self._reader(conn).get_ms2_info_batch([7])[7]

        assert info["TriggerMass"] == 700.5
        assert info["Parent"] == 3
        assert info["PrecursorCharge"] == 2
        assert info["CollisionEnergy"] == 30.0
        assert info["ElectronEnergy"] is None

    def test_exd_frame_with_linked_cid_is_not_dropped(self) -> None:
        # The FrameMsMsInfo view of schema v5 joins FragmentationCid and so loses this frame.
        conn = self._v5_conn()
        conn.executescript(
            """
            INSERT INTO FragmentationFrameToExperiment VALUES (7, 1);
            INSERT INTO FragmentationExperiment VALUES (1, 1);
            INSERT INTO FragmentationStep VALUES (1, 1, 4, 10, NULL);
            INSERT INTO FragmentationStep VALUES (2, NULL, 1, NULL, NULL);
            INSERT INTO FragmentationExd VALUES (1, 30, 35.0);
            INSERT INTO FragmentationCid VALUES (2, 57.5);
            INSERT INTO FragmentationStepToStep VALUES (2, 1);
            """
        )

        info = self._reader(conn).get_ms2_info_batch([7])[7]

        assert info["ElectronEnergy"] == 35.0
        assert info["ReactionTime"] == 30.0
        assert info["CollisionEnergy"] == 57.5

    def test_frame_without_precursor_gets_parent_zero(self) -> None:
        conn = self._v5_conn()
        conn.executescript(
            """
            INSERT INTO FragmentationFrameToExperiment VALUES (7, 1);
            INSERT INTO FragmentationExperiment VALUES (1, 1);
            INSERT INTO FragmentationStep VALUES (1, 1, 1, NULL, NULL);
            INSERT INTO FragmentationCid VALUES (1, 30.0);
            """
        )

        assert self._reader(conn).get_ms2_info_batch([7])[7]["Parent"] == 0

    def test_old_schema_reads_frame_msms_info(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.execute(
            "CREATE TABLE FrameMsMsInfo (Frame INTEGER, Parent INTEGER, TriggerMass REAL, "
            "IsolationWidth REAL, PrecursorCharge INTEGER, CollisionEnergy REAL)"
        )
        conn.execute("INSERT INTO FrameMsMsInfo VALUES (7, 3, 700.5, 2.0, 2, 30.0)")

        info = self._reader(conn).get_ms2_info_batch([7])[7]

        assert info == {
            "Frame": 7,
            "Parent": 3,
            "TriggerMass": 700.5,
            "IsolationWidth": 2.0,
            "PrecursorCharge": 2,
            "CollisionEnergy": 30.0,
        }


class TestTsfConversion:
    """TSF schema v5: ExD MS2 frames are MsMsType 3 and must be counted and written."""

    class _FakeReader:
        """Stand-in for TsfReader: 1 MS1 frame and four MS2 frames of different kinds."""

        def __init__(self, path: object) -> None:
            self.metadata = _meta()

        def __enter__(self) -> TestTsfConversion._FakeReader:
            return self

        def __exit__(self, *_: object) -> None:
            return None

        def get_all_frames(self) -> list[tuple[int, float, str, int, int]]:
            # (Id, Time, Polarity, ScanMode, MsMsType)
            return [
                (1, 1.0, "+", 0, 0),
                (2, 2.0, "+", 1, 3),  # ExD then CID
                (3, 3.0, "+", 1, 2),  # CID
                (4, 4.0, "+", 1, 3),  # no MS2 info: skipped, must not be counted
                (5, 5.0, "+", 1, 2),  # outside the requested range below
            ]

        def get_ms2_info_batch(self, frame_ids: list[int]) -> dict[int, dict[str, object]]:
            base = {"Parent": 1, "TriggerMass": 700.5, "IsolationWidth": 2.0}
            info = {
                2: {
                    **base,
                    "PrecursorCharge": 2,
                    "CollisionEnergy": 57.5,
                    "ReactionTime": 30.0,
                    "ElectronEnergy": 0.0,
                },
                3: {**base, "PrecursorCharge": 2, "CollisionEnergy": 30.0},
                5: {**base, "PrecursorCharge": 2, "CollisionEnergy": 30.0},
            }
            return {f: info[f] for f in frame_ids if f in info}

        def read_line_spectrum(self, frame_id: int) -> tuple[np.ndarray, np.ndarray]:
            return np.array([100.0, 200.0]), np.array([50.0, 60.0], dtype=np.float32)

    def test_exd_frame_of_type_3_is_counted_and_written(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        d = tmp_path / "s.d"
        d.mkdir()
        (d / "analysis.tsf").write_bytes(b"")
        monkeypatch.setattr(cli, "TsfReader", self._FakeReader)
        out = tmp_path / "o.mzML"

        cli.run_tsf_conversion(ConversionConfig(input=d, output=out, end_frame=4))

        root = ET.parse(out).getroot()
        spectra = root.findall(".//{*}spectrum")
        assert root.find(".//{*}spectrumList").attrib["count"] == "3"  # type: ignore[union-attr]
        assert len(spectra) == 3  # frame 1, 2, 3; frame 4 has no info; frame 5 is out of range
        names = [
            [p.attrib["name"] for p in s.findall(".//{*}activation/{*}cvParam")] for s in spectra
        ]
        assert names[0] == []  # MS1
        assert names[1][0] == "electron activated dissociation"  # frame 2, type 3
        assert "supplemental collision energy" in names[1]
        assert names[2] == ["collision-induced dissociation", "collision energy"]  # frame 3

    def test_metadata_counts_type_2_and_3_as_ms2(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE GlobalMetadata (Key TEXT, Value TEXT)")
        conn.execute("CREATE TABLE Frames (Id INTEGER PRIMARY KEY, MsMsType INTEGER)")
        conn.executemany("INSERT INTO Frames VALUES (?, ?)", list(enumerate([0, 2, 3, 3, 0], 1)))
        reader = TsfReader.__new__(TsfReader)
        reader._tsf = SimpleNamespace(conn=conn)  # type: ignore[attr-defined]
        reader._metadata = None

        meta = reader.metadata

        assert meta.ms1_spectra_count == 2
        assert meta.ms2_dda_count == 3
        assert meta.total_spectra == 5
