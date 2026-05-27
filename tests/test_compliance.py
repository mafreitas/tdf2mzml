"""Compliance tests for Bruker SDK redistribution.

These tests enforce that the bundled libs/ directory contains only files
explicitly permitted by the Bruker TDF SDK and Baf2Sql redist.txt files,
and that the required third-party notice files are present.

Run: pytest tests/test_compliance.py -v
"""

from __future__ import annotations

from pathlib import Path

import pytest

LIBS_DIR = Path(__file__).parent.parent / "src" / "tdf2mzml" / "libs"

# From Incoming_updates_data/timsdata/redist.txt and
# Incoming_updates_data/baf2sql-c-2.9.0/redist.txt
ALLOWED_BINARIES = {
    "libtimsdata.so",  # TDF SDK linux64
    "timsdata.dll",  # TDF SDK win64
    "libbaf2sql_c.so",  # Baf2Sql linux64
    "baf2sql_c.dll",  # Baf2Sql win64
}

REQUIRED_NOTICES = {
    "THIRD-PARTY-LICENSE-README.txt",  # TDF SDK
    "BAF2SQL-README.txt",  # Baf2Sql README (renamed to avoid clash)
    "BAF2SQL-THIRD-PARTY-LICENSE-README.txt",
}


def test_only_redist_listed_binaries_are_bundled() -> None:
    """Only binaries listed in the Bruker redist.txt files may ship."""
    binaries = {p.name for p in LIBS_DIR.iterdir() if p.suffix in {".so", ".dll", ".lib"}}
    disallowed = binaries - ALLOWED_BINARIES
    assert not disallowed, (
        f"Disallowed binaries bundled (not on redist.txt): {sorted(disallowed)}. "
        f"See Incoming_updates_data/*/redist.txt."
    )


def test_required_notice_files_present() -> None:
    """All EULA-required notice files must accompany the libs."""
    files = {p.name for p in LIBS_DIR.iterdir()}
    missing = REQUIRED_NOTICES - files
    assert not missing, f"Missing required notices: {sorted(missing)}"


def test_cli_version_contains_bruker_copyright() -> None:
    """--version output must satisfy Bruker EULA §4.4 'About' notice."""
    from tdf2mzml.cli import _version_text  # added in Task 4

    text = _version_text()
    assert "Bruker" in text
    assert "TDF SDK" in text or "Baf2Sql" in text


@pytest.mark.parametrize("required", ["Bruker", "Baf2Sql"])
def test_notice_file_contains_attributions(required: str) -> None:
    """Top-level NOTICE must attribute both SDKs."""
    notice = Path(__file__).parent.parent / "NOTICE"
    assert notice.exists(), "NOTICE file missing at repo root"
    assert required in notice.read_text(encoding="utf-8")
