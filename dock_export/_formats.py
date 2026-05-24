"""Single source of truth for export format lists.

At module init, GDAL is queried for write-capable file-based drivers.
Unavailable drivers are excluded from the returned lists.
If GDAL is not available, the full static lists are used as fallback.
"""

from __future__ import annotations

# ── Master label map: driver short name → display label ──────────────────
DRIVER_LABELS: dict[str, str] = {
    # Vector drivers
    "GPKG": "GeoPackage",
    "ESRI Shapefile": "Shapefile",
    "GeoJSON": "GeoJSON",
    "GeoJSONSeq": "GeoJSON (Newline Delimited)",
    "KML": "KML",
    "LIBKML": "LIBKML",
    "CSV": "CSV",
    "FlatGeobuf": "FlatGeobuf",
    "GPX": "GPX",
    "GML": "GML",
    "TopoJSON": "TopoJSON",
    "SQLite": "SQLite",
    "SpatiaLite": "SpatiaLite",
    "DXF": "DXF",
    "DGN": "Microstation DGN",
    "MapInfo File": "MapInfo TAB",
    "Parquet": "GeoParquet",
    "Arrow": "Arrow",
    "MBTiles": "MBTiles",
    "FileGDB": "ESRI File Geodatabase",
    "OpenFileGDB": "OpenFileGDB",
    "GeoRSS": "GeoRSS",
    "MVT": "MVT (Mapbox Vector Tiles)",
    "PMTiles": "PMTiles",
    "JSONFG": "JSONFG (OGC JSON)",
    "MapML": "MapML",
    "PDF": "PDF (Geospatial)",
    "VDV": "VDV (Transit Data)",
    "JML": "JML (OpenJUMP)",
    "PGDUMP": "PGDUMP (PostgreSQL SQL)",
    "MiraMonVector": "MiraMon Vector",
    "OGR_GMT": "GMT ASCII (.gmt)",
    "Selafin": "Selafin",
    "WAsP": "WAsP (.map)",
    "XLSX": "XLSX",
    "ODS": "ODS",
    # Raster drivers
    "GTiff": "GeoTIFF",
    "COG": "Cloud Optimized GeoTIFF",
    "VRT": "Virtual Raster",
    "ENVI": "ENVI (.hdr)",
    "EHdr": "EHdr (ESRI BIL)",
    "ECW": "ECW (Wavelet)",
    "PNG": "PNG",
    "JPEG": "JPEG",
    "JPEG2000": "JPEG2000",
    "WEBP": "WebP",
    "JPEGXL": "JPEG XL",
    "GIF": "GIF",
    "NetCDF": "NetCDF",
    "BMP": "BMP",
    "HFA": "ERDAS Imagine (.img)",
    "PCIDSK": "PCIDSK",
    "NITF": "NITF",
    "GRIB": "GRIB (.grb)",
    "SAGA": "SAGA GIS (.sdat)",
    "Zarr": "Zarr",
    "AAIGrid": "AAIGrid (ASCII)",
    "DTED": "DTED",
    "SRTMHGT": "SRTMHGT",
    "XYZ": "XYZ Grid",
    "PCRaster": "PCRaster",
    "ILWIS": "ILWIS",
    "RST": "RST (Idrisi)",
    "ZMap": "ZMap",
    "SIGDEM": "SIGDEM",
    "Terragen": "Terragen",
}

# ── Preferred ordering ───────────────────────────────────────────────────
_VECTOR_DRIVER_ORDER: list[str] = [
    "GPKG",
    "ESRI Shapefile",
    "GeoJSON",
    "GeoJSONSeq",
    "KML",
    "LIBKML",
    "CSV",
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
    "MBTiles",
    "OpenFileGDB",
    "FileGDB",
    "GeoRSS",
    "MVT",
    "PMTiles",
    "JSONFG",
    "MapML",
    "PDF",
    "VDV",
    "JML",
    "PGDUMP",
    "MiraMonVector",
    "OGR_GMT",
    "Selafin",
    "WAsP",
    "XLSX",
    "ODS",
]

_RASTER_DRIVER_ORDER: list[str] = [
    "GTiff",
    "COG",
    "VRT",
    "ENVI",
    "EHdr",
    "ECW",
    "PNG",
    "JPEG",
    "JPEG2000",
    "WEBP",
    "JPEGXL",
    "GIF",
    "NetCDF",
    "BMP",
    "MBTiles",
    "HFA",
    "PCIDSK",
    "NITF",
    "GRIB",
    "SAGA",
    "Zarr",
    "AAIGrid",
    "DTED",
    "SRTMHGT",
    "XYZ",
    "PDF",
    "PCRaster",
    "ILWIS",
    "RST",
    "ZMap",
    "SIGDEM",
    "Terragen",
]

# Drivers that require live database/network connections or API credentials
_EXCLUDED_VECTOR_DRIVERS: frozenset[str] = frozenset(
    {
        "MySQL",
        "PostgreSQL",
        "PGeo",
        "MSSQLSpatial",
        "SDE",
        "Oracle",
        "Carto",
        "AmigoCloud",
        "Elasticsearch",
        "CouchDB",
        "MongoDBv3",
        "GNS",
        "WFS",
        "OAPIF",
        "GPSBabel",
        "BAG",
    }
)

_ALL_VECTOR: frozenset[str] = frozenset(_VECTOR_DRIVER_ORDER)
_ALL_RASTER: frozenset[str] = frozenset(_RASTER_DRIVER_ORDER)


def _query_gdal(is_vector: bool) -> set[str]:
    """Return set of write-capable file-based GDAL drivers available at runtime.

    Excludes database/cloud/API drivers (those with DMD_CONNECTION_PREFIX).
    Falls back to the full static set if GDAL is not available.
    """
    try:
        from osgeo import gdal

        available: set[str] = set()
        for i in range(gdal.GetDriverCount()):
            drv = gdal.GetDriver(i)
            meta = drv.GetMetadata()
            can_create = (
                meta.get("DCAP_CREATE") == "YES" or meta.get("DCAP_CREATECOPY") == "YES"
            )
            if not can_create:
                continue
            if is_vector and meta.get("DCAP_VECTOR") == "YES":
                # Skip database/cloud/API drivers that require live connections
                if (
                    meta.get("DMD_CONNECTION_PREFIX")
                    or drv.ShortName in _EXCLUDED_VECTOR_DRIVERS
                ):
                    continue
                available.add(drv.ShortName)
            elif not is_vector and meta.get("DCAP_RASTER") == "YES":
                available.add(drv.ShortName)
        return available
    except Exception:
        return set()


# ── Determine available drivers at import time ───────────────────────────
_available_vector: set[str] = _query_gdal(is_vector=True)
_available_raster: set[str] = _query_gdal(is_vector=False)

AVAILABLE_VECTOR_DRIVERS: frozenset[str] = (
    frozenset(_available_vector) if _available_vector else _ALL_VECTOR
)
AVAILABLE_RASTER_DRIVERS: frozenset[str] = (
    frozenset(_available_raster) if _available_raster else _ALL_RASTER
)


# ── Public helpers ───────────────────────────────────────────────────────
def get_vector_formats(include_default: bool = False) -> list[tuple[str, str]]:
    """Return (label, driver) pairs for every available vector format."""
    result: list[tuple[str, str]] = []
    if include_default:
        result.append(("Default", ""))
    available = AVAILABLE_VECTOR_DRIVERS
    if available is _ALL_VECTOR:
        for d in _VECTOR_DRIVER_ORDER:
            result.append((DRIVER_LABELS.get(d, d), d))
    else:
        for d in _VECTOR_DRIVER_ORDER:
            if d in available:
                result.append((DRIVER_LABELS.get(d, d), d))
        for d in sorted(available - _ALL_VECTOR):
            result.append((d, d))
    return result


def get_raster_formats(include_default: bool = False) -> list[tuple[str, str]]:
    """Return (label, driver) pairs for every available raster format."""
    result: list[tuple[str, str]] = []
    if include_default:
        result.append(("Default", ""))
    available = AVAILABLE_RASTER_DRIVERS
    if available is _ALL_RASTER:
        for d in _RASTER_DRIVER_ORDER:
            result.append((DRIVER_LABELS.get(d, d), d))
    else:
        for d in _RASTER_DRIVER_ORDER:
            if d in available:
                result.append((DRIVER_LABELS.get(d, d), d))
        for d in sorted(available - _ALL_RASTER):
            result.append((d, d))
    return result
