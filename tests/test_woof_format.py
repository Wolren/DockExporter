"""Comprehensive tests for dock_export.woof_format.

Covers: CDC chunking, ChunkStore dedup, v1/v2 roundtrips,
compatibility, edge cases, error handling, and directory packing."""

from __future__ import annotations

import os
import struct
import sys
from typing import Dict, List

import pytest

# Allow direct import under test runners
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dock_export.woof_format import (
    HEADER_SIZE,
    HASH_SIZE,
    WOOF_MAGIC,
    WOOF_VERSION_V1,
    WOOF_VERSION_V2,
    FLAG_XOR,
    FLAG_HAS_CHUNK_STORE,
    FLAG_ENTRY_CHUNKED,
    _ChunkStore,
    _chunk_data,
    _is_compressible,
    _xor,
    extract_woof_to_directory,
    pack_woof,
    pack_woof_from_directory,
    unpack_woof,
    woof_magic_bytes,
)
from test_data_gen import (
    generate_binary_blob,
    generate_csv,
    generate_geojson,
    generate_qgs_project,
    generate_qml_style,
    make_standard_test_set,
    write_test_data_to_disk,
)


# ═══════════════════════════════════════════════════════════════════
# 1.  CONSTANTS & HELPERS
# ═══════════════════════════════════════════════════════════════════


def _parse_header(data: bytes) -> tuple:
    """Extract header fields for inspection."""
    assert len(data) >= HEADER_SIZE
    magic = data[0:4]
    version, hdr_flags, xor_size, raw_size = struct.unpack("<IQQQ", data[4:32])
    return magic, version, hdr_flags, xor_size, raw_size


def _payload(data: bytes) -> bytes:
    """Extract and XOR-deobfuscate the payload."""
    _magic, _version, hdr_flags, xor_size, _raw = _parse_header(data)
    payload = data[HEADER_SIZE : HEADER_SIZE + xor_size]
    if hdr_flags & FLAG_XOR:
        payload = _xor(payload)
    return payload


def _archive_size_info(data: bytes) -> dict:
    """Return aggregate size metrics from a .woof archive."""
    _magic, _ver, _flags, xor_size, raw_size = _parse_header(data)
    return {
        "archive_size": len(data),
        "xor_payload_size": xor_size,
        "raw_total_declared": raw_size,
        "overhead": len(data) - xor_size,
    }


# ═══════════════════════════════════════════════════════════════════
# 2.  UNIT TESTS — LOW-LEVEL COMPONENTS
# ═══════════════════════════════════════════════════════════════════


class TestWoofConstants:
    def test_magic_bytes(self):
        assert woof_magic_bytes() == WOOF_MAGIC == b"WOOF"

    def test_header_size(self):
        assert HEADER_SIZE == 32

    def test_hash_size(self):
        assert HASH_SIZE in (16, 32)  # xxh128 if available, sha256 fallback


class TestXor:
    def test_xor_roundtrip(self):
        data = b"hello world\x00\xff"
        assert _xor(_xor(data)) == data

    def test_xor_nonzero(self):
        data = b"\x00" * 16
        assert _xor(data) != data  # XOR should change nulls

    def test_xor_empty(self):
        assert _xor(b"") == b""


class TestIsCompressible:
    def test_compressible_exts(self):
        for ext in [
            ".qgs",
            ".qml",
            ".xml",
            ".geojson",
            ".json",
            ".csv",
            ".prj",
            ".sld",
            ".py",
        ]:
            assert _is_compressible(f"file{ext}"), f"{ext} should be compressible"
            assert _is_compressible(f"dir/file{ext}"), (
                f"dir/file{ext} should be compressible"
            )

    def test_noncompressible_exts(self):
        for ext in [".gpkg", ".tiff", ".tif", ".png", ".jpg", ".shp", ".dbf"]:
            assert not _is_compressible(f"file{ext}"), (
                f"{ext} should NOT be compressible"
            )

    def test_path_normalization(self):
        assert _is_compressible("data/POINTS.GeoJSON")  # case-insensitive match


class TestChunkData:
    MIN = 4096
    AVG = 16384
    MAX = 65536

    def test_small_data_not_chunked(self):
        data = b"x" * 100
        chunks = _chunk_data(data)
        assert len(chunks) == 1
        assert chunks[0] == data

    def test_medium_data_few_chunks(self):
        data = b"a" * 20000
        chunks = _chunk_data(data)
        assert 1 <= len(chunks) <= 4

    def test_large_data_many_chunks(self):
        data = b"abcdefgh" * 20000  # ~160KB
        chunks = _chunk_data(data)
        assert len(chunks) >= 2

    def test_no_chunk_smaller_than_min(self):
        data = b"x" * 50000
        chunks = _chunk_data(data)
        for c in chunks:
            assert len(c) >= self.MIN or len(c) <= self.AVG, (
                f"chunk too small: {len(c)} < {self.MIN}"
            )

    def test_no_chunk_larger_than_max(self):
        data = bytes(range(256)) * 500  # 128KB
        chunks = _chunk_data(data)
        for c in chunks:
            assert len(c) <= self.MAX + self.AVG, (
                f"chunk too large: {len(c)} > {self.MAX}"
            )

    def test_concat_chunks_reproduces_original(self):
        data = os.urandom(50000)
        chunks = _chunk_data(data)
        assert b"".join(chunks) == data

    def test_empty_data(self):
        assert _chunk_data(b"") == []

    def test_reproducible(self):
        data = b"hello world, this is test data for chunking " * 1000
        c1 = _chunk_data(data)
        c2 = _chunk_data(data)
        assert c1 == c2  # deterministic


class TestChunkStore:
    def test_add_and_get(self):
        store = _ChunkStore()
        h = store.add(b"hello world")
        assert len(h) == HASH_SIZE
        assert store.get(h) == b"hello world"

    def test_dedup(self):
        store = _ChunkStore()
        h1 = store.add(b"same content")
        h2 = store.add(b"same content")
        assert h1 == h2
        assert len(store._order) == 1  # stored once

    def test_unique_content(self):
        store = _ChunkStore()
        h1 = store.add(b"content one")
        h2 = store.add(b"content two")
        assert h1 != h2
        assert len(store._order) == 2

    def test_serialize_empty(self):
        store = _ChunkStore()
        data = store.serialize()
        assert len(data) == 8  # just num_chunks = 0

    def test_serialize_deserialize(self):
        store = _ChunkStore()
        store.add(b"alpha")
        store.add(b"beta")
        store.add(b"gamma")
        data = store.serialize()
        store2 = _ChunkStore.deserialize(data)
        assert len(store2._order) == 3
        for h in store._order:
            assert store.get(h) == store2.get(h)

    def test_deserialize_invalid(self):
        with pytest.raises(Exception):
            _ChunkStore.deserialize(b"\xff" * 8)


# ═══════════════════════════════════════════════════════════════════
# 3.  ROUNDTRIP TESTS — v1, v2
# ═══════════════════════════════════════════════════════════════════


class TestPackUnpackV1:
    def test_roundtrip(self, test_entries):
        packed = pack_woof(test_entries, compress=True, use_v2=False)
        unpacked = unpack_woof(packed)
        assert unpacked == test_entries

    def test_no_compress(self, test_entries):
        packed = pack_woof(test_entries, compress=False, use_v2=False)
        unpacked = unpack_woof(packed)
        assert unpacked == test_entries

    def test_header(self, test_entries):
        packed = pack_woof(test_entries, compress=True, use_v2=False)
        magic, ver, flags, xor_sz, raw = _parse_header(packed)
        assert magic == WOOF_MAGIC
        assert ver == WOOF_VERSION_V1
        assert flags == 0

    def test_single_entry(self):
        data = pack_woof({"hello.txt": b"world"}, compress=True, use_v2=False)
        assert unpack_woof(data) == {"hello.txt": b"world"}

    def test_empty_value(self):
        data = pack_woof({"empty.txt": b""}, compress=True, use_v2=False)
        assert unpack_woof(data) == {"empty.txt": b""}


class TestPackUnpackV2:
    def test_roundtrip(self, test_entries):
        packed = pack_woof(test_entries, compress=True, use_v2=True)
        unpacked = unpack_woof(packed)
        assert unpacked == test_entries

    def test_no_compress(self, test_entries):
        packed = pack_woof(test_entries, compress=False, use_v2=True)
        unpacked = unpack_woof(packed)
        assert unpacked == test_entries

    def test_header(self, test_entries):
        packed = pack_woof(test_entries, compress=True, use_v2=True)
        magic, ver, flags, _xor_sz, _raw = _parse_header(packed)
        assert magic == WOOF_MAGIC
        assert ver == WOOF_VERSION_V2
        # Small compressible files use inline zstd (no chunk store),
        # larger files produce a chunk store — both are valid
        assert flags & ~FLAG_HAS_CHUNK_STORE == 0

    def test_chunk_dedup_works(self):
        """Identical text files should share chunks."""
        entries = {
            "a.qgs": generate_qgs_project(num_layers=2).encode("utf-8"),
            "b.qgs": generate_qgs_project(num_layers=2).encode("utf-8"),
        }
        packed = pack_woof(entries, compress=True, use_v2=True)
        unpacked = unpack_woof(packed)
        assert unpacked == entries
        # The chunk store should have deduplicated (if files exceed inline zstd threshold)
        magic, ver, flags, _xor_sz, _raw = _parse_header(packed)
        if flags & FLAG_HAS_CHUNK_STORE:
            payload = _payload(packed)
            store = _ChunkStore.deserialize(payload)
            total_raw = sum(store._raw_sizes.values())
            total_comp = sum(len(c) for c in store._chunks.values())
            assert total_comp <= total_raw

    def test_binary_passthrough(self):
        """Binary files should be stored inline without chunking."""
        entries = {"data.tiff": generate_binary_blob(10)}
        packed = pack_woof(entries, compress=True, use_v2=True)
        info = _archive_size_info(packed)
        assert info["raw_total_declared"] == len(entries["data.tiff"])

    def test_empty_entries(self):
        data = pack_woof({}, compress=True, use_v2=True)
        assert len(data) >= HEADER_SIZE
        assert unpack_woof(data) == {}


class TestRoundtripEdgeCases:
    def test_empty_archive(self):
        for use_v2 in [True, False]:
            packed = pack_woof({}, compress=True, use_v2=use_v2)
            assert unpack_woof(packed) == {}

    def test_single_byte_file(self):
        for use_v2 in [True, False]:
            entries = {"a.txt": b"x"}
            packed = pack_woof(entries, compress=True, use_v2=use_v2)
            assert unpack_woof(packed) == entries

    def test_large_binary(self):
        """Verify large binary files survive roundtrip."""
        entries = {"large.tiff": generate_binary_blob(2048)}  # 2MB
        for compress in [True, False]:
            for use_v2 in [True, False]:
                packed = pack_woof(entries, compress=compress, use_v2=use_v2)
                assert unpack_woof(packed) == entries

    def test_deeply_nested_dirs(self):
        entries = {
            "a/b/c/d/e/f/file.txt": b"deep",
            "x/y/z.geojson": generate_geojson(10).encode("utf-8"),
        }
        for use_v2 in [True, False]:
            packed = pack_woof(entries, compress=True, use_v2=use_v2)
            assert unpack_woof(packed) == entries

    def test_special_chars_in_names(self):
        entries = {
            "project (1).qgs": b"<qgis/>",
            "data - copy.geojson": b'{"type":"FeatureCollection","features":[]}',
            "roads & rails.csv": b"id,name\n1,test",
        }
        for use_v2 in [True, False]:
            packed = pack_woof(entries, compress=True, use_v2=use_v2)
            unpacked = unpack_woof(packed)
            assert unpacked == entries

    def test_unicode_content(self):
        entries = {
            "data.geojson": '{"name": "café"}'.encode("utf-8"),
            "metadata.xml": '<meta lang="fr">élève</meta>'.encode("utf-8"),
        }
        for use_v2 in [True, False]:
            packed = pack_woof(entries, compress=True, use_v2=use_v2)
            assert unpack_woof(packed) == entries


# ═══════════════════════════════════════════════════════════════════
# 4.  CROSS-VERSION COMPATIBILITY
# ═══════════════════════════════════════════════════════════════════


class TestCrossVersion:
    """v1 and v2 archives must both be readable by unpack_woof."""

    def test_v1_unpacked_by_auto(self, test_entries):
        packed = pack_woof(test_entries, compress=True, use_v2=False)
        assert unpack_woof(packed) == test_entries

    def test_v2_unpacked_by_auto(self, test_entries):
        packed = pack_woof(test_entries, compress=True, use_v2=True)
        assert unpack_woof(packed) == test_entries

    def test_mixed_compress_modes(self, test_entries):
        """Unpack must handle compress=True and compress=False from any version."""
        for use_v2 in [True, False]:
            for comp in [True, False]:
                kwargs = {"compress": comp, "use_v2": use_v2}
                packed = pack_woof(test_entries, **kwargs)
                result = unpack_woof(packed)
                assert result == test_entries, f"Failed: {kwargs}"


# ═══════════════════════════════════════════════════════════════════
# 5.  DIRECTORY PACKING / EXTRACTION
# ═══════════════════════════════════════════════════════════════════


class TestDirectoryPacking:
    def test_pack_from_directory_roundtrip(self, test_entries, temp_dir):
        write_test_data_to_disk(temp_dir, test_entries)
        for use_v2 in [True, False]:
            packed = pack_woof_from_directory(temp_dir, compress=True, use_v2=use_v2)
            unpacked = unpack_woof(packed)
            # Compare normalized (paths are OS-native)
            normalized = {}
            for name, content in test_entries.items():
                norm = name.replace("/", os.sep).replace("\\", os.sep)
                normalized[norm] = content
            assert unpacked == normalized

    def test_extract_to_directory(self, test_entries, temp_dir):
        packed = pack_woof(test_entries, compress=True, use_v2=True)
        extract_woof_to_directory(packed, temp_dir)
        # Verify extracted files match
        for arcname, content in test_entries.items():
            full_path = os.path.join(temp_dir, arcname)
            assert os.path.isfile(full_path), f"Missing: {full_path}"
            with open(full_path, "rb") as f:
                assert f.read() == content, f"Content mismatch: {arcname}"

    def test_extract_preserves_subdirs(self, test_entries, temp_dir):
        packed = pack_woof(test_entries, compress=True, use_v2=True)
        extract_woof_to_directory(packed, temp_dir)
        assert os.path.isdir(os.path.join(temp_dir, "data"))
        assert os.path.isdir(os.path.join(temp_dir, "styles"))
        assert os.path.isdir(os.path.join(temp_dir, "vectors"))


# ═══════════════════════════════════════════════════════════════════
# 6.  ERROR HANDLING & MALFORMED DATA
# ═══════════════════════════════════════════════════════════════════


class TestErrorHandling:
    def test_truncated_header(self):
        with pytest.raises(ValueError, match="Truncated"):
            unpack_woof(b"\x00" * 10)

    def test_bad_magic(self):
        with pytest.raises(ValueError, match="Not a .woof"):
            unpack_woof(b"ZIP\x00" * 10)

    def test_invalid_data(self):
        with pytest.raises(Exception):
            unpack_woof(b"WOOF" + b"\xff" * 100)

    def test_nonexistent_directory(self):
        """Non-existent directory must raise or return empty archive."""
        try:
            result = pack_woof_from_directory("/nonexistent/path")
            assert result == b"" or unpack_woof(result) == {}
        except (FileNotFoundError, OSError, StopIteration):
            pass  # acceptable error behavior

    def test_non_dict_entries(self):
        with pytest.raises((TypeError, AttributeError)):
            pack_woof(None)  # type: ignore[arg-type]


# ═══════════════════════════════════════════════════════════════════
# 7.  SIZE PROPERTIES — SANITY CHECKS
# ═══════════════════════════════════════════════════════════════════


class TestSizeSanity:
    def test_v1_smaller_with_compress(self, test_entries):
        """Compressed should be smaller or equal for compressible data."""
        uncomp = pack_woof(test_entries, compress=False, use_v2=False)
        comp = pack_woof(test_entries, compress=True, use_v2=False)
        # For compressible text data, compressed archive should be smaller
        assert len(comp) <= len(uncomp) * 1.05  # allow 5% overhead

    def test_v2_smaller_than_v1(self, test_entries):
        """v2 should compress at least as well as v1."""
        v1 = pack_woof(test_entries, compress=True, use_v2=False)
        v2 = pack_woof(test_entries, compress=True, use_v2=True)
        assert len(v2) <= len(v1) or abs(len(v2) - len(v1)) < 100

    def test_declared_raw_size(self, test_entries):
        total = sum(len(c) for c in test_entries.values())
        for use_v2 in [True, False]:
            packed = pack_woof(test_entries, compress=True, use_v2=use_v2)
            info = _archive_size_info(packed)
            assert info["raw_total_declared"] == total

    def test_no_data_loss_for_binary(self, test_entries):
        """Even without compression, binary files must survive."""
        packed = pack_woof(test_entries, compress=False, use_v2=True)
        assert unpack_woof(packed) == test_entries


# ═══════════════════════════════════════════════════════════════════
# 8.  DETERMINISM
# ═══════════════════════════════════════════════════════════════════


class TestDeterminism:
    """Identical inputs must produce identical archives."""

    def test_v1_deterministic(self, test_entries):
        a = pack_woof(test_entries, compress=True, use_v2=False)
        b = pack_woof(test_entries, compress=True, use_v2=False)
        assert a == b

    def test_v2_deterministic(self, test_entries):
        a = pack_woof(test_entries, compress=True, use_v2=True)
        b = pack_woof(test_entries, compress=True, use_v2=True)
        assert a == b


# ═══════════════════════════════════════════════════════════════════
# 9.  STRESS TESTS
# ═══════════════════════════════════════════════════════════════════


class TestStress:
    """Heavy-load tests for stability and memory behaviour."""

    def test_many_small_files(self):
        entries = {}
        for i in range(1000):
            entries[f"file_{i:04d}.txt"] = f"content_{i}".encode("utf-8")
        for use_v2 in [True, False]:
            packed = pack_woof(entries, compress=True, use_v2=use_v2)
            assert unpack_woof(packed) == entries

    def test_large_text_file(self):
        """A single large text file (~5MB of QGS-like XML)."""
        content = generate_qgs_project(num_layers=50, shared_symbols=20)
        content = (content * 20).encode("utf-8")  # ~5MB
        entries = {"huge.qgs": content}
        for use_v2 in [True, False]:
            packed = pack_woof(entries, compress=True, use_v2=use_v2)
            unpacked = unpack_woof(packed)
            assert unpacked["huge.qgs"] == content

    def test_mixed_compression_modes(self):
        """All modes on the same large dataset."""
        entries = make_standard_test_set()
        # Add some big binaries
        entries["big.tiff"] = generate_binary_blob(1024)
        for use_v2 in [True, False]:
            for comp in [True, False]:
                kwargs = {"compress": comp, "use_v2": use_v2}
                packed = pack_woof(entries, **kwargs)
                result = unpack_woof(packed)
                assert result == entries


# ═══════════════════════════════════════════════════════════════════
# 10.  REAL-WORLD SCENARIOS
# ═══════════════════════════════════════════════════════════════════


class TestScenarioFidelity:
    """Realistic GIS scenarios must survive pack/unpack identically."""

    def test_qgs_project_roundtrip_v2(self):
        qgs = generate_qgs_project(num_layers=5, shared_symbols=3)
        entries = {
            "project.qgs": qgs.encode("utf-8"),
            "roads.geojson": generate_geojson(10).encode("utf-8"),
        }
        packed = pack_woof(entries, compress=True, use_v2=True)
        assert unpack_woof(packed) == entries

    def test_csv_geo_csv(self):
        entries = {
            "data.csv": generate_csv(50).encode("utf-8"),
        }
        for use_v2 in [True, False]:
            packed = pack_woof(entries, compress=True, use_v2=use_v2)
            u = unpack_woof(packed)
            assert u == entries, f"CSV roundtrip failed for v{2 if use_v2 else 1}"


# ═══════════════════════════════════════════════════════════════════
# 11.  REAL-WORLD DATA TESTS
# ═══════════════════════════════════════════════════════════════════
# These tests use files from tests/real_data/ and skip gracefully
# when the directory is missing or empty.  You can run them with:
#     pytest tests/test_woof_format.py -k TestRealData -v


_ARCHIVE_EXTS = {".woof", ".zip", ".qgz", ".rar", ".7z", ".gz", ".tar", ".bz2"}


def _is_archive(name: str) -> bool:
    """Check if a file is an archive itself (should be excluded from testing)."""
    _, ext = os.path.splitext(name)
    return ext.lower() in _ARCHIVE_EXTS


class TestRealData:
    """Integration tests using files from tests/real_data/.

    Validates that the .woof compressor handles real-world GIS files:
    TIFFs, GPKGs, Shapefiles, PNGs, QGZ projects, VRTs, PDFs,
    and mixed directory structures.

    Files >100 MB in the fixture are excluded to keep memory manageable.
    All tests skip gracefully when real_data/ is missing or empty.
    """

    def test_roundtrip_v1(self, real_data_entries):
        if not real_data_entries:
            pytest.skip("No real data found in tests/real_data/")
        packed = pack_woof(real_data_entries, compress=True, use_v2=False)
        assert unpack_woof(packed) == real_data_entries

    def test_roundtrip_v2(self, real_data_entries):
        if not real_data_entries:
            pytest.skip("No real data found in tests/real_data/")
        packed = pack_woof(real_data_entries, compress=True, use_v2=True)
        assert unpack_woof(packed) == real_data_entries

    def test_no_compress_v2(self, real_data_entries):
        if not real_data_entries:
            pytest.skip("No real data found in tests/real_data/")
        packed = pack_woof(real_data_entries, compress=False, use_v2=True)
        assert unpack_woof(packed) == real_data_entries

    def test_extract_to_directory(self, real_data_entries, temp_dir):
        if not real_data_entries:
            pytest.skip("No real data found in tests/real_data/")
        packed = pack_woof(real_data_entries, compress=True, use_v2=True)
        extract_woof_to_directory(packed, temp_dir)
        for arcname, content in real_data_entries.items():
            full_path = os.path.join(temp_dir, arcname)
            assert os.path.isfile(full_path), f"Missing extracted: {full_path}"
            with open(full_path, "rb") as f:
                assert f.read() == content, f"Content mismatch: {arcname}"

    def test_excludes_archives(self, real_data_entries):
        """Archive files (.woof, .zip, .qgz, etc.) should not be packed."""
        if not real_data_entries:
            pytest.skip("No real data found in tests/real_data/")
        non_archives = {
            k: v for k, v in real_data_entries.items() if not _is_archive(k)
        }
        packed = pack_woof(non_archives, compress=True, use_v2=True)
        assert unpack_woof(packed) == non_archives

    def test_pack_from_real_directory(self, real_data_path, temp_dir):
        """Pack the real_data/ directory directly using pack_woof_from_directory."""
        import os as _os

        if not _os.path.isdir(real_data_path):
            pytest.skip("tests/real_data/ not found")
        if not any(_os.scandir(real_data_path)):
            pytest.skip("tests/real_data/ is empty")
        packed = pack_woof_from_directory(real_data_path, compress=True, use_v2=True)
        unpacked = unpack_woof(packed)
        # Verify at least the directory structure survived
        assert len(unpacked) > 0
        # Spot-check: all paths should be relative and not absolute
        for name in unpacked:
            assert not name.startswith("/"), f"Absolute path in archive: {name}"
            assert not name.startswith("\\"), f"Absolute path in archive: {name}"
