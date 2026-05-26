"""SQL helpers shared by the Bruker readers.

Avoids the SQLite ``too many SQL variables`` error on Windows by chunking
any ``IN (?, ?, ...)`` query whose placeholder list might exceed the
SQLite variable limit (``SQLITE_MAX_VARIABLE_NUMBER``, default 32766 on
Windows CPython, 999 on older builds).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from typing import Any

SQL_IN_CHUNK_SIZE: int = 500


def batched_in_query(
    conn: sqlite3.Connection,
    sql_template: str,
    ids: list[int],
    *,
    extra_params: tuple[Any, ...] = (),
) -> Iterator[tuple[Any, ...]]:
    """Execute a SQL IN-clause query in chunks of :data:`SQL_IN_CHUNK_SIZE`.

    ``sql_template`` must contain exactly one ``{placeholders}`` format
    slot. Each chunk fills that slot with ``"?,?,?,..."`` of the
    appropriate length and runs ``conn.execute`` once. Rows are yielded
    in chunk order (the order within a chunk follows SQLite's own ordering
    for that statement — callers that need a specific ordering must
    dict-map by key or sort downstream).

    Parameters
    ----------
    conn
        Open SQLite connection.
    sql_template
        Query string with one ``{placeholders}`` slot, e.g.
        ``"SELECT a, b FROM T WHERE x IN ({placeholders})"``.
    ids
        Values to substitute. Splits into chunks of ``SQL_IN_CHUNK_SIZE``.
    extra_params
        Additional positional params appended *after* each chunk's
        placeholders. Used when the SQL has both ``IN(...)`` and other
        bound parameters (including a second, bounded ``IN (...)``
        inlined directly in the template).

    Yields
    ------
    tuple
        Rows from each chunk's ``execute()`` call.
    """
    if not ids:
        return
    for start in range(0, len(ids), SQL_IN_CHUNK_SIZE):
        chunk = ids[start : start + SQL_IN_CHUNK_SIZE]
        placeholders = ",".join("?" * len(chunk))
        yield from conn.execute(
            sql_template.format(placeholders=placeholders),
            (*chunk, *extra_params),
        )
