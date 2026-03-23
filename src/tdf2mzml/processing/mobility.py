"""Ion mobility calculations and 1/K0 utility functions.

Provides intensity-weighted mean 1/K0 computation and per-scan TIC
aggregation.  All functions are pure numeric transforms operating on
numpy arrays — no SDK calls or file I/O.

The primary use case is the ``"mean"`` ion mobility mode, where each
MS1 spectrum gets a single representative 1/K0 value computed as the
intensity-weighted average across all mobility scan lines.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import numpy.typing as npt

if TYPE_CHECKING:
    from tdf2mzml.io.reader import TdfReader


def intensity_weighted_mean_ook0(
    scan_intensities: npt.NDArray[np.float32 | np.int32 | np.uint32],
    ook0_values: npt.NDArray[np.float64],
) -> float:
    """Compute the intensity-weighted mean 1/K0 across mobility scans.

    This is the ``"mean"`` ion mobility mode: a single representative
    1/K0 value is derived per spectrum by weighting each scan's 1/K0
    by that scan's total ion current.

    Parameters
    ----------
    scan_intensities : numpy.ndarray
        Per-scan summed intensity (TIC) values.  Shape ``(n_scans,)``.
    ook0_values : numpy.ndarray
        1/K0 values (V·s/cm²) for each scan.  Shape ``(n_scans,)``.

    Returns
    -------
    float
        Intensity-weighted mean 1/K0 in V·s/cm².  Returns the arithmetic
        mean if total intensity is zero.

    Notes
    -----
    Requires ``len(scan_intensities) == len(ook0_values)``.
    """
    total = float(np.sum(scan_intensities))
    if total == 0.0:
        return float(np.mean(ook0_values))
    weights = scan_intensities.astype(np.float64) / total
    return float(np.dot(weights, ook0_values))


def per_scan_tic(
    scans: list[tuple[npt.NDArray[np.uint32], npt.NDArray[np.uint32]]],
) -> npt.NDArray[np.float32]:
    """Compute the total ion current for each raw scan.

    Uses a single ``np.add.reduceat`` call on concatenated intensities rather
    than a Python-level loop over scans, which is significantly faster for
    frames with many scan lines (e.g. 1 000+ mobility bins).

    Parameters
    ----------
    scans : list of tuple
        Raw scan data as ``[(indices, intensities), ...]``.

    Returns
    -------
    numpy.ndarray
        Per-scan TIC values (float32), length equals ``len(scans)``.
    """
    n = len(scans)
    if n == 0:
        return np.empty(0, dtype=np.float32)

    result = np.zeros(n, dtype=np.float32)

    # np.add.reduceat requires strictly increasing start indices, so we
    # must skip empty scans and only concatenate non-empty intensity arrays.
    nonempty_idx = [i for i, s in enumerate(scans) if len(s[1]) > 0]
    if not nonempty_idx:
        return result

    arrs = [scans[i][1] for i in nonempty_idx]
    all_int = np.concatenate(arrs).astype(np.float32)
    # Build cumulative start offsets for reduceat: [0, len0, len0+len1, ...]
    ne_lengths = np.fromiter((len(a) for a in arrs), dtype=np.intp, count=len(arrs))
    starts = np.zeros(len(arrs), dtype=np.intp)
    np.cumsum(ne_lengths[:-1], out=starts[1:])

    sums = np.add.reduceat(all_int, starts)
    result[nonempty_idx] = sums
    return result


def mean_ook0_for_frame(
    reader: TdfReader,
    frame_id: int,
    num_scans: int,
) -> float:
    """Compute intensity-weighted mean 1/K0 for an entire MS1 frame.

    Uses :meth:`~tdf2mzml.io.reader.TdfReader.read_scan_tics` instead of
    :meth:`~tdf2mzml.io.reader.TdfReader.read_scans` to avoid copying index
    arrays for every scan line.

    Parameters
    ----------
    reader : TdfReader
        Open TDF reader (used for scan data and scan→1/K0 conversion).
    frame_id : int
        TDF frame ID.
    num_scans : int
        Total number of scans in the frame.

    Returns
    -------
    float
        Intensity-weighted mean 1/K0 in V·s/cm².
    """
    scan_nums = np.arange(0, num_scans, dtype=np.float64)
    ook0_values: npt.NDArray[np.float64] = reader.scan_num_to_one_over_k0(
        frame_id, scan_nums
    )
    tic_per_scan = reader.read_scan_tics(frame_id, 0, num_scans)
    return intensity_weighted_mean_ook0(tic_per_scan, ook0_values)
