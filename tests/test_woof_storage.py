"""Tests for woof archive storage operations.

Covers: directory path derivation, manifest I/O, URI helpers,
manifest building, and URI rewriting logic.

The conftest.py provides QGIS mocks, so we don't need to mock
``qgis.core`` locally.
"""

from __future__ import annotations

from unittest.mock import patch

from dock_export.woof.manifest import (
    WOOF_URI_PREFIX,
    Manifest,
    ManifestEntry,
    _fast_hash,
    build_manifest,
    from_woof_uri,
    to_woof_uri,
)
from dock_export.woof.woof_storage import _extract_dir_for, _read_manifest

# ═══════════════════════════════════════════════════════════════════
# 1.  HELPER: _extract_dir_for
# ═══════════════════════════════════════════════════════════════════


class TestExtractDirFor:
    def test_appends_files_suffix(self):
        assert _extract_dir_for("/tmp/project.woof") == "/tmp/project_files"

    def test_with_absolute_path(self):
        result = _extract_dir_for(r"C:\data\export.woof")
        assert result == r"C:\data\export_files"

    def test_dot_in_name_before_extension(self):
        result = _extract_dir_for("/tmp/my.project.v2.woof")
        assert result == "/tmp/my.project.v2_files"


# ═══════════════════════════════════════════════════════════════════
# 2.  URI HELPERS: to_woof_uri / from_woof_uri
# ═══════════════════════════════════════════════════════════════════


class TestWoofUri:
    def test_to_woof_uri(self):
        assert to_woof_uri("project.qgs") == "woof://project.qgs"

    def test_from_woof_uri_valid(self):
        assert from_woof_uri("woof://project.qgs") == "project.qgs"

    def test_from_woof_uri_invalid(self):
        assert from_woof_uri("http://project.qgs") is None

    def test_roundtrip(self):
        arcname = "vectors/roads.shp"
        assert from_woof_uri(to_woof_uri(arcname)) == arcname

    def test_empty_string(self):
        assert to_woof_uri("") == WOOF_URI_PREFIX


# ═══════════════════════════════════════════════════════════════════
# 3.  MANIFEST SERIALISATION
# ═══════════════════════════════════════════════════════════════════


class TestManifestSerialisation:
    def test_to_json_roundtrip(self):
        manifest = Manifest(
            woof_version=4,
            created="2026-07-29T12:00:00+00:00",
            plugin_version="1.0.0",
            entries={
                "project.qgs": ManifestEntry(type="project", size=100, hash="abc123"),
            },
            dependencies={},
            uri_rewrites={"woof://project.qgs": "/data/project.qgs"},
        )
        raw = manifest.to_json()
        restored = Manifest.from_json(raw)
        assert restored.woof_version == 4
        assert restored.plugin_version == "1.0.0"
        assert "project.qgs" in restored.entries
        assert restored.entries["project.qgs"].type == "project"
        assert restored.uri_rewrites["woof://project.qgs"] == "/data/project.qgs"

    def test_empty_manifest(self):
        m = Manifest.empty()
        assert m.woof_version == 4
        assert m.entries == {}
        assert m.dependencies == {}
        assert m.uri_rewrites == {}

    def test_empty_roundtrip(self):
        m = Manifest.empty()
        assert Manifest.from_json(m.to_json()) == m


class TestManifestEntry:
    def test_entry_fields(self):
        entry = ManifestEntry(type="vector", size=2048, hash="deadbeef")
        assert entry.type == "vector"
        assert entry.size == 2048
        assert entry.hash == "deadbeef"

    def test_entry_to_dict(self):
        import dataclasses

        entry = ManifestEntry(type="raster", size=0, hash="")
        d = dataclasses.asdict(entry)
        assert d == {"type": "raster", "size": 0, "hash": ""}


# ═══════════════════════════════════════════════════════════════════
# 4.  BUILD MANIFEST — entry type detection
# ═══════════════════════════════════════════════════════════════════


class TestBuildManifest:
    def test_project_type(self):
        entries = {"project.qgs": b"<qgis/>"}
        manifest = build_manifest(entries)
        assert manifest.entries["project.qgs"].type == "project"

    def test_vector_type(self):
        entries = {"vectors/roads.shp": b"data"}
        manifest = build_manifest(entries)
        assert manifest.entries["vectors/roads.shp"].type == "vector"

    def test_raster_type(self):
        entries = {"rasters/dem.tiff": b"data"}
        manifest = build_manifest(entries)
        assert manifest.entries["rasters/dem.tiff"].type == "raster"

    def test_style_type(self):
        entries = {"styles/roads.qml": b"<qgis/>"}
        manifest = build_manifest(entries)
        assert manifest.entries["styles/roads.qml"].type == "style"

    def test_sld_style_type(self):
        entries = {"styles/parcels.sld": b"<sld/>"}
        manifest = build_manifest(entries)
        assert manifest.entries["styles/parcels.sld"].type == "style"

    def test_manifest_entry_type(self):
        entries = {"woof-manifest.json": b"{}"}
        manifest = build_manifest(entries)
        assert manifest.entries["woof-manifest.json"].type == "manifest"

    def test_arcpy_entry_type(self):
        entries = {"layer_tree.json": b"[]"}
        manifest = build_manifest(entries)
        assert manifest.entries["layer_tree.json"].type == "arcpy"

    def test_resource_fallback(self):
        entries = {"data/notes.txt": b"hello"}
        manifest = build_manifest(entries)
        assert manifest.entries["data/notes.txt"].type == "resource"

    def test_size_and_hash_recorded(self):
        content = b"hello world"
        entries = {"hello.txt": content}
        manifest = build_manifest(entries)
        entry = manifest.entries["hello.txt"]
        assert entry.size == len(content)
        assert isinstance(entry.hash, str)
        assert len(entry.hash) > 0

    def test_uri_rewrites_from_path_map(self):
        entries = {"project.qgs": b"<qgis/>"}
        path_map = {"/home/user/project.qgs": "project.qgs"}
        manifest = build_manifest(entries, path_map=path_map)
        assert "woof://project.qgs" in manifest.uri_rewrites
        assert manifest.uri_rewrites["woof://project.qgs"] == "/home/user/project.qgs"

    def test_dependencies_included(self):
        entries = {"project.qgs": b"<qgis/>"}
        deps = {"project.qgs": ["roads.geojson"]}
        manifest = build_manifest(entries, dependencies=deps)
        assert manifest.dependencies == deps

    def test_plugin_version(self):
        entries = {"project.qgs": b"<qgis/>"}
        manifest = build_manifest(entries, plugin_version="2.0.0")
        assert manifest.plugin_version == "2.0.0"


# ═══════════════════════════════════════════════════════════════════
# 5.  _READ_MANIFEST (via woof_storage)
# ═══════════════════════════════════════════════════════════════════


class TestReadManifest:
    @patch("dock_export.woof.woof_storage.unpack_one")
    def test_read_manifest_returns_none_for_empty_data(self, mock_unpack_one):
        mock_unpack_one.side_effect = KeyError("not found")
        assert _read_manifest(b"") is None

    @patch("dock_export.woof.woof_storage.unpack_one")
    def test_read_manifest_valid(self, mock_unpack_one):
        manifest = Manifest(
            woof_version=4,
            created="2026-07-29T12:00:00+00:00",
            plugin_version="1.0.0",
            entries={
                "project.qgs": ManifestEntry(
                    type="project", size=42, hash="abc"
                ),
            },
            dependencies={},
            uri_rewrites={},
        )
        mock_unpack_one.return_value = manifest.to_json().encode("utf-8")
        result = _read_manifest(b"fake-woof-data")
        assert result is not None
        assert result.woof_version == 4
        assert "project.qgs" in result.entries


# ═══════════════════════════════════════════════════════════════════
# 6.  FAST HASH DETERMINISM
# ═══════════════════════════════════════════════════════════════════


class TestFastHash:
    def test_deterministic(self):
        data = b"hello world"
        assert _fast_hash(data) == _fast_hash(data)

    def test_different_inputs_differ(self):
        assert _fast_hash(b"abc") != _fast_hash(b"xyz")
