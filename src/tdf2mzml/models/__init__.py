"""Pydantic domain models for tdf2mzml.

Re-exports all public model classes for convenient import::

    from tdf2mzml.models import ConversionConfig, AcquisitionMetadata
"""

from tdf2mzml.models.config import ConversionConfig
from tdf2mzml.models.metadata import AcquisitionMetadata, DiaWindow
from tdf2mzml.models.spectrum import PrecursorInfo, PrecursorRow, SpectrumArrays

__all__ = [
    "AcquisitionMetadata",
    "ConversionConfig",
    "DiaWindow",
    "PrecursorInfo",
    "PrecursorRow",
    "SpectrumArrays",
]
