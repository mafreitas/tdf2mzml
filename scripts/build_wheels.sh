#!/usr/bin/env bash
# Build platform-specific wheels for tdf2mzml.
#
# Produces three artifacts in dist/:
#   - tdf2mzml-X.Y.Z.tar.gz                       (sdist, all sources + libs)
#   - tdf2mzml-X.Y.Z-py3-none-manylinux_2_24_x86_64.whl  (Linux libs only)
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
build_platform_wheel manylinux_2_24_x86_64 libtimsdata.so libbaf2sql_c.so

# Windows wheel
build_platform_wheel win_amd64 timsdata.dll baf2sql_c.dll

echo
echo "Built artifacts:"
ls -lh "$DIST"

python -m pip install --upgrade --quiet twine
python -m twine check "$DIST"/*
