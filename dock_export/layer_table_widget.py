"""
layer_table_widget.py  –  Editable layer table for the export dock.

Each row represents one layer with:
  Col 0 – Source Name (read-only, live layer display name)
  Col 1 – Export Name (editable inline – NEVER touches the live layer)
  Col 2 – Filter (indicator badge)
  Col 3 – Type (Vector / Raster)

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
from qgis.PyQt.QtGui import QBrush, QColor
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QTableWidget,
    QTableWidgetItem,
)

from qgis.core import QgsMapLayer, QgsProject, QgsRasterLayer, QgsVectorLayer


# --------------------------------------------------------------------------- #
# Column indices                                                              #
# --------------------------------------------------------------------------- #
COL_SOURCE = 0
COL_EXPORT = 1
COL_FILTER = 2
COL_TYPE   = 3
N_COLS     = 4


class LayerTableWidget(QTableWidget):
    """
    A QTableWidget that manages ExportSpec-like rows for the dock.

    Signals
    -------
    selection_changed(layer_ids: list[str])
        Emitted when the set of selected rows changes.
    export_name_changed(layer_id: str, new_name: str)
        Emitted when the user edits an Export Name cell.
    """

    selection_changed = pyqtSignal(list)
    export_name_changed = pyqtSignal(str, str)

    def __init__(self, parent=None):
        super().__init__(0, N_COLS, parent)

        self._export_names: Dict[str, str] = {}
        self._filters: Dict[str, str] = {}

        self._setup_header()
        self._setup_appearance()

        self.itemChanged.connect(self._on_item_changed)
        self.itemSelectionChanged.connect(self._emit_selection_changed)

    # ------------------------------------------------------------------ #
    # Setup                                                               #
    # ------------------------------------------------------------------ #

    def _setup_header(self) -> None:
        self.setHorizontalHeaderLabels([
            "Source Name", "Export Name", "Filter", "Type"
        ])
        hh = self.horizontalHeader()
        hh.setSectionResizeMode(COL_SOURCE, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(COL_EXPORT, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(COL_FILTER, QHeaderView.ResizeMode.Fixed)
        hh.setSectionResizeMode(COL_TYPE,   QHeaderView.ResizeMode.Fixed)
        self.setColumnWidth(COL_FILTER, 64)
        self.setColumnWidth(COL_TYPE, 72)

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

            # Col 0 – source name (read-only but selectable)
            src_item = QTableWidgetItem(layer.name())
            src_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            src_item.setData(Qt.ItemDataRole.UserRole, layer.id())
            self.setItem(row, COL_SOURCE, src_item)

            # Col 1 – export name (editable)
            export_name = self._export_names.get(layer.id(), layer.name())
            exp_item = QTableWidgetItem(export_name)
            exp_item.setFlags(
                Qt.ItemFlag.ItemIsEnabled |
                Qt.ItemFlag.ItemIsSelectable |
                Qt.ItemFlag.ItemIsEditable
            )
            exp_item.setData(Qt.ItemDataRole.UserRole, layer.id())

            if export_name != layer.name():
                exp_item.setForeground(QBrush(QColor("#1565C0")))
                f = exp_item.font()
                f.setBold(True)
                exp_item.setFont(f)

            self.setItem(row, COL_EXPORT, exp_item)

            # Col 2 – filter badge
            filt = self._filters.get(layer.id(), "")
            filt_item = QTableWidgetItem("⚡" if filt else "")
            filt_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            filt_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            filt_item.setData(Qt.ItemDataRole.UserRole, layer.id())
            if filt:
                filt_item.setToolTip(f"Filter:\n{filt}")
                filt_item.setForeground(QBrush(QColor("#e67e22")))
            self.setItem(row, COL_FILTER, filt_item)

            # Col 3 – type
            type_str = "Vector" if is_vector else "Raster"
            type_item = QTableWidgetItem(type_str)
            type_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            type_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            type_item.setData(Qt.ItemDataRole.UserRole, layer.id())
            color = QColor("#1b5e20") if is_vector else QColor("#4a148c")
            type_item.setForeground(QBrush(color))
            self.setItem(row, COL_TYPE, type_item)

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

            if new_name != src_name:
                item.setForeground(QBrush(QColor("#1565C0")))
                f = item.font()
                f.setBold(True)
                item.setFont(f)
            else:
                item.setForeground(QBrush(QColor()))
                f = item.font()
                f.setBold(False)
                item.setFont(f)

            self.export_name_changed.emit(layer_id, new_name)

    # ------------------------------------------------------------------ #
    # Internal helpers                                                    #
    # ------------------------------------------------------------------ #

    def _layer_id_for_row(self, row: int) -> Optional[str]:
        item = self.item(row, COL_SOURCE)
        return item.data(Qt.ItemDataRole.UserRole) if item else None