#!/usr/bin/env bash
# fetch_test_data.sh — Download reference test files for tdf2mzml validation.
#
# Usage:
#   bash test_data/fetch_test_data.sh [--all | --tdf | --tsf | --baf]
#
# Without arguments, downloads everything that is missing.
# Files are placed in the appropriate subdirectory under test_data/.
#
# Sources:
#   TDF + mzML  : PRIDE PXD068318 (timsTOF Pro 2, DIA-PASEF)
#   TSF         : already bundled in Incoming_updates_data/
#   BAF         : PRIDE PXD014619 (Bruker maXis, standalone .baf)
#
# Note: PRIDE does not publish mzML alongside BAF datasets.
#       Generate a BAF reference mzML yourself with msconvert after downloading.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TDF_DIR="$SCRIPT_DIR/tdf"
TSF_DIR="$SCRIPT_DIR/tsf"
BAF_DIR="$SCRIPT_DIR/baf"
REF_DIR="$SCRIPT_DIR/reference"

PRIDE_BASE="ftp://ftp.pride.ebi.ac.uk/pride/data/archive"

mkdir -p "$TDF_DIR" "$TSF_DIR" "$BAF_DIR" "$REF_DIR"

download() {
    local url="$1" dest="$2"
    if [ -f "$dest" ]; then
        echo "  [skip] $(basename $dest) already exists"
        return
    fi
    echo "  Downloading $(basename $dest) ..."
    wget -q --show-progress -O "$dest" "$url"
    echo "  Done: $(du -sh $dest | cut -f1)"
}

fetch_tdf() {
    echo "=== TDF (timsTOF Pro 2, DIA-PASEF) ==="
    echo "Source: PRIDE PXD068318"
    # Smallest .d.zip in the dataset (~8.1 GB) — large, skip by default
    # Paired mzML available (~411 MB)
    echo "  NOTE: TDF .d.zip files are 8+ GB — skipping raw download."
    echo "  Reference mzML (411 MB) is available at:"
    echo "  ${PRIDE_BASE}/2025/10/PXD068318/tims_23jul1345_Slot1-47_1_5268.mzML"
    echo ""
    echo "  To download only the mzML for cross-validation:"
    echo "  wget -P $REF_DIR ${PRIDE_BASE}/2025/10/PXD068318/tims_23jul1345_Slot1-47_1_5268.mzML"
}

fetch_tsf() {
    echo "=== TSF (timsTOF fleX, LC-MS autoMSMS) ==="
    echo "Source: bundled in repository (Incoming_updates_data/)"
    local neg="$TSF_DIR/timsTOF_autoMSMS_Urine_6min_neg.d"
    local pos="$TSF_DIR/timsTOF_autoMSMS_Urine_6min_pos.d"
    if [ -d "$neg" ] && [ -d "$pos" ]; then
        echo "  [ok] TSF .d directories already present in $TSF_DIR"
    else
        echo "  TSF test data not found — copy from Incoming_updates_data/ manually:"
        echo "  cp -r Incoming_updates_data/timsTOF_autoMSMS_Urine_6min_neg.d $TSF_DIR/"
        echo "  cp -r Incoming_updates_data/timsTOF_autoMSMS_Urine_6min_pos.d $TSF_DIR/"
    fi
}

fetch_baf() {
    echo "=== BAF (Bruker maXis, standalone .baf) ==="
    echo "Source: PRIDE PXD014619 — neonatal renal study"
    echo "Instrument: Bruker maXis (LC-MS/MS, no ion mobility)"
    # analysis39.baf is ~229 MB
    download \
        "${PRIDE_BASE}/2021/03/PXD014619/analysis39.baf" \
        "$BAF_DIR/PXD014619_analysis39.baf"
    echo ""
    echo "  NOTE: No paired mzML is available on PRIDE for BAF datasets."
    echo "  To generate a reference mzML, run msconvert:"
    echo "  msconvert $BAF_DIR/PXD014619_analysis39.baf --mzML -o $REF_DIR"
}

case "${1:-all}" in
    --tdf) fetch_tdf ;;
    --tsf) fetch_tsf ;;
    --baf) fetch_baf ;;
    --all|all|"")
        fetch_tdf; echo ""
        fetch_tsf; echo ""
        fetch_baf ;;
    *)
        echo "Usage: $0 [--all | --tdf | --tsf | --baf]"
        exit 1 ;;
esac
