"""tdf2mzml — Convert Bruker mass spectrometry data to indexed mzML.

Supports three Bruker binary formats:

- **TDF** — timsTOF PASEF (DDA and DIA) with trapped ion mobility.
- **TSF** — timsTOF fleX / TIMS-off (no ion mobility).
- **BAF** — maXis, impact, and other Bruker QTOF instruments.

Output is fully indexed mzML 1.1.0 with byte-offset spectrum index,
enabling random-access by downstream tools (OpenMS, Skyline, etc.).
"""

__version__ = "0.5.0"
__author__ = "Michael A. Freitas"
__license__ = "BSD 4-Clause License"
