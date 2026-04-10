"""
models.py  –  Pure-data definitions for the spec-driven export engine.

An ExportSpec fully describes ONE export job.  It never holds a reference
to a live QgsMapLayer object; it stores the *layer ID* instead so the
engine can look it up at write time without keeping layer objects alive.
"""
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ExportSpec:
    """Describes a single layer export operation.

    Parameters
    ----------
    source_layer_id : str
        ID of the source QgsMapLayer in the current project.
    export_name : str
        Output layer/table name and (for single-file formats) the file stem.
        This is set independently of the live layer's display name.
    target_mode : str
        ``'single'`` → write each layer to its own file.
        ``'gpkg'``   → append as a table inside one shared GeoPackage.
    output_path : str
        For ``'single'``: directory path where the file will be written.
        For ``'gpkg'``:   full path to the target ``.gpkg`` file.
    driver : str
        OGR driver string: ``'GPKG'``, ``'ESRI Shapefile'``,
        ``'GeoJSON'``, ``'KML'``; or raster sentinel ``'GTiff'``.
    filter_expression : str
        Optional QGIS feature filter expression (WHERE clause semantics).
        Empty string means "all features".
    style_mode : str
        One of ``'none'``, ``'qml'``, ``'sld'``, ``'both'``, ``'embed'``.
        ``'embed'`` writes the QML into the layer's style table inside the
        GeoPackage.  It is only meaningful when ``driver == 'GPKG'``.
    replace_in_project : bool
        When ``True``, after a successful export the engine calls
        ``setDataSource`` on the original project layer so it points to the
        newly written file.
    """

    source_layer_id: str = ""
    export_name: str = ""
    target_mode: str = "single"      # 'single' | 'gpkg'
    output_path: str = ""            # dir for single, .gpkg path for gpkg
    driver: str = "GPKG"
    filter_expression: str = ""
    style_mode: str = "none"         # 'none'|'qml'|'sld'|'both'|'embed'
    replace_in_project: bool = False

    # ------------------------------------------------------------------ #
    # Helpers                                                              #
    # ------------------------------------------------------------------ #

    @property
    def is_raster_driver(self) -> bool:
        return self.driver in ("GTiff", "PNG", "JPEG")

    @property
    def file_extension(self) -> str:
        mapping = {
            "GPKG": ".gpkg",
            "ESRI Shapefile": ".shp",
            "GeoJSON": ".geojson",
            "GeoJSONSeq": ".geojsonl",
            "KML": ".kml",
            "FlatGeobuf": ".fgb",
            "GTiff": ".tif",
            "PNG": ".png",
            "JPEG": ".jpg",
        }
        return mapping.get(self.driver, ".gpkg")
