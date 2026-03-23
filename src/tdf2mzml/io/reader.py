"""TdfReader: high-level interface over the Bruker TDF SQLite database and SDK.

All SQL queries and SDK calls are centralised here.  Callers in
``processing/`` receive typed Python objects and never touch the raw
``sqlite3.Connection`` or the :class:`~tdf2mzml.io.timsdata.TimsData`
handle directly.
"""

import logging
from pathlib import Path

import numpy as np
import numpy.typing as npt

from tdf2mzml.constants import (
    META_ACQ_DATETIME,
    META_ACQ_FIRMWARE_VERSION,
    META_ACQ_SOFTWARE,
    META_ACQ_SOFTWARE_VENDOR,
    META_ACQ_SOFTWARE_VERSION,
    META_ANALYSIS_ID,
    META_CLOSED_PROPERLY,
    META_DESCRIPTION,
    META_INSTRUMENT_FAMILY,
    META_INSTRUMENT_NAME,
    META_INSTRUMENT_REVISION,
    META_INSTRUMENT_SERIAL,
    META_INSTRUMENT_SOURCE_TYPE,
    META_INSTRUMENT_VENDOR,
    META_METHOD_NAME,
    META_MZ_RANGE_LOWER,
    META_MZ_RANGE_UPPER,
    META_OOK0_RANGE_LOWER,
    META_OOK0_RANGE_UPPER,
    META_OPERATOR_NAME,
    META_SAMPLE_NAME,
    META_SCHEMA_TYPE,
    META_SCHEMA_VERSION_MAJOR,
    META_SCHEMA_VERSION_MINOR,
    MSMS_TYPE_MS1,
    MSMS_TYPE_PASEF_DDA,
    MSMS_TYPE_PASEF_DIA,
    PRECURSOR_COLUMNS,
)
from tdf2mzml.io.timsdata import PressureCompensationStrategy, TimsData
from tdf2mzml.models.metadata import AcquisitionMetadata, DiaWindow
from tdf2mzml.models.spectrum import PrecursorRow

logger = logging.getLogger(__name__)


class TdfReader:
    """Unified reader for a single Bruker ``.d`` / TDF dataset.

    Wraps :class:`~tdf2mzml.io.timsdata.TimsData` (binary SDK) and the
    SQLite ``analysis.tdf`` database (metadata + frame tables) behind a
    single, typed API.  Intended to be used as a context manager.

    Parameters
    ----------
    path : Path or str
        Path to the Bruker ``.d`` directory.
    pressure_compensation : PressureCompensationStrategy, optional
        Pressure compensation mode passed to the SDK. Default is no
        compensation.

    Examples
    --------
    >>> with TdfReader("/data/sample.d") as reader:
    ...     meta = reader.metadata
    ...     frames = reader.get_ms1_frames()
    """

    def __init__(
        self,
        path: Path | str,
        pressure_compensation: PressureCompensationStrategy = (
            PressureCompensationStrategy.NoPressureCompensation
        ),
    ) -> None:
        self._path = Path(path)
        self._tims = TimsData(
            str(self._path),
            pressure_compensation=pressure_compensation,
        )
        self._metadata: AcquisitionMetadata | None = None

    def close(self) -> None:
        """Close the SDK handle and SQLite connection."""
        self._tims.close()

    def __enter__(self) -> "TdfReader":
        """Return self for use as a context manager."""
        return self

    def __exit__(self, *_: object) -> None:
        """Close the reader on context manager exit."""
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
            Frozen Pydantic model populated from ``GlobalMetadata`` and
            frame count queries.
        """
        if self._metadata is None:
            self._metadata = self._build_metadata()
        return self._metadata

    def _build_metadata(self) -> AcquisitionMetadata:
        """Query the TDF database and construct :class:`AcquisitionMetadata`.

        Returns
        -------
        AcquisitionMetadata
        """
        conn = self._tims.conn

        # Read entire GlobalMetadata table in one query
        raw: dict[str, str] = {
            row[0]: row[1]
            for row in conn.execute("SELECT Key, Value FROM GlobalMetadata").fetchall()
        }

        def _get(key: str, default: str = "") -> str:
            return raw.get(key, default)

        # Frame type counts
        frame_count: int = conn.execute(
            "SELECT COUNT(*) FROM Frames"
        ).fetchone()[0]

        ms1_count: int = conn.execute(
            f"SELECT COUNT(*) FROM Frames WHERE MsMsType={MSMS_TYPE_MS1}"
        ).fetchone()[0]

        dda_frame_count: int = conn.execute(
            f"SELECT COUNT(*) FROM Frames WHERE MsMsType={MSMS_TYPE_PASEF_DDA}"
        ).fetchone()[0]
        dda_precursor_count: int = 0
        if dda_frame_count > 0:
            dda_precursor_count = conn.execute(
                "SELECT COUNT(*) FROM Precursors"
            ).fetchone()[0]

        dia_count: int = conn.execute(
            f"SELECT COUNT(*) FROM Frames WHERE MsMsType={MSMS_TYPE_PASEF_DIA}"
        ).fetchone()[0]

        total = ms1_count + dda_precursor_count + dia_count

        # DIA windows
        dia_windows: list[DiaWindow] = []
        if dia_count > 0:
            for row in conn.execute("SELECT * FROM DiaFrameMsMsWindows").fetchall():
                dia_windows.append(
                    DiaWindow(
                        window_group=int(row[0]),
                        scan_num_begin=int(row[1]),
                        scan_num_end=int(row[2]),
                        isolation_mz=float(row[3]),
                        isolation_width=float(row[4]),
                        collision_energy=float(row[5]),
                    )
                )

        return AcquisitionMetadata(
            schema_type=_get(META_SCHEMA_TYPE),
            schema_version_major=int(_get(META_SCHEMA_VERSION_MAJOR, "0")),
            schema_version_minor=int(_get(META_SCHEMA_VERSION_MINOR, "0")),
            acq_software=_get(META_ACQ_SOFTWARE),
            acq_software_version=_get(META_ACQ_SOFTWARE_VERSION),
            acq_firmware_version=_get(META_ACQ_FIRMWARE_VERSION),
            acq_software_vendor=_get(META_ACQ_SOFTWARE_VENDOR),
            acq_date_time=_get(META_ACQ_DATETIME),
            instrument_name=_get(META_INSTRUMENT_NAME),
            instrument_family=_get(META_INSTRUMENT_FAMILY),
            instrument_serial_number=_get(META_INSTRUMENT_SERIAL),
            instrument_revision=int(_get(META_INSTRUMENT_REVISION, "0")),
            instrument_source_type=int(_get(META_INSTRUMENT_SOURCE_TYPE, "0")),
            instrument_vendor=_get(META_INSTRUMENT_VENDOR),
            operator_name=_get(META_OPERATOR_NAME),
            sample_name=_get(META_SAMPLE_NAME),
            description=_get(META_DESCRIPTION),
            method_name=_get(META_METHOD_NAME),
            analysis_id=_get(META_ANALYSIS_ID),
            closed_properly=bool(int(_get(META_CLOSED_PROPERLY, "1"))),
            mz_acq_range_lower=float(_get(META_MZ_RANGE_LOWER, "0")),
            mz_acq_range_upper=float(_get(META_MZ_RANGE_UPPER, "0")),
            one_over_k0_range_lower=float(_get(META_OOK0_RANGE_LOWER, "0")),
            one_over_k0_range_upper=float(_get(META_OOK0_RANGE_UPPER, "0")),
            frame_count=frame_count,
            ms1_spectra_count=ms1_count,
            ms2_dda_count=dda_precursor_count,
            ms2_dia_count=dia_count,
            total_spectra=total,
            has_pasef_dda=dda_frame_count > 0,
            has_pasef_dia=dia_count > 0,
            dia_windows=dia_windows,
        )

    # ------------------------------------------------------------------
    # Frame queries
    # ------------------------------------------------------------------

    def get_ms1_frames(self) -> list[tuple[int, ...]]:
        """Return all MS1 (MsMsType=0) frame rows.

        Returns
        -------
        list of tuple
            All columns from the ``Frames`` table for MS1 frames.
        """
        return self._tims.conn.execute(  
            f"SELECT * FROM Frames WHERE MsMsType={MSMS_TYPE_MS1}"
        ).fetchall()

    def get_all_frames(self) -> list[tuple[int, ...]]:
        """Return all frame rows ordered by ID.

        Returns
        -------
        list of tuple
            All columns from the ``Frames`` table.
        """
        return self._tims.conn.execute(  
            "SELECT * FROM Frames ORDER BY Id"
        ).fetchall()

    def get_num_scans(self, frame_id: int) -> int:
        """Return the number of scan lines (mobility bins) in a frame.

        Parameters
        ----------
        frame_id : int
            TDF frame ID.

        Returns
        -------
        int
            Value of ``NumScans`` for the given frame.
        """
        row = self._tims.conn.execute(
            "SELECT NumScans FROM Frames WHERE Id=?", (frame_id,)
        ).fetchone()
        return int(row[0])

    # ------------------------------------------------------------------
    # Precursor queries
    # ------------------------------------------------------------------

    def get_precursors_for_frame(
        self, frame_id: int
    ) -> list[PrecursorRow]:
        """Return all precursors belonging to a given MS1 frame.

        Parameters
        ----------
        frame_id : int
            Parent MS1 frame ID.

        Returns
        -------
        list of dict
            Each dict maps :data:`~tdf2mzml.constants.PRECURSOR_COLUMNS`
            column names to their values.
        """
        col_str = ", ".join(PRECURSOR_COLUMNS)
        rows = self._tims.conn.execute(
            f"SELECT {col_str} FROM Precursors WHERE Parent=?", (frame_id,)
        ).fetchall()
        return [
            {PRECURSOR_COLUMNS[i]: row[i] for i in range(len(PRECURSOR_COLUMNS))}  # type: ignore[misc]
            for row in rows
        ]

    def get_precursors_in_range(
        self, frame_start: int, frame_end: int
    ) -> dict[int, list[PrecursorRow]]:
        """Return all precursors for frames in [frame_start, frame_end] in one query.

        Much faster than calling :meth:`get_precursors_for_frame` per DDA frame
        because it avoids the per-frame SQL round-trip overhead.

        Parameters
        ----------
        frame_start : int
            First frame ID (inclusive).
        frame_end : int
            Last frame ID (inclusive).

        Returns
        -------
        dict
            Mapping of ``frame_id`` → list of :class:`~tdf2mzml.models.spectrum.PrecursorRow`.
        """
        col_str = ", ".join(PRECURSOR_COLUMNS)
        rows = self._tims.conn.execute(
            f"SELECT {col_str} FROM Precursors WHERE Parent BETWEEN ? AND ?",
            (frame_start, frame_end),
        ).fetchall()
        parent_idx = PRECURSOR_COLUMNS.index("Parent")
        result: dict[int, list[PrecursorRow]] = {}
        for row in rows:
            rec: PrecursorRow = {  # type: ignore[assignment]
                PRECURSOR_COLUMNS[i]: row[i] for i in range(len(PRECURSOR_COLUMNS))
            }
            result.setdefault(int(row[parent_idx]), []).append(rec)
        return result

    def get_pasef_frame_info(self, precursor_id: int) -> dict[str, object]:
        """Return PASEF frame isolation and collision energy info for a precursor.

        Parameters
        ----------
        precursor_id : int
            Precursor ID from the ``Precursors`` table.

        Returns
        -------
        dict
            Keys: ``IsolationMz``, ``CollisionEnergy``, ``IsolationWidth``.
        """
        row = self._tims.conn.execute(
            "SELECT IsolationMz, CollisionEnergy, IsolationWidth "
            "FROM PasefFrameMsMsInfo WHERE Precursor=?",
            (precursor_id,),
        ).fetchone()
        return {
            "IsolationMz": row[0],
            "CollisionEnergy": row[1],
            "IsolationWidth": row[2],
        }

    def get_pasef_frame_info_batch(
        self, precursor_ids: list[int]
    ) -> dict[int, dict[str, float]]:
        """Return PASEF isolation/CE info for multiple precursors in one query.

        Parameters
        ----------
        precursor_ids : list of int
            Precursor IDs to look up.

        Returns
        -------
        dict
            Mapping precursor_id → {IsolationMz, CollisionEnergy, IsolationWidth}.
        """
        if not precursor_ids:
            return {}
        placeholders = ",".join("?" * len(precursor_ids))
        rows = self._tims.conn.execute(
            f"SELECT Precursor, IsolationMz, CollisionEnergy, IsolationWidth "
            f"FROM PasefFrameMsMsInfo WHERE Precursor IN ({placeholders})",
            precursor_ids,
        ).fetchall()
        return {
            int(r[0]): {
                "IsolationMz": float(r[1]),
                "CollisionEnergy": float(r[2]),
                "IsolationWidth": float(r[3]),
            }
            for r in rows
        }

    def get_parent_frame_ids(self, precursor_id: int) -> list[int]:
        """Return all MS2 frame IDs that contain a given precursor.

        Parameters
        ----------
        precursor_id : int
            Precursor ID.

        Returns
        -------
        list of int
            Frame IDs from ``PasefFrameMsMsInfo``.
        """
        rows = self._tims.conn.execute(
            "SELECT Frame FROM PasefFrameMsMsInfo WHERE Precursor=?",
            (precursor_id,),
        ).fetchall()
        return [int(r[0]) for r in rows]

    # ------------------------------------------------------------------
    # DIA queries
    # ------------------------------------------------------------------

    def get_dia_window_group(self, frame_id: int) -> int:
        """Return the DIA window group ID for a DIA frame.

        Parameters
        ----------
        frame_id : int
            A MsMsType=9 frame ID.

        Returns
        -------
        int
            Window group identifier.
        """
        row = self._tims.conn.execute(
            "SELECT WindowGroup FROM DiaFrameMsMsInfo WHERE Frame=?",
            (frame_id,),
        ).fetchone()
        return int(row[0])

    def get_dia_windows_for_group(
        self, window_group: int
    ) -> list[tuple[int, ...]]:
        """Return all DIA window definitions for a window group.

        Parameters
        ----------
        window_group : int
            Window group identifier.

        Returns
        -------
        list of tuple
            All columns from ``DiaFrameMsMsWindows`` for this group.
        """
        return self._tims.conn.execute(  
            "SELECT * FROM DiaFrameMsMsWindows WHERE WindowGroup=?",
            (window_group,),
        ).fetchall()

    # ------------------------------------------------------------------
    # SDK delegation — spectrum extraction
    # ------------------------------------------------------------------

    def extract_centroided_spectrum(
        self,
        frame_id: int,
        scan_begin: int,
        scan_end: int,
        peak_picker_resolution: float | None = None,
        dense: bool = True,
    ) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.float32]]:
        """Extract a centroided spectrum via the SDK.

        Parameters
        ----------
        frame_id : int
            TDF frame ID.
        scan_begin : int
            First scan line (inclusive).
        scan_end : int
            Last scan line (exclusive).
        peak_picker_resolution : float or None, optional
            Custom peak picker resolution. None uses the SDK default.
        dense : bool, optional
            True (default) → dense (_v2) algorithm; False → sparse (_v3).

        Returns
        -------
        tuple
            ``(mz_array, intensity_array)`` as float64 and float32.
        """
        return self._tims.extract_centroided_spectrum(
            frame_id, scan_begin, scan_end, peak_picker_resolution, dense
        )

    def extract_profile_for_frame(
        self, frame_id: int, scan_begin: int, scan_end: int
    ) -> npt.NDArray[np.int32]:
        """Extract a quasi-profile spectrum via the SDK.

        Parameters
        ----------
        frame_id : int
            TDF frame ID.
        scan_begin : int
            First scan line (inclusive).
        scan_end : int
            Last scan line (exclusive).

        Returns
        -------
        numpy.ndarray
            Profile intensity values (int32).
        """
        return self._tims.extract_profile_for_frame(frame_id, scan_begin, scan_end)

    def read_scans(
        self, frame_id: int, scan_begin: int, scan_end: int
    ) -> list[tuple[npt.NDArray[np.uint32], npt.NDArray[np.uint32]]]:
        """Read raw per-scan (index, intensity) arrays via the SDK.

        Parameters
        ----------
        frame_id : int
            TDF frame ID.
        scan_begin : int
            First scan line (inclusive, 0-based).
        scan_end : int
            Last scan line (exclusive).

        Returns
        -------
        list of tuple
            One ``(indices, intensities)`` uint32 pair per scan line.
        """
        return self._tims.read_scans(frame_id, scan_begin, scan_end)

    def read_scan_tics(
        self, frame_id: int, scan_begin: int, scan_end: int
    ) -> npt.NDArray[np.float32]:
        """Return per-scan TIC values without copying index arrays.

        Faster than :meth:`read_scans` for TIC-only use cases (mean 1/K0)
        because it skips the ``indices`` copy for every scan line.

        Parameters
        ----------
        frame_id : int
            TDF frame ID.
        scan_begin : int
            First scan (inclusive, 0-based).
        scan_end : int
            Last scan (exclusive).

        Returns
        -------
        numpy.ndarray
            Per-scan TIC values (float32), length ``scan_end - scan_begin``.
        """
        return self._tims.read_scan_tics(frame_id, scan_begin, scan_end)

    def read_pasef_msms(
        self,
        precursor_list: list[int],
        sparse: bool = True,
    ) -> dict[int, tuple[npt.NDArray[np.float64], npt.NDArray[np.float32]]]:
        """Read peak-picked PASEF MS/MS spectra for a list of precursor IDs.

        Parameters
        ----------
        precursor_list : list of int
            Precursor IDs.
        sparse : bool, optional
            Use sparse (v2) algorithm. Default True.

        Returns
        -------
        dict
            Mapping of ``precursor_id`` → ``(mz_array, intensity_array)``.
        """
        return self._tims.read_pasef_msms(precursor_list, sparse=sparse)

    # ------------------------------------------------------------------
    # SDK delegation — coordinate conversion
    # ------------------------------------------------------------------

    def index_to_mz(
        self, frame_id: int, indices: npt.ArrayLike
    ) -> npt.NDArray[np.float64]:
        """Convert TOF bin indices to m/z values.

        Parameters
        ----------
        frame_id : int
            TDF frame ID.
        indices : array-like
            TOF index values.

        Returns
        -------
        numpy.ndarray
            m/z values (float64).
        """
        return self._tims.index_to_mz(frame_id, indices)

    def scan_num_to_one_over_k0(
        self, frame_id: int, scan_nums: npt.ArrayLike
    ) -> npt.NDArray[np.float64]:
        """Convert scan line indices to 1/K0 ion mobility values.

        Parameters
        ----------
        frame_id : int
            TDF frame ID.
        scan_nums : array-like
            Scan line indices (0-based).

        Returns
        -------
        numpy.ndarray
            1/K0 values in V·s/cm² (float64).
        """
        return self._tims.scan_num_to_one_over_k0(frame_id, scan_nums)
