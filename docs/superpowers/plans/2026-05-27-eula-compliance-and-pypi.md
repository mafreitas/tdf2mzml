# Bruker SDK EULA Compliance + PyPI Publication Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring tdf2mzml v0.6.1 into full compliance with the Bruker TDF SDK and Baf2Sql EULAs, then publish platform-specific wheels to PyPI under a GitHub Actions trusted-publisher workflow.

**Architecture:**
- **Compliance:** Limit bundled native files to those listed in each SDK's `redist.txt`, bundle the required `THIRD-PARTY-LICENSE-README.txt` (and Baf2Sql `README.txt`), surface Bruker copyright in the CLI `--version` output and a top-level `NOTICE` file, and confirm BSD-4-Clause project license is compatible with Section 5.2 (not an "Excluded License").
- **Distribution:** Build one platform-tagged wheel per OS — `manylinux_2_17_x86_64` (Linux libs) and `win_amd64` (Windows DLLs) — using a custom `bdist_wheel --plat-name` invocation. The pure-Python source files are identical between wheels; only the contents of `tdf2mzml/libs/` differ. Source SDK files live in `Incoming_updates_data/timsdata/` and `Incoming_updates_data/baf2sql-c-2.9.0/` and are the canonical "host location" for future updates.
- **Publishing:** GitHub Actions workflow builds both wheels + sdist on tag push, runs `twine check`, uploads to TestPyPI for verification, then promotes to PyPI via PyPI's OIDC trusted-publisher flow (no long-lived API tokens).

**Tech Stack:** Python 3.11+, setuptools 68+, build, twine, GitHub Actions, PyPI trusted publishers (OIDC).

---

## File Structure

**New files:**
- `NOTICE` — Top-level third-party attributions (Bruker TDF SDK + Baf2Sql) per EULA Section 4.4
- `src/tdf2mzml/libs/THIRD-PARTY-LICENSE-README.txt` — Bruker TDF SDK third-party notice (must accompany libtimsdata.so / timsdata.dll per redist.txt)
- `src/tdf2mzml/libs/BAF2SQL-README.txt` — Baf2Sql README (must accompany libbaf2sql_c.so per redist.txt)
- `src/tdf2mzml/libs/BAF2SQL-THIRD-PARTY-LICENSE-README.txt` — Baf2Sql third-party notice
- `scripts/sync_sdk_libs.py` — Idempotent script that copies the redist-listed files from `Incoming_updates_data/` into `src/tdf2mzml/libs/`. Single source of truth for what gets bundled.
- `scripts/build_wheels.sh` — Build linux and win wheels with correct platform tags
- `.github/workflows/publish.yml` — Tag-triggered build + publish to PyPI (OIDC)
- `docs/PYPI_RELEASE.md` — Operator runbook: how to cut a release, PyPI trusted-publisher setup, TestPyPI dry-run
- `tests/test_compliance.py` — Asserts only redist-listed files are bundled and required notices are present

**Modified files:**
- `pyproject.toml` — Add License/OS classifiers, fix `package-data` (drop `*.lib`), add `[project.urls]` extras, bump version to `0.7.0`
- `src/tdf2mzml/__init__.py` — Expose Bruker SDK version constant for `--version`
- `src/tdf2mzml/cli.py:144-155` — Extend `--version` output to include Bruker TDF SDK / Baf2Sql copyright per EULA §4.4
- `README.md:48,201-206` — Replace "bundles ... so no separate SDK installation is necessary" with EULA-compliant attribution; add NOTICE section
- `Makefile` — Add `sync-libs`, `wheels`, `wheels-clean`, `release-test`, `release` targets
- `.gitignore` — Add `dist/`, `build/` (defensive; setuptools generates these)

**Removed files:**
- `src/tdf2mzml/libs/timsdata.lib` — NOT on Bruker TDF SDK redist.txt (it is a Windows import library for C/C++ compile-time linking, never needed by ctypes at runtime)

**Added (vendored from SDK):**
- `src/tdf2mzml/libs/baf2sql_c.dll` — Win64 Baf2Sql DLL (currently missing; required for Windows BAF support)

---

## Compliance Reference Matrix

| SDK | Bundled lib | Required companion | Currently shipping? |
|-----|-------------|---------------------|---------------------|
| TDF (timsdata) Linux | `libtimsdata.so` | `THIRD-PARTY-LICENSE-README.txt` | lib ✅ / notice ❌ |
| TDF (timsdata) Win64 | `timsdata.dll` | `THIRD-PARTY-LICENSE-README.txt` | lib ✅ / notice ❌ |
| Baf2Sql Linux | `libbaf2sql_c.so` | `README.txt` + `THIRD-PARTY-LICENSE-README.txt` | lib ✅ / notices ❌ |
| Baf2Sql Win64 | `baf2sql_c.dll` | `README.txt` + `THIRD-PARTY-LICENSE-README.txt` | ❌ all missing |
| (NOT redistributable) | `timsdata.lib` (import lib) | — | ❌ shipped in error |

Source of truth: `Incoming_updates_data/timsdata/redist.txt` and `Incoming_updates_data/baf2sql-c-2.9.0/redist.txt`.

---

## Phase 1 — EULA Compliance

### Task 1: Write compliance test (fail-first)

**Files:**
- Create: `tests/test_compliance.py`

- [ ] **Step 1: Write the failing test**

```python
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
    "libtimsdata.so",          # TDF SDK linux64
    "timsdata.dll",            # TDF SDK win64
    "libbaf2sql_c.so",         # Baf2Sql linux64
    "baf2sql_c.dll",           # Baf2Sql win64
}

REQUIRED_NOTICES = {
    "THIRD-PARTY-LICENSE-README.txt",       # TDF SDK
    "BAF2SQL-README.txt",                   # Baf2Sql README (renamed to avoid clash)
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
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/mfreitas/repos/tdf2mzml
python -m pytest tests/test_compliance.py -v
```

Expected: 4 failures (timsdata.lib still present, notice files missing, NOTICE missing, _version_text not defined).

- [ ] **Step 3: Commit the failing test**

```bash
git add tests/test_compliance.py
git commit -m "test: add Bruker SDK redist + notice compliance tests (failing)"
```

---

### Task 2: Add the sync-libs script

**Files:**
- Create: `scripts/sync_sdk_libs.py`

- [ ] **Step 1: Write the script**

```python
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
```

- [ ] **Step 2: Run it**

```bash
python scripts/sync_sdk_libs.py
```

Expected output includes:
```
removing non-redist file: timsdata.lib
copied Incoming_updates_data/timsdata/linux64/libtimsdata.so -> libs/libtimsdata.so
... (7 copies total)
```

- [ ] **Step 3: Verify the libs directory**

```bash
ls -1 src/tdf2mzml/libs/
```

Expected (7 files):
```
BAF2SQL-README.txt
BAF2SQL-THIRD-PARTY-LICENSE-README.txt
baf2sql_c.dll
libbaf2sql_c.so
libtimsdata.so
THIRD-PARTY-LICENSE-README.txt
timsdata.dll
```

- [ ] **Step 4: Commit the script and synced libs**

```bash
git add scripts/sync_sdk_libs.py src/tdf2mzml/libs/
git commit -m "build: sync Bruker SDK libs to match redist.txt allowlists

- Remove timsdata.lib (Windows import lib, not on TDF SDK redist.txt)
- Add baf2sql_c.dll for Windows BAF support
- Bundle THIRD-PARTY-LICENSE-README.txt from TDF SDK
- Bundle BAF2SQL-README.txt and BAF2SQL-THIRD-PARTY-LICENSE-README.txt
- Add scripts/sync_sdk_libs.py to make future updates idempotent

Source files in Incoming_updates_data/{timsdata,baf2sql-c-2.9.0}/ are the
canonical host location for SDK updates."
```

---

### Task 3: Add top-level NOTICE file

**Files:**
- Create: `NOTICE`

- [ ] **Step 1: Write the NOTICE**

```
tdf2mzml — Convert Bruker mass spectrometry data to indexed mzML
Copyright (c) 2020-2026 Michael A. Freitas, The Ohio State University
Licensed under the BSD 4-Clause License (see LICENSE.md).

================================================================================
THIRD-PARTY SOFTWARE NOTICES
================================================================================

This product includes the following third-party software, redistributed in
binary form under the terms of each component's license. The full license
texts are bundled in src/tdf2mzml/libs/ and reproduced with the installed
wheel under tdf2mzml/libs/.

--------------------------------------------------------------------------------
Bruker TDF SDK (TDF Software Development Kit), version 3.3.6.2
Copyright (c) Bruker Daltonics GmbH & Co. KG. All rights reserved.

Redistributed binaries:
  - tdf2mzml/libs/libtimsdata.so   (linux64)
  - tdf2mzml/libs/timsdata.dll     (win64)

Redistribution is governed by the Bruker Daltonics Software License Agreement
("EULA TDF-SDK") accompanying the SDK; the files listed above are those
permitted for redistribution by Section 4 and the SDK's redist.txt.

Third-party components used by the TDF SDK (Intel MKL, zlib, Boost, UTF8-CPP,
SQLite, CppSQLite, VIGRA, Zstandard, and others) are described in:
  tdf2mzml/libs/THIRD-PARTY-LICENSE-README.txt

--------------------------------------------------------------------------------
Bruker Baf2Sql, version 2.9.0
Copyright (c) Bruker Daltonics GmbH & Co. KG. All rights reserved.

Redistributed binaries:
  - tdf2mzml/libs/libbaf2sql_c.so   (linux64)
  - tdf2mzml/libs/baf2sql_c.dll     (win64)

Redistribution is governed by the Bruker Daltonics Baf2Sql End User License
Agreement accompanying the SDK; the files listed above are those permitted
for redistribution by the SDK's redist.txt.

Required accompanying notices:
  tdf2mzml/libs/BAF2SQL-README.txt
  tdf2mzml/libs/BAF2SQL-THIRD-PARTY-LICENSE-README.txt

================================================================================
RUNTIME REQUIREMENTS (Windows)
================================================================================

The Bruker libraries require the Microsoft Visual C++ Redistributable
(Visual Studio 2022 X64). Download and install from:
  https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist
```

- [ ] **Step 2: Commit**

```bash
git add NOTICE
git commit -m "docs: add NOTICE file attributing Bruker TDF SDK and Baf2Sql"
```

---

### Task 4: Extend CLI --version to satisfy EULA §4.4

**Files:**
- Modify: `src/tdf2mzml/__init__.py`
- Modify: `src/tdf2mzml/cli.py:144-155`

- [ ] **Step 1: Add SDK version constants to package init**

Edit `src/tdf2mzml/__init__.py` — append to the existing content:

```python
__version__ = "0.7.0"
__author__ = "Michael A. Freitas"
__license__ = "BSD 4-Clause License"

# Bundled third-party SDK versions — surfaced in CLI --version per
# Bruker EULA §4.4 "About box" attribution requirement.
__bruker_tdf_sdk_version__ = "3.3.6.2"
__bruker_baf2sql_version__ = "2.9.0"
```

- [ ] **Step 2: Add `_version_text` helper to cli.py**

Insert just above `def build_parser()` in `src/tdf2mzml/cli.py`:

```python
def _version_text() -> str:
    """Compose the multi-line --version string.

    Includes Bruker SDK copyright notices required by the TDF SDK EULA §4.4
    and the Baf2Sql EULA equivalent.
    """
    from tdf2mzml import (
        __bruker_baf2sql_version__,
        __bruker_tdf_sdk_version__,
        __version__,
    )
    return (
        f"tdf2mzml {__version__}\n"
        f"Copyright (c) 2020-2026 Michael A. Freitas, The Ohio State University.\n"
        f"Licensed under the BSD 4-Clause License.\n"
        f"\n"
        f"Bundles Bruker TDF SDK {__bruker_tdf_sdk_version__} and "
        f"Bruker Baf2Sql {__bruker_baf2sql_version__}\n"
        f"Copyright (c) Bruker Daltonics GmbH & Co. KG. All rights reserved.\n"
        f"Used under the Bruker Software License Agreements.\n"
        f"See NOTICE and tdf2mzml/libs/THIRD-PARTY-LICENSE-README.txt for details."
    )
```

- [ ] **Step 3: Wire it into the parser**

Replace lines 151-155 of `src/tdf2mzml/cli.py`:

```python
    parser.add_argument(
        "--version",
        action="version",
        version=_version_text(),
    )
```

- [ ] **Step 4: Run the compliance tests**

```bash
python -m pytest tests/test_compliance.py -v
```

Expected: all 4 tests + 2 parametrized = 5 passes.

- [ ] **Step 5: Sanity-check the CLI**

```bash
python -m tdf2mzml.cli --version
```

Expected output (first three lines):
```
tdf2mzml 0.7.0
Copyright (c) 2020-2026 Michael A. Freitas, The Ohio State University.
Licensed under the BSD 4-Clause License.
```

- [ ] **Step 6: Commit**

```bash
git add src/tdf2mzml/__init__.py src/tdf2mzml/cli.py
git commit -m "feat(cli): include Bruker SDK copyright in --version output

Satisfies Bruker TDF SDK EULA §4.4 'About box' attribution requirement
by surfacing TDF SDK and Baf2Sql copyright notices when the user runs
'tdf2mzml --version'."
```

---

### Task 5: Update pyproject.toml package-data and metadata

**Files:**
- Modify: `pyproject.toml:3` (version)
- Modify: `pyproject.toml:8-13` (classifiers)
- Modify: `pyproject.toml:20-21` (urls)
- Modify: `pyproject.toml:49-50` (package-data)

- [ ] **Step 1: Bump version**

Change line 3:
```toml
version = "0.7.0"
```

- [ ] **Step 2: Expand classifiers**

Replace the `classifiers = [...]` block:
```toml
classifiers = [
    "Development Status :: 4 - Beta",
    "Environment :: Console",
    "Intended Audience :: Science/Research",
    "License :: OSI Approved :: BSD License",
    "Operating System :: POSIX :: Linux",
    "Operating System :: Microsoft :: Windows",
    "Programming Language :: Python :: 3 :: Only",
    "Programming Language :: Python :: 3.11",
    "Programming Language :: Python :: 3.12",
    "Programming Language :: Python :: 3.13",
    "Topic :: Scientific/Engineering :: Bio-Informatics",
]
```

- [ ] **Step 3: Add project URLs**

Replace the `[project.urls]` block:
```toml
[project.urls]
Homepage = "https://github.com/mafreitas/tdf2mzml"
Repository = "https://github.com/mafreitas/tdf2mzml"
Issues = "https://github.com/mafreitas/tdf2mzml/issues"
Changelog = "https://github.com/mafreitas/tdf2mzml/blob/main/CHANGELOG.md"
```

- [ ] **Step 4: Tighten package-data (drop *.lib, add notice files)**

Replace the `[tool.setuptools.package-data]` block:
```toml
[tool.setuptools.package-data]
tdf2mzml = [
    "libs/*.so",
    "libs/*.dll",
    "libs/THIRD-PARTY-LICENSE-README.txt",
    "libs/BAF2SQL-README.txt",
    "libs/BAF2SQL-THIRD-PARTY-LICENSE-README.txt",
]
```

Notice: no `libs/*.lib` — Windows import libs are explicitly excluded.

- [ ] **Step 5: Add license-files entry**

After the `license = {file = "LICENSE.md"}` line, add:
```toml
license-files = ["LICENSE.md", "NOTICE"]
```

- [ ] **Step 6: Run all tests**

```bash
make ci
```

Expected: lint + typecheck + tests all pass.

- [ ] **Step 7: Build sdist locally and inspect contents**

```bash
pip install --upgrade build
python -m build --sdist
tar -tzf dist/tdf2mzml-0.7.0.tar.gz | grep -E "(NOTICE|LICENSE|libs/)" | sort
```

Expected: NOTICE, LICENSE.md, and every file in `src/tdf2mzml/libs/` listed.

- [ ] **Step 8: Commit**

```bash
git add pyproject.toml
git commit -m "build(pyproject): bump to 0.7.0, expand classifiers, fix package-data

- Drop libs/*.lib from package-data (Windows import lib, not redistributable)
- Bundle Bruker third-party notice files
- Add OSI BSD License + OS classifiers for PyPI
- Include NOTICE alongside LICENSE.md via license-files"
```

---

### Task 6: Update README compliance language

**Files:**
- Modify: `README.md:48`
- Modify: `README.md:201-206`

- [ ] **Step 1: Replace the dependencies paragraph (line 48)**

Replace:
> The package bundles the required Bruker SDK libraries (`libtimsdata.so`, `timsdata.dll`, `libbaf2sql_c.so`) so no separate SDK installation is necessary.

With:

> The package bundles the redistributable subset of the Bruker TDF SDK (v3.3.6.2)
> and Baf2Sql (v2.9.0) shared libraries on Linux (`libtimsdata.so`,
> `libbaf2sql_c.so`) and Windows (`timsdata.dll`, `baf2sql_c.dll`), redistributed
> under the Bruker Software License Agreements. See [NOTICE](NOTICE) for full
> attribution and third-party component notices. Windows users must also install
> the [Microsoft Visual C++ 2022 X64 Redistributable](https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist).

- [ ] **Step 2: Extend the License section (line 201-206)**

Replace:
```markdown
## License

BSD 4-Clause License. Copyright (c) 2020, Michael A. Freitas, The Ohio State University.

See [LICENSE.md](LICENSE.md) for the full text.
```

With:
```markdown
## License

`tdf2mzml` is released under the **BSD 4-Clause License**, Copyright (c) 2020-2026 Michael A. Freitas, The Ohio State University. See [LICENSE.md](LICENSE.md) for the full text.

### Third-Party Software

This distribution bundles binaries from the **Bruker TDF SDK** (v3.3.6.2) and **Baf2Sql** (v2.9.0), Copyright (c) Bruker Daltonics GmbH & Co. KG. These binaries are redistributed under the Bruker Software License Agreements, in compliance with the redistribution allowlists in each SDK's `redist.txt`. Full attributions and the third-party component license texts are included in [NOTICE](NOTICE) and in `tdf2mzml/libs/THIRD-PARTY-LICENSE-README.txt` (installed alongside the package).

Because the Bruker EULAs prohibit redistribution alongside GPL-family ("Excluded License") software, downstream projects bundling `tdf2mzml` must avoid GPL, LGPL, and AGPL licenses.
```

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs(README): update compliance language for Bruker SDK redistribution"
```

---

## Phase 2 — Platform Wheel Build

### Task 7: Add the wheel build script

**Files:**
- Create: `scripts/build_wheels.sh`

- [ ] **Step 1: Write the script**

```bash
#!/usr/bin/env bash
# Build platform-specific wheels for tdf2mzml.
#
# Produces three artifacts in dist/:
#   - tdf2mzml-X.Y.Z.tar.gz                       (sdist, all sources + libs)
#   - tdf2mzml-X.Y.Z-py3-none-manylinux_2_17_x86_64.whl  (Linux libs only)
#   - tdf2mzml-X.Y.Z-py3-none-win_amd64.whl              (Windows libs only)
#
# The wheels share identical Python sources; they differ only in which
# binaries from src/tdf2mzml/libs/ are retained. We use a staging directory
# per platform so we never mutate the source tree.

set -euo pipefail

REPO_ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cd "$REPO_ROOT"

VERSION=$(python -c "from tdf2mzml import __version__; print(__version__)")
DIST="$REPO_ROOT/dist"
rm -rf "$DIST" build/ src/*.egg-info

python -m pip install --upgrade --quiet build wheel

build_platform_wheel() {
    local plat="$1"
    shift
    local keep_patterns=("$@")

    local stage
    stage=$(mktemp -d -t tdf2mzml-stage-XXXX)
    trap "rm -rf $stage" RETURN

    rsync -a --exclude '.git' --exclude '.venv' --exclude 'dist' \
          --exclude 'build' --exclude 'Incoming_updates_data' \
          --exclude '__pycache__' --exclude '.pytest_cache' \
          --exclude '.mypy_cache' --exclude '.ruff_cache' \
          "$REPO_ROOT/" "$stage/"

    # Strip every binary; then keep only the platform's set.
    find "$stage/src/tdf2mzml/libs" -maxdepth 1 \
         \( -name '*.so' -o -name '*.dll' -o -name '*.lib' \) -delete

    for pat in "${keep_patterns[@]}"; do
        cp "$REPO_ROOT/src/tdf2mzml/libs/$pat" "$stage/src/tdf2mzml/libs/$pat"
    done

    (
        cd "$stage"
        python -m build --wheel \
               --config-setting=--build-option="--plat-name=$plat"
        cp dist/*.whl "$DIST/"
    )
}

mkdir -p "$DIST"

# sdist (single, platform-agnostic; carries every redist-listed lib + notice)
python -m build --sdist
cp dist/*.tar.gz "$DIST/" 2>/dev/null || true

# Linux wheel
build_platform_wheel manylinux_2_17_x86_64 libtimsdata.so libbaf2sql_c.so

# Windows wheel
build_platform_wheel win_amd64 timsdata.dll baf2sql_c.dll

echo
echo "Built artifacts:"
ls -lh "$DIST"

python -m pip install --upgrade --quiet twine
python -m twine check "$DIST"/*
```

- [ ] **Step 2: Make it executable and run**

```bash
chmod +x scripts/build_wheels.sh
./scripts/build_wheels.sh
```

Expected: three files in `dist/` and `twine check` reports `PASSED` for all.

- [ ] **Step 3: Verify each wheel contains the right libs**

```bash
python -c "
import zipfile, glob
for w in sorted(glob.glob('dist/*.whl')):
    print(w)
    with zipfile.ZipFile(w) as z:
        for n in sorted(z.namelist()):
            if 'libs/' in n:
                print('  ', n)
"
```

Expected:
- `manylinux_2_17_x86_64` wheel: only `libtimsdata.so`, `libbaf2sql_c.so`, the 3 notice files.
- `win_amd64` wheel: only `timsdata.dll`, `baf2sql_c.dll`, the 3 notice files.

- [ ] **Step 4: Audit the Linux wheel for manylinux compatibility (show only — do NOT repair)**

```bash
pip install --quiet auditwheel
auditwheel show dist/tdf2mzml-0.7.0-py3-none-manylinux_2_17_x86_64.whl
```

Expected: report shows required external glibc symbols. If `auditwheel` flags an incompatibility (e.g., the .so requires glibc newer than 2.17), bump the tag — see Task 7b below for fallback to `manylinux_2_28` or `linux_x86_64`.

**Do NOT run `auditwheel repair`.** It rewrites the wheel by bundling extra shared libraries and renaming the .so with a content hash, which could be construed as modifying Bruker's redistributable (and Bruker's EULA permits redistribution only of the exact files in `redist.txt`). Use `show` for diagnosis and adjust the platform tag instead.

- [ ] **Step 5: Commit**

```bash
git add scripts/build_wheels.sh
git commit -m "build: add platform-specific wheel build script

Produces sdist + manylinux_2_17_x86_64 + win_amd64 wheels by staging
the source tree per-platform and pruning binaries that don't belong."
```

---

### Task 7b: Adjust platform tag if auditwheel rejects manylinux_2_17

Only execute this task if Task 7 Step 4 reported the .so requires a newer glibc.

- [ ] **Step 1: Determine actual glibc requirement**

```bash
objdump -T src/tdf2mzml/libs/libtimsdata.so | grep -oP 'GLIBC_\K[0-9.]+' | sort -V | tail -1
```

| Output | Use platform tag |
|--------|------------------|
| ≤ 2.17 | `manylinux_2_17_x86_64` (default) |
| 2.18-2.27 | `manylinux_2_28_x86_64` |
| ≥ 2.28 | `linux_x86_64` (no manylinux guarantee; install will only work on glibc-compatible distros) |

- [ ] **Step 2: Update scripts/build_wheels.sh**

Replace the `build_platform_wheel manylinux_2_17_x86_64 ...` line with the appropriate tag from the table above.

- [ ] **Step 3: Re-run and commit**

```bash
./scripts/build_wheels.sh
git add scripts/build_wheels.sh
git commit -m "build: pin Linux wheel to <chosen> per actual glibc requirement"
```

---

### Task 8: Add Makefile targets

**Files:**
- Modify: `Makefile`

- [ ] **Step 1: Edit Makefile**

Add to `.PHONY`:
```makefile
.PHONY: setup clean dev test lint typecheck format build ci sync-libs wheels release-test release
```

Append to the end of the file:
```makefile
sync-libs:
	python scripts/sync_sdk_libs.py

wheels: sync-libs
	./scripts/build_wheels.sh

release-test: wheels
	python -m twine upload --repository testpypi dist/*

release: wheels
	python -m twine upload dist/*
```

- [ ] **Step 2: Smoke-test**

```bash
make sync-libs
make wheels
```

Expected: both targets succeed end-to-end.

- [ ] **Step 3: Commit**

```bash
git add Makefile
git commit -m "build(Makefile): add sync-libs, wheels, release-test, release targets"
```

---

## Phase 3 — PyPI Publish Workflow

### Task 9: Add GitHub Actions publish workflow

**Files:**
- Create: `.github/workflows/publish.yml`

- [ ] **Step 1: Write the workflow**

```yaml
name: Publish

on:
  push:
    tags: ["v*.*.*"]
  workflow_dispatch:
    inputs:
      target:
        description: "Publish target"
        required: true
        default: "testpypi"
        type: choice
        options:
          - testpypi
          - pypi

permissions:
  contents: read

jobs:
  build:
    name: Build wheels + sdist
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v5
      - uses: actions/setup-python@v6
        with:
          python-version: "3.12"

      - name: Verify tag matches package version
        if: startsWith(github.ref, 'refs/tags/')
        run: |
          TAG="${GITHUB_REF##*/}"           # v0.7.0
          PKG=$(python -c "from tdf2mzml import __version__; print('v'+__version__)")
          test "$TAG" = "$PKG" || { echo "tag $TAG != package $PKG"; exit 1; }

      - name: Build platform wheels + sdist
        run: ./scripts/build_wheels.sh

      - name: Verify compliance tests still pass
        run: |
          pip install -e ".[dev]"
          pytest tests/test_compliance.py -v

      - uses: actions/upload-artifact@v4
        with:
          name: dist
          path: dist/

  publish-testpypi:
    name: Publish to TestPyPI
    needs: build
    if: |
      github.event_name == 'push' ||
      (github.event_name == 'workflow_dispatch' && github.event.inputs.target == 'testpypi')
    runs-on: ubuntu-latest
    environment:
      name: testpypi
      url: https://test.pypi.org/p/tdf2mzml
    permissions:
      id-token: write   # required for OIDC trusted publishing
    steps:
      - uses: actions/download-artifact@v4
        with:
          name: dist
          path: dist/
      - uses: pypa/gh-action-pypi-publish@release/v1
        with:
          repository-url: https://test.pypi.org/legacy/

  publish-pypi:
    name: Publish to PyPI
    needs: publish-testpypi
    if: |
      startsWith(github.ref, 'refs/tags/') ||
      (github.event_name == 'workflow_dispatch' && github.event.inputs.target == 'pypi')
    runs-on: ubuntu-latest
    environment:
      name: pypi
      url: https://pypi.org/p/tdf2mzml
    permissions:
      id-token: write
    steps:
      - uses: actions/download-artifact@v4
        with:
          name: dist
          path: dist/
      - uses: pypa/gh-action-pypi-publish@release/v1
```

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/publish.yml
git commit -m "ci: add PyPI publish workflow (OIDC trusted publisher)

Tag push to v*.*.* triggers build -> TestPyPI -> PyPI promotion.
Manual workflow_dispatch can target TestPyPI only for dry runs.
Tag must match tdf2mzml.__version__."
```

---

### Task 10: Write the release runbook

**Files:**
- Create: `docs/PYPI_RELEASE.md`

- [ ] **Step 1: Write the runbook**

```markdown
# Releasing tdf2mzml to PyPI

This project publishes platform-specific wheels (`manylinux_2_17_x86_64` and
`win_amd64`) plus an sdist to PyPI on every `v*.*.*` git tag, via a GitHub
Actions workflow using PyPI's OIDC trusted publisher (no API tokens).

## One-time setup

### 1. Register the project on TestPyPI and PyPI

- Create account on https://test.pypi.org and https://pypi.org if you don't
  have one. Enable 2FA on both.
- Reserve the `tdf2mzml` name by manually uploading a first release once,
  or by configuring trusted publishing before the first release using the
  "pending publisher" flow.

### 2. Configure trusted publishers

For each of TestPyPI and PyPI:

1. Project page → Settings → Publishing → Add a new pending publisher.
2. Fill in:
   - **PyPI Project Name:** `tdf2mzml`
   - **Owner:** `mafreitas`
   - **Repository name:** `tdf2mzml`
   - **Workflow name:** `publish.yml`
   - **Environment name:** `pypi` (or `testpypi`)
3. Save.

### 3. Configure GitHub environments

In the GitHub repo → Settings → Environments → New environment:

- Create `testpypi` and `pypi` environments.
- For `pypi`, add a required reviewer (yourself) so production uploads
  pause for manual approval.

## Cutting a release

1. Update `CHANGELOG.md` with the new version's notes.
2. Bump the version in **two** places (must match exactly):
   - `pyproject.toml` (`version = "X.Y.Z"`)
   - `src/tdf2mzml/__init__.py` (`__version__ = "X.Y.Z"`)
3. If the bundled SDK versions changed, update:
   - `src/tdf2mzml/__init__.py` (`__bruker_tdf_sdk_version__`, `__bruker_baf2sql_version__`)
   - `NOTICE` (SDK version line)
   - `README.md` (the dependencies paragraph)
4. Commit and PR; merge once green.
5. From `main`:
   ```bash
   git tag vX.Y.Z
   git push origin vX.Y.Z
   ```
6. Watch the Actions tab. The workflow will:
   - Build sdist + both wheels
   - Verify `tdf2mzml.__version__` matches the tag
   - Run compliance tests
   - Publish to TestPyPI
   - Wait for `pypi` environment approval, then publish to PyPI

## Dry run (TestPyPI only)

```bash
gh workflow run publish.yml -f target=testpypi
```

Then install from TestPyPI to verify:
```bash
pip install --index-url https://test.pypi.org/simple/ \
            --extra-index-url https://pypi.org/simple/ \
            tdf2mzml==X.Y.Z
tdf2mzml --version    # must show Bruker copyright lines
```

## Local manual release (emergency only)

If the GHA workflow is unavailable:

```bash
# Ensure you're on the tagged commit, working tree clean
make wheels                  # produces dist/*
python -m twine check dist/*
python -m twine upload --repository testpypi dist/*
# install + smoke test, then:
python -m twine upload dist/*
```

This requires API tokens stored in `~/.pypirc`; prefer the OIDC workflow.

## Updating the bundled Bruker SDK

The canonical "host location" for SDK source files is
`Incoming_updates_data/`:

- `Incoming_updates_data/timsdata/` — Bruker TDF SDK install tree
- `Incoming_updates_data/baf2sql-c-2.9.0/` — Baf2Sql install tree

To pick up a new SDK release:

1. Replace the contents of those directories with the new SDK install.
2. Re-read each `redist.txt` — confirm the allowlist hasn't changed.
   If it has, update `scripts/sync_sdk_libs.py`'s `COPY_MAP`.
3. Update version constants in `src/tdf2mzml/__init__.py` and `NOTICE`.
4. Run `make sync-libs` to re-vendor the redistributable files.
5. Run `make ci` and `make wheels` to verify nothing broke.
6. Commit the SDK refresh in a single commit:
   ```bash
   git add Incoming_updates_data/ src/tdf2mzml/libs/ \
           src/tdf2mzml/__init__.py NOTICE scripts/sync_sdk_libs.py
   git commit -m "build: update Bruker TDF SDK to vX.Y.Z and Baf2Sql to vA.B.C"
   ```
```

- [ ] **Step 2: Commit**

```bash
git add docs/PYPI_RELEASE.md
git commit -m "docs: add PyPI release runbook (OIDC trusted publisher)"
```

---

## Phase 4 — First Release

### Task 11: Configure PyPI trusted publishers

This is a manual, browser-based step — no code changes. Required before Task 12.

- [ ] **Step 1: TestPyPI** — follow `docs/PYPI_RELEASE.md` § "Configure trusted publishers" for https://test.pypi.org.
- [ ] **Step 2: PyPI** — same for https://pypi.org.
- [ ] **Step 3: GitHub environments** — create `testpypi` and `pypi` environments, add manual-approval reviewer to `pypi`.

### Task 12: Dry-run via TestPyPI

- [ ] **Step 1: Trigger TestPyPI publish**

```bash
gh workflow run publish.yml -f target=testpypi
gh run watch
```

- [ ] **Step 2: Install from TestPyPI on Linux**

```bash
python -m venv /tmp/tdf2mzml-test
source /tmp/tdf2mzml-test/bin/activate
pip install --index-url https://test.pypi.org/simple/ \
            --extra-index-url https://pypi.org/simple/ \
            tdf2mzml==0.7.0
tdf2mzml --version
```

Expected: version output includes the Bruker copyright block.

- [ ] **Step 3: (Optional) Install from TestPyPI on Windows**

If a Windows machine is available, repeat Step 2 on Windows and confirm `tdf2mzml --version` works (which proves the win_amd64 wheel + `timsdata.dll` load).

### Task 13: First production release

- [ ] **Step 1: Merge `feature/0.6.1-compliance-fixes` to main** via PR.
- [ ] **Step 2: Tag and push**

```bash
git checkout main && git pull
git tag v0.7.0
git push origin v0.7.0
```

- [ ] **Step 3: Approve the `pypi` environment deployment** in the GitHub Actions UI.
- [ ] **Step 4: Verify on PyPI** — visit https://pypi.org/project/tdf2mzml/ and confirm wheels + sdist are listed.
- [ ] **Step 5: Smoke-test from PyPI**

```bash
python -m venv /tmp/tdf2mzml-prod && source /tmp/tdf2mzml-prod/bin/activate
pip install tdf2mzml==0.7.0
tdf2mzml --version
```

---

## Self-Review Checklist

- **Spec coverage:**
  - EULA §4.1-§4.3 (only listed redist files) → Task 1 test + Task 2 sync script
  - EULA §4.4 (About box copyright) → Task 4 (`--version`)
  - Required notice files → Task 2 (copy) + Task 5 (package-data) + Task 3 (NOTICE)
  - §5.2 Excluded License compatibility → BSD 4-Clause already in repo; Task 6 documents the downstream constraint
  - PyPI hosting → Tasks 5, 7, 9, 10, 11, 12, 13
- **Placeholders:** none — every code block is complete.
- **Type consistency:** `_version_text` is defined in Task 4 Step 2 and consumed by Task 1's compliance test (Step 1) — names match.
- **Gotchas worth flagging during execution:**
  - If auditwheel rejects `manylinux_2_17_x86_64`, fall back to Task 7b.
  - The Bruker libs may require Microsoft VC++ 2022 Redist on Windows — documented in NOTICE and README.
  - `Incoming_updates_data/` is not packaged into the wheel/sdist; it lives only in the repo as the source for `sync_sdk_libs.py`. (`MANIFEST.in` not needed — setuptools default sdist excludes it.)
  - Verify the sdist does NOT accidentally include `Incoming_updates_data/` after Task 5 Step 7. If it does, add `MANIFEST.in` with `prune Incoming_updates_data`.
