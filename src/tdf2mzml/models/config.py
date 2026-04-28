"""Conversion configuration model.

:class:`ConversionConfig` is the single validated parameter object that flows
through the entire conversion pipeline.  It is constructed from CLI arguments
by :func:`~tdf2mzml.cli.parse_args` and validated with Pydantic, including
auto-extraction of ``.zip`` archives and verification that the input directory
contains a recognised Bruker analysis file (``analysis.tdf``, ``analysis.tsf``,
or ``analysis.baf``).
"""

from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, Field, model_validator

from tdf2mzml.constants import (
    DEFAULT_END_FRAME,
    DEFAULT_MS1_THRESHOLD,
    DEFAULT_MS2_NLARGEST,
    DEFAULT_MS2_THRESHOLD,
    DEFAULT_PRECISION,
    DEFAULT_START_FRAME,
)


class ConversionConfig(BaseModel):
    """All parameters controlling a single Bruker → mzML conversion run.

    Supports TDF (timsTOF PASEF), TSF (timsTOF fleX), and BAF (maXis/impact)
    input formats.  Format detection is automatic based on which analysis
    file is present in the ``.d`` directory.

    Parameters
    ----------
    input : Path
        Path to the Bruker ``.d`` directory or standalone ``.baf`` file.
    output : Path
        Destination ``.mzML`` file path.
    ms1_type : {"centroid", "profile", "raw"}
        How MS1 spectra are represented in the output.
    ms1_threshold : float
        Minimum intensity for raw-mode MS1 peak inclusion (≥ 0).
    ms2_threshold : float
        Minimum intensity for MS2 peak inclusion (≥ 0).
    ms2_nlargest : int
        Retain only the N largest MS2 peaks per spectrum; ``-1`` keeps all.
    start_frame : int
        First TDF frame ID to convert; ``-1`` starts from the first frame.
    end_frame : int
        Last TDF frame ID to convert (inclusive); ``-1`` ends at the last.
    compression : {"none", "zlib"}
        Binary array compression in the mzML output.
    ion_mobility : {"none", "mean", "perscan", "array"}
        Strategy for capturing ion mobility data.

        - ``"none"``    — no ion mobility written.
        - ``"mean"``    — intensity-weighted mean 1/K0 per spectrum.
        - ``"perscan"`` — one spectrum per scan line with its exact 1/K0.
        - ``"array"``   — full IM-resolved MS1: all IM bins preserved as
          separate peaks with a parallel per-peak exact 1/K0 array (like
          timsconvert). MS1 peak counts are much larger; file size increases
          significantly.
    precision : float
        m/z binning precision in ppm for raw-mode merging (> 0).
    checksum_source_files : bool
        Compute and embed SHA-1 checksums for the source ``.tdf`` /
        ``.tdf_bin`` files.  Disabled by default because hashing a multi-GB
        ``.tdf_bin`` dominates startup time on large datasets.
    debug : bool
        Enable verbose DEBUG-level logging.
    """

    input: Path = Field(..., description="Path to the .d input directory")
    output: Path = Field(..., description="Path to the output .mzML file")
    ms1_type: Literal["centroid", "profile", "raw"] = Field(
        "centroid", description="MS1 spectrum representation type"
    )
    ms1_threshold: Annotated[float, Field(ge=0)] = Field(
        DEFAULT_MS1_THRESHOLD, description="Minimum intensity for raw MS1 peaks"
    )
    ms2_threshold: Annotated[float, Field(ge=0)] = Field(
        DEFAULT_MS2_THRESHOLD, description="Minimum intensity for MS2 peaks"
    )
    ms2_nlargest: int = Field(
        DEFAULT_MS2_NLARGEST, description="Keep N largest MS2 peaks; -1 keeps all"
    )
    start_frame: int = Field(
        DEFAULT_START_FRAME, description="First frame to convert; -1 = first available"
    )
    end_frame: int = Field(
        DEFAULT_END_FRAME, description="Last frame to convert; -1 = last available"
    )
    compression: Literal["none", "zlib"] = Field("none", description="Binary array compression")
    ion_mobility: Literal["none", "mean", "perscan", "array"] = Field(
        "mean", description="Ion mobility capture strategy"
    )
    precision: Annotated[float, Field(gt=0)] = Field(
        DEFAULT_PRECISION, description="m/z binning precision in ppm for raw mode"
    )
    checksum_source_files: bool = Field(
        False,
        description=(
            "Embed SHA-1 checksums for source .tdf/.tdf_bin files. "
            "Disabled by default; hashing a large .tdf_bin is slow."
        ),
    )
    debug: bool = Field(False, description="Enable verbose debug logging")

    @model_validator(mode="after")
    def _validate_frame_range(self) -> "ConversionConfig":
        """Ensure start_frame < end_frame when both are explicitly set."""
        if self.start_frame != -1 and self.end_frame != -1 and self.end_frame <= self.start_frame:
            raise ValueError(
                f"end_frame ({self.end_frame}) must be greater than "
                f"start_frame ({self.start_frame})"
            )
        return self

    @model_validator(mode="after")
    def _resolve_input(self) -> "ConversionConfig":
        """Auto-extract zipped .d directories and verify analysis.tdf exists.

        If *input* points to a ``.zip`` file (or a path ending in ``.d.zip``),
        the archive is extracted to a temporary sibling directory and *input*
        is updated to point at the extracted ``.d`` directory.
        """
        import zipfile

        path = self.input

        # Auto-extract .zip archives
        if path.suffix == ".zip" and zipfile.is_zipfile(path):
            import tempfile

            extract_dir = Path(tempfile.mkdtemp(prefix="tdf2mzml_"))
            with zipfile.ZipFile(path) as zf:
                zf.extractall(extract_dir)

            # Find the .d directory inside the extracted contents
            d_dirs = list(extract_dir.rglob("*.d"))
            if not d_dirs:
                raise ValueError(f"No .d directory found after extracting '{path}'")
            # Use model_copy to update the immutable-ish field
            object.__setattr__(self, "input", d_dirs[0])
            path = self.input

        # BAF: input may be a .baf file directly (standalone) or a .d directory
        if path.suffix == ".baf" and path.is_file():
            return self  # valid standalone BAF file

        tdf = path / "analysis.tdf"
        tsf = path / "analysis.tsf"
        baf = path / "analysis.baf"
        if not tdf.exists() and not tsf.exists() and not baf.exists():
            raise ValueError(
                f"Input directory '{path}' does not contain "
                "analysis.tdf, analysis.tsf, or analysis.baf"
            )
        return self
