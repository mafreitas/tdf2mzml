"""MS1 spectrum extraction functions.

All functions take a :class:`~tdf2mzml.io.reader.TdfReader` and frame
parameters, and return a :class:`~tdf2mzml.models.spectrum.SpectrumArrays`
instance.  No I/O beyond the reader, no psims, no mzML concerns here.
"""

import logging
from typing import Literal

import numpy as np
import numpy.typing as npt

from tdf2mzml.io.reader import TdfReader
from tdf2mzml.models.spectrum import SpectrumArrays

logger = logging.getLogger(__name__)


def get_centroid_ms1(
    reader: TdfReader,
    frame_id: int,
    num_scans: int,
    peak_picker_resolution: float | None = None,
) -> SpectrumArrays:
    """Extract a centroided MS1 spectrum for a full TDF frame.

    Delegates to the Bruker SDK ``tims_extract_centroided_spectrum_for_frame_v2``
    which performs on-instrument-style peak picking across all mobility scans.

    Parameters
    ----------
    reader : TdfReader
        Open TDF reader.
    frame_id : int
        TDF frame ID (1-based).
    num_scans : int
        Number of scan lines in the frame (from ``Frames.NumScans``).
    peak_picker_resolution : float or None, optional
        Custom resolution parameter passed to the SDK peak picker.
        ``None`` uses the SDK default.

    Returns
    -------
    SpectrumArrays
        Centroided m/z (float64) and intensity (float32) arrays.
    """
    mz, intensity = reader.extract_centroided_spectrum(
        frame_id, 0, num_scans, peak_picker_resolution=peak_picker_resolution
    )
    return SpectrumArrays(mz=mz, intensity=intensity)


def get_profile_ms1(
    reader: TdfReader,
    frame_id: int,
    num_scans: int,
) -> SpectrumArrays:
    """Extract a quasi-profile MS1 spectrum for a full TDF frame.

    Parameters
    ----------
    reader : TdfReader
        Open TDF reader.
    frame_id : int
        TDF frame ID.
    num_scans : int
        Number of scan lines in the frame.

    Returns
    -------
    SpectrumArrays
        Profile m/z (float64) and intensity (float32) arrays.
    """
    intensity_i32 = reader.extract_profile_for_frame(frame_id, 0, num_scans)
    # Profile length corresponds to the full TOF bin range; map bin index → m/z
    n_bins = len(intensity_i32)
    mz = reader.index_to_mz(frame_id, np.arange(n_bins, dtype=np.float64))
    intensity = intensity_i32.astype(np.float32)
    return SpectrumArrays(mz=mz, intensity=intensity)


def get_raw_ms1(
    reader: TdfReader,
    frame_id: int,
    num_scans: int,
    threshold: float = 100.0,
) -> SpectrumArrays:
    """Build a raw MS1 spectrum by vectorised merging of all mobility scans.

    Reads raw (index, intensity) pairs for every scan line, applies a
    minimum intensity threshold, converts TOF indices to m/z in a single
    bulk SDK call, then sums intensities at coincident m/z positions using
    ``numpy.unique`` + ``numpy.bincount``.

    Parameters
    ----------
    reader : TdfReader
        Open TDF reader.
    frame_id : int
        TDF frame ID.
    num_scans : int
        Number of scan lines in the frame.
    threshold : float, optional
        Minimum peak intensity to include.  Default is 100.0.

    Returns
    -------
    SpectrumArrays
        Merged m/z (float64) and summed intensity (float32) arrays,
        sorted ascending by m/z.

    Notes
    -----
    This replaces the previous per-peak Python loop with a fully vectorised
    numpy pipeline for significant performance improvement on large frames.
    """
    scans = reader.read_scans(frame_id, 0, num_scans)

    # Concatenate all scan data into flat arrays
    index_parts: list[npt.NDArray[np.uint32]] = []
    intensity_parts: list[npt.NDArray[np.uint32]] = []
    for scan_indices, scan_intensities in scans:
        if len(scan_indices) > 0:
            index_parts.append(scan_indices)
            intensity_parts.append(scan_intensities)

    if not index_parts:
        return SpectrumArrays(
            mz=np.empty(0, dtype=np.float64),
            intensity=np.empty(0, dtype=np.float32),
        )

    all_indices = np.concatenate(index_parts)
    all_intensities = np.concatenate(intensity_parts).astype(np.float32)

    # Apply intensity threshold before the expensive SDK conversion call
    mask = all_intensities >= threshold
    if not np.any(mask):
        return SpectrumArrays(
            mz=np.empty(0, dtype=np.float64),
            intensity=np.empty(0, dtype=np.float32),
        )
    all_indices = all_indices[mask]
    all_intensities = all_intensities[mask]

    # Single bulk SDK call: convert all indices to m/z
    all_mz = reader.index_to_mz(frame_id, all_indices.astype(np.float64))

    # Round to 4 decimal places then sum coincident m/z values
    mz_rounded = np.round(all_mz, decimals=4)
    unique_mz, inv = np.unique(mz_rounded, return_inverse=True)
    summed_intensity = np.bincount(inv, weights=all_intensities).astype(np.float32)

    return SpectrumArrays(mz=unique_mz, intensity=summed_intensity)


def get_im_resolved_ms1(
    reader: TdfReader,
    frame_id: int,
    num_scans: int,
    threshold: float = 0.0,
) -> tuple[SpectrumArrays, npt.NDArray[np.float64]]:
    """Extract an IM-resolved MS1 spectrum preserving all ion mobility bins.

    Unlike :func:`get_raw_ms1`, this function does **not** merge peaks at
    coincident m/z values.  Every peak from every scan line is kept
    separately, and a parallel per-peak 1/K0 array is returned so that the
    full IM dimension can be written as a third binary array in the mzML
    output.

    Parameters
    ----------
    reader : TdfReader
        Open TDF reader.
    frame_id : int
        TDF frame ID.
    num_scans : int
        Number of scan lines in the frame.
    threshold : float, optional
        Minimum peak intensity to include.  Default is 0.0 (keep all).

    Returns
    -------
    tuple of (SpectrumArrays, ndarray)
        ``(arrays, ook0_array)`` where ``arrays`` holds m/z (float64) and
        intensity (float32) sorted by ascending m/z, and ``ook0_array`` is
        the parallel per-peak 1/K0 (float64) derived from each peak's exact
        scan-line position.
    """
    scans = reader.read_scans(frame_id, 0, num_scans)

    # One batch SDK call: 1/K0 for every scan number
    ook0_per_scan = reader.scan_num_to_one_over_k0(
        frame_id, np.arange(num_scans, dtype=np.float64)
    )

    index_parts: list[npt.NDArray[np.uint32]] = []
    int_parts: list[npt.NDArray[np.float32]] = []
    scan_id_parts: list[npt.NDArray[np.int32]] = []

    for scan_idx, (scan_indices, scan_intensities) in enumerate(scans):
        if len(scan_indices) == 0:
            continue
        scan_int = scan_intensities.astype(np.float32)
        if threshold > 0:
            mask = scan_int >= threshold
            if not np.any(mask):
                continue
            scan_indices = scan_indices[mask]
            scan_int = scan_int[mask]
        index_parts.append(scan_indices)
        int_parts.append(scan_int)
        scan_id_parts.append(
            np.full(len(scan_indices), scan_idx, dtype=np.int32)
        )

    if not index_parts:
        empty_f64 = np.empty(0, dtype=np.float64)
        return (
            SpectrumArrays(
                mz=empty_f64,
                intensity=np.empty(0, dtype=np.float32),
            ),
            empty_f64,
        )

    all_indices = np.concatenate(index_parts)
    all_int = np.concatenate(int_parts)
    all_scan_ids = np.concatenate(scan_id_parts)

    # Single bulk SDK call: convert all indices to m/z at once
    all_mz = reader.index_to_mz(frame_id, all_indices.astype(np.float64))
    all_ook0 = ook0_per_scan[all_scan_ids]

    # Sort by m/z (required by mzML spec)
    order = np.argsort(all_mz)
    return (
        SpectrumArrays(mz=all_mz[order], intensity=all_int[order]),
        all_ook0[order].astype(np.float64),
    )


def get_ms1_spectrum(
    reader: TdfReader,
    frame_id: int,
    num_scans: int,
    ms1_type: Literal["centroid", "profile", "raw"],
    threshold: float = 100.0,
    peak_picker_resolution: float | None = None,
) -> tuple[SpectrumArrays, bool]:
    """Dispatch MS1 extraction to the appropriate function by type.

    Parameters
    ----------
    reader : TdfReader
        Open TDF reader.
    frame_id : int
        TDF frame ID.
    num_scans : int
        Number of scan lines in the frame.
    ms1_type : {"centroid", "profile", "raw"}
        Which extraction method to use.
    threshold : float, optional
        Intensity threshold for raw mode.  Default is 100.0.
    peak_picker_resolution : float or None, optional
        Custom peak picker resolution for centroid mode.

    Returns
    -------
    tuple
        ``(SpectrumArrays, centroided_flag)`` where the flag is True for
        centroid and raw modes, False for profile mode.
    """
    if ms1_type == "centroid":
        return (
            get_centroid_ms1(reader, frame_id, num_scans, peak_picker_resolution),
            True,
        )
    if ms1_type == "profile":
        return get_profile_ms1(reader, frame_id, num_scans), False
    # raw
    return get_raw_ms1(reader, frame_id, num_scans, threshold), True
