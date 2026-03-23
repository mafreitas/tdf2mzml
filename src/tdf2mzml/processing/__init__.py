"""Data transformation submodule: MS1, MS2, and ion mobility processing.

This package contains pure data-transform functions that bridge the gap
between raw SDK output (index/intensity arrays, scan data) and the typed
domain objects written to mzML (SpectrumArrays, PrecursorInfo).

Modules
-------
ms1
    MS1 extraction: centroid, profile, raw (vectorised merge), IM-resolved.
ms2
    PASEF DDA and DIA MS2 spectrum extraction with precursor metadata.
mobility
    Ion mobility calculations: intensity-weighted mean 1/K0, per-scan TIC.
"""
