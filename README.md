# Dock Export

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![QGIS](https://img.shields.io/badge/QGIS-3.22+-green)](https://www.qgis.org/)
[![Qt](https://img.shields.io/badge/Qt-5.x_|_6.x-green)](https://www.qt.io/)

A spec-driven export plugin for QGIS. Select layers once, configure everything in one place — names, formats, filters, CRS, styles, field subsets — and export to single files, GeoPackage, or portable `.woof` / ZIP archives. Never mutates live project layers.

---

## What problem does this solve?

Normally in QGIS, exporting layers means repeating the same steps over and over: right-click → Export → pick format → pick path → repeat. Need the same layer in three formats? Do it three times. Want to filter, reproject, and apply a style? That's more dialogs per layer. Have a project with 20 layers to share? Export them one by one or zip the project file and hope the file paths match.

Dock Export replaces all of that with a single dock:

- **Select layers once** — check what you need from one list
- **Configure everything in one place** — rename, filter, reproject, subset fields, apply styles per layer
- **Export in one click** — single files (multiple formats per layer), one multi-layer GeoPackage, or a fully self-contained archive (`.woof` / `.zip`) with rewritten project XML

It's a shortcut for: *I need to get data out of QGIS without busywork.*

---

### Gallery

| Single Files Tab | GeoPackage Tab | Project Export Tab | History Tab |
| ---------------- | -------------- | ------------------ | ----------- |
| ![Single files tab](gallery/single-tab.png) | ![GeoPackage tab](gallery/gpkg-tab.png) | ![Project export tab](gallery/project-tab.png) | ![History tab](gallery/history-tab.png) |

---

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

    PET --> WOOF[.woof archive\nv3 Rust]
    PET --> ZIP[ZIP archive]
```

---

## Features

### Export modes

| Mode | What it does | Best for |
|------|-------------|----------|
| **Single Files** | Each selected layer → one or more files in a directory (GPKG, Shapefile, GeoJSON, GeoTIFF, ...) | Delivering layers individually, converting formats, archiving in a folder structure |
| **GeoPackage** | All selected layers → a single `.gpkg` file with separate tables | Sharing many layers as one file, embedding in other projects |
| **Project Export** | Entire project → `.woof` archive or `.zip`, with all source files + rewritten project XML | Sending the whole project to someone, backup, moving between machines |

### Per-layer controls

- **Export name** — rename per layer independently of the source name; naming template with `{layer_name}`, `{date}`, `{crs}`, `{datetime}` placeholders
- **QGIS expression filter** — per-layer `WHERE` clause using `QgsExpression` (field list, function tree, search, validation)
- **CRS reprojection** — per-layer target CRS via native QGIS projection selector
- **Field subset** — choose which attributes to include per layer
- **Format override** — per-layer driver override (e.g. force a specific layer to Shapefile while the rest use GPKG)

### Vector formats

GPKG, ESRI Shapefile, GeoJSON, KML, CSV, FlatGeobuf, GPX, GML, TopoJSON, SQLite, SpatiaLite, Newline-delimited GeoJSON, DXF, DGN, MapInfo TAB, GeoParquet, Arrow, MBTiles, ESRI FileGDB, GeoRSS, XLSX, ODS.

### Raster formats

GeoTIFF, PNG, JPEG, JPEG2000, WebP, BMP, MBTiles, ERDAS Imagine.

### Style management

- **QML sidecars** — per-layer `.qml` files next to the export
- **SLD sidecars** — per-layer `.sld` files (vector only)
- **Embed in GPKG** — styles stored in the `layer_styles` table (works with Single Files GPKG and GeoPackage tab)

### Archive export (.woof / ZIP)

- **.woof** — native Rust archive format with xxhash3-64 integrity verification, seek table for random access, per-entry zstd compression, parallel decompression
- **ZIP** — standard deflate compression via Python `zipfile`
- **Compression levels** — None / Normal / Heavy (maps to zstd levels 0 / 3 / 9)
- **Handles remote layers** — WMS, WFS, PostGIS, etc. keep their original datasource URLs in the project XML
- **Handles sidecars** — QML, SLD, world files (`.tfw`, `.pgw`, `.jgw`, ...) alongside source files are collected automatically
- **Project resources** — layout images, SVGs, HTML items, report templates are included
- **XML rewriting** — datasource paths in the project file are rewritten to archive-relative paths

### QGIS integration

- Docks inside the QGIS main window (not a modal dialog)
- Right-click any layer → opens Dock Export with that layer preselected
- `.woof` opener injected into Project → Open From submenu
- Auto-refresh when layers are added, removed, or renamed
- Settings persist across QGIS sessions via `QgsSettings`

---

## .woof Archive Format

`.woof` is a portable, self-contained snapshot of a QGIS project. It bundles every file the project depends on — vector datasets, rasters, GeoPackages, QML/SLD styles, world files, layout images, SVGs, report templates, and the project file itself with all datasource paths rewritten to relative references inside the archive.

`.woof` files are opened directly from QGIS via Project → Open From → Open `.woof` Project. The archive is extracted in-memory and the project loads with all paths resolved — no broken links, no missing sidecars. Remote layers (WMS, WFS, PostGIS) keep their original URLs and are not packaged; scratch and memory layers are noted as not packaged.

The archive format is implemented as a native Rust crate (`native_woof_impl`) exposed to Python via PyO3. Each file in the archive is stored as a separate entry with its own zstd compression level, xxhash3-64 integrity hash, and seek-table metadata that allows random access — you can extract a single file without decompressing the entire archive. Decompression runs in parallel across entries for fast extraction.

## License

GNU General Public License v3.0. See `LICENSE`.
