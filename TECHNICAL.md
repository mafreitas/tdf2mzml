# tdf2mzml -- Technical Documentation

This document describes the internal architecture, data flow, and conversion algorithms of tdf2mzml v0.5.0.

---

## Architecture

The source code lives under `src/tdf2mzml/` and is organized into five subpackages plus top-level orchestration modules:

```
src/tdf2mzml/
    __init__.py
    cli.py              # Entry point, arg parsing, format detection, conversion dispatch
    constants.py        # Shared constants (CV terms, namespaces, etc.)
    utils.py            # Small utility functions
    io/
        __init__.py
        reader.py       # TdfReader -- high-level TDF/timsTOF SDK wrapper
        tsf_reader.py   # TsfReader -- TSF format reader
        baf_reader.py   # BafReader -- BAF format reader
        timsdata.py     # Low-level ctypes bindings for libtimsdata.so / timsdata.dll
        bafdata.py      # Low-level ctypes bindings for libbaf2sql_c.so
    models/
        __init__.py
        config.py       # ConversionConfig (Pydantic) -- all CLI options in one model
        metadata.py     # AcquisitionMetadata -- instrument, acquisition, and run info
        spectrum.py     # PrecursorInfo, SpectrumArrays -- per-spectrum data containers
    processing/
        __init__.py
        ms1.py          # MS1 spectrum extraction: centroid, profile, raw, IM-resolved
        ms2.py          # MS2 spectrum extraction: DDA-PASEF, DIA-PASEF
        mobility.py     # Ion mobility transforms: intensity-weighted mean 1/K0
    output/
        __init__.py
        writer.py       # IndexedMzMLWriter -- top-level mzML document construction
        xml_elements.py # String builders for individual mzML XML elements
        encoding.py     # Base64 encoding and optional zlib compression for binary arrays
```

### Design Principles

- **Pydantic models** for configuration and metadata ensure validated, typed data flows between stages.
- **Direct string construction** for XML output (not ElementTree) gives byte-level control required for indexed mzML offset tracking.
- **Bulk SQL queries** for precursor and PASEF frame info minimize database round-trips.
- **Processing functions are pure transforms** -- they receive arrays and return arrays, with no I/O side effects.

---

## Module Details

### `cli.py` -- Orchestration

The main entry point (`main()`) builds an argument parser, constructs a `ConversionConfig`, detects the input format, and dispatches to the appropriate conversion function:

- `run_conversion()` -- TDF (timsTOF PASEF) pipeline
- `run_tsf_conversion()` -- TSF pipeline
- `run_baf_conversion()` -- BAF pipeline

### `io/` -- Format Readers

**TdfReader** (`reader.py`): Opens a `.d` directory containing `analysis.tdf`. Wraps the Bruker TimsData SDK to provide methods for extracting centroided and profile spectra, reading frame metadata from the SQLite database, and converting scan indices to 1/K0 values.

**TsfReader** (`tsf_reader.py`): Handles `.d` directories containing `analysis.tsf` (without `analysis.tdf`). Uses `tsf_read_line_spectrum_v2` from the SDK. No ion mobility dimension.

**BafReader** (`baf_reader.py`): Handles `.d` directories containing `analysis.baf` or standalone `.baf` files. Uses `libbaf2sql_c` which generates a temporary SQLite cache from the binary BAF data. Reads the Spectra table joined with AcquisitionKeys for MS level and polarity.

**timsdata.py**: Low-level ctypes wrapper around `libtimsdata.so` (Linux) or `timsdata.dll` (Windows). Provides the C function signatures for `tims_open`, `tims_read_scans_v2`, `tims_extract_centroided_spectrum_for_frame_v2`, scan-to-1/K0 conversion, and related functions.

**bafdata.py**: Low-level ctypes wrapper around `libbaf2sql_c.so`. Provides C function signatures for opening BAF storage, generating the SQLite cache, and reading line/profile spectra.

### `models/` -- Data Models

**ConversionConfig** (`config.py`): A Pydantic model holding all user-facing options: input/output paths, ms1_type, thresholds, frame range, compression mode, ion mobility mode, precision, and debug flag.

**AcquisitionMetadata** (`metadata.py`): Instrument configuration, acquisition parameters, and run-level metadata extracted from the GlobalMetadata table (TDF/TSF) or the Spectra/AcquisitionKeys tables (BAF).

**PrecursorInfo** (`spectrum.py`): Per-MS2-spectrum precursor data: selected ion m/z, charge state, isolation window offsets, collision energy, and scan number range (for PASEF).

**SpectrumArrays** (`spectrum.py`): Container for the numeric arrays that make up a spectrum: m/z, intensity, and optionally ion mobility (1/K0) arrays.

### `processing/` -- Data Transforms

**ms1.py**: Functions for each MS1 type:
- `centroid` -- calls the SDK's peak-picking across all mobility scans
- `profile` -- reads the full TOF bin range and converts bin indices to m/z via the SDK
- `raw` -- vectorised merge of all scan lines: concatenate arrays, apply intensity threshold, bulk index-to-m/z conversion, round to 4 decimal places, use `numpy.unique` + `numpy.bincount` for coincident m/z summation
- IM-resolved variants that produce parallel per-peak 1/K0 arrays

**ms2.py**: MS2 spectrum extraction for DDA-PASEF and DIA-PASEF modes. DDA uses `read_pasef_msms` SDK calls; DIA extracts centroided spectra for specific scan ranges corresponding to each DIA window.

**mobility.py**: Computes intensity-weighted mean 1/K0 for a set of mobility scans. Uses per-scan total ion current as weights.

### `output/` -- mzML Generation

**IndexedMzMLWriter** (`writer.py`): Manages the overall document lifecycle. Opens the output file with a buffered writer (4 MB chunks), writes the XML header sections (cvList, fileDescription, softwareList, instrumentConfigurationList, sampleList, dataProcessingList, run element, spectrumList), provides methods to write individual spectrum elements, and finalizes the document with the byte-offset index and SHA-1 file checksum.

**xml_elements.py**: Pure functions that build mzML XML strings for spectrum elements, binary data arrays, precursor elements, CV params, and other mzML constructs. String concatenation is used deliberately for byte-offset predictability.

**encoding.py**: Encodes numpy arrays to base64 binary data arrays with optional zlib compression. Handles both 32-bit and 64-bit float encodings.

---

## Conversion Algorithms

### Format Detection

In `cli.py:run_conversion`, the input format is detected by examining the input path and the contents of the `.d` directory:

1. If the path ends with `.baf` or the directory contains `analysis.baf` (without TDF/TSF files) -- **BAF mode**
2. If the directory contains `analysis.tsf` but not `analysis.tdf` -- **TSF mode**
3. Otherwise -- **TDF mode** (default)

### TDF Conversion Pipeline

The TDF pipeline (`run_conversion` + `_write_spectra`) handles timsTOF PASEF data with full ion mobility support:

1. **Open reader**: Instantiate `TdfReader`, which loads the Bruker SDK shared library and opens an SQLite connection to `analysis.tdf`.

2. **Build metadata**: Construct `AcquisitionMetadata` from the GlobalMetadata table (instrument type, acquisition mode, m/z range, etc.).

3. **Resolve frame range**: Apply `start_frame` / `end_frame` from config, defaulting to the full range.

4. **Count total spectra**: Sum of MS1 frames + DDA precursors + DIA windows across the frame range. This count is written into the `spectrumList count` attribute.

5. **Bulk-load DDA precursors**: A single SQL query retrieves all precursor entries (selected m/z, charge, scan number, parent frame) for the entire frame range.

6. **Bulk-load PASEF frame info**: A single SQL query retrieves isolation m/z, isolation width, collision energy, and scan number ranges for all precursor entries.

7. **Open writer**: Instantiate `IndexedMzMLWriter`, which writes the XML preamble and all header sections (cvList, fileDescription, softwareList, instrumentConfigurationList, sampleList, dataProcessingList, opening run and spectrumList tags).

8. **Iterate frames** in order:

   - **MS1 frames** (MsMsType=0):
     - Extract spectrum via SDK (`extract_centroided_spectrum_for_frame_v2` for centroid mode, or scan-level reads for profile/raw)
     - Optionally compute ion mobility: mean (intensity-weighted 1/K0 across scans) or array (full per-peak 1/K0)
     - Write the spectrum element with byte offset recorded

   - **DDA precursors** (after each MS1 frame):
     - Emit all DDA precursors whose `Parent` frame matches the current MS1 frame
     - Use batch SDK call `read_pasef_msms` for efficient extraction
     - Batch scan-index-to-1/K0 conversion
     - Build `PrecursorInfo` with isolation window offsets (computed from the PASEF frame info)
     - Write each MS2 spectrum element

   - **DIA frames** (MsMsType=9):
     - For each window in the frame's window group, extract a centroided spectrum over the scan range defined by the window
     - Build `PrecursorInfo` from the DIA window definition (target m/z, isolation width)
     - Write the MS2 spectrum element

9. **Finalize**:
   - Close the `</spectrumList>`, `</run>`, `</mzML>` tags
   - Write the `<indexList>` containing byte offsets for every spectrum
   - Write the `<indexListOffset>` value
   - Compute and write `<fileChecksum>` (SHA-1 of everything before the checksum element)
   - Close `</indexedmzML>`

### TSF Conversion Pipeline

The TSF pipeline (`run_tsf_conversion`) handles timsTOF data without the ion mobility dimension:

1. Open `TsfReader` (SDK + SQLite connection to `analysis.tsf`)
2. Build `AcquisitionMetadata` from GlobalMetadata
3. Read frame metadata; MS2 info comes from the `FrameMsMsInfo` table (TriggerMass, IsolationWidth, CollisionEnergy)
4. No PASEF batching, no DIA -- simple interleaved MS1/MS2 iteration
5. Extract spectra using `tsf_read_line_spectrum_v2`
6. Write via `IndexedMzMLWriter` with the same finalization as TDF

### BAF Conversion Pipeline

The BAF pipeline (`run_baf_conversion`) handles classic Bruker QTOF data:

1. Open `BafData` via `libbaf2sql_c` (the library generates a temporary SQLite cache from the binary `.baf` file)
2. Read the `Spectra` table joined with `AcquisitionKeys` to determine MS level and polarity for each spectrum
3. For MS2 spectra, read precursor information:
   - Precursor mass from the `Steps` table
   - Collision energy and isolation width from the `Variables` view
   - Handle 0-indexed vs 1-indexed `Steps.Number` via a `MIN(Number)` subquery
4. Supports both standalone `.baf` files and `.baf` files within `.d` directories
5. Write via `IndexedMzMLWriter` with the same finalization steps

---

## MS1 Spectrum Types

### Centroid

Calls the SDK function `extract_centroided_spectrum_for_frame_v2`, which performs peak-picking across all mobility scans and returns deduplicated m/z + intensity arrays. This is the fastest mode and produces the smallest output.

### Profile

Reads the full TOF bin range for the frame. Bin indices are converted to m/z values via the SDK's calibration function. The resulting arrays represent the continuous profile spectrum.

### Raw

A vectorised merge of all individual scan lines within a frame:

1. Read all scans for the frame, collecting per-scan m/z index and intensity arrays
2. Concatenate all arrays
3. Apply the `ms1_threshold` intensity filter
4. Bulk-convert TOF bin indices to m/z values via the SDK
5. Round m/z values to 4 decimal places
6. Use `numpy.unique` to find distinct m/z values and `numpy.bincount` (or equivalent) to sum intensities at coincident m/z bins

This mode preserves more spectral detail than centroid but produces larger output than profile.

---

## Ion Mobility Modes

### None

No ion mobility information is included in the output. Each spectrum contains only m/z and intensity binary data arrays.

### Mean

For each MS1 spectrum, the intensity-weighted mean 1/K0 is computed:

1. For each mobility scan in the frame, compute the total ion current (TIC)
2. Convert each scan index to its 1/K0 value via the SDK
3. Compute the weighted mean: `sum(TIC_i * oneOverK0_i) / sum(TIC_i)`
4. Store as a single CV param on the spectrum element

### Array

Full ion-mobility-resolved output:

1. Read every peak from every mobility scan in the frame
2. For each peak, look up the 1/K0 value corresponding to its scan index
3. Produce three parallel arrays: m/z, intensity, and 1/K0
4. Sort all arrays by m/z
5. Write the 1/K0 array as an additional binary data array alongside m/z and intensity

This mode can significantly increase output file size but preserves the complete ion mobility dimension.

---

## Indexed mzML Output

### Structure

The output conforms to the indexed mzML 1.1.0 specification:

```xml
<?xml version="1.0" encoding="utf-8"?>
<indexedmzML xmlns="...">
  <mzML>
    <cvList> ... </cvList>
    <fileDescription> ... </fileDescription>
    <softwareList> ... </softwareList>
    <instrumentConfigurationList> ... </instrumentConfigurationList>
    <sampleList> ... </sampleList>
    <dataProcessingList> ... </dataProcessingList>
    <run>
      <spectrumList count="N">
        <spectrum index="0" ...> ... </spectrum>
        <spectrum index="1" ...> ... </spectrum>
        ...
      </spectrumList>
    </run>
  </mzML>
  <indexList count="1">
    <index name="spectrum">
      <offset idRef="...">byte_offset</offset>
      ...
    </index>
  </indexList>
  <indexListOffset>byte_offset</indexListOffset>
  <fileChecksum>sha1_hex</fileChecksum>
</indexedmzML>
```

### Implementation Details

- **Direct string construction**: XML elements are built via string concatenation in `xml_elements.py`, not via an XML library. This is deliberate -- it provides exact control over byte offsets, which are required for the spectrum index.

- **Buffered writer**: The writer uses 4 MB write buffers to reduce system call overhead while maintaining an accurate running byte count.

- **Incremental SHA-1**: A SHA-1 hash is updated incrementally as bytes are written. The `<fileChecksum>` value covers all bytes from the start of the file up to (but not including) the `<fileChecksum>` element itself.

- **Byte-offset index**: As each `<spectrum>` element is written, its starting byte offset is recorded. These offsets are emitted in the `<indexList>` section after the `</mzML>` closing tag, enabling random access by any mzML reader.

---

## Data Flow

```
.d directory
    |
    +-- analysis.tdf ----> TdfReader ----> TimsData (SDK)
    +-- analysis.tsf ----> TsfReader ----> TsfData (SDK)
    +-- analysis.baf ----> BafReader ----> BafData (libbaf2sql_c)
                              |
                              v
                     AcquisitionMetadata
                              |
                     +--------+--------+
                     |                 |
              MS1 processing    MS2 processing
              (ms1.py)          (ms2.py)
                     |                 |
                     v                 v
              SpectrumArrays    SpectrumArrays + PrecursorInfo
                     |                 |
                     +--------+--------+
                              |
                     IndexedMzMLWriter
                     (xml_elements.py + encoding.py)
                              |
                              v
                     output.mzML (indexed)
```

---

## SDK Libraries

tdf2mzml bundles the following Bruker SDK shared libraries in `src/tdf2mzml/libs/`:

| Library | Platform | Purpose |
|---------|----------|---------|
| `libtimsdata.so` | Linux | TDF and TSF format access |
| `timsdata.dll` | Windows | TDF and TSF format access |
| `libbaf2sql_c.so` | Linux | BAF format access (generates SQLite from binary BAF) |

These libraries are loaded at runtime via ctypes. The Python wrappers (`timsdata.py`, `bafdata.py`) define the C function signatures and handle platform-specific library loading.

---

## Performance Considerations

- **Bulk SQL queries**: Precursor and PASEF frame info are loaded in bulk (one query for the entire frame range) rather than per-frame, reducing SQLite overhead significantly for large datasets.
- **Batch SDK calls**: `read_pasef_msms` processes multiple precursors in a single SDK call.
- **Vectorised numpy operations**: The raw MS1 mode uses numpy vectorisation for m/z binning and intensity summation, avoiding Python-level loops over individual peaks.
- **Buffered I/O**: 4 MB write buffers minimize system call overhead during output.
- **String-based XML**: Avoids the overhead of DOM construction and serialization that would come with ElementTree or lxml.

## Docker Image

The project includes a `Dockerfile` for containerised deployment. The image is published on Docker Hub as [`mfreitas/tdf2mzml`](https://hub.docker.com/r/mfreitas/tdf2mzml).

### Image structure

- **Base image**: `python:3.12-slim`
- **System dependency**: `libgomp1` (OpenMP runtime required by `libbaf2sql_c.so`)
- **SDK library path**: Registered via `ldconfig` in `/etc/ld.so.conf.d/tdf2mzml.conf` so the Bruker SDK shared libraries (`libtimsdata.so`, `libbaf2sql_c.so`) are discoverable at runtime.
- **Entrypoint**: `tdf2mzml` CLI
- **Build artefacts removed**: `src/` and `pyproject.toml` are deleted after `pip install` to keep the image lean.

### Building

```bash
docker build -t mfreitas/tdf2mzml:0.5 .
docker tag mfreitas/tdf2mzml:0.5 mfreitas/tdf2mzml:latest
```

### Publishing to Docker Hub

```bash
docker login
docker push mfreitas/tdf2mzml:0.5
docker push mfreitas/tdf2mzml:latest
```

### Running

```bash
# Mount the current directory and convert a dataset
docker run --rm -v $PWD:/data mfreitas/tdf2mzml -i /data/sample.d -o /data/sample.mzML

# All CLI arguments are passed through
docker run --rm -v $PWD:/data mfreitas/tdf2mzml -i /data/sample.d --compression zlib --ion_mobility array
```
