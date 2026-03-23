"""MS2 spectrum extraction for PASEF DDA and DIA acquisition modes."""

import logging
from typing import TypedDict

import numpy as np

from tdf2mzml.io.reader import TdfReader
from tdf2mzml.models.spectrum import PrecursorInfo, SpectrumArrays


class PrecursorRow(TypedDict, total=False):
    """Typed dictionary matching the Precursors table columns."""

    Id: int
    LargestPeakMz: float
    AverageMz: float
    MonoisotopicMz: float
    ScanNumber: float | None
    Charge: int | None
    Intensity: float
    Parent: int

logger = logging.getLogger(__name__)


def get_pasef_dda_ms2(
    reader: TdfReader,
    precursor: PrecursorRow,
    parent_spectrum_id: str,
    ms2_data: dict[int, tuple[object, object]] | None = None,
    pasef_info: dict[int, dict[str, float]] | None = None,
    one_over_k0: float | None = None,
) -> tuple[SpectrumArrays, PrecursorInfo]:
    """Extract a PASEF DDA MS2 spectrum and build its precursor metadata.

    Uses ``tims_read_pasef_msms_v2`` (sparse, improved performance in SDK
    v3.3.6.2) to retrieve the peak-picked spectrum.  Ion mobility (1/K0) is
    computed from the precursor scan number and included in
    :class:`~tdf2mzml.models.spectrum.PrecursorInfo`.

    Parameters
    ----------
    reader : TdfReader
        Open TDF reader.
    precursor : dict
        Precursor row from the ``Precursors`` table, keyed by
        :data:`~tdf2mzml.constants.PRECURSOR_COLUMNS`.
    parent_spectrum_id : str
        Spectrum ID of the parent MS1 frame (e.g. ``"index=1"``).
    ms2_data : dict, optional
        Pre-fetched batch result from ``read_pasef_msms``.  If provided,
        the per-precursor SDK call is skipped.
    pasef_info : dict, optional
        Pre-fetched batch result from ``get_pasef_frame_info_batch``.
        If provided, the per-precursor SQL query is skipped.
    one_over_k0 : float, optional
        Pre-computed 1/K0 for this precursor.  If provided, the
        ``scan_num_to_one_over_k0`` SDK call is skipped.

    Returns
    -------
    tuple
        ``(SpectrumArrays, PrecursorInfo)`` for the MS2 spectrum.
    """
    precursor_id: int = precursor["Id"]
    parent_frame_id: int = precursor["Parent"]
    scan_number = precursor.get("ScanNumber")

    # Retrieve peak-picked spectrum — use pre-fetched batch if available
    ms2_result = ms2_data if ms2_data is not None else reader.read_pasef_msms([precursor_id], sparse=True)
    if precursor_id not in ms2_result:
        logger.warning("No MS2 data returned for precursor ID %d", precursor_id)
        arrays = SpectrumArrays(
            mz=np.empty(0, dtype=np.float64),
            intensity=np.empty(0, dtype=np.float32),
        )
    else:
        raw_mz, raw_i = ms2_result[precursor_id]
        arrays = SpectrumArrays(
            mz=np.asarray(raw_mz, dtype=np.float64),
            intensity=np.asarray(raw_i, dtype=np.float32),
        )

    # Ion mobility — use pre-computed value if supplied, else call SDK
    ook0: float | None = one_over_k0
    if ook0 is None and scan_number is not None:
        ook0_arr = reader.scan_num_to_one_over_k0(
            parent_frame_id, [float(scan_number)]
        )
        ook0 = float(ook0_arr[0])

    # PASEF frame isolation / collision energy — use pre-fetched cache if available
    _pasef = (
        pasef_info.get(precursor_id)
        if pasef_info is not None
        else reader.get_pasef_frame_info(precursor_id)
    )
    if _pasef is None:
        logger.warning("No PASEF frame info for precursor ID %d", precursor_id)
        _pasef = {"IsolationMz": 0.0, "CollisionEnergy": 0.0, "IsolationWidth": 0.0}
    isolation_mz = float(_pasef["IsolationMz"])
    collision_energy = float(_pasef["CollisionEnergy"])
    isolation_width = float(_pasef["IsolationWidth"])

    # Determine selected ion m/z and isolation offsets
    charge = precursor.get("Charge")
    if charge is not None:
        selected_mz = float(precursor["MonoisotopicMz"])
    else:
        selected_mz = float(precursor["LargestPeakMz"])

    isolation_offset = isolation_mz - selected_mz
    half_width = isolation_width / 2.0

    info = PrecursorInfo(
        mz=selected_mz,
        charge=int(charge) if charge is not None else None,
        spectrum_reference=parent_spectrum_id,
        isolation_window_target=selected_mz,
        isolation_window_lower=half_width - isolation_offset,
        isolation_window_upper=half_width + isolation_offset,
        one_over_k0=ook0,
        collision_energy=collision_energy,
        activation="CID",
    )

    return arrays, info


def get_pasef_dia_ms2(
    reader: TdfReader,
    frame_id: int,
    window: tuple[int, ...],
    parent_spectrum_id: str,
) -> tuple[SpectrumArrays, PrecursorInfo]:
    """Extract a PASEF DIA MS2 spectrum for a single isolation window.

    Parameters
    ----------
    reader : TdfReader
        Open TDF reader.
    frame_id : int
        DIA frame ID (MsMsType=9).
    window : tuple
        A ``DiaFrameMsMsWindows`` row:
        ``(WindowGroup, ScanNumBegin, ScanNumEnd, IsolationMz,
        IsolationWidth, CollisionEnergy)``.
    parent_spectrum_id : str
        Spectrum ID of the preceding MS1 frame.

    Returns
    -------
    tuple
        ``(SpectrumArrays, PrecursorInfo)`` for the DIA MS2 spectrum.
    """
    scan_begin = int(window[1])
    scan_end = int(window[2])
    mz_center = float(window[3])
    mz_width = float(window[4])
    collision_energy = float(window[5])

    raw_mz, raw_i = reader.extract_centroided_spectrum(
        frame_id, scan_begin, scan_end
    )
    arrays = SpectrumArrays(
        mz=np.asarray(raw_mz, dtype=np.float64),
        intensity=np.asarray(raw_i, dtype=np.float32),
    )

    half_width = mz_width / 2.0
    info = PrecursorInfo(
        mz=mz_center,
        charge=None,
        spectrum_reference=parent_spectrum_id,
        isolation_window_target=mz_center,
        isolation_window_lower=half_width,
        isolation_window_upper=half_width,
        one_over_k0=None,
        collision_energy=collision_energy,
        activation="CID",
    )

    return arrays, info
