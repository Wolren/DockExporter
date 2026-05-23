"""Per-layer settings dialog: target CRS + attribute field selection."""

from typing import Dict, List, Optional

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)
from qgis.core import QgsCoordinateReferenceSystem, QgsField, QgsProject, QgsVectorLayer
from qgis.gui import QgsProjectionSelectionDialog


class LayerSettingsDialog(QDialog):
    """Dialog for per-layer export settings: target CRS and attribute field selection."""

    _COL_CHECK = 0
    _COL_NAME = 1
    _COL_TYPE = 2

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
        self.setMinimumWidth(420)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        layer = QgsProject.instance().mapLayer(self._layer_id)
        layer_name = layer.name() if layer else "(unknown)"
        layout.addWidget(QLabel(f"<b>{layer_name}</b>"))

        # CRS row
        crs_row = QHBoxLayout()
        crs_row.addWidget(QLabel("Target CRS:"))
        self._crs_label = QLabel(
            self._crs_authid if self._crs_authid else "Source CRS (no override)"
        )
        self._crs_label.setStyleSheet("color:#555;")
        crs_row.addWidget(self._crs_label)
        change_btn = QPushButton("Change...")
        change_btn.clicked.connect(self._pick_crs)
        crs_row.addWidget(change_btn)
        crs_row.addStretch()
        layout.addLayout(crs_row)

        # Field selection (vector only)
        if isinstance(layer, QgsVectorLayer):
            layout.addWidget(QLabel("Attribute fields to include:"))

            self._field_table = QTableWidget(0, 3)
            self._field_table.setHorizontalHeaderLabels(["", "Name", "Type"])
            self._field_table.verticalHeader().setVisible(False)
            hh = self._field_table.horizontalHeader()
            hh.setSectionResizeMode(self._COL_CHECK, QHeaderView.ResizeMode.Fixed)
            hh.setSectionResizeMode(self._COL_NAME, QHeaderView.ResizeMode.Stretch)
            hh.setSectionResizeMode(self._COL_TYPE, QHeaderView.ResizeMode.Fixed)
            self._field_table.setColumnWidth(self._COL_CHECK, 28)
            self._field_table.setColumnWidth(self._COL_TYPE, 100)
            self._field_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)

            all_checked = not self._selected_fields
            for f in layer.fields():
                fname = f.name()
                row = self._field_table.rowCount()
                self._field_table.insertRow(row)

                check_item = QTableWidgetItem("")
                check_item.setFlags(
                    Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
                )
                check_item.setCheckState(
                    Qt.CheckState.Checked
                    if (all_checked or fname in self._selected_fields)
                    else Qt.CheckState.Unchecked
                )
                self._field_table.setItem(row, self._COL_CHECK, check_item)

                name_item = QTableWidgetItem(fname)
                name_item.setFlags(
                    Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
                )
                self._field_table.setItem(row, self._COL_NAME, name_item)

                type_item = QTableWidgetItem(self._field_type_str(f))
                type_item.setFlags(
                    Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
                )
                type_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self._field_table.setItem(row, self._COL_TYPE, type_item)

            layout.addWidget(self._field_table)

        # Buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @staticmethod
    def _field_type_str(f: QgsField) -> str:
        type_name = f.typeName()
        if f.length() > 0:
            return f"{type_name}({f.length()})"
        return type_name

    def _pick_crs(self) -> None:
        dlg = QgsProjectionSelectionDialog(self)
        crs = QgsCoordinateReferenceSystem(self._crs_authid)
        if crs.isValid():
            dlg.setCrs(crs)
        if dlg.exec():
            selected = dlg.crs()
            if selected.isValid():
                self._crs_authid = selected.authid()
                self._crs_label.setText(self._crs_authid)

    def crs_authid(self) -> str:
        return self._crs_authid

    def selected_field_names(self) -> List[str]:
        names = []
        for row in range(self._field_table.rowCount()):
            check = self._field_table.item(row, self._COL_CHECK)
            name = self._field_table.item(row, self._COL_NAME)
            if check and name and check.checkState() == Qt.CheckState.Checked:
                names.append(name.text())
        return names
