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
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QGroupBox,
    QHeaderView,
    QSizePolicy,
    QStyle,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from ._formats import get_raster_formats, get_vector_formats
from .export_engine import layer_export_block_reason
from .layer_settings_dialog import LayerSettingsDialog

COL_TYPE = 0
COL_SOURCE = 1
COL_EXPORT = 2
COL_FORMAT = 3
COL_FILTER = 4
COL_CRS = 5
N_COLS = 6

VECTOR_FORMATS = get_vector_formats(include_default=False)
RASTER_FORMATS = get_raster_formats(include_default=False)
FORMAT_DEFAULT_KEY = ""


class _NoWheelComboBox(QComboBox):
    def wheelEvent(self, e):
        e.ignore()


class _FormatOverrideDialog(QDialog):
    """Multi-select format picker for a single layer with a Default checkbox."""

    def __init__(
        self,
        layer_id: str,
        current: set[str],
        parent=None,
    ):
        super().__init__(parent)
        layer = QgsProject.instance().mapLayer(layer_id)
        is_vector = isinstance(layer, QgsVectorLayer)

        self.setWindowTitle("Layer export formats")
        layout = QVBoxLayout(self)

        has_override = bool(current)

        self._default_cb = QCheckBox("Default (globally set)")
        self._default_cb.setChecked(not has_override)
        layout.addWidget(self._default_cb)

        self._checks: dict[str, QCheckBox] = {}
        fmt_list = VECTOR_FORMATS if is_vector else RASTER_FORMATS
        group = QGroupBox()
        grid = QGridLayout(group)
        for idx, (label, driver) in enumerate(fmt_list):
            cb = QCheckBox(label)
            cb.setChecked(driver in current if has_override else False)
            self._checks[driver] = cb
            grid.addWidget(cb, idx // 3, idx % 3)
        layout.addWidget(group)

        btn_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
        )
        btn_box.accepted.connect(self.accept)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

    def selected_drivers(self) -> set[str]:
        if self._default_cb.isChecked():
            return set()
        return {d for d, cb in self._checks.items() if cb.isChecked()}


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
        self._format_overrides: dict[str, set[str]] = {}
        self._global_vector_formats: set[str] = {"GPKG"}
        self._global_raster_formats: set[str] = {"GTiff"}
        self._filters: dict[str, str] = {}
        self._target_crs: dict[str, str] = {}
        self._field_filters: dict[str, list[str]] = {}
        self._field_type_overrides: dict[str, dict[str, str]] = {}
        self._encodings: dict[str, str] = {}
        self._save_selected_only: dict[str, bool] = {}
        self._use_aliases: dict[str, bool] = {}
        self._persist_metadata: dict[str, bool] = {}
        self._geometry_type_override: dict[str, str] = {}
        self._force_z: dict[str, bool] = {}
        self._force_multi: dict[str, bool] = {}
        self._filter_extents: dict[str, str] = {}
        self._datasource_options: dict[str, list[str]] = {}
        self._layer_options: dict[str, list[str]] = {}
        self._raster_resolution_x: dict[str, float] = {}
        self._raster_resolution_y: dict[str, float] = {}
        self._raster_nodata: dict[str, str] = {}
        self._skip_attr_creation: dict[str, bool] = {}
        self._include_constraints: dict[str, bool] = {}
        self._layer_description: dict[str, str] = {}
        self._layer_fid: dict[str, str] = {}
        self._layer_geom_name: dict[str, str] = {}
        self._layer_identifier: dict[str, str] = {}
        self._layer_spatial_index: dict[str, str] = {}
        self._field_export_names: dict[str, dict[str, str]] = {}
        self._export_warnings: dict[str, str] = {}
        self._row_for_layer: dict[str, int] = {}

        self._setup_header()
        self._setup_appearance()
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
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
                drivers = self._format_overrides.get(layer.id(), set())
                fmt_item = QTableWidgetItem(
                    self._format_display_text(drivers, is_vector),
                )
                fmt_item.setFlags(
                    Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable,
                )
                fmt_item.setData(Qt.ItemDataRole.UserRole, layer.id())
                self.setItem(row, COL_FORMAT, fmt_item)

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

    def _format_display_text(self, drivers: set[str], is_vector: bool = True) -> str:
        """Return a short label summarizing format drivers, or 'Default' when using global defaults."""
        if not drivers:
            return "Default"
        labels = {d: lbl for lbl, d in VECTOR_FORMATS}
        labels.update({d: lbl for lbl, d in RASTER_FORMATS})
        names = [labels.get(d, d) for d in sorted(drivers)]
        return ", ".join(names)

    def set_format_override(self, layer_id: str, drivers: set[str]) -> None:
        """Set the format override for a layer. Empty set means default (global)."""
        old = self._format_overrides.get(layer_id)
        if drivers:
            self._format_overrides[layer_id] = drivers
        elif layer_id in self._format_overrides:
            del self._format_overrides[layer_id]
        if old != self._format_overrides.get(layer_id):
            self.format_changed.emit(
                layer_id,
                ",".join(sorted(drivers)),
            )

    def get_format_override(self, layer_id: str) -> set[str]:
        """Return the format override drivers for a layer, or empty set for default."""
        return self._format_overrides.get(layer_id, set())

    def _update_format_display(self, layer_id: str) -> None:
        """Refresh the format cell text for a layer."""
        row = self._row_for_layer.get(layer_id)
        if row is None:
            return
        item = self.item(row, COL_FORMAT)
        if item is None:
            return
        layer = QgsProject.instance().mapLayer(layer_id)
        is_vector = isinstance(layer, QgsVectorLayer)
        drivers = self._format_overrides.get(layer_id, set())
        item.setText(self._format_display_text(drivers, is_vector))

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

    def get_field_type_overrides(self, layer_id: str) -> dict[str, str] | None:
        """Return field name → overridden type name for a layer, or None."""
        return self._field_type_overrides.get(layer_id)

    def get_field_export_names(self, layer_id: str) -> dict[str, str] | None:
        """Return field name → export name mapping for a layer, or None."""
        return self._field_export_names.get(layer_id)

    def get_encoding(self, layer_id: str) -> str:
        """Return the encoding for a layer, or 'UTF-8' as default."""
        return self._encodings.get(layer_id, "UTF-8")

    def get_save_selected_only(self, layer_id: str) -> bool:
        """Return whether to export only selected features for a layer."""
        return self._save_selected_only.get(layer_id, False)

    def get_use_aliases(self, layer_id: str) -> bool:
        """Return whether to use field aliases for export column names."""
        return self._use_aliases.get(layer_id, False)

    def get_persist_metadata(self, layer_id: str) -> bool:
        """Return whether to persist layer metadata in the output."""
        return self._persist_metadata.get(layer_id, False)

    def get_geometry_type_override(self, layer_id: str) -> str:
        """Return the geometry type override for a layer (empty string = automatic)."""
        return self._geometry_type_override.get(layer_id, "")

    def get_force_z(self, layer_id: str) -> bool:
        """Return whether to force Z dimension in the output geometry."""
        return self._force_z.get(layer_id, False)

    def get_force_multi(self, layer_id: str) -> bool:
        """Return whether to force multi-type geometry in the output."""
        return self._force_multi.get(layer_id, False)

    def get_filter_extent(self, layer_id: str) -> str:
        """Return the spatial extent filter as 'xmin,ymin,xmax,ymax' or empty string."""
        return self._filter_extents.get(layer_id, "")

    def get_raster_resolution_x(self, layer_id: str) -> float:
        return self._raster_resolution_x.get(layer_id, 0.0)

    def get_raster_resolution_y(self, layer_id: str) -> float:
        return self._raster_resolution_y.get(layer_id, 0.0)

    def get_raster_nodata(self, layer_id: str) -> str:
        return self._raster_nodata.get(layer_id, "")

    def get_skip_attribute_creation(self, layer_id: str) -> bool:
        return self._skip_attr_creation.get(layer_id, False)

    def get_include_constraints(self, layer_id: str) -> bool:
        return self._include_constraints.get(layer_id, False)

    def get_datasource_options(self, layer_id: str) -> list[str] | None:
        """Return datasource creation options for a layer, or None."""
        val = self._datasource_options.get(layer_id)
        return val if val else None

    def get_layer_options(self, layer_id: str) -> list[str] | None:
        """Return layer creation options for a layer, or None."""
        val = self._layer_options.get(layer_id)
        return val if val else None

    def get_description(self, layer_id: str) -> str:
        return self._layer_description.get(layer_id, "")

    def get_layer_fid(self, layer_id: str) -> str:
        return self._layer_fid.get(layer_id, "")

    def get_geometry_name(self, layer_id: str) -> str:
        return self._layer_geom_name.get(layer_id, "")

    def get_identifier(self, layer_id: str) -> str:
        return self._layer_identifier.get(layer_id, "")

    def get_spatial_index(self, layer_id: str) -> str:
        return self._layer_spatial_index.get(layer_id, "")

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

    def set_global_formats(
        self,
        vector_formats: set[str],
        raster_formats: set[str],
    ) -> None:
        """Set the global default format sets used when no per-layer override exists."""
        self._global_vector_formats = vector_formats
        self._global_raster_formats = raster_formats
        for layer_id in self._row_for_layer:
            self._update_format_display(layer_id)

    def _on_format_clicked(self, row: int) -> None:
        layer_id = self._layer_id_for_row(row)
        if not layer_id:
            return
        current = self._format_overrides.get(layer_id, set())
        dlg = _FormatOverrideDialog(layer_id, current, self)
        if dlg.exec():
            new_drivers = dlg.selected_drivers()
            if new_drivers:
                self._format_overrides[layer_id] = new_drivers
            elif layer_id in self._format_overrides:
                del self._format_overrides[layer_id]
            self._update_format_display(layer_id)
            self.format_changed.emit(
                layer_id,
                ",".join(sorted(new_drivers)),
            )

    def _on_cell_clicked(self, row: int, col: int) -> None:
        if col == COL_FORMAT and self._show_format:
            self._on_format_clicked(row)
            return
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
            field_type_overrides=self._field_type_overrides.get(layer_id),
            current_encoding=self._encodings.get(layer_id, "UTF-8"),
            save_selected_only=self._save_selected_only.get(layer_id, False),
            use_aliases_for_names=self._use_aliases.get(layer_id, False),
            persist_layer_metadata=self._persist_metadata.get(layer_id, False),
            geometry_type_override=self._geometry_type_override.get(layer_id, ""),
            force_z=self._force_z.get(layer_id, False),
            force_multi=self._force_multi.get(layer_id, False),
            filter_extent=self._filter_extents.get(layer_id, ""),
            datasource_options=self._datasource_options.get(layer_id),
            layer_options=self._layer_options.get(layer_id),
            raster_resolution_x=self._raster_resolution_x.get(layer_id, 0.0),
            raster_resolution_y=self._raster_resolution_y.get(layer_id, 0.0),
            raster_nodata=self._raster_nodata.get(layer_id, ""),
            skip_attribute_creation=self._skip_attr_creation.get(layer_id, False),
            include_constraints=self._include_constraints.get(layer_id, False),
            field_export_names=self._field_export_names.get(layer_id),
            description=self._layer_description.get(layer_id, ""),
            layer_fid=self._layer_fid.get(layer_id, ""),
            geometry_name=self._layer_geom_name.get(layer_id, ""),
            identifier=self._layer_identifier.get(layer_id, ""),
            spatial_index=self._layer_spatial_index.get(layer_id, "YES"),
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

            types = dlg.field_type_overrides()
            if types:
                self._field_type_overrides[layer_id] = types
            elif layer_id in self._field_type_overrides:
                del self._field_type_overrides[layer_id]

            self._encodings[layer_id] = dlg.encoding()
            self._save_selected_only[layer_id] = dlg.save_selected_only()
            self._use_aliases[layer_id] = dlg.use_aliases_for_export_name()
            self._persist_metadata[layer_id] = dlg.persist_layer_metadata()
            self._geometry_type_override[layer_id] = dlg.geometry_type_override()
            self._force_z[layer_id] = dlg.force_z_dimension()
            self._force_multi[layer_id] = dlg.force_multi_type()
            self._filter_extents[layer_id] = dlg.filter_extent()
            ds_opts = dlg.datasource_options()
            self._datasource_options[layer_id] = ds_opts if ds_opts else []
            lyr_opts = dlg.layer_options()
            self._layer_options[layer_id] = lyr_opts if lyr_opts else []

            self._raster_resolution_x[layer_id] = dlg.raster_resolution_x()
            self._raster_resolution_y[layer_id] = dlg.raster_resolution_y()
            self._raster_nodata[layer_id] = dlg.raster_nodata()

            self._skip_attr_creation[layer_id] = dlg.skip_attribute_creation()
            self._include_constraints[layer_id] = dlg.include_constraints()

            exp_names = dlg.export_field_names()
            if exp_names:
                self._field_export_names[layer_id] = exp_names
            elif layer_id in self._field_export_names:
                del self._field_export_names[layer_id]

            self._layer_description[layer_id] = dlg.description()
            self._layer_fid[layer_id] = dlg.layer_fid()
            self._layer_geom_name[layer_id] = dlg.geometry_name()
            self._layer_identifier[layer_id] = dlg.identifier()
            self._layer_spatial_index[layer_id] = dlg.spatial_index()

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
            return
        crs = QgsCoordinateReferenceSystem(value)
        if crs.isValid():
            item.setToolTip(f"Target CRS: {crs.authid()}" + hint)
        else:
            item.setToolTip("Invalid CRS" + hint)
            item.setForeground(QBrush(QColor("#b91c1c")))
