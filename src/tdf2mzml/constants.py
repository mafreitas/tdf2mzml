"""Project-wide constants: SQL keys, CV accessions, and defaults.

All magic strings and numbers are centralised here so that callers
reference names rather than raw literals.
"""

# ---------------------------------------------------------------------------
# Bruker SDK
# ---------------------------------------------------------------------------

SDK_VERSION: str = "2.8.7"
"""Version of the bundled Bruker TIMS SDK shared library."""

TIMS_SDK_SOFTWARE_ID: str = "TIMS_SDK"
"""Software list ID used in the mzML softwareList element."""

MAX_FRAME_BUFFER_SIZE: int = 16_777_216
"""Hard upper limit (bytes) for the raw scan read buffer in TimsData."""

# ---------------------------------------------------------------------------
# TDF GlobalMetadata keys
# ---------------------------------------------------------------------------

META_SCHEMA_TYPE: str = "SchemaType"
META_SCHEMA_VERSION_MAJOR: str = "SchemaVersionMajor"
META_SCHEMA_VERSION_MINOR: str = "SchemaVersionMinor"
META_ACQ_SOFTWARE: str = "AcquisitionSoftware"
META_ACQ_SOFTWARE_VERSION: str = "AcquisitionSoftwareVersion"
META_ACQ_DATETIME: str = "AcquisitionDateTime"
META_ACQ_FIRMWARE_VERSION: str = "AcquisitionFirmwareVersion"
META_INSTRUMENT_NAME: str = "InstrumentName"
META_INSTRUMENT_FAMILY: str = "InstrumentFamily"
META_INSTRUMENT_REVISION: str = "InstrumentRevision"
META_INSTRUMENT_SERIAL: str = "InstrumentSerialNumber"
META_INSTRUMENT_SOURCE_TYPE: str = "InstrumentSourceType"
META_OPERATOR_NAME: str = "OperatorName"
META_SAMPLE_NAME: str = "SampleName"
META_METHOD_NAME: str = "MethodName"
META_MZ_RANGE_LOWER: str = "MzAcqRangeLower"
META_MZ_RANGE_UPPER: str = "MzAcqRangeUpper"
META_OOK0_RANGE_LOWER: str = "OneOverK0AcqRangeLower"
META_OOK0_RANGE_UPPER: str = "OneOverK0AcqRangeUpper"
META_MAX_PEAKS_PER_SCAN: str = "MaxNumPeaksPerScan"
META_TIMS_COMPRESSION_TYPE: str = "TimsCompressionType"
META_DIGITIZER_NUM_SAMPLES: str = "DigitizerNumSamples"
META_DESCRIPTION: str = "Description"
META_ANALYSIS_ID: str = "AnalysisId"
META_CLOSED_PROPERLY: str = "ClosedProperly"
META_ACQ_SOFTWARE_VENDOR: str = "AcquisitionSoftwareVendor"
META_INSTRUMENT_VENDOR: str = "InstrumentVendor"

# ---------------------------------------------------------------------------
# TDF Frame MsMsType values
# ---------------------------------------------------------------------------

MSMS_TYPE_MS1: int = 0
"""Standard MS1 / precursor frame."""

MSMS_TYPE_PASEF_DDA: int = 8
"""PASEF DDA MS/MS frame."""

MSMS_TYPE_PASEF_DIA: int = 9
"""PASEF DIA MS/MS frame."""

# ---------------------------------------------------------------------------
# Precursor table columns (order matters — matches SQL SELECT)
# ---------------------------------------------------------------------------

PRECURSOR_COLUMNS: list[str] = [
    "Id",
    "LargestPeakMz",
    "AverageMz",
    "MonoisotopicMz",
    "ScanNumber",
    "Charge",
    "Intensity",
    "Parent",
]

PASEF_FRAME_COLUMNS: list[str] = [
    "IsolationMz",
    "CollisionEnergy",
    "IsolationWidth",
]

# ---------------------------------------------------------------------------
# mzML CV accessions (PSI-MS ontology)
# ---------------------------------------------------------------------------

# Spectrum types
CV_MS1_SPECTRUM: str = "MS:1000579"          # MS1 spectrum
CV_MSN_SPECTRUM: str = "MS:1000580"          # MSn spectrum
CV_CENTROID_SPECTRUM: str = "MS:1000127"     # centroid spectrum
CV_PROFILE_SPECTRUM: str = "MS:1000128"      # profile spectrum
CV_MS_LEVEL: str = "MS:1000511"              # ms level
CV_POSITIVE_SCAN: str = "MS:1000130"         # positive scan
CV_NEGATIVE_SCAN: str = "MS:1000129"         # negative scan

# Scan params
CV_SCAN_START_TIME: str = "MS:1000016"       # scan start time
CV_FILTER_STRING: str = "MS:1000512"         # filter string (unused)
CV_TOTAL_ION_CURRENT: str = "MS:1000285"     # total ion current
CV_BASE_PEAK_MZ: str = "MS:1000504"          # base peak m/z
CV_BASE_PEAK_INTENSITY: str = "MS:1000505"   # base peak intensity
CV_NO_COMBINATION: str = "MS:1000795"        # no combination
CV_SCAN_WINDOW_LOWER: str = "MS:1000501"     # scan window lower limit
CV_SCAN_WINDOW_UPPER: str = "MS:1000500"     # scan window upper limit

# Arrays
CV_MZ_ARRAY: str = "MS:1000514"             # m/z array
CV_INTENSITY_ARRAY: str = "MS:1000515"      # intensity array
CV_ION_MOBILITY_ARRAY: str = "MS:1002816"   # mean inverse reduced ion mobility array

# Ion mobility
CV_INVERSE_REDUCED_ION_MOBILITY: str = "MS:1002814"   # inverse reduced ion mobility (1/K0)
CV_MEAN_INVERSE_REDUCED_ION_MOBILITY: str = "MS:1003008"  # mean inverse reduced ion mobility
CV_IM_LOWER_LIMIT: str = "MS:1002476"   # inverse reduced ion mobility lower limit
CV_IM_UPPER_LIMIT: str = "MS:1002477"   # inverse reduced ion mobility upper limit

# Encoding
CV_64BIT_FLOAT: str = "MS:1000523"          # 64-bit float
CV_32BIT_FLOAT: str = "MS:1000521"          # 32-bit float (intensity)
CV_ZLIB_COMPRESSION: str = "MS:1000574"     # zlib compression
CV_NO_COMPRESSION: str = "MS:1000576"       # no compression

# Instrument / source
CV_BRUKER_INSTRUMENT: str = "MS:1000122"    # Bruker Daltonics instrument model
CV_NANOSPRAY_INLET: str = "MS:1000485"      # nanospray inlet
CV_QUADRUPOLE: str = "MS:1000081"           # quadrupole
CV_TOF_ANALYZER: str = "MS:1000084"         # time-of-flight
CV_MCP_DETECTOR: str = "MS:1000114"         # microchannel plate detector
CV_PHOTOMULTIPLIER: str = "MS:1000116"      # photomultiplier
CV_INSTRUMENT_SERIAL: str = "MS:1000529"    # instrument serial number
CV_ESI: str = "MS:1000073"                  # electrospray ionization

# File format
CV_BRUKER_TDF_FORMAT: str = "MS:1002817"    # Bruker TDF format
CV_BRUKER_TDF_NATIVE_ID: str = "MS:1002818" # Bruker TDF nativeID format
CV_SHA1: str = "MS:1000569"                  # SHA-1

# Software
CV_BRUKER_SOFTWARE: str = "MS:1000692"      # Bruker software
CV_CUSTOM_SOFTWARE: str = "MS:1000799"      # custom unreleased software tool
CV_MICROTOFCONTROL: str = "MS:1000726"      # micrOTOFcontrol

# Activation
CV_CID: str = "MS:1000133"                  # collision-induced dissociation
CV_COLLISION_ENERGY: str = "MS:1000045"     # collision energy

# Precursor / isolation
CV_SELECTED_ION_MZ: str = "MS:1000744"      # selected ion m/z
CV_CHARGE_STATE: str = "MS:1000041"         # charge state
CV_ISOLATION_WINDOW_TARGET: str = "MS:1000827"  # isolation window target m/z
CV_ISOLATION_WINDOW_LOWER: str = "MS:1000828"   # isolation window lower offset
CV_ISOLATION_WINDOW_UPPER: str = "MS:1000829"   # isolation window upper offset

# Data processing
CV_CONVERSION_TO_MZML: str = "MS:1000544"   # Conversion to mzML

# ---------------------------------------------------------------------------
# Unit CV accessions (for unitCvRef + unitAccession + unitName triplets)
# ---------------------------------------------------------------------------

UNIT_MZ: str = "MS:1000040"                 # m/z
UNIT_MINUTE: str = "UO:0000031"             # minute
UNIT_ELECTRONVOLT: str = "UO:0000266"       # electronvolt
UNIT_COUNTS: str = "MS:1000131"             # number of detector counts
UNIT_VSCC: str = "MS:1002814"               # volt-second per square centimeter

# ---------------------------------------------------------------------------
# mzML namespace / schema
# ---------------------------------------------------------------------------

MZML_NAMESPACE: str = "http://psi.hupo.org/ms/mzml"
MZML_SCHEMA_LOCATION: str = (
    "http://psi.hupo.org/ms/mzml "
    "http://psidev.info/files/ms/mzML/xsd/mzML1.1.0.xsd"
)
MZML_VERSION: str = "1.1.0"

CV_MS_URI: str = "https://raw.githubusercontent.com/HUPO-PSI/psi-ms-CV/master/psi-ms.obo"
CV_UO_URI: str = "https://raw.githubusercontent.com/bio-ontology-research-group/unit-ontology/master/unit.obo"

# ---------------------------------------------------------------------------
# Defaults (mirrors CLI defaults)
# ---------------------------------------------------------------------------

DEFAULT_MS1_TYPE: str = "centroid"
DEFAULT_MS1_THRESHOLD: float = 100.0
DEFAULT_MS2_THRESHOLD: float = 10.0
DEFAULT_MS2_NLARGEST: int = -1
DEFAULT_COMPRESSION: str = "none"
DEFAULT_ION_MOBILITY_MODE: str = "mean"
DEFAULT_PRECISION: float = 10.0
DEFAULT_START_FRAME: int = -1
DEFAULT_END_FRAME: int = -1
