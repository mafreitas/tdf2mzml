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
