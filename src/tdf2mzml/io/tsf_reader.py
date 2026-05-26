"""TsfReader: high-level interface over the Bruker TSF SQLite database and SDK.

TSF (timsTOF fleX / TIMS-off) files use ``analysis.tsf`` instead of
``analysis.tdf``.  There is no ion mobility data.  Spectra are read via
``tsf_read_line_spectrum_v2``.
"""

import logging
from pathlib import Path
from typing import Any

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
    META_OPERATOR_NAME,
    META_SAMPLE_NAME,
    META_SCHEMA_TYPE,
    META_SCHEMA_VERSION_MAJOR,
    META_SCHEMA_VERSION_MINOR,
)
from tdf2mzml.io.timsdata import TsfData
from tdf2mzml.models.metadata import AcquisitionMetadata

logger = logging.getLogger(__name__)

# TSF MsMsType values
TSF_MSMS_TYPE_MS1: int = 0
TSF_MSMS_TYPE_AUTO_MSMS: int = 2


class TsfReader:
    """Unified reader for a single Bruker ``.d`` / TSF dataset.

    Wraps :class:`~tdf2mzml.io.timsdata.TsfData` (binary SDK) and the
    SQLite ``analysis.tsf`` database (metadata + frame tables) behind a
    single, typed API.  Intended to be used as a context manager.

    Parameters
    ----------
    path : Path or str
        Path to the Bruker ``.d`` directory.

    Examples
    --------
    >>> with TsfReader("/data/sample.d") as reader:
    ...     meta = reader.metadata
    ...     frames = reader.get_all_frames()
    """

    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)
        self._tsf = TsfData(str(self._path))
        self._metadata: AcquisitionMetadata | None = None

    def close(self) -> None:
        """Close the SDK handle and SQLite connection."""
        self._tsf.close()

    def __enter__(self) -> "TsfReader":
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
        """Query the TSF database and construct :class:`AcquisitionMetadata`.

        Returns
        -------
        AcquisitionMetadata
        """
        conn = self._tsf.conn

        # Read entire GlobalMetadata table in one query
        raw: dict[str, str] = {
            row[0]: row[1]
            for row in conn.execute("SELECT Key, Value FROM GlobalMetadata").fetchall()
        }

        def _get(key: str, default: str = "") -> str:
            return raw.get(key, default)

        # Frame type counts
        frame_count: int = conn.execute("SELECT COUNT(*) FROM Frames").fetchone()[0]

        ms1_count: int = conn.execute(
            f"SELECT COUNT(*) FROM Frames WHERE MsMsType={TSF_MSMS_TYPE_MS1}"
        ).fetchone()[0]

        ms2_count: int = conn.execute(
            f"SELECT COUNT(*) FROM Frames WHERE MsMsType={TSF_MSMS_TYPE_AUTO_MSMS}"
        ).fetchone()[0]

        total = ms1_count + ms2_count

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
            # TSF has no ion mobility — set K0 range to zero
            one_over_k0_range_lower=0.0,
            one_over_k0_range_upper=0.0,
            frame_count=frame_count,
            ms1_spectra_count=ms1_count,
            ms2_dda_count=ms2_count,
            ms2_dia_count=0,
            total_spectra=total,
            has_pasef_dda=False,
            has_pasef_dia=False,
            dia_windows=[],
        )

    # ------------------------------------------------------------------
    # Frame queries
    # ------------------------------------------------------------------

    def get_all_frames(self) -> list[tuple[int, float, int, int, int]]:
        """Return all frame rows ordered by ID.

        Returns
        -------
        list of tuple
            Rows with columns: Id, Time, Polarity, ScanMode, MsMsType from
            the ``Frames`` table, ordered by Id.
        """
        return self._tsf.conn.execute(
            "SELECT Id, Time, Polarity, ScanMode, MsMsType FROM Frames ORDER BY Id"
        ).fetchall()

    # ------------------------------------------------------------------
    # MS2 / FrameMsMsInfo queries
    # ------------------------------------------------------------------

    def get_ms2_info_for_frame(self, frame_id: int) -> dict[str, Any] | None:
        """Return MS2 isolation and collision energy info for a TSF MS2 frame.

        Parameters
        ----------
        frame_id : int
            TSF frame ID (MsMsType=2).

        Returns
        -------
        dict or None
            Keys: ``Frame``, ``Parent``, ``TriggerMass``, ``IsolationWidth``,
            ``PrecursorCharge``, ``CollisionEnergy``.  Returns None if no
            row exists for the given frame_id.
        """
        row = self._tsf.conn.execute(
            "SELECT Frame, Parent, TriggerMass, IsolationWidth, "
            "PrecursorCharge, CollisionEnergy "
            "FROM FrameMsMsInfo WHERE Frame=?",
            (frame_id,),
        ).fetchone()
        if row is None:
            return None
        return {
            "Frame": int(row[0]),
            "Parent": int(row[1]),
            "TriggerMass": float(row[2]) if row[2] is not None else 0.0,
            "IsolationWidth": float(row[3]) if row[3] is not None else 0.0,
            "PrecursorCharge": int(row[4]) if row[4] is not None else None,
            "CollisionEnergy": float(row[5]) if row[5] is not None else 0.0,
        }

    def get_ms2_info_batch(self, frame_ids: list[int]) -> dict[int, dict[str, Any]]:
        """Return MS2 info for multiple frames in a single SQL query.

        Parameters
        ----------
        frame_ids : list of int
            TSF MS2 frame IDs to look up.

        Returns
        -------
        dict
            Mapping frame_id → info dict (same structure as
            :meth:`get_ms2_info_for_frame`).
        """
        if not frame_ids:
            return {}
        placeholders = ",".join("?" * len(frame_ids))
        rows = self._tsf.conn.execute(
            f"SELECT Frame, Parent, TriggerMass, IsolationWidth, "
            f"PrecursorCharge, CollisionEnergy "
            f"FROM FrameMsMsInfo WHERE Frame IN ({placeholders})",
            frame_ids,
        ).fetchall()
        return {
            int(r[0]): {
                "Frame": int(r[0]),
                "Parent": int(r[1]),
                "TriggerMass": float(r[2]) if r[2] is not None else 0.0,
                "IsolationWidth": float(r[3]) if r[3] is not None else 0.0,
                "PrecursorCharge": int(r[4]) if r[4] is not None else None,
                "CollisionEnergy": float(r[5]) if r[5] is not None else 0.0,
            }
            for r in rows
        }

    def get_parent_ms1_ids(self, frame_ids: list[int]) -> dict[int, int]:
        """Return a mapping of MS2 frame ID → parent MS1 frame ID.

        Parameters
        ----------
        frame_ids : list of int
            TSF MS2 frame IDs.

        Returns
        -------
        dict
            Mapping frame_id → parent MS1 frame ID.
        """
        if not frame_ids:
            return {}
        placeholders = ",".join("?" * len(frame_ids))
        rows = self._tsf.conn.execute(
            f"SELECT Frame, Parent FROM FrameMsMsInfo WHERE Frame IN ({placeholders})",
            frame_ids,
        ).fetchall()
        return {int(r[0]): int(r[1]) for r in rows}

    # ------------------------------------------------------------------
    # Spectrum reading
    # ------------------------------------------------------------------

    def read_line_spectrum(
        self, frame_id: int
    ) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.float32]]:
        """Read a centroid line spectrum for a TSF frame.

        Delegates to :meth:`~tdf2mzml.io.timsdata.TsfData.read_line_spectrum`.

        Parameters
        ----------
        frame_id : int
            TSF frame ID.

        Returns
        -------
        tuple
            ``(mz_array, intensity_array)`` as float64 and float32.
        """
        return self._tsf.read_line_spectrum(frame_id)
