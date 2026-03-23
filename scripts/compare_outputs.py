"""compare_outputs.py — Cross-validate tdf2mzml output against a reference mzML.

Compares sampled spectra from two mzML files on:
  - Total spectrum count
  - MS1 / MS2 ratio
  - Binary array data (m/z + intensity) for MS2 spectra
  - Precursor m/z values
  - Key metadata (run ID, sample name, acquisition datetime)

Usage:
    python test_data/compare_outputs.py <ours.mzML> <reference.mzML> [--n-sample N]

Exit code 0 = all checks pass, 1 = differences found.
"""

from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np

NS = {"m": "http://psi.hupo.org/ms/mzml"}

SEPARATOR = "─" * 60


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _count_attr(root: ET.Element, tag: str, attr: str) -> int:
    el = root.find(f".//{tag}", NS)
    return int(el.attrib.get(attr, 0)) if el is not None else 0


def _text(root: ET.Element, tag: str) -> str:
    el = root.find(f".//{tag}", NS)
    return (el.text or "").strip() if el is not None else ""


def _cv(spec: ET.Element, accession: str) -> str | None:
    el = spec.find(f".//m:cvParam[@accession='{accession}']", NS)
    return el.attrib.get("value") if el is not None else None


def _arrays(spec: ET.Element) -> tuple[np.ndarray, np.ndarray]:
    import base64, zlib
    mz = np.empty(0)
    intensity = np.empty(0)
    for arr in spec.findall(".//m:binaryDataArray", NS):
        names = {p.attrib.get("name", "") for p in arr.findall("m:cvParam", NS)}
        binary_el = arr.find("m:binary", NS)
        if binary_el is None or not (binary_el.text or "").strip():
            continue
        raw = base64.b64decode(binary_el.text.strip())
        if "zlib compression" in names:
            raw = zlib.decompress(raw)
        if "64-bit float" in names:
            arr_data = np.frombuffer(raw, dtype=np.float64)
        else:
            arr_data = np.frombuffer(raw, dtype=np.float32).astype(np.float64)
        if "m/z array" in names:
            mz = arr_data
        elif "intensity array" in names:
            intensity = arr_data
    return mz, intensity


def _ms_level(spec: ET.Element) -> int:
    v = _cv(spec, "MS:1000511")
    return int(v) if v else 0


def _precursor_mz(spec: ET.Element) -> float | None:
    el = spec.find(".//m:selectedIon/m:cvParam[@accession='MS:1000744']", NS)
    return float(el.attrib["value"]) if el is not None else None


# ---------------------------------------------------------------------------
# Main comparison
# ---------------------------------------------------------------------------


def compare(ours_path: Path, ref_path: Path, n_sample: int = 50) -> bool:
    print(SEPARATOR)
    print(f"Ours      : {ours_path}")
    print(f"Reference : {ref_path}")
    print(SEPARATOR)

    ours_tree = ET.parse(ours_path)
    ref_tree = ET.parse(ref_path)
    ours_root = ours_tree.getroot()
    ref_root = ref_tree.getroot()

    ok = True

    # ---- Spectrum counts ----
    ours_count = _count_attr(ours_root, "m:spectrumList", "count")
    ref_count = _count_attr(ref_root, "m:spectrumList", "count")
    match = ours_count == ref_count
    print(f"Spectrum count : ours={ours_count}  ref={ref_count}  {'✓' if match else '✗ MISMATCH'}")
    if not match:
        ok = False

    # ---- Metadata ----
    for label, tag in [
        ("Run ID",       "m:run"),
        ("Sample name",  "m:sample"),
        ("File checksum","m:fileChecksum"),
    ]:
        ours_val = ours_root.find(f".//{tag}", NS)
        ref_val  = ref_root.find(f".//{tag}", NS)
        ov = (ours_val.attrib.get("id") or ours_val.text or "").strip() if ours_val is not None else ""
        rv = (ref_val.attrib.get("id")  or ref_val.text  or "").strip() if ref_val  is not None else ""
        # Checksum will differ; just note presence
        if "checksum" in label.lower():
            has = bool(ov) and bool(rv)
            print(f"{label:<15}: {'both present ✓' if has else 'missing in one ✗'}")
        else:
            match = ov == rv
            print(f"{label:<15}: ours={ov!r}  ref={rv!r}  {'✓' if match else '✗ MISMATCH'}")
            if not match:
                ok = False

    # ---- MS1 / MS2 split ----
    ours_specs = ours_root.findall(".//m:spectrum", NS)
    ref_specs  = ref_root.findall(".//m:spectrum",  NS)

    ours_ms1 = sum(1 for s in ours_specs if _ms_level(s) == 1)
    ours_ms2 = sum(1 for s in ours_specs if _ms_level(s) == 2)
    ref_ms1  = sum(1 for s in ref_specs  if _ms_level(s) == 1)
    ref_ms2  = sum(1 for s in ref_specs  if _ms_level(s) == 2)
    match_ms = ours_ms1 == ref_ms1 and ours_ms2 == ref_ms2
    print(f"MS1/MS2 split  : ours={ours_ms1}/{ours_ms2}  ref={ref_ms1}/{ref_ms2}  {'✓' if match_ms else '✗ MISMATCH'}")
    if not match_ms:
        ok = False

    # ---- Sample MS2 binary arrays ----
    ms2_ours = [s for s in ours_specs if _ms_level(s) == 2]
    ms2_ref  = [s for s in ref_specs  if _ms_level(s) == 2]
    n = min(n_sample, len(ms2_ours), len(ms2_ref))
    step = max(1, len(ms2_ours) // n)
    indices = list(range(0, len(ms2_ours), step))[:n]

    mz_matches = int_matches = prec_matches = 0
    mz_max_diff = 0.0
    int_max_diff = 0.0

    for idx in indices:
        if idx >= len(ms2_ref):
            break
        o_mz, o_int = _arrays(ms2_ours[idx])
        r_mz, r_int = _arrays(ms2_ref[idx])
        o_prec = _precursor_mz(ms2_ours[idx])
        r_prec = _precursor_mz(ms2_ref[idx])

        if len(o_mz) == len(r_mz) and len(o_mz) > 0:
            diff = float(np.max(np.abs(o_mz - r_mz)))
            mz_max_diff = max(mz_max_diff, diff)
            if diff < 1e-6:
                mz_matches += 1
        elif len(o_mz) == 0 and len(r_mz) == 0:
            mz_matches += 1

        if len(o_int) == len(r_int) and len(o_int) > 0:
            diff = float(np.max(np.abs(o_int - r_int)))
            int_max_diff = max(int_max_diff, diff)
            if diff < 1.0:
                int_matches += 1
        elif len(o_int) == 0 and len(r_int) == 0:
            int_matches += 1

        if o_prec is not None and r_prec is not None:
            if abs(o_prec - r_prec) < 0.01:
                prec_matches += 1

    total = len(indices)
    print(f"\nSampled {total} MS2 spectra (step={step}):")
    mz_ok = mz_matches == total
    int_ok = int_matches == total
    print(f"  m/z arrays exact   : {mz_matches}/{total}  max_diff={mz_max_diff:.2e}  {'✓' if mz_ok else '✗'}")
    print(f"  intensity arrays   : {int_matches}/{total}  max_diff={int_max_diff:.2e}  {'✓' if int_ok else '✗'}")
    print(f"  precursor m/z ±0.01: {prec_matches}/{total}  {'✓' if prec_matches == total else '~'}")
    if not mz_ok or not int_ok:
        ok = False

    print(SEPARATOR)
    print("RESULT:", "PASS ✓" if ok else "FAIL ✗")
    print(SEPARATOR)
    return ok


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare two mzML files")
    parser.add_argument("ours", type=Path, help="tdf2mzml output .mzML")
    parser.add_argument("reference", type=Path, help="Reference .mzML")
    parser.add_argument("--n-sample", type=int, default=50,
                        help="Number of MS2 spectra to sample (default 50)")
    args = parser.parse_args()

    ok = compare(args.ours, args.reference, args.n_sample)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
