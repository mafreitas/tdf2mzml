#!/usr/bin/env python3
"""
Compare two mzML files to validate tdf2mzml converter output against timsconvert reference.

Files:
  Reference (timsconvert): /workspace/incoming_updates_data/20190122_HeLa_QC_Slot1-47_1_3219.mzML
  Ours (tdf2mzml):         /workspace/test_output/HeLa_QC_full.mzML

Key structural differences already known:
  - Reference uses zlib + 64-bit for all arrays; ours uses no-compression, mz=64-bit int=32-bit
  - Reference stores ion mobility as 3rd binary array (MS:1003006); ours as scan cvParam (MS:1002814)
  - Reference cvParams always have accession; ours sometimes use name-only cvParams
  - Reference idRef format: "scan=N" (1-based); ours: "index=N" (0-based)
"""

import sys
import re
import struct
import base64
import zlib
import xml.etree.ElementTree as ET
from pathlib import Path

REF_FILE = "/workspace/incoming_updates_data/20190122_HeLa_QC_Slot1-47_1_3219.mzML"
OUR_FILE = "/workspace/test_output/HeLa_QC_full.mzML"

NS = "http://psi.hupo.org/ms/mzml"
NS_WRAP_OPEN = f'<root xmlns="{NS}">'
NS_WRAP_CLOSE = "</root>"

SAMPLE_INDICES = [0, 1000, 5000, 10000, 50000, 100000, 150000, 200000, 240000, 241264]

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def T(name):
    return f"{{{NS}}}{name}"


def cv_by_acc(elem, accession):
    for c in elem.iter(T("cvParam")):
        if c.get("accession") == accession:
            return c.get("value")
    return None


def cv_by_name(elem, name_substr):
    """Find cvParam by (partial) name match, return value."""
    for c in elem.iter(T("cvParam")):
        if name_substr.lower() in (c.get("name") or "").lower():
            return c.get("value")
    return None


def find_cv_acc(elem, accession):
    for c in elem.iter(T("cvParam")):
        if c.get("accession") == accession:
            return c
    return None


def find_cv_name(elem, name_substr):
    for c in elem.iter(T("cvParam")):
        if name_substr.lower() in (c.get("name") or "").lower():
            return c
    return None


def decode_array(bda_elem):
    """
    Decode a <binaryDataArray> element.
    Handles: zlib / no-compression, 32-bit / 64-bit float.
    """
    binary_elem = bda_elem.find(T("binary"))
    if binary_elem is None or not binary_elem.text:
        return []
    raw = base64.b64decode(binary_elem.text.strip())

    # Compression
    if find_cv_acc(bda_elem, "MS:1000574") is not None:  # zlib
        raw = zlib.decompress(raw)
    # else no compression (MS:1000576) or absent

    # Precision
    if find_cv_acc(bda_elem, "MS:1000523") is not None or find_cv_name(bda_elem, "64-bit float") is not None:
        fmt, item_size = "d", 8
    else:
        fmt, item_size = "f", 4

    n = len(raw) // item_size
    if n == 0:
        return []
    return list(struct.unpack(f"<{n}{fmt}", raw))


def read_head(filepath, nbytes=300000):
    with open(filepath, "rb") as f:
        return f.read(nbytes).decode("utf-8", errors="replace")


def get_spectrum_count(filepath):
    head = read_head(filepath, 600000)
    m = re.search(r'<spectrumList\s+count="(\d+)"', head)
    return int(m.group(1)) if m else None


# ─────────────────────────────────────────────────────────────────────────────
# Metadata extraction
# ─────────────────────────────────────────────────────────────────────────────

def extract_metadata(filepath):
    head = read_head(filepath, 300000)
    meta = {}

    # Instrument serial MS:1000529
    m = re.search(r'accession="MS:1000529"\s+[^>]*value="([^"]*)"', head)
    if not m:
        m = re.search(r'value="([^"]*)"\s+[^>]*accession="MS:1000529"', head)
    meta["instrument_serial"] = m.group(1) if m else "N/A"

    # Instrument model – timsconvert uses MS:1002877 (timsTOF Pro) or similar
    meta["instrument_model"] = "N/A"
    for acc in ["MS:1002877", "MS:1003005", "MS:1003109"]:
        m2 = re.search(rf'accession="{acc}"[^>]*name="([^"]*)"', head)
        if m2:
            meta["instrument_model"] = m2.group(1)
            break
    if meta["instrument_model"] == "N/A":
        for pattern in [r'name="(timsTOF[^"]*)"', r'name="(Bruker[^"]*format[^"]*)"']:
            m2 = re.search(pattern, head, re.IGNORECASE)
            if m2:
                meta["instrument_model"] = m2.group(1)
                break
    # Fallback: look for any instrument-related cvParam in instrumentConfiguration block
    if meta["instrument_model"] == "N/A":
        ic_start = head.find("<instrumentConfiguration")
        if ic_start != -1:
            ic = head[ic_start:ic_start + 2000]
            m2 = re.search(r'name="([^"]+)"', ic)
            if m2:
                meta["instrument_model"] = m2.group(1)

    # Sample name MS:1000002
    m = re.search(r'accession="MS:1000002"\s+[^>]*value="([^"]*)"', head)
    meta["sample_name"] = m.group(1) if m else "N/A"

    # Acquisition date
    m = re.search(r'startTimeStamp="([^"]*)"', head)
    if not m:
        m = re.search(r'accession="MS:1000747"\s+[^>]*value="([^"]*)"', head)
    meta["acquisition_date"] = m.group(1) if m else "N/A"

    # Software versions
    software_versions = []
    for m in re.finditer(r'<software\s+id="([^"]*)"[^>]*version="([^"]*)"', head):
        software_versions.append(f"{m.group(1)} v{m.group(2)}")
    meta["software_versions"] = software_versions

    # Scan window m/z (MS:1000501 lower, MS:1000500 upper)
    m_low = re.search(r'accession="MS:1000501"\s+[^>]*value="([^"]*)"', head)
    m_high = re.search(r'accession="MS:1000500"\s+[^>]*value="([^"]*)"', head)
    if not m_low:
        m_low = re.search(r'name="scan window lower limit"\s+value="([^"]*)"', head)
    if not m_high:
        m_high = re.search(r'name="scan window upper limit"\s+value="([^"]*)"', head)
    meta["scan_window_low"] = m_low.group(1) if m_low else "N/A"
    meta["scan_window_high"] = m_high.group(1) if m_high else "N/A"

    # Ion mobility scan window (MS:1002476 lower, MS:1002477 upper)
    m_im_low = re.search(r'accession="MS:1002476"\s+[^>]*value="([^"]*)"', head)
    m_im_high = re.search(r'accession="MS:1002477"\s+[^>]*value="([^"]*)"', head)
    if not m_im_low:
        m_im_low = re.search(r'name="inverse reduced ion mobility lower limit"\s+value="([^"]*)"', head)
    if not m_im_high:
        m_im_high = re.search(r'name="inverse reduced ion mobility upper limit"\s+value="([^"]*)"', head)
    meta["im_window_low"] = m_im_low.group(1) if m_im_low else "N/A"
    meta["im_window_high"] = m_im_high.group(1) if m_im_high else "N/A"

    return meta


# ─────────────────────────────────────────────────────────────────────────────
# Index parsing
# ─────────────────────────────────────────────────────────────────────────────

def get_index_list_offset(filepath):
    with open(filepath, "rb") as f:
        f.seek(0, 2)
        size = f.tell()
        f.seek(max(0, size - 500))
        tail = f.read().decode("utf-8", errors="replace")
    m = re.search(r"<indexListOffset>(\d+)</indexListOffset>", tail)
    return int(m.group(1)) if m else None


def parse_index(filepath):
    """Returns ordered list of (idRef, byte_offset) tuples."""
    idx_start = get_index_list_offset(filepath)
    if idx_start is None:
        print(f"  WARNING: indexListOffset not found in {filepath}")
        return []
    with open(filepath, "rb") as f:
        f.seek(0, 2)
        file_size = f.tell()
        f.seek(idx_start)
        read_size = min(file_size - idx_start, 25 * 1024 * 1024)
        idx_text = f.read(read_size).decode("utf-8", errors="replace")

    offsets = []
    for m in re.finditer(r'<offset\s+idRef="([^"]*)"\s*>(\d+)</offset>', idx_text):
        offsets.append((m.group(1), int(m.group(2))))
    return offsets


def get_offset_by_index(offsets, n):
    if n >= len(offsets):
        return None, None
    return offsets[n]


# ─────────────────────────────────────────────────────────────────────────────
# Spectrum extraction and parsing
# ─────────────────────────────────────────────────────────────────────────────

def read_spectrum_at_offset(filepath, offset, initial_read=512 * 1024):
    """
    Seek to offset, find <spectrum ...> ... </spectrum>, parse with namespace wrapper.
    Grows read size if </spectrum> not found in initial read.
    """
    for read_size in [initial_read, 2 * 1024 * 1024, 8 * 1024 * 1024]:
        with open(filepath, "rb") as f:
            f.seek(offset)
            chunk = f.read(read_size)
        text = chunk.decode("utf-8", errors="replace")
        start = text.find("<spectrum ")
        if start == -1:
            return None
        end = text.find("</spectrum>", start)
        if end != -1:
            spec_text = text[start:end + len("</spectrum>")]
            wrapped = NS_WRAP_OPEN + spec_text + NS_WRAP_CLOSE
            try:
                root = ET.fromstring(wrapped)
                return root.find(T("spectrum"))
            except ET.ParseError as e:
                print(f"    XML parse error at offset {offset}: {e}")
                return None
    print(f"    Could not find </spectrum> in {read_size // 1024}KB read at offset {offset}")
    return None


def parse_spectrum(elem):
    if elem is None:
        return None

    info = {}
    info["index"] = elem.get("index")
    info["id"] = elem.get("id")
    info["defaultArrayLength"] = int(elem.get("defaultArrayLength", 0))

    # MS level (accession or name fallback)
    ms_lv = cv_by_acc(elem, "MS:1000511")
    if ms_lv is None:
        ms_lv = cv_by_name(elem, "ms level")
    info["ms_level"] = ms_lv

    # Scan start time
    scan_list = elem.find(T("scanList"))
    info["scan_start_time"] = None
    info["ion_mobility_scan"] = None

    if scan_list is not None:
        scan = scan_list.find(T("scan"))
        if scan is not None:
            st = cv_by_acc(scan, "MS:1000016")
            if st is None:
                st = cv_by_name(scan, "scan start time")
            info["scan_start_time"] = st

            # Ion mobility from scan: MS:1002815 or MS:1002814 (mean inverse reduced IM)
            im = cv_by_acc(scan, "MS:1002815")
            if im is None:
                im = cv_by_acc(scan, "MS:1002814")
            if im is None:
                im = cv_by_name(scan, "mean inverse reduced ion mobility")
            info["ion_mobility_scan"] = im

    # Precursor
    info.update({
        "precursor_mz": None, "precursor_charge": None,
        "isolation_window_lower": None, "isolation_window_upper": None,
        "collision_energy": None,
    })
    prec_list = elem.find(T("precursorList"))
    if prec_list is not None:
        prec = prec_list.find(T("precursor"))
        if prec is not None:
            sil = prec.find(T("selectedIonList"))
            if sil is not None:
                si = sil.find(T("selectedIon"))
                if si is not None:
                    pmz = cv_by_acc(si, "MS:1000744")
                    if pmz is None:
                        pmz = cv_by_name(si, "selected ion m/z")
                    info["precursor_mz"] = pmz
                    pch = cv_by_acc(si, "MS:1000041")
                    if pch is None:
                        pch = cv_by_name(si, "charge state")
                    info["precursor_charge"] = pch
            iso = prec.find(T("isolationWindow"))
            if iso is not None:
                iwl = cv_by_acc(iso, "MS:1000828")
                if iwl is None:
                    iwl = cv_by_name(iso, "isolation window lower offset")
                info["isolation_window_lower"] = iwl
                iwu = cv_by_acc(iso, "MS:1000829")
                if iwu is None:
                    iwu = cv_by_name(iso, "isolation window upper offset")
                info["isolation_window_upper"] = iwu
            act = prec.find(T("activation"))
            if act is not None:
                ce = cv_by_acc(act, "MS:1000045")
                if ce is None:
                    ce = cv_by_name(act, "collision energy")
                info["collision_energy"] = ce

    # Binary arrays
    mz_arr = []
    int_arr = []
    im_arr = []

    bda_list = elem.find(T("binaryDataArrayList"))
    if bda_list is not None:
        for bda in bda_list.findall(T("binaryDataArray")):
            is_mz = (find_cv_acc(bda, "MS:1000514") is not None or
                     find_cv_name(bda, "m/z array") is not None)
            is_int = (find_cv_acc(bda, "MS:1000515") is not None or
                      find_cv_name(bda, "intensity array") is not None)
            is_im = any(find_cv_acc(bda, acc) is not None for acc in
                        ["MS:1002476", "MS:1002815", "MS:1003006", "MS:1002477"]) or \
                    find_cv_name(bda, "ion mobility") is not None

            data = decode_array(bda)
            if is_mz:
                mz_arr = data
            elif is_int:
                int_arr = data
            elif is_im:
                im_arr = data

    info["mz_len"] = len(mz_arr)
    info["int_len"] = len(int_arr)
    info["im_len"] = len(im_arr)
    info["has_im_array"] = len(im_arr) > 0

    info["mz_first5"] = [round(x, 5) for x in mz_arr[:5]]
    info["mz_last5"] = [round(x, 5) for x in mz_arr[-5:]]
    info["int_first5"] = [round(x, 1) for x in int_arr[:5]]
    info["int_last5"] = [round(x, 1) for x in int_arr[-5:]]

    if im_arr:
        info["im_first5"] = [round(x, 5) for x in im_arr[:5]]
        info["im_last5"] = [round(x, 5) for x in im_arr[-5:]]
    else:
        info["im_first5"] = []
        info["im_last5"] = []

    return info


# ─────────────────────────────────────────────────────────────────────────────
# MS level ratio (first N spectra)
# ─────────────────────────────────────────────────────────────────────────────

def get_ms_ratio(filepath, n_spectra=50):
    ms_counts = {}
    count = 0
    with open(filepath, "rb") as f:
        buffer = b""
        for chunk in iter(lambda: f.read(512 * 1024), b""):
            buffer += chunk
            while True:
                start = buffer.find(b"<spectrum ")
                if start == -1:
                    buffer = buffer[-500:]
                    break
                end = buffer.find(b"</spectrum>", start)
                if end == -1:
                    break
                spec_bytes = buffer[start:end + len(b"</spectrum>")]
                buffer = buffer[end + len(b"</spectrum>"):]
                try:
                    wrapped = NS_WRAP_OPEN.encode() + spec_bytes + NS_WRAP_CLOSE.encode()
                    root = ET.fromstring(wrapped.decode("utf-8", errors="replace"))
                    spec = root.find(T("spectrum"))
                    if spec is None:
                        continue
                    ms_lv = cv_by_acc(spec, "MS:1000511")
                    if ms_lv is None:
                        ms_lv = cv_by_name(spec, "ms level")
                    ms_counts[ms_lv] = ms_counts.get(ms_lv, 0) + 1
                    count += 1
                    if count >= n_spectra:
                        break
                except ET.ParseError:
                    pass
            if count >= n_spectra:
                break
    return ms_counts


# ─────────────────────────────────────────────────────────────────────────────
# Display helpers
# ─────────────────────────────────────────────────────────────────────────────

W_LABEL = 38
W_REF = 44


def print_section(title):
    print(f"\n{'='*95}")
    print(f"  {title}")
    print(f"{'='*95}")


def print_header():
    print(f"\n  {'Field':<{W_LABEL}} | {'Reference (timsconvert)':<{W_REF}} | Our (tdf2mzml)  [match]")
    print(f"  {'-'*W_LABEL}-+-{'-'*W_REF}-+-{'-'*42}")


def fmt_val(v, width):
    s = "None" if v is None else str(v)
    return s[:width].ljust(width)


def print_row(label, ref_val, our_val, match_sym=None):
    if match_sym is None:
        match_sym = "✓" if str(ref_val) == str(our_val) else "✗"
    label_s = str(label)[:W_LABEL].ljust(W_LABEL)
    ref_s = fmt_val(ref_val, W_REF)
    our_s = fmt_val(our_val, 42)
    print(f"  {label_s} | {ref_s} | {our_s}  [{match_sym}]")


def values_close(a, b, tol=0.001):
    try:
        return abs(float(a) - float(b)) <= tol * max(1, abs(float(a)))
    except (TypeError, ValueError):
        return str(a) == str(b)


def arrays_close(a_list, b_list, tol=0.001):
    if len(a_list) != len(b_list):
        return False
    return all(values_close(a, b, tol) for a, b in zip(a_list, b_list))


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main():
    print("=" * 95)
    print("  mzML COMPARISON: tdf2mzml vs timsconvert reference")
    print("=" * 95)
    print(f"  Reference : {REF_FILE}")
    print(f"  Ours      : {OUR_FILE}")
    ref_size = Path(REF_FILE).stat().st_size / (1024**3)
    our_size = Path(OUR_FILE).stat().st_size / (1024**3)
    print(f"  File sizes: Reference={ref_size:.2f} GB, Ours={our_size:.2f} GB")

    differences = []

    # ── 1. Spectrum count ──────────────────────────────────────────────────
    print_section("1. Spectrum Count")
    ref_count = get_spectrum_count(REF_FILE)
    our_count = get_spectrum_count(OUR_FILE)
    print_header()
    print_row("spectrumList count", ref_count, our_count)
    if ref_count != our_count:
        differences.append(f"Spectrum count: ref={ref_count}, ours={our_count}")

    # ── 2. Metadata ────────────────────────────────────────────────────────
    print_section("2. Metadata Comparison")
    sys.stdout.flush()
    ref_meta = extract_metadata(REF_FILE)
    our_meta = extract_metadata(OUR_FILE)

    print_header()
    meta_fields = [
        ("instrument_model",  "Instrument model"),
        ("instrument_serial", "Instrument serial"),
        ("sample_name",       "Sample name"),
        ("acquisition_date",  "Acquisition date/time"),
        ("scan_window_low",   "Scan window low m/z"),
        ("scan_window_high",  "Scan window high m/z"),
        ("im_window_low",     "IM window low (1/K0)"),
        ("im_window_high",    "IM window high (1/K0)"),
    ]
    for key, label in meta_fields:
        rv = ref_meta.get(key, "N/A")
        ov = our_meta.get(key, "N/A")
        print_row(label, rv, ov)
        if str(rv) != str(ov):
            differences.append(f"Metadata '{label}': ref='{rv}', ours='{ov}'")

    print(f"\n  Software versions:")
    print(f"    Reference : {', '.join(ref_meta.get('software_versions', [])) or 'N/A'}")
    print(f"    Ours      : {', '.join(our_meta.get('software_versions', [])) or 'N/A'}")

    # ── 3. Index ───────────────────────────────────────────────────────────
    print_section("3. Index Offsets")
    sys.stdout.flush()
    ref_idx_off = get_index_list_offset(REF_FILE)
    our_idx_off = get_index_list_offset(OUR_FILE)
    print(f"  Reference indexListOffset : {ref_idx_off:,}")
    print(f"  Ours      indexListOffset : {our_idx_off:,}")

    print("  Parsing reference index...")
    sys.stdout.flush()
    ref_offsets = parse_index(REF_FILE)
    print(f"  Reference: {len(ref_offsets):,} offset entries")

    print("  Parsing our index...")
    sys.stdout.flush()
    our_offsets = parse_index(OUR_FILE)
    print(f"  Ours:      {len(our_offsets):,} offset entries")

    if len(ref_offsets) != len(our_offsets):
        differences.append(f"Index entry count: ref={len(ref_offsets)}, ours={len(our_offsets)}")

    if ref_offsets:
        print(f"\n  Reference idRef format: '{ref_offsets[0][0]}' (1-based scan=N)")
    if our_offsets:
        print(f"  Ours      idRef format: '{our_offsets[0][0]}' (0-based index=N)")

    # ── 4. Spectrum comparison ─────────────────────────────────────────────
    print_section("4. Spectrum-Level Comparison (Sampled Spectra)")
    sys.stdout.flush()

    for idx in SAMPLE_INDICES:
        ref_key, ref_offset = get_offset_by_index(ref_offsets, idx)
        our_key, our_offset = get_offset_by_index(our_offsets, idx)

        if ref_offset is None and our_offset is None:
            print(f"\n  [Index {idx}] Both out of range — skipping")
            continue
        if ref_offset is None:
            print(f"\n  [Index {idx}] Reference: out of range")
            continue
        if our_offset is None:
            print(f"\n  [Index {idx}] Ours: out of range")
            continue

        print(f"\n  ── Spectrum index {idx} {'─'*50}")
        print(f"    Ref  idRef='{ref_key}'  offset={ref_offset:,}")
        print(f"    Ours idRef='{our_key}'  offset={our_offset:,}")
        sys.stdout.flush()

        ref_elem = read_spectrum_at_offset(REF_FILE, ref_offset)
        our_elem = read_spectrum_at_offset(OUR_FILE, our_offset)
        ref_s = parse_spectrum(ref_elem)
        our_s = parse_spectrum(our_elem)

        if ref_s is None:
            print("    ERROR: Could not parse reference spectrum")
            continue
        if our_s is None:
            print("    ERROR: Could not parse our spectrum")
            continue

        print_header()

        def diff_note(field, label, tol=None):
            rv = ref_s.get(field)
            ov = our_s.get(field)
            if tol is not None:
                close = values_close(rv, ov, tol)
                sym = "✓" if close else "✗"
            else:
                sym = "✓" if str(rv) == str(ov) else "✗"
            print_row(label, rv, ov, sym)
            if sym == "✗":
                if tol is None or not values_close(rv, ov, tol):
                    differences.append(f"Index {idx} | {label}: ref={rv}, ours={ov}")

        diff_note("ms_level",         "MS level")
        diff_note("scan_start_time",  "Scan start time (min)", tol=0.0001)
        diff_note("defaultArrayLength", "Peak count (attr)")
        diff_note("mz_len",           "m/z array length")
        diff_note("int_len",          "Intensity array length")
        diff_note("has_im_array",     "Has IM binary array")
        diff_note("im_len",           "IM array length")
        diff_note("ion_mobility_scan","Ion mobility (scan cvParam)")

        for arr_field, arr_label, tol in [
            ("mz_first5",  "m/z first 5 peaks",       0.0001),
            ("mz_last5",   "m/z last 5 peaks",        0.0001),
            ("int_first5", "Intensity first 5 peaks", 0.05),
            ("int_last5",  "Intensity last 5 peaks",  0.05),
        ]:
            rv = ref_s.get(arr_field, [])
            ov = our_s.get(arr_field, [])
            close = arrays_close(rv, ov, tol)
            sym = "✓" if close else "✗"
            print_row(arr_label, rv, ov, sym)
            if not close:
                differences.append(f"Index {idx} | {arr_label}: ref={str(rv)[:60]}, ours={str(ov)[:60]}")

        if ref_s.get("has_im_array") or our_s.get("has_im_array"):
            for arr_field, arr_label in [("im_first5", "IM first 5"), ("im_last5", "IM last 5")]:
                rv = ref_s.get(arr_field, [])
                ov = our_s.get(arr_field, [])
                close = arrays_close(rv, ov, 0.0001)
                sym = "✓" if close else "✗"
                print_row(arr_label, rv, ov, sym)
                if not close:
                    differences.append(f"Index {idx} | {arr_label}: ref={str(rv)[:60]}, ours={str(ov)[:60]}")

        # MS2 fields
        if ref_s.get("ms_level") == "2" or our_s.get("ms_level") == "2":
            print(f"\n    [MS2 precursor fields]")
            print_header()
            ms2_fields = [
                ("precursor_mz",          "Precursor m/z",           0.01),
                ("precursor_charge",      "Precursor charge",        None),
                ("isolation_window_lower","Isolation window lower",   0.01),
                ("isolation_window_upper","Isolation window upper",   0.01),
                ("collision_energy",      "Collision energy",         0.01),
            ]
            for field, label, tol in ms2_fields:
                rv = ref_s.get(field)
                ov = our_s.get(field)
                if tol is not None:
                    close = values_close(rv, ov, tol)
                    sym = "✓" if close else "✗"
                else:
                    sym = "✓" if str(rv) == str(ov) else "✗"
                print_row(label, rv, ov, sym)
                if sym == "✗":
                    differences.append(f"Index {idx} | {label}: ref={rv}, ours={ov}")

    # ── 5. MS1/MS2 ratio ──────────────────────────────────────────────────
    print_section("5. MS Level Ratio (first 50 spectra)")
    sys.stdout.flush()
    print("  Streaming first 50 spectra from each file...")
    ref_ms = get_ms_ratio(REF_FILE, 50)
    our_ms = get_ms_ratio(OUR_FILE, 50)

    print_header()
    all_levels = sorted(set(list(ref_ms.keys()) + list(our_ms.keys())))
    for lvl in all_levels:
        rv = ref_ms.get(lvl, 0)
        ov = our_ms.get(lvl, 0)
        print_row(f"MS{lvl} count (first 50)", rv, ov)
        if rv != ov:
            differences.append(f"MS{lvl} in first 50 spectra: ref={rv}, ours={ov}")

    ref_ms1 = ref_ms.get("1", 0)
    ref_ms2 = ref_ms.get("2", 0)
    our_ms1 = our_ms.get("1", 0)
    our_ms2 = our_ms.get("2", 0)
    ref_ratio = f"{ref_ms2/ref_ms1:.1f}:1" if ref_ms1 > 0 else "N/A (no MS1)"
    our_ratio = f"{our_ms2/our_ms1:.1f}:1" if our_ms1 > 0 else "N/A (no MS1)"
    print_row("MS2:MS1 ratio", ref_ratio, our_ratio)

    # ── 6. Structural format differences (known) ───────────────────────────
    print_section("6. Known Structural Format Differences (not data errors)")
    format_diffs = [
        ("Binary encoding",      "zlib + 64-bit all arrays",       "No compression; mz=64-bit, int=32-bit"),
        ("Ion mobility storage", "3rd binary array (MS:1003006)",   "Scan cvParam (MS:1002814)"),
        ("Spectrum ID format",   "scan=N (1-based)",                "index=N (0-based)"),
        ("cvParam accessions",   "All have accessions",             "Some use name-only (no accession)"),
        ("Software listed",      "timsconvert v2.0.0, python-psims","tdf2mzml v0.5.0"),
    ]
    W = 30
    print(f"\n  {'Aspect':<{W}} | {'Reference':<45} | Ours")
    print(f"  {'-'*W}-+-{'-'*45}-+-{'-'*40}")
    for aspect, ref_val, our_val in format_diffs:
        print(f"  {aspect:<{W}} | {ref_val:<45} | {our_val}")

    # ── 7. Differences summary ────────────────────────────────────────────
    print_section("7. Data Differences Summary")
    # Filter out known-acceptable differences
    data_differences = [d for d in differences if
                        "Instrument model" not in d and
                        "Instrument serial" not in d and
                        "IM window" not in d]
    metadata_differences = [d for d in differences if
                             "Instrument model" in d or
                             "Instrument serial" in d or
                             "IM window" in d]

    if metadata_differences:
        print(f"\n  Metadata-level differences ({len(metadata_differences)}):")
        for d in metadata_differences:
            print(f"    • {d}")

    if not data_differences:
        print("\n  No data differences in sampled spectra. Spectrum content matches (within tolerance).")
    else:
        print(f"\n  Data differences in sampled spectra ({len(data_differences)}):")
        for i, d in enumerate(data_differences, 1):
            print(f"    {i:3d}. {d}")

    print(f"\n{'='*95}")
    print("  Comparison complete.")
    print(f"{'='*95}\n")


if __name__ == "__main__":
    main()
