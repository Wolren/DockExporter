# Dock Export

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![QGIS](https://img.shields.io/badge/QGIS-3.22+-green)](https://www.qgis.org/)
[![Qt](https://img.shields.io/badge/Qt-5.x_|_6.x-green)](https://www.qt.io/)

Spec-driven export of vector and raster layers from a QGIS project to single files, GeoPackage, or portable `.woof` archives, with per-layer names, QGIS expression filtering, style management, CRS reprojection, and field subset selection. Never mutates live project layers.

## Pipeline

```mermaid
flowchart LR
    L[Project Layers] --> LTW[LayerTableWidget]
    LTW --> SPECS[ExportSpec[]]
    SPECS -->|Single Files| ENG[ExportEngine]
    SPECS -->|GeoPackage| ENG
    SPECS -->|Project Export| PET[ProjectExportTab]

    ENG --> SF[Single Files\n.gpkg .shp .tif ...]
    ENG --> GPKG[Multi-layer\nGeoPackage]

    PET --> WOOF[.woof archive\nv2 / v3 / ZIP]
    PET --> ZIP[ZIP archive]

    subgraph Native [Rust Native Crate]
        V3[v3 pack/unpack\nxxhash3-64, seek table\nzstd per-entry]
    end

    WOOF -.->|pack_v3| V3
    WOOF -.->|pack_v2| PY2[Python v2 impl]
```

The pipeline is fully spec-driven. Export names, filters, CRS targets, style modes, field subsets, and compression levels are staged in `ExportSpec` dataclass instances and applied only at write time. Live project layers are never renamed, filtered, or otherwise mutated.

## Key Capabilities

- **Three export tabs** -- Single Files (per-layer, multiple formats), GeoPackage (multi-layer single `.gpkg`), Project Export (`.woof` archive or `.zip`)
- **.woof archive format** -- Custom binary archive with v2 (Python, zstd) and v3 (Rust native, xxhash3-64 + seek table + random access) versions
- **ZIP export mode** -- Alternative archive format with deflate compression
- **Vector formats** -- GeoPackage, ESRI Shapefile, GeoJSON, KML, FlatGeobuf
- **Raster export** -- GeoTIFF for single files; embedded raster tables in GeoPackage via GDAL
- **Per-layer naming** -- Edit export names independently of source layer names
- **QGIS expression filters** -- WHERE-clause filtering using `QgsExpression`
- **CRS reprojection** -- Per-layer target CRS via native QGIS CRS selector
- **Field subset selection** -- Choose which attributes to include per layer (Layer Settings dialog)
- **Style management** -- QML sidecars, SLD sidecars (vector only), or embedded GeoPackage `layer_styles`
- **Compression levels** -- None / Normal / Heavy for archive exports
- **Project source repointing** -- Optionally add exported files to the QGIS project after write
- **Context menu integration** -- Right-click any layer in the QGIS layer tree to open Dock Export
- **Open From menu** -- `.woof` project opener injected into QGIS Project → Open From submenu
- **Auto-refresh** -- Layer table refreshes on project add/remove/rename signals

## Module Reference

### ExportSpec (`models.py`)

Pure-data dataclass describing one export job. Holds source layer ID, export name, target mode (`single` / `gpkg` / `project`), output path, OGR driver, filter expression, style mode, replace flag, target CRS, and optional field subset.

### LayerTableWidget

Editable table (Type, Source Name, Export Name, Filter badge, CRS). CRS double-click opens the Layer Settings dialog (CRS picker + per-layer field checkboxes).

### ExportEngine

Iterates `ExportSpec` list, resolves source layers from the project, dispatches to format-specific writers:

| Layer type | Mode | Mechanism |
| ---------- | ---- | --------- |
| Vector | Single | `QgsVectorFileWriter.create()` per driver; filtered clone via `QgsFeatureRequest` / `QgsVectorLayer` memory layer when filter/CRS/field-subset requires it |
| Vector | GPKG | Same as single, with `RegeneratePrimaryKey` flag and `CreateOrOverwriteLayer` |
| Raster | Single | `gdal.Translate()` to GeoTIFF |
| Raster | GPKG | `gdal.Translate()` with `RASTER_TABLE` + `APPEND_SUBDATASET=YES` |

### ProjectExportTab

Archives entire project into a single portable file:

| Mode | Format | Mechanism |
| ---- | ------ | --------- |
| .woof (v2) | Python zstd per-entry | `woof_python` module packs entries sequentially |
| .woof (v3) | Rust native, seek table, xxhash3-64 | `native_woof_impl` PyO3 crate for fast pack/unpack |
| ZIP | Standard ZIP with deflate | Python `zipfile` module |

Remote layers (WMS, WFS, PostGIS, etc.) keep their original datasource URLs in the project XML. File-based layers are copied into the archive. Scratch/memory layers are noted as "not packaged."

### StyleManager

Encapsulates QML save, SLD save (vector only), and GeoPackage `layer_styles` embedding via `saveStyleToDatabase()`.

### LayerSettingsDialog

Modal dialog for per-layer settings: CRS picker (`QgsProjectionSelectionDialog`) and attribute field checklist. Opened by double-clicking the CRS cell in `LayerTableWidget`.

### SQLFilterDialog

Modal QGIS expression editor with field list, function tree browser, search, validation via `QgsExpression`, and per-layer application.

## Key Modules

| Module | Purpose |
| ------ | ------- |
| `plugin.py` | Plugin entry, toolbar icon, menu, context menu hook, Open From submenu injection |
| `dock_widget.py` | `QgsDockWidget` wrapper, close-event cleanup |
| `export_widget.py` | Tabbed UI (Single Files / GeoPackage / Project Export / History), export dispatch, progress bar |
| `layer_table_widget.py` | Editable layer table with inline rename, selection, filter/CRS/field indicators, Layer Settings dialog hook |
| `models.py` | `ExportSpec`, `ExportResult` dataclasses |
| `export_engine.py` | Vector/raster export dispatch, filtered clones, CRS transforms |
| `project_export_tab.py` | Project-level archive export (.woof / ZIP), remote layer handling, XML source rewriting |
| `style_manager.py` | QML/SLD sidecar files, GPKG style embedding |
| `sql_filter_widget.py` | QGIS expression editor with field list, function tree, validation |
| `woof_python.py` | Python implementation of .woof v2 format (zstd per-entry, no dedup) |
| `woof_storage.py` | Extract and open .woof archives as QGIS projects |
| `woof_native/` | Rust PyO3 crate implementing .woof v3 format (xxhash3-64, seek table, parallel decompression) |

## .woof Archive Format

| Version | Implementation | Hash | Structure | Speed |
| ------- | -------------- | ---- | --------- | ----- |
| v2 | Python (`woof_python`) | BLAKE3 → xxhash3-64 | Flat: entry count + name heap + payload blob | ~400 MB/s pack (no-compress) |
| v3 | Rust (`woof_native`) | xxhash3-64 | Seek table: sorted name heap, per-entry offset + hash + size, optional zstd | ~650 MB/s pack (no-compress), random access via `unpack_one` |

## Icons

| State | File | Description |
| ----- | ---- | ----------- |
| Enabled | `icons/dock_export.svg` | Three stacked colored volumes (blue, orange, green) — WinRAR-inspired layer stack |

## Concurrency

- Exports run in the main thread with a `QProgressBar` and `QApplication.processEvents()` for UI updates
- No background thread is currently used (annotated in source as a TODO for async via `QThread`)

## Persistence

- No persistent settings file. All state (filters, CRS selections, export names, field subsets) is held in-memory and cleared when the dock is closed.
- `QgsProject` signals (`layersAdded`, `layersRemoved`, `layerWasAdded`, `cleared`, `readProject`, `nameChanged`) trigger auto-refresh.

## Compatibility

- QGIS 3.22 -- 4.99
- Qt5 / Qt6 (via `qgis.PyQt`)
- GDAL required for raster export (usually bundled with QGIS)
- Python 3.10+ (union type syntax)
- Rust native crate requires `maturin build --release` or pre-built wheel

## Known Issues

- No background threading — long exports block the UI
- Filter expression / field subset state is lost on project close (no persistence)
- Scratch and memory layers cannot be packaged into archives (source data is ephemeral)

## Repository Structure

```
Dock exporter/
├── dock_export/                  # Plugin package
│   ├── __init__.py              # QGIS plugin factory
│   ├── metadata.txt             # QGIS plugin metadata
│   ├── plugin.py                # Entry point, toolbar, context menu
│   ├── dock_widget.py           # Dock widget wrapper
│   ├── export_widget.py         # Tabbed UI (Single / GPKG / Project / History)
│   ├── export_engine.py         # Export dispatch engine
│   ├── layer_table_widget.py    # Editable layer table
│   ├── models.py                # ExportSpec, ExportResult
│   ├── project_export_tab.py    # Project archive export (.woof / ZIP)
│   ├── style_manager.py         # QML/SLD/embed helpers
│   ├── sql_filter_widget.py     # Expression filter dialog
│   ├── layer_settings_dialog.py # CRS + field subset dialog
│   ├── woof_python.py           # Python .woof v2 format
│   ├── woof_storage.py          # .woof extract/open
│   └── icons/
│       └── dock_export.svg      # Toolbar icon
├── woof_native/                  # Rust PyO3 crate (v3 format)
│   ├── Cargo.toml
│   ├── pyproject.toml
│   └── src/
│       ├── lib.rs, pack.rs, unpack.rs
│       ├── unpack_one.rs, entry.rs
│       ├── seek_table.rs, error.rs
├── tests/
│   ├── test_woof_format.py      # Format roundtrip tests
│   ├── benchmark_woof.py        # Benchmark suite
│   ├── benchmark_report.md      # Generated benchmark results
│   ├── test_data_gen.py         # Test data generation
│   └── conftest.py              # pytest fixtures
├── gallery/                      # Screenshots (placeholder)
├── LICENSE                       # GNU GPL v3
└── README.md
```

## License

GNU General Public License v3.0. See `LICENSE`.
