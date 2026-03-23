"""Acquisition metadata models populated from the TDF GlobalMetadata table."""

from typing import Annotated

from pydantic import BaseModel, Field


class DiaWindow(BaseModel):
    """A single DIA isolation window definition.

    Parameters
    ----------
    window_group : int
        Window group identifier (from ``DiaFrameMsMsWindowGroups``).
    scan_num_begin : int
        First scan line (mobility index) for this window (inclusive).
    scan_num_end : int
        Last scan line for this window (exclusive).
    isolation_mz : float
        Centre m/z of the isolation window (Da).
    isolation_width : float
        Total width of the isolation window (Da).
    collision_energy : float
        Collision energy applied in this window (eV).
    """

    model_config = {"frozen": True}

    window_group: int
    scan_num_begin: int
    scan_num_end: int
    isolation_mz: float
    isolation_width: float
    collision_energy: float


class AcquisitionMetadata(BaseModel):
    """All metadata extracted from a TDF file.

    Populated once at startup by :class:`~tdf2mzml.io.reader.TdfReader`
    and passed read-only to all downstream components.

    Parameters
    ----------
    schema_type : str
        TDF schema type string (e.g. ``"TDF"``).
    schema_version_major : int
        Major schema version number.
    schema_version_minor : int
        Minor schema version number.
    acq_software : str
        Acquisition software name (e.g. ``"Bruker otofControl"``).
    acq_software_version : str
        Acquisition software version string.
    acq_firmware_version : str
        Acquisition firmware version string.
    acq_software_vendor : str
        Acquisition software vendor (e.g. ``"Bruker"``).
    acq_date_time : str
        ISO 8601 acquisition timestamp.
    instrument_name : str
        Instrument model name (e.g. ``"timsTOF Pro"``).
    instrument_family : str
        Instrument family code from GlobalMetadata.
    instrument_serial_number : str
        Instrument serial number.
    instrument_revision : int
        Instrument hardware revision number.
    instrument_source_type : int
        Source type code from GlobalMetadata (e.g. 11 = nanoelectrospray).
    instrument_vendor : str
        Instrument vendor (e.g. ``"Bruker"``).
    operator_name : str
        Operator name recorded in the TDF.
    sample_name : str
        Sample name recorded in the TDF.
    description : str
        Free-text sample description from the TDF.
    method_name : str
        Acquisition method name.
    analysis_id : str
        Unique UUID for this acquisition (``AnalysisId`` in GlobalMetadata).
    closed_properly : bool
        True when the acquisition was closed cleanly; False may indicate
        truncated or corrupt data.
    mz_acq_range_lower : float
        Lower m/z acquisition range boundary (Da).
    mz_acq_range_upper : float
        Upper m/z acquisition range boundary (Da).
    one_over_k0_range_lower : float
        Lower 1/K0 acquisition range boundary (V·s/cm²).
    one_over_k0_range_upper : float
        Upper 1/K0 acquisition range boundary (V·s/cm²).
    frame_count : int
        Total number of frames in the dataset.
    ms1_spectra_count : int
        Number of MS1 (MsMsType=0) frames.
    ms2_dda_count : int
        Number of PASEF DDA precursors (from the ``Precursors`` table).
    ms2_dia_count : int
        Number of PASEF DIA frames (MsMsType=9).
    total_spectra : int
        Total number of spectra that will be written to the output.
    has_pasef_dda : bool
        True when at least one MsMsType=8 frame is present.
    has_pasef_dia : bool
        True when at least one MsMsType=9 frame is present.
    dia_windows : list[DiaWindow]
        All DIA isolation window definitions; empty for DDA datasets.
    """

    model_config = {"frozen": True}

    # Schema
    schema_type: str
    schema_version_major: int
    schema_version_minor: int
    # Software & firmware
    acq_software: str
    acq_software_version: str
    acq_firmware_version: str
    acq_software_vendor: str
    acq_date_time: str
    # Instrument
    instrument_name: str
    instrument_family: str
    instrument_serial_number: str
    instrument_revision: int
    instrument_source_type: int
    instrument_vendor: str
    operator_name: str
    sample_name: str
    description: str
    method_name: str
    analysis_id: str
    closed_properly: bool
    # Acquisition ranges
    mz_acq_range_lower: float
    mz_acq_range_upper: float
    one_over_k0_range_lower: float
    one_over_k0_range_upper: float
    # Counts
    frame_count: Annotated[int, Field(ge=0)]
    ms1_spectra_count: Annotated[int, Field(ge=0)]
    ms2_dda_count: Annotated[int, Field(ge=0)]
    ms2_dia_count: Annotated[int, Field(ge=0)]
    total_spectra: Annotated[int, Field(ge=0)]
    # Flags
    has_pasef_dda: bool
    has_pasef_dia: bool
    # DIA windows
    dia_windows: list[DiaWindow] = Field(default_factory=list)
