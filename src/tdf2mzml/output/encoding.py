"""Binary array encoding for mzML: base64 + optional zlib compression."""

import base64
import zlib
from typing import Literal

import numpy as np
import numpy.typing as npt


def encode_array(
    array: npt.NDArray[np.float64 | np.float32 | np.int32],
    compression: Literal["none", "zlib"] = "none",
) -> str:
    """Encode a numpy array to a base64 string for embedding in mzML.

    Parameters
    ----------
    array : numpy.ndarray
        The array to encode.  dtype is preserved; no implicit conversion.
    compression : {"none", "zlib"}
        Whether to apply zlib compression before base64 encoding.

    Returns
    -------
    str
        Base64-encoded string (ASCII).
    """
    raw: bytes = array.tobytes()
    if compression == "zlib":
        raw = zlib.compress(raw)
    return base64.b64encode(raw).decode("ascii")


def mz_array_params(compression: Literal["none", "zlib"]) -> list[str]:
    """Return CV param names for an m/z binary data array.

    Parameters
    ----------
    compression : {"none", "zlib"}
        Compression type.

    Returns
    -------
    list of str
        CV term names to include in the ``<binaryDataArray>`` element.
    """
    params = ["m/z array", "64-bit float"]
    params.append("zlib compression" if compression == "zlib" else "no compression")
    return params


def intensity_array_params(compression: Literal["none", "zlib"]) -> list[str]:
    """Return CV param names for an intensity binary data array.

    Parameters
    ----------
    compression : {"none", "zlib"}
        Compression type.

    Returns
    -------
    list of str
        CV term names to include in the ``<binaryDataArray>`` element.
    """
    params = ["intensity array", "32-bit float"]
    params.append("zlib compression" if compression == "zlib" else "no compression")
    return params


def ion_mobility_array_params(compression: Literal["none", "zlib"]) -> list[str]:
    """Return CV param names for an ion mobility binary data array.

    Parameters
    ----------
    compression : {"none", "zlib"}
        Compression type.

    Returns
    -------
    list of str
        CV term names to include in the ``<binaryDataArray>`` element.
    """
    params = ["mean inverse reduced ion mobility array", "64-bit float"]
    params.append("zlib compression" if compression == "zlib" else "no compression")
    return params
