# Changelog

All notable changes to tdf2mzml are documented in this file.

## [0.6.1] — 2026-05-26

### Fixed
- **XML attribute escaping** (#33) — values containing `"` no longer break the surrounding attribute. Affects sample descriptions, source-file paths, software fields, instrument names, and other attribute-bound strings. Adds an `_xml_attr()` helper applied at every attribute-bound escape site in `output/xml_elements.py`.
- **Ion mobility cvParam** (#32) — per-spectrum scan element now emits the correct PSI-MS scalar term `MS:1002815 "inverse reduced ion mobility"`. Previously emitted `MS:1002814` (the unit `volt-second per square centimeter`) as both term and unit accession, and used the non-standard name `mean inverse reduced ion mobility`. Verified against the PSI-MS OBO.
- **SQL `IN (...)` chunking for Windows** (#31) — Bruker `.d` files with >32,766 DDA precursors no longer fail on Windows. CPython on Windows ships SQLite with `SQLITE_MAX_VARIABLE_NUMBER=32766`; the five SQL sites in the PASEF/TDF, TSF, and BAF readers now route through a shared `batched_in_query()` helper that splits IN-clause params into chunks of 500.

### Removed
- Stale `requirements.txt` from the v0.3 era (pinned `lxml==4.6.3`, `numpy==1.18.3`, `psims`, `matplotlib`, `pandas`, `SQLAlchemy` — none of which are used post-v0.5). The file was unreferenced by `Dockerfile`, `Makefile`, CI, and `pyproject.toml`. Removal closes 7 dependabot alerts (2 high, 5 medium) that all targeted those obsolete pins.

## [0.6.0] — 2026-04-28

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
- Docker images: `0.6` and `0.6_noentry` published to Docker Hub
- Docker smoke tests (marked slow, manual only)
- Coverage configuration targeting 85%+ on critical output modules (96% achieved)
- CHANGELOG.md documenting all versions
- SDK-dependent tests auto-skipped when Bruker shared library unavailable (CI, macOS)

### Fixed
- All mypy strict-mode errors resolved across 6 modules (13 errors)
- ruff lint and format applied consistently across all 28 Python files
- GitHub Actions updated to Node.js 24 compatible versions (checkout v5, setup-python v6)

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
