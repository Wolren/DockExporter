"""Tests for model classes: ExportSpec, ExportResult, StyleMode."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dock_export.models import ExportResult, ExportSpec, StyleMode


class TestStyleMode:
    def test_constants(self):
        assert StyleMode.NONE == "none"
        assert StyleMode.QML == "qml"
        assert StyleMode.SLD == "sld"
        assert StyleMode.BOTH == "both"
        assert StyleMode.EMBED == "embed"


class TestExportSpec:
    def test_defaults(self):
        spec = ExportSpec()
        assert spec.source_layer_id == ""
        assert spec.source_name == ""
        assert spec.export_name == ""
        assert spec.target_mode == "single"
        assert spec.output_path == ""
        assert spec.driver == "GPKG"
        assert spec.filter_expression == ""
        assert spec.style_mode == "none"
        assert spec.replace_in_project is False
        assert spec.target_crs_authid == ""
        assert spec.field_names is None

    def test_known_raster_drivers(self):
        raster_drivers = {
            "GTiff",
            "PNG",
            "JPEG",
            "JPEG2000",
            "WEBP",
            "BMP",
            "HFA",
            "MBTiles",
        }
        for d in raster_drivers:
            assert ExportSpec(driver=d).is_raster_driver, f"{d} should be raster"

    def test_known_vector_drivers(self):
        vector_drivers = {
            "GPKG",
            "ESRI Shapefile",
            "GeoJSON",
            "GeoJSONSeq",
            "KML",
            "FlatGeobuf",
            "GPX",
            "GML",
            "TopoJSON",
            "SQLite",
            "SpatiaLite",
            "DXF",
            "DGN",
            "MapInfo File",
            "Parquet",
            "Arrow",
            "FileGDB",
            "GeoRSS",
            "XLSX",
            "ODS",
        }
        for d in vector_drivers:
            assert not ExportSpec(driver=d).is_raster_driver, f"{d} should be vector"

    def test_file_extension_all(self):
        cases = {
            "GPKG": ".gpkg",
            "ESRI Shapefile": ".shp",
            "GeoJSON": ".geojson",
            "GeoJSONSeq": ".geojsonl",
            "KML": ".kml",
            "FlatGeobuf": ".fgb",
            "GPX": ".gpx",
            "GML": ".gml",
            "TopoJSON": ".topojson",
            "SQLite": ".sqlite",
            "SpatiaLite": ".sqlite",
            "DXF": ".dxf",
            "DGN": ".dgn",
            "MapInfo File": ".tab",
            "Parquet": ".parquet",
            "Arrow": ".arrow",
            "MBTiles": ".mbtiles",
            "FileGDB": ".gdb",
            "GeoRSS": ".xml",
            "XLSX": ".xlsx",
            "ODS": ".ods",
            "GTiff": ".tif",
            "PNG": ".png",
            "JPEG": ".jpg",
            "JPEG2000": ".jp2",
            "WEBP": ".webp",
            "BMP": ".bmp",
            "HFA": ".img",
        }
        for driver, expected_ext in cases.items():
            spec = ExportSpec(driver=driver)
            assert (
                spec.file_extension == expected_ext
            ), f"driver={driver!r}: expected {expected_ext!r}, got {spec.file_extension!r}"

    def test_file_extension_default(self):
        spec = ExportSpec(driver="UNKNOWN_DRIVER")
        assert spec.file_extension == ".gpkg"

    def test_is_raster_driver_default(self):
        assert not ExportSpec().is_raster_driver

    def test_export_spec_str_does_not_crash(self):
        spec = ExportSpec(source_layer_id="abc", export_name="test")
        text = str(spec)
        assert "abc" in text
        assert "test" in text

    def test_export_spec_repr(self):
        spec = ExportSpec(driver="GeoJSON")
        r = repr(spec)
        assert "ExportSpec" in r
        assert "GeoJSON" in r


class TestExportResult:
    def test_defaults(self):
        spec = ExportSpec()
        result = ExportResult(spec)
        assert result.spec is spec
        assert result.success is False
        assert result.output_path == ""
        assert result.error == ""
        assert result.features_written == 0

    def test_success_result(self):
        spec = ExportSpec(driver="GPKG")
        result = ExportResult(
            spec,
            success=True,
            output_path="/tmp/out.gpkg",
            features_written=42,
        )
        assert result.success
        assert result.output_path == "/tmp/out.gpkg"
        assert result.features_written == 42

    def test_failure_result(self):
        spec = ExportSpec()
        result = ExportResult(spec, success=False, error="Disk full")
        assert not result.success
        assert result.error == "Disk full"

    def test_spec_mutation_independence(self):
        spec = ExportSpec(driver="GPKG")
        result = ExportResult(spec)
        spec.driver = "GeoJSON"
        assert result.spec.driver == "GeoJSON"
