"""SQL IN-clause chunking tests.

Guards against the SQLite ``too many SQL variables`` error on Windows
(#31). All five callers in ``src/tdf2mzml/io/`` that issue
``IN (?, ?, ...)`` queries must batch their placeholders so no single
``execute()`` exceeds :data:`SQL_IN_CHUNK_SIZE`.
"""

from __future__ import annotations

import sqlite3
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from tdf2mzml.io._sql import SQL_IN_CHUNK_SIZE, batched_in_query

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _counting_conn(real_conn: sqlite3.Connection) -> MagicMock:
    """Wrap a real sqlite connection so execute() calls can be counted."""
    return MagicMock(wraps=real_conn)


# ---------------------------------------------------------------------------
# Unit tests on the helper
# ---------------------------------------------------------------------------


class TestBatchedInQuery:
    """Direct unit tests for :func:`batched_in_query`."""

    def test_chunks_at_configured_size(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE T (x INTEGER PRIMARY KEY)")
        ids = list(range(50_000))
        conn.executemany("INSERT INTO T (x) VALUES (?)", [(i,) for i in ids])

        counting = _counting_conn(conn)
        rows = list(
            batched_in_query(
                counting,
                "SELECT x FROM T WHERE x IN ({placeholders})",
                ids,
            )
        )

        assert len(rows) == len(ids)
        # 50000 / 500 = 100 chunks → 100 execute() calls
        assert counting.execute.call_count == 100
        # No chunk exceeded SQL_IN_CHUNK_SIZE placeholders
        for call in counting.execute.call_args_list:
            sql = call.args[0]
            params = call.args[1]
            assert sql.count("?") == len(params)
            assert len(params) <= SQL_IN_CHUNK_SIZE

    def test_empty_ids_yields_nothing(self) -> None:
        conn = sqlite3.connect(":memory:")
        counting = _counting_conn(conn)
        rows = list(
            batched_in_query(
                counting,
                "SELECT x FROM T WHERE x IN ({placeholders})",
                [],
            )
        )
        assert rows == []
        assert counting.execute.call_count == 0

    def test_extra_params_appended_each_chunk(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE T (x INTEGER, kind TEXT)")
        # Rows: 1200 entries split across two kinds
        rows_to_insert: list[tuple[int, str]] = [
            *((i, "a") for i in range(600)),
            *((i, "b") for i in range(600, 1200)),
        ]
        conn.executemany("INSERT INTO T (x, kind) VALUES (?, ?)", rows_to_insert)

        counting = _counting_conn(conn)
        ids = list(range(1200))
        rows = list(
            batched_in_query(
                counting,
                "SELECT x FROM T WHERE x IN ({placeholders}) AND kind = ?",
                ids,
                extra_params=("a",),
            )
        )

        assert len(rows) == 600  # only kind="a" matches
        # 1200/500 → 3 chunks; each must end with "a"
        for call in counting.execute.call_args_list:
            params = call.args[1]
            assert params[-1] == "a"

    def test_unevenly_sized_final_chunk(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE T (x INTEGER PRIMARY KEY)")
        ids = list(range(1234))  # 1234 = 2 full chunks of 500 + remainder 234
        conn.executemany("INSERT INTO T (x) VALUES (?)", [(i,) for i in ids])

        counting = _counting_conn(conn)
        rows = list(
            batched_in_query(
                counting,
                "SELECT x FROM T WHERE x IN ({placeholders})",
                ids,
            )
        )
        assert len(rows) == 1234
        assert counting.execute.call_count == 3
        sizes = [len(call.args[1]) for call in counting.execute.call_args_list]
        assert sizes == [500, 500, 234]


# ---------------------------------------------------------------------------
# Integration tests on each of the 5 SQL sites
# ---------------------------------------------------------------------------

# Each test builds an in-memory SQLite database with synthetic rows for
# >40,000 IDs and verifies the corresponding reader method (a) returns the
# expected count, (b) splits the query into chunks (execute call_count > 1).


_LARGE_N = 40_001  # > 40,000 per spec; also > 32,766 to exercise the Windows fail path


def _make_pasef_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE PasefFrameMsMsInfo ("
        "Precursor INTEGER PRIMARY KEY, IsolationMz REAL, "
        "CollisionEnergy REAL, IsolationWidth REAL)"
    )
    conn.executemany(
        "INSERT INTO PasefFrameMsMsInfo VALUES (?, ?, ?, ?)",
        [(i, 100.0 + i * 0.01, 20.0, 2.0) for i in range(_LARGE_N)],
    )
    return conn


def _make_tsf_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE FrameMsMsInfo ("
        "Frame INTEGER PRIMARY KEY, Parent INTEGER, "
        "TriggerMass REAL, IsolationWidth REAL, "
        "PrecursorCharge INTEGER, CollisionEnergy REAL)"
    )
    conn.executemany(
        "INSERT INTO FrameMsMsInfo VALUES (?, ?, ?, ?, ?, ?)",
        [(i, i - 1, 500.0, 2.0, 2, 25.0) for i in range(_LARGE_N)],
    )
    return conn


def _make_baf_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE Steps (TargetSpectrum INTEGER, Number INTEGER, Mass REAL)")
    conn.executemany(
        "INSERT INTO Steps VALUES (?, 0, ?)",
        [(i, 100.0 + i * 0.01) for i in range(_LARGE_N)],
    )
    conn.execute("CREATE TABLE Variables (Spectrum INTEGER, Variable INTEGER, Value REAL)")
    # Insert two variables per spectrum (collision_energy=5, isolation_width=8)
    conn.executemany(
        "INSERT INTO Variables VALUES (?, ?, ?)",
        [(i, 5, 25.0) for i in range(_LARGE_N)] + [(i, 8, 2.0) for i in range(_LARGE_N)],
    )
    return conn


class TestPasefChunking:
    """``io/reader.py:get_pasef_frame_info_batch`` (#31 reported site)."""

    def test_large_precursor_list(self) -> None:
        try:
            from tdf2mzml.io.reader import TdfReader
        except OSError as exc:
            pytest.skip(f"Bruker SDK not available: {exc}")
        conn = _counting_conn(_make_pasef_conn())
        reader = TdfReader.__new__(TdfReader)
        reader._tims = SimpleNamespace(conn=conn)  # type: ignore[attr-defined]

        ids = list(range(_LARGE_N))
        result = reader.get_pasef_frame_info_batch(ids)

        assert len(result) == _LARGE_N
        assert conn.execute.call_count > 1  # chunking actually ran
        assert all(len(call.args[1]) <= SQL_IN_CHUNK_SIZE for call in conn.execute.call_args_list)


class TestTsfChunking:
    """``io/tsf_reader.py`` — two IN-clause sites."""

    def test_ms2_info_batch_large(self) -> None:
        try:
            from tdf2mzml.io.tsf_reader import TsfReader
        except OSError as exc:
            pytest.skip(f"Bruker SDK not available: {exc}")
        conn = _counting_conn(_make_tsf_conn())
        reader = TsfReader.__new__(TsfReader)
        reader._tsf = SimpleNamespace(conn=conn)  # type: ignore[attr-defined]

        ids = list(range(_LARGE_N))
        result = reader.get_ms2_info_batch(ids)

        assert len(result) == _LARGE_N
        assert conn.execute.call_count > 1
        assert all(len(call.args[1]) <= SQL_IN_CHUNK_SIZE for call in conn.execute.call_args_list)

    def test_parent_ms1_ids_large(self) -> None:
        try:
            from tdf2mzml.io.tsf_reader import TsfReader
        except OSError as exc:
            pytest.skip(f"Bruker SDK not available: {exc}")
        conn = _counting_conn(_make_tsf_conn())
        reader = TsfReader.__new__(TsfReader)
        reader._tsf = SimpleNamespace(conn=conn)  # type: ignore[attr-defined]

        ids = list(range(_LARGE_N))
        result = reader.get_parent_ms1_ids(ids)

        assert len(result) == _LARGE_N
        assert conn.execute.call_count > 1
        assert all(len(call.args[1]) <= SQL_IN_CHUNK_SIZE for call in conn.execute.call_args_list)


class TestBafChunking:
    """``io/baf_reader.py`` — Steps single IN + Variables 2D IN."""

    def _make_reader(self, conn: MagicMock) -> Any:  # noqa: ANN401
        from tdf2mzml.io.baf_reader import BafReader

        reader = BafReader.__new__(BafReader)
        reader._baf = SimpleNamespace(conn=conn)  # type: ignore[attr-defined]
        reader._var_collision_energy = 5  # type: ignore[attr-defined]
        reader._var_isolation_width = 8  # type: ignore[attr-defined]
        return reader

    def test_precursor_info_batch_large(self) -> None:
        conn = _counting_conn(_make_baf_conn())
        reader = self._make_reader(conn)

        ids = list(range(_LARGE_N))
        result = reader.get_ms2_precursor_batch(ids)

        assert len(result) == _LARGE_N
        # Steps query + Variables query both chunked → many execute() calls
        assert conn.execute.call_count > 2
        assert all(
            len(call.args[1]) <= SQL_IN_CHUNK_SIZE + 2  # +2 for var_ids tail
            for call in conn.execute.call_args_list
        )

    def test_variables_2d_does_not_chunk_var_ids(self) -> None:
        """The bounded ``var_ids`` (≤2 values) must not be chunked."""
        conn = _counting_conn(_make_baf_conn())
        reader = self._make_reader(conn)

        ids = list(range(_LARGE_N))
        reader.get_ms2_precursor_batch(ids)

        # Inspect Variables-query calls: each must have exactly 2 var_id
        # placeholders at the tail. The outer Spectrum IN list varies per
        # chunk; var_ids never expand or shrink.
        var_calls = [c for c in conn.execute.call_args_list if "Variables" in c.args[0]]
        assert var_calls, "expected at least one Variables query"
        for call in var_calls:
            sql = call.args[0]
            params = call.args[1]
            # The SQL has two IN clauses: Spectrum IN (...) AND Variable IN (?, ?)
            assert "Variable IN (?,?)" in sql or "Variable IN (?, ?)" in sql
            # Tail two params must be the var_ids (5, 8) — unchanged per call
            assert params[-2:] == (5, 8)


@pytest.mark.parametrize("size", [SQL_IN_CHUNK_SIZE - 1, SQL_IN_CHUNK_SIZE, SQL_IN_CHUNK_SIZE + 1])
def test_boundary_sizes(size: int) -> None:
    """Exact-boundary IDs around SQL_IN_CHUNK_SIZE chunk cleanly."""
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE T (x INTEGER PRIMARY KEY)")
    ids = list(range(size))
    conn.executemany("INSERT INTO T (x) VALUES (?)", [(i,) for i in ids])

    counting = _counting_conn(conn)
    rows = list(
        batched_in_query(
            counting,
            "SELECT x FROM T WHERE x IN ({placeholders})",
            ids,
        )
    )
    assert len(rows) == size
