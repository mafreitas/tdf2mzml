"""Test conversions against the incoming_updates_data sample files.

Run with:
    python scripts/test_incoming.py

For each ``.d`` directory found under ``incoming_updates_data/`` the script:
  - Detects whether the dataset is TDF (timsTOF with TIMS) or TSF (timsTOF
    fleX / TIMS-off).
  - For TDF: attempts a real conversion, validates the output mzML, and
    prints key statistics.
  - For TSF: prints a clear NOT-SUPPORTED notice so we know what is still
    needed.

Exit code is 0 if every supported format converted successfully, 1 otherwise.
"""

from __future__ import annotations

import cProfile
import io
import logging
import pstats
import sqlite3
import sys
import time
import traceback
import xml.etree.ElementTree as ET
from pathlib import Path

# ---------------------------------------------------------------------------
# Locate root / venv-installed package
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from tdf2mzml.cli import run_conversion  # noqa: E402
from tdf2mzml.models.config import ConversionConfig  # noqa: E402

INCOMING = REPO_ROOT / "incoming_updates_data"
NS = {"m": "http://psi.hupo.org/ms/mzml"}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _schema_type(d_path: Path) -> str | None:
    """Return the SchemaType string from GlobalMetadata, or None on error."""
    for name in ("analysis.tdf", "analysis.tsf"):
        db = d_path / name
        if db.exists():
            try:
                conn = sqlite3.connect(str(db))
                row = conn.execute(
                    "SELECT Value FROM GlobalMetadata WHERE Key='SchemaType'"
                ).fetchone()
                conn.close()
                return str(row[0]) if row else None
            except Exception:
                return None
    return None


def _validate_mzml(path: Path) -> dict[str, object]:
    """Parse an mzML file and return summary stats, raises on invalid XML."""
    tree = ET.parse(path)
    root = tree.getroot()

    assert "indexedmzML" in root.tag, "Root is not <indexedmzML>"

    spec_list = root.find(".//m:spectrumList", NS)
    assert spec_list is not None, "<spectrumList> not found"
    count = int(spec_list.attrib["count"])
    spectra = spec_list.findall("m:spectrum", NS)
    assert len(spectra) == count, f"count attr {count} != actual spectra {len(spectra)}"

    index = root.find(".//m:index", NS)
    assert index is not None, "<index> not found"

    checksum = root.find(".//m:fileChecksum", NS)
    assert checksum is not None, "<fileChecksum> not found"
    assert len(checksum.text or "") == 40, "fileChecksum is not 40-char SHA-1"

    # Ion mobility scan window check
    im_windows = root.findall(
        ".//m:scanWindow/m:cvParam[@accession='MS:1002476']", NS
    )

    sample = root.find(".//m:sample", NS)
    run = root.find(".//m:run", NS)

    return {
        "spectra": count,
        "file_size_kb": path.stat().st_size // 1024,
        "has_index": True,
        "has_checksum": True,
        "has_im_window": len(im_windows) > 0,
        "sample_name": sample.attrib.get("name", "") if sample is not None else "",
        "run_id": run.attrib.get("id", "") if run is not None else "",
    }


def _find_d_dirs(base: Path) -> list[Path]:
    """Return all top-level .d directories under base."""
    return sorted(p for p in base.iterdir() if p.is_dir() and p.suffix == ".d")


# ---------------------------------------------------------------------------
# Per-sample runner
# ---------------------------------------------------------------------------

SEPARATOR = "─" * 60


END_FRAME = 10000  # frames per test run


def run_sample(
    d_path: Path,
    out_dir: Path,
    ms1_type: str = "centroid",
    profile: bool = False,
) -> bool:
    """Run (or skip) one sample. Returns True on pass / expected skip."""
    schema = _schema_type(d_path)
    print(f"\n{SEPARATOR}")
    print(f"Sample : {d_path.name}")
    print(f"Schema : {schema or 'UNKNOWN'}")
    print(f"Mode   : ms1_type={ms1_type!r}  profiling={'on' if profile else 'off'}")

    if schema is None:
        print("SKIP   : Could not determine schema type (no .tdf / .tsf found)")
        return True

    if schema == "TSF":
        # TSF is now supported — run the conversion the same way as TDF
        out = out_dir / f"{d_path.stem}_{ms1_type}.mzML"
        print(f"Output : {out}")

        try:
            config = ConversionConfig(
                input=d_path,
                output=out,
                ms1_type=ms1_type,  # type: ignore[arg-type]
                ion_mobility="none",  # TSF has no ion mobility
                end_frame=END_FRAME,
            )
        except Exception as exc:
            print(f"FAIL   : ConversionConfig error — {exc}")
            return False

        t0 = time.perf_counter()
        try:
            if profile:
                pr = cProfile.Profile()
                pr.enable()
                run_conversion(config)
                pr.disable()
            else:
                run_conversion(config)
        except Exception:
            print("FAIL   : Conversion raised an exception:")
            traceback.print_exc()
            return False
        elapsed = time.perf_counter() - t0

        if not out.exists() or out.stat().st_size < 500:
            print("FAIL   : Output file missing or suspiciously small")
            return False

        try:
            vstats = _validate_mzml(out)
        except Exception as exc:
            print(f"FAIL   : mzML validation error — {exc}")
            return False

        print(f"PASS   : {vstats['spectra']} spectra, {vstats['file_size_kb']} KB "
              f"in {elapsed:.2f}s")
        print(f"         run id       = {vstats['run_id']}")
        print(f"         sample name  = {vstats['sample_name']}")
        print(f"         IM window    = {'yes (MS:1002476/7)' if vstats['has_im_window'] else 'no (TSF has no TIMS)'}")
        print(f"         index        = {'yes' if vstats['has_index'] else 'NO'}")
        print(f"         SHA-1 chksum = {'yes' if vstats['has_checksum'] else 'NO'}")

        if profile:
            buf = io.StringIO()
            ps = pstats.Stats(pr, stream=buf).sort_stats("cumulative")
            ps.print_stats(20)
            print("\n--- cProfile top-20 (cumulative) ---")
            print(buf.getvalue())

        return True

    if schema != "TDF":
        print(f"SKIP   : Unknown schema type '{schema}'")
        return True

    # ---- TDF conversion ----
    out = out_dir / f"{d_path.stem}_{ms1_type}.mzML"
    print(f"Output : {out}")

    try:
        config = ConversionConfig(
            input=d_path,
            output=out,
            ms1_type=ms1_type,  # type: ignore[arg-type]
            ion_mobility="mean",
            end_frame=END_FRAME,
        )
    except Exception as exc:
        print(f"FAIL   : ConversionConfig error — {exc}")
        return False

    t0 = time.perf_counter()
    try:
        if profile:
            pr = cProfile.Profile()
            pr.enable()
            run_conversion(config)
            pr.disable()
        else:
            run_conversion(config)
    except Exception:
        print("FAIL   : Conversion raised an exception:")
        traceback.print_exc()
        return False
    elapsed = time.perf_counter() - t0

    if not out.exists() or out.stat().st_size < 500:
        print("FAIL   : Output file missing or suspiciously small")
        return False

    try:
        vstats = _validate_mzml(out)
    except Exception as exc:
        print(f"FAIL   : mzML validation error — {exc}")
        return False

    print(f"PASS   : {vstats['spectra']} spectra, {vstats['file_size_kb']} KB "
          f"in {elapsed:.2f}s")
    print(f"         run id       = {vstats['run_id']}")
    print(f"         sample name  = {vstats['sample_name']}")
    print(f"         IM window    = {'yes (MS:1002476/7)' if vstats['has_im_window'] else 'no'}")
    print(f"         index        = {'yes' if vstats['has_index'] else 'NO'}")
    print(f"         SHA-1 chksum = {'yes' if vstats['has_checksum'] else 'NO'}")

    if profile:
        buf = io.StringIO()
        ps = pstats.Stats(pr, stream=buf).sort_stats("cumulative")
        ps.print_stats(20)
        print("\n--- cProfile top-20 (cumulative) ---")
        print(buf.getvalue())

    return True


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    """Discover and run all incoming sample conversions, print a summary."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    if not INCOMING.exists():
        print(f"ERROR: {INCOMING} does not exist")
        sys.exit(1)

    samples = _find_d_dirs(INCOMING)
    if not samples:
        print(f"No .d directories found under {INCOMING}")
        sys.exit(1)

    print(f"Found {len(samples)} sample(s) in {INCOMING}")

    out_dir = REPO_ROOT / "test_output"
    out_dir.mkdir(exist_ok=True)

    results: list[tuple[str, bool]] = []
    for d in samples:
        ok = run_sample(d, out_dir, ms1_type="centroid", profile=True)
        results.append((d.name, ok))

    print(f"\n{SEPARATOR}")
    print("Summary")
    print(SEPARATOR)
    all_pass = True
    for name, ok in results:
        status = "PASS/SKIP" if ok else "FAIL"
        print(f"  {status:<10} {name}")
        if not ok:
            all_pass = False

    sys.exit(0 if all_pass else 1)


if __name__ == "__main__":
    main()
