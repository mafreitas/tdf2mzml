"""TsfData.read_line_spectrum buffer logic, with a fake SDK (no Bruker library or data needed)."""

from __future__ import annotations

import ctypes

import numpy as np
import pytest

try:
    from tdf2mzml.io.timsdata import TsfData
except OSError as exc:  # the Bruker SDK library cannot be loaded on this platform
    pytest.skip(f"Bruker SDK not available: {exc}", allow_module_level=True)


class _FakeDll:
    """Stand-in for the SDK: returns *index* values 0..n-1 and a fixed conversion to m/z."""

    def __init__(self, n_peaks: int, error: bool = False) -> None:
        self.n_peaks = n_peaks
        self.error = error
        self.read_lengths: list[int] = []

    def tsf_read_line_spectrum_v2(
        self, handle: int, frame_id: int, index_ptr: object, intensity_ptr: object, length: int
    ) -> int:
        self.read_lengths.append(length)
        if self.error:
            return -1
        for i in range(min(length, self.n_peaks)):  # an incomplete result when length is too small
            index_ptr[i] = float(i)  # type: ignore[index]
            intensity_ptr[i] = 10.0 + i  # type: ignore[index]
        return self.n_peaks

    def tsf_index_to_mz(
        self, handle: int, frame_id: int, in_ptr: object, out_ptr: object, count: int
    ) -> int:
        for i in range(count):
            out_ptr[i] = 100.0 + 2.0 * in_ptr[i]  # type: ignore[index]
        return 1

    def tsf_close(self, handle: int) -> None:
        return None

    def tsf_get_last_error_string(self, buf: object, length: int) -> int:
        message = b"sdk failed"
        if buf is not None:
            ctypes.memmove(buf, message + b"\0", len(message) + 1)  # type: ignore[arg-type]
        return len(message) + 1


def _tsf(dll: _FakeDll, buffer_size: int = 4) -> TsfData:
    tsf = TsfData.__new__(TsfData)
    tsf._dll = dll  # type: ignore[assignment]
    tsf.handle = 1
    tsf._line_buffer_size = buffer_size
    return tsf


def test_index_values_are_converted_to_mz() -> None:
    """The SDK returns index values; they must be converted to m/z."""
    mz, intensity = _tsf(_FakeDll(3)).read_line_spectrum(7)

    assert mz.tolist() == [100.0, 102.0, 104.0]
    assert intensity.tolist() == [10.0, 11.0, 12.0]
    assert mz.dtype == np.float64
    assert intensity.dtype == np.float32


def test_buffer_grows_and_is_read_again() -> None:
    """A result that is longer than the buffer is incomplete, so it is read again."""
    dll = _FakeDll(10)
    tsf = _tsf(dll, buffer_size=4)

    mz, intensity = tsf.read_line_spectrum(7)

    assert len(mz) == len(intensity) == 10
    assert mz[-1] == 118.0
    assert dll.read_lengths == [4, 10]  # too small once, then the length the SDK asked for
    assert tsf._line_buffer_size == 10  # the next frame starts with the larger buffer


def test_frame_without_peaks_gives_empty_arrays() -> None:
    """A length of 0 is an empty frame, not an error."""
    dll = _FakeDll(0)

    mz, intensity = _tsf(dll).read_line_spectrum(7)

    assert len(mz) == 0
    assert len(intensity) == 0
    assert dll.read_lengths == [4]


def test_sdk_error_is_raised() -> None:
    """A length of -1 is an SDK error and carries the SDK message."""
    with pytest.raises(RuntimeError, match="sdk failed"):
        _tsf(_FakeDll(3, error=True)).read_line_spectrum(7)


def test_binding_matches_the_sdk_header() -> None:
    """Guards the access violation: the SDK takes buffers, not a callback (tsfdata.h)."""
    from tdf2mzml.io import timsdata

    fn = timsdata._dll.tsf_read_line_spectrum_v2
    assert len(fn.argtypes) == 5
    assert fn.argtypes[2] == ctypes.POINTER(ctypes.c_double)
    assert fn.argtypes[3] == ctypes.POINTER(ctypes.c_float)
    assert fn.restype is ctypes.c_int32
