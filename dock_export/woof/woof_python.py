"""Pure-Python .woof implementation with v2 write + v3/v4 read support.

v2 structure (all little-endian):
  [0-3]    Magic: b"WOOF"
  [4-7]    Version: uint32 (2)
  [8-15]   Header flags: uint64
  [16-23]  Payload size: uint64
  [24-31]  Total raw size: uint64
  [32+]    Payload — flat entry table (flags, name_length, name, data_length, data)

v4 structure (v3 is identical but version=3; v4 can set FLAG_DEDUP in header flags):
  [0-3]    Magic: b"WOOF"
  [4-7]    Version: uint32 (4)
  [8-15]   Header flags: uint64  (bit 0 = FLAG_DEDUP when content-addressed dedup applied)
  [16-23]  Seek offset: uint64
  [24-31]  Payload offset: uint64
  [32-39]  Payload size: uint64
  [40-47]  Total raw size: uint64
  [48+]    Seek table + payload
"""

from __future__ import annotations

import os
import struct

import zstandard as _zstd

WOOF_MAGIC = b"WOOF"
WOOF_VERSION_V2 = 2
WOOF_VERSION_V3 = 3
WOOF_VERSION_V4 = 4

FLAG_ENTRY_ZSTD = 2
FLAG_DEDUP = 1

HEADER_SIZE_V2 = 32
HEADER_SIZE_V34 = 48
HEADER_SIZE = HEADER_SIZE_V34
SEEK_ENTRY_SIZE = 44

# --- xxhash3-64 helper (optional, graceful fallback) ---

_xxhash3_64 = None
try:
    import xxhash

    _xxhash3_64 = xxhash.xxh3_64
except ImportError:
    pass


def _xxh3_64(data: bytes) -> int:
    if _xxhash3_64 is not None:
        return _xxhash3_64(data).intdigest()
    return 0


# --- Format detection ---

_SUPPORTED_VERSIONS = {WOOF_VERSION_V2, WOOF_VERSION_V3, WOOF_VERSION_V4}


def _detect_version(data: bytes) -> int | None:
    """Detect archive version from header. Returns version or None."""
    if len(data) < 8:
        return None
    if data[0:4] != WOOF_MAGIC:
        return None
    version = struct.unpack("<I", data[4:8])[0]
    return version if version in _SUPPORTED_VERSIONS else None


# --- v3/v4 seek table decoder ---


def _decode_seek_table(data: bytes, offset: int) -> list[dict]:
    """Decode seek table from v3/v4 archive. Returns list of seek entry dicts."""
    num_entries = struct.unpack("<I", data[offset : offset + 4])[0]
    table_start = offset + 4
    heap_start = table_start + num_entries * SEEK_ENTRY_SIZE

    entries = []
    name_heap_offset = 0
    for i in range(num_entries):
        pos = table_start + i * SEEK_ENTRY_SIZE
        flags = struct.unpack("<I", data[pos : pos + 4])[0]
        name_len = struct.unpack("<I", data[pos + 4 : pos + 8])[0]
        name_offset = struct.unpack("<I", data[pos + 8 : pos + 12])[0]
        data_offset = struct.unpack("<Q", data[pos + 12 : pos + 20])[0]
        data_size = struct.unpack("<Q", data[pos + 20 : pos + 28])[0]
        raw_size = struct.unpack("<Q", data[pos + 28 : pos + 36])[0]
        hash_ = struct.unpack("<Q", data[pos + 36 : pos + 44])[0]

        name_start = heap_start + name_heap_offset
        name_end = name_start + name_len
        name = data[name_start:name_end].decode("utf-8")
        name_heap_offset += name_len

        entries.append(
            {
                "flags": flags,
                "name": name,
                "name_offset": name_offset,
                "data_offset": data_offset,
                "data_size": data_size,
                "raw_size": raw_size,
                "hash": hash_,
            }
        )
    return entries


def _decode_v34_header(data: bytes) -> tuple[int, int, int, int, int]:
    """Parse v3/v4 header. Returns (hdr_flags, seek_off, payload_off, payload_sz, total_raw)."""
    hdr_flags = struct.unpack("<Q", data[8:16])[0]
    seek_off = struct.unpack("<Q", data[16:24])[0]
    payload_off = struct.unpack("<Q", data[24:32])[0]
    payload_sz = struct.unpack("<Q", data[32:40])[0]
    total_raw = struct.unpack("<Q", data[40:48])[0]
    return hdr_flags, seek_off, payload_off, payload_sz, total_raw


# --- Seek table encoder (v3/v4) ---


def _encode_seek_table(entries: list[dict]) -> bytes:
    """Encode seek table entries to binary (v3/v4 format)."""
    parts = [struct.pack("<I", len(entries))]
    name_heap = bytearray()
    name_offset = 0
    for e in entries:
        name_bytes = e["name"].encode("utf-8")
        parts.append(
            struct.pack(
                "<IIIQQQQ",
                e["flags"],
                len(name_bytes),
                name_offset,
                e["data_offset"],
                e["data_size"],
                e["raw_size"],
                e["hash"],
            )
        )
        name_heap.extend(name_bytes)
        name_offset += len(name_bytes)
    parts.append(bytes(name_heap))
    return b"".join(parts)


# --- v4 packer ---


def _pack_v4(entries, compress: bool, level: int = 3) -> bytes:
    """Build a v4 .woof byte array with seek table, xxhash3-64 checksums, and dedup."""
    cctx = _zstd.ZstdCompressor(level=level) if compress else None
    total_raw = 0

    sorted_entries = sorted(entries, key=lambda x: x[0])

    payload = bytearray()
    seek_entries: list[dict] = []
    dedup_map: dict[int, tuple[int, int]] = {}
    dedup_occurred = False

    for name, content in sorted_entries:
        raw_len = len(content)
        total_raw += raw_len
        h = _xxh3_64(content)

        if h != 0 and h in dedup_map:
            existing_offset, existing_size = dedup_map[h]
            seek_entries.append(
                {
                    "flags": 0,
                    "name": name,
                    "data_offset": existing_offset,
                    "data_size": existing_size,
                    "raw_size": raw_len,
                    "hash": h,
                }
            )
            dedup_occurred = True
            continue

        if compress:
            compressed = cctx.compress(content)
            if len(compressed) < raw_len:
                data, flags = compressed, FLAG_ENTRY_ZSTD
            else:
                data, flags = content, 0
        else:
            data, flags = content, 0

        data_offset = len(payload)
        data_size = len(data)
        if h != 0:
            dedup_map[h] = (data_offset, data_size)
        seek_entries.append(
            {
                "flags": flags,
                "name": name,
                "data_offset": data_offset,
                "data_size": data_size,
                "raw_size": raw_len,
                "hash": h,
            }
        )
        payload.extend(data)

    seek_table_bytes = _encode_seek_table(seek_entries)
    payload_size = len(payload)
    header_flags = FLAG_DEDUP if dedup_occurred else 0

    header = struct.pack(
        "<4sIQQQQQ",
        WOOF_MAGIC,
        WOOF_VERSION_V4,
        header_flags,
        HEADER_SIZE_V34,
        HEADER_SIZE_V34 + len(seek_table_bytes),
        payload_size,
        total_raw,
    )
    return bytes(header + seek_table_bytes + bytes(payload))


# --- v3/v4 extraction helpers ---


def _extract_entry(data: bytes, seek_entry: dict, payload_slice: bytes) -> bytes:
    """Extract and decompress a single entry from a v3/v4 archive."""
    start = seek_entry["data_offset"]
    end = start + seek_entry["data_size"]
    raw = payload_slice[start:end]

    if seek_entry["flags"] & FLAG_ENTRY_ZSTD:
        dctx = _zstd.ZstdDecompressor()
        decompressed = dctx.decompress(raw, max_output_size=seek_entry["raw_size"])
    else:
        decompressed = bytes(raw)

    # Verify xxhash3-64 if available
    if _xxhash3_64 is not None:
        computed = _xxh3_64(decompressed)
        if computed != seek_entry["hash"]:
            msg = f"Checksum mismatch for '{seek_entry['name']}'"
            raise ValueError(msg)

    return decompressed


# --- v2 helpers (unchanged) ---


def _iter_dict(entries: dict[str, bytes]):
    for name in sorted(entries.keys()):
        yield name, entries[name]


def _pack_v2(entries, compress: bool, level: int = 3) -> bytes:
    """Build a v2 .woof byte array with per-file zstd compression."""
    parts: list[bytes] = []
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


def _unpack_v2(data: bytes) -> dict[str, bytes]:
    """Parse a v2 .woof archive into a dict of {name: content}."""
    _hdr_flags, xor_size, _total_raw = struct.unpack("<QQQ", data[8:32])
    payload = data[HEADER_SIZE_V2 : HEADER_SIZE_V2 + xor_size]

    entries: dict[str, bytes] = {}
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


def _unpack_v34(data: bytes) -> dict[str, bytes]:
    """Parse a v3/v4 .woof archive into a dict of {name: content}."""
    _hdr_flags, _seek_off, payload_off, payload_sz, _total_raw = _decode_v34_header(data)
    seek_entries = _decode_seek_table(data, _seek_off)
    payload = data[payload_off : payload_off + payload_sz]

    entries: dict[str, bytes] = {}
    for se in seek_entries:
        entries[se["name"]] = _extract_entry(data, se, payload)
    return entries


# --- Public API (matches Rust native module interface) ---


def pack_woof(entries: dict[str, bytes], compress: bool = True, level: int = 3, **_kwargs) -> bytes:
    """Pack dict entries into a .woof byte stream (v4 format)."""
    return _pack_v4(_iter_dict(entries), compress, level)


def pack_woof_to_file(
    output_path: str,
    entries,
    compress: bool = True,
    level: int = 3,
    progress_cb=None,
) -> None:
    """Build a v4 .woof archive from entries and write to *output_path*."""
    if progress_cb:
        entry_list = list(entries)
        total = len(entry_list)
    else:
        entry_list = entries
        total = 0

    # Consume all entries into memory for v4 packing (matching Rust path)
    entry_dict: dict[str, bytes] = {}
    for idx, entry in enumerate(entry_list):
        name, content = entry
        entry_dict[name] = content
        if progress_cb and total > 0:
            progress_cb(idx, total)

    data = _pack_v4(_iter_dict(entry_dict), compress, level)
    with open(output_path, "wb") as f:
        f.write(data)


def unpack_woof(data: bytes) -> dict[str, bytes]:
    """Unpack a .woof byte stream into named entries (handles v2, v3, v4)."""
    version = _detect_version(data)
    if version is None:
        msg = "Not a .woof file or unsupported version"
        raise ValueError(msg)
    if version == WOOF_VERSION_V2:
        return _unpack_v2(data)
    return _unpack_v34(data)


def extract_woof_to_directory(data: bytes, target_dir: str) -> None:
    """Extract a .woof archive into *target_dir*, recreating directory structure."""
    entries = unpack_woof(data)
    os.makedirs(target_dir, exist_ok=True)
    for arcname, content in entries.items():
        dst = os.path.join(target_dir, arcname)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(dst, "wb") as f:
            f.write(content)


def woof_magic_bytes() -> bytes:
    return WOOF_MAGIC


# --- Proxy functions matching native module names ---


def pack_woof_py(entries: dict, compress: bool, level: int = 3) -> bytes:
    """Pack *entries* into a .woof archive (Python fallback, v4 format)."""
    return _pack_v4(_iter_dict(entries), compress, level)


def unpack_woof_py(data: bytes) -> dict:
    """Unpack a .woof archive (Python fallback, handles v2, v3, v4)."""
    return unpack_woof(data)


def list_entries_py(data: bytes) -> list:
    """Return the list of entry metadata in a .woof archive (handles v2, v3, v4).

    Returns list of (name, flags, data_size, raw_size, hash) tuples.
    """
    version = _detect_version(data)
    if version is None:
        return []
    if version == WOOF_VERSION_V2:
        return _list_entries_v2(data)
    return _list_entries_v34(data)


def _list_entries_v2(data: bytes) -> list:
    _hdr_flags, xor_size, _total_raw = struct.unpack("<QQQ", data[8:32])
    payload = data[HEADER_SIZE_V2 : HEADER_SIZE_V2 + xor_size]
    entries: list = []
    fp = 0
    ftable_len = len(payload)
    while fp < ftable_len:
        flags, name_len = struct.unpack("<II", payload[fp : fp + 8])
        fp += 8
        name = payload[fp : fp + name_len].decode("utf-8")
        fp += name_len
        if flags & FLAG_ENTRY_ZSTD:
            data_len = struct.unpack("<Q", payload[fp : fp + 8])[0]
        else:
            data_len = struct.unpack("<Q", payload[fp : fp + 8])[0]
        fp += 8 + data_len
        entries.append((name, flags, data_len, data_len, 0))
    return entries


def _list_entries_v34(data: bytes) -> list:
    _hdr_flags, _seek_off, payload_off, payload_sz, _total_raw = _decode_v34_header(data)
    seek_entries = _decode_seek_table(data, _seek_off)
    return [
        (se["name"], se["flags"], se["data_size"], se["raw_size"], se["hash"])
        for se in seek_entries
    ]


def unpack_one_py(data: bytes, name: str) -> bytes:
    """Extract a single entry *name* from a .woof archive (handles v2, v3, v4)."""
    version = _detect_version(data)
    if version is None:
        msg = "Not a .woof file or unsupported version"
        raise ValueError(msg)
    if version == WOOF_VERSION_V2:
        return _unpack_one_v2(data, name)
    return _unpack_one_v34(data, name)


def _unpack_one_v2(data: bytes, name: str) -> bytes:
    _hdr_flags, xor_size, _total_raw = struct.unpack("<QQQ", data[8:32])
    payload = data[HEADER_SIZE_V2 : HEADER_SIZE_V2 + xor_size]
    dctx = _zstd.ZstdDecompressor()
    fp = 0
    ftable_len = len(payload)
    while fp < ftable_len:
        flags, name_len = struct.unpack("<II", payload[fp : fp + 8])
        fp += 8
        entry_name = payload[fp : fp + name_len].decode("utf-8")
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
        if entry_name == name:
            return content
    raise KeyError(f"Entry '{name}' not found")


def _unpack_one_v34(data: bytes, name: str) -> bytes:
    _hdr_flags, _seek_off, payload_off, payload_sz, _total_raw = _decode_v34_header(data)
    seek_entries = _decode_seek_table(data, _seek_off)
    payload = data[payload_off : payload_off + payload_sz]

    # Binary search (entries are sorted by name)
    lo, hi = 0, len(seek_entries)
    while lo < hi:
        mid = (lo + hi) // 2
        mid_name = seek_entries[mid]["name"]
        if mid_name < name:
            lo = mid + 1
        elif mid_name > name:
            hi = mid
        else:
            return _extract_entry(data, seek_entries[mid], payload)
    raise KeyError(f"Entry '{name}' not found")


# --- Deprecated backward-compat stubs (kept for tests) ---

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
    directory: str,
    compress: bool = True,
    level: int = 3,
) -> bytes:
    return _pack_v4(_iter_directory(directory), compress, level)


def _iter_directory(directory: str):
    paths: list[str] = []
    for root, _dirs, fnames in os.walk(directory):
        for fname in fnames:
            paths.append(os.path.join(root, fname))
    paths.sort()
    for full_path in paths:
        arcname = os.path.relpath(full_path, directory)
        with open(full_path, "rb") as f:
            yield arcname, f.read()
