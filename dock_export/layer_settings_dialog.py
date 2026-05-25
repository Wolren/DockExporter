"""Per-layer settings dialog: CRS, encoding, selected features, field selection, aliases, geometry, and metadata."""

import encodings.aliases

from qgis.core import (
    QgsApplication,
    QgsCoordinateReferenceSystem,
    QgsField,
    QgsProject,
    QgsRasterLayer,
    QgsRectangle,
    QgsVectorFileWriter,
    QgsVectorLayer,
)
from qgis.gui import QgsExtentGroupBox, QgsProjectionSelectionWidget
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

# Ordered list of type names shown in the type override combo
_TYPE_NAMES = [
    "Integer",
    "Integer64",
    "Double",
    "DecimalNumber",
    "String",
    "Date",
    "DateTime",
    "Time",
    "Boolean",
    "Binary",
]


class _NoWheelComboBox(QComboBox):
    def wheelEvent(self, e):
        e.ignore()


class LayerSettingsDialog(QDialog):
    """Per-layer export settings: CRS, encoding, selected features, field selection with type overrides, aliases, metadata, and geometry options."""

    _COL_CHECK = 0
    _COL_NAME = 1
    _COL_EXPORT_NAME = 2
    _COL_TYPE = 3

    def __init__(
        self,
        layer_id: str,
        current_crs_authid: str,
        selected_fields: list[str] | None = None,
        field_type_overrides: dict[str, str] | None = None,
        current_encoding: str = "UTF-8",
        save_selected_only: bool = False,
        use_aliases_for_names: bool = False,
        persist_layer_metadata: bool = False,
        geometry_type_override: str = "",
        force_z: bool = False,
        force_multi: bool = False,
        filter_extent: str = "",
        datasource_options: list[str] | None = None,
        layer_options: list[str] | None = None,
        raster_resolution_x: float = 0.0,
        raster_resolution_y: float = 0.0,
        raster_nodata: str = "",
        field_export_names: dict[str, str] | None = None,
        skip_attribute_creation: bool = False,
        include_constraints: bool = False,
        description: str = "",
        layer_fid: str = "",
        geometry_name: str = "",
        identifier: str = "",
        spatial_index: str = "",
        parent=None,
    ):
        super().__init__(parent)
        self._layer_id = layer_id
        self._crs_authid = current_crs_authid
        self._selected_fields: list[str] = selected_fields or []
        self._field_type_overrides: dict[str, str] = field_type_overrides or {}
        self._current_encoding = current_encoding
        self._save_selected_only = save_selected_only
        self._use_aliases_for_names = use_aliases_for_names
        self._persist_layer_metadata = persist_layer_metadata
        self._geometry_type_override = geometry_type_override
        self._force_z = force_z
        self._force_multi = force_multi
        self._filter_extent = filter_extent
        self._datasource_options: list[str] = datasource_options or []
        self._layer_options: list[str] = layer_options or []
        self._raster_resolution_x = raster_resolution_x
        self._raster_resolution_y = raster_resolution_y
        self._raster_nodata = raster_nodata
        self._field_export_names: dict[str, str] = field_export_names or {}
        self._skip_attr_creation = skip_attribute_creation
        self._include_constraints = include_constraints
        self._description = description
        self._layer_fid = layer_fid
        self._geometry_name = geometry_name
        self._identifier = identifier
        self._spatial_index = spatial_index
        self._type_combos: dict[str, QComboBox] = {}
        self._field_table: QTableWidget | None = None

        self.setWindowTitle("Layer Export Settings")
        self.setMinimumSize(600, 500)
        self.resize(640, 720)
        self._build_ui()

    def _build_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content_widget = QWidget()
        layout = QVBoxLayout(content_widget)

        layer = QgsProject.instance().mapLayer(self._layer_id)
        layer_name = layer.name() if layer else "(unknown)"
        layout.addWidget(QLabel(f"<b>{layer_name}</b>"))

        crs_row = QHBoxLayout()
        crs_row.addWidget(QLabel("CRS"))
        self._crs_widget = QgsProjectionSelectionWidget()
        crs = QgsCoordinateReferenceSystem(self._crs_authid)
        if crs.isValid():
            self._crs_widget.setCrs(crs)
        else:
            self._crs_widget.setCrs(QgsCoordinateReferenceSystem())
        crs_row.addWidget(self._crs_widget, 1)
        layout.addLayout(crs_row)

        enc_row = QHBoxLayout()
        enc_row.addWidget(QLabel("Encoding"))
        self._encoding_combo = _NoWheelComboBox()
        try:
            encodings = QgsVectorFileWriter.availableEncodings()
        except AttributeError:
            try:
                from qgis.PyQt.QtCore import QTextCodec

                raw = QTextCodec.availableCodecs()
                encodings = []
                for c in raw:
                    if isinstance(c, str):
                        encodings.append(c)
                    elif isinstance(c, bytes):
                        try:
                            encodings.append(c.decode("utf-8"))
                        except UnicodeDecodeError:
                            encodings.append(c.decode("latin-1"))
                    else:
                        try:
                            encodings.append(bytes(c).decode("utf-8"))
                        except (TypeError, AttributeError):
                            encodings.append(str(c))
                encodings.sort()
            except (ImportError, AttributeError):
                canon = set(encodings.aliases.aliases.values())
                encodings = sorted(c for c in canon if not c.startswith("_"))
        self._encoding_combo.addItems(encodings)
        idx = self._encoding_combo.findText(self._current_encoding)
        if idx >= 0:
            self._encoding_combo.setCurrentIndex(idx)
        enc_row.addWidget(self._encoding_combo)
        layout.addLayout(enc_row)

        if isinstance(layer, QgsVectorLayer):
            self._selected_only_cb = QCheckBox("Save only selected features")
            self._selected_only_cb.setChecked(self._save_selected_only)
            layout.addWidget(self._selected_only_cb)

            self._fields_group = QGroupBox(
                "Select fields to export and their export options",
            )
            self._fields_group.setCheckable(True)
            self._fields_group.setChecked(True)
            group_layout = QVBoxLayout(self._fields_group)

            self._fields_content = QWidget()
            content_layout = QVBoxLayout(self._fields_content)
            content_layout.setContentsMargins(0, 0, 0, 0)

            self._field_table = QTableWidget(0, 4)
            self._field_table.setHorizontalHeaderLabels(
                ["", "Name", "Export name", "Type"],
            )
            self._field_table.verticalHeader().setVisible(False)
            self._field_table.setMinimumHeight(150)
            hh = self._field_table.horizontalHeader()
            hh.setSectionResizeMode(self._COL_CHECK, QHeaderView.ResizeMode.Fixed)
            hh.setSectionResizeMode(self._COL_NAME, QHeaderView.ResizeMode.Stretch)
            hh.setSectionResizeMode(
                self._COL_EXPORT_NAME, QHeaderView.ResizeMode.Stretch
            )
            hh.setSectionResizeMode(self._COL_TYPE, QHeaderView.ResizeMode.Fixed)
            self._field_table.setColumnWidth(self._COL_CHECK, 28)
            self._field_table.setColumnWidth(self._COL_TYPE, 140)

            all_checked = not self._selected_fields
            for f in layer.fields():
                fname = f.name()
                row = self._field_table.rowCount()
                self._field_table.insertRow(row)

                check_item = QTableWidgetItem("")
                check_item.setFlags(
                    Qt.ItemFlag.ItemIsEnabled
                    | Qt.ItemFlag.ItemIsSelectable
                    | Qt.ItemFlag.ItemIsUserCheckable,
                )
                check_item.setCheckState(
                    (
                        Qt.CheckState.Checked
                        if (all_checked or fname in self._selected_fields)
                        else Qt.CheckState.Unchecked
                    ),
                )
                self._field_table.setItem(row, self._COL_CHECK, check_item)

                name_item = QTableWidgetItem(fname)
                name_item.setFlags(
                    Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable,
                )
                self._field_table.setItem(row, self._COL_NAME, name_item)

                if fname in self._field_export_names:
                    export_name = self._field_export_names[fname]
                elif self._use_aliases_for_names and f.alias():
                    export_name = f.alias()
                else:
                    export_name = fname
                exp_item = QTableWidgetItem(export_name)
                exp_item.setFlags(
                    Qt.ItemFlag.ItemIsEnabled
                    | Qt.ItemFlag.ItemIsSelectable
                    | Qt.ItemFlag.ItemIsEditable,
                )
                self._field_table.setItem(row, self._COL_EXPORT_NAME, exp_item)

                combo = _NoWheelComboBox()
                combo.addItems(_TYPE_NAMES)
                override = self._field_type_overrides.get(fname)
                preferred = override or self._field_type_str(f)
                idx = combo.findText(preferred)
                if idx >= 0:
                    combo.setCurrentIndex(idx)
                self._type_combos[fname] = combo
                self._field_table.setCellWidget(row, self._COL_TYPE, combo)

            content_layout.addWidget(self._field_table)

            btn_row = QHBoxLayout()
            select_all_btn = QPushButton("Select All")
            select_all_btn.clicked.connect(self._select_all_fields)
            btn_row.addWidget(select_all_btn)
            deselect_all_btn = QPushButton("Deselect All")
            deselect_all_btn.clicked.connect(self._deselect_all_fields)
            btn_row.addWidget(deselect_all_btn)
            content_layout.addLayout(btn_row)

            self._use_aliases_cb = QCheckBox("Use aliases for export name")
            self._use_aliases_cb.setChecked(self._use_aliases_for_names)
            self._use_aliases_cb.toggled.connect(self._on_use_aliases_toggled)
            content_layout.addWidget(self._use_aliases_cb)

            self._skip_attr_cb = QCheckBox("Skip attribute creation")
            self._skip_attr_cb.setChecked(self._skip_attr_creation)
            content_layout.addWidget(self._skip_attr_cb)

            self._include_constraints_cb = QCheckBox("Include field constraints")
            self._include_constraints_cb.setChecked(self._include_constraints)
            content_layout.addWidget(self._include_constraints_cb)

            group_layout.addWidget(self._fields_content)
            self._fields_group.toggled.connect(self._fields_content.setVisible)
            layout.addWidget(self._fields_group)

        self._persist_metadata_cb = QCheckBox("Persist layer metadata")
        self._persist_metadata_cb.setChecked(self._persist_layer_metadata)
        layout.addWidget(self._persist_metadata_cb)

        if isinstance(layer, QgsVectorLayer):
            geom_group = QGroupBox("Geometry")
            geom_layout = QVBoxLayout(geom_group)

            geom_type_row = QHBoxLayout()
            geom_type_row.addWidget(QLabel("Geometry type"))
            self._geom_type_combo = _NoWheelComboBox()
            self._geom_type_combo.addItem("Automatic", "")
            self._geom_type_combo.addItem(
                QgsApplication.getThemeIcon("/mIconPointLayer.svg"),
                "Point",
                "Point",
            )
            self._geom_type_combo.addItem(
                QgsApplication.getThemeIcon("/mIconLineLayer.svg"),
                "LineString",
                "LineString",
            )
            self._geom_type_combo.addItem(
                QgsApplication.getThemeIcon("/mIconPolygonLayer.svg"),
                "Polygon",
                "Polygon",
            )
            self._geom_type_combo.addItem("GeometryCollection", "GeometryCollection")
            self._geom_type_combo.addItem(
                QgsApplication.getThemeIcon("/mIconTableLayer.svg"),
                "No geometry",
                "NoGeometry",
            )
            idx = self._geom_type_combo.findData(self._geometry_type_override)
            if idx >= 0:
                self._geom_type_combo.setCurrentIndex(idx)
            self._geom_type_combo.currentIndexChanged.connect(
                self._on_geom_type_changed,
            )
            self._on_geom_type_changed(self._geom_type_combo.currentIndex())
            geom_type_row.addWidget(self._geom_type_combo)
            geom_layout.addLayout(geom_type_row)

            self._force_z_cb = QCheckBox("Include Z dimension")
            self._force_z_cb.setChecked(self._force_z)
            geom_layout.addWidget(self._force_z_cb)

            self._force_multi_cb = QCheckBox("Force multi-type")
            self._force_multi_cb.setChecked(self._force_multi)
            geom_layout.addWidget(self._force_multi_cb)

            self._on_geom_type_changed(self._geom_type_combo.currentIndex())
            layout.addWidget(geom_group)

        has_extent_override = bool(self._filter_extent)
        extent_group = QgsExtentGroupBox(self)
        extent_group.setCheckable(True)
        extent_group.setChecked(has_extent_override)
        extent_group.setTitleBase(
            "Extent" if has_extent_override else "Extent (current: none)",
        )
        extent_group.toggled.connect(
            lambda checked: extent_group.setTitleBase(
                "Extent" if checked else "Extent (current: none)",
            ),
        )
        if layer is not None:
            extent_group.setOriginalExtent(layer.extent(), layer.crs())
            extent_group.setCurrentExtent(layer.extent(), layer.crs())
            extent_group.setOutputCrs(layer.crs())
            if has_extent_override:
                parts = self._filter_extent.split(",")
                if len(parts) == 4:
                    try:
                        rect = QgsRectangle(
                            float(parts[0]),
                            float(parts[1]),
                            float(parts[2]),
                            float(parts[3]),
                        )
                        extent_group.setOutputExtentFromUser(rect)
                    except (ValueError, TypeError):
                        pass
        layout.addWidget(extent_group)
        self._extent_group = extent_group

        layer_opts_group = QGroupBox("Layer Options")
        layer_opts_layout = QVBoxLayout(layer_opts_group)

        _LAYER_OPT_LABEL_WIDTH = 140

        def _make_layer_opt_row(label: str, widget: QWidget) -> QHBoxLayout:
            row = QHBoxLayout()
            lbl = QLabel(label)
            lbl.setFixedWidth(_LAYER_OPT_LABEL_WIDTH)
            row.addWidget(lbl)
            row.addWidget(widget, 1)
            return row

        self._layer_description_edit = QLineEdit()
        self._layer_description_edit.setText(self._description)
        layer_opts_layout.addLayout(
            _make_layer_opt_row("DESCRIPTION", self._layer_description_edit),
        )

        self._layer_fid_edit = QLineEdit()
        self._layer_fid_edit.setPlaceholderText("fid")
        self._layer_fid_edit.setText(self._layer_fid)
        layer_opts_layout.addLayout(
            _make_layer_opt_row("FID", self._layer_fid_edit),
        )

        self._layer_geom_name_edit = QLineEdit()
        self._layer_geom_name_edit.setPlaceholderText("geom")
        self._layer_geom_name_edit.setText(self._geometry_name)
        layer_opts_layout.addLayout(
            _make_layer_opt_row("GEOMETRY_NAME", self._layer_geom_name_edit),
        )

        self._layer_identifier_edit = QLineEdit()
        self._layer_identifier_edit.setText(self._identifier)
        layer_opts_layout.addLayout(
            _make_layer_opt_row("IDENTIFIER", self._layer_identifier_edit),
        )

        si_row = QHBoxLayout()
        si_lbl = QLabel("SPATIAL_INDEX")
        si_lbl.setFixedWidth(140)
        si_row.addWidget(si_lbl)
        self._layer_si_combo = _NoWheelComboBox()
        self._layer_si_combo.addItems(["YES", "", "NO"])
        if not self._spatial_index:
            self._layer_si_combo.setCurrentIndex(0)
        else:
            idx = self._layer_si_combo.findText(self._spatial_index)
            if idx >= 0:
                self._layer_si_combo.setCurrentIndex(idx)
        si_row.addWidget(self._layer_si_combo)
        si_row.addStretch()
        layer_opts_layout.addLayout(si_row)

        layout.addWidget(layer_opts_group)

        gdal_group = QGroupBox("Custom Options")
        gdal_layout = QVBoxLayout(gdal_group)

        gdal_layout.addWidget(QLabel("Data source"))
        self._ds_options_table = QTableWidget(0, 2)
        self._ds_options_table.setHorizontalHeaderLabels(["Name", "Value"])
        self._ds_options_table.horizontalHeader().setStretchLastSection(True)
        self._populate_opt_table(self._ds_options_table, self._datasource_options)
        ds_btn_row = QHBoxLayout()
        ds_add = QPushButton("+")
        ds_add.clicked.connect(lambda: self._add_opt_row(self._ds_options_table))
        ds_remove = QPushButton("\u2212")
        ds_remove.clicked.connect(lambda: self._remove_opt_row(self._ds_options_table))
        ds_btn_row.addWidget(ds_add)
        ds_btn_row.addWidget(ds_remove)
        ds_btn_row.addStretch()
        gdal_layout.addWidget(self._ds_options_table)
        gdal_layout.addLayout(ds_btn_row)

        gdal_layout.addWidget(QLabel("Layer"))
        self._lyr_options_table = QTableWidget(0, 2)
        self._lyr_options_table.setHorizontalHeaderLabels(["Name", "Value"])
        self._lyr_options_table.horizontalHeader().setStretchLastSection(True)
        self._populate_opt_table(self._lyr_options_table, self._layer_options)
        lyr_btn_row = QHBoxLayout()
        lyr_add = QPushButton("+")
        lyr_add.clicked.connect(lambda: self._add_opt_row(self._lyr_options_table))
        lyr_remove = QPushButton("\u2212")
        lyr_remove.clicked.connect(
            lambda: self._remove_opt_row(self._lyr_options_table),
        )
        lyr_btn_row.addWidget(lyr_add)
        lyr_btn_row.addWidget(lyr_remove)
        lyr_btn_row.addStretch()
        gdal_layout.addWidget(self._lyr_options_table)
        gdal_layout.addLayout(lyr_btn_row)

        layout.addWidget(gdal_group)

        if isinstance(layer, QgsRasterLayer):
            raster_group = QGroupBox("Raster options")
            raster_layout = QVBoxLayout(raster_group)

            res_row = QHBoxLayout()
            res_row.addWidget(QLabel("Resolution X"))
            self._res_x_spin = QDoubleSpinBox()
            self._res_x_spin.setRange(0, 1e9)
            self._res_x_spin.setDecimals(6)
            self._res_x_spin.setValue(self._raster_resolution_x)
            self._res_x_spin.setSpecialValueText("Auto")
            res_row.addWidget(self._res_x_spin)
            res_row.addWidget(QLabel("Y"))
            self._res_y_spin = QDoubleSpinBox()
            self._res_y_spin.setRange(0, 1e9)
            self._res_y_spin.setDecimals(6)
            self._res_y_spin.setValue(self._raster_resolution_y)
            self._res_y_spin.setSpecialValueText("Auto")
            res_row.addWidget(self._res_y_spin)
            raster_layout.addLayout(res_row)

            nodata_row = QHBoxLayout()
            nodata_row.addWidget(QLabel("Nodata value"))
            self._nodata_edit = QLineEdit()
            self._nodata_edit.setText(self._raster_nodata)
            self._nodata_edit.setPlaceholderText("Leave empty for default")
            nodata_row.addWidget(self._nodata_edit)
            raster_layout.addLayout(nodata_row)

            layout.addWidget(raster_group)

        scroll.setWidget(content_widget)
        main_layout.addWidget(scroll, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        main_layout.addWidget(buttons)

    @staticmethod
    def _field_type_str(f: QgsField) -> str:
        """Return a human-readable type string for a QgsField."""
        return f.typeName()

    def _on_geom_type_changed(self, index: int) -> None:
        data = self._geom_type_combo.itemData(index)
        is_no_geom = data == "NoGeometry"
        if hasattr(self, "_force_z_cb"):
            self._force_z_cb.setEnabled(not is_no_geom)
        if hasattr(self, "_force_multi_cb"):
            self._force_multi_cb.setEnabled(not is_no_geom)

    def _select_all_fields(self) -> None:
        if self._field_table is None:
            return
        for row in range(self._field_table.rowCount()):
            item = self._field_table.item(row, self._COL_CHECK)
            if item:
                item.setCheckState(Qt.CheckState.Checked)

    def _deselect_all_fields(self) -> None:
        if self._field_table is None:
            return
        for row in range(self._field_table.rowCount()):
            item = self._field_table.item(row, self._COL_CHECK)
            if item:
                item.setCheckState(Qt.CheckState.Unchecked)

    def _on_use_aliases_toggled(self, checked: bool) -> None:
        if self._field_table is None:
            return
        layer = QgsProject.instance().mapLayer(self._layer_id)
        if not isinstance(layer, QgsVectorLayer):
            return
        for row in range(self._field_table.rowCount()):
            name_item = self._field_table.item(row, self._COL_NAME)
            exp_item = self._field_table.item(row, self._COL_EXPORT_NAME)
            if name_item is None or exp_item is None:
                continue
            fname = name_item.text()
            field = layer.fields().field(fname)
            if not field.isValid():
                continue
            if checked and field.alias():
                exp_item.setText(field.alias())
            else:
                exp_item.setText(fname)

    @staticmethod
    def _populate_opt_table(table: QTableWidget, entries: list[str]) -> None:
        for entry in entries:
            parts = entry.split("=", 1)
            row = table.rowCount()
            table.insertRow(row)
            table.setItem(row, 0, QTableWidgetItem(parts[0]))
            table.setItem(row, 1, QTableWidgetItem(parts[1] if len(parts) > 1 else ""))

    @staticmethod
    def _add_opt_row(table: QTableWidget) -> None:
        row = table.rowCount()
        table.insertRow(row)
        table.setItem(row, 0, QTableWidgetItem(""))
        table.setItem(row, 1, QTableWidgetItem(""))

    @staticmethod
    def _remove_opt_row(table: QTableWidget) -> None:
        rows = set()
        for item in table.selectedItems():
            rows.add(item.row())
        for r in sorted(rows, reverse=True):
            table.removeRow(r)

    @staticmethod
    def _read_opt_table(table: QTableWidget) -> list[str]:
        result: list[str] = []
        for row in range(table.rowCount()):
            name = table.item(row, 0)
            value = table.item(row, 1)
            n = name.text().strip() if name else ""
            v = value.text().strip() if value else ""
            if n:
                result.append(f"{n}={v}")
        return result

    def crs_authid(self) -> str:
        """Return the currently selected CRS auth ID from the native widget."""
        crs = self._crs_widget.crs()
        return crs.authid() if crs.isValid() else ""

    def encoding(self) -> str:
        """Return the selected encoding."""
        return self._encoding_combo.currentText()

    def save_selected_only(self) -> bool:
        """Return whether to export only selected features."""
        if not hasattr(self, "_selected_only_cb"):
            return False
        return self._selected_only_cb.isChecked()

    def use_aliases_for_export_name(self) -> bool:
        """Return whether to use field aliases as export column names."""
        return (
            self._use_aliases_cb.isChecked()
            if hasattr(self, "_use_aliases_cb")
            else False
        )

    def persist_layer_metadata(self) -> bool:
        """Return whether to persist layer metadata in the output."""
        return self._persist_metadata_cb.isChecked()

    def filter_extent(self) -> str:
        """Return the spatial extent filter as 'xmin,ymin,xmax,ymax' or empty string if not set."""
        if not hasattr(self, "_extent_group"):
            return ""
        if not self._extent_group.isChecked():
            return ""
        if (
            self._extent_group.extentState()
            == QgsExtentGroupBox.ExtentState.OriginalExtent
        ):
            return ""
        rect = self._extent_group.outputExtent()
        if rect.isNull():
            return ""
        return (
            f"{rect.xMinimum()},{rect.yMinimum()},{rect.xMaximum()},{rect.yMaximum()}"
        )

    def datasource_options(self) -> list[str]:
        """Return the list of 'KEY=VALUE' datasource creation options."""
        return self._read_opt_table(self._ds_options_table)

    def layer_options(self) -> list[str]:
        """Return the list of 'KEY=VALUE' layer creation options."""
        return self._read_opt_table(self._lyr_options_table)

    def geometry_type_override(self) -> str:
        """Return the selected geometry type override (empty string = automatic)."""
        if not hasattr(self, "_geom_type_combo"):
            return ""
        return self._geom_type_combo.currentData() or ""

    def force_z_dimension(self) -> bool:
        """Return whether to force Z dimension in the output geometry."""
        if not hasattr(self, "_force_z_cb"):
            return False
        return self._force_z_cb.isChecked()

    def force_multi_type(self) -> bool:
        """Return whether to force multi-type geometry in the output."""
        if not hasattr(self, "_force_multi_cb"):
            return False
        return self._force_multi_cb.isChecked()

    def selected_field_names(self) -> list[str]:
        """Return the list of checked field names."""
        names = []
        if self._field_table is None:
            return names
        for row in range(self._field_table.rowCount()):
            check = self._field_table.item(row, self._COL_CHECK)
            name = self._field_table.item(row, self._COL_NAME)
            if check and name and check.checkState() == Qt.CheckState.Checked:
                names.append(name.text())
        return names

    def raster_resolution_x(self) -> float:
        if not hasattr(self, "_res_x_spin"):
            return 0.0
        return self._res_x_spin.value()

    def raster_resolution_y(self) -> float:
        if not hasattr(self, "_res_y_spin"):
            return 0.0
        return self._res_y_spin.value()

    def raster_nodata(self) -> str:
        if not hasattr(self, "_nodata_edit"):
            return ""
        return self._nodata_edit.text().strip()

    def skip_attribute_creation(self) -> bool:
        if not hasattr(self, "_skip_attr_cb"):
            return False
        return self._skip_attr_cb.isChecked()

    def include_constraints(self) -> bool:
        if not hasattr(self, "_include_constraints_cb"):
            return False
        return self._include_constraints_cb.isChecked()

    def description(self) -> str:
        return (
            self._layer_description_edit.text().strip()
            if hasattr(self, "_layer_description_edit")
            else ""
        )

    def layer_fid(self) -> str:
        return (
            self._layer_fid_edit.text().strip()
            if hasattr(self, "_layer_fid_edit")
            else ""
        )

    def geometry_name(self) -> str:
        return (
            self._layer_geom_name_edit.text().strip()
            if hasattr(self, "_layer_geom_name_edit")
            else ""
        )

    def identifier(self) -> str:
        return (
            self._layer_identifier_edit.text().strip()
            if hasattr(self, "_layer_identifier_edit")
            else ""
        )

    def spatial_index(self) -> str:
        if not hasattr(self, "_layer_si_combo"):
            return ""
        return self._layer_si_combo.currentText()

    def export_field_names(self) -> dict[str, str]:
        """Return dict of field name → export name for all checked fields."""
        names: dict[str, str] = {}
        if self._field_table is None:
            return names
        for row in range(self._field_table.rowCount()):
            check = self._field_table.item(row, self._COL_CHECK)
            name = self._field_table.item(row, self._COL_NAME)
            exp = self._field_table.item(row, self._COL_EXPORT_NAME)
            if check and name and exp and check.checkState() == Qt.CheckState.Checked:
                fname = name.text()
                ename = exp.text().strip()
                if ename and ename != fname:
                    names[fname] = ename
        return names

    def field_type_overrides(self) -> dict[str, str]:
        """Return dict of field name → overridden type name for all checked fields."""
        overrides: dict[str, str] = {}
        if self._field_table is None:
            return overrides
        for row in range(self._field_table.rowCount()):
            check = self._field_table.item(row, self._COL_CHECK)
            name = self._field_table.item(row, self._COL_NAME)
            if check and name and check.checkState() == Qt.CheckState.Checked:
                combo = self._field_table.cellWidget(row, self._COL_TYPE)
                if combo:
                    overrides[name.text()] = combo.currentText()
        return overrides
