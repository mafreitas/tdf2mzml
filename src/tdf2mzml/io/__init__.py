"""I/O submodule: SDK wrappers and TDF/TSF/BAF readers.

The Bruker readers depend on the platform-specific ``libtimsdata`` SDK,
which is unavailable on macOS. Re-exports are wrapped in a try/except so
SDK-free helpers (e.g. :mod:`tdf2mzml.io._sql`) remain importable on
development machines that lack the shared library.
"""

try:
    from tdf2mzml.io.baf_reader import BafReader
    from tdf2mzml.io.reader import TdfReader
    from tdf2mzml.io.tsf_reader import TsfReader

    __all__ = ["BafReader", "TdfReader", "TsfReader"]
except OSError:
    __all__ = []
