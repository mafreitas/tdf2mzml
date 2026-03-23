"""Per-spectrum data models."""

from typing import Annotated, TypedDict

import numpy as np
import numpy.typing as npt
from pydantic import BaseModel, Field, model_validator


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

Float64Array = npt.NDArray[np.float64]
Float32Array = npt.NDArray[np.float32]


class SpectrumArrays(BaseModel):
    """A matched pair of m/z and intensity arrays for a single spectrum.

    Parameters
    ----------
    mz : numpy.ndarray
        Monotonically increasing m/z values (float64).
    intensity : numpy.ndarray
        Corresponding intensity values (float32), same length as *mz*.
    """

    model_config = {"arbitrary_types_allowed": True}

    mz: Float64Array = Field(..., description="m/z array (float64, sorted ascending)")
    intensity: Float32Array = Field(..., description="Intensity array (float32)")

    @model_validator(mode="after")
    def _same_length(self) -> "SpectrumArrays":
        if len(self.mz) != len(self.intensity):
            raise ValueError(
                f"mz length ({len(self.mz)}) != intensity length ({len(self.intensity)})"
            )
        return self

    @property
    def is_empty(self) -> bool:
        """True when the spectrum contains no peaks."""
        return len(self.mz) == 0


class PrecursorInfo(BaseModel):
    """Metadata describing the precursor ion for an MS2 spectrum.

    Parameters
    ----------
    mz : float
        Selected precursor m/z (monoisotopic if known, else largest peak).
    charge : int or None
        Precursor charge state; ``None`` when undetermined.
    spectrum_reference : str
        Spectrum ID of the parent MS1 frame (e.g. ``"index=1"``).
    isolation_window_target : float
        Isolation window centre m/z (Da).
    isolation_window_lower : float
        Lower offset from the target (Da).
    isolation_window_upper : float
        Upper offset from the target (Da).
    one_over_k0 : float or None
        Inverse reduced ion mobility (1/K0) of the precursor ion in
        V·s/cm²; ``None`` when not available.
    collision_energy : float
        Collision energy applied (eV).
    activation : str
        Activation method CV term name. Default is ``"CID"``.
    """

    model_config = {"frozen": True}

    mz: float
    charge: int | None = None
    spectrum_reference: str
    isolation_window_target: float
    isolation_window_lower: float
    isolation_window_upper: Annotated[float, Field(ge=0)]
    one_over_k0: float | None = Field(
        None,
        description="Inverse reduced ion mobility 1/K0 of precursor (V·s/cm²)",
    )
    collision_energy: float
    activation: str = "CID"
