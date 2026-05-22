"""Pure-data classes: ExportSpec (single export job) and ExportResult (outcome)."""

from dataclasses import dataclass
from typing import List


class StyleMode:
    """String constants for style export modes."""

    NONE = "none"
    QML = "qml"
    SLD = "sld"
    BOTH = "both"
    EMBED = "embed"


@dataclass
class ExportSpec:
    """Describes a single layer export job. Pure data -- never holds layer references.

    Stores the source layer ID instead of a QgsMapLayer object so the engine
    looks it up at write time.

    Parameters
    ----------
    source_layer_id : str
        ID of the source QgsMapLayer in the current project.
    export_name : str
        Output layer/table name and file stem. Independent of live layer name.
    target_mode : str
        'single' -> each layer to its own file; 'gpkg' -> table in one GeoPackage.
    output_path : str
        For 'single': output directory. For 'gpkg': full .gpkg path.
    driver : str
        OGR driver string: 'GPKG', 'ESRI Shapefile', 'GeoJSON', 'KML',
        'FlatGeobuf', 'GTiff'.
    filter_expression : str
        Optional QGIS expression filter. Empty = all features.
    style_mode : str
        One of StyleMode constants: NONE, QML, SLD, BOTH, EMBED.
    replace_in_project : bool
        If True, calls setDataSource on the project layer after successful export.
    target_crs_authid : str
        Target CRS in WKT or EPSG:AUTHID form. Empty = source layer CRS.
    """

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
    field_names: List[str] = None

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
