"""Command-line interface for tdf2mzml.

Entry point: ``tdf2mzml -i input.d -o output.mzML``
"""

from __future__ import annotations

import argparse
import logging
import re
from pathlib import Path

import numpy as np

from tdf2mzml import __version__
from tdf2mzml.constants import (
    DEFAULT_COMPRESSION,
    DEFAULT_END_FRAME,
    DEFAULT_ION_MOBILITY_MODE,
    DEFAULT_MS1_THRESHOLD,
    DEFAULT_MS1_TYPE,
    DEFAULT_MS2_NLARGEST,
    DEFAULT_MS2_THRESHOLD,
    DEFAULT_PRECISION,
    DEFAULT_START_FRAME,
    MSMS_TYPE_MS1,
    MSMS_TYPE_PASEF_DDA,
    MSMS_TYPE_PASEF_DIA,
)
from tdf2mzml.io.baf_reader import BafReader, BAF_POLARITY_POSITIVE, BAF_MS_LEVEL_MS1
from tdf2mzml.io.reader import TdfReader
from tdf2mzml.io.tsf_reader import TsfReader, TSF_MSMS_TYPE_MS1, TSF_MSMS_TYPE_AUTO_MSMS
from tdf2mzml.models.config import ConversionConfig
from tdf2mzml.models.spectrum import PrecursorInfo, SpectrumArrays
from tdf2mzml.output.writer import IndexedMzMLWriter
from tdf2mzml.processing.mobility import mean_ook0_for_frame
from tdf2mzml.processing.ms1 import get_im_resolved_ms1, get_ms1_spectrum
from tdf2mzml.processing.ms2 import get_pasef_dda_ms2, get_pasef_dia_ms2
from tdf2mzml.utils import ProgressLogger, timing

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    """Build and return the CLI argument parser.

    Returns
    -------
    argparse.ArgumentParser
    """
    parser = argparse.ArgumentParser(
        prog="tdf2mzml",
        description=f"Convert Bruker TimsTOF TDF files to indexed mzML  (v{__version__})",
    )
    parser.add_argument(
        "-i", "--input",
        required=True,
        metavar="INPUT_DIR",
        help="Path to the Bruker .d directory",
    )
    parser.add_argument(
        "-o", "--output",
        required=False,
        default=None,
        metavar="OUTPUT_FILE",
        help="Output .mzML path (default: same location and base name as input, with .mzML extension)",
    )
    parser.add_argument(
        "--ms1_type",
        choices=["centroid", "profile", "raw"],
        default=DEFAULT_MS1_TYPE,
        metavar="TYPE",
        help=f"MS1 spectrum type (default: {DEFAULT_MS1_TYPE})",
    )
    parser.add_argument(
        "--ms1_threshold",
        type=float,
        default=DEFAULT_MS1_THRESHOLD,
        metavar="VALUE",
        help=f"Min intensity for raw MS1 (default: {DEFAULT_MS1_THRESHOLD})",
    )
    parser.add_argument(
        "--ms2_threshold",
        type=float,
        default=DEFAULT_MS2_THRESHOLD,
        metavar="VALUE",
        help=f"Min intensity for MS2 (default: {DEFAULT_MS2_THRESHOLD})",
    )
    parser.add_argument(
        "--ms2_nlargest",
        type=int,
        default=DEFAULT_MS2_NLARGEST,
        metavar="N",
        help="Keep N largest MS2 peaks; -1 = all",
    )
    parser.add_argument(
        "-s", "--start_frame",
        type=int,
        default=DEFAULT_START_FRAME,
        metavar="N",
        help="First frame to convert (-1 = first available)",
    )
    parser.add_argument(
        "-e", "--end_frame",
        type=int,
        default=DEFAULT_END_FRAME,
        metavar="N",
        help="Last frame to convert (-1 = last available)",
    )
    parser.add_argument(
        "--compression",
        choices=["none", "zlib"],
        default=DEFAULT_COMPRESSION,
        metavar="TYPE",
        help=f"Binary array compression (default: {DEFAULT_COMPRESSION})",
    )
    parser.add_argument(
        "--ion_mobility",
        choices=["none", "mean", "perscan", "array"],
        default=DEFAULT_ION_MOBILITY_MODE,
        metavar="MODE",
        help=(
            "Ion mobility capture: none | mean (intensity-weighted 1/K0 scalar) | "
            "perscan (one spectrum per scan line) | "
            "array (full IM-resolved MS1: all IM bins preserved, per-peak 1/K0 array). "
            f"Default: {DEFAULT_ION_MOBILITY_MODE}"
        ),
    )
    parser.add_argument(
        "--precision",
        type=float,
        default=DEFAULT_PRECISION,
        metavar="PPM",
        help=f"m/z binning precision in ppm for raw mode (default: {DEFAULT_PRECISION})",
    )
    parser.add_argument(
        "-d", "--debug",
        action="store_true",
        default=False,
        help="Enable verbose debug logging",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    return parser


def _derive_output(input_path: str) -> str:
    """Derive the default output path from the input .d directory path.

    Parameters
    ----------
    input_path : str
        Path to the ``.d`` input directory.

    Returns
    -------
    str
        Output path with ``.d`` suffix replaced by ``.mzML``.
    """
    # Strip .baf extension for standalone BAF files
    if input_path.lower().endswith(".baf"):
        return re.sub(r"\.baf$", ".mzML", input_path, flags=re.IGNORECASE)
    return re.sub(r"\.d[/\\]?$", ".mzML", input_path.rstrip("/\\"))


def parse_args(argv: list[str] | None = None) -> ConversionConfig:
    """Parse CLI arguments into a :class:`~tdf2mzml.models.config.ConversionConfig`.

    Parameters
    ----------
    argv : list of str or None, optional
        Argument list; defaults to ``sys.argv[1:]``.

    Returns
    -------
    ConversionConfig
        Validated conversion configuration.
    """
    parser = build_parser()
    args = parser.parse_args(argv)

    output = args.output or _derive_output(args.input)

    return ConversionConfig(
        input=Path(args.input),
        output=Path(output),
        ms1_type=args.ms1_type,
        ms1_threshold=args.ms1_threshold,
        ms2_threshold=args.ms2_threshold,
        ms2_nlargest=args.ms2_nlargest,
        start_frame=args.start_frame,
        end_frame=args.end_frame,
        compression=args.compression,
        ion_mobility=args.ion_mobility,
        precision=args.precision,
        checksum_source_files=getattr(args, "checksum_source_files", False),
        debug=args.debug,
    )


# ---------------------------------------------------------------------------
# Conversion orchestration
# ---------------------------------------------------------------------------


def _count_spectra_in_range(
    reader: TdfReader,
    all_frames: list[tuple[int, ...]],
    start_frame: int,
    end_frame: int,
    meta: object,
) -> int:
    """Count spectra that will be written for the given frame range.

    Uses bulk SQL queries rather than per-frame round-trips.

    Parameters
    ----------
    reader : TdfReader
        Open TDF reader.
    all_frames : list of tuple
        All frame rows from the ``Frames`` table.
    start_frame : int
        First frame ID (inclusive).
    end_frame : int
        Last frame ID (inclusive).
    meta : AcquisitionMetadata
        Acquisition metadata.

    Returns
    -------
    int
        Total number of spectra that will be written.
    """
    from tdf2mzml.models.metadata import AcquisitionMetadata  # local to avoid cycle

    assert isinstance(meta, AcquisitionMetadata)

    ms1_count = sum(
        1
        for f in all_frames
        if start_frame <= int(f[0]) <= end_frame and int(f[4]) == MSMS_TYPE_MS1
    )

    dda_count = 0
    if meta.has_pasef_dda:
        # Single query: count precursors whose parent frame is in range
        dda_count = reader._tims.conn.execute(
            "SELECT COUNT(*) FROM Precursors WHERE Parent BETWEEN ? AND ?",
            (start_frame, end_frame),
        ).fetchone()[0]

    dia_count = 0
    if meta.has_pasef_dia:
        # For DIA we need windows per frame — batch via subquery
        dia_frame_ids = [
            int(f[0])
            for f in all_frames
            if start_frame <= int(f[0]) <= end_frame and int(f[4]) == MSMS_TYPE_PASEF_DIA
        ]
        for fid in dia_frame_ids:
            window_group = reader.get_dia_window_group(fid)
            dia_count += len(reader.get_dia_windows_for_group(window_group))

    return ms1_count + dda_count + dia_count


def _polarity_cv(polarity_char: str) -> str | None:
    """Map a TSF Frames.Polarity character to an mzML CV term name.

    Parameters
    ----------
    polarity_char : str
        Value from the ``Polarity`` column: ``'+'`` or ``'-'``.

    Returns
    -------
    str or None
        ``"positive scan"`` (CV MS:1000130) for ``'+'``,
        ``"negative scan"`` (CV MS:1000129) for ``'-'``,
        ``None`` for anything else.
    """
    if polarity_char == "+":
        return "positive scan"
    if polarity_char == "-":
        return "negative scan"
    return None


@timing
def run_tsf_conversion(config: ConversionConfig) -> None:
    """Execute a full TSF → indexed mzML conversion.

    Parameters
    ----------
    config : ConversionConfig
        Validated conversion parameters.
    """
    logger.info("tdf2mzml v%s  [TSF mode]", __version__)
    logger.info("Input:  %s", config.input)
    logger.info("Output: %s", config.output)

    with TsfReader(config.input) as reader:
        meta = reader.metadata
        logger.info(
            "%d frames | %d MS1 | %d MS2 (AutoMSMS)",
            meta.frame_count,
            meta.ms1_spectra_count,
            meta.ms2_dda_count,
        )

        all_frames = reader.get_all_frames()

        start_frame = config.start_frame if config.start_frame != -1 else 1
        end_frame = (
            config.end_frame if config.end_frame != -1 else meta.frame_count
        )

        # Count spectra that will be written
        actual_spectra = sum(
            1
            for f in all_frames
            if start_frame <= int(f[0]) <= end_frame
            and int(f[4]) in (TSF_MSMS_TYPE_MS1, TSF_MSMS_TYPE_AUTO_MSMS)
        )

        progress = ProgressLogger(total=actual_spectra)

        # Pre-load FrameMsMsInfo for all MS2 frames in range
        ms2_frame_ids = [
            int(f[0])
            for f in all_frames
            if start_frame <= int(f[0]) <= end_frame
            and int(f[4]) == TSF_MSMS_TYPE_AUTO_MSMS
        ]
        ms2_info_cache = reader.get_ms2_info_batch(ms2_frame_ids)

        # Build a map of MS1 frame_id → last written MS1 spectrum_id so that
        # MS2 frames can reference their parent MS1 by spectrum ID.
        # We populate this as we write MS1 spectra.
        ms1_spectrum_id_by_frame: dict[int, str] = {}
        last_ms1_spectrum_id: str = "index=0"

        with IndexedMzMLWriter(
            output_path=config.output,
            metadata=meta,
            input_path=config.input,
            compression=config.compression,
            total_spectra=actual_spectra,
            checksum_source_files=config.checksum_source_files,
        ) as writer:
            for frame in all_frames:
                frame_id = int(frame[0])
                frame_time = float(frame[1])
                polarity_char = str(frame[2]) if frame[2] is not None else "+"
                msms_type = int(frame[4])
                scan_start_time = frame_time / 60.0

                if frame_id < start_frame or frame_id > end_frame:
                    continue

                polarity = _polarity_cv(polarity_char)

                if msms_type == TSF_MSMS_TYPE_MS1:
                    # Read the line spectrum
                    try:
                        raw_mz, raw_i = reader.read_line_spectrum(frame_id)
                    except RuntimeError as exc:
                        logger.warning(
                            "Frame %d: read_line_spectrum failed: %s", frame_id, exc
                        )
                        raw_mz = np.empty(0, dtype=np.float64)
                        raw_i = np.empty(0, dtype=np.float32)

                    # Apply MS1 threshold
                    if config.ms1_threshold > 0 and len(raw_i) > 0:
                        mask = raw_i >= config.ms1_threshold
                        raw_mz = raw_mz[mask]
                        raw_i = raw_i[mask]

                    arrays = SpectrumArrays(
                        mz=raw_mz,
                        intensity=raw_i,
                    )

                    last_ms1_spectrum_id = writer.write_ms1_spectrum(
                        arrays=arrays,
                        scan_start_time=scan_start_time,
                        centroided=True,
                        one_over_k0=None,
                        polarity=polarity,
                    )
                    ms1_spectrum_id_by_frame[frame_id] = last_ms1_spectrum_id
                    progress.update(ms_level=1)

                elif msms_type == TSF_MSMS_TYPE_AUTO_MSMS:
                    info = ms2_info_cache.get(frame_id)
                    if info is None:
                        logger.warning(
                            "Frame %d: no FrameMsMsInfo entry, skipping", frame_id
                        )
                        continue

                    # Resolve parent MS1 spectrum ID
                    parent_ms1_frame = info["Parent"]
                    parent_spectrum_id = ms1_spectrum_id_by_frame.get(
                        parent_ms1_frame, last_ms1_spectrum_id
                    )

                    # Read the MS2 line spectrum
                    try:
                        raw_mz, raw_i = reader.read_line_spectrum(frame_id)
                    except RuntimeError as exc:
                        logger.warning(
                            "Frame %d: read_line_spectrum failed: %s", frame_id, exc
                        )
                        raw_mz = np.empty(0, dtype=np.float64)
                        raw_i = np.empty(0, dtype=np.float32)

                    # Apply MS2 threshold
                    if config.ms2_threshold > 0 and len(raw_i) > 0:
                        mask = raw_i >= config.ms2_threshold
                        raw_mz = raw_mz[mask]
                        raw_i = raw_i[mask]

                    # Apply n-largest filter
                    if config.ms2_nlargest > 0 and len(raw_i) > config.ms2_nlargest:
                        top_idx = np.argpartition(raw_i, -config.ms2_nlargest)[
                            -config.ms2_nlargest:
                        ]
                        top_idx = top_idx[np.argsort(raw_mz[top_idx])]
                        raw_mz = raw_mz[top_idx]
                        raw_i = raw_i[top_idx]

                    arrays = SpectrumArrays(
                        mz=raw_mz,
                        intensity=raw_i,
                    )

                    trigger_mz = info["TriggerMass"]
                    isolation_width = info["IsolationWidth"]
                    half_width = isolation_width / 2.0
                    charge = info["PrecursorCharge"]

                    precursor_info = PrecursorInfo(
                        mz=trigger_mz,
                        charge=int(charge) if charge is not None else None,
                        spectrum_reference=parent_spectrum_id,
                        isolation_window_target=trigger_mz,
                        isolation_window_lower=half_width,
                        isolation_window_upper=half_width,
                        one_over_k0=None,
                        collision_energy=info["CollisionEnergy"],
                        activation="CID",
                    )

                    writer.write_ms2_spectrum(
                        arrays=arrays,
                        scan_start_time=scan_start_time,
                        precursor=precursor_info,
                        polarity=polarity,
                    )
                    progress.update(ms_level=2)

    logger.info("Conversion complete: %s", config.output)


@timing
def run_baf_conversion(config: ConversionConfig) -> None:
    """Execute a full BAF → indexed mzML conversion.

    Parameters
    ----------
    config : ConversionConfig
        Validated conversion parameters.
    """
    logger.info("tdf2mzml v%s  [BAF mode]", __version__)
    logger.info("Input:  %s", config.input)
    logger.info("Output: %s", config.output)

    with BafReader(config.input) as reader:
        meta = reader.metadata
        logger.info(
            "%d spectra total | %d MS1 | %d MS2",
            meta.frame_count,
            meta.ms1_spectra_count,
            meta.ms2_dda_count,
        )

        all_spectra = reader.get_all_spectra()

        start_frame = config.start_frame if config.start_frame != -1 else 1
        end_frame = (
            config.end_frame if config.end_frame != -1 else meta.frame_count
        )

        # Filter to the requested range
        spectra_in_range = [
            row for row in all_spectra
            if start_frame <= int(row[0]) <= end_frame
        ]
        actual_spectra = len(spectra_in_range)
        progress = ProgressLogger(total=actual_spectra)

        # Pre-load MS2 precursor info for all MS2 spectra in range
        ms2_ids = [
            int(row[0]) for row in spectra_in_range if int(row[9]) >= BAF_MS_LEVEL_MS1 + 1
        ]
        ms2_info_cache = reader.get_ms2_precursor_batch(ms2_ids)

        # Track last written MS1 spectrum ID for MS2 parent references
        last_ms1_spectrum_id: str = "index=0"

        with IndexedMzMLWriter(
            output_path=config.output,
            metadata=meta,
            input_path=config.input,
            compression=config.compression,
            total_spectra=actual_spectra,
            checksum_source_files=config.checksum_source_files,
        ) as writer:
            for row in spectra_in_range:
                # Unpack spectrum row
                # (Id, Rt, Parent, MzAcqRangeLower, MzAcqRangeUpper,
                #  LineMzId, LineIntensityId, ProfileMzId, ProfileIntensityId,
                #  MsLevel, Polarity)
                spec_id   = int(row[0])
                rt_sec    = float(row[1]) if row[1] is not None else 0.0
                ms_level  = int(row[9])
                polarity_code = int(row[10]) if row[10] is not None else BAF_POLARITY_POSITIVE
                line_mz_id  = row[5]
                line_int_id = row[6]
                prof_mz_id  = row[7]
                prof_int_id = row[8]

                scan_start_time = rt_sec / 60.0
                polarity = (
                    "positive scan" if polarity_code == BAF_POLARITY_POSITIVE
                    else "negative scan"
                )

                # --- Read spectrum arrays ---
                # Prefer centroid (line); fall back to profile for MS1
                use_centroid = config.ms1_type != "profile"
                if use_centroid and line_mz_id is not None and line_int_id is not None:
                    try:
                        raw_mz, raw_i = reader.read_line_spectrum(
                            int(line_mz_id), int(line_int_id)
                        )
                        centroided = True
                    except RuntimeError as exc:
                        logger.warning("Spectrum %d: line read failed: %s", spec_id, exc)
                        raw_mz = np.empty(0, dtype=np.float64)
                        raw_i = np.empty(0, dtype=np.float32)
                        centroided = True
                elif prof_mz_id is not None and prof_int_id is not None:
                    try:
                        raw_mz, raw_i = reader.read_profile_spectrum(
                            int(prof_mz_id), int(prof_int_id)
                        )
                        centroided = False
                    except RuntimeError as exc:
                        logger.warning("Spectrum %d: profile read failed: %s", spec_id, exc)
                        raw_mz = np.empty(0, dtype=np.float64)
                        raw_i = np.empty(0, dtype=np.float32)
                        centroided = False
                else:
                    raw_mz = np.empty(0, dtype=np.float64)
                    raw_i = np.empty(0, dtype=np.float32)
                    centroided = True

                # --- MS1 ---
                if ms_level == BAF_MS_LEVEL_MS1:
                    if config.ms1_threshold > 0 and len(raw_i) > 0:
                        mask = raw_i >= config.ms1_threshold
                        raw_mz = raw_mz[mask]
                        raw_i = raw_i[mask]

                    arrays = SpectrumArrays(mz=raw_mz, intensity=raw_i)
                    last_ms1_spectrum_id = writer.write_ms1_spectrum(
                        arrays=arrays,
                        scan_start_time=scan_start_time,
                        centroided=centroided,
                        polarity=polarity,
                    )
                    progress.update(ms_level=1)

                # --- MS2 ---
                else:
                    if config.ms2_threshold > 0 and len(raw_i) > 0:
                        mask = raw_i >= config.ms2_threshold
                        raw_mz = raw_mz[mask]
                        raw_i = raw_i[mask]

                    if config.ms2_nlargest > 0 and len(raw_i) > config.ms2_nlargest:
                        top_idx = np.argpartition(raw_i, -config.ms2_nlargest)[
                            -config.ms2_nlargest:
                        ]
                        top_idx = top_idx[np.argsort(raw_mz[top_idx])]
                        raw_mz = raw_mz[top_idx]
                        raw_i = raw_i[top_idx]

                    arrays = SpectrumArrays(mz=raw_mz, intensity=raw_i)

                    info = ms2_info_cache.get(spec_id, {})
                    precursor_mz = info.get("mass", 0.0)
                    ce = info.get("collision_energy")
                    iso_w = info.get("isolation_width")
                    half_w = float(iso_w) / 2.0 if iso_w is not None else None

                    precursor_info = PrecursorInfo(
                        mz=float(precursor_mz),
                        charge=None,
                        spectrum_reference=last_ms1_spectrum_id,
                        isolation_window_target=float(precursor_mz),
                        isolation_window_lower=half_w,
                        isolation_window_upper=half_w,
                        one_over_k0=None,
                        collision_energy=float(ce) if ce is not None else None,
                        activation="CID",
                    )
                    writer.write_ms2_spectrum(
                        arrays=arrays,
                        scan_start_time=scan_start_time,
                        precursor=precursor_info,
                        polarity=polarity,
                    )
                    progress.update(ms_level=2)

    logger.info("Conversion complete: %s", config.output)


@timing
def run_conversion(config: ConversionConfig) -> None:
    """Execute a full TDF → indexed mzML conversion.

    Parameters
    ----------
    config : ConversionConfig
        Validated conversion parameters.
    """
    # Detect schema type and dispatch to the appropriate converter
    inp = config.input
    is_baf = (inp.suffix == ".baf" and inp.is_file()) or (
        (inp / "analysis.baf").exists() and not (inp / "analysis.tdf").exists()
    )
    if is_baf:
        run_baf_conversion(config)
        return
    if (inp / "analysis.tsf").exists() and not (inp / "analysis.tdf").exists():
        run_tsf_conversion(config)
        return

    logger.info("tdf2mzml v%s", __version__)
    logger.info("Input:  %s", config.input)
    logger.info("Output: %s", config.output)

    with TdfReader(config.input) as reader:
        meta = reader.metadata
        logger.info(
            "%d frames | %d MS1 | %d DDA precursors | %d DIA frames",
            meta.frame_count,
            meta.ms1_spectra_count,
            meta.ms2_dda_count,
            meta.ms2_dia_count,
        )

        # Resolve frame range
        all_frames = reader.get_all_frames()
        start_frame = config.start_frame if config.start_frame != -1 else 1
        end_frame = (
            config.end_frame if config.end_frame != -1 else meta.frame_count
        )

        actual_spectra = _count_spectra_in_range(
            reader, all_frames, start_frame, end_frame, meta
        )
        progress = ProgressLogger(total=actual_spectra)

        with IndexedMzMLWriter(
            output_path=config.output,
            metadata=meta,
            input_path=config.input,
            compression=config.compression,
            total_spectra=actual_spectra,
            checksum_source_files=config.checksum_source_files,
        ) as writer:
            _write_spectra(
                reader=reader,
                writer=writer,
                config=config,
                all_frames=all_frames,
                start_frame=start_frame,
                end_frame=end_frame,
                progress=progress,
            )

    logger.info("Conversion complete: %s", config.output)


def _write_spectra(
    reader: TdfReader,
    writer: IndexedMzMLWriter,
    config: ConversionConfig,
    all_frames: list[tuple[int, ...]],
    start_frame: int,
    end_frame: int,
    progress: ProgressLogger,
) -> None:
    """Inner loop: iterate frames and write spectra.

    Parameters
    ----------
    reader : TdfReader
        Open TDF reader.
    writer : IndexedMzMLWriter
        Open mzML writer.
    config : ConversionConfig
        Conversion parameters.
    all_frames : list of tuple
        All frame rows from the ``Frames`` table.
    start_frame : int
        First frame ID to process (inclusive).
    end_frame : int
        Last frame ID to process (inclusive).
    progress : ProgressLogger
        Progress reporter.
    """
    last_ms1_spectrum_id: str = "index=0"

    meta = reader.metadata

    # Load all DDA precursors for the frame range in a single SQL query
    from tdf2mzml.models.spectrum import PrecursorRow
    dda_precursors: dict[int, list[PrecursorRow]] = (
        reader.get_precursors_in_range(start_frame, end_frame)
        if meta.has_pasef_dda
        else {}
    )

    # Pre-load PASEF frame info for all precursors in one batch SQL query
    all_precursor_ids: list[int] = [
        int(p["Id"])
        for precs in dda_precursors.values()
        for p in precs
    ]
    pasef_info_cache: dict[int, dict[str, float]] = (
        reader.get_pasef_frame_info_batch(all_precursor_ids)
        if all_precursor_ids
        else {}
    )

    for frame in all_frames:
        frame_id = int(frame[0])
        frame_time = float(frame[1])
        msms_type = int(frame[4])
        scan_start_time = frame_time / 60.0

        if frame_id < start_frame or frame_id > end_frame:
            continue

        num_scans = int(frame[8])  # NumScans column

        # ---- MS1 frame ----
        if msms_type == MSMS_TYPE_MS1:
            ook0: float | None = None
            im_array: np.ndarray | None = None

            if config.ion_mobility == "array":
                # Full IM-resolved mode: one spectrum per frame, all IM bins
                # kept as separate peaks with a parallel per-peak 1/K0 array.
                arrays, im_array = get_im_resolved_ms1(
                    reader=reader,
                    frame_id=frame_id,
                    num_scans=num_scans,
                    threshold=config.ms1_threshold,
                )
                centroided = True
                if im_array.size == 0:
                    im_array = None
            else:
                arrays, centroided = get_ms1_spectrum(
                    reader=reader,
                    frame_id=frame_id,
                    num_scans=num_scans,
                    ms1_type=config.ms1_type,
                    threshold=config.ms1_threshold,
                    peak_picker_resolution=None,
                )
                if config.ion_mobility == "mean" and not arrays.is_empty:
                    ook0 = mean_ook0_for_frame(reader, frame_id, num_scans)

            last_ms1_spectrum_id = writer.write_ms1_spectrum(
                arrays=arrays,
                scan_start_time=scan_start_time,
                centroided=centroided,
                one_over_k0=ook0,
                ion_mobility_array=im_array,
            )
            progress.update(ms_level=1)

            # ---- PASEF DDA: emit MS2s for every precursor of this MS1 frame ----
            # Precursors.Parent = MS1 frame ID, so we look up by MS1 frame_id here.
            # The SDK's read_pasef_msms collapses all associated DDA frames per
            # precursor automatically — we never iterate DDA frames ourselves.
            if meta.has_pasef_dda:
                frame_precursors = dda_precursors.get(frame_id, [])
                if frame_precursors:
                    # Batch SDK call: fetch all MS2 spectra for this frame at once
                    frame_prec_ids = [int(p["Id"]) for p in frame_precursors]
                    ms2_batch = reader.read_pasef_msms(frame_prec_ids, sparse=True)

                    # Batch 1/K0 conversion for all precursor scan numbers at once
                    scan_numbers = [
                        float(p["ScanNumber"])
                        for p in frame_precursors
                        if p.get("ScanNumber") is not None
                    ]
                    prec_ook0: dict[int, float] = {}
                    if scan_numbers:
                        ook0_arr = reader.scan_num_to_one_over_k0(frame_id, scan_numbers)
                        sn_iter = (
                            p for p in frame_precursors if p.get("ScanNumber") is not None
                        )
                        prec_ook0 = {
                            int(p["Id"]): float(v)
                            for p, v in zip(sn_iter, ook0_arr)
                        }

                    for precursor in frame_precursors:
                        ms2_arrays, precursor_info = get_pasef_dda_ms2(
                            reader=reader,
                            precursor=precursor,
                            parent_spectrum_id=last_ms1_spectrum_id,
                            ms2_data=ms2_batch,
                            pasef_info=pasef_info_cache,
                            one_over_k0=prec_ook0.get(int(precursor["Id"])),
                        )
                        writer.write_ms2_spectrum(
                            arrays=ms2_arrays,
                            scan_start_time=scan_start_time,
                            precursor=precursor_info,
                        )
                        progress.update(ms_level=2)

        # ---- PASEF DIA MS2 frame ----
        elif msms_type == MSMS_TYPE_PASEF_DIA and meta.has_pasef_dia:
            window_group = reader.get_dia_window_group(frame_id)
            windows = reader.get_dia_windows_for_group(window_group)
            for window in windows:
                ms2_arrays, precursor_info = get_pasef_dia_ms2(
                    reader=reader,
                    frame_id=frame_id,
                    window=window,
                    parent_spectrum_id=last_ms1_spectrum_id,
                )
                writer.write_ms2_spectrum(
                    arrays=ms2_arrays,
                    scan_start_time=scan_start_time,
                    precursor=precursor_info,
                )
                progress.update(ms_level=2)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> None:
    """CLI entry point.

    Parameters
    ----------
    argv : list of str or None, optional
        Argument list; defaults to ``sys.argv[1:]``.
    """
    config = parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if config.debug else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    run_conversion(config)


if __name__ == "__main__":
    main()
