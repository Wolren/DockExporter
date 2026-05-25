"""Pure-data classes: ExportSpec (single export job), ExportResult (outcome), StyleMode (constants)."""

from __future__ import annotations

from dataclasses import dataclass

from ._formats import AVAILABLE_RASTER_DRIVERS as RASTER_DRIVERS


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
    field_types: dict[str, str] | None = None
    encoding: str = "UTF-8"
    save_selected_only: bool = False
    use_aliases_for_export_name: bool = False
    persist_layer_metadata: bool = False
    geometry_type_override: str = ""
    force_z: bool = False
    force_multi: bool = False
    filter_extent: str = ""
    datasource_options: list[str] | None = None
    layer_options: list[str] | None = None
    raster_resolution_x: float = 0.0
    raster_resolution_y: float = 0.0
    raster_nodata: str = ""
    field_export_names: dict[str, str] | None = None
    skip_attribute_creation: bool = False
    include_constraints: bool = False
    description: str = ""
    layer_fid: str = ""
    geometry_name: str = ""
    identifier: str = ""
    spatial_index: str = "YES"

    @property
    def is_raster_driver(self) -> bool:
        return self.driver in RASTER_DRIVERS

    @property
    def file_extension(self) -> str:
        mapping = {
            "GPKG": ".gpkg",
            "ESRI Shapefile": ".shp",
            "GeoJSON": ".geojson",
            "GeoJSONSeq": ".geojsonl",
            "KML": ".kml",
            "LIBKML": ".kml",
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
            "OpenFileGDB": ".gdb",
            "GeoRSS": ".xml",
            "MVT": ".mvt",
            "PMTiles": ".pmtiles",
            "JSONFG": ".json",
            "MapML": ".mapml",
            "PDF": ".pdf",
            "VDV": ".vdv",
            "JML": ".jml",
            "PGDUMP": ".sql",
            "MiraMonVector": ".pol",
            "OGR_GMT": ".gmt",
            "Selafin": ".slf",
            "WAsP": ".map",
            "XLSX": ".xlsx",
            "ODS": ".ods",
            "GTiff": ".tif",
            "COG": ".tif",
            "VRT": ".vrt",
            "ENVI": ".dat",
            "EHdr": ".bil",
            "ECW": ".ecw",
            "PNG": ".png",
            "JPEG": ".jpg",
            "JPEG2000": ".jp2",
            "WEBP": ".webp",
            "JPEGXL": ".jxl",
            "GIF": ".gif",
            "NetCDF": ".nc",
            "BMP": ".bmp",
            "HFA": ".img",
            "PCIDSK": ".pix",
            "NITF": ".ntf",
            "GRIB": ".grb",
            "SAGA": ".sdat",
            "Zarr": ".zarr",
            "AAIGrid": ".asc",
            "DTED": ".dt2",
            "SRTMHGT": ".hgt",
            "XYZ": ".xyz",
            "PCRaster": ".map",
            "ILWIS": ".mpr",
            "RST": ".rst",
            "ZMap": ".zmap",
            "SIGDEM": ".sigdem",
            "Terragen": ".ter",
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
