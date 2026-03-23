"""IndexedMzMLWriter: produces fully indexed mzML 1.1.0 output files.

Writes ``<indexedmzML>`` with a byte-offset ``<index>`` section enabling
random-access tools (OpenMS, Skyline, MSConvert, etc.) to seek directly to
any spectrum without scanning the entire file.
"""

import hashlib
import logging
from pathlib import Path
from platform import python_version
from typing import Literal

import numpy as np
import numpy.typing as npt

from tdf2mzml import __version__
from tdf2mzml.constants import SDK_VERSION
from tdf2mzml.models.metadata import AcquisitionMetadata
from tdf2mzml.models.spectrum import PrecursorInfo, SpectrumArrays
from tdf2mzml.output import xml_elements as xe
from tdf2mzml.utils import sha1_checksum

logger = logging.getLogger(__name__)


class IndexedMzMLWriter:
    """Write a fully indexed mzML 1.1.0 file without psims.

    Opens the output file on construction and keeps it open until
    :meth:`finalize` is called (or the context manager exits).

    Parameters
    ----------
    output_path : Path or str
        Destination ``.mzML`` file path.
    metadata : AcquisitionMetadata
        Instrument and acquisition metadata read from the TDF.
    input_path : Path or str
        Path to the source ``.d`` directory (used for source file entries).
    compression : {"none", "zlib"}
        Binary array compression for all spectra. Default ``"none"``.
    total_spectra : int
        Total spectrum count declared in ``<spectrumList count="N">``.

    Examples
    --------
    >>> with IndexedMzMLWriter(out, metadata, src) as writer:
    ...     writer.write_ms1_spectrum(...)
    ...     writer.write_ms2_spectrum(...)
    """

    def __init__(
        self,
        output_path: Path | str,
        metadata: AcquisitionMetadata,
        input_path: Path | str,
        compression: Literal["none", "zlib"] = "none",
        total_spectra: int = 0,
        checksum_source_files: bool = False,
    ) -> None:
        self._path = Path(output_path)
        self._metadata = metadata
        self._input_path = Path(input_path)
        self._compression = compression
        self._total_spectra = total_spectra
        self._checksum_source_files = checksum_source_files
        self._fh = open(self._path, "wb")  # noqa: SIM115  # must stay open across calls
        self._buf = bytearray()            # write buffer — flushed in FLUSH_SIZE chunks
        self._disk_pos: int = 0           # bytes physically written to disk
        self._sha1 = hashlib.sha1()       # incremental hash — avoids read-back in finalize
        self._offsets: list[tuple[str, int]] = []   # (spectrum_id, byte_offset)
        self._spectrum_index: int = 0
        self._run_open_offset: int = 0
        self._spectrum_list_open_offset: int = 0

    _FLUSH_SIZE: int = 4 * 1024 * 1024  # 4 MB write buffer

    def __enter__(self) -> "IndexedMzMLWriter":
        """Write the mzML header and return self."""
        self._write_header()
        return self

    def __exit__(self, *_: object) -> None:
        """Finalise and close the output file on context manager exit."""
        self.finalize()

    # ------------------------------------------------------------------
    # Header
    # ------------------------------------------------------------------

    def _write_header(self) -> None:
        """Write all mzML header sections up to (but not including) spectrumList."""
        meta = self._metadata
        inp = self._input_path

        # Support TDF, TSF, and BAF source file names
        if (inp / "analysis.tsf").exists():
            db_name = "analysis.tsf"
            bin_name = "analysis.tsf_bin"
        elif (inp / "analysis.baf").exists():
            db_name = "analysis.baf"
            bin_name = "analysis.baf"  # BAF has no separate bin file
        else:
            db_name = "analysis.tdf"
            bin_name = "analysis.tdf_bin"

        db_path = inp / db_name
        bin_path = inp / bin_name

        def _src_sha1(p: Path) -> str:
            if self._checksum_source_files and p.exists():
                return sha1_checksum(str(p))
            return ""

        source_files = [
            {
                "id": str(db_path).replace("/", "__"),
                "name": db_name,
                "location": str(inp),
                "sha1": _src_sha1(db_path),
            },
            {
                "id": str(bin_path).replace("/", "__"),
                "name": bin_name,
                "location": str(inp),
                "sha1": _src_sha1(bin_path),
            },
        ]

        software_entries = [
            {"id": "TIMS_SDK", "version": SDK_VERSION, "cv_name": "Bruker software"},
            {
                "id": meta.acq_software,
                "version": meta.acq_software_version,
                "cv_name": "micrOTOFcontrol",
            },
            {
                "id": "tdf2mzml",
                "version": __version__,
                "cv_name": f"python {python_version()}",
            },
        ]

        self._write(xe.xml_declaration())
        self._write(xe.indexed_mzml_open())
        self._write(xe.mzml_open(self._total_spectra))
        self._write(xe.cv_list())
        self._write(xe.file_description(source_files))
        self._write(xe.software_list(software_entries))
        self._write(xe.instrument_configuration_list(
            meta.instrument_serial_number,
            instrument_name=meta.instrument_name,
            instrument_vendor=meta.instrument_vendor,
        ))
        self._write(xe.sample_list(meta.sample_name, description=meta.description))
        self._write(xe.data_processing_list(__version__))

        # Build a safe run ID from sample name or fall back to analysis_id / "1"
        run_id = (
            meta.sample_name.replace(" ", "_").replace("/", "_") or
            meta.analysis_id or
            "1"
        )
        # Warn if acquisition was not closed cleanly
        if not meta.closed_properly:
            logger.warning(
                "TDF file was not closed properly (ClosedProperly=0) — "
                "data may be truncated or corrupt."
            )

        run_attrs = (
            f'id="{run_id}" '
            f'defaultInstrumentConfigurationRef="IC1" '
            f'defaultSourceFileRef="{source_files[0]["id"]}" '
            f'sampleRef="S1" '
            f'startTimeStamp="{meta.acq_date_time}"'
        )
        # Embed operator name and method as userParams on the run element
        operator_param = (
            f'\n      <userParam name="contact name" value="{meta.operator_name}"/>'
            if meta.operator_name
            else ""
        )
        method_param = (
            f'\n      <userParam name="acquisition method" value="{meta.method_name}"/>'
            if meta.method_name
            else ""
        )
        run_line = (
            f'    <run {run_attrs}>{operator_param}{method_param}\n'
        ).encode()
        self._write(run_line)

        # Open spectrumList
        sl_line = (
            f'      <spectrumList count="{self._total_spectra}" '
            f'defaultDataProcessingRef="tdf2mzml_conversion">\n'
        ).encode()
        self._write(sl_line)

    # ------------------------------------------------------------------
    # Spectrum writing
    # ------------------------------------------------------------------

    def write_ms1_spectrum(
        self,
        arrays: SpectrumArrays,
        scan_start_time: float,
        centroided: bool,
        one_over_k0: float | None = None,
        ion_mobility_array: npt.NDArray[np.float64] | None = None,
        polarity: str | None = None,
    ) -> str:
        """Write a single MS1 spectrum to the output file.

        Parameters
        ----------
        arrays : SpectrumArrays
            m/z and intensity arrays for the spectrum.
        scan_start_time : float
            Scan start time in minutes.
        centroided : bool
            True for centroid, False for profile output.
        one_over_k0 : float or None, optional
            Mean inverse reduced ion mobility for this spectrum.
        ion_mobility_array : numpy.ndarray or None, optional
            Per-peak mean 1/K0 array (``"array"`` IM mode only).
        polarity : str or None, optional
            Scan polarity CV term name (``"positive scan"`` or
            ``"negative scan"``).  None omits the polarity CV param.

        Returns
        -------
        str
            The spectrum ID string assigned to this spectrum.
        """
        spectrum_id = f"index={self._spectrum_index}"
        return self._write_spectrum(
            spectrum_id=spectrum_id,
            ms_level=1,
            centroided=centroided,
            arrays=arrays,
            scan_start_time=scan_start_time,
            one_over_k0=one_over_k0,
            ion_mobility_array=ion_mobility_array,
            polarity=polarity,
        )

    def write_ms2_spectrum(
        self,
        arrays: SpectrumArrays,
        scan_start_time: float,
        precursor: PrecursorInfo,
        one_over_k0: float | None = None,
        polarity: str | None = None,
    ) -> str:
        """Write a single MS2 spectrum to the output file.

        Parameters
        ----------
        arrays : SpectrumArrays
            m/z and intensity arrays for the spectrum.
        scan_start_time : float
            Scan start time in minutes.
        precursor : PrecursorInfo
            Precursor ion metadata.
        one_over_k0 : float or None, optional
            Mean 1/K0 for this spectrum (falls back to
            ``precursor.one_over_k0`` if None).
        polarity : str or None, optional
            Scan polarity CV term name (``"positive scan"`` or
            ``"negative scan"``).  None omits the polarity CV param.

        Returns
        -------
        str
            The spectrum ID string assigned to this spectrum.
        """
        spectrum_id = f"index={self._spectrum_index}"
        ook0 = one_over_k0 if one_over_k0 is not None else precursor.one_over_k0
        return self._write_spectrum(
            spectrum_id=spectrum_id,
            ms_level=2,
            centroided=True,
            arrays=arrays,
            scan_start_time=scan_start_time,
            one_over_k0=ook0,
            precursor=precursor,
            polarity=polarity,
        )

    def _write_spectrum(
        self,
        spectrum_id: str,
        ms_level: int,
        centroided: bool,
        arrays: SpectrumArrays,
        scan_start_time: float,
        one_over_k0: float | None = None,
        ion_mobility_array: npt.NDArray[np.float64] | None = None,
        precursor: PrecursorInfo | None = None,
        polarity: str | None = None,
    ) -> str:
        """Render and write a spectrum element, recording its byte offset.

        Returns
        -------
        str
            Spectrum ID.
        """
        meta = self._metadata

        if arrays.is_empty:
            tic = 0.0
            bp_mz = 0.0
            bp_int = 0.0
        else:
            tic = float(np.sum(arrays.intensity))
            bp_idx = int(np.argmax(arrays.intensity))
            bp_mz = float(arrays.mz[bp_idx])
            bp_int = float(arrays.intensity[bp_idx])

        offset = self._tell()
        self._offsets.append((spectrum_id, offset))

        block = xe.spectrum_element(
            spectrum_id=spectrum_id,
            index=self._spectrum_index,
            ms_level=ms_level,
            centroided=centroided,
            scan_start_time=scan_start_time,
            mz_array=arrays.mz,
            intensity_array=arrays.intensity,
            scan_window_lower=meta.mz_acq_range_lower,
            scan_window_upper=meta.mz_acq_range_upper,
            compression=self._compression,
            total_ion_current=tic,
            base_peak_mz=bp_mz,
            base_peak_intensity=bp_int,
            precursor_mz=precursor.mz if precursor else None,
            precursor_charge=precursor.charge if precursor else None,
            precursor_spectrum_ref=precursor.spectrum_reference if precursor else None,
            isolation_window_target=precursor.isolation_window_target if precursor else None,
            isolation_window_lower=precursor.isolation_window_lower if precursor else None,
            isolation_window_upper=precursor.isolation_window_upper if precursor else None,
            collision_energy=precursor.collision_energy if precursor else None,
            one_over_k0=one_over_k0,
            ion_mobility_array=ion_mobility_array,
            ook0_window_lower=meta.one_over_k0_range_lower or None,
            ook0_window_upper=meta.one_over_k0_range_upper or None,
            polarity=polarity,
        )
        self._write(block)
        self._spectrum_index += 1
        return spectrum_id

    # ------------------------------------------------------------------
    # Finalization
    # ------------------------------------------------------------------

    def finalize(self) -> None:
        """Close spectrumList, run, mzML; write index, checksum, close file."""
        if self._fh.closed:
            return

        # Close spectrumList and run
        self._write(b"      </spectrumList>\n")
        self._write(b"    </run>\n")
        self._write(b"  </mzML>\n")

        # Write index
        index_list_offset = self._tell()
        self._write(b'  <indexList count="1">\n')
        self._write(b'    <index name="spectrum">\n')
        for sid, off in self._offsets:
            self._write(
                f'      <offset idRef="{sid}">{off}</offset>\n'.encode()
            )
        self._write(b"    </index>\n")
        self._write(b"  </indexList>\n")

        # indexListOffset
        self._write(
            f"  <indexListOffset>{index_list_offset}</indexListOffset>\n".encode()
        )

        # Flush all buffered data so sha1 digest is complete
        self._flush()
        sha1_hex = self._sha1.hexdigest()

        # Write fileChecksum and closing tag directly — not part of the checksum
        tail = (
            f"  <fileChecksum>{sha1_hex}</fileChecksum>\n"
            "</indexedmzML>\n"
        ).encode()
        self._fh.write(tail)

        self._fh.close()
        logger.info("Wrote %d spectra to %s", self._spectrum_index, self._path)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _tell(self) -> int:
        """Return current virtual write position (disk + buffered bytes)."""
        return self._disk_pos + len(self._buf)

    def _flush(self) -> None:
        """Flush write buffer to disk."""
        if self._buf:
            self._fh.write(self._buf)
            self._disk_pos += len(self._buf)
            self._buf.clear()

    def _write(self, data: bytes) -> None:
        self._sha1.update(data)
        self._buf += data
        if len(self._buf) >= self._FLUSH_SIZE:
            self._flush()
