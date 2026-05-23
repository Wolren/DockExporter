"""Pure-data classes: ExportSpec (single export job), ExportResult (outcome), StyleMode (constants)."""

from dataclasses import dataclass


class StyleMode:
    """String constants for style export modes."""

    NONE = "none"
    QML = "qml"
    SLD = "sld"
    BOTH = "both"
    EMBED = "embed"


@dataclass
class ExportSpec:
    """Describes a single layer export job. Stores the source layer ID (not a QgsMapLayer reference) for thread safety."""

    source_layer_id: str = ""
    source_name: str = ""
    export_name: str = ""
    target_mode: str = "single"
    output_path: str = ""
    driver: str = "GPKG"
    filter_expression: str = ""
    style_mode: str = "none"
    replace_in_project: bool = False
    target_crs_authid: str = ""
    field_names: list[str] = None

    @property
    def is_raster_driver(self) -> bool:
        return self.driver in (
            "GTiff",
            "PNG",
            "JPEG",
            "JPEG2000",
            "WEBP",
            "BMP",
            "HFA",
            "MBTiles",
        )

    @property
    def file_extension(self) -> str:
        mapping = {
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
        return mapping.get(self.driver, ".gpkg")


@dataclass
class ExportResult:
    """Holds the outcome of a single ExportSpec execution."""

    spec: ExportSpec
    success: bool = False
    output_path: str = ""
    error: str = ""
    features_written: int = 0
