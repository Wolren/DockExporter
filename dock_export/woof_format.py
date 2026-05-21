"""
Custom binary format for .woof archives, optimised for GIS data.

v1 (legacy): per-entry zlib, simple flat entries
v2 (current): zstd compression per-file

Design:
  - zstd for all compressed data — ~5x faster than zlib
  - GIS binaries (GPKG, TIFF, SHP, PNG, JPG) stored inline raw

Structure (v2, all little-endian):
  [0-3]    Magic: b"WOOF"
  [4-7]    Version: uint32
  [8-15]   Header flags: uint64 (bit 0 = XOR)
  [16-23]  Payload size: uint64
  [24-31]  Total raw size: uint64
  [32+]    Payload

  v2 Payload:
    [File Table]      — file entries (zstd-compressed or inline raw)

  File Table:
    num_entries: uint32
    for each entry:
      entry_flags: uint32  (bit 1 = zstd compressed)
      name_len:    uint32
      name:        name_len UTF-8 bytes
      data_len:   uint64
      data:       data_len bytes (raw or zstd-compressed)
"""

from __future__ import annotations

import os
import struct
import zlib
from typing import Dict, List

import zstandard as _zstd

try:
    from ._woof_native import (
        NATIVE as _NATIVE,
        pack_v2 as _pack_v2_native,
        unpack_v2 as _unpack_v2_native,
    )
except ImportError:
    _NATIVE = False

WOOF_MAGIC = b"WOOF"
WOOF_VERSION_V1 = 1
WOOF_VERSION_V2 = 2

FLAG_XOR = 1
FLAG_ENTRY_ZSTD = 2

WOOF_XOR_KEY = 0xA5
_XOR_TABLE = bytes([i ^ WOOF_XOR_KEY for i in range(256)])
HEADER_SIZE = 32

# File types that benefit from compression + resource extraction
_COMPRESSIBLE_EXTS = frozenset(
    {
        ".qgs",
        ".qml",
        ".qlr",
        ".xml",
        ".xsl",
        ".xsd",
        ".csv",
        ".txt",
        ".json",
        ".geojson",
        ".topojson",
        ".yml",
        ".yaml",
        ".md",
        ".html",
        ".htm",
        ".css",
        ".js",
        ".py",
        ".bat",
        ".sh",
        ".cfg",
        ".conf",
        ".ini",
        ".prj",
        ".cpg",
        ".sld",
        ".gfs",
    }
)


# ── Helpers ─────────────────────────────────────────────────────


def _xor(data: bytes) -> bytes:
    return data.translate(_XOR_TABLE)


def _is_compressible(arcname: str) -> bool:
    ext = os.path.splitext(arcname)[1].lower()
    return ext in _COMPRESSIBLE_EXTS


# ── Iterator helpers for streaming ──────────────────────────────


def _iter_dict(entries: Dict[str, bytes]):
    """Yield sorted (name, content) pairs from a dict."""
    for name in sorted(entries.keys()):
        yield name, entries[name]


def _iter_directory(directory: str):
    """Yield sorted (name, content) pairs from a directory, reading one file at a time."""
    paths: List[str] = []
    for root, _dirs, fnames in os.walk(directory):
        for fname in fnames:
            paths.append(os.path.join(root, fname))
    paths.sort()
    for full_path in paths:
        arcname = os.path.relpath(full_path, directory)
        with open(full_path, "rb") as f:
            yield arcname, f.read()


# ── v2 packing ──────────────────────────────────────────────────


def _pack_v2(
    entries,
    compress: bool,
    level: int = 3,
) -> bytes:
    """Build a v2 .woof byte array with per-file zstd compression.

    *entries* is an iterable of (name, content) pairs (e.g. from _iter_dict or _iter_directory).
    """
    parts: List[bytes] = []
    cctx = _zstd.ZstdCompressor(level=level) if compress else None
    total_raw = 0

    for name, content in entries:
        total_raw += len(content)
        name_bytes = name.encode("utf-8")
        if compress:
            compressed = cctx.compress(content)
            if len(compressed) < len(content):
                parts.append(struct.pack("<II", FLAG_ENTRY_ZSTD, len(name_bytes)))
                parts.append(name_bytes)
                parts.append(struct.pack("<Q", len(compressed)))
                parts.append(compressed)
            else:
                parts.append(struct.pack("<II", 0, len(name_bytes)))
                parts.append(name_bytes)
                parts.append(struct.pack("<Q", len(content)))
                parts.append(content)
        else:
            parts.append(struct.pack("<II", 0, len(name_bytes)))
            parts.append(name_bytes)
            parts.append(struct.pack("<Q", len(content)))
            parts.append(content)

    ftable = b"".join(parts)
    header = struct.pack(
        "<4sIQQQ",
        WOOF_MAGIC,
        WOOF_VERSION_V2,
        0,
        len(ftable),
        total_raw,
    )
    return header + ftable


# ── v2 unpacking ────────────────────────────────────────────────


def _unpack_v2(payload: bytes, hdr_flags: int = 0) -> Dict[str, bytes]:
    """Parse a v2 .woof payload into named entries."""
    view = memoryview(payload)
    offset = 0
    # Legacy chunk store skip (v2 archives with CDC chunk store)
    if hdr_flags & 2:  # FLAG_HAS_CHUNK_STORE
        offset = 8
        num_chunks = struct.unpack("<Q", view[0:8])[0]
        for _ in range(num_chunks):
            if offset + 48 > len(view):
                raise ValueError("Truncated legacy chunk store")
            offset += 16  # hash (xxh128 was always used)
            comp_size, _ = struct.unpack("<QQ", view[offset : offset + 16])
            offset += 16 + comp_size
    ftable = view[offset:]

    entries: Dict[str, bytes] = {}
    fp = 0
    ftable_len = len(ftable)
    dctx = _zstd.ZstdDecompressor()
    while fp < ftable_len:
        flags, name_len = struct.unpack("<II", ftable[fp : fp + 8])
        fp += 8
        name = bytes(ftable[fp : fp + name_len]).decode("utf-8")
        fp += name_len

        if flags & FLAG_ENTRY_ZSTD:
            data_len = struct.unpack("<Q", ftable[fp : fp + 8])[0]
            fp += 8
            content = dctx.decompress(bytes(ftable[fp : fp + data_len]))
            fp += data_len
        else:
            data_len = struct.unpack("<Q", ftable[fp : fp + 8])[0]
            fp += 8
            content = bytes(ftable[fp : fp + data_len])
            fp += data_len

        entries[name] = content
    return entries


# ── v1 packing (legacy) ─────────────────────────────────────────


def _pack_v1(
    entries,
    compress: bool,
    level: int = 6,
) -> bytes:
    """Build a v1 .woof byte array (zlib per-entry, no dedup).

    *entries* is an iterable of (name, content) pairs.
    *level* = zlib compression level (1-9, default 6 matches ZIP).
    Uses try-compress-keep-smallest strategy for all files when *compress*=True.
    """
    parts: List[bytes] = []
    total_raw = 0
    for name, content in entries:
        total_raw += len(content)
        if compress:
            payload = zlib.compress(content, level)
            if len(payload) < len(content):
                flags = 1
            else:
                payload = content
                flags = 0
        else:
            payload = content
            flags = 0
        name_bytes = name.encode("utf-8")
        parts.append(struct.pack("<II", flags, len(name_bytes)))
        parts.append(name_bytes)
        parts.append(struct.pack("<Q", len(payload)))
        parts.append(payload)

    ftable = b"".join(parts)
    header = struct.pack(
        "<4sIQQQ",
        WOOF_MAGIC,
        WOOF_VERSION_V1,
        0,
        len(ftable),
        total_raw,
    )
    return header + ftable


def _unpack_v1(payload: bytes) -> Dict[str, bytes]:
    """Parse a v1 .woof payload into named entries."""
    entries: Dict[str, bytes] = {}
    view = memoryview(payload)
    offset = 0
    total = len(payload)
    while offset < total:
        flags, name_len = struct.unpack("<II", view[offset : offset + 8])
        offset += 8
        name = bytes(view[offset : offset + name_len]).decode("utf-8")
        offset += name_len
        content_len = struct.unpack("<Q", view[offset : offset + 8])[0]
        offset += 8
        if flags & 1:
            content = zlib.decompress(view[offset : offset + content_len])
        else:
            content = bytes(view[offset : offset + content_len])
        offset += content_len
        entries[name] = content
    return entries


# ── Public API ──────────────────────────────────────────────────


def pack_woof(
    entries: Dict[str, bytes],
    compress: bool = True,
    use_v2: bool = True,
) -> bytes:
    """Pack dict entries into a .woof byte stream.

    *use_v2*=True   → v2 (zstd per-file, default)
    *use_v2*=False  → v1 (zlib per-entry, legacy)
    """
    if _NATIVE and use_v2:
        return _pack_v2_native(entries, compress)
    if use_v2:
        return _pack_v2(_iter_dict(entries), compress)
    return _pack_v1(_iter_dict(entries), compress)


def pack_woof_from_directory(
    directory: str,
    compress: bool = True,
    use_v2: bool = True,
) -> bytes:
    """Build a .woof archive from a directory tree.

    Files are read one at a time, avoiding storing all content in memory at once.
    """
    if use_v2:
        return _pack_v2(_iter_directory(directory), compress)
    return _pack_v1(_iter_directory(directory), compress)


def pack_woof_to_file(
    output_path: str,
    entries,
    compress: bool = True,
) -> None:
    """Stream .woof archive directly to a file.

    *entries* is an iterable of (name, content) pairs.
    Writes sequentially without buffering the full archive in memory.
    """
    cctx = _zstd.ZstdCompressor(level=3) if compress else None
    total_raw = 0
    payload_size = 0

    with open(output_path, "wb") as f:
        # Placeholder header — patched after all entries
        f.write(b"\0" * HEADER_SIZE)

        for name, content in entries:
            total_raw += len(content)
            name_bytes = name.encode("utf-8")

            if compress:
                compressed = cctx.compress(content)
                use_compressed = len(compressed) < len(content)
            else:
                use_compressed = False

            if use_compressed:
                f.write(struct.pack("<II", FLAG_ENTRY_ZSTD, len(name_bytes)))
                f.write(name_bytes)
                f.write(struct.pack("<Q", len(compressed)))
                f.write(compressed)
                payload_size += 8 + len(name_bytes) + 8 + len(compressed)
            else:
                f.write(struct.pack("<II", 0, len(name_bytes)))
                f.write(name_bytes)
                f.write(struct.pack("<Q", len(content)))
                f.write(content)
                payload_size += 8 + len(name_bytes) + 8 + len(content)

        # Patch header with actual sizes
        f.seek(0)
        f.write(
            struct.pack(
                "<4sIQQQ",
                WOOF_MAGIC,
                WOOF_VERSION_V2,
                0,
                payload_size,
                total_raw,
            )
        )


def unpack_woof(data: bytes) -> Dict[str, bytes]:
    """Unpack a .woof byte stream into named entries.

    Supports v1 and v2.  Raises ValueError on invalid or truncated data.
    """
    if len(data) < HEADER_SIZE:
        raise ValueError("Truncated .woof file")
    magic = data[0:4]
    if magic != WOOF_MAGIC:
        raise ValueError(f"Not a .woof file (magic: {magic!r})")

    version, hdr_flags, xor_size, _total_raw = struct.unpack("<IQQQ", data[4:32])
    payload = data[HEADER_SIZE : HEADER_SIZE + xor_size]
    if len(payload) < xor_size:
        raise ValueError("Truncated .woof payload")
    if hdr_flags & FLAG_XOR:
        payload = _xor(payload)

    if version == WOOF_VERSION_V2:
        return _unpack_v2(payload, hdr_flags)
    return _unpack_v1(payload)


def extract_woof_to_directory(data: bytes, target_dir: str) -> None:
    """Extract a .woof archive into a directory."""
    entries = unpack_woof(data)
    os.makedirs(target_dir, exist_ok=True)
    for arcname, content in entries.items():
        dst = os.path.join(target_dir, arcname)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(dst, "wb") as f:
            f.write(content)


def woof_magic_bytes() -> bytes:
    return WOOF_MAGIC
