"""BafReader: high-level interface over a Bruker BAF .d analysis directory.

Wraps :class:`~tdf2mzml.io.bafdata.BafData` (binary SDK + SQLite) behind a
typed API mirroring :class:`~tdf2mzml.io.tsf_reader.TsfReader`.  No TDF/TIMS
concepts (frames, ion mobility) apply here — BAF is a standard LC-MS format.
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

import numpy as np
import numpy.typing as npt

from tdf2mzml.io.bafdata import BafData
from tdf2mzml.models.metadata import AcquisitionMetadata

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# AcquisitionKeys.Polarity
BAF_POLARITY_POSITIVE = 0
BAF_POLARITY_NEGATIVE = 1

# AcquisitionKeys.MsLevel
BAF_MS_LEVEL_MS1 = 0
BAF_MS_LEVEL_MS2 = 1

# SupportedVariables PermanentNames for per-spectrum acquisition parameters.
# These are stable across instrument generations.
_PNAME_COLLISION_ENERGY = "Collision_Energy_Act"
_PNAME_ISOLATION_WIDTH = {
    "Precursor_IsolationWidth",
    "Quadrupole_IsolationResolution_Act",
}


# ---------------------------------------------------------------------------
# BafReader
# ---------------------------------------------------------------------------


class BafReader:
    """Reader for a Bruker BAF ``.d`` analysis directory.

    Parameters
    ----------
    path : Path or str
        Path to the ``.d`` directory containing ``analysis.baf``.

    Examples
    --------
    >>> with BafReader("/data/sample.d") as reader:
    ...     meta = reader.metadata
    ...     spectra = reader.get_all_spectra()
    """

    def __init__(self, path: Path | str) -> None:
        p = Path(path)
        # Accept either a direct .baf file or a .d directory containing analysis.baf
        if p.suffix == ".baf" and p.is_file():
            baf_file = p
            self._path = p.parent
        else:
            baf_file = p / "analysis.baf"
            if not baf_file.exists():
                raise FileNotFoundError(f"analysis.baf not found in {p}")
            self._path = p
        self._baf = BafData(baf_file)
        self._metadata: AcquisitionMetadata | None = None
        # Variable IDs resolved from SupportedVariables at open time
        self._var_collision_energy: int | None = None
        self._var_isolation_width: int | None = None
        self._resolve_variable_ids()

    def _resolve_variable_ids(self) -> None:
        """Look up variable IDs for collision energy and isolation width."""
        try:
            rows = self._baf.conn.execute(
                "SELECT Variable, PermanentName FROM SupportedVariables"
            ).fetchall()
            for var_id, name in rows:
                if name == _PNAME_COLLISION_ENERGY:
                    self._var_collision_energy = int(var_id)
                elif name in _PNAME_ISOLATION_WIDTH:
                    self._var_isolation_width = int(var_id)
        except sqlite3.OperationalError:
            pass  # SupportedVariables absent in some BAF versions

    def close(self) -> None:
        """Release all SDK resources."""
        self._baf.close()

    def __enter__(self) -> BafReader:
        """Enter context manager."""
        return self

    def __exit__(self, *_: object) -> None:
        """Exit context manager and release resources."""
        self.close()

    # ------------------------------------------------------------------
    # Metadata
    # ------------------------------------------------------------------

    @property
    def metadata(self) -> AcquisitionMetadata:
        """All acquisition metadata, lazily loaded on first access.

        Returns
        -------
        AcquisitionMetadata
            Frozen Pydantic model populated from the BAF ``Properties``
            and ``Spectra`` tables.
        """
        if self._metadata is None:
            self._metadata = self._load_metadata()
        return self._metadata

    def _load_metadata(self) -> AcquisitionMetadata:
        conn = self._baf.conn

        def _prop(key: str, default: str = "") -> str:
            row = conn.execute("SELECT Value FROM Properties WHERE Key=?", (key,)).fetchone()
            return str(row[0]) if row and row[0] is not None else default

        # Spectrum counts
        total = conn.execute("SELECT COUNT(*) FROM Spectra").fetchone()[0]
        ms1_count = conn.execute(
            "SELECT COUNT(*) FROM Spectra s "
            "JOIN AcquisitionKeys ak ON s.AcquisitionKey=ak.Id "
            "WHERE ak.MsLevel=0"
        ).fetchone()[0]
        ms2_count = conn.execute(
            "SELECT COUNT(*) FROM Spectra s "
            "JOIN AcquisitionKeys ak ON s.AcquisitionKey=ak.Id "
            "WHERE ak.MsLevel>=1"
        ).fetchone()[0]

        # m/z range from first MS1 spectrum
        mz_row = conn.execute(
            "SELECT s.MzAcqRangeLower, s.MzAcqRangeUpper FROM Spectra s "
            "JOIN AcquisitionKeys ak ON s.AcquisitionKey=ak.Id "
            "WHERE ak.MsLevel=0 LIMIT 1"
        ).fetchone()
        mz_lower = float(mz_row[0]) if mz_row and mz_row[0] is not None else 0.0
        mz_upper = float(mz_row[1]) if mz_row and mz_row[1] is not None else 2000.0

        return AcquisitionMetadata(
            schema_type="BAF",
            schema_version_major=0,
            schema_version_minor=0,
            acq_software=_prop("AcquisitionSoftware", "micrOTOFcontrol"),
            acq_software_version=_prop("AcquisitionSoftwareVersion"),
            acq_firmware_version="",
            acq_software_vendor=_prop("AcquisitionSoftwareVendor", "Bruker"),
            acq_date_time=_prop("AcquisitionDateTime"),
            instrument_name=_prop("InstrumentName"),
            instrument_family=_prop("InstrumentFamily"),
            instrument_serial_number=_prop("InstrumentSerialNumber"),
            instrument_revision=0,
            instrument_source_type=0,
            instrument_vendor=_prop("InstrumentVendor", "Bruker"),
            operator_name=_prop("OperatorName"),
            sample_name=_prop("SampleName"),
            description=_prop("Description"),
            method_name=_prop("MethodName"),
            analysis_id=_prop("AnalysisId"),
            closed_properly=True,
            mz_acq_range_lower=mz_lower,
            mz_acq_range_upper=mz_upper,
            one_over_k0_range_lower=0.0,
            one_over_k0_range_upper=0.0,
            frame_count=int(total),
            ms1_spectra_count=int(ms1_count),
            ms2_dda_count=int(ms2_count),
            ms2_dia_count=0,
            total_spectra=int(total),
            has_pasef_dda=ms2_count > 0,
            has_pasef_dia=False,
        )

    # ------------------------------------------------------------------
    # Spectrum enumeration
    # ------------------------------------------------------------------

    def get_all_spectra(
        self,
    ) -> list[
        tuple[
            int,
            float,
            int | None,
            float,
            float,
            int | None,
            int | None,
            int | None,
            int | None,
            int,
            int,
        ]
    ]:
        """Return all spectra ordered by Id.

        Each row:
        ``(Id, Rt, Parent, MzAcqRangeLower, MzAcqRangeUpper,
           LineMzId, LineIntensityId, ProfileMzId, ProfileIntensityId,
           MsLevel, Polarity)``
        """
        return self._baf.conn.execute(
            "SELECT s.Id, s.Rt, s.Parent, s.MzAcqRangeLower, s.MzAcqRangeUpper, "
            "s.LineMzId, s.LineIntensityId, s.ProfileMzId, s.ProfileIntensityId, "
            "ak.MsLevel, ak.Polarity "
            "FROM Spectra s "
            "JOIN AcquisitionKeys ak ON s.AcquisitionKey=ak.Id "
            "ORDER BY s.Id"
        ).fetchall()

    # ------------------------------------------------------------------
    # MS2 precursor info
    # ------------------------------------------------------------------

    def get_ms2_precursor_batch(
        self, spectrum_ids: list[int]
    ) -> dict[int, dict[str, float | None]]:
        """Return precursor info for a batch of MS2 spectrum IDs.

        Queries the ``Steps`` table for precursor mass and the ``Variables``
        view for collision energy and isolation width (where available).

        Parameters
        ----------
        spectrum_ids : list of int
            MS2 spectrum IDs to look up.

        Returns
        -------
        dict
            ``{spectrum_id: {"mass": float, "collision_energy": float|None,
            "isolation_width": float|None}}``
        """
        if not spectrum_ids:
            return {}

        placeholders = ",".join("?" * len(spectrum_ids))

        # Precursor mass from Steps — take the first fragmentation step per spectrum
        # (Number is 0-indexed on some instruments, 1-indexed on others)
        steps_rows = self._baf.conn.execute(
            f"SELECT TargetSpectrum, Mass FROM Steps "
            f"WHERE TargetSpectrum IN ({placeholders}) "
            f"AND Number = (SELECT MIN(Number) FROM Steps s2 "
            f"WHERE s2.TargetSpectrum = Steps.TargetSpectrum)",
            spectrum_ids,
        ).fetchall()
        result: dict[int, dict[str, float | None]] = {}
        for spec_id, mass in steps_rows:
            result[int(spec_id)] = {
                "mass": float(mass) if mass is not None else 0.0,
                "collision_energy": None,
                "isolation_width": None,
            }

        # Collision energy and isolation width from Variables view
        var_ids: list[int] = []
        if self._var_collision_energy is not None:
            var_ids.append(self._var_collision_energy)
        if self._var_isolation_width is not None:
            var_ids.append(self._var_isolation_width)

        if var_ids and result:
            v_ph = ",".join("?" * len(var_ids))
            s_ph = ",".join("?" * len(spectrum_ids))
            try:
                var_rows = self._baf.conn.execute(
                    f"SELECT Spectrum, Variable, Value FROM Variables "
                    f"WHERE Spectrum IN ({s_ph}) AND Variable IN ({v_ph})",
                    (*spectrum_ids, *var_ids),
                ).fetchall()
                for spec_id, var_id, value in var_rows:
                    sid = int(spec_id)
                    if sid not in result:
                        continue
                    if value is None:
                        continue
                    if var_id == self._var_collision_energy:
                        result[sid]["collision_energy"] = float(value)
                    elif var_id == self._var_isolation_width:
                        result[sid]["isolation_width"] = float(value)
            except sqlite3.OperationalError:
                pass  # Variables view may not be populated

        return result

    # ------------------------------------------------------------------
    # Spectrum data
    # ------------------------------------------------------------------

    def read_line_spectrum(
        self, mz_id: int, int_id: int
    ) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.float32]]:
        """Read a centroid (line) spectrum from binary storage.

        Parameters
        ----------
        mz_id : int
            ``LineMzId`` from the Spectra table row.
        int_id : int
            ``LineIntensityId`` from the Spectra table row.

        Returns
        -------
        tuple of (ndarray, ndarray)
            m/z (float64) and intensity (float32) arrays.
        """
        mz = self._baf.read_array_double(mz_id)
        intensity = self._baf.read_array_double(int_id).astype(np.float32)
        return mz, intensity

    def read_profile_spectrum(
        self, mz_id: int, int_id: int
    ) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.float32]]:
        """Read a profile spectrum from binary storage.

        Parameters
        ----------
        mz_id : int
            ``ProfileMzId`` from the Spectra table row.
        int_id : int
            ``ProfileIntensityId`` from the Spectra table row.

        Returns
        -------
        tuple of (ndarray, ndarray)
            m/z (float64) and intensity (float32) arrays.
        """
        mz = self._baf.read_array_double(mz_id)
        intensity = self._baf.read_array_double(int_id).astype(np.float32)
        return mz, intensity
