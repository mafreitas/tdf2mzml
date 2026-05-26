"""mzML XML compliance tests.

These tests verify that the XML output from xml_elements.py conforms to
the mzML 1.1.0 specification. They exercise the XML builders directly with
synthetic numpy arrays — no real TDF data is needed, so they run fast in CI.

Every test here guards against a specific regression from the v0.5 refactor:
dropped cvParam accessions, wrong cvRef, missing encodedLength, 0-based
spectrum IDs, incomplete unit triplets, and wrong instrument accessions.
"""

from __future__ import annotations

import re

import numpy as np
import pytest

from tdf2mzml.output import xml_elements as xe

try:
    from lxml import etree
except ImportError:  # pragma: no cover - local fallback when lxml is unavailable
    import xml.etree.ElementTree as etree  # type: ignore[no-redef]  # noqa: N813

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Regex to find all <cvParam .../> tags in raw XML text
_CVPARAM_RE = re.compile(r"<cvParam\s[^>]+/>")


def _find_all_cvparams(xml_bytes: bytes) -> list[dict[str, str]]:
    """Parse all cvParam tags from raw XML bytes into attribute dicts."""
    results = []
    for match in _CVPARAM_RE.finditer(xml_bytes.decode()):
        tag_str = match.group()
        # Use a mini-parse to extract attributes
        attrs = dict(re.findall(r'(\w+)="([^"]*)"', tag_str))
        results.append(attrs)
    return results


def _find_all_tags(xml_bytes: bytes, tag: str) -> list[dict[str, str]]:
    """Find all opening tags of a given name and return their attributes."""
    pattern = re.compile(rf"<{tag}\s([^>]*)>")
    results = []
    for match in pattern.finditer(xml_bytes.decode()):
        attrs = dict(re.findall(r'(\w+)="([^"]*)"', match.group()))
        results.append(attrs)
    return results


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def ms1_spectrum_bytes() -> bytes:
    """Generate a minimal MS1 spectrum XML block for compliance testing."""
    mz = np.array([100.0, 200.0, 300.0], dtype=np.float64)
    intensity = np.array([1000.0, 2000.0, 500.0], dtype=np.float32)
    return xe.spectrum_element(
        spectrum_id="index=1",
        index=0,
        ms_level=1,
        centroided=True,
        scan_start_time=1.234567,
        mz_array=mz,
        intensity_array=intensity,
        scan_window_lower=50.0,
        scan_window_upper=1700.0,
        compression="none",
        total_ion_current=3500.0,
        base_peak_mz=200.0,
        base_peak_intensity=2000.0,
        one_over_k0=1.234,
        polarity="positive scan",
    )


@pytest.fixture
def ms2_spectrum_bytes() -> bytes:
    """Generate a minimal MS2 spectrum XML block with precursor info."""
    mz = np.array([150.0, 250.0], dtype=np.float64)
    intensity = np.array([500.0, 1000.0], dtype=np.float32)
    return xe.spectrum_element(
        spectrum_id="index=2",
        index=1,
        ms_level=2,
        centroided=True,
        scan_start_time=1.5,
        mz_array=mz,
        intensity_array=intensity,
        scan_window_lower=50.0,
        scan_window_upper=1700.0,
        compression="zlib",
        total_ion_current=1500.0,
        base_peak_mz=250.0,
        base_peak_intensity=1000.0,
        precursor_mz=456.789,
        precursor_charge=2,
        precursor_spectrum_ref="index=1",
        isolation_window_target=456.789,
        isolation_window_lower=1.0,
        isolation_window_upper=1.0,
        collision_energy=30.0,
    )


@pytest.fixture
def ms1_with_im_array_bytes() -> bytes:
    """Generate an MS1 spectrum with per-peak ion mobility array."""
    mz = np.array([100.0, 200.0], dtype=np.float64)
    intensity = np.array([1000.0, 2000.0], dtype=np.float32)
    im = np.array([1.1, 1.2], dtype=np.float64)
    return xe.spectrum_element(
        spectrum_id="index=1",
        index=0,
        ms_level=1,
        centroided=True,
        scan_start_time=1.0,
        mz_array=mz,
        intensity_array=intensity,
        scan_window_lower=50.0,
        scan_window_upper=1700.0,
        compression="none",
        total_ion_current=3000.0,
        base_peak_mz=200.0,
        base_peak_intensity=2000.0,
        ion_mobility_array=im,
        ook0_window_lower=0.6,
        ook0_window_upper=1.6,
    )


# ===================================================================
# XML escaping
# ===================================================================


class TestXmlEscaping:
    """XML builders must escape attribute values, including quotes."""

    def test_xml_attr_escapes_double_quotes(self) -> None:
        assert xe._xml_attr('a"b') == "a&quot;b"
        assert xe._xml_attr("plain") == "plain"
        assert xe._xml_attr('he said "hi" & ok') == "he said &quot;hi&quot; &amp; ok"

    def test_sample_description_with_quotes_is_well_formed(self) -> None:
        xml_bytes = xe.sample_list("sample one", 'sample "alpha" & beta')

        root = etree.fromstring(xml_bytes)
        description = root.find("sample/userParam")

        assert description is not None
        assert description.get("value") == 'sample "alpha" & beta'


# ===================================================================
# cvParam compliance — accession, cvRef, value
# ===================================================================


class TestCvParamCompliance:
    """Verify every cvParam has required attributes per mzML 1.1.0 XSD."""

    def test_every_cvparam_has_accession_ms1(self, ms1_spectrum_bytes: bytes) -> None:
        params = _find_all_cvparams(ms1_spectrum_bytes)
        assert len(params) > 0, "No cvParams found"
        for p in params:
            assert "accession" in p, f"cvParam missing accession: name={p.get('name')}"
            assert p["accession"].startswith("MS:") or p["accession"].startswith("UO:"), (
                f"Invalid accession format: {p['accession']}"
            )

    def test_every_cvparam_has_accession_ms2(self, ms2_spectrum_bytes: bytes) -> None:
        params = _find_all_cvparams(ms2_spectrum_bytes)
        for p in params:
            assert "accession" in p, f"cvParam missing accession: name={p.get('name')}"

    def test_cvref_is_psi_ms_ms1(self, ms1_spectrum_bytes: bytes) -> None:
        params = _find_all_cvparams(ms1_spectrum_bytes)
        for p in params:
            assert p.get("cvRef") == "PSI-MS", (
                f"cvRef should be 'PSI-MS', got '{p.get('cvRef')}' for name={p.get('name')}"
            )

    def test_cvref_is_psi_ms_ms2(self, ms2_spectrum_bytes: bytes) -> None:
        params = _find_all_cvparams(ms2_spectrum_bytes)
        for p in params:
            assert p.get("cvRef") == "PSI-MS", (
                f"cvRef should be 'PSI-MS', got '{p.get('cvRef')}' for name={p.get('name')}"
            )

    def test_cvparam_has_value_attribute(self, ms1_spectrum_bytes: bytes) -> None:
        params = _find_all_cvparams(ms1_spectrum_bytes)
        for p in params:
            assert "value" in p, f"cvParam missing value attribute: name={p.get('name')}"

    def test_cv_list_uses_psi_ms_id(self) -> None:
        cv_xml = xe.cv_list().decode()
        assert 'id="PSI-MS"' in cv_xml
        assert 'id="UO"' in cv_xml


# ===================================================================
# Unit triplets — unitCvRef + unitAccession + unitName
# ===================================================================


class TestUnitTriplets:
    """Any cvParam with unitName must have full unit triplet."""

    def test_unit_params_have_full_triplet_ms1(self, ms1_spectrum_bytes: bytes) -> None:
        params = _find_all_cvparams(ms1_spectrum_bytes)
        for p in params:
            if "unitName" in p:
                assert "unitAccession" in p, (
                    f"cvParam has unitName but no unitAccession: name={p.get('name')}"
                )
                assert "unitCvRef" in p, (
                    f"cvParam has unitName but no unitCvRef: name={p.get('name')}"
                )

    def test_unit_params_have_full_triplet_ms2(self, ms2_spectrum_bytes: bytes) -> None:
        params = _find_all_cvparams(ms2_spectrum_bytes)
        for p in params:
            if "unitName" in p:
                assert "unitAccession" in p, (
                    f"cvParam has unitName but no unitAccession: name={p.get('name')}"
                )
                assert "unitCvRef" in p, (
                    f"cvParam has unitName but no unitCvRef: name={p.get('name')}"
                )

    def test_mz_unit_accession(self, ms1_spectrum_bytes: bytes) -> None:
        params = _find_all_cvparams(ms1_spectrum_bytes)
        mz_params = [p for p in params if p.get("unitName") == "m/z"]
        assert len(mz_params) > 0
        for p in mz_params:
            assert p["unitAccession"] == "MS:1000040"

    def test_minute_unit_accession(self, ms1_spectrum_bytes: bytes) -> None:
        params = _find_all_cvparams(ms1_spectrum_bytes)
        minute_params = [p for p in params if p.get("unitName") == "minute"]
        assert len(minute_params) == 1
        assert minute_params[0]["unitAccession"] == "UO:0000031"
        assert minute_params[0]["unitCvRef"] == "UO"

    def test_electronvolt_unit_accession(self, ms2_spectrum_bytes: bytes) -> None:
        params = _find_all_cvparams(ms2_spectrum_bytes)
        ev_params = [p for p in params if p.get("unitName") == "electronvolt"]
        assert len(ev_params) == 1
        assert ev_params[0]["unitAccession"] == "UO:0000266"
        assert ev_params[0]["unitCvRef"] == "UO"

    def test_detector_counts_unit_accession(self, ms1_spectrum_bytes: bytes) -> None:
        params = _find_all_cvparams(ms1_spectrum_bytes)
        count_params = [p for p in params if p.get("unitName") == "number of detector counts"]
        assert len(count_params) == 1
        assert count_params[0]["unitAccession"] == "MS:1000131"


# ===================================================================
# encodedLength on binaryDataArray
# ===================================================================


class TestEncodedLength:
    """Every binaryDataArray must have encodedLength matching binary content."""

    def test_binary_data_array_has_encoded_length(self, ms1_spectrum_bytes: bytes) -> None:
        bda_tags = _find_all_tags(ms1_spectrum_bytes, "binaryDataArray")
        assert len(bda_tags) >= 2, "Expected at least 2 binaryDataArrays"
        for tag in bda_tags:
            assert "encodedLength" in tag, "binaryDataArray missing encodedLength attribute"
            assert int(tag["encodedLength"]) > 0

    def test_encoded_length_matches_binary_content(self, ms1_spectrum_bytes: bytes) -> None:
        text = ms1_spectrum_bytes.decode()
        # Find all <binary>...</binary> content and corresponding encodedLength
        binary_re = re.compile(
            r'encodedLength="(\d+)"[^>]*>.*?<binary>([^<]*)</binary>',
            re.DOTALL,
        )
        matches = binary_re.findall(text)
        assert len(matches) >= 2
        for declared_len, b64_content in matches:
            assert int(declared_len) == len(b64_content), (
                f"encodedLength={declared_len} but base64 has {len(b64_content)} chars"
            )

    def test_im_array_has_encoded_length(self, ms1_with_im_array_bytes: bytes) -> None:
        bda_tags = _find_all_tags(ms1_with_im_array_bytes, "binaryDataArray")
        assert len(bda_tags) == 3, "Expected 3 binaryDataArrays (mz, int, IM)"
        for tag in bda_tags:
            assert "encodedLength" in tag

    def test_zlib_compressed_encoded_length(self, ms2_spectrum_bytes: bytes) -> None:
        bda_tags = _find_all_tags(ms2_spectrum_bytes, "binaryDataArray")
        assert len(bda_tags) >= 2
        for tag in bda_tags:
            assert "encodedLength" in tag
            assert int(tag["encodedLength"]) > 0


# ===================================================================
# Spectrum IDs — must be 1-based
# ===================================================================


class TestSpectrumIds:
    """Spectrum id attribute must use 1-based indexing."""

    def test_spectrum_id_is_one_based(self, ms1_spectrum_bytes: bytes) -> None:
        text = ms1_spectrum_bytes.decode()
        # index=0 in the XML attribute, but id should be "index=1"
        assert 'index="0"' in text, "index attribute should be 0-based"
        assert 'id="index=1"' in text, "id should be 1-based (index=1 for first spectrum)"

    def test_ms2_precursor_ref_matches_parent(self, ms2_spectrum_bytes: bytes) -> None:
        text = ms2_spectrum_bytes.decode()
        assert 'spectrumRef="index=1"' in text


# ===================================================================
# Software list
# ===================================================================


class TestSoftwareList:
    """Software list entries must have proper CV accessions."""

    @pytest.fixture
    def software_xml(self) -> bytes:
        entries = [
            {
                "id": "TIMS_SDK",
                "version": "2.8.7",
                "cv_name": "Bruker software",
                "cv_accession": "MS:1000692",
                "user_params": [
                    {"name": "software name", "value": "TIMS SDK"},
                ],
            },
            {
                "id": "otofControl",
                "version": "1.0",
                "cv_name": "micrOTOFcontrol",
                "cv_accession": "MS:1000726",
            },
            {
                "id": "tdf2mzml",
                "version": "0.5.0",
                "cv_name": "custom unreleased software tool",
                "cv_accession": "MS:1000799",
                "cv_value": "tdf2mzml",
                "user_params": [{"name": "python", "value": "3.12.0"}],
            },
        ]
        return xe.software_list(entries)

    def test_software_list_has_accessions(self, software_xml: bytes) -> None:
        params = _find_all_cvparams(software_xml)
        assert len(params) == 3
        for p in params:
            assert "accession" in p
            assert p["accession"].startswith("MS:")

    def test_tims_sdk_accession(self, software_xml: bytes) -> None:
        params = _find_all_cvparams(software_xml)
        bruker = [p for p in params if p.get("name") == "Bruker software"]
        assert len(bruker) == 1
        assert bruker[0]["accession"] == "MS:1000692"

    def test_microtofcontrol_accession(self, software_xml: bytes) -> None:
        params = _find_all_cvparams(software_xml)
        otof = [p for p in params if p.get("name") == "micrOTOFcontrol"]
        assert len(otof) == 1
        assert otof[0]["accession"] == "MS:1000726"

    def test_tdf2mzml_entry(self, software_xml: bytes) -> None:
        params = _find_all_cvparams(software_xml)
        tool = [p for p in params if p.get("name") == "custom unreleased software tool"]
        assert len(tool) == 1
        assert tool[0]["accession"] == "MS:1000799"
        assert tool[0]["value"] == "tdf2mzml"

    def test_tdf2mzml_has_python_userparam(self, software_xml: bytes) -> None:
        text = software_xml.decode()
        assert 'name="python"' in text
        assert 'value="3.12.0"' in text

    def test_tims_sdk_has_name_userparam(self, software_xml: bytes) -> None:
        text = software_xml.decode()
        assert 'name="software name"' in text
        assert 'value="TIMS SDK"' in text


# ===================================================================
# Instrument configuration
# ===================================================================


class TestInstrumentConfig:
    """Instrument configuration must have correct CV accessions."""

    @pytest.fixture
    def instrument_xml(self) -> bytes:
        return xe.instrument_configuration_list(
            serial_number="12345",
            instrument_name="timsTOF Pro",
            instrument_vendor="Bruker",
        )

    def test_instrument_model_accession(self, instrument_xml: bytes) -> None:
        params = _find_all_cvparams(instrument_xml)
        model = [p for p in params if p.get("name") == "Bruker Daltonics instrument model"]
        assert len(model) == 1
        assert model[0]["accession"] == "MS:1000122"

    def test_serial_number_accession(self, instrument_xml: bytes) -> None:
        params = _find_all_cvparams(instrument_xml)
        serial = [p for p in params if p.get("name") == "instrument serial number"]
        assert len(serial) == 1
        assert serial[0]["accession"] == "MS:1000529"
        assert serial[0]["value"] == "12345"

    def test_nanospray_accession(self, instrument_xml: bytes) -> None:
        params = _find_all_cvparams(instrument_xml)
        ns = [p for p in params if p.get("name") == "nanospray inlet"]
        assert len(ns) == 1
        assert ns[0]["accession"] == "MS:1000485"

    def test_esi_accession(self, instrument_xml: bytes) -> None:
        params = _find_all_cvparams(instrument_xml)
        esi = [p for p in params if p.get("name") == "electrospray ionization"]
        assert len(esi) == 1
        assert esi[0]["accession"] == "MS:1000073"

    def test_quadrupole_accession(self, instrument_xml: bytes) -> None:
        params = _find_all_cvparams(instrument_xml)
        q = [p for p in params if p.get("name") == "quadrupole"]
        assert len(q) == 1
        assert q[0]["accession"] == "MS:1000081"

    def test_tof_accession(self, instrument_xml: bytes) -> None:
        params = _find_all_cvparams(instrument_xml)
        tof = [p for p in params if p.get("name") == "time-of-flight"]
        assert len(tof) == 1
        assert tof[0]["accession"] == "MS:1000084"

    def test_mcp_detector_accession(self, instrument_xml: bytes) -> None:
        params = _find_all_cvparams(instrument_xml)
        mcp = [p for p in params if p.get("name") == "microchannel plate detector"]
        assert len(mcp) == 1
        assert mcp[0]["accession"] == "MS:1000114"

    def test_photomultiplier_present(self, instrument_xml: bytes) -> None:
        params = _find_all_cvparams(instrument_xml)
        pmt = [p for p in params if p.get("name") == "photomultiplier"]
        assert len(pmt) == 1
        assert pmt[0]["accession"] == "MS:1000116"

    def test_instrument_userparams(self, instrument_xml: bytes) -> None:
        text = instrument_xml.decode()
        assert 'name="instrument model"' in text
        assert 'value="timsTOF Pro"' in text
        assert 'name="instrument vendor"' in text
        assert 'value="Bruker"' in text


# ===================================================================
# File description
# ===================================================================


class TestFileDescription:
    """File description must have correct CV accessions."""

    @pytest.fixture
    def filedesc_xml(self) -> bytes:
        sources = [
            {
                "id": "test__analysis.tdf",
                "name": "analysis.tdf",
                "location": "/data",
                "sha1": "abc123def456",
            },
        ]
        return xe.file_description(sources)

    def test_ms1_spectrum_accession(self, filedesc_xml: bytes) -> None:
        params = _find_all_cvparams(filedesc_xml)
        ms1 = [p for p in params if p.get("name") == "MS1 spectrum"]
        assert len(ms1) == 1
        assert ms1[0]["accession"] == "MS:1000579"

    def test_msn_spectrum_accession(self, filedesc_xml: bytes) -> None:
        params = _find_all_cvparams(filedesc_xml)
        msn = [p for p in params if p.get("name") == "MSn spectrum"]
        assert len(msn) == 1
        assert msn[0]["accession"] == "MS:1000580"

    def test_sha1_accession(self, filedesc_xml: bytes) -> None:
        params = _find_all_cvparams(filedesc_xml)
        sha = [p for p in params if p.get("name") == "SHA-1"]
        assert len(sha) == 1
        assert sha[0]["accession"] == "MS:1000569"
        assert sha[0]["value"] == "abc123def456"

    def test_tdf_format_accession(self, filedesc_xml: bytes) -> None:
        params = _find_all_cvparams(filedesc_xml)
        tdf = [p for p in params if p.get("name") == "Bruker TDF format"]
        assert len(tdf) == 1
        assert tdf[0]["accession"] == "MS:1002817"

    def test_native_id_format_accession(self, filedesc_xml: bytes) -> None:
        params = _find_all_cvparams(filedesc_xml)
        nid = [p for p in params if p.get("name") == "Bruker TDF nativeID format"]
        assert len(nid) == 1
        assert nid[0]["accession"] == "MS:1002818"


# ===================================================================
# Data processing
# ===================================================================


class TestDataProcessing:
    """Data processing list must have conversion CV accession."""

    def test_conversion_accession(self) -> None:
        xml_bytes = xe.data_processing_list("0.5.0")
        params = _find_all_cvparams(xml_bytes)
        conv = [p for p in params if p.get("name") == "Conversion to mzML"]
        assert len(conv) == 1
        assert conv[0]["accession"] == "MS:1000544"


# ===================================================================
# MS2 precursor structure
# ===================================================================


class TestPrecursorStructure:
    """MS2 precursor section must have correct accessions and units."""

    def test_isolation_window_target_accession(self, ms2_spectrum_bytes: bytes) -> None:
        params = _find_all_cvparams(ms2_spectrum_bytes)
        target = [p for p in params if p.get("name") == "isolation window target m/z"]
        assert len(target) == 1
        assert target[0]["accession"] == "MS:1000827"
        assert target[0]["unitAccession"] == "MS:1000040"

    def test_isolation_window_offsets(self, ms2_spectrum_bytes: bytes) -> None:
        params = _find_all_cvparams(ms2_spectrum_bytes)
        lower = [p for p in params if p.get("name") == "isolation window lower offset"]
        upper = [p for p in params if p.get("name") == "isolation window upper offset"]
        assert len(lower) == 1
        assert lower[0]["accession"] == "MS:1000828"
        assert len(upper) == 1
        assert upper[0]["accession"] == "MS:1000829"

    def test_selected_ion_mz(self, ms2_spectrum_bytes: bytes) -> None:
        params = _find_all_cvparams(ms2_spectrum_bytes)
        ion = [p for p in params if p.get("name") == "selected ion m/z"]
        assert len(ion) == 1
        assert ion[0]["accession"] == "MS:1000744"
        assert ion[0]["unitAccession"] == "MS:1000040"

    def test_charge_state(self, ms2_spectrum_bytes: bytes) -> None:
        params = _find_all_cvparams(ms2_spectrum_bytes)
        charge = [p for p in params if p.get("name") == "charge state"]
        assert len(charge) == 1
        assert charge[0]["accession"] == "MS:1000041"
        assert charge[0]["value"] == "2"

    def test_collision_induced_dissociation(self, ms2_spectrum_bytes: bytes) -> None:
        params = _find_all_cvparams(ms2_spectrum_bytes)
        cid = [p for p in params if p.get("name") == "collision-induced dissociation"]
        assert len(cid) == 1
        assert cid[0]["accession"] == "MS:1000133"

    def test_collision_energy(self, ms2_spectrum_bytes: bytes) -> None:
        params = _find_all_cvparams(ms2_spectrum_bytes)
        ce = [p for p in params if p.get("name") == "collision energy"]
        assert len(ce) == 1
        assert ce[0]["accession"] == "MS:1000045"
        assert ce[0]["unitAccession"] == "UO:0000266"
        assert ce[0]["unitCvRef"] == "UO"


# ===================================================================
# Ion mobility — scan-level and array
# ===================================================================


class TestIonMobility:
    """Ion mobility cvParams must have correct accessions."""

    def test_scan_level_ook0(self, ms1_spectrum_bytes: bytes) -> None:
        params = _find_all_cvparams(ms1_spectrum_bytes)
        ook0 = [p for p in params if p.get("name") == "mean inverse reduced ion mobility"]
        assert len(ook0) == 1
        assert ook0[0]["accession"] == "MS:1002814"
        assert ook0[0]["unitName"] == "volt-second per square centimeter"

    def test_im_array_accession(self, ms1_with_im_array_bytes: bytes) -> None:
        params = _find_all_cvparams(ms1_with_im_array_bytes)
        im_arr = [p for p in params if p.get("name") == "mean inverse reduced ion mobility array"]
        assert len(im_arr) == 1
        assert im_arr[0]["accession"] == "MS:1002816"

    def test_im_window_limits(self, ms1_with_im_array_bytes: bytes) -> None:
        params = _find_all_cvparams(ms1_with_im_array_bytes)
        lower = [p for p in params if p.get("name") == "inverse reduced ion mobility lower limit"]
        upper = [p for p in params if p.get("name") == "inverse reduced ion mobility upper limit"]
        assert len(lower) == 1
        assert lower[0]["accession"] == "MS:1002476"
        assert len(upper) == 1
        assert upper[0]["accession"] == "MS:1002477"


# ===================================================================
# Spectrum-level CV terms
# ===================================================================


class TestSpectrumCvTerms:
    """Spectrum-level CV terms must have correct accessions."""

    def test_ms_level_accession(self, ms1_spectrum_bytes: bytes) -> None:
        params = _find_all_cvparams(ms1_spectrum_bytes)
        level = [p for p in params if p.get("name") == "ms level"]
        assert len(level) == 1
        assert level[0]["accession"] == "MS:1000511"
        assert level[0]["value"] == "1"

    def test_centroid_spectrum_accession(self, ms1_spectrum_bytes: bytes) -> None:
        params = _find_all_cvparams(ms1_spectrum_bytes)
        cs = [p for p in params if p.get("name") == "centroid spectrum"]
        assert len(cs) == 1
        assert cs[0]["accession"] == "MS:1000127"

    def test_positive_scan_accession(self, ms1_spectrum_bytes: bytes) -> None:
        params = _find_all_cvparams(ms1_spectrum_bytes)
        ps = [p for p in params if p.get("name") == "positive scan"]
        assert len(ps) == 1
        assert ps[0]["accession"] == "MS:1000130"

    def test_tic_accession(self, ms1_spectrum_bytes: bytes) -> None:
        params = _find_all_cvparams(ms1_spectrum_bytes)
        tic = [p for p in params if p.get("name") == "total ion current"]
        assert len(tic) == 1
        assert tic[0]["accession"] == "MS:1000285"

    def test_base_peak_mz_accession(self, ms1_spectrum_bytes: bytes) -> None:
        params = _find_all_cvparams(ms1_spectrum_bytes)
        bp = [p for p in params if p.get("name") == "base peak m/z"]
        assert len(bp) == 1
        assert bp[0]["accession"] == "MS:1000504"

    def test_base_peak_intensity_accession(self, ms1_spectrum_bytes: bytes) -> None:
        params = _find_all_cvparams(ms1_spectrum_bytes)
        bp = [p for p in params if p.get("name") == "base peak intensity"]
        assert len(bp) == 1
        assert bp[0]["accession"] == "MS:1000505"

    def test_no_combination_accession(self, ms1_spectrum_bytes: bytes) -> None:
        params = _find_all_cvparams(ms1_spectrum_bytes)
        nc = [p for p in params if p.get("name") == "no combination"]
        assert len(nc) == 1
        assert nc[0]["accession"] == "MS:1000795"

    def test_scan_start_time_accession(self, ms1_spectrum_bytes: bytes) -> None:
        params = _find_all_cvparams(ms1_spectrum_bytes)
        sst = [p for p in params if p.get("name") == "scan start time"]
        assert len(sst) == 1
        assert sst[0]["accession"] == "MS:1000016"

    def test_scan_window_lower_accession(self, ms1_spectrum_bytes: bytes) -> None:
        params = _find_all_cvparams(ms1_spectrum_bytes)
        sw = [p for p in params if p.get("name") == "scan window lower limit"]
        assert len(sw) == 1
        assert sw[0]["accession"] == "MS:1000501"

    def test_scan_window_upper_accession(self, ms1_spectrum_bytes: bytes) -> None:
        params = _find_all_cvparams(ms1_spectrum_bytes)
        sw = [p for p in params if p.get("name") == "scan window upper limit"]
        assert len(sw) == 1
        assert sw[0]["accession"] == "MS:1000500"

    def test_mz_array_accession(self, ms1_spectrum_bytes: bytes) -> None:
        params = _find_all_cvparams(ms1_spectrum_bytes)
        mza = [p for p in params if p.get("name") == "m/z array"]
        assert len(mza) == 1
        assert mza[0]["accession"] == "MS:1000514"

    def test_intensity_array_accession(self, ms1_spectrum_bytes: bytes) -> None:
        params = _find_all_cvparams(ms1_spectrum_bytes)
        ia = [p for p in params if p.get("name") == "intensity array"]
        assert len(ia) == 1
        assert ia[0]["accession"] == "MS:1000515"

    def test_64bit_float_accession(self, ms1_spectrum_bytes: bytes) -> None:
        params = _find_all_cvparams(ms1_spectrum_bytes)
        f64 = [p for p in params if p.get("name") == "64-bit float"]
        assert len(f64) == 1
        assert f64[0]["accession"] == "MS:1000523"

    def test_32bit_float_accession(self, ms1_spectrum_bytes: bytes) -> None:
        params = _find_all_cvparams(ms1_spectrum_bytes)
        f32 = [p for p in params if p.get("name") == "32-bit float"]
        assert len(f32) == 1
        assert f32[0]["accession"] == "MS:1000521"

    def test_no_compression_accession(self, ms1_spectrum_bytes: bytes) -> None:
        params = _find_all_cvparams(ms1_spectrum_bytes)
        nc = [p for p in params if p.get("name") == "no compression"]
        assert len(nc) == 2, "Expected 2 (one per binary array: mz + intensity)"
        for p in nc:
            assert p["accession"] == "MS:1000576"

    def test_zlib_compression_accession(self, ms2_spectrum_bytes: bytes) -> None:
        params = _find_all_cvparams(ms2_spectrum_bytes)
        zc = [p for p in params if p.get("name") == "zlib compression"]
        assert len(zc) >= 1
        assert zc[0]["accession"] == "MS:1000574"
