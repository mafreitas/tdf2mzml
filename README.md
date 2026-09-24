# tdf2mzml

[![CI](https://github.com/mafreitas/tdf2mzml/actions/workflows/ci.yml/badge.svg)](https://github.com/mafreitas/tdf2mzml/actions/workflows/ci.yml)

**v0.6.1** -- Convert Bruker mass spectrometry data to indexed mzML 1.1.0

Author: Michael A. Freitas

---

## Overview

tdf2mzml converts Bruker raw data directories into fully indexed mzML 1.1.0 files with byte-offset spectrum indices for random access. It supports three Bruker acquisition formats and produces standards-compliant output suitable for downstream processing with any mzML-compatible tool.

## Supported Formats

| Format | Instrument families | Acquisition modes |
|--------|-------------------|-------------------|
| **TDF** (timsTOF PASEF) | timsTOF Pro, timsTOF HT, timsTOF SCP | DDA-PASEF, DIA-PASEF |
| **TSF** (timsTOF fleX / TIMS-off) | timsTOF fleX, timsTOF with TIMS disabled | MS1/MS2 interleaved |
| **BAF** (classic QTOF) | maXis, impact, other Bruker QTOF | Standard MS1/MS2 |

Format detection is automatic based on the contents of the `.d` directory (or a standalone `.baf` file).

## Installation

**Requirements:** Python >= 3.11

### From GitHub

```bash
pip install git+https://github.com/mafreitas/tdf2mzml
```

### From source

```bash
git clone https://github.com/mafreitas/tdf2mzml.git
cd tdf2mzml
make setup
```

### Dependencies

- `pydantic >= 2.0`
- `numpy >= 1.24`

The package bundles the required Bruker SDK libraries (`libtimsdata.so`, `timsdata.dll`, `libbaf2sql_c.so`) so no separate SDK installation is necessary.

## Quick Start

Convert a timsTOF PASEF dataset:

```bash
tdf2mzml -i /path/to/sample.d -o sample.mzML
```

Convert a BAF dataset with zlib compression:

```bash
tdf2mzml -i /path/to/sample.d --compression zlib -o sample.mzML
```

Convert a subset of frames with full ion mobility arrays:

```bash
tdf2mzml -i /path/to/sample.d -s 100 -e 500 --ion_mobility array -o subset.mzML
```

If `-o` is omitted, the output filename is derived from the input path.

## CLI Reference

```
tdf2mzml [-h] -i INPUT [-o OUTPUT] [--ms1_type {centroid,profile,raw}]
          [--ms1_threshold FLOAT] [--ms2_threshold FLOAT]
          [--ms2_nlargest INT] [-s INT] [-e INT]
          [--compression {none,zlib}] [--ion_mobility {none,mean,array}]
          [--precision FLOAT] [-d] [--version]
```

| Argument | Description | Default |
|----------|-------------|---------|
| `-i`, `--input` | Path to Bruker `.d` directory or `.baf` file (required) | -- |
| `-o`, `--output` | Output `.mzML` file path | Derived from input |
| `--ms1_type` | MS1 spectrum type: `centroid`, `profile`, or `raw` | `centroid` |
| `--ms1_threshold` | Minimum intensity for raw MS1 spectra | `100.0` |
| `--ms2_threshold` | Minimum intensity for MS2 spectra | `10.0` |
| `--ms2_nlargest` | Keep only the N most intense MS2 peaks; `-1` keeps all | `-1` |
| `-s`, `--start_frame` | First frame to convert; `-1` starts at the beginning | `-1` |
| `-e`, `--end_frame` | Last frame to convert; `-1` converts to the end | `-1` |
| `--compression` | Binary array compression: `none` or `zlib` | `none` |
| `--ion_mobility` | Ion mobility output mode: `none`, `mean`, or `array` | `mean` |
| `--precision` | m/z binning tolerance in ppm for raw mode | `10.0` |
| `-d`, `--debug` | Enable verbose/debug logging | Off |
| `--version` | Print version and exit | -- |

## Ion Mobility Modes

tdf2mzml provides three modes for handling trapped ion mobility spectrometry (TIMS) data in TDF files:

### `none`

No ion mobility data is written to the output. Spectra contain only m/z and intensity arrays.

### `mean` (default)

Each MS1 spectrum includes a single intensity-weighted mean inverse reduced ion mobility value (1/K0). The mean is computed across all mobility scans using per-scan total ion current as weights. This is compact and sufficient for most LC-MS workflows.

### `array`

Full ion-mobility-resolved output. Every peak from every mobility scan is preserved as a separate entry, with a parallel per-peak 1/K0 array alongside the m/z and intensity arrays. Peaks are sorted by m/z. This mode produces larger files but retains the complete mobility dimension for downstream ion mobility analysis.

## MS1 Spectrum Types

- **centroid** -- SDK peak-picked spectra aggregated across all mobility scans. Fastest and most compact.
- **profile** -- Full TOF bin range with bin-index-to-m/z conversion via the SDK.
- **raw** -- Vectorised merge of all scan lines: concatenate, apply intensity threshold, bulk index-to-m/z conversion, round to 4 decimal places, and sum coincident m/z values using numpy.

## Docker Usage

Pre-built images are available on Docker Hub as `mfreitas/tdf2mzml`.

| Tag | Description |
|-----|-------------|
| `latest` | Latest stable release (CMD-based, Nextflow-compatible) |
| `0.5` | v0.5/0.6 with ENTRYPOINT |
| `0.5_noentry` | v0.5/0.6 with CMD (same as `latest`) |
| `mhcquant` | v0.1 legacy image for MHCquant/nf-core pipelines |

### Pull and run from Docker Hub

```bash
# Pull the latest image
docker pull mfreitas/tdf2mzml:latest

# Convert a TDF dataset
docker run --rm -v $PWD:/data mfreitas/tdf2mzml -i /data/sample.d -o /data/sample.mzML

# Convert a BAF dataset with zlib compression
docker run --rm -v $PWD:/data mfreitas/tdf2mzml -i /data/sample.d --compression zlib

# Use the noentry variant (for Nextflow / workflow managers)
docker run --rm -v $PWD:/data mfreitas/tdf2mzml:0.5_noentry tdf2mzml -i /data/sample.d
```

### Build the image locally

```bash
make build
```

## Development

### Setup

```bash
git clone https://github.com/mafreitas/tdf2mzml.git
cd tdf2mzml
make setup    # installs asdf runtime + dev dependencies
```

The dev extras include `ruff`, `mypy`, `pytest`, and `pytest-cov`.

### Running all checks

```bash
make ci       # runs lint + typecheck + tests (same as CI pipeline)
```

### Individual targets

```bash
make lint      # ruff check + format verification
make typecheck # mypy strict mode
make test      # pytest with coverage (excludes slow/Docker tests)
make test-all  # pytest including slow tests (requires Docker)
make format    # auto-fix formatting
```

### CI/CD

Pull requests are automatically checked by GitHub Actions:

- **Lint** -- ruff check and format verification
- **Type check** -- mypy in strict mode across all modules
- **Test** -- 64+ mzML compliance tests with 85%+ coverage on critical output modules

All three jobs must pass before a PR can be merged.

## mzML Compliance

The output conforms to the mzML 1.1.0 specification:

- Every `<cvParam>` includes required `accession`, `cvRef="PSI-MS"`, and `value` attributes
- Unit-bearing parameters include full triplets (`unitCvRef`, `unitAccession`, `unitName`)
- `<binaryDataArray>` elements include `encodedLength`
- Spectrum IDs are 1-based (`id="index=1"`)
- All CV accessions verified against the PSI-MS controlled vocabulary
- Indexed mzML with byte-offset spectrum index and SHA-1 file checksum

## License

BSD 4-Clause License. Copyright (c) 2020, Michael A. Freitas, The Ohio State University.

See [LICENSE.md](LICENSE.md) for the full text.
