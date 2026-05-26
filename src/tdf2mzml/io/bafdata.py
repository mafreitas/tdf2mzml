"""Low-level ctypes wrapper around libbaf2sql_c.so / baf2sql_c.dll.

Provides SQLite cache generation and binary array I/O for Bruker BAF files.
The Bruker BAF format stores mass spectrometry data in a proprietary binary
container (``analysis.baf``) with optional companion files (``_xtr``, ``_idx``).
The ``libbaf2sql_c`` library generates an SQLite cache that exposes metadata
(``Spectra``, ``AcquisitionKeys``, ``Steps``, ``Variables``, ``Properties``)
and provides binary array read access for m/z and intensity data.

The library is loaded once per process and its function signatures are
configured on first use.  All SDK functions follow a two-call pattern:
call once with NULL/0 to get the required buffer size, then call again
with a buffer of that size.
"""

from __future__ import annotations

import ctypes
import sqlite3
from pathlib import Path

import numpy as np
import numpy.typing as npt

# ---------------------------------------------------------------------------
# Library loading
# ---------------------------------------------------------------------------

_LIBS_DIR = Path(__file__).parent.parent / "libs"

_LIB_CANDIDATES = [
    _LIBS_DIR / "libbaf2sql_c.so",  # Linux
    _LIBS_DIR / "baf2sql_c.dll",  # Windows 64-bit
]

_lib: ctypes.CDLL | None = None


def _load_library() -> ctypes.CDLL:
    """Load the first available BAF SDK shared library from the libs directory."""
    for candidate in _LIB_CANDIDATES:
        if candidate.exists():
            return ctypes.cdll.LoadLibrary(str(candidate))
    raise RuntimeError(
        "libbaf2sql_c not found; expected one of: " + ", ".join(str(p) for p in _LIB_CANDIDATES)
    )


def _configure_signatures(lib: ctypes.CDLL) -> None:
    """Set ctypes argtypes/restype for each exported SDK function."""
    # baf2sql_get_sqlite_cache_filename_v2(buf, buf_len, baf_path, ignore_calib)
    # Returns required buffer length; 0 on error.
    lib.baf2sql_get_sqlite_cache_filename_v2.argtypes = [
        ctypes.c_char_p,
        ctypes.c_uint32,
        ctypes.c_char_p,
        ctypes.c_int,
    ]
    lib.baf2sql_get_sqlite_cache_filename_v2.restype = ctypes.c_uint32

    # baf2sql_array_open_storage(use_raw_calibration, baf_path) → handle
    lib.baf2sql_array_open_storage.argtypes = [ctypes.c_int, ctypes.c_char_p]
    lib.baf2sql_array_open_storage.restype = ctypes.c_uint64

    lib.baf2sql_array_close_storage.argtypes = [ctypes.c_uint64]
    lib.baf2sql_array_close_storage.restype = None

    lib.baf2sql_get_last_error_string.argtypes = [ctypes.c_char_p, ctypes.c_uint32]
    lib.baf2sql_get_last_error_string.restype = ctypes.c_uint32

    lib.baf2sql_array_get_num_elements.argtypes = [
        ctypes.c_uint64,
        ctypes.c_uint64,
        ctypes.POINTER(ctypes.c_uint64),
    ]
    lib.baf2sql_array_get_num_elements.restype = ctypes.c_int

    lib.baf2sql_array_read_double.argtypes = [
        ctypes.c_uint64,
        ctypes.c_uint64,
        ctypes.POINTER(ctypes.c_double),
    ]
    lib.baf2sql_array_read_double.restype = ctypes.c_int


def _get_lib() -> ctypes.CDLL:
    """Return the singleton BAF SDK library handle, loading it on first call."""
    global _lib
    if _lib is None:
        _lib = _load_library()
        _configure_signatures(_lib)
    return _lib


def _last_error(lib: ctypes.CDLL) -> str:
    """Retrieve the last error message from the BAF SDK (two-call pattern)."""
    n = lib.baf2sql_get_last_error_string(None, 0)
    buf = ctypes.create_string_buffer(n)
    lib.baf2sql_get_last_error_string(buf, n)
    return buf.value.decode("utf-8", errors="replace")


# ---------------------------------------------------------------------------
# BafData
# ---------------------------------------------------------------------------


class BafData:
    """Thin wrapper around libbaf2sql_c providing SQLite + binary array I/O.

    Parameters
    ----------
    baf_path : Path
        Path to the ``analysis.baf`` file (not the ``.d`` directory).
    raw_calibration : bool, optional
        If True, returns raw (uncalibrated) m/z data. Default False uses
        the most recent calibration state.

    Examples
    --------
    >>> baf = BafData(Path("sample.d/analysis.baf"))
    >>> mz = baf.read_array_double(mz_id)
    >>> baf.close()
    """

    def __init__(self, baf_path: Path, raw_calibration: bool = False) -> None:
        self._lib = _get_lib()
        baf_bytes = str(baf_path).encode("utf-8")

        # Two-call pattern: first call with NULL buffer to get required length,
        # second call with a buffer of that size to retrieve the cache path.
        n = self._lib.baf2sql_get_sqlite_cache_filename_v2(None, 0, baf_bytes, 0)
        if n == 0:
            raise RuntimeError(
                f"baf2sql_get_sqlite_cache_filename_v2 failed: {_last_error(self._lib)}"
            )
        buf = ctypes.create_string_buffer(n)
        self._lib.baf2sql_get_sqlite_cache_filename_v2(buf, n, baf_bytes, 0)
        sqlite_path = buf.value.decode("utf-8")

        self.conn: sqlite3.Connection = sqlite3.connect(sqlite_path)

        # Open binary storage handle
        self._handle: int = self._lib.baf2sql_array_open_storage(
            1 if raw_calibration else 0, baf_bytes
        )
        if self._handle == 0:
            self.conn.close()
            raise RuntimeError(f"baf2sql_array_open_storage failed: {_last_error(self._lib)}")

    def close(self) -> None:
        """Release the binary storage handle and close the SQLite connection."""
        if self._handle:
            self._lib.baf2sql_array_close_storage(self._handle)
            self._handle = 0
        self.conn.close()

    def read_array_double(self, array_id: int) -> npt.NDArray[np.float64]:
        """Read a binary array from the BAF file as float64.

        Parameters
        ----------
        array_id : int
            Opaque integer ID from a Spectra table column (e.g. LineMzId).

        Returns
        -------
        numpy.ndarray
            Array of float64 values; empty if the array has zero elements.

        Raises
        ------
        RuntimeError
            If the SDK call fails.
        """
        n = ctypes.c_uint64(0)
        if not self._lib.baf2sql_array_get_num_elements(self._handle, array_id, ctypes.byref(n)):
            raise RuntimeError(f"baf2sql_array_get_num_elements failed: {_last_error(self._lib)}")
        if n.value == 0:
            return np.empty(0, dtype=np.float64)
        out = np.empty(n.value, dtype=np.float64)
        if not self._lib.baf2sql_array_read_double(
            self._handle,
            array_id,
            out.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
        ):
            raise RuntimeError(f"baf2sql_array_read_double failed: {_last_error(self._lib)}")
        return out
