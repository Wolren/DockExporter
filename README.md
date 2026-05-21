# Dock Export

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![QGIS](https://img.shields.io/badge/QGIS-3.22+-green)](https://www.qgis.org/)
[![Qt](https://img.shields.io/badge/Qt-5.x_|_6.x-green)](https://www.qt.io/)

Spec-driven export of vector and raster layers from a QGIS project to single files or GeoPackage, with per-layer renamed export names, QGIS expression filtering, style management, and CRS reprojection. Never renames or mutates live project layers.

## Gallery

| Single Files Tab | GeoPackage Tab |
| ---------------- | -------------- |
| ![Single files tab](gallery/single-tab.png) | ![GeoPackage tab](gallery/gpkg-tab.png) |

| Filter Dialog | CRS Selector |
| ------------- | ------------ |
| ![Filter dialog](gallery/filter-dialog.png) | ![CRS selector](gallery/crs-selector.png) |

> Gallery images are placeholders. Replace with actual screenshots.
## Pipeline

```

Project Layers --> LayerTableWidget --> ExportSpec[] --> ExportEngine --> Output Files
    (live,        (editable names,    (pure data,       (QGIS/GDAL,     (.gpkg/.shp/
     untouched)     filter/CRS tags)    no layer refs)    with progress)  .geojson/...)
```

The entire export pipeline is spec-driven. Export names, filters, CRS targets, and style modes are staged in `ExportSpec` dataclass instances and applied only at write time. Live project layers are never renamed, filtered, or otherwise mutated.

## Key Capabilities

- **Dual export modes** -- Single files (per-layer, multiple formats) or GeoPackage (multi-layer single `.gpkg`)
- **Vector formats** -- GeoPackage, ESRI Shapefile, GeoJSON, KML, FlatGeobuf
- **Raster export** -- GeoTIFF for single files; embedded raster tables in GeoPackage via GDAL
- **Per-layer naming** -- Edit export names independently of source layer names
- **QGIS expression filters** -- WHERE-clause filtering using `QgsExpression`, validated against live layers
- **CRS reprojection** -- Per-layer target CRS via native QGIS CRS selector
- **Style management** -- QML sidecars, SLD sidecars (vector), both, or embedded GeoPackage `layer_styles`
- **Project source replacement** -- Optionally repoint project layers to exported files after write
- **Context menu integration** -- Right-click any layer in the QGIS layer tree to open Dock Export
- **Auto-refresh** -- Layer table refreshes on project add/remove/rename signals

## Module Reference

### ExportSpec (models.py)

A pure-data dataclass describing one export job. Holds the source layer ID (not a layer reference), export name, target mode (`single`/`gpkg`), output path, OGR driver, filter expression, style mode, replace flag, and target CRS.

### LayerTableWidget

Editable 5-column table (Type, Source Name, Export Name, Filter badge, CRS). Selection-based row picking. Export names are stored internally and read at export time -- the live layer's `setName()` is never called.

### ExportEngine

Iterates `ExportSpec` list, resolves source layers from the project, then:

| Layer type | Mode | Mechanism |
| ---------- | ---- | --------- |
| Vector     | Single | `QgsVectorFileWriter.create()` per driver, filtered clone via `QgsFeatureRequest` when filter/CRS/driver requires it |
| Vector     | GPKG  | Same as single, with `RegeneratePrimaryKey` flag and `CreateOrOverwriteLayer` |
| Raster     | Single | `gdal.Translate()` to GeoTIFF |
| Raster     | GPKG  | `gdal.Translate()` with `RASTER_TABLE` + `APPEND_SUBDATASET=YES` |

### StyleManager

Encapsulates QML save, SLD save (vector only), and GeoPackage `layer_styles` embedding via `saveStyleToDatabase()`.

### SQLFilterDialog

Modal QGIS expression editor with field list, function tree browser, search, validation via `QgsExpression`, and per-layer application.

## Key Modules

| Module | Purpose |
| ------ | ------- |
| `plugin.py` | Plugin entry, toolbar icon, menu, context menu hook |
| `dock_widget.py` | `QgsDockWidget` wrapper, close-event cleanup |
| `export_widget.py` | Tabbed UI (Single Files / GeoPackage), export dispatch, progress bar |
| `layer_table_widget.py` | Editable layer table with inline rename, selection, filter/CRS indicators |
| `models.py` | `ExportSpec` dataclass |
| `export_engine.py` | Vector/raster export dispatch, filtered clones, CRS transforms |
| `style_manager.py` | QML/SLD sidecar files, GPKG style embedding |
| `sql_filter_widget.py` | QGIS expression editor with field list, function tree, validation |

## Concurrency

- Exports run in the main thread with a `QProgressBar` and `QApplication.processEvents()` for UI updates
- No background thread is currently used (annotated in source as a TODO for async via `QThread`)

## Persistence

- No persistent settings file. All state (filters, CRS selections, export names) is held in-memory and cleared when the dock is closed.
- `QgsProject` signals (`layersAdded`, `layersRemoved`, `layerWasAdded`, `cleared`, `readProject`, `nameChanged`) trigger auto-refresh.

## Compatibility

- QGIS 3.22 -- 4.99
- Qt5 / Qt6 (via `qgis.PyQt`)
- GDAL required for raster export (usually bundled with QGIS)

## Known Issues

- Raster sources from non-file providers (WMS, WMTS, XYZ) are not exportable
- No background threading -- long exports block the UI
- Filter expression state is lost on project close (no persistence)

## Repository Structure

```
dock-export/
├── dock_export/               # Plugin package
│   ├── __init__.py           # QGIS plugin factory
│   ├── metadata.txt          # QGIS plugin metadata
│   ├── plugin.py             # Entry point, toolbar, context menu
│   ├── dock_widget.py        # Dock widget wrapper
│   ├── export_widget.py      # Tabbed UI (Single / GeoPackage)
│   ├── layer_table_widget.py # Editable layer table
│   ├── models.py             # ExportSpec dataclass
│   ├── export_engine.py      # Export dispatch engine
│   ├── style_manager.py      # QML/SLD/embed helpers
│   └── sql_filter_widget.py  # Expression filter dialog
├── temp/                      # Draft/iteration files
└── LICENSE                    # GNU GPL v3
```

## License

GNU General Public License v3.0. See `LICENSE`.
