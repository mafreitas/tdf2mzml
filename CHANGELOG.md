# Changelog

All notable changes to tdf2mzml are documented in this file.

## [0.7.0] — Unreleased

### Added
- **TDF schema v5 support** — reads schema 5.x (timsOmni, acquisition software 8.x) data. Schema v5 replaces the old MS/MS tables with views, and the views drop ExD frames, so the `Fragmentation*` tables are read directly for schema v5. Data with schema 3.x and 4.x use the same code as before.
- **ExD DDA-PASEF** — ECD, EID and other electron-based fragmentation. The MS2 frames of these runs have `MsMsType=3`, not 8; the previous version wrote MS1 spectra only for them. One MS2 spectrum is written for each precursor.
- **ECcID (ExD followed by CID)** — the CID step linked through `FragmentationStepToStep` is read as part of the same activation. The instrument records one spectrum for the chain, so one MS2 spectrum (ms level 2) is written.
- **Guided-PASEF (schema 5.1 and 5.2)** — files with CID and ExD (ECciD, EIciD) precursors in one run convert, with one MS2 spectrum for each precursor. The `FragmentationPrecursor.PrecursorGroup` column links the CID and ExD spectra of the same ion: both get a `<userParam name="precursor group" value="N"/>` on the `<spectrum>` element. A group has one CID spectrum (its precursor ID is the group value) and one ExD spectrum. They have the same selected ion m/z, and the ExD spectrum follows the CID spectrum within about 0.5 s. mzML has no standard term for this link. Precursors without a group (plain CID), and data older than schema 5.1, have no such parameter.
- **Activation terms in `<activation>`:**
  - ExD: `MS:1003294` electron activated dissociation, `MS:1003410` electron beam energy (eV) and a `reaction time` userParam (ms).
  - ECcID: the ExD terms plus `MS:1002679` supplemental collision-induced dissociation and `MS:1002680` supplemental collision energy (eV).
  - ETD: `MS:1000598` and the `reaction time` userParam.
  - CID output is unchanged.
- `THIRD-PARTY-LICENSE-README.txt` is now shipped with the SDK libraries, as the SDK redistribution terms require.
- The SDK version written to the `<softwareList>` of the mzML is now `5.0.4` (it was `2.8.7`, which was out of date).

### Changed
- **Bruker TDF-SDK 5.0.4** replaces SDK 3.3.701 (`timsdata.dll`, `libtimsdata.so`, `timsdata.lib`). SDK 3.3.701 cannot open schema v5 data. SDK 5.0.4 also opens schema 3.x data, and the spectrum count, peak count and metadata layout are the same as before.
- **Centroided peak areas change slightly for existing data.** The centroider in SDK 5.x splits the shared area of closely spaced peaks (about 40 ppm apart) at bin boundaries. SDK 3.3.701 split the shared bin by a fraction. The total of the two peaks is the same. No SDK parameter restores the old split. Measured on five schema 3.1, 3.6 and 3.8 datasets (DDA and DIA):
  - Raw scans, profile data, calibration and the MS1 and DIA centroid m/z values are identical.
  - MS1: 8 to 18 % of the centroided peaks have a different intensity (median 7 %). The TIC differs by 3e-6 or less.
  - DIA MS2: about 6 % of the peaks have a different intensity. The TIC differs by 5e-4 or less.
  - DDA MS2: 0.7 to 2.4 % of the peaks have a different intensity. The sparse peak picker moves m/z by up to 1 ppm. The TIC differs by 1.3e-3 or less. The base peak m/z changes in less than 2 % of the spectra.
  - Results from this version and from 0.6.x on the same data are not byte-identical. Results from this version are repeatable.
- File header differences from earlier 0.7.0 builds and 0.6.x: run and source-file IDs, the file checksum value, and the index offsets (see Fixed). Every `<spectrum>` element is byte-identical for the same input and options.
- `Frames` and `DiaFrameMsMsWindows` are read with named columns instead of `SELECT *` (the SDK guide says the column order can change).
- DIA windows are read once for all frames (one query per window group) instead of two queries per DIA frame, twice.
- The precursor count for the spectrum header is a reader method (`count_precursors_in_range`); `cli.py` no longer runs SQL.

### Fixed
- **Zip input overwrote the zip** — `tdf2mzml -i x.d.zip` without `-o` used the input path as the output path and destroyed the archive. The default output for `x.d.zip` and `x.zip` is now `x.mzML`, the `.d` suffix is matched in any case, and an output path equal to the input path is refused.
- **Zip input left its extracted data in the temp folder.** The archive is now extracted into a temporary directory that is removed at the end, also after an error.
- **A failed conversion left a complete-looking file** (index, checksum and closing tags, but fewer spectra than `spectrumList count`). The partial output is now deleted when an error occurs.
- **`--ms2_threshold` and `--ms2_nlargest` had no effect on TDF** (they worked for TSF and BAF only). They now apply to DDA and DIA MS2 spectra. The TDF default stays "no filtering" (threshold 0), so TDF output does not change unless the options are given. TSF and BAF keep the default threshold 10.
- **mzML IDs were not valid XML IDs.** `run` IDs started with a digit, `sourceFile` IDs were file paths (`D:\...`), and `software` IDs had spaces. They are now valid `xs:ID` values: the run ID is the sample name made valid, source files are `SF1` and `SF2`.
- **File checksum and index offsets did not follow the mzML schema.** The SHA-1 now covers the file up to and including the `<fileChecksum>` open tag (it stopped before the tag). Spectrum offsets and `indexListOffset` now point at the tag, not at the indentation before it.
- **Quotes in the operator name, method name or acquisition time broke the XML** in the run header (the same bug class as the 0.6.1 fix, missed there).
- **CV list:** PSI-MS is declared as version 4.2.15 (it said 4.1.30, older than terms we write, such as `MS:1003294`), and the Unit Ontology URI is `http://purl.obolibrary.org/obo/uo.obo` (the old URL returns 404).
- **TSF:** MS2 frames without MS2 info were skipped but still counted in `spectrumList count`. They are no longer counted. TSF schema v5 support is partial: MS2 frames of `MsMsType` 2 and 3 are read (ExD frames are type 3), and the `Fragmentation*` tables are read directly because the `FrameMsMsInfo` view drops ExD frames. It is tested only with an in-memory database, not with a real TSF v5 file. There is no precursor group on TSF.
- **TSF: the line spectrum read crashed** (`access violation`) on real files. The binding used a callback signature, but the SDK function (`tsf_read_line_spectrum_v2`) takes buffers and returns the needed length. It now reads with a growing buffer and converts the index values with `tsf_index_to_mz`. An empty frame gives an empty spectrum and no warning. Tested with two real MS1 TSF v5 files (ecTOF): peak counts and TIC match `Frames`, and the m/z and intensity arrays are identical to timsconvert.
- **BAF:** an MS2 spectrum without precursor data was written with a precursor m/z of 0. It is now written without a `<precursorList>`, and a warning is logged.

### Known limits
- ExD is written with the generic `MS:1003294` term. The schema does not say if a run is ECD or EID, so the electron beam energy value tells them apart.
- The reaction time is written as a `reaction time` userParam (ms), because PSI-MS has no term for it.
- A precursor whose frames have different activation settings gets one merged spectrum, labelled with its first activation. The converter logs a warning. The guided-PASEF files tested so far do not have such precursors.
- ExD in DIA-PASEF and PRM-PASEF is not supported. MS^n with n > 2 is written as ms level 2.
- TSF schema v5 MS2 and ExD frames are tested only with an in-memory database. The real TSF v5 files tested have MS1 frames only. There is no precursor group on TSF.
- The `IonizationType` of a multi-ionization TSF run (for example EI and CI frames) is not written to the mzML.
- The default `--ms1_threshold` is 100. Data with small intensities (ecTOF) loses most peaks with it, so use `--ms1_threshold 0` there.

## [0.6.1] — 2026-09-24

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
