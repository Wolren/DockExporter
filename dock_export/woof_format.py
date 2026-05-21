"""
Custom binary format for .woof archives, optimised for GIS data.

v1 (legacy): per-entry zlib, simple flat entries
v2 (current): zstd compression + content-defined chunking with dedup

Design:
  - zstd for all compressed data — ~5x faster than zlib
  - FastCDC content-defined chunking via Gear rolling hash
  - Deduplicated chunk store — identical chunk content stored once
  - GIS binaries (GPKG, TIFF, SHP, PNG, JPG) stored inline raw

Structure (v2, all little-endian):
  [0-3]    Magic: b"WOOF"
  [4-7]    Version: uint32
  [8-15]   Header flags: uint64 (bit 1=has chunk store)
  [16-23]  Payload size: uint64
  [24-31]  Total raw size: uint64
  [32+]    Payload

  v2 Payload:
    [Chunk Store]     — optional, zstd-compressed deduplicated chunks
    [File Table]      — file entries referencing chunks (or inline data)

  Chunk Store:
    num_chunks: uint64
    for each chunk (insertion order):
      hash:           HASH_SIZE bytes (xxh128 if available, sha256 fallback)
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
        hashes:     num_hashes × HASH_SIZE bytes
        tail_trim:  uint32  (reserved, always 0)
      else (inline):
        data_len:   uint64
        data:       data_len bytes (raw)
"""

from __future__ import annotations

import os
import struct
import zlib
from typing import Dict, List

import zstandard as _zstd

try:
    import xxhash as _xxhash

    _HASH_AVAILABLE = True
except ImportError:
    _HASH_AVAILABLE = False

WOOF_MAGIC = b"WOOF"
WOOF_VERSION_V1 = 1
WOOF_VERSION_V2 = 2

FLAG_XOR = 1
FLAG_HAS_CHUNK_STORE = 2
FLAG_ENTRY_CHUNKED = 1
FLAG_ENTRY_ZSTD = 2

WOOF_XOR_KEY = 0xA5
HEADER_SIZE = 32
HASH_SIZE = 16 if _HASH_AVAILABLE else 32

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


# ── CDC (Content-Defined Chunking) ──────────────────────────────

_MIN_CHUNK = 4096
_AVG_CHUNK = 16384
_MAX_CHUNK = 65536
_MASK = _AVG_CHUNK - 1

_GEAR_TABLE: List[int] | None = None


def _get_gear_table() -> List[int]:
    global _GEAR_TABLE
    if _GEAR_TABLE is None:
        import random

        rng = random.Random(42)
        _GEAR_TABLE = [rng.getrandbits(64) for _ in range(256)]
    return _GEAR_TABLE


def _chunk_data(data: bytes) -> List[bytes]:
    """FastCDC-style content-defined chunking using Gear rolling hash.

    Average chunk size = _AVG_CHUNK (16 KB).
    No chunk is smaller than _MIN_CHUNK or larger than _MAX_CHUNK.
    Uses a kickstart loop to skip boundary checks up to _MIN_CHUNK,
    then re-kickstarts after each boundary for tighter distribution.
    """
    n = len(data)
    if n == 0:
        return []
    if n <= _MIN_CHUNK:
        return [data]

    table = _get_gear_table()
    chunks: List[bytes] = []
    start = 0
    h = 0
    i = 0

    while i < n:
        # Kickstart: skip boundary checks up to _MIN_CHUNK
        while i < n and (i - start) < _MIN_CHUNK:
            h = (h << 1) + table[data[i]]
            i += 1

        # Normal phase: check boundaries up to _MAX_CHUNK
        found = False
        while i < n and (i - start) < _MAX_CHUNK:
            h = (h << 1) + table[data[i]]
            i += 1
            if (h & _MASK) == 0:
                chunks.append(data[start:i])
                start = i
                h = 0
                found = True
                break

        if not found and i > start:
            # Force split at _MAX_CHUNK
            chunks.append(data[start:i])
            start = i
            h = 0

    if start < n:
        chunks.append(data[start:])
    return chunks


# ── Chunk store (deduplicated zstd chunks) ──────────────────────


if _HASH_AVAILABLE:

    def _hash_chunk(chunk: bytes) -> bytes:
        return _xxhash.xxh128(chunk).digest()

else:
    import hashlib as _hashlib

    def _hash_chunk(chunk: bytes) -> bytes:
        return _hashlib.sha256(chunk).digest()


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
        cctx = _zstd.ZstdCompressor(level=level)
        self._chunks[h] = cctx.compress(chunk)
        self._raw_sizes[h] = len(chunk)
        self._order.append(h)
        return h

    def add_by_hash(self, chunk: bytes, h: bytes, level: int = 3) -> bytes:
        """Add chunk with pre-computed hash (avoids re-hashing)."""
        if h in self._chunks:
            return h
        cctx = _zstd.ZstdCompressor(level=level)
        self._chunks[h] = cctx.compress(chunk)
        self._raw_sizes[h] = len(chunk)
        self._order.append(h)
        return h

    def get(self, h: bytes) -> bytes:
        dctx = _zstd.ZstdDecompressor()
        return dctx.decompress(self._chunks[h])

    def get_raw_size(self, h: bytes) -> int:
        return self._raw_sizes.get(h, 0)

    def sum_raw_sizes(self, hashes: List[bytes], raw_sizes: List[int]) -> int:
        """Return total raw size of chunks, counting stored dedup sizes."""
        total = 0
        for h, sz in zip(hashes, raw_sizes):
            total += self._raw_sizes.get(h, sz)
        return total

    def serialize(self) -> bytes:
        buf = bytearray()
        buf.extend(struct.pack("<Q", len(self._order)))
        for h in self._order:
            compressed = self._chunks[h]
            buf.extend(h)
            buf.extend(struct.pack("<QQ", len(compressed), self._raw_sizes[h]))
            buf.extend(compressed)
        return bytes(buf)

    @classmethod
    def deserialize(cls, data: bytes) -> _ChunkStore:
        store = cls()
        view = memoryview(data)
        offset = 0
        num = struct.unpack("<Q", view[offset : offset + 8])[0]
        offset += 8
        for _ in range(num):
            h = bytes(view[offset : offset + HASH_SIZE])
            offset += HASH_SIZE
            comp_size, raw_size = struct.unpack("<QQ", view[offset : offset + 16])
            offset += 16
            compressed = bytes(view[offset : offset + comp_size])
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
    """Build a v2 .woof byte array with zstd + CDC chunk dedup."""
    store = _ChunkStore()
    ftable = bytearray()
    cctx = _zstd.ZstdCompressor(level=level, threads=-1) if compress else None

    for name in sorted(entries.keys()):
        content = entries[name]
        name_bytes = name.encode("utf-8")
        if compress:
            compressed = cctx.compress(content)
            if len(compressed) < len(content):
                # whole-file zstd helps — also try CDC for text files
                if len(content) >= 32768 and _is_compressible(name):
                    chunks = _chunk_data(content)
                    chunk_hashes = [_hash_chunk(c) for c in chunks]
                    chunk_sizes = [len(c) for c in chunks]
                    dedup_raw = store.sum_raw_sizes(chunk_hashes, chunk_sizes)
                    if dedup_raw < len(content):
                        hashes = [
                            store.add_by_hash(c, h, level)
                            for c, h in zip(chunks, chunk_hashes)
                        ]
                        ftable.extend(
                            struct.pack("<II", FLAG_ENTRY_CHUNKED, len(name_bytes))
                        )
                        ftable.extend(name_bytes)
                        ftable.extend(struct.pack("<II", len(hashes), 0))
                        for h in hashes:
                            ftable.extend(h)
                        continue
                flags = FLAG_ENTRY_ZSTD
                ftable.extend(struct.pack("<II", flags, len(name_bytes)))
                ftable.extend(name_bytes)
                ftable.extend(struct.pack("<Q", len(compressed)))
                ftable.extend(compressed)
            else:
                ftable.extend(struct.pack("<II", 0, len(name_bytes)))
                ftable.extend(name_bytes)
                ftable.extend(struct.pack("<Q", len(content)))
                ftable.extend(content)
        else:
            ftable.extend(struct.pack("<II", 0, len(name_bytes)))
            ftable.extend(name_bytes)
            ftable.extend(struct.pack("<Q", len(content)))
            ftable.extend(content)

    has_chunks = len(store._order) > 0
    chunk_bytes = store.serialize() if has_chunks else b""
    payload = chunk_bytes + bytes(ftable)

    total_raw = sum(len(c) for c in entries.values())
    flags = 0
    if has_chunks:
        flags |= FLAG_HAS_CHUNK_STORE
    header = struct.pack(
        "<4sIQQQ",
        WOOF_MAGIC,
        WOOF_VERSION_V2,
        flags,
        len(payload),
        total_raw,
    )
    return header + payload


# ── v2 unpacking ────────────────────────────────────────────────


def _unpack_v2(payload: bytes, hdr_flags: int = 0) -> Dict[str, bytes]:
    """Parse a v2 .woof payload into named entries."""
    store = _ChunkStore()
    view = memoryview(payload)
    offset = 0
    if hdr_flags & FLAG_HAS_CHUNK_STORE:
        store = _ChunkStore.deserialize(payload)
        offset = 8
        num_chunks = struct.unpack("<Q", view[0:8])[0]
        for _ in range(num_chunks):
            offset += HASH_SIZE
            comp_size, _ = struct.unpack("<QQ", view[offset : offset + 16])
            offset += 16 + comp_size
    ftable = view[offset:]

    entries: Dict[str, bytes] = {}
    fp = 0
    ftable_len = len(ftable)
    while fp < ftable_len:
        flags, name_len = struct.unpack("<II", ftable[fp : fp + 8])
        fp += 8
        name = bytes(ftable[fp : fp + name_len]).decode("utf-8")
        fp += name_len

        if flags & FLAG_ENTRY_CHUNKED:
            num_hashes, tail_trim = struct.unpack("<II", ftable[fp : fp + 8])
            fp += 8
            hash_bytes_len = num_hashes * HASH_SIZE
            parts = [
                store.get(bytes(ftable[fp + i : fp + i + HASH_SIZE]))
                for i in range(0, hash_bytes_len, HASH_SIZE)
            ]
            fp += hash_bytes_len
            content = b"".join(parts)
            if tail_trim and tail_trim <= len(content):
                content = content[:-tail_trim]
        elif flags & FLAG_ENTRY_ZSTD:
            dctx = _zstd.ZstdDecompressor()
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
    entries: Dict[str, bytes],
    compress: bool,
    level: int = 6,
) -> bytes:
    """Build a v1 .woof byte array (zlib per-entry, no dedup).

    *level* = zlib compression level (1-9, default 6 matches ZIP).
    Uses try-compress-keep-smallest strategy for all files when *compress*=True.
    """
    buf = bytearray()
    buf.extend(b"\0" * HEADER_SIZE)
    total_raw = 0
    for name in sorted(entries.keys()):
        content = entries[name]
        raw_size = len(content)
        total_raw += raw_size
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
        buf.extend(struct.pack("<II", flags, len(name_bytes)))
        buf.extend(name_bytes)
        buf.extend(struct.pack("<Q", len(payload)))
        buf.extend(payload)

    payload_data = bytes(buf[HEADER_SIZE:])
    header = struct.pack(
        "<4sIQQQ",
        WOOF_MAGIC,
        WOOF_VERSION_V1,
        0,
        len(payload_data),
        total_raw,
    )
    return header + payload_data


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
        content = bytes(view[offset : offset + content_len])
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
