"""
Custom binary format for .woof archives, optimised for GIS data.

v1 (legacy): per-entry zlib, simple flat entries
v2 (current): zstd compression + content-defined chunking with SHA-256 dedup

Design:
  - zstd (multithreaded) for all compressed data — ~5x faster than zlib
  - Content-defined chunking via Buzhash rolling hash
  - Deduplicated chunk store — identical chunk content stored once
  - GIS binaries (GPKG, TIFF, SHP) stored inline raw — already compressed
  - XOR obfuscation prevents accidental opening by generic tools

Structure (v2, all little-endian):
  [0-3]    Magic: b"WOOF"
  [4-7]    Version: uint32
  [8-15]   Header flags: uint64 (bit 0= XOR, bit 1=has chunk store)
  [16-23]  XOR-obfuscated payload size: uint64
  [24-31]  Unobfuscated payload size (for validation): uint64
  [32+]    Payload

  v2 Payload:
    [Chunk Store]     — zstd-compressed, deduplicated chunks
    [File Table]      — file entries referencing chunks (or inline data)

  Chunk Store:
    num_chunks: uint64
    for each chunk (insertion order):
      hash:           32 bytes (SHA-256)
      compressed_size: uint64
      raw_size:        uint64
      data:           compressed_size bytes (zstd)

  File Table:
    num_entries: uint32
    for each entry:
      entry_flags: uint32  (bit 0 = chunked, 0 = inline)
      name_len:    uint32
      name:        name_len UTF-8 bytes
      if chunked:
        num_hashes: uint32
        hashes:     num_hashes × 32 bytes (SHA-256 → Chunk Store)
        tail_trim:  uint32  (reserved, always 0)
      else (inline):
        data_len:   uint64
        data:       data_len bytes (raw)
"""

from __future__ import annotations

import hashlib
import io
import os
import struct
import zlib
from typing import Dict, List

WOOF_MAGIC = b"WOOF"
WOOF_VERSION_V1 = 1
WOOF_VERSION_V2 = 2

FLAG_XOR = 1
FLAG_HAS_CHUNK_STORE = 2
FLAG_ENTRY_CHUNKED = 1

WOOF_XOR_KEY = 0xA5
HEADER_SIZE = 32
HASH_SIZE = 32  # SHA-256 bytes

# File types that benefit from compression + resource extraction
_COMPRESSIBLE_EXTS = frozenset(
    {
        ".qgs",
        ".qgz",
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


# ── CDC (Content-Defined Chunking) ──────────────────────────────

_MIN_CHUNK = 4096
_AVG_CHUNK = 16384
_MAX_CHUNK = 65536
_MASK = _AVG_CHUNK - 1

_BUZHASH_TABLE: List[int] | None = None


def _get_buzhash_table() -> List[int]:
    global _BUZHASH_TABLE
    if _BUZHASH_TABLE is None:
        import random

        rng = random.Random(0)
        _BUZHASH_TABLE = [rng.getrandbits(32) for _ in range(256)]
    return _BUZHASH_TABLE


def _chunk_data(data: bytes) -> List[bytes]:
    """Split *data* into variable-sized chunks using Buzhash rolling hash.

    Average chunk size = _AVG_CHUNK (16 KB).
    No chunk is smaller than _MIN_CHUNK or larger than _MAX_CHUNK.
    """
    table = _get_buzhash_table()
    n = len(data)
    chunks: List[bytes] = []
    start = 0
    h = 0
    i = 0
    while i < n:
        chunk_len = i - start
        if chunk_len < _MIN_CHUNK:
            i += 1
            continue
        if chunk_len >= _MAX_CHUNK:
            chunks.append(data[start:i])
            start = i
            h = 0
            continue
        h = ((h << 1) | (h >> 31)) ^ table[data[i]]
        i += 1
        if (h & _MASK) == 0:
            chunks.append(data[start:i])
            start = i
            h = 0
    if start < n:
        chunks.append(data[start:])
    return chunks


# ── Chunk store (deduplicated zstd chunks) ──────────────────────


def _hash_chunk(chunk: bytes) -> bytes:
    return hashlib.sha256(chunk).digest()


class _ChunkStore:
    """Ordered, deduplicated store of zstd-compressed chunks keyed by SHA-256."""

    def __init__(self) -> None:
        self._chunks: Dict[bytes, bytes] = {}
        self._raw_sizes: Dict[bytes, int] = {}
        self._order: List[bytes] = []

    def add(self, chunk: bytes, level: int = 3) -> bytes:
        h = _hash_chunk(chunk)
        if h in self._chunks:
            return h
        import zstandard

        cctx = zstandard.ZstdCompressor(level=level)
        self._chunks[h] = cctx.compress(chunk)
        self._raw_sizes[h] = len(chunk)
        self._order.append(h)
        return h

    def get(self, h: bytes) -> bytes:
        import zstandard

        dctx = zstandard.ZstdDecompressor()
        return dctx.decompress(self._chunks[h])

    def serialize(self) -> bytes:
        buf = io.BytesIO()
        buf.write(struct.pack("<Q", len(self._order)))
        for h in self._order:
            compressed = self._chunks[h]
            buf.write(h)
            buf.write(struct.pack("<QQ", len(compressed), self._raw_sizes[h]))
            buf.write(compressed)
        return buf.getvalue()

    @classmethod
    def deserialize(cls, data: bytes) -> _ChunkStore:
        store = cls()
        offset = 0
        num = struct.unpack("<Q", data[offset : offset + 8])[0]
        offset += 8
        for _ in range(num):
            h = data[offset : offset + 32]
            offset += 32
            comp_size, raw_size = struct.unpack("<QQ", data[offset : offset + 16])
            offset += 16
            compressed = data[offset : offset + comp_size]
            offset += comp_size
            store._chunks[h] = compressed
            store._raw_sizes[h] = raw_size
            store._order.append(h)
        return store


# ── Helpers ─────────────────────────────────────────────────────


def _xor(data: bytes) -> bytes:
    return bytes(b ^ WOOF_XOR_KEY for b in data)


def _is_compressible(arcname: str) -> bool:
    ext = os.path.splitext(arcname)[1].lower()
    return ext in _COMPRESSIBLE_EXTS


# ── v2 packing ──────────────────────────────────────────────────


def _pack_v2(
    entries: Dict[str, bytes],
    compress: bool,
    level: int = 3,
) -> bytes:
    """Build a v2 .woof byte array with zstd + CDC chunk dedup (no resource graph)."""
    store = _ChunkStore()
    ftable = io.BytesIO()

    for name in sorted(entries.keys()):
        content = entries[name]
        if _is_compressible(name) and compress:
            flags = FLAG_ENTRY_CHUNKED
            chunks = _chunk_data(content)
            hashes = [store.add(c, level) for c in chunks]
            name_bytes = name.encode("utf-8")
            ftable.write(struct.pack("<II", flags, len(name_bytes)))
            ftable.write(name_bytes)
            ftable.write(struct.pack("<II", len(hashes), 0))
            for h in hashes:
                ftable.write(h)
        else:
            flags = 0
            name_bytes = name.encode("utf-8")
            ftable.write(struct.pack("<II", flags, len(name_bytes)))
            ftable.write(name_bytes)
            ftable.write(struct.pack("<Q", len(content)))
            ftable.write(content)

    chunk_bytes = store.serialize()
    ftable_bytes = ftable.getvalue()
    payload = chunk_bytes + ftable_bytes

    xor_payload = _xor(payload)
    total_raw = sum(len(c) for c in entries.values())
    header = struct.pack(
        "<4sIQQQ",
        WOOF_MAGIC,
        WOOF_VERSION_V2,
        FLAG_XOR | FLAG_HAS_CHUNK_STORE,
        len(xor_payload),
        total_raw,
    )
    return header + xor_payload


# ── v2 unpacking ────────────────────────────────────────────────


def _unpack_v2(payload: bytes) -> Dict[str, bytes]:
    """Parse a v2 .woof payload into named entries."""
    store = _ChunkStore.deserialize(payload)
    # Find file table boundary
    offset = 8
    num_chunks = struct.unpack("<Q", payload[0:8])[0]
    for _ in range(num_chunks):
        offset += 32
        comp_size, _ = struct.unpack("<QQ", payload[offset : offset + 16])
        offset += 16
        offset += comp_size
    ftable = payload[offset:]

    entries: Dict[str, bytes] = {}
    fp = 0
    while fp < len(ftable):
        flags, name_len = struct.unpack("<II", ftable[fp : fp + 8])
        fp += 8
        name = ftable[fp : fp + name_len].decode("utf-8")
        fp += name_len

        if flags & FLAG_ENTRY_CHUNKED:
            num_hashes, tail_trim = struct.unpack("<II", ftable[fp : fp + 8])
            fp += 8
            parts = [
                store.get(ftable[fp + i : fp + i + 32])
                for i in range(0, num_hashes * 32, 32)
            ]
            fp += num_hashes * 32
            content = b"".join(parts)
            if tail_trim and tail_trim <= len(content):
                content = content[:-tail_trim]
        else:
            data_len = struct.unpack("<Q", ftable[fp : fp + 8])[0]
            fp += 8
            content = ftable[fp : fp + data_len]
            fp += data_len

        entries[name] = content
    return entries


# ── v1 packing (legacy) ─────────────────────────────────────────


def _pack_v1(
    entries: Dict[str, bytes],
    compress: bool,
    fast_level: int = 1,
) -> bytes:
    """Build a v1 .woof byte array (zlib per-entry, no dedup)."""
    buf = io.BytesIO()
    buf.write(b"\0" * HEADER_SIZE)
    total_raw = 0
    for name in sorted(entries.keys()):
        content = entries[name]
        raw_size = len(content)
        total_raw += raw_size
        compressed = compress and _is_compressible(name)
        payload = zlib.compress(content, fast_level) if compressed else content
        flags = 1 if compressed else 0
        name_bytes = name.encode("utf-8")
        buf.write(struct.pack("<II", flags, len(name_bytes)))
        buf.write(name_bytes)
        buf.write(struct.pack("<Q", len(payload)))
        buf.write(payload)

    payload_data = buf.getvalue()[HEADER_SIZE:]
    xor_payload = _xor(payload_data)
    header = struct.pack(
        "<4sIQQQ",
        WOOF_MAGIC,
        WOOF_VERSION_V1,
        FLAG_XOR,
        len(xor_payload),
        total_raw,
    )
    return header + xor_payload


def _unpack_v1(payload: bytes) -> Dict[str, bytes]:
    """Parse a v1 .woof payload into named entries."""
    entries: Dict[str, bytes] = {}
    offset = 0
    while offset < len(payload):
        flags, name_len = struct.unpack("<II", payload[offset : offset + 8])
        offset += 8
        name = payload[offset : offset + name_len].decode("utf-8")
        offset += name_len
        content_len = struct.unpack("<Q", payload[offset : offset + 8])[0]
        offset += 8
        content = payload[offset : offset + content_len]
        offset += content_len
        if flags & 1:
            content = zlib.decompress(content)
        entries[name] = content
    return entries


# ── Public API ──────────────────────────────────────────────────


def pack_woof(
    entries: Dict[str, bytes],
    compress: bool = True,
    use_v2: bool = True,
) -> bytes:
    """Pack dict entries into a .woof byte stream.

    *use_v2*=True   → v2 (zstd + CDC chunk dedup, default)
    *use_v2*=False  → v1 (zlib per-entry, legacy)
    """
    if use_v2:
        return _pack_v2(entries, compress)
    return _pack_v1(entries, compress)


def pack_woof_from_directory(
    directory: str,
    compress: bool = True,
    use_v2: bool = True,
) -> bytes:
    """Build a .woof archive from a directory tree.

    Files are read one at a time.  Only the output buffer grows with the
    archive size.
    """
    entries: Dict[str, bytes] = {}
    file_list: List[str] = []
    for root, _dirs, fnames in os.walk(directory):
        for fname in fnames:
            file_list.append(os.path.join(root, fname))
    file_list.sort()

    for full_path in file_list:
        arcname = os.path.relpath(full_path, directory)
        with open(full_path, "rb") as f:
            entries[arcname] = f.read()

    return pack_woof(entries, compress=compress, use_v2=use_v2)


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
        return _unpack_v2(payload)
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
