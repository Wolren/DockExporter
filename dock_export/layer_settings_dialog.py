"""Per-layer settings dialog: target CRS + attribute field selection."""

from typing import Dict, List, Optional

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)
from qgis.core import QgsCoordinateReferenceSystem, QgsProject, QgsVectorLayer
from qgis.gui import QgsProjectionSelectionDialog


class LayerSettingsDialog(QDialog):
    """Dialog for per-layer export settings: target CRS and attribute field selection.

    Opens from double-clicking the CRS column in the layer table.
    """

    def __init__(
        self,
        layer_id: str,
        current_crs_authid: str,
        selected_fields: Optional[List[str]] = None,
        parent=None,
    ):
        super().__init__(parent)
        self._layer_id = layer_id
        self._crs_authid = current_crs_authid
        self._selected_fields: List[str] = selected_fields or []
        self._field_checkboxes: Dict[str, QCheckBox] = {}

        self.setWindowTitle("Layer Export Settings")
        self.setMinimumWidth(400)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        layer = QgsProject.instance().mapLayer(self._layer_id)
        layer_name = layer.name() if layer else "(unknown)"
        layout.addWidget(QLabel(f"<b>{layer_name}</b>"))

        # CRS row
        crs_row = QHBoxLayout()
        crs_row.addWidget(QLabel("Target CRS:"))
        crs_label = QLabel(self._crs_authid or "Source CRS (no override)")
        crs_label.setStyleSheet("color:#555;")
        crs_row.addWidget(crs_label)
        change_btn = QPushButton("Change...")
        change_btn.clicked.connect(lambda: self._pick_crs(crs_label))
        crs_row.addWidget(change_btn)
        crs_row.addStretch()
        layout.addLayout(crs_row)

        # Field selection (vector only)
        if isinstance(layer, QgsVectorLayer):
            layout.addWidget(QLabel("Attribute fields to include:"))
            self._field_table = QTableWidget(0, 1)
            self._field_table.setHorizontalHeaderLabels(["Include"])
            self._field_table.verticalHeader().setVisible(False)
            hh = self._field_table.horizontalHeader()
            hh.setStretchLastSection(True)

            all_names = [f.name() for f in layer.fields()]
            select_all = QCheckBox("Select all")
            select_all.setChecked(True)
            select_all.toggled.connect(self._on_select_all_toggled)
            layout.addWidget(select_all)

            for fname in all_names:
                row = self._field_table.rowCount()
                self._field_table.insertRow(row)
                cb = QCheckBox(fname)
                cb.setChecked(
                    not self._selected_fields or fname in self._selected_fields
                )
                self._field_checkboxes[fname] = cb
                item = QTableWidgetItem("")
                item.setFlags(Qt.ItemFlag.ItemIsNoFlags)
                self._field_table.setItem(row, 0, item)
                self._field_table.setCellWidget(row, 0, cb)

            layout.addWidget(self._field_table)

        # Buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _pick_crs(self, label: QLabel) -> None:
        dlg = QgsProjectionSelectionDialog(self)
        crs = QgsCoordinateReferenceSystem(self._crs_authid)
        if crs.isValid():
            dlg.setCrs(crs)
        if dlg.exec():
            selected = dlg.crs()
            if selected.isValid():
                self._crs_authid = selected.authid()
                label.setText(self._crs_authid)

    def _on_select_all_toggled(self, checked: bool) -> None:
        for cb in self._field_checkboxes.values():
            cb.setChecked(checked)

    def crs_authid(self) -> str:
        return self._crs_authid

    def selected_field_names(self) -> List[str]:
        return [name for name, cb in self._field_checkboxes.items() if cb.isChecked()]
