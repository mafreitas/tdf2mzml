"""Low-level XML string builders for mzML elements.

These functions produce raw XML strings (bytes) and track byte offsets for
the indexed mzML ``<index>`` section.  Using direct string construction
(rather than ElementTree) gives us precise byte-level control needed for
the offset index.

All public functions return ``bytes`` to be written directly to the output
file opened in binary mode.
"""

from __future__ import annotations

import textwrap
from typing import Literal
from xml.sax.saxutils import escape as _xml_escape, quoteattr as _xml_quoteattr

import numpy as np
import numpy.typing as npt

from tdf2mzml.constants import (
    CV_32BIT_FLOAT,
    CV_64BIT_FLOAT,
    CV_BASE_PEAK_INTENSITY,
    CV_BASE_PEAK_MZ,
    CV_BRUKER_INSTRUMENT,
    CV_BRUKER_TDF_FORMAT,
    CV_BRUKER_TDF_NATIVE_ID,
    CV_CENTROID_SPECTRUM,
    CV_CHARGE_STATE,
    CV_CID,
    CV_COLLISION_ENERGY,
    CV_CONVERSION_TO_MZML,
    CV_ESI,
    CV_IM_LOWER_LIMIT,
    CV_IM_UPPER_LIMIT,
    CV_INSTRUMENT_SERIAL,
    CV_INVERSE_REDUCED_ION_MOBILITY,
    CV_ION_MOBILITY_ARRAY,
    CV_ISOLATION_WINDOW_LOWER,
    CV_ISOLATION_WINDOW_TARGET,
    CV_ISOLATION_WINDOW_UPPER,
    CV_MCP_DETECTOR,
    CV_PHOTOMULTIPLIER,
    CV_MS1_SPECTRUM,
    CV_MS_LEVEL,
    CV_MSN_SPECTRUM,
    CV_MZ_ARRAY,
    CV_INTENSITY_ARRAY,
    CV_NANOSPRAY_INLET,
    CV_NEGATIVE_SCAN,
    CV_NO_COMBINATION,
    CV_NO_COMPRESSION,
    CV_POSITIVE_SCAN,
    CV_PROFILE_SPECTRUM,
    CV_QUADRUPOLE,
    CV_SCAN_START_TIME,
    CV_SCAN_WINDOW_LOWER,
    CV_SCAN_WINDOW_UPPER,
    CV_SELECTED_ION_MZ,
    CV_SHA1,
    CV_TOF_ANALYZER,
    CV_TOTAL_ION_CURRENT,
    CV_ZLIB_COMPRESSION,
    MZML_NAMESPACE,
    MZML_SCHEMA_LOCATION,
    MZML_VERSION,
    UNIT_COUNTS,
    UNIT_ELECTRONVOLT,
    UNIT_MINUTE,
    UNIT_MZ,
    UNIT_VSCC,
)
from tdf2mzml.output.encoding import encode_array

# ---------------------------------------------------------------------------
# CV reference ID (must match the <cv id="..."> in cv_list())
# ---------------------------------------------------------------------------

_CVREF = "PSI-MS"

# ---------------------------------------------------------------------------
# Indentation helpers
# ---------------------------------------------------------------------------

_INDENT = "  "


def _indent(level: int) -> str:
    return _INDENT * level


# ---------------------------------------------------------------------------
# cvParam helper
# ---------------------------------------------------------------------------


def _cv(
    accession: str,
    name: str,
    value: str = "",
    *,
    unit_accession: str = "",
    unit_name: str = "",
    unit_cvref: str = "",
) -> str:
    """Render a ``<cvParam ... />`` attribute string (without surrounding tag indent).

    Always emits ``cvRef``, ``accession``, ``name``, and ``value`` attributes.
    When *unit_accession* is provided the full unit triplet
    (``unitCvRef``, ``unitAccession``, ``unitName``) is appended.
    """
    s = f'cvRef="{_CVREF}" accession="{accession}" name="{name}" value="{value}"'
    if unit_accession:
        ucvref = unit_cvref or _CVREF
        s += f' unitCvRef="{ucvref}" unitAccession="{unit_accession}" unitName="{unit_name}"'
    return f"<cvParam {s}/>"


# Lookup tables for dynamic CV term names -> accession
_POLARITY_ACCESSION: dict[str, str] = {
    "positive scan": CV_POSITIVE_SCAN,
    "negative scan": CV_NEGATIVE_SCAN,
}

_SPECTRUM_TYPE_ACCESSION: dict[str, str] = {
    "centroid spectrum": CV_CENTROID_SPECTRUM,
    "profile spectrum": CV_PROFILE_SPECTRUM,
}

_COMPRESSION_ACCESSION: dict[str, str] = {
    "zlib compression": CV_ZLIB_COMPRESSION,
    "no compression": CV_NO_COMPRESSION,
}


# ---------------------------------------------------------------------------
# File-level wrappers
# ---------------------------------------------------------------------------


def xml_declaration() -> bytes:
    """Return the XML declaration line.

    Returns
    -------
    bytes
    """
    return b'<?xml version="1.0" encoding="utf-8"?>\n'


def indexed_mzml_open() -> bytes:
    """Return the opening ``<indexedmzML>`` tag.

    Returns
    -------
    bytes
    """
    ns = MZML_NAMESPACE
    xsi = "http://www.w3.org/2001/XMLSchema-instance"
    return (
        f'<indexedmzML xmlns="{ns}"\n'
        f'             xmlns:xsi="{xsi}"\n'
        f'             xsi:schemaLocation="{MZML_SCHEMA_LOCATION}">\n'
    ).encode()


def mzml_open(spectrum_count: int) -> bytes:
    """Return the opening ``<mzML>`` tag and run element stub.

    Parameters
    ----------
    spectrum_count : int
        Total number of spectra (written into ``count`` attribute of
        ``<spectrumList>``).

    Returns
    -------
    bytes
    """
    ns = MZML_NAMESPACE
    return (
        f'  <mzML xmlns="{ns}" version="{MZML_VERSION}">\n'
    ).encode()


# ---------------------------------------------------------------------------
# Controlled vocabulary list
# ---------------------------------------------------------------------------


def cv_list() -> bytes:
    """Return the ``<cvList>`` block referencing PSI-MS and UO ontologies.

    Returns
    -------
    bytes
    """
    return textwrap.dedent("""\
      <cvList count="2">
        <cv id="PSI-MS" fullName="Proteomics Standards Initiative Mass Spectrometry Ontology"
            version="4.1.30" URI="https://raw.githubusercontent.com/HUPO-PSI/psi-ms-CV/master/psi-ms.obo"/>
        <cv id="UO" fullName="Unit Ontology"
            version="09:04:2014" URI="https://raw.githubusercontent.com/bio-ontology-research-group/unit-ontology/master/unit.obo"/>
      </cvList>
    """).encode("utf-8")


# ---------------------------------------------------------------------------
# fileDescription
# ---------------------------------------------------------------------------


def file_description(
    source_files: list[dict[str, str]],
    content_params: list[str] | None = None,
) -> bytes:
    """Return the ``<fileDescription>`` block.

    Parameters
    ----------
    source_files : list of dict
        Each dict must have keys: ``id``, ``name``, ``location``,
        ``sha1`` (optional).
    content_params : list of str, optional
        CV term names for ``<fileContent>``. Defaults to
        ``["MS1 spectrum", "MSn spectrum"]``.

    Returns
    -------
    bytes
    """
    _content_accessions: dict[str, str] = {
        "MS1 spectrum": CV_MS1_SPECTRUM,
        "MSn spectrum": CV_MSN_SPECTRUM,
    }

    if content_params is None:
        content_params = ["MS1 spectrum", "MSn spectrum"]

    lines: list[str] = ["    <fileDescription>", "      <fileContent>"]
    for p in content_params:
        acc = _content_accessions.get(p, "")
        lines.append(f"        {_cv(acc, p)}")
    lines.append("      </fileContent>")
    lines.append(f"      <sourceFileList count=\"{len(source_files)}\">")
    for sf in source_files:
        sha_attr = (
            f'\n          {_cv(CV_SHA1, "SHA-1", _xml_escape(sf["sha1"]))}'
            if sf.get("sha1")
            else ""
        )
        lines.append(
            f'        <sourceFile id="{_xml_escape(sf["id"])}" name="{_xml_escape(sf["name"])}" '
            f'location="{_xml_escape(sf["location"])}">'
            f'{sha_attr}\n'
            f'          {_cv(CV_BRUKER_TDF_FORMAT, "Bruker TDF format")}\n'
            f'          {_cv(CV_BRUKER_TDF_NATIVE_ID, "Bruker TDF nativeID format")}\n'
            f'        </sourceFile>'
        )
    lines += ["      </sourceFileList>", "    </fileDescription>"]
    return ("\n".join(lines) + "\n").encode("utf-8")


# ---------------------------------------------------------------------------
# softwareList
# ---------------------------------------------------------------------------


def software_list(entries: list[dict[str, str]]) -> bytes:
    """Return the ``<softwareList>`` block.

    Parameters
    ----------
    entries : list of dict
        Each dict must have ``id``, ``version``, ``cv_name``, ``cv_accession``.
        Optional keys: ``cv_value`` (value for the cvParam, default ``""``),
        ``user_params`` (list of ``{"name": ..., "value": ...}`` dicts).

    Returns
    -------
    bytes
    """
    lines = [f'    <softwareList count="{len(entries)}">']
    for e in entries:
        acc = e.get("cv_accession", "")
        cv_value = e.get("cv_value", "")
        cv_tag = f'        {_cv(acc, _xml_escape(e["cv_name"]), cv_value)}'
        user_tags = ""
        for up in e.get("user_params", []):
            user_tags += (
                f'\n        <userParam name="{_xml_escape(up["name"])}" '
                f'value="{_xml_escape(up["value"])}" type="xsd:string"/>'
            )
        lines.append(
            f'      <software id="{_xml_escape(e["id"])}" version="{_xml_escape(e["version"])}">\n'
            f'{cv_tag}{user_tags}\n'
            f'      </software>'
        )
    lines.append("    </softwareList>")
    return ("\n".join(lines) + "\n").encode("utf-8")


# ---------------------------------------------------------------------------
# instrumentConfigurationList
# ---------------------------------------------------------------------------


def instrument_configuration_list(
    serial_number: str,
    instrument_name: str = "",
    instrument_vendor: str = "",
) -> bytes:
    """Return the ``<instrumentConfigurationList>`` block for a timsTOF.

    Parameters
    ----------
    serial_number : str
        Instrument serial number.
    instrument_name : str, optional
        Instrument model name from GlobalMetadata (e.g. ``"timsTOF Pro"``).
    instrument_vendor : str, optional
        Instrument vendor string (e.g. ``"Bruker"``).

    Returns
    -------
    bytes
    """
    name_param = (
        f'\n            <userParam name="instrument model" value="{_xml_escape(instrument_name)}"/>'
        if instrument_name
        else ""
    )
    vendor_param = (
        f'\n            <userParam name="instrument vendor" value="{_xml_escape(instrument_vendor)}"/>'
        if instrument_vendor
        else ""
    )
    cv_instrument = _cv(CV_BRUKER_INSTRUMENT, "Bruker Daltonics instrument model")
    cv_serial = _cv(CV_INSTRUMENT_SERIAL, "instrument serial number", _xml_escape(serial_number))
    cv_nanospray = _cv(CV_NANOSPRAY_INLET, "nanospray inlet")
    cv_esi = _cv(CV_ESI, "electrospray ionization")
    cv_quad = _cv(CV_QUADRUPOLE, "quadrupole")
    cv_tof = _cv(CV_TOF_ANALYZER, "time-of-flight")
    cv_mcp = _cv(CV_MCP_DETECTOR, "microchannel plate detector")
    cv_pmt = _cv(CV_PHOTOMULTIPLIER, "photomultiplier")
    return textwrap.dedent(f"""\
        <instrumentConfigurationList count="1">
          <instrumentConfiguration id="IC1">
            {cv_instrument}{name_param}
            {cv_serial}{vendor_param}
            <componentList count="3">
              <source order="1">
                {cv_nanospray}
                {cv_esi}
              </source>
              <analyzer order="2">
                {cv_quad}
                {cv_tof}
              </analyzer>
              <detector order="3">
                {cv_mcp}
                {cv_pmt}
              </detector>
            </componentList>
          </instrumentConfiguration>
        </instrumentConfigurationList>
    """).encode("utf-8")


def sample_list(
    sample_name: str,
    description: str = "",
) -> bytes:
    """Return a ``<sampleList>`` block with a single sample entry.

    Parameters
    ----------
    sample_name : str
        Sample name from GlobalMetadata.
    description : str, optional
        Free-text description from GlobalMetadata.

    Returns
    -------
    bytes
    """
    desc_param = (
        f'\n        <userParam name="sample description" value="{_xml_escape(description)}"/>'
        if description
        else ""
    )
    return textwrap.dedent(f"""\
        <sampleList count="1">
          <sample id="S1" name="{_xml_escape(sample_name)}">{desc_param}
          </sample>
        </sampleList>
    """).encode("utf-8")


# ---------------------------------------------------------------------------
# dataProcessingList
# ---------------------------------------------------------------------------


def data_processing_list(version: str) -> bytes:
    """Return the ``<dataProcessingList>`` block.

    Parameters
    ----------
    version : str
        tdf2mzml version string.

    Returns
    -------
    bytes
    """
    cv_conversion = _cv(CV_CONVERSION_TO_MZML, "Conversion to mzML")
    return textwrap.dedent(f"""\
        <dataProcessingList count="1">
          <dataProcessing id="tdf2mzml_conversion">
            <processingMethod order="0" softwareRef="tdf2mzml">
              {cv_conversion}
            </processingMethod>
          </dataProcessing>
        </dataProcessingList>
    """).encode("utf-8")


# ---------------------------------------------------------------------------
# spectrum element
# ---------------------------------------------------------------------------


def spectrum_element(
    spectrum_id: str,
    index: int,
    ms_level: int,
    centroided: bool,
    scan_start_time: float,
    mz_array: npt.NDArray[np.float64],
    intensity_array: npt.NDArray[np.float32],
    scan_window_lower: float,
    scan_window_upper: float,
    compression: Literal["none", "zlib"],
    total_ion_current: float,
    base_peak_mz: float,
    base_peak_intensity: float,
    precursor_mz: float | None = None,
    precursor_charge: int | None = None,
    precursor_spectrum_ref: str | None = None,
    isolation_window_target: float | None = None,
    isolation_window_lower: float | None = None,
    isolation_window_upper: float | None = None,
    collision_energy: float | None = None,
    one_over_k0: float | None = None,
    ion_mobility_array: npt.NDArray[np.float64] | None = None,
    ook0_window_lower: float | None = None,
    ook0_window_upper: float | None = None,
    polarity: str | None = None,
) -> bytes:
    """Render a complete ``<spectrum>`` XML element to bytes.

    Parameters
    ----------
    spectrum_id : str
        Spectrum ID string (e.g. ``"index=1"``).
    index : int
        0-based spectrum index.
    ms_level : int
        MS level (1 or 2).
    centroided : bool
        True for centroid, False for profile.
    scan_start_time : float
        Scan start time in minutes.
    mz_array : numpy.ndarray
        m/z array (float64).
    intensity_array : numpy.ndarray
        Intensity array (float32).
    scan_window_lower : float
        Lower m/z scan window bound.
    scan_window_upper : float
        Upper m/z scan window bound.
    compression : {"none", "zlib"}
        Binary array compression.
    total_ion_current : float
        Total ion current for this spectrum.
    base_peak_mz : float
        m/z of the base peak.
    base_peak_intensity : float
        Intensity of the base peak.
    precursor_mz : float or None
        Precursor m/z (MS2 only).
    precursor_charge : int or None
        Precursor charge state (MS2 only).
    precursor_spectrum_ref : str or None
        Parent spectrum ID (MS2 only).
    isolation_window_target : float or None
        Isolation window centre m/z (MS2 only).
    isolation_window_lower : float or None
        Isolation window lower offset (MS2 only).
    isolation_window_upper : float or None
        Isolation window upper offset (MS2 only).
    collision_energy : float or None
        Collision energy in eV (MS2 only).
    one_over_k0 : float or None
        Mean inverse reduced ion mobility (1/K0) for the spectrum.
    ion_mobility_array : numpy.ndarray or None
        Per-peak mean 1/K0 array (for ``"array"`` IM mode).
    ook0_window_lower : float or None
        Lower 1/K0 acquisition range (V·s/cm²); adds a second
        ``<scanWindow>`` with ``MS:1002476`` / ``MS:1002477`` CV params.
    ook0_window_upper : float or None
        Upper 1/K0 acquisition range (V·s/cm²).
    polarity : str or None, optional
        Scan polarity CV term name.  Pass ``"positive scan"`` (CV MS:1000130)
        or ``"negative scan"`` (CV MS:1000129).  When None, no polarity CV
        term is emitted (default for TDF/TIMS files where polarity is not
        stored per-frame).

    Returns
    -------
    bytes
        Complete ``<spectrum>...</spectrum>`` block as UTF-8 bytes.
    """
    n_peaks = len(mz_array)
    spectrum_type = "centroid spectrum" if centroided else "profile spectrum"
    spectrum_type_acc = _SPECTRUM_TYPE_ACCESSION[spectrum_type]
    n_arrays = 3 if ion_mobility_array is not None else 2

    # Encode binary arrays
    mz_b64 = encode_array(mz_array, compression)
    int_b64 = encode_array(intensity_array, compression)
    comp_cv_name = "zlib compression" if compression == "zlib" else "no compression"
    comp_cv_acc = _COMPRESSION_ACCESSION[comp_cv_name]

    polarity_cv = ""
    if polarity is not None:
        pol_acc = _POLARITY_ACCESSION[polarity]
        polarity_cv = f'\n        {_cv(pol_acc, polarity)}'

    lines: list[str] = [
        f'      <spectrum index="{index}" id="{spectrum_id}" defaultArrayLength="{n_peaks}">',
        f'        {_cv(CV_MS_LEVEL, "ms level", str(ms_level))}',
        f'        {_cv(spectrum_type_acc, spectrum_type)}' + polarity_cv,
        f'        {_cv(CV_TOTAL_ION_CURRENT, "total ion current", f"{total_ion_current:.6g}")}',
        f'        {_cv(CV_BASE_PEAK_MZ, "base peak m/z", f"{base_peak_mz:.6f}", unit_accession=UNIT_MZ, unit_name="m/z")}',
        f'        {_cv(CV_BASE_PEAK_INTENSITY, "base peak intensity", f"{base_peak_intensity:.6g}", unit_accession=UNIT_COUNTS, unit_name="number of detector counts")}',
    ]

    # Scan list
    im_scan_cv = ""
    if one_over_k0 is not None:
        im_scan_cv = (
            f'\n          {_cv(CV_INVERSE_REDUCED_ION_MOBILITY, "mean inverse reduced ion mobility", f"{one_over_k0:.6f}", unit_accession=UNIT_VSCC, unit_name="volt-second per square centimeter")}'
        )
    has_im_window = ook0_window_lower is not None and ook0_window_upper is not None
    n_scan_windows = 2 if has_im_window else 1
    im_window_xml = ""
    if has_im_window:
        im_window_xml = (
            f'\n              <scanWindow>\n'
            f'                {_cv(CV_IM_LOWER_LIMIT, "inverse reduced ion mobility lower limit", str(ook0_window_lower), unit_accession=UNIT_VSCC, unit_name="volt-second per square centimeter")}\n'
            f'                {_cv(CV_IM_UPPER_LIMIT, "inverse reduced ion mobility upper limit", str(ook0_window_upper), unit_accession=UNIT_VSCC, unit_name="volt-second per square centimeter")}\n'
            f'              </scanWindow>'
        )
    lines += [
        '        <scanList count="1">',
        f'          {_cv(CV_NO_COMBINATION, "no combination")}',
        '          <scan>',
        f'            {_cv(CV_SCAN_START_TIME, "scan start time", f"{scan_start_time:.6f}", unit_accession=UNIT_MINUTE, unit_name="minute", unit_cvref="UO")}' + im_scan_cv,
        f'            <scanWindowList count="{n_scan_windows}">',
        '              <scanWindow>',
        f'                {_cv(CV_SCAN_WINDOW_LOWER, "scan window lower limit", str(scan_window_lower), unit_accession=UNIT_MZ, unit_name="m/z")}',
        f'                {_cv(CV_SCAN_WINDOW_UPPER, "scan window upper limit", str(scan_window_upper), unit_accession=UNIT_MZ, unit_name="m/z")}',
        '              </scanWindow>' + im_window_xml,
        '            </scanWindowList>',
        '          </scan>',
        '        </scanList>',
    ]

    # Precursor list (MS2 only)
    if ms_level == 2 and precursor_mz is not None:
        charge_cv = ""
        if precursor_charge is not None:
            charge_cv = f'\n              {_cv(CV_CHARGE_STATE, "charge state", str(precursor_charge))}'
        ref_attr = (
            f' spectrumRef="{precursor_spectrum_ref}"'
            if precursor_spectrum_ref
            else ""
        )
        ce_cv = ""
        if collision_energy is not None:
            ce_cv = f'\n            {_cv(CV_COLLISION_ENERGY, "collision energy", str(collision_energy), unit_accession=UNIT_ELECTRONVOLT, unit_name="electronvolt", unit_cvref="UO")}'
        lines += [
            '        <precursorList count="1">',
            f'          <precursor{ref_attr}>',
            '            <isolationWindow>',
            *(
                [
                    f'              {_cv(CV_ISOLATION_WINDOW_TARGET, "isolation window target m/z", str(isolation_window_target), unit_accession=UNIT_MZ, unit_name="m/z")}',
                ]
                if isolation_window_target is not None
                else []
            ),
            *(
                [
                    f'              {_cv(CV_ISOLATION_WINDOW_LOWER, "isolation window lower offset", str(isolation_window_lower), unit_accession=UNIT_MZ, unit_name="m/z")}',
                ]
                if isolation_window_lower is not None
                else []
            ),
            *(
                [
                    f'              {_cv(CV_ISOLATION_WINDOW_UPPER, "isolation window upper offset", str(isolation_window_upper), unit_accession=UNIT_MZ, unit_name="m/z")}',
                ]
                if isolation_window_upper is not None
                else []
            ),
            '            </isolationWindow>',
            '            <selectedIonList count="1">',
            '              <selectedIon>',
            f'                {_cv(CV_SELECTED_ION_MZ, "selected ion m/z", str(precursor_mz), unit_accession=UNIT_MZ, unit_name="m/z")}' + charge_cv,
            '              </selectedIon>',
            '            </selectedIonList>',
            '            <activation>',
            f'              {_cv(CV_CID, "collision-induced dissociation")}' + ce_cv,
            '            </activation>',
            '          </precursor>',
            '        </precursorList>',
        ]

    # Binary data arrays
    lines.append(f'        <binaryDataArrayList count="{n_arrays}">')

    # m/z array
    lines += [
        '          <binaryDataArray>',
        f'            {_cv(CV_MZ_ARRAY, "m/z array")}',
        f'            {_cv(CV_64BIT_FLOAT, "64-bit float")}',
        f'            {_cv(comp_cv_acc, comp_cv_name)}',
        f'            <binary>{mz_b64}</binary>',
        '          </binaryDataArray>',
    ]

    # intensity array
    lines += [
        '          <binaryDataArray>',
        f'            {_cv(CV_INTENSITY_ARRAY, "intensity array")}',
        f'            {_cv(CV_32BIT_FLOAT, "32-bit float")}',
        f'            {_cv(comp_cv_acc, comp_cv_name)}',
        f'            <binary>{int_b64}</binary>',
        '          </binaryDataArray>',
    ]

    # optional ion mobility array
    if ion_mobility_array is not None:
        im_b64 = encode_array(ion_mobility_array, compression)
        lines += [
            '          <binaryDataArray>',
            f'            {_cv(CV_ION_MOBILITY_ARRAY, "mean inverse reduced ion mobility array")}',
            f'            {_cv(CV_64BIT_FLOAT, "64-bit float")}',
            f'            {_cv(comp_cv_acc, comp_cv_name)}',
            f'            <binary>{im_b64}</binary>',
            '          </binaryDataArray>',
        ]

    lines += ["        </binaryDataArrayList>", "      </spectrum>"]
    return ("\n".join(lines) + "\n").encode("utf-8")
