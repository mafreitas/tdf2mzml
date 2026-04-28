# Changelog

All notable changes to tdf2mzml are documented in this file.

## [0.6.0] — In Progress

### Added
- **CI/CD pipeline** — GitHub Actions workflow with lint, typecheck, and test jobs on every PR
- **64 mzML compliance tests** — guards against every regression from the v0.5 cvParam incident
  - cvParam accession, cvRef, value attribute presence
  - Full unit triplets (unitCvRef + unitAccession + unitName)
  - encodedLength on binaryDataArray elements
  - 1-based spectrum IDs
  - Correct accessions for instrument, software, file description, data processing, precursor, and ion mobility CV terms
- **Makefile** — `setup`, `test`, `lint`, `typecheck`, `format`, `build`, `ci` targets
- `.tool-versions` — Python 3.12 pinned via asdf
- Docker smoke tests (marked slow, manual only)
- Coverage configuration targeting 85%+ on critical output modules
- Full docstrings across all modules (excluding SDK bindings)

### Fixed
- All mypy strict-mode errors resolved across 6 modules (13 errors)
- ruff lint and format applied consistently across all 28 Python files

### Changed
- Version bumped to 0.6.0
- pyproject.toml: added pytest markers, coverage config, updated ruff per-file ignores
- Dockerfile labels updated to 0.6.0

## [0.5.0] — 2026-04-22

### Added
- **BAF format support** — maXis, impact, and other Bruker QTOF instruments via libbaf2sql_c
- **TSF format support** — timsTOF fleX / TIMS-off (no ion mobility)
- **Ion mobility modes** — `none`, `mean` (intensity-weighted 1/K0), `array` (per-peak 1/K0)
- **Modular architecture** — refactored from monolithic script to `src/tdf2mzml/` package layout
- **Indexed mzML writer** — custom writer with byte-offset index, replacing psims dependency
- DIA-PASEF support
- Pydantic models for configuration, metadata, and spectrum data
- `Dockerfile.noentry` variant without ENTRYPOINT for Nextflow compatibility
- procps (ps) added to Docker images for Nextflow process monitoring

### Fixed
- **mzML cvParam compliance** — restored required `accession` attributes on all cvParam elements
- **cvRef** — changed from `"MS"` to `"PSI-MS"` to match established convention
- **encodedLength** — added to all binaryDataArray elements (required by ProteoWizard consumers)
- **Spectrum IDs** — corrected from 0-based to 1-based (`id="index=1"`)
- **Unit triplets** — added full `unitCvRef` + `unitAccession` + `unitName` on all unit-bearing cvParams
- **Software entries** — proper CV accessions (MS:1000692, MS:1000726, MS:1000799) with userParam structure
- **Instrument accessions** — fixed Bruker instrument model (MS:1000122), MCP detector (MS:1000114)
- **Photomultiplier** — restored in detector component list (MS:1000116)
- BAF polarity and MS level detection

### Changed
- Removed psims dependency — direct XML string construction for performance
- 4-7x faster conversion vs v0.3

### Removed
- psims dependency
- Legacy monolithic `tdf2mzml.py` script

## [0.4.0] — 2024

### Changed
- Package structure reorganization (pyproject.toml, src layout)
- Linting and formatting pass
- Updated Dockerfile

## [0.3.0] — 2020-02-11

### Added
- Initial public release
- TDF (timsTOF PASEF DDA) to mzML conversion via psims
- Bruker TIMS SDK integration (libtimsdata.so)
- Docker support
- Centroid, profile, and raw MS1 modes
- Frame range selection
- zlib compression option

### Fixed
- Ion mobility term corrected from "drift time" to "inverse reduced ion mobility" (1/K0)
- Windows path handling
- Retention time units (seconds to minutes)
- Profile mode index-to-m/z conversion
- Missing scan handling
