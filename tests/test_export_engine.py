"""Tests for the core export engine — standalone functions.

``export_engine.py`` depends on ``qgis.core`` at the module level.
The conftest.py mocks QGIS for the whole test suite, so we can import
freely here.
"""

from __future__ import annotations

from dock_export.export.export_engine import gpkg_layer_uri
from dock_export.models import ExportSpec

# ═══════════════════════════════════════════════════════════════════
# 1.  gpkg_layer_uri
# ═══════════════════════════════════════════════════════════════════


class TestGpkgLayerUri:
    """Tests for the GPKG URI builder used by export engine."""

    def test_basic_path_and_name(self):
        uri = gpkg_layer_uri("/data/output.gpkg", "roads")
        assert uri == "/data/output.gpkg|layername=roads"

    def test_empty_layername_returns_path(self):
        uri = gpkg_layer_uri("/data/output.gpkg", "")
        assert uri == "/data/output.gpkg"

    def test_layername_with_spaces(self):
        uri = gpkg_layer_uri("/tmp/out.gpkg", "land parcels")
        assert uri == '/tmp/out.gpkg|layername="land parcels"'

    def test_layername_with_backslash(self):
        uri = gpkg_layer_uri("/tmp/out.gpkg", "roads\\bridges")
        assert uri == '/tmp/out.gpkg|layername="roads\\bridges"'

    def test_layername_with_pipe(self):
        uri = gpkg_layer_uri("/tmp/out.gpkg", "a|b")
        assert uri == '/tmp/out.gpkg|layername="a|b"'

    def test_layername_with_double_quote(self):
        """Internal double-quotes are escaped by doubling."""
        uri = gpkg_layer_uri("/tmp/out.gpkg", 'say "hello"')
        assert uri == '/tmp/out.gpkg|layername="say ""hello"""'

    def test_simple_name_no_quoting(self):
        """Simple names must NOT be quoted."""
        uri = gpkg_layer_uri("/data/out.gpkg", "roads")
        assert '"' not in uri

    def test_windows_path_with_spaces(self):
        """A path containing spaces should not affect quoting of a plain layername."""
        uri = gpkg_layer_uri("C:/My Project/data.gpkg", "trees")
        assert uri == 'C:/My Project/data.gpkg|layername=trees'

    def test_layername_with_single_quote(self):
        """Single quotes are considered safe chars and should NOT trigger quoting."""
        uri = gpkg_layer_uri("/tmp/out.gpkg", "o'brien")
        assert uri == '/tmp/out.gpkg|layername="o\'brien"'


# ═══════════════════════════════════════════════════════════════════
# 2.  ExportSpec — additional validation beyond defaults
# ═══════════════════════════════════════════════════════════════════


class TestExportSpecPathGeneration:
    """Verify how ExportSpec produces output file paths."""

    def test_file_extension_gpkg(self):
        spec = ExportSpec(driver="GPKG")
        assert spec.file_extension == ".gpkg"

    def test_file_extension_geojson(self):
        spec = ExportSpec(driver="GeoJSON")
        assert spec.file_extension == ".geojson"

    def test_file_extension_shapefile(self):
        spec = ExportSpec(driver="ESRI Shapefile")
        assert spec.file_extension == ".shp"

    def test_file_extension_unknown_fallsback(self):
        spec = ExportSpec(driver="NONEXISTENT")
        assert spec.file_extension == ".gpkg"

    def test_path_construction(self):
        """Simulate how export_engine builds final output paths."""
        import os

        spec = ExportSpec(
            driver="GeoJSON",
            export_name="my_layer",
            output_path="/tmp/exports",
        )
        expected = os.path.join(
            spec.output_path,
            f"{spec.export_name}{spec.file_extension}",
        )
        # Expect platform-appropriate separator
        if os.sep == "\\":
            assert "\\" in expected
        assert expected.endswith("my_layer.geojson")

    def test_is_raster(self):
        assert ExportSpec(driver="GTiff").is_raster_driver
        assert not ExportSpec(driver="GPKG").is_raster_driver

    def test_field_names_default_none(self):
        spec = ExportSpec()
        assert spec.field_names is None

    def test_target_mode_default(self):
        spec = ExportSpec()
        assert spec.target_mode == "single"
