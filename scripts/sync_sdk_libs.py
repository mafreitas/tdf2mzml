#!/usr/bin/env python3
"""Sync Bruker SDK files from Incoming_updates_data/ into src/tdf2mzml/libs/.

Copies ONLY the files listed in each SDK's redist.txt plus required notices.
Renames Baf2Sql notices to avoid filename collisions with the TDF SDK notices.

Run from repo root: python scripts/sync_sdk_libs.py
"""

from __future__ import annotations

import shutil
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SRC_TDF = REPO / "Incoming_updates_data" / "timsdata"
SRC_BAF = REPO / "Incoming_updates_data" / "baf2sql-c-2.9.0"
DEST = REPO / "src" / "tdf2mzml" / "libs"

# (source, dest_name). Source paths from Incoming_updates_data/*/redist.txt
COPY_MAP: list[tuple[Path, str]] = [
    # TDF SDK binaries
    (SRC_TDF / "linux64" / "libtimsdata.so", "libtimsdata.so"),
    (SRC_TDF / "win64" / "timsdata.dll", "timsdata.dll"),
    # TDF SDK required notice
    (SRC_TDF / "THIRD-PARTY-LICENSE-README.txt", "THIRD-PARTY-LICENSE-README.txt"),
    # Baf2Sql binaries
    (SRC_BAF / "linux64" / "libbaf2sql_c.so", "libbaf2sql_c.so"),
    (SRC_BAF / "win64" / "baf2sql_c.dll", "baf2sql_c.dll"),
    # Baf2Sql required notices (renamed to avoid clash with TDF notice)
    (SRC_BAF / "README.txt", "BAF2SQL-README.txt"),
    (SRC_BAF / "THIRD-PARTY-LICENSE-README.txt", "BAF2SQL-THIRD-PARTY-LICENSE-README.txt"),
]


def main() -> int:
    """Copy redist-listed SDK files into the libs/ directory; return exit code."""
    DEST.mkdir(parents=True, exist_ok=True)
    missing = [src for src, _ in COPY_MAP if not src.exists()]
    if missing:
        print("ERROR: source SDK files missing:")
        for m in missing:
            print(f"  - {m}")
        return 1

    # Remove anything in DEST that we are not about to put back.
    allowed_dest = {name for _, name in COPY_MAP}
    for existing in DEST.iterdir():
        if existing.name not in allowed_dest:
            print(f"removing non-redist file: {existing.name}")
            existing.unlink()

    for src, dest_name in COPY_MAP:
        dest = DEST / dest_name
        shutil.copy2(src, dest)
        print(f"copied {src.relative_to(REPO)} -> libs/{dest_name}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
