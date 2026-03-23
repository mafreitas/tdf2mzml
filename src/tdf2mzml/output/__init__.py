"""mzML output submodule: binary encoding, XML elements, and indexed writer.

Modules
-------
encoding
    Base64 encoding with optional zlib compression for binary data arrays.
xml_elements
    Low-level XML string builders for individual mzML elements (``<spectrum>``,
    ``<fileDescription>``, ``<cvList>``, etc.).  Uses direct string construction
    for byte-level offset control required by the indexed mzML format.
writer
    :class:`IndexedMzMLWriter` — high-level context-managed writer that
    produces a complete indexed mzML 1.1.0 file with spectrum byte-offset
    index and SHA-1 file checksum.
"""
