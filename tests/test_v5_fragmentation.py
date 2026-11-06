"""Schema v5 (ExD, ECcID) precursor and activation tests.

The databases are built in memory, so no Bruker data is needed. They cover the
cases found in real timsOmni data: ExD-only precursors, ExD followed by a linked
CID step (ECcID), and precursors that use plain CID.
"""

from __future__ import annotations

import logging
import sqlite3
from types import SimpleNamespace

import pytest

try:
    from tdf2mzml.io.reader import TdfReader
except OSError as exc:  # the Bruker SDK library cannot be loaded on this platform
    pytest.skip(f"Bruker SDK not available: {exc}", allow_module_level=True)

from tdf2mzml.processing.ms2 import get_pasef_dda_ms2

_SCHEMA_V5 = """
CREATE TABLE FragmentationIsolationWindow (
    Id INTEGER PRIMARY KEY, IsolationMz REAL, IsolationWidth REAL,
    ScanNumBegin INTEGER, ScanNumEnd INTEGER);
CREATE TABLE FragmentationStep (
    Id INTEGER PRIMARY KEY, IsolationWindow INTEGER, FragmentationType INTEGER NOT NULL,
    Precursor INTEGER, PrmTarget INTEGER);
CREATE TABLE FragmentationStepToStep (
    FragmentationStepId INTEGER PRIMARY KEY, FragmentationStepOriginId INTEGER NOT NULL);
CREATE TABLE FragmentationCid (FragmentationStepId INTEGER PRIMARY KEY, CollisionEnergy REAL);
CREATE TABLE FragmentationExd (
    FragmentationStepId INTEGER PRIMARY KEY, ReactionTime INTEGER, ElectronEnergy REAL);
CREATE TABLE FragmentationEtd (FragmentationStepId INTEGER PRIMARY KEY, ReactionTime INTEGER);
"""

_CID, _ETD, _EXD = 1, 3, 4


def _make_reader(conn: sqlite3.Connection) -> TdfReader:
    reader = TdfReader.__new__(TdfReader)
    reader._tims = SimpleNamespace(conn=conn)  # type: ignore[attr-defined]
    reader._metadata = None
    return reader


@pytest.fixture
def v5_conn() -> sqlite3.Connection:
    """In-memory schema v5 database with four isolation windows."""
    conn = sqlite3.connect(":memory:")
    conn.executescript(_SCHEMA_V5)
    conn.executemany(
        "INSERT INTO FragmentationIsolationWindow VALUES (?, ?, 2.5, 400, 430)",
        [(1, 700.5), (2, 800.5), (3, 900.5), (4, 1000.5)],
    )
    return conn


def _add_step(
    conn: sqlite3.Connection,
    step_id: int,
    frag_type: int,
    precursor: int | None,
    window: int | None,
) -> None:
    conn.execute(
        "INSERT INTO FragmentationStep VALUES (?, ?, ?, ?, NULL)",
        (step_id, window, frag_type, precursor),
    )


class TestFragmentationInfo:
    """``TdfReader.get_pasef_frame_info_batch`` on schema v5 data."""

    def test_cid_only(self, v5_conn: sqlite3.Connection) -> None:
        _add_step(v5_conn, 1, _CID, precursor=10, window=1)
        v5_conn.execute("INSERT INTO FragmentationCid VALUES (1, 32.5)")

        info = _make_reader(v5_conn).get_pasef_frame_info_batch([10])

        assert info[10] == {
            "IsolationMz": 700.5,
            "IsolationWidth": 2.5,
            "CollisionEnergy": 32.5,
            "ReactionTime": None,
            "ElectronEnergy": None,
            "PrecursorGroup": None,
        }

    def test_precursor_group(self, v5_conn: sqlite3.Connection) -> None:
        # Schema 5.1 adds FragmentationPrecursor.PrecursorGroup (guided-PASEF).
        v5_conn.execute(
            "CREATE TABLE FragmentationPrecursor (Id INTEGER PRIMARY KEY, PrecursorGroup INTEGER)"
        )
        v5_conn.executemany(
            "INSERT INTO FragmentationPrecursor VALUES (?, ?)", [(10, 7), (11, None)]
        )
        _add_step(v5_conn, 1, _CID, precursor=10, window=1)
        _add_step(v5_conn, 2, _CID, precursor=11, window=2)
        v5_conn.executemany("INSERT INTO FragmentationCid VALUES (?, 30.0)", [(1,), (2,)])

        info = _make_reader(v5_conn).get_pasef_frame_info_batch([10, 11])

        assert info[10]["PrecursorGroup"] == 7.0
        assert info[11]["PrecursorGroup"] is None

    def test_exd_only_has_no_collision_energy(self, v5_conn: sqlite3.Connection) -> None:
        _add_step(v5_conn, 1, _EXD, precursor=10, window=1)
        v5_conn.execute("INSERT INTO FragmentationExd VALUES (1, 30, 35.0)")

        info = _make_reader(v5_conn).get_pasef_frame_info_batch([10])[10]

        assert info["CollisionEnergy"] is None
        assert info["ReactionTime"] == 30.0
        assert info["ElectronEnergy"] == 35.0

    def test_exd_then_linked_cid(self, v5_conn: sqlite3.Connection) -> None:
        # ECcID: the ExD step holds the precursor and window, the CID step follows it.
        _add_step(v5_conn, 1, _EXD, precursor=10, window=1)
        _add_step(v5_conn, 2, _CID, precursor=None, window=None)
        v5_conn.execute("INSERT INTO FragmentationExd VALUES (1, 30, 0.0)")
        v5_conn.execute("INSERT INTO FragmentationCid VALUES (2, 57.5)")
        v5_conn.execute("INSERT INTO FragmentationStepToStep VALUES (2, 1)")

        info = _make_reader(v5_conn).get_pasef_frame_info_batch([10])[10]

        assert info["IsolationMz"] == 700.5
        assert info["ElectronEnergy"] == 0.0
        assert info["CollisionEnergy"] == 57.5

    def test_etd_reaction_time(self, v5_conn: sqlite3.Connection) -> None:
        _add_step(v5_conn, 1, _ETD, precursor=10, window=1)
        v5_conn.execute("INSERT INTO FragmentationEtd VALUES (1, 50)")

        info = _make_reader(v5_conn).get_pasef_frame_info_batch([10])[10]

        assert info["ReactionTime"] == 50.0
        assert info["ElectronEnergy"] is None

    def test_uses_first_step_of_each_precursor(self, v5_conn: sqlite3.Connection) -> None:
        # Each frame of a precursor has its own step; the values are the same.
        for step_id in (1, 2, 3):
            _add_step(v5_conn, step_id, _CID, precursor=10, window=1)
            v5_conn.execute("INSERT INTO FragmentationCid VALUES (?, 20.0)", (step_id,))
        _add_step(v5_conn, 4, _CID, precursor=11, window=2)
        v5_conn.execute("INSERT INTO FragmentationCid VALUES (4, 25.0)")

        info = _make_reader(v5_conn).get_pasef_frame_info_batch([10, 11, 12])

        assert sorted(info) == [10, 11]  # 12 has no step
        assert info[11]["IsolationMz"] == 800.5

    def test_mixed_activation_warns(
        self, v5_conn: sqlite3.Connection, caplog: pytest.LogCaptureFixture
    ) -> None:
        _add_step(v5_conn, 1, _CID, precursor=10, window=1)
        _add_step(v5_conn, 2, _EXD, precursor=10, window=1)
        v5_conn.execute("INSERT INTO FragmentationCid VALUES (1, 30.0)")
        v5_conn.execute("INSERT INTO FragmentationExd VALUES (2, 30, 35.0)")

        with caplog.at_level(logging.WARNING, logger="tdf2mzml.io.reader"):
            info = _make_reader(v5_conn).get_pasef_frame_info_batch([10])

        assert info[10]["CollisionEnergy"] == 30.0  # first step wins
        assert "different activation settings" in caplog.text

    def test_different_energy_values_warn(
        self, v5_conn: sqlite3.Connection, caplog: pytest.LogCaptureFixture
    ) -> None:
        # Same activation type, different energy: your query3 reports this as duplicate rows.
        _add_step(v5_conn, 1, _CID, precursor=10, window=1)
        _add_step(v5_conn, 2, _CID, precursor=10, window=1)
        v5_conn.executemany("INSERT INTO FragmentationCid VALUES (?, ?)", [(1, 30.0), (2, 35.0)])

        with caplog.at_level(logging.WARNING, logger="tdf2mzml.io.reader"):
            info = _make_reader(v5_conn).get_pasef_frame_info_batch([10])

        assert info[10]["CollisionEnergy"] == 30.0
        assert "different activation settings" in caplog.text

    def test_single_precursor_lookup(self, v5_conn: sqlite3.Connection) -> None:
        _add_step(v5_conn, 1, _EXD, precursor=10, window=1)
        v5_conn.execute("INSERT INTO FragmentationExd VALUES (1, 30, 35.0)")

        assert _make_reader(v5_conn).get_pasef_frame_info(10)["ElectronEnergy"] == 35.0

    def test_old_schema_reads_pasef_table_unchanged(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.execute(
            "CREATE TABLE PasefFrameMsMsInfo (Precursor INTEGER, IsolationMz REAL, "
            "CollisionEnergy REAL, IsolationWidth REAL)"
        )
        conn.execute("INSERT INTO PasefFrameMsMsInfo VALUES (10, 700.5, 32.5, 2.5)")

        info = _make_reader(conn).get_pasef_frame_info_batch([10])

        assert info == {10: {"IsolationMz": 700.5, "CollisionEnergy": 32.5, "IsolationWidth": 2.5}}


def _metadata_conn(
    schema_major: str, frame_types: list[int], n_precursors: int
) -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE GlobalMetadata (Key TEXT, Value TEXT)")
    conn.execute("INSERT INTO GlobalMetadata VALUES ('SchemaVersionMajor', ?)", (schema_major,))
    conn.execute("CREATE TABLE Frames (Id INTEGER PRIMARY KEY, MsMsType INTEGER)")
    conn.executemany("INSERT INTO Frames VALUES (?, ?)", list(enumerate(frame_types, 1)))
    conn.execute("CREATE TABLE Precursors (Id INTEGER PRIMARY KEY)")
    conn.executemany("INSERT INTO Precursors VALUES (?)", [(i,) for i in range(n_precursors)])
    return conn


class TestMetadataCounts:
    """``AcquisitionMetadata`` DDA detection for ExD frames."""

    def test_v5_exd_frames_count_as_dda(self) -> None:
        # ExD MS2 frames are MsMsType 3, so only the Precursors view shows the DDA data.
        meta = _make_reader(_metadata_conn("5", [0, 3, 3, 0, 3], 2)).metadata

        assert meta.has_pasef_dda
        assert meta.ms2_dda_count == 2
        assert meta.total_spectra == 4  # 2 MS1 + 2 precursors

    def test_old_schema_without_pasef_frames_is_not_dda(self) -> None:
        # Schema below 5 keeps the old rule: no MsMsType=8 frame means no DDA MS2 output.
        meta = _make_reader(_metadata_conn("3", [0, 0], 5)).metadata

        assert not meta.has_pasef_dda
        assert meta.ms2_dda_count == 0

    def test_old_schema_pasef_frames(self) -> None:
        meta = _make_reader(_metadata_conn("3", [0, 8, 8], 4)).metadata

        assert meta.has_pasef_dda
        assert meta.ms2_dda_count == 4


class TestPrecursorActivation:
    """``get_pasef_dda_ms2`` picks the activation method from the precursor info."""

    _PRECURSOR = {  # noqa: RUF012
        "Id": 10,
        "Parent": 1,
        "LargestPeakMz": 700.0,
        "MonoisotopicMz": 699.5,
        "Charge": 2,
        "ScanNumber": None,
    }

    def _info(self, pasef: dict[str, float | None]) -> object:
        peaks = {10: ([100.0, 200.0], [5.0, 6.0])}
        _, info = get_pasef_dda_ms2(
            reader=SimpleNamespace(),  # type: ignore[arg-type]
            precursor=self._PRECURSOR,  # type: ignore[arg-type]
            parent_spectrum_id="index=1",
            ms2_data=peaks,
            pasef_info={10: pasef},
            one_over_k0=1.0,
        )
        return info

    def test_old_schema_info_is_cid(self) -> None:
        info = self._info({"IsolationMz": 700.0, "CollisionEnergy": 30.0, "IsolationWidth": 2.0})

        assert info.activation == "CID"  # type: ignore[attr-defined]
        assert info.collision_energy == 30.0  # type: ignore[attr-defined]
        assert info.electron_energy is None  # type: ignore[attr-defined]
        assert info.precursor_group is None  # type: ignore[attr-defined]

    def test_precursor_group(self) -> None:
        info = self._info(
            {
                "IsolationMz": 700.0,
                "IsolationWidth": 2.0,
                "CollisionEnergy": 30.0,
                "PrecursorGroup": 43.0,
            }
        )

        assert info.precursor_group == 43  # type: ignore[attr-defined]

    def test_exd_with_linked_cid(self) -> None:
        info = self._info(
            {
                "IsolationMz": 700.0,
                "IsolationWidth": 2.0,
                "CollisionEnergy": 57.5,
                "ReactionTime": 30.0,
                "ElectronEnergy": 0.0,
            }
        )

        assert info.activation == "ExD"  # type: ignore[attr-defined]
        assert info.electron_energy == 0.0  # type: ignore[attr-defined]
        assert info.reaction_time_ms == 30.0  # type: ignore[attr-defined]
        assert info.collision_energy == 57.5  # type: ignore[attr-defined]

    def test_exd_without_cid(self) -> None:
        info = self._info(
            {
                "IsolationMz": 700.0,
                "IsolationWidth": 2.0,
                "CollisionEnergy": None,
                "ReactionTime": 30.0,
                "ElectronEnergy": 35.0,
            }
        )

        assert info.activation == "ExD"  # type: ignore[attr-defined]
        assert info.collision_energy is None  # type: ignore[attr-defined]

    def test_etd(self) -> None:
        info = self._info(
            {
                "IsolationMz": 700.0,
                "IsolationWidth": 2.0,
                "CollisionEnergy": None,
                "ReactionTime": 50.0,
                "ElectronEnergy": None,
            }
        )

        assert info.activation == "ETD"  # type: ignore[attr-defined]
