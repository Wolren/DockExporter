"""Editable layer table widget. Displays project layers with export names, format overrides, filters, and CRS settings."""

from __future__ import annotations

from qgis.core import (
    QgsApplication,
    QgsCoordinateReferenceSystem,
    QgsMapLayer,
    QgsProject,
    QgsRasterLayer,
    QgsVectorLayer,
)
from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtGui import QBrush, QColor, QIcon, QPalette
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHeaderView,
    QSizePolicy,
    QStyle,
    QTableWidget,
    QTableWidgetItem,
)

from .export_engine import layer_export_block_reason
from .layer_settings_dialog import LayerSettingsDialog

COL_TYPE = 0
COL_SOURCE = 1
COL_EXPORT = 2
COL_FORMAT = 3
COL_FILTER = 4
COL_CRS = 5
N_COLS = 6

VECTOR_FORMATS = [
    ("Default", ""),
    ("GeoPackage", "GPKG"),
    ("Shapefile", "ESRI Shapefile"),
    ("GeoJSON", "GeoJSON"),
    ("KML", "KML"),
    ("LIBKML", "LIBKML"),
    ("CSV", "CSV"),
    ("FlatGeobuf", "FlatGeobuf"),
    ("GPX", "GPX"),
    ("GML", "GML"),
    ("TopoJSON", "TopoJSON"),
    ("SQLite", "SQLite"),
    ("SpatiaLite", "SpatiaLite"),
    ("GeoJSON (Newline Delimited)", "GeoJSONSeq"),
    ("DXF", "DXF"),
    ("Microstation DGN", "DGN"),
    ("MapInfo TAB", "MapInfo File"),
    ("GeoParquet", "Parquet"),
    ("Arrow", "Arrow"),
    ("MBTiles", "MBTiles"),
    ("OpenFileGDB", "OpenFileGDB"),
    ("ESRI File Geodatabase", "FileGDB"),
    ("GeoRSS", "GeoRSS"),
    ("MVT (Mapbox Vector Tiles)", "MVT"),
    ("PMTiles", "PMTiles"),
    ("JSONFG (OGC JSON)", "JSONFG"),
    ("MapML", "MapML"),
    ("PDF (Geospatial)", "PDF"),
    ("VDV (Transit Data)", "VDV"),
    ("JML (OpenJUMP)", "JML"),
    ("PGDUMP (PostgreSQL SQL)", "PGDUMP"),
    ("MiraMon Vector", "MiraMonVector"),
    ("GMT ASCII (.gmt)", "OGR_GMT"),
    ("Selafin", "Selafin"),
    ("WAsP (.map)", "WAsP"),
    ("XLSX", "XLSX"),
    ("ODS", "ODS"),
]
RASTER_FORMATS = [
    ("Default", ""),
    ("GeoTIFF", "GTiff"),
    ("Cloud Optimized GeoTIFF", "COG"),
    ("Virtual Raster", "VRT"),
    ("ENVI (.hdr)", "ENVI"),
    ("EHdr (ESRI BIL)", "EHdr"),
    ("ECW (Wavelet)", "ECW"),
    ("PNG", "PNG"),
    ("JPEG", "JPEG"),
    ("JPEG2000", "JPEG2000"),
    ("WebP", "WEBP"),
    ("JPEG XL", "JPEGXL"),
    ("GIF", "GIF"),
    ("NetCDF", "NetCDF"),
    ("BMP", "BMP"),
    ("MBTiles", "MBTiles"),
    ("ERDAS Imagine (.img)", "HFA"),
    ("PCIDSK", "PCIDSK"),
    ("NITF", "NITF"),
    ("GRIB (.grb)", "GRIB"),
    ("SAGA GIS (.sdat)", "SAGA"),
    ("Zarr", "Zarr"),
    ("AAIGrid (ASCII)", "AAIGrid"),
    ("DTED", "DTED"),
    ("SRTMHGT", "SRTMHGT"),
    ("XYZ Grid", "XYZ"),
    ("PDF (Geospatial)", "PDF"),
    ("PCRaster", "PCRaster"),
    ("ILWIS", "ILWIS"),
    ("RST (Idrisi)", "RST"),
    ("ZMap", "ZMap"),
    ("SIGDEM", "SIGDEM"),
    ("Terragen", "Terragen"),
]
FORMAT_DEFAULT_KEY = ""


class LayerTableWidget(QTableWidget):
    """Editable layer table used in the Single Files and GeoPackage tabs.

    Columns: Type icon, Source Name, Export Name, Format, Filter, CRS.

    Signals
    -------
    selection_changed(layer_ids: list[str])
    export_name_changed(layer_id: str, new_name: str)
    crs_changed(layer_id: str, authid: str)
    format_changed(layer_id: str, driver: str)
    """

    selection_changed = pyqtSignal(list)
    export_name_changed = pyqtSignal(str, str)
    crs_changed = pyqtSignal(str, str)
    format_changed = pyqtSignal(str, str)

    def __init__(self, show_format: bool = True, parent=None):
        super().__init__(0, N_COLS, parent)
        self._show_format = show_format
        self._export_names: dict[str, str] = {}
        self._format_overrides: dict[str, str] = {}
        self._filters: dict[str, str] = {}
        self._target_crs: dict[str, str] = {}
        self._field_filters: dict[str, list[str]] = {}
        self._export_warnings: dict[str, str] = {}
        self._row_for_layer: dict[str, int] = {}

        self._setup_header()
        self._setup_appearance()
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.itemChanged.connect(self._on_item_changed)
        self.itemSelectionChanged.connect(self._emit_selection_changed)
        self.cellClicked.connect(self._on_cell_clicked)

    def sizeHint(self):
        """Cap preferred height so the dock does not overflow the main window."""
        hint = super().sizeHint()
        max_rows = 10
        header_h = self.horizontalHeader().height() if self.horizontalHeader() else 25
        row_h = self.verticalHeader().defaultSectionSize() or 22
        frame = self.frameWidth() * 2
        max_h = header_h + max_rows * row_h + frame
        hint.setHeight(min(hint.height(), max_h))
        return hint

    def _setup_header(self) -> None:
        headers = ["", "Source Name", "Export Name", "Format", "Filter", "Settings"]
        self.setHorizontalHeaderLabels(headers)
        hh = self.horizontalHeader()
        hh.setStyleSheet("font-weight:bold;")
        hh.setStretchLastSection(True)
        hh.setSectionResizeMode(COL_TYPE, QHeaderView.ResizeMode.Fixed)
        hh.setSectionResizeMode(COL_SOURCE, QHeaderView.ResizeMode.Interactive)
        hh.setSectionResizeMode(COL_EXPORT, QHeaderView.ResizeMode.Interactive)
        hh.setSectionResizeMode(COL_FORMAT, QHeaderView.ResizeMode.Interactive)
        hh.setSectionResizeMode(COL_FILTER, QHeaderView.ResizeMode.Fixed)
        hh.setSectionResizeMode(COL_CRS, QHeaderView.ResizeMode.Interactive)
        self.setColumnWidth(COL_TYPE, 20)
        self.setColumnWidth(COL_SOURCE, 90 if self._show_format else 125)
        self.setColumnWidth(COL_EXPORT, 90 if self._show_format else 125)
        self.setColumnWidth(COL_FORMAT, 80 if self._show_format else 0)
        self.setColumnWidth(COL_FILTER, 50)
        self.setColumnWidth(COL_CRS, 48)
        self.setColumnHidden(COL_FORMAT, not self._show_format)

    def _setup_appearance(self) -> None:
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
            | QAbstractItemView.EditTrigger.SelectedClicked,
        )
        self.setAlternatingRowColors(True)
        self.verticalHeader().setVisible(False)
        self.setShowGrid(False)

    def populate(
        self,
        layers: list[QgsMapLayer],
        type_filter: str | None = None,
    ) -> None:
        """Populate the table with the given list of layers."""
        prev_selected = set(self.selected_layer_ids())
        self.blockSignals(True)
        self.setRowCount(0)
        self._row_for_layer.clear()

        rows_to_reselect: list[int] = []
        for layer in layers:
            is_vector = isinstance(layer, QgsVectorLayer)
            is_raster = isinstance(layer, QgsRasterLayer)
            if type_filter == "vector" and not is_vector:
                continue
            if type_filter == "raster" and not is_raster:
                continue

            row = self.rowCount()
            self.insertRow(row)
            self._row_for_layer[layer.id()] = row

            block_reason = layer_export_block_reason(layer)
            self._export_warnings[layer.id()] = block_reason

            type_item = QTableWidgetItem("")
            type_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            type_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            type_item.setData(Qt.ItemDataRole.UserRole, layer.id())
            type_item.setIcon(self._icon_for_layer(layer))
            type_tooltip = (
                "Vector layer"
                if is_vector
                else "Raster layer"
                if is_raster
                else "Other layer"
            )
            if block_reason:
                type_tooltip += f"\n\nNot exportable:\n{block_reason}"
            type_item.setToolTip(type_tooltip)
            self.setItem(row, COL_TYPE, type_item)

            src_item = QTableWidgetItem(layer.name())
            src_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            src_item.setData(Qt.ItemDataRole.UserRole, layer.id())
            if block_reason:
                src_item.setToolTip(f"Not exportable:\n{block_reason}")
                src_item.setForeground(QBrush(QColor("#9a3412")))
                src_item.setIcon(
                    self.style().standardIcon(
                        QStyle.StandardPixmap.SP_MessageBoxWarning,
                    ),
                )
            self.setItem(row, COL_SOURCE, src_item)

            export_name = self._export_names.get(layer.id(), layer.name())
            exp_item = QTableWidgetItem(export_name)
            exp_item.setFlags(
                Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsSelectable
                | Qt.ItemFlag.ItemIsEditable,
            )
            exp_item.setData(Qt.ItemDataRole.UserRole, layer.id())
            self._apply_export_name_style(exp_item, export_name, layer.name())
            self.setItem(row, COL_EXPORT, exp_item)

            if self._show_format:
                formats = VECTOR_FORMATS if is_vector else RASTER_FORMATS
                combo = QComboBox()
                for label, _driver in formats:
                    combo.addItem(label)
                current_driver = self._format_overrides.get(layer.id(), "")
                for idx, (_label, driver) in enumerate(formats):
                    if driver == current_driver:
                        combo.setCurrentIndex(idx)
                        break
                lid = layer.id()
                combo.currentIndexChanged.connect(
                    lambda _idx, lid=lid, f=formats: self._on_format_changed(
                        lid,
                        f,
                    ),
                )
                self.setCellWidget(row, COL_FORMAT, combo)

            filt = self._filters.get(layer.id(), "")
            filt_item = QTableWidgetItem("\u26a1" if filt else "")
            filt_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            filt_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            filt_item.setData(Qt.ItemDataRole.UserRole, layer.id())
            if filt:
                filt_item.setToolTip(f"Filter:\n{filt}")
                filt_item.setForeground(QBrush(QColor("#e67e22")))
            self.setItem(row, COL_FILTER, filt_item)

            default_crs = layer.crs().authid() if layer.crs().isValid() else ""
            target_crs = self._target_crs.get(layer.id(), default_crs)
            crs_item = QTableWidgetItem(target_crs)
            crs_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            crs_item.setData(Qt.ItemDataRole.UserRole, layer.id())
            self._apply_crs_style(crs_item)
            self.setItem(row, COL_CRS, crs_item)

            if layer.id() in prev_selected:
                rows_to_reselect.append(row)

        self.blockSignals(False)
        for row in rows_to_reselect:
            self.selectRow(row)
        self._emit_selection_changed()

    def _on_format_changed(self, layer_id: str, formats: list[tuple[str, str]]) -> None:
        row = self._row_for_layer.get(layer_id)
        if row is None:
            return
        combo = self.cellWidget(row, COL_FORMAT)
        if combo is None:
            return
        idx = combo.currentIndex()
        if 0 <= idx < len(formats):
            driver = formats[idx][1]
            old = self._format_overrides.get(layer_id, "")
            if driver != old:
                self._format_overrides[layer_id] = driver
                self.format_changed.emit(layer_id, driver)

    def set_format_override(self, layer_id: str, driver: str) -> None:
        """Set the format override for a layer. Empty string means default (global)."""
        self._format_overrides[layer_id] = driver
        row = self._row_for_layer.get(layer_id)
        if row is None:
            return
        combo = self.cellWidget(row, COL_FORMAT)
        if combo is None:
            return
        layer = QgsProject.instance().mapLayer(layer_id)
        is_vector = isinstance(layer, QgsVectorLayer)
        formats = VECTOR_FORMATS if is_vector else RASTER_FORMATS
        for idx, (_label, d) in enumerate(formats):
            if d == driver:
                combo.blockSignals(True)
                combo.setCurrentIndex(idx)
                combo.blockSignals(False)
                break

    def get_format_override(self, layer_id: str) -> str:
        """Return the format override for a layer, or empty string for default."""
        return self._format_overrides.get(layer_id, "")

    def set_filter(self, layer_id: str, expression: str) -> None:
        """Set a filter expression badge for a specific layer."""
        self._filters[layer_id] = expression
        row = self._row_for_layer.get(layer_id)
        if row is not None:
            filt_item = self.item(row, COL_FILTER)
            if filt_item:
                has = bool(expression.strip())
                filt_item.setText("\u26a1" if has else "")
                filt_item.setToolTip(f"Filter:\n{expression}" if has else "")
                filt_item.setForeground(
                    QBrush(QColor("#e67e22") if has else QColor("#999999")),
                )

    def get_filters(self) -> dict[str, str]:
        """Return a copy of the current filter dict."""
        return dict(self._filters)

    def get_target_crs(self, layer_id: str) -> str:
        """Return the stored target CRS auth ID for a layer."""
        return self._target_crs.get(layer_id, "")

    def set_target_crs(self, layer_id: str, authid: str) -> None:
        """Update the displayed target CRS for a layer."""
        self._target_crs[layer_id] = authid
        row = self._row_for_layer.get(layer_id)
        if row is not None:
            crs_item = self.item(row, COL_CRS)
            if crs_item:
                self.blockSignals(True)
                crs_item.setText(authid)
                self._apply_crs_style(crs_item)
                self.blockSignals(False)

    def get_field_filter(self, layer_id: str) -> list[str] | None:
        """Return selected field names for a layer, or None for all fields."""
        return self._field_filters.get(layer_id)

    def set_field_filter(self, layer_id: str, field_names: list[str] | None) -> None:
        """Set which fields to include for a layer. None means all fields."""
        if field_names:
            self._field_filters[layer_id] = field_names
        elif layer_id in self._field_filters:
            del self._field_filters[layer_id]

    def export_warning(self, layer_id: str) -> str:
        return self._export_warnings.get(layer_id, "")

    def selected_layer_ids(self) -> list[str]:
        """Return list of selected layer IDs."""
        ids: list[str] = []
        model = self.selectionModel()
        if not model:
            return ids
        for index in model.selectedRows():
            lid = self._layer_id_for_row(index.row())
            if lid:
                ids.append(lid)
        return ids

    def check_all(self) -> None:
        self.selectAll()
        self._emit_selection_changed()

    def uncheck_all(self) -> None:
        self.clearSelection()
        self._emit_selection_changed()

    def get_selected_items(self) -> list[tuple[str, str]]:
        """Return (layer_id, export_name) tuples for selected rows."""
        result = []
        model = self.selectionModel()
        if not model:
            return result
        for index in sorted(model.selectedRows(), key=lambda x: x.row()):
            lid = self._layer_id_for_row(index.row())
            exp_item = self.item(index.row(), COL_EXPORT)
            name = exp_item.text().strip() if exp_item else ""
            if lid and name:
                result.append((lid, name))
        return result

    def reset_export_names(self) -> None:
        """Reset all export names back to source layer names."""
        self.blockSignals(True)
        for row in range(self.rowCount()):
            lid = self._layer_id_for_row(row)
            if not lid:
                continue
            layer = QgsProject.instance().mapLayer(lid)
            if layer is None:
                continue
            source_name = layer.name()
            self._export_names[lid] = source_name
            exp_item = self.item(row, COL_EXPORT)
            if exp_item:
                exp_item.setText(source_name)
                self._apply_export_name_style(exp_item, source_name, source_name)
        self.blockSignals(False)

    def get_export_name(self, layer_id: str) -> str | None:
        return self._export_names.get(layer_id)

    def set_active_layer(self, layer: QgsMapLayer) -> None:
        """Select and scroll to a specific layer row."""
        if not layer:
            return
        row = self._row_for_layer.get(layer.id())
        if row is not None:
            self.clearSelection()
            self.selectRow(row)
            self.scrollToItem(self.item(row, COL_SOURCE))
            self._emit_selection_changed()

    def count_filters(self) -> int:
        """Return the number of layers with non-empty filter expressions."""
        return sum(1 for v in self._filters.values() if v.strip())

    def _emit_selection_changed(self) -> None:
        self.selection_changed.emit(self.selected_layer_ids())

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        col = item.column()
        if col == COL_EXPORT:
            layer_id = item.data(Qt.ItemDataRole.UserRole)
            new_name = item.text().strip()
            if not layer_id:
                return
            self._export_names[layer_id] = new_name
            layer = QgsProject.instance().mapLayer(layer_id)
            self._apply_export_name_style(item, new_name, layer.name() if layer else "")
            self.export_name_changed.emit(layer_id, new_name)

    def _on_cell_clicked(self, row: int, col: int) -> None:
        if col != COL_CRS:
            return
        layer_id = self._layer_id_for_row(row)
        layer = QgsProject.instance().mapLayer(layer_id) if layer_id else None
        if layer is None:
            return

        crs_item = self.item(row, COL_CRS)
        current = crs_item.text().strip() if crs_item else ""
        if not current and layer.crs().isValid():
            current = layer.crs().authid()

        dlg = LayerSettingsDialog(
            layer_id,
            current,
            selected_fields=self._field_filters.get(layer_id),
            parent=self,
        )
        if dlg.exec():
            authid = dlg.crs_authid()
            self._target_crs[layer_id] = authid
            if crs_item:
                self.blockSignals(True)
                crs_item.setText(authid)
                self._apply_crs_style(crs_item)
                self.blockSignals(False)
            self.crs_changed.emit(layer_id, authid)

            fields = dlg.selected_field_names()
            if fields:
                self._field_filters[layer_id] = fields
            elif layer_id in self._field_filters:
                del self._field_filters[layer_id]

    def _layer_id_for_row(self, row: int) -> str | None:
        item = self.item(row, COL_SOURCE)
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _icon_for_layer(self, layer: QgsMapLayer) -> QIcon:
        if isinstance(layer, QgsVectorLayer):
            icon = QgsApplication.getThemeIcon("/mIconVector.svg")
            return (
                icon
                if not icon.isNull()
                else self.style().standardIcon(QStyle.StandardPixmap.SP_FileIcon)
            )
        if isinstance(layer, QgsRasterLayer):
            icon = QgsApplication.getThemeIcon("/mIconRaster.svg")
            return (
                icon
                if not icon.isNull()
                else self.style().standardIcon(QStyle.StandardPixmap.SP_DriveHDIcon)
            )
        return self.style().standardIcon(
            QStyle.StandardPixmap.SP_FileDialogDetailedView,
        )

    def _apply_export_name_style(
        self,
        item: QTableWidgetItem,
        export_name: str,
        source_name: str,
    ) -> None:
        f = item.font()
        if export_name != source_name:
            item.setForeground(QBrush(QColor("#2e7d32")))
            item.setBackground(QBrush(QColor()))
            f.setBold(True)
            f.setItalic(True)
            item.setToolTip("Custom export name")
        else:
            item.setForeground(QBrush(self.palette().color(QPalette.ColorRole.Text)))
            item.setBackground(QBrush(QColor()))
            f.setBold(False)
            f.setItalic(False)
            item.setToolTip("")
        item.setFont(f)

    def _apply_crs_style(self, item: QTableWidgetItem) -> None:
        value = item.text().strip()
        hint = " (click for settings)"
        if not value:
            item.setToolTip("Uses source layer CRS" + hint)
            item.setForeground(QBrush(self.palette().color(QPalette.ColorRole.Text)))
            return
        crs = QgsCoordinateReferenceSystem(value)
        if crs.isValid():
            item.setToolTip(f"Target CRS: {crs.authid()}" + hint)
            item.setForeground(QBrush(self.palette().color(QPalette.ColorRole.Text)))
        else:
            item.setToolTip("Invalid CRS" + hint)
            item.setForeground(QBrush(QColor("#b91c1c")))
