"""Typed Python ctypes wrapper for the Bruker TIMS SDK (TDF format).

This module wraps the compiled Bruker TIMS SDK shared library
(``libtimsdata.so`` on Linux, ``timsdata.dll`` on Windows) using ctypes.
The binaries live in ``src/tdf2mzml/libs/`` and are bundled with the package.

SDK version: 3.3.6.2

Notes
-----
Bruker provides a reference ctypes example at
``timsdata/examples/py/timsdata.py``.  This module is our own clean,
fully-typed reimplementation of that interface, using the v3.3.6.2 API
(``tims_open_v2``, ``tims_read_pasef_msms_v2``,
``tims_extract_centroided_spectrum_for_frame_v2``, etc.).

References
----------
Bruker TDF-SDK documentation (see ``timsdata/Documentation.pdf``).
"""

import os
import sqlite3
from collections.abc import Iterator
from ctypes import (
    CFUNCTYPE,
    POINTER,
    Structure,
    c_char_p,
    c_double,
    c_float,
    c_int32,
    c_int64,
    c_uint32,
    c_uint64,
    c_void_p,
    cdll,
    create_string_buffer,
)
from enum import IntEnum
from pathlib import Path
from sys import platform

import numpy as np
import numpy.typing as npt

# ---------------------------------------------------------------------------
# Locate and load the shared library
# ---------------------------------------------------------------------------

_LIBS_DIR = Path(__file__).parent.parent / "libs"

if platform.startswith("win32"):
    _lib_path = (_LIBS_DIR / "timsdata.dll").as_posix()
elif platform.startswith("linux"):
    _lib_path = (_LIBS_DIR / "libtimsdata.so").as_posix()
else:
    raise OSError(f"Unsupported platform: {platform!r}")

_dll = cdll.LoadLibrary(_lib_path)

# ---------------------------------------------------------------------------
# DLL function signatures — SDK v3.3.6.2
# ---------------------------------------------------------------------------

# open / close
_dll.tims_open_v2.argtypes = [c_char_p, c_uint32, c_uint32]
_dll.tims_open_v2.restype = c_uint64
_dll.tims_open_recalibration_id.argtypes = [c_char_p, c_char_p]
_dll.tims_open_recalibration_id.restype = c_uint64
_dll.tims_close.argtypes = [c_uint64]
_dll.tims_close.restype = None

# error
_dll.tims_get_last_error_string.argtypes = [c_char_p, c_uint32]
_dll.tims_get_last_error_string.restype = c_uint32

# recalibration
_dll.tims_has_recalibrated_state.argtypes = [c_uint64]
_dll.tims_has_recalibrated_state.restype = c_uint32
_dll.tims_get_calibration_id.argtypes = [c_uint64, c_char_p, c_uint32]
_dll.tims_get_calibration_id.restype = c_uint32

# raw scan reading
_dll.tims_read_scans_v2.argtypes = [
    c_uint64,
    c_int64,
    c_uint32,
    c_uint32,
    c_void_p,
    c_uint32,
]
_dll.tims_read_scans_v2.restype = c_uint32

# callback functor types
_MSMS_FUNCTOR = CFUNCTYPE(None, c_int64, c_uint32, POINTER(c_double), POINTER(c_float))
_MSMS_PROFILE_FUNCTOR = CFUNCTYPE(None, c_int64, c_uint32, POINTER(c_int32))

# PASEF MS/MS — v2 (sparse, recommended) and v2_2024 (dense)
_dll.tims_read_pasef_msms_v2.argtypes = [
    c_uint64,
    POINTER(c_int64),
    c_uint32,
    _MSMS_FUNCTOR,
    c_void_p,
]
_dll.tims_read_pasef_msms_v2.restype = c_uint32
_dll.tims_read_pasef_msms_for_frame_v2.argtypes = [
    c_uint64,
    c_int64,
    _MSMS_FUNCTOR,
    c_void_p,
]
_dll.tims_read_pasef_msms_for_frame_v2.restype = c_uint32
_dll.tims_read_pasef_msms_v2_2024.argtypes = [
    c_uint64,
    POINTER(c_int64),
    c_uint32,
    _MSMS_FUNCTOR,
    c_void_p,
]
_dll.tims_read_pasef_msms_v2_2024.restype = c_uint32
_dll.tims_read_pasef_msms_for_frame_v2_2024.argtypes = [
    c_uint64,
    c_int64,
    _MSMS_FUNCTOR,
    c_void_p,
]
_dll.tims_read_pasef_msms_for_frame_v2_2024.restype = c_uint32

# PASEF profile MS/MS
_dll.tims_read_pasef_profile_msms.argtypes = [
    c_uint64,
    POINTER(c_int64),
    c_uint32,
    _MSMS_PROFILE_FUNCTOR,
]
_dll.tims_read_pasef_profile_msms.restype = c_uint32
_dll.tims_read_pasef_profile_msms_for_frame.argtypes = [
    c_uint64,
    c_int64,
    _MSMS_PROFILE_FUNCTOR,
]
_dll.tims_read_pasef_profile_msms_for_frame.restype = c_uint32

# centroid extraction — v2 (dense), v3 (sparse), ext variants (custom resolution)
_dll.tims_extract_centroided_spectrum_for_frame_v2.argtypes = [
    c_uint64,
    c_int64,
    c_uint32,
    c_uint32,
    _MSMS_FUNCTOR,
    c_void_p,
]
_dll.tims_extract_centroided_spectrum_for_frame_v2.restype = c_uint32
_dll.tims_extract_centroided_spectrum_for_frame_v3.argtypes = [
    c_uint64,
    c_int64,
    c_uint32,
    c_uint32,
    _MSMS_FUNCTOR,
    c_void_p,
]
_dll.tims_extract_centroided_spectrum_for_frame_v3.restype = c_uint32
_dll.tims_extract_centroided_spectrum_for_frame_ext.argtypes = [
    c_uint64,
    c_int64,
    c_uint32,
    c_uint32,
    c_double,
    _MSMS_FUNCTOR,
    c_void_p,
]
_dll.tims_extract_centroided_spectrum_for_frame_ext.restype = c_uint32
_dll.tims_extract_centroided_spectrum_for_frame_ext_v3.argtypes = [
    c_uint64,
    c_int64,
    c_uint32,
    c_uint32,
    c_double,
    _MSMS_FUNCTOR,
    c_void_p,
]
_dll.tims_extract_centroided_spectrum_for_frame_ext_v3.restype = c_uint32

# profile extraction
_dll.tims_extract_profile_for_frame.argtypes = [
    c_uint64,
    c_int64,
    c_uint32,
    c_uint32,
    _MSMS_PROFILE_FUNCTOR,
    c_void_p,
]
_dll.tims_extract_profile_for_frame.restype = c_uint32


# chromatogram extraction
class ChromatogramJob(Structure):
    """Job descriptor for a single EIC/XIC extraction request."""

    _fields_ = [
        ("id", c_int64),
        ("time_begin", c_double),
        ("time_end", c_double),
        ("mz_min", c_double),
        ("mz_max", c_double),
        ("ook0_min", c_double),
        ("ook0_max", c_double),
    ]


_CHROM_JOB_GEN = CFUNCTYPE(c_uint32, POINTER(ChromatogramJob), c_void_p)
_CHROM_TRACE_SINK = CFUNCTYPE(
    c_uint32, c_int64, c_uint32, POINTER(c_int64), POINTER(c_uint64), c_void_p
)
_dll.tims_extract_chromatograms.argtypes = [
    c_uint64,
    _CHROM_JOB_GEN,
    _CHROM_TRACE_SINK,
    c_void_p,
]
_dll.tims_extract_chromatograms.restype = c_uint32

# coordinate conversions
_CONV_ARGS = [c_uint64, c_int64, POINTER(c_double), POINTER(c_double), c_uint32]
for _fn in (
    "tims_index_to_mz",
    "tims_mz_to_index",
    "tims_scannum_to_oneoverk0",
    "tims_oneoverk0_to_scannum",
    "tims_scannum_to_voltage",
    "tims_voltage_to_scannum",
):
    getattr(_dll, _fn).argtypes = _CONV_ARGS
    getattr(_dll, _fn).restype = c_uint32

# CCS / 1/K0 utilities
_dll.tims_oneoverk0_to_ccs_for_mz.argtypes = [c_double, c_int32, c_double]
_dll.tims_oneoverk0_to_ccs_for_mz.restype = c_double
_dll.tims_ccs_to_oneoverk0_for_mz.argtypes = [c_double, c_int32, c_double]
_dll.tims_ccs_to_oneoverk0_for_mz.restype = c_double

# ---------------------------------------------------------------------------
# TSF SDK function signatures (timsTOF fleX / TIMS-off format)
# ---------------------------------------------------------------------------

# TSF open / close
_dll.tsf_open.argtypes = [c_char_p, c_uint32]
_dll.tsf_open.restype = c_uint64
_dll.tsf_close.argtypes = [c_uint64]
_dll.tsf_close.restype = None
_dll.tsf_get_last_error_string.argtypes = [c_char_p, c_uint32]
_dll.tsf_get_last_error_string.restype = c_uint32

# TSF spectrum reading
_dll.tsf_read_line_spectrum_v2.argtypes = [c_uint64, c_int64, _MSMS_FUNCTOR, c_void_p]
_dll.tsf_read_line_spectrum_v2.restype = c_uint32
_dll.tsf_read_profile_spectrum_v2.argtypes = [c_uint64, c_int64, _MSMS_PROFILE_FUNCTOR, c_void_p]
_dll.tsf_read_profile_spectrum_v2.restype = c_uint32

# TSF coordinate conversion
_TSF_CONV_ARGS = [c_uint64, c_int64, POINTER(c_double), POINTER(c_double), c_uint32]
_dll.tsf_index_to_mz.argtypes = _TSF_CONV_ARGS  # type: ignore[assignment]
_dll.tsf_index_to_mz.restype = c_uint32

# ---------------------------------------------------------------------------
# Public enums
# ---------------------------------------------------------------------------


class PressureCompensationStrategy(IntEnum):
    """Pressure compensation mode for :class:`TimsData`.

    Attributes
    ----------
    NoPressureCompensation :
        No pressure compensation applied (default).
    AnalysisGlobalPressureCompensation :
        Apply a single global pressure correction for the whole analysis.
    PerFramePressureCompensation :
        Apply per-frame pressure correction (most accurate).
    """

    NoPressureCompensation = 0
    AnalysisGlobalPressureCompensation = 1
    PerFramePressureCompensation = 2


# ---------------------------------------------------------------------------
# Internal helper
# ---------------------------------------------------------------------------


def _raise_last_error() -> None:
    """Raise a RuntimeError containing the last SDK error message."""
    n = _dll.tims_get_last_error_string(None, 0)
    buf = create_string_buffer(n)
    _dll.tims_get_last_error_string(buf, n)
    raise RuntimeError(buf.value.decode("utf-8", errors="replace"))


# ---------------------------------------------------------------------------
# Module-level CCS utilities
# ---------------------------------------------------------------------------


def one_over_k0_to_ccs(ook0: float, charge: int, mz: float) -> float:
    """Convert inverse reduced ion mobility (1/K0) to CCS.

    Uses the Mason-Schamp equation as implemented in the Bruker SDK.

    Parameters
    ----------
    ook0 : float
        Inverse reduced ion mobility in V·s/cm².
    charge : int
        Ion charge state.
    mz : float
        Ion m/z value.

    Returns
    -------
    float
        Collision cross-section in Å².
    """
    return float(_dll.tims_oneoverk0_to_ccs_for_mz(ook0, charge, mz))


def ccs_to_one_over_k0(ccs: float, charge: int, mz: float) -> float:
    """Convert CCS to inverse reduced ion mobility (1/K0).

    Parameters
    ----------
    ccs : float
        Collision cross-section in Å².
    charge : int
        Ion charge state.
    mz : float
        Ion m/z value.

    Returns
    -------
    float
        Inverse reduced ion mobility in V·s/cm².
    """
    return float(_dll.tims_ccs_to_oneoverk0_for_mz(ccs, charge, mz))


# ---------------------------------------------------------------------------
# TimsData class
# ---------------------------------------------------------------------------


class TimsData:
    """Typed wrapper around the Bruker TIMS SDK for reading TDF datasets.

    Opens the SDK handle (binary data) and a SQLite connection
    (``analysis.tdf`` metadata) for a single ``.d`` directory.

    Parameters
    ----------
    analysis_directory : str
        Absolute path to the Bruker ``.d`` directory.
    use_recalibrated_state : bool, optional
        Use the on-disk recalibrated calibration state if available.
        Default is False.
    pressure_compensation : PressureCompensationStrategy, optional
        Pressure compensation mode. Default is no compensation.
    recalibration_id : str or None, optional
        Open a specific recalibration by ID instead of the default one.

    Raises
    ------
    ValueError
        If *analysis_directory* is not a string.
    RuntimeError
        If the SDK fails to open the dataset.
    """

    def __init__(
        self,
        analysis_directory: str,
        use_recalibrated_state: bool = False,
        pressure_compensation: PressureCompensationStrategy = (
            PressureCompensationStrategy.NoPressureCompensation
        ),
        recalibration_id: str | None = None,
    ) -> None:
        if not isinstance(analysis_directory, str):
            raise ValueError("analysis_directory must be a str.")

        self._dll = _dll
        self._frame_buffer_size: int = 128

        if recalibration_id is not None:
            self.handle: int = self._dll.tims_open_recalibration_id(
                analysis_directory.encode("utf-8"),
                recalibration_id.encode("utf-8"),
            )
        else:
            self.handle = self._dll.tims_open_v2(
                analysis_directory.encode("utf-8"),
                1 if use_recalibrated_state else 0,
                int(pressure_compensation),
            )

        if self.handle == 0:
            _raise_last_error()

        self.conn: sqlite3.Connection = sqlite3.connect(
            os.path.join(analysis_directory, "analysis.tdf")
        )

    @classmethod
    def from_recalibration_id(cls, analysis_directory: str, recalibration_id: str) -> "TimsData":
        """Open a dataset using a specific recalibration ID.

        Parameters
        ----------
        analysis_directory : str
            Absolute path to the ``.d`` directory.
        recalibration_id : str
            Recalibration identifier string.

        Returns
        -------
        TimsData
        """
        return cls(analysis_directory, recalibration_id=recalibration_id)

    def close(self) -> None:
        """Close the SDK handle and SQLite connection."""
        if getattr(self, "handle", None):
            self._dll.tims_close(self.handle)
            self.handle = 0
        if getattr(self, "conn", None):
            self.conn.close()
            self.conn = None  # type: ignore[assignment]

    def __enter__(self) -> "TimsData":
        """Return self for use as a context manager."""
        return self

    def __exit__(self, *_: object) -> None:
        """Close the SDK handle on context manager exit."""
        self.close()

    def __del__(self) -> None:
        """Ensure the SDK handle is closed when the object is garbage-collected."""
        self.close()

    # ------------------------------------------------------------------
    # Internal: coordinate conversion dispatcher
    # ------------------------------------------------------------------

    def _convert(
        self,
        frame_id: int,
        values: npt.ArrayLike,
        fn: object,
    ) -> npt.NDArray[np.float64]:
        arr = (
            values
            if isinstance(values, np.ndarray) and values.dtype == np.float64
            else np.array(values, dtype=np.float64)
        )
        n = len(arr)
        out = np.empty(n, dtype=np.float64)
        ok = fn(  # type: ignore[operator]
            self.handle,
            frame_id,
            arr.ctypes.data_as(POINTER(c_double)),
            out.ctypes.data_as(POINTER(c_double)),
            n,
        )
        if ok == 0:
            _raise_last_error()
        return out

    # ------------------------------------------------------------------
    # Coordinate conversions
    # ------------------------------------------------------------------

    def index_to_mz(self, frame_id: int, indices: npt.ArrayLike) -> npt.NDArray[np.float64]:
        """Convert raw TOF bin indices to m/z values.

        Parameters
        ----------
        frame_id : int
            TDF frame ID (calibration is frame-specific).
        indices : array-like
            TOF index values.

        Returns
        -------
        numpy.ndarray
            m/z values (float64).
        """
        return self._convert(frame_id, indices, self._dll.tims_index_to_mz)

    def mz_to_index(self, frame_id: int, mzs: npt.ArrayLike) -> npt.NDArray[np.float64]:
        """Convert m/z values to raw TOF bin indices.

        Parameters
        ----------
        frame_id : int
            TDF frame ID.
        mzs : array-like
            m/z values.

        Returns
        -------
        numpy.ndarray
            TOF index values (float64).
        """
        return self._convert(frame_id, mzs, self._dll.tims_mz_to_index)

    def scan_num_to_one_over_k0(
        self, frame_id: int, scan_nums: npt.ArrayLike
    ) -> npt.NDArray[np.float64]:
        """Convert scan line indices to inverse reduced ion mobility (1/K0).

        Parameters
        ----------
        frame_id : int
            TDF frame ID.
        scan_nums : array-like
            Scan line indices (0-based).

        Returns
        -------
        numpy.ndarray
            1/K0 values in V·s/cm² (float64).
        """
        return self._convert(frame_id, scan_nums, self._dll.tims_scannum_to_oneoverk0)

    def one_over_k0_to_scan_num(
        self, frame_id: int, mobilities: npt.ArrayLike
    ) -> npt.NDArray[np.float64]:
        """Convert 1/K0 values to scan line indices.

        Parameters
        ----------
        frame_id : int
            TDF frame ID.
        mobilities : array-like
            1/K0 values in V·s/cm².

        Returns
        -------
        numpy.ndarray
            Scan line indices (float64).
        """
        return self._convert(frame_id, mobilities, self._dll.tims_oneoverk0_to_scannum)

    def scan_num_to_voltage(
        self, frame_id: int, scan_nums: npt.ArrayLike
    ) -> npt.NDArray[np.float64]:
        """Convert scan line indices to voltages.

        Parameters
        ----------
        frame_id : int
            TDF frame ID.
        scan_nums : array-like
            Scan line indices.

        Returns
        -------
        numpy.ndarray
            Voltage values (float64).
        """
        return self._convert(frame_id, scan_nums, self._dll.tims_scannum_to_voltage)

    # ------------------------------------------------------------------
    # Raw scan reading
    # ------------------------------------------------------------------

    def read_scans_buffer(
        self, frame_id: int, scan_begin: int, scan_end: int
    ) -> npt.NDArray[np.uint32]:
        """Read raw scan data into the low-level DLL buffer format.

        Parameters
        ----------
        frame_id : int
            TDF frame ID.
        scan_begin : int
            First scan line (inclusive, 0-based).
        scan_end : int
            Last scan line (exclusive).

        Returns
        -------
        numpy.ndarray
            Raw uint32 buffer as returned by ``tims_read_scans_v2``.

        Raises
        ------
        RuntimeError
            If the SDK fails or the frame exceeds the buffer size limit.
        """
        while True:
            cnt = int(self._frame_buffer_size)
            buf = np.empty(cnt, dtype=np.uint32)
            buf_bytes = 4 * cnt
            required = self._dll.tims_read_scans_v2(
                self.handle,
                frame_id,
                scan_begin,
                scan_end,
                buf.ctypes.data_as(POINTER(c_uint32)),
                buf_bytes,
            )
            if required == 0:
                _raise_last_error()
            if required > buf_bytes:
                if required > 16_777_216:
                    raise RuntimeError(
                        f"Frame {frame_id}: required buffer {required} B exceeds 16 MiB limit."
                    )
                self._frame_buffer_size = required // 4 + 1
            else:
                break
        return buf

    def read_scans(
        self, frame_id: int, scan_begin: int, scan_end: int
    ) -> list[tuple[npt.NDArray[np.uint32], npt.NDArray[np.uint32]]]:
        """Read raw (index, intensity) pairs for a scan range within a frame.

        Parameters
        ----------
        frame_id : int
            TDF frame ID.
        scan_begin : int
            First scan line (inclusive, 0-based).
        scan_end : int
            Last scan line (exclusive).

        Returns
        -------
        list of tuple
            One ``(indices, intensities)`` uint32 array pair per scan line.
        """
        buf = self.read_scans_buffer(frame_id, scan_begin, scan_end)
        result: list[tuple[npt.NDArray[np.uint32], npt.NDArray[np.uint32]]] = []
        n = scan_end - scan_begin
        offset = n
        for i in range(scan_begin, scan_end):
            n_peaks = int(buf[i - scan_begin])
            indices = buf[offset : offset + n_peaks].copy()
            offset += n_peaks
            intensities = buf[offset : offset + n_peaks].copy()
            offset += n_peaks
            result.append((indices, intensities))
        return result

    def read_scan_tics(
        self, frame_id: int, scan_begin: int, scan_end: int
    ) -> npt.NDArray[np.float32]:
        """Return per-scan total ion current using vectorised reduceat.

        Avoids copying index arrays and replaces the per-scan Python loop
        with a single ``np.add.reduceat`` over concatenated intensities.

        Parameters
        ----------
        frame_id : int
            TDF frame ID.
        scan_begin : int
            First scan line (inclusive, 0-based).
        scan_end : int
            Last scan line (exclusive).

        Returns
        -------
        numpy.ndarray
            Per-scan TIC values (float32), length ``scan_end - scan_begin``.
        """
        buf = self.read_scans_buffer(frame_id, scan_begin, scan_end)
        n = scan_end - scan_begin
        counts = buf[:n].astype(np.intp)  # peaks per scan

        total_data = int((counts * 2).sum())
        if total_data == 0:
            return np.zeros(n, dtype=np.float32)

        # Start of each scan's data block within buf[n:]
        # Layout per scan: [indices(c), intensities(c)]
        cum2 = np.empty(n + 1, dtype=np.intp)
        cum2[0] = 0
        np.cumsum(counts * 2, out=cum2[1:])

        ne_mask = counts > 0
        ne_idx = np.where(ne_mask)[0]
        if len(ne_idx) == 0:
            return np.zeros(n, dtype=np.float32)

        ne_counts = counts[ne_idx]
        # Intensity block starts at cum2[i] + counts[i] within buf[n:]
        ne_int_starts = cum2[ne_idx] + ne_counts

        # Build flat index array into buf[n:] for all intensity values
        total_ne_peaks = int(ne_counts.sum())
        cum_ne = np.empty(len(ne_counts), dtype=np.intp)
        cum_ne[0] = 0
        np.cumsum(ne_counts[:-1], out=cum_ne[1:])

        # within-scan offsets: [0,1,...,c0-1, 0,1,...,c1-1, ...]
        within = np.arange(total_ne_peaks, dtype=np.intp) - np.repeat(cum_ne, ne_counts)
        flat_idx = np.repeat(ne_int_starts, ne_counts) + within

        all_ints = buf[n:][flat_idx].astype(np.float32)
        sums = np.add.reduceat(all_ints, cum_ne)

        result = np.zeros(n, dtype=np.float32)
        result[ne_idx] = sums
        return result

    # ------------------------------------------------------------------
    # PASEF peak-picked MS/MS
    # ------------------------------------------------------------------

    def read_pasef_msms(
        self,
        precursor_list: list[int],
        sparse: bool = True,
    ) -> dict[int, tuple[npt.NDArray[np.float64], npt.NDArray[np.float32]]]:
        """Read peak-picked PASEF MS/MS spectra for a list of precursor IDs.

        Parameters
        ----------
        precursor_list : list of int
            Precursor IDs from the ``Precursors`` table.
        sparse : bool, optional
            Use the sparse (v2) algorithm (default True). Set False to use
            the dense (v2_2024) algorithm which may return more peaks.

        Returns
        -------
        dict
            Mapping of ``precursor_id`` → ``(mz_array, intensity_array)``.
        """
        precursors_arr = np.array(precursor_list, dtype=np.int64)
        result: dict[int, tuple[npt.NDArray[np.float64], npt.NDArray[np.float32]]] = {}

        @_MSMS_FUNCTOR
        def _cb(
            pid: int,
            n: int,
            mz_ptr: POINTER(c_double),  # type: ignore[valid-type]
            area_ptr: POINTER(c_float),  # type: ignore[valid-type]
        ) -> None:
            result[pid] = (
                np.array(mz_ptr[:n], dtype=np.float64),
                np.array(area_ptr[:n], dtype=np.float32),
            )

        fn = self._dll.tims_read_pasef_msms_v2 if sparse else self._dll.tims_read_pasef_msms_v2_2024
        ok = fn(
            self.handle,
            precursors_arr.ctypes.data_as(POINTER(c_int64)),
            len(precursor_list),
            _cb,
            None,
        )
        if ok == 0:
            _raise_last_error()
        return result

    def read_pasef_msms_for_frame(
        self,
        frame_id: int,
        sparse: bool = True,
    ) -> dict[int, tuple[npt.NDArray[np.float64], npt.NDArray[np.float32]]]:
        """Read all peak-picked PASEF MS/MS spectra for a single frame.

        Parameters
        ----------
        frame_id : int
            TDF frame ID.
        sparse : bool, optional
            Use sparse (v2) algorithm. Default True.

        Returns
        -------
        dict
            Mapping of ``precursor_id`` → ``(mz_array, intensity_array)``.
        """
        result: dict[int, tuple[npt.NDArray[np.float64], npt.NDArray[np.float32]]] = {}

        @_MSMS_FUNCTOR
        def _cb(
            pid: int,
            n: int,
            mz_ptr: POINTER(c_double),  # type: ignore[valid-type]
            area_ptr: POINTER(c_float),  # type: ignore[valid-type]
        ) -> None:
            result[pid] = (
                np.array(mz_ptr[:n], dtype=np.float64),
                np.array(area_ptr[:n], dtype=np.float32),
            )

        fn = (
            self._dll.tims_read_pasef_msms_for_frame_v2
            if sparse
            else self._dll.tims_read_pasef_msms_for_frame_v2_2024
        )
        ok = fn(self.handle, frame_id, _cb, None)
        if ok == 0:
            _raise_last_error()
        return result

    # ------------------------------------------------------------------
    # Frame-level centroid extraction
    # ------------------------------------------------------------------

    def extract_centroided_spectrum(
        self,
        frame_id: int,
        scan_begin: int,
        scan_end: int,
        peak_picker_resolution: float | None = None,
        dense: bool = True,
    ) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.float32]]:
        """Extract a centroided spectrum for a scan range within a frame.

        The SDK performs on-instrument-style peak picking across all
        selected mobility scans.

        Parameters
        ----------
        frame_id : int
            TDF frame ID.
        scan_begin : int
            First scan line (inclusive, 0-based).
        scan_end : int
            Last scan line (exclusive).
        peak_picker_resolution : float or None, optional
            Custom peak picker resolution parameter. None uses the default
            resolution setting built into the SDK.
        dense : bool, optional
            When True (default), use the dense (_v2) algorithm which returns
            more peaks. When False, use the sparse (_v3) algorithm.

        Returns
        -------
        tuple
            ``(mz_array, intensity_array)`` as float64 and float32.

        Raises
        ------
        RuntimeError
            If the SDK returns a failure code.
        """
        result: tuple[npt.NDArray[np.float64], npt.NDArray[np.float32]] | None = None

        @_MSMS_FUNCTOR
        def _cb(
            _: int,
            n: int,
            mz_ptr: POINTER(c_double),  # type: ignore[valid-type]
            area_ptr: POINTER(c_float),  # type: ignore[valid-type]
        ) -> None:
            nonlocal result
            result = (
                np.array(mz_ptr[:n], dtype=np.float64),
                np.array(area_ptr[:n], dtype=np.float32),
            )

        if peak_picker_resolution is None:
            fn = (
                self._dll.tims_extract_centroided_spectrum_for_frame_v2
                if dense
                else self._dll.tims_extract_centroided_spectrum_for_frame_v3
            )
            ok = fn(self.handle, frame_id, scan_begin, scan_end, _cb, None)
        else:
            fn = (
                self._dll.tims_extract_centroided_spectrum_for_frame_ext
                if dense
                else self._dll.tims_extract_centroided_spectrum_for_frame_ext_v3
            )
            ok = fn(
                self.handle,
                frame_id,
                scan_begin,
                scan_end,
                peak_picker_resolution,
                _cb,
                None,
            )

        if ok == 0:
            _raise_last_error()

        return (
            result
            if result is not None
            else (
                np.empty(0, dtype=np.float64),
                np.empty(0, dtype=np.float32),
            )
        )

    # ------------------------------------------------------------------
    # Frame-level profile extraction
    # ------------------------------------------------------------------

    def extract_profile_for_frame(
        self, frame_id: int, scan_begin: int, scan_end: int
    ) -> npt.NDArray[np.int32]:
        """Extract a quasi-profile intensity array for a scan range.

        Parameters
        ----------
        frame_id : int
            TDF frame ID.
        scan_begin : int
            First scan line (inclusive, 0-based).
        scan_end : int
            Last scan line (exclusive).

        Returns
        -------
        numpy.ndarray
            Profile intensity values (int32); length equals the number of
            TOF bins in the acquisition m/z range.
        """
        result: npt.NDArray[np.int32] | None = None

        @_MSMS_PROFILE_FUNCTOR
        def _cb(
            _: int,
            n: int,
            int_ptr: POINTER(c_int32),  # type: ignore[valid-type]
        ) -> None:
            nonlocal result
            result = np.array(int_ptr[:n], dtype=np.int32)

        ok = self._dll.tims_extract_profile_for_frame(
            self.handle, frame_id, scan_begin, scan_end, _cb, None
        )
        if ok == 0:
            _raise_last_error()
        return result if result is not None else np.empty(0, dtype=np.int32)

    # ------------------------------------------------------------------
    # Chromatogram extraction
    # ------------------------------------------------------------------

    def extract_chromatograms(
        self,
        jobs: Iterator[ChromatogramJob],
        trace_sink: object,
    ) -> None:
        """Extract multiple EIC/XIC chromatograms efficiently.

        Parameters
        ----------
        jobs : iterator of ChromatogramJob
            Chromatogram job descriptors produced in ascending
            ``time_begin`` order.
        trace_sink : callable
            Called for each extracted trace with arguments
            ``(job_id, frame_ids_array, values_array)``.

        Raises
        ------
        RuntimeError
            If the SDK returns a failure code.
        """

        @_CHROM_JOB_GEN
        def _gen(job_ptr: object, _: object) -> int:
            try:
                next_job = next(jobs)
                job_ptr[0] = next_job  # type: ignore[index]
                return 1
            except StopIteration:
                return 2

        @_CHROM_TRACE_SINK
        def _sink(
            job_id: int,
            n: int,
            frame_ids_ptr: POINTER(c_int64),  # type: ignore[valid-type]
            values_ptr: POINTER(c_uint64),  # type: ignore[valid-type]
            _: c_void_p,
        ) -> int:
            trace_sink(  # type: ignore[operator]
                job_id,
                np.array(frame_ids_ptr[:n], dtype=np.int64),
                np.array(values_ptr[:n], dtype=np.uint64),
            )
            return 1

        ok = self._dll.tims_extract_chromatograms(self.handle, _gen, _sink, 0)
        if ok == 0:
            _raise_last_error()


# ---------------------------------------------------------------------------
# TsfData class
# ---------------------------------------------------------------------------


class TsfData:
    """Typed wrapper around the Bruker TSF SDK for reading TSF datasets.

    Opens the SDK handle (binary data) and a SQLite connection
    (``analysis.tsf`` metadata) for a single ``.d`` directory.

    TSF files are produced by the timsTOF fleX instrument operating in
    TIMS-off mode.  There is no ion mobility data; spectra are read via
    ``tsf_read_line_spectrum_v2`` which returns m/z values directly.

    Parameters
    ----------
    analysis_directory : str
        Absolute path to the Bruker ``.d`` directory.
    use_recalibrated_state : bool, optional
        Use the on-disk recalibrated calibration state if available.
        Default is False.

    Raises
    ------
    ValueError
        If *analysis_directory* is not a string.
    RuntimeError
        If the SDK fails to open the dataset.
    """

    def __init__(
        self,
        analysis_directory: str,
        use_recalibrated_state: bool = False,
    ) -> None:
        if not isinstance(analysis_directory, str):
            raise ValueError("analysis_directory must be a str.")

        self._dll = _dll

        self.handle: int = self._dll.tsf_open(
            analysis_directory.encode("utf-8"),
            1 if use_recalibrated_state else 0,
        )

        if self.handle == 0:
            self._raise_last_error()

        self.conn: sqlite3.Connection = sqlite3.connect(
            os.path.join(analysis_directory, "analysis.tsf")
        )

    def close(self) -> None:
        """Close the SDK handle and SQLite connection."""
        if getattr(self, "handle", None):
            self._dll.tsf_close(self.handle)
            self.handle = 0
        if getattr(self, "conn", None):
            self.conn.close()
            self.conn = None  # type: ignore[assignment]

    def __enter__(self) -> "TsfData":
        """Return self for use as a context manager."""
        return self

    def __exit__(self, *_: object) -> None:
        """Close the SDK handle on context manager exit."""
        self.close()

    def __del__(self) -> None:
        """Ensure the SDK handle is closed when the object is garbage-collected."""
        self.close()

    def _raise_last_error(self) -> None:
        """Raise a RuntimeError containing the last TSF SDK error message."""
        n = self._dll.tsf_get_last_error_string(None, 0)
        buf = create_string_buffer(n)
        self._dll.tsf_get_last_error_string(buf, n)
        raise RuntimeError(buf.value.decode("utf-8", errors="replace"))

    def read_line_spectrum(
        self, frame_id: int
    ) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.float32]]:
        """Read a centroid line spectrum for a TSF frame.

        Calls ``tsf_read_line_spectrum_v2`` which returns m/z values
        directly (no index-to-mz conversion needed).

        Parameters
        ----------
        frame_id : int
            TSF frame ID.

        Returns
        -------
        tuple
            ``(mz_array, intensity_array)`` as float64 and float32.

        Raises
        ------
        RuntimeError
            If the SDK returns a failure code.
        """
        result: tuple[npt.NDArray[np.float64], npt.NDArray[np.float32]] | None = None

        @_MSMS_FUNCTOR
        def _cb(
            _fid: int,
            n: int,
            mz_ptr: POINTER(c_double),  # type: ignore[valid-type]
            area_ptr: POINTER(c_float),  # type: ignore[valid-type]
        ) -> None:
            nonlocal result
            result = (
                np.array(mz_ptr[:n], dtype=np.float64),
                np.array(area_ptr[:n], dtype=np.float32),
            )

        ok = self._dll.tsf_read_line_spectrum_v2(self.handle, frame_id, _cb, None)
        if ok == 0:
            self._raise_last_error()

        return (
            result
            if result is not None
            else (
                np.empty(0, dtype=np.float64),
                np.empty(0, dtype=np.float32),
            )
        )
