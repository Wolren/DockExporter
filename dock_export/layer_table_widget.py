"""
layer_table_widget.py  –  Editable layer table for the export dock.

Each row represents one layer with:
  Col 0 – Type (vector/raster icon)
  Col 1 – Source Name (read-only, live layer display name)
  Col 2 – Export Name (editable inline – NEVER touches the live layer)
  Col 3 – Filter (indicator badge)
  Col 4 – CRS (picked via native QGIS CRS selector)

Selection is row-based:
  * click anywhere on a row to select it
  * Shift/Ctrl selection works natively
  * selected rows are the rows exported

Export names are stored inside the table model itself; they are read by
the export engine at write time and injected into SaveVectorOptions.layerName.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtGui import QBrush, QColor, QIcon, QPalette
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QTableWidget,
    QTableWidgetItem,
    QStyle,
)

from qgis.core import (
    QgsApplication,
    QgsCoordinateReferenceSystem,
    QgsMapLayer,
    QgsProject,
    QgsRasterLayer,
    QgsVectorLayer,
)
from qgis.gui import QgsProjectionSelectionDialog

from .export_engine import layer_export_block_reason


# --------------------------------------------------------------------------- #
# Column indices                                                              #
# --------------------------------------------------------------------------- #
COL_TYPE   = 0
COL_SOURCE = 1
COL_EXPORT = 2
COL_FILTER = 3
COL_CRS    = 4
N_COLS     = 5


class LayerTableWidget(QTableWidget):
    """
    A QTableWidget that manages ExportSpec-like rows for the dock.

    Signals
    -------
    selection_changed(layer_ids: list[str])
        Emitted when the set of selected rows changes.
    export_name_changed(layer_id: str, new_name: str)
        Emitted when the user edits an Export Name cell.
    crs_changed(layer_id: str, authid: str)
        Emitted when the target CRS is changed from the CRS picker.
    """

    selection_changed = pyqtSignal(list)
    export_name_changed = pyqtSignal(str, str)
    crs_changed = pyqtSignal(str, str)

    def __init__(self, parent=None):
        super().__init__(0, N_COLS, parent)

        self._export_names: Dict[str, str] = {}
        self._filters: Dict[str, str] = {}
        self._target_crs: Dict[str, str] = {}
        self._export_warnings: Dict[str, str] = {}

        self._setup_header()
        self._setup_appearance()

        self.itemChanged.connect(self._on_item_changed)
        self.itemSelectionChanged.connect(self._emit_selection_changed)
        self.cellDoubleClicked.connect(self._on_cell_double_clicked)

    # ------------------------------------------------------------------ #
    # Setup                                                               #
    # ------------------------------------------------------------------ #

    def _setup_header(self) -> None:
        self.setHorizontalHeaderLabels([
            "", "Source Name", "Export Name", "Filter", "CRS"
        ])
        hh = self.horizontalHeader()
        hh.setSectionResizeMode(COL_TYPE,   QHeaderView.ResizeMode.Fixed)
        hh.setSectionResizeMode(COL_SOURCE, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(COL_EXPORT, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(COL_FILTER, QHeaderView.ResizeMode.Fixed)
        hh.setSectionResizeMode(COL_CRS,    QHeaderView.ResizeMode.Fixed)
        self.setColumnWidth(COL_TYPE, 34)
        self.setColumnWidth(COL_FILTER, 64)
        self.setColumnWidth(COL_CRS, 112)

    def _setup_appearance(self) -> None:
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked |
            QAbstractItemView.EditTrigger.EditKeyPressed |
            QAbstractItemView.EditTrigger.SelectedClicked
        )
        self.setAlternatingRowColors(True)
        self.verticalHeader().setVisible(False)
        self.setShowGrid(False)

    # ------------------------------------------------------------------ #
    # Public API – populate / refresh                                     #
    # ------------------------------------------------------------------ #

    def populate(
        self,
        layers: List[QgsMapLayer],
        type_filter: Optional[str] = None,
    ) -> None:
        """
        Rebuild the table from *layers*.

        Parameters
        ----------
        layers : list of QgsMapLayer
        type_filter : 'vector' | 'raster' | None (both)
        """
        prev_selected = set(self.selected_layer_ids())

        self.blockSignals(True)
        self.setRowCount(0)

        rows_to_reselect: List[int] = []

        for layer in layers:
            is_vector = isinstance(layer, QgsVectorLayer)
            is_raster = isinstance(layer, QgsRasterLayer)

            if type_filter == "vector" and not is_vector:
                continue
            if type_filter == "raster" and not is_raster:
                continue

            row = self.rowCount()
            self.insertRow(row)

            block_reason = layer_export_block_reason(layer)
            self._export_warnings[layer.id()] = block_reason

            # Col 0 – type icon
            type_item = QTableWidgetItem("")
            type_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            type_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            type_item.setData(Qt.ItemDataRole.UserRole, layer.id())
            type_item.setIcon(self._icon_for_layer(layer))
            type_tooltip = "Vector layer" if is_vector else "Raster layer" if is_raster else "Other layer"
            if block_reason:
                type_tooltip += f"\n\nNot exportable:\n{block_reason}"
            type_item.setToolTip(type_tooltip)
            self.setItem(row, COL_TYPE, type_item)

            # Col 1 – source name (read-only but selectable)
            src_item = QTableWidgetItem(layer.name())
            src_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            src_item.setData(Qt.ItemDataRole.UserRole, layer.id())
            if block_reason:
                src_item.setToolTip(f"Not exportable:\n{block_reason}")
                src_item.setForeground(QBrush(QColor("#9a3412")))
                src_item.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MessageBoxWarning))
            self.setItem(row, COL_SOURCE, src_item)

            # Col 2 – export name (editable)
            export_name = self._export_names.get(layer.id(), layer.name())
            exp_item = QTableWidgetItem(export_name)
            exp_item.setFlags(
                Qt.ItemFlag.ItemIsEnabled |
                Qt.ItemFlag.ItemIsSelectable |
                Qt.ItemFlag.ItemIsEditable
            )
            exp_item.setData(Qt.ItemDataRole.UserRole, layer.id())
            self._apply_export_name_style(exp_item, export_name, layer.name())
            self.setItem(row, COL_EXPORT, exp_item)

            # Col 3 – filter badge
            filt = self._filters.get(layer.id(), "")
            filt_item = QTableWidgetItem("⚡" if filt else "")
            filt_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            filt_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            filt_item.setData(Qt.ItemDataRole.UserRole, layer.id())
            if filt:
                filt_item.setToolTip(f"Filter:\n{filt}")
                filt_item.setForeground(QBrush(QColor("#e67e22")))
            self.setItem(row, COL_FILTER, filt_item)

            # Col 4 – target CRS (native CRS picker on double-click)
            default_crs = layer.crs().authid() if layer.crs().isValid() else ""
            target_crs = self._target_crs.get(layer.id(), default_crs)
            crs_item = QTableWidgetItem(target_crs)
            crs_item.setFlags(
                Qt.ItemFlag.ItemIsEnabled |
                Qt.ItemFlag.ItemIsSelectable
            )
            crs_item.setData(Qt.ItemDataRole.UserRole, layer.id())
            self._apply_crs_style(crs_item)
            self.setItem(row, COL_CRS, crs_item)

            if layer.id() in prev_selected:
                rows_to_reselect.append(row)

        self.blockSignals(False)

        for row in rows_to_reselect:
            self.selectRow(row)

        self._emit_selection_changed()

    # ------------------------------------------------------------------ #
    # External filter update                                              #
    # ------------------------------------------------------------------ #

    def set_filter(self, layer_id: str, expression: str) -> None:
        """Update the stored filter and refresh the filter badge."""
        self._filters[layer_id] = expression
        for row in range(self.rowCount()):
            if self._layer_id_for_row(row) == layer_id:
                filt_item = self.item(row, COL_FILTER)
                if filt_item:
                    has = bool(expression.strip())
                    filt_item.setText("⚡" if has else "")
                    if has:
                        filt_item.setToolTip(f"Filter:\n{expression}")
                        filt_item.setForeground(QBrush(QColor("#e67e22")))
                    else:
                        filt_item.setToolTip("")
                        filt_item.setForeground(QBrush(QColor("#999999")))
                break

    def get_filters(self) -> Dict[str, str]:
        return dict(self._filters)

    def get_target_crs(self, layer_id: str) -> str:
        return self._target_crs.get(layer_id, "")

    def set_target_crs(self, layer_id: str, authid: str) -> None:
        self._target_crs[layer_id] = authid
        for row in range(self.rowCount()):
            if self._layer_id_for_row(row) == layer_id:
                crs_item = self.item(row, COL_CRS)
                if crs_item:
                    self.blockSignals(True)
                    crs_item.setText(authid)
                    self._apply_crs_style(crs_item)
                    self.blockSignals(False)
                break

    def export_warning(self, layer_id: str) -> str:
        return self._export_warnings.get(layer_id, "")

    # ------------------------------------------------------------------ #
    # Selection helpers                                                   #
    # ------------------------------------------------------------------ #

    def selected_layer_ids(self) -> List[str]:
        """Return layer IDs of selected rows."""
        ids: List[str] = []
        model = self.selectionModel()
        if not model:
            return ids

        for index in model.selectedRows():
            row = index.row()
            lid = self._layer_id_for_row(row)
            if lid:
                ids.append(lid)
        return ids

    def checked_layer_ids(self) -> List[str]:
        """
        Compatibility wrapper for old code.
        Now returns selected layer IDs.
        """
        return self.selected_layer_ids()

    def check_all(self) -> None:
        """
        Compatibility wrapper for old code.
        Now selects all rows.
        """
        self.selectAll()
        self._emit_selection_changed()

    def uncheck_all(self) -> None:
        """
        Compatibility wrapper for old code.
        Now clears selection.
        """
        self.clearSelection()
        self._emit_selection_changed()

    # ------------------------------------------------------------------ #
    # Export spec read-out                                                #
    # ------------------------------------------------------------------ #

    def get_checked_items(self) -> List[Tuple[str, str]]:
        """
        Compatibility wrapper for old code.

        Return (layer_id, export_name) for every selected row.
        Export name comes from the editable col, NEVER the live layer name.
        """
        return self.get_selected_items()

    def get_selected_items(self) -> List[Tuple[str, str]]:
        """
        Return (layer_id, export_name) for every selected row.
        """
        result = []
        model = self.selectionModel()
        if not model:
            return result

        for index in sorted(model.selectedRows(), key=lambda x: x.row()):
            row = index.row()
            lid = self._layer_id_for_row(row)
            exp_item = self.item(row, COL_EXPORT)
            export_name = exp_item.text().strip() if exp_item else ""
            if lid and export_name:
                result.append((lid, export_name))
        return result

    def reset_export_names(self) -> None:
        """Reset all export names to match their source layer names."""
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

    def get_export_name(self, layer_id: str) -> Optional[str]:
        return self._export_names.get(layer_id)

    def set_active_layer(self, layer: QgsMapLayer) -> None:
        """
        Select a specific layer row in the table and scroll to it.
        """
        if not layer:
            return

        self.clearSelection()
        for row in range(self.rowCount()):
            if self._layer_id_for_row(row) == layer.id():
                self.selectRow(row)
                self.scrollToItem(self.item(row, COL_SOURCE))
                break

        self._emit_selection_changed()

    # ------------------------------------------------------------------ #
    # Signal handlers                                                     #
    # ------------------------------------------------------------------ #

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
            src_name = layer.name() if layer else ""
            self._apply_export_name_style(item, new_name, src_name)

            self.export_name_changed.emit(layer_id, new_name)
        elif col == COL_CRS:
            layer_id = item.data(Qt.ItemDataRole.UserRole)
            if not layer_id:
                return
            value = item.text().strip()
            self._target_crs[layer_id] = value
            self._apply_crs_style(item)

    def _on_cell_double_clicked(self, row: int, col: int) -> None:
        if col != COL_CRS:
            return

        layer_id = self._layer_id_for_row(row)
        if not layer_id:
            return

        layer = QgsProject.instance().mapLayer(layer_id)
        if layer is None:
            return

        crs_item = self.item(row, COL_CRS)
        current_authid = crs_item.text().strip() if crs_item else ""
        if not current_authid and layer.crs().isValid():
            current_authid = layer.crs().authid()

        dlg = QgsProjectionSelectionDialog(self)
        current_crs = QgsCoordinateReferenceSystem(current_authid)
        if current_crs.isValid():
            dlg.setCrs(current_crs)

        if dlg.exec():
            selected_crs = dlg.crs()
            if not selected_crs.isValid():
                return
            authid = selected_crs.authid()
            if not authid:
                authid = selected_crs.toOgcWmsCrs()
            self._target_crs[layer_id] = authid
            if crs_item:
                self.blockSignals(True)
                crs_item.setText(authid)
                self._apply_crs_style(crs_item)
                self.blockSignals(False)
            self.crs_changed.emit(layer_id, authid)

    # ------------------------------------------------------------------ #
    # Internal helpers                                                    #
    # ------------------------------------------------------------------ #

    def _layer_id_for_row(self, row: int) -> Optional[str]:
        item = self.item(row, COL_SOURCE)
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _icon_for_layer(self, layer: QgsMapLayer) -> QIcon:
        if isinstance(layer, QgsVectorLayer):
            icon = QgsApplication.getThemeIcon("/mIconVector.svg")
            if not icon.isNull():
                return icon
            return self.style().standardIcon(QStyle.StandardPixmap.SP_FileIcon)

        if isinstance(layer, QgsRasterLayer):
            icon = QgsApplication.getThemeIcon("/mIconRaster.svg")
            if not icon.isNull():
                return icon
            return self.style().standardIcon(QStyle.StandardPixmap.SP_DriveHDIcon)

        return self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogDetailedView)

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
        if not value:
            item.setToolTip("Uses source layer CRS")
            item.setForeground(QBrush(self.palette().color(QPalette.ColorRole.Text)))
            return

        crs = QgsCoordinateReferenceSystem(value)
        if crs.isValid():
            item.setToolTip(f"Target CRS: {crs.authid()}")
            item.setForeground(QBrush(self.palette().color(QPalette.ColorRole.Text)))
        else:
            item.setToolTip("Invalid CRS (use form like EPSG:4326)")
            item.setForeground(QBrush(QColor("#b91c1c")))
