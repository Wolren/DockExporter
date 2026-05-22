"""Pure-Python fallback .woof implementation (v2 format, zstd per-file).

Structure (v2, all little-endian):
  [0-3]    Magic: b"WOOF"
  [4-7]    Version: uint32
  [8-15]   Header flags: uint64
  [16-23]  Payload size: uint64
  [24-31]  Total raw size: uint64
  [32+]    Payload — flat file table (flags, name, data)"""

from __future__ import annotations

import os
import struct
from typing import Dict, List

import zstandard as _zstd

WOOF_MAGIC = b"WOOF"
WOOF_VERSION_V2 = 2

FLAG_ENTRY_ZSTD = 2

HEADER_SIZE = 32


# ── Iterator helpers ────────────────────────────────────────────


def _iter_dict(entries: Dict[str, bytes]):
    """Yield sorted (name, content) pairs from a dict."""
    for name in sorted(entries.keys()):
        yield name, entries[name]


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


def _unpack_v2(data: bytes) -> Dict[str, bytes]:
    """Parse a v2 .woof archive into named entries."""
    if len(data) < HEADER_SIZE:
        raise ValueError("Truncated .woof file")
    if data[0:4] != WOOF_MAGIC:
        raise ValueError(f"Not a .woof file")
    version = struct.unpack("<I", data[4:8])[0]
    if version != WOOF_VERSION_V2:
        raise ValueError(f"Unsupported version: {version}")

    _hdr_flags, xor_size, _total_raw = struct.unpack("<QQQ", data[8:32])
    payload = data[HEADER_SIZE : HEADER_SIZE + xor_size]

    entries: Dict[str, bytes] = {}
    fp = 0
    ftable_len = len(payload)
    dctx = _zstd.ZstdDecompressor()
    while fp < ftable_len:
        flags, name_len = struct.unpack("<II", payload[fp : fp + 8])
        fp += 8
        name = payload[fp : fp + name_len].decode("utf-8")
        fp += name_len

        if flags & FLAG_ENTRY_ZSTD:
            data_len = struct.unpack("<Q", payload[fp : fp + 8])[0]
            fp += 8
            content = dctx.decompress(payload[fp : fp + data_len])
            fp += data_len
        else:
            data_len = struct.unpack("<Q", payload[fp : fp + 8])[0]
            fp += 8
            content = bytes(payload[fp : fp + data_len])
            fp += data_len

        entries[name] = content
    return entries


# ── Public API ──────────────────────────────────────────────────


def pack_woof(entries: Dict[str, bytes], compress: bool = True, **kwargs) -> bytes:
    """Pack dict entries into a v2 .woof byte stream."""
    return _pack_v2(_iter_dict(entries), compress)


def pack_woof_to_file(
    output_path: str,
    entries,
    compress: bool = True,
    level: int = 3,
    progress_cb=None,
) -> None:
    """Stream .woof archive directly to a file.

    *entries* is an iterable of (name, content) pairs.
    *level* is zstd compression level (1-22, default 3).
    *progress_cb* receives (current, total) tuples for progress reporting.
    Writes sequentially without buffering the full archive in memory.
    """
    cctx = _zstd.ZstdCompressor(level=level) if compress else None
    total_raw = 0
    payload_size = 0

    # Pre-count total items for progress
    if progress_cb:
        entry_list = list(entries)
        total = len(entry_list)
    else:
        entry_list = entries  # type: ignore
        total = 0

    with open(output_path, "wb") as f:
        # Placeholder header — patched after all entries
        f.write(b"\0" * HEADER_SIZE)

        for idx, entry in enumerate(entry_list):
            name, content = entry
            if progress_cb:
                progress_cb(idx, total)
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
    """Unpack a v2 .woof byte stream into named entries."""
    return _unpack_v2(data)


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


# ── Deprecated backward-compat stubs (kept for tests) ──────────

WOOF_VERSION_V1 = 1
FLAG_XOR = 1

_WOOF_XOR_KEY = 0xA5
_XOR_TABLE = bytes([i ^ _WOOF_XOR_KEY for i in range(256)])


def _xor(data: bytes) -> bytes:
    return data.translate(_XOR_TABLE)


def _is_compressible(arcname: str) -> bool:
    _ext = os.path.splitext(arcname)[1].lower()
    return _ext in _COMPRESSIBLE_EXTS


_COMPRESSIBLE_EXTS = frozenset(
    {
        ".qgs",
        ".qml",
        ".xml",
        ".csv",
        ".txt",
        ".json",
        ".geojson",
        ".yml",
        ".yaml",
        ".md",
        ".html",
        ".sld",
        ".prj",
        ".py",
    }
)


def pack_woof_from_directory(
    directory: str, compress: bool = True, use_v2: bool = True
) -> bytes:
    return _pack_v2(_iter_directory(directory), compress)


def _iter_directory(directory: str):
    paths: List[str] = []
    for root, _dirs, fnames in os.walk(directory):
        for fname in fnames:
            paths.append(os.path.join(root, fname))
    paths.sort()
    for full_path in paths:
        arcname = os.path.relpath(full_path, directory)
        with open(full_path, "rb") as f:
            yield arcname, f.read()
