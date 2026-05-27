"""tdf2mzml — Convert Bruker mass spectrometry data to indexed mzML.

Supports three Bruker binary formats:

- **TDF** — timsTOF PASEF (DDA and DIA) with trapped ion mobility.
- **TSF** — timsTOF fleX / TIMS-off (no ion mobility).
- **BAF** — maXis, impact, and other Bruker QTOF instruments.

Output is fully indexed mzML 1.1.0 with byte-offset spectrum index,
enabling random-access by downstream tools (OpenMS, Skyline, etc.).
"""

__version__ = "0.7.0"
__author__ = "Michael A. Freitas"
__license__ = "BSD 4-Clause License"

# Bundled third-party SDK versions — surfaced in CLI --version per
# Bruker EULA §4.4 "About box" attribution requirement.
__bruker_tdf_sdk_version__ = "3.3.6.2"
__bruker_baf2sql_version__ = "2.9.0"


def _version_text() -> str:
    """Compose the multi-line --version string.

    Includes Bruker SDK copyright notices required by the TDF SDK EULA §4.4
    and the Baf2Sql EULA equivalent. Defined here (not in cli.py) so that
    callers can import it without triggering the SDK ctypes loader, which
    would fail on macOS or any platform without a bundled Bruker library.

    Returns
    -------
    str
        Multi-line version banner with project + Bruker copyright.
    """
    return (
        f"tdf2mzml {__version__}\n"
        f"Copyright (c) 2020-2026 Michael A. Freitas, The Ohio State University.\n"
        f"Licensed under the BSD 4-Clause License.\n"
        f"\n"
        f"Bundles Bruker TDF SDK {__bruker_tdf_sdk_version__} and "
        f"Bruker Baf2Sql {__bruker_baf2sql_version__}\n"
        f"Copyright (c) Bruker Daltonics GmbH & Co. KG. All rights reserved.\n"
        f"Used under the Bruker Software License Agreements.\n"
        f"See NOTICE and tdf2mzml/libs/THIRD-PARTY-LICENSE-README.txt for details."
    )
