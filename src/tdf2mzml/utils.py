"""Utility helpers: timing decorator, SHA-1 checksum, progress logging.

These are pure infrastructure with no domain knowledge of TDF or mzML.
"""

import hashlib
import logging
import time
from collections.abc import Callable
from functools import wraps
from typing import ParamSpec, TypeVar

logger = logging.getLogger(__name__)

_P = ParamSpec("_P")
_R = TypeVar("_R")

# ---------------------------------------------------------------------------
# Timing decorator
# ---------------------------------------------------------------------------


def timing(func: Callable[_P, _R]) -> Callable[_P, _R]:
    """Log the wall-clock execution time of a function.

    Parameters
    ----------
    func : callable
        The function to wrap.

    Returns
    -------
    callable
        Wrapped function that logs execution time at INFO level.

    Examples
    --------
    >>> @timing
    ... def slow():
    ...     time.sleep(0.1)
    >>> slow()   # logs: "slow function took 0.100 s"
    """

    @wraps(func)
    def wrapper(*args: _P.args, **kwargs: _P.kwargs) -> _R:
        t0 = time.perf_counter()
        result = func(*args, **kwargs)
        elapsed = time.perf_counter() - t0
        logger.info("%s took %.3f s", func.__name__, elapsed)
        return result

    return wrapper


# ---------------------------------------------------------------------------
# SHA-1 checksum
# ---------------------------------------------------------------------------


def sha1_checksum(path: str, block_size: int = 65_536) -> str:
    """Compute the SHA-1 hex digest of a file.

    Parameters
    ----------
    path : str
        Absolute or relative path to the file.
    block_size : int, optional
        Read buffer size in bytes. Default is 65 536 (64 KiB).

    Returns
    -------
    str
        Lowercase hexadecimal SHA-1 digest string (40 characters).

    Raises
    ------
    OSError
        If the file cannot be opened or read.
    """
    hasher = hashlib.sha1()
    with open(path, "rb") as fh:
        buf = fh.read(block_size)
        while buf:
            hasher.update(buf)
            buf = fh.read(block_size)
    return hasher.hexdigest()


# ---------------------------------------------------------------------------
# Progress logger
# ---------------------------------------------------------------------------


class ProgressLogger:
    """Log periodic progress messages during spectrum writing.

    Tracks MS1 and MS2 counts separately so each progress line shows
    the breakdown by MS level.

    Parameters
    ----------
    total : int
        Total number of spectra to be written.
    interval : int, optional
        Log a message every *interval* spectra. Default is 1 000.

    Examples
    --------
    >>> progress = ProgressLogger(total=5000)
    >>> for i in range(5000):
    ...     progress.update(ms_level=1 if i % 10 == 0 else 2)
    """

    def __init__(self, total: int, interval: int = 1_000) -> None:
        self.total = total
        self.interval = interval
        self._count = 0
        self._ms1 = 0
        self._ms2 = 0
        self._t0 = time.perf_counter()

    def update(self, ms_level: int = 1) -> None:
        """Increment the counter and emit a log message every *interval* spectra.

        Parameters
        ----------
        ms_level : int
            MS level of the spectrum just written (1 or 2).
        """
        self._count += 1
        if ms_level == 1:
            self._ms1 += 1
        else:
            self._ms2 += 1

        if self._count % self.interval == 0:
            elapsed = time.perf_counter() - self._t0
            logger.info(
                "MS1: %d  MS2: %d  |  total %d / %d  (%.1f s)",
                self._ms1,
                self._ms2,
                self._count,
                self.total,
                elapsed,
            )
            self._t0 = time.perf_counter()
