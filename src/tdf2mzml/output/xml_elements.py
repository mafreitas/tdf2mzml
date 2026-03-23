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

from tdf2mzml.constants import MZML_NAMESPACE, MZML_SCHEMA_LOCATION, MZML_VERSION
from tdf2mzml.output.encoding import encode_array

# ---------------------------------------------------------------------------
# Indentation helpers
# ---------------------------------------------------------------------------

_INDENT = "  "


def _indent(level: int) -> str:
    return _INDENT * level


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
        <cv id="MS" fullName="Proteomics Standards Initiative Mass Spectrometry Ontology"
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
    if content_params is None:
        content_params = ["MS1 spectrum", "MSn spectrum"]

    lines: list[str] = ["    <fileDescription>", "      <fileContent>"]
    for p in content_params:
        lines.append(f'        <cvParam cvRef="MS" name="{p}"/>')
    lines.append("      </fileContent>")
    lines.append(f"      <sourceFileList count=\"{len(source_files)}\">")
    for sf in source_files:
        sha_attr = (
            f'\n          <cvParam cvRef="MS" accession="MS:1000569" '
            f'name="SHA-1" value="{_xml_escape(sf["sha1"])}"/>'
            if sf.get("sha1")
            else ""
        )
        lines.append(
            f'        <sourceFile id="{_xml_escape(sf["id"])}" name="{_xml_escape(sf["name"])}" '
            f'location="{_xml_escape(sf["location"])}">'
            f'{sha_attr}\n'
            f'          <cvParam cvRef="MS" name="Bruker TDF format"/>\n'
            f'          <cvParam cvRef="MS" name="Bruker TDF nativeID format"/>\n'
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
        Each dict: ``{"id": ..., "version": ..., "cv_name": ...}``.

    Returns
    -------
    bytes
    """
    lines = [f'    <softwareList count="{len(entries)}">']
    for e in entries:
        lines.append(
            f'      <software id="{_xml_escape(e["id"])}" version="{_xml_escape(e["version"])}">\n'
            f'        <cvParam cvRef="MS" name="{_xml_escape(e["cv_name"])}"/>\n'
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
    return textwrap.dedent(f"""\
        <instrumentConfigurationList count="1">
          <instrumentConfiguration id="IC1">
            <cvParam cvRef="MS" name="Bruker Daltonics instrument model"/>{name_param}
            <cvParam cvRef="MS" name="instrument serial number" value="{_xml_escape(serial_number)}"/>{vendor_param}
            <componentList count="3">
              <source order="1">
                <cvParam cvRef="MS" name="nanospray inlet"/>
                <cvParam cvRef="MS" name="electrospray ionization"/>
              </source>
              <analyzer order="2">
                <cvParam cvRef="MS" name="quadrupole"/>
                <cvParam cvRef="MS" name="time-of-flight"/>
              </analyzer>
              <detector order="3">
                <cvParam cvRef="MS" name="microchannel plate detector"/>
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
    return textwrap.dedent("""\
        <dataProcessingList count="1">
          <dataProcessing id="tdf2mzml_conversion">
            <processingMethod order="0" softwareRef="tdf2mzml">
              <cvParam cvRef="MS" name="Conversion to mzML"/>
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
    n_arrays = 3 if ion_mobility_array is not None else 2

    # Encode binary arrays
    mz_b64 = encode_array(mz_array, compression)
    int_b64 = encode_array(intensity_array, compression)
    comp_cv = "zlib compression" if compression == "zlib" else "no compression"

    polarity_cv = (
        f'\n        <cvParam cvRef="MS" name="{polarity}"/>'
        if polarity is not None
        else ""
    )

    lines: list[str] = [
        f'      <spectrum index="{index}" id="{spectrum_id}" defaultArrayLength="{n_peaks}">',
        f'        <cvParam cvRef="MS" name="ms level" value="{ms_level}"/>',
        f'        <cvParam cvRef="MS" name="{spectrum_type}"/>' + polarity_cv,
        f'        <cvParam cvRef="MS" name="total ion current" value="{total_ion_current:.6g}"/>',
        f'        <cvParam cvRef="MS" name="base peak m/z" value="{base_peak_mz:.6f}" unitName="m/z"/>',
        f'        <cvParam cvRef="MS" name="base peak intensity" value="{base_peak_intensity:.6g}" unitName="number of detector counts"/>',
    ]

    # Scan list
    im_scan_cv = (
        f'\n          <cvParam cvRef="MS" accession="MS:1002814" '
        f'name="mean inverse reduced ion mobility" value="{one_over_k0:.6f}" '
        f'unitName="volt-second per square centimeter"/>'
        if one_over_k0 is not None
        else ""
    )
    has_im_window = ook0_window_lower is not None and ook0_window_upper is not None
    n_scan_windows = 2 if has_im_window else 1
    im_window_xml = (
        f'\n              <scanWindow>\n'
        f'                <cvParam cvRef="MS" accession="MS:1002476" '
        f'name="inverse reduced ion mobility lower limit" '
        f'value="{ook0_window_lower}" unitName="volt-second per square centimeter"/>\n'
        f'                <cvParam cvRef="MS" accession="MS:1002477" '
        f'name="inverse reduced ion mobility upper limit" '
        f'value="{ook0_window_upper}" unitName="volt-second per square centimeter"/>\n'
        f'              </scanWindow>'
        if has_im_window
        else ""
    )
    lines += [
        '        <scanList count="1">',
        '          <cvParam cvRef="MS" name="no combination"/>',
        '          <scan>',
        f'            <cvParam cvRef="MS" accession="MS:1000016" name="scan start time" '
        f'value="{scan_start_time:.6f}" unitName="minute"/>' + im_scan_cv,
        f'            <scanWindowList count="{n_scan_windows}">',
        '              <scanWindow>',
        f'                <cvParam cvRef="MS" name="scan window lower limit" value="{scan_window_lower}" unitName="m/z"/>',
        f'                <cvParam cvRef="MS" name="scan window upper limit" value="{scan_window_upper}" unitName="m/z"/>',
        '              </scanWindow>' + im_window_xml,
        '            </scanWindowList>',
        '          </scan>',
        '        </scanList>',
    ]

    # Precursor list (MS2 only)
    if ms_level == 2 and precursor_mz is not None:
        charge_cv = (
            f'\n              <cvParam cvRef="MS" name="charge state" value="{precursor_charge}"/>'
            if precursor_charge is not None
            else ""
        )
        ref_attr = (
            f' spectrumRef="{precursor_spectrum_ref}"'
            if precursor_spectrum_ref
            else ""
        )
        ce_cv = (
            f'\n            <cvParam cvRef="MS" name="collision energy" value="{collision_energy}" unitName="electronvolt"/>'
            if collision_energy is not None
            else ""
        )
        lines += [
            '        <precursorList count="1">',
            f'          <precursor{ref_attr}>',
            '            <isolationWindow>',
            *(
                [
                    f'              <cvParam cvRef="MS" name="isolation window target m/z" value="{isolation_window_target}" unitName="m/z"/>',
                ]
                if isolation_window_target is not None
                else []
            ),
            *(
                [
                    f'              <cvParam cvRef="MS" name="isolation window lower offset" value="{isolation_window_lower}" unitName="m/z"/>',
                ]
                if isolation_window_lower is not None
                else []
            ),
            *(
                [
                    f'              <cvParam cvRef="MS" name="isolation window upper offset" value="{isolation_window_upper}" unitName="m/z"/>',
                ]
                if isolation_window_upper is not None
                else []
            ),
            '            </isolationWindow>',
            '            <selectedIonList count="1">',
            '              <selectedIon>',
            f'                <cvParam cvRef="MS" name="selected ion m/z" value="{precursor_mz}" unitName="m/z"/>' + charge_cv,
            '              </selectedIon>',
            '            </selectedIonList>',
            '            <activation>',
            '              <cvParam cvRef="MS" name="collision-induced dissociation"/>' + ce_cv,
            '            </activation>',
            '          </precursor>',
            '        </precursorList>',
        ]

    # Binary data arrays
    lines.append(f'        <binaryDataArrayList count="{n_arrays}">')

    # m/z array
    lines += [
        '          <binaryDataArray>',
        '            <cvParam cvRef="MS" name="m/z array"/>',
        '            <cvParam cvRef="MS" name="64-bit float"/>',
        f'            <cvParam cvRef="MS" name="{comp_cv}"/>',
        f'            <binary>{mz_b64}</binary>',
        '          </binaryDataArray>',
    ]

    # intensity array
    lines += [
        '          <binaryDataArray>',
        '            <cvParam cvRef="MS" name="intensity array"/>',
        '            <cvParam cvRef="MS" name="32-bit float"/>',
        f'            <cvParam cvRef="MS" name="{comp_cv}"/>',
        f'            <binary>{int_b64}</binary>',
        '          </binaryDataArray>',
    ]

    # optional ion mobility array
    if ion_mobility_array is not None:
        im_b64 = encode_array(ion_mobility_array, compression)
        lines += [
            '          <binaryDataArray>',
            '            <cvParam cvRef="MS" accession="MS:1002816" name="mean inverse reduced ion mobility array"/>',
            '            <cvParam cvRef="MS" name="64-bit float"/>',
            f'            <cvParam cvRef="MS" name="{comp_cv}"/>',
            f'            <binary>{im_b64}</binary>',
            '          </binaryDataArray>',
        ]

    lines += ["        </binaryDataArrayList>", "      </spectrum>"]
    return ("\n".join(lines) + "\n").encode("utf-8")
