"""Main export UI with Single Files, GeoPackage, and History tabs. Builds ExportSpec list from table state."""

from __future__ import annotations

import json
import os
import time
from contextlib import suppress
from datetime import datetime

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsProject,
    QgsRectangle,
    QgsRasterLayer,
    QgsSettings,
    QgsVectorLayer,
)
from qgis.gui import QgsExtentGroupBox
from qgis.PyQt.QtCore import QThread
from qgis.PyQt.QtGui import QTextCursor
from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from .export_engine import ExportResult, layer_export_block_reason
from .export_worker import ExportWorker
from ._formats import get_raster_formats, get_vector_formats
from .layer_table_widget import LayerTableWidget
from .models import ExportSpec, StyleMode
from .project_export_tab import ProjectExportTab
from .sql_filter_widget import SQLFilterDialog

SETTINGS_ROOT = "DockExport"

VECTOR_FORMAT_DEFS = get_vector_formats(include_default=False)
RASTER_FORMAT_DEFS = get_raster_formats(include_default=False)


class FormatDialog(QDialog):
    """Modal dialog for selecting export formats."""

    def __init__(
        self,
        vector_selected: set[str],
        raster_selected: set[str],
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Select export formats")
        self.setMinimumWidth(550)

        layout = QVBoxLayout(self)

        vec_group = QGroupBox("Vector formats")
        vec_grid = QGridLayout(vec_group)
        self._vec_checks: dict[str, QCheckBox] = {}
        for idx, (label, driver) in enumerate(VECTOR_FORMAT_DEFS):
            cb = QCheckBox(label)
            cb.setChecked(driver in vector_selected)
            self._vec_checks[driver] = cb
            vec_grid.addWidget(cb, idx // 5, idx % 5)
        layout.addWidget(vec_group)

        ras_group = QGroupBox("Raster formats")
        ras_grid = QGridLayout(ras_group)
        self._ras_checks: dict[str, QCheckBox] = {}
        for idx, (label, driver) in enumerate(RASTER_FORMAT_DEFS):
            cb = QCheckBox(label)
            cb.setChecked(driver in raster_selected)
            self._ras_checks[driver] = cb
            ras_grid.addWidget(cb, idx // 5, idx % 5)
        layout.addWidget(ras_group)

        btn_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
        )
        btn_box.accepted.connect(self.accept)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

    def get_vector_selected(self) -> set[str]:
        return {d for d, cb in self._vec_checks.items() if cb.isChecked()}

    def get_raster_selected(self) -> set[str]:
        return {d for d, cb in self._ras_checks.items() if cb.isChecked()}


class ExportWidget(QWidget):
    """Tabbed export UI embedded in the dock. Builds ExportSpecs from table state."""

    def __init__(self, iface, parent=None):
        """Build the UI, load persisted settings, populate layer tables, and connect project signals."""
        super().__init__(parent)
        self.iface = iface
        self._filters: dict[str, str] = {}
        self._target_crs: dict[str, str] = {}
        self._filter_dialog = None
        self._log_entries: list[str] = []
        self._vector_selected: set[str] = {"GPKG"}
        self._raster_selected: set[str] = {"GTiff"}
        self._global_extent_coords: str = ""
        self._global_extent_crs: str = ""

        self._build_ui()
        self._load_settings()
        self._refresh_layers()
        self._connect_project_signals()

    @staticmethod
    def _sanitize_name(name: str) -> str:
        """Replace filesystem-unsafe characters with underscore."""
        for ch in r'\/:*?"<>|':
            name = name.replace(ch, "_")
        return name

    def _build_ui(self) -> None:
        """Build the main layout: tabs, layer count label, progress bar, status, and action buttons."""
        root = QVBoxLayout(self)
        root.setSpacing(6)
        root.setContentsMargins(6, 6, 6, 6)

        self._tabs = QTabWidget()
        self._tabs.addTab(self._build_single_tab(), "Single files")
        self._tabs.addTab(self._build_gpkg_tab(), "GeoPackage")
        self._tabs.addTab(self._build_project_tab(), "Project Export")
        self._tabs.addTab(self._build_log_tab(), "History")
        self._tabs.currentChanged.connect(self._on_tab_changed)
        root.addWidget(self._tabs)

        self._layer_count_label = QLabel("")
        self._layer_count_label.setStyleSheet(
            "font-size:9pt; color:#555; padding:2px 0;",
        )
        root.addWidget(self._layer_count_label)

        self._progress = QProgressBar()
        self._progress.setVisible(False)
        root.addWidget(self._progress)

        self._status = QLabel("")
        self._status.setWordWrap(True)
        self._status.setStyleSheet("font-size:9pt; color:#555;")
        root.addWidget(self._status)

        self._btn_widget = QWidget()
        self._btn_row = QHBoxLayout(self._btn_widget)
        self._btn_row.addStretch()

        self._reset_names_btn = QPushButton("Reset Names")
        self._reset_names_btn.setToolTip("Reset export names to source layer names")
        self._reset_names_btn.clicked.connect(self._reset_export_names)
        self._btn_row.addWidget(self._reset_names_btn)

        self._filter_btn = QPushButton("Set Filters")
        self._filter_btn.setToolTip("Set per-layer QGIS expression filters")
        self._filter_btn.clicked.connect(self._open_filter_dialog)
        self._btn_row.addWidget(self._filter_btn)

        self._reset_all_btn = QPushButton("Reset All")
        self._reset_all_btn.setToolTip(
            "Reset names, filters, CRS, format overrides, and settings",
        )
        self._reset_all_btn.clicked.connect(self._reset_all)
        self._btn_row.addWidget(self._reset_all_btn)

        self._export_btn = QPushButton("Export")
        self._export_btn.setStyleSheet("font-weight:bold; padding:5px 18px;")
        self._export_btn.clicked.connect(self._do_export)
        self._btn_row.addWidget(self._export_btn)

        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.setVisible(False)
        self._cancel_btn.setStyleSheet(
            "background:#c0392b; color:white; font-weight:bold; padding:5px 18px;",
        )
        self._cancel_btn.clicked.connect(self._cancel_export)
        self._btn_row.addWidget(self._cancel_btn)

        root.addWidget(self._btn_widget)

    def _build_log_tab(self) -> QWidget:
        """Build the History tab with a read-only log view and Clear button."""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(0, 0, 0, 0)

        self._log_view = QTextBrowser()
        self._log_view.setReadOnly(True)
        self._log_view.setOpenExternalLinks(False)
        self._log_view.document().setMaximumBlockCount(500)
        self._log_view.setStyleSheet(
            "font-size:8pt; font-family:monospace;",
        )
        layout.addWidget(self._log_view)

        log_btn_row = QHBoxLayout()
        log_btn_row.addStretch()
        clear_log_btn = QPushButton("Clear Log")
        clear_log_btn.clicked.connect(self._clear_log)
        log_btn_row.addWidget(clear_log_btn)
        layout.addLayout(log_btn_row)

        return tab

    def _clear_log(self) -> None:
        """Clear the history log view and the internal entry list."""
        self._log_view.clear()
        self._log_entries.clear()
        self._log_view.document().clear()

    def _build_single_tab(self) -> QWidget:
        """Build the Single Files tab with layer table, select buttons, output config, and format options."""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(6)

        self._single_table = LayerTableWidget()
        self._single_table.crs_changed.connect(self._on_target_crs_changed)
        self._single_table.selection_changed.connect(self._update_export_button_state)
        layout.addWidget(self._single_table)

        sel_row = QHBoxLayout()
        all_btn = QPushButton("Select all")
        all_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        all_btn.clicked.connect(self._single_table.check_all)
        sel_row.addWidget(all_btn, 1)
        none_btn = QPushButton("Deselect all")
        none_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        none_btn.clicked.connect(self._single_table.uncheck_all)
        sel_row.addWidget(none_btn, 1)
        refresh_btn = QPushButton("Refresh")
        refresh_btn.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )
        refresh_btn.clicked.connect(self._refresh_layers)
        sel_row.addWidget(refresh_btn, 1)
        layout.addLayout(sel_row)

        self._fmt_row = QHBoxLayout()
        self._fmt_row.addWidget(QLabel("Formats:"))
        self._fmt_btn = QPushButton()
        self._fmt_btn.clicked.connect(self._configure_formats)
        self._fmt_row.addWidget(self._fmt_btn)
        self._fmt_row.addStretch()
        self._extent_btn = QPushButton()
        self._extent_btn.setMaximumWidth(200)
        self._extent_btn.clicked.connect(self._set_global_extent)
        self._fmt_row.addWidget(self._extent_btn)
        layout.addLayout(self._fmt_row)

        out_group = QGroupBox("Output")
        out_layout = QVBoxLayout(out_group)

        dir_row = QHBoxLayout()
        self._single_dir_edit = QLineEdit()
        self._single_dir_edit.setPlaceholderText("Select output directory...")
        self._single_dir_edit.textChanged.connect(self._update_export_button_state)
        dir_row.addWidget(self._single_dir_edit)
        browse = QPushButton("...")
        browse.setMaximumWidth(36)
        browse.clicked.connect(self._browse_single_dir)
        dir_row.addWidget(browse)
        out_layout.addLayout(dir_row)

        style_row = QHBoxLayout()
        style_row.addWidget(QLabel("Style:"))
        self._single_style_combo = QComboBox()
        self._single_style_combo.addItems(
            ["None", "QML", "SLD", "Both", "Embed in GPKG"],
        )
        self._single_style_combo.setCurrentIndex(1)
        style_row.addWidget(self._single_style_combo)
        style_row.addStretch()
        out_layout.addLayout(style_row)

        naming_row = QHBoxLayout()
        self._naming_template_edit = QLineEdit()
        self._naming_template_edit.setPlaceholderText("{layer_name}")
        self._naming_template_edit.setToolTip(
            "Placeholders: {layer_name}, {date}, {time}, {crs}, {datetime}",
        )
        naming_row.addWidget(QLabel("Name pattern:"))
        naming_row.addWidget(self._naming_template_edit)
        hint_btn = QPushButton("?")
        hint_btn.setFixedWidth(24)
        hint_btn.setToolTip("Show available placeholders")
        hint_btn.clicked.connect(self._show_naming_hint)
        naming_row.addWidget(hint_btn)
        apply_name_btn = QPushButton("Apply")
        apply_name_btn.setToolTip(
            "Apply naming pattern to all export names in the table",
        )
        apply_name_btn.clicked.connect(self._apply_naming_template)
        naming_row.addWidget(apply_name_btn)
        out_layout.addLayout(naming_row)

        self._single_replace_cb = QCheckBox("Replace source in project after export")
        self._single_replace_cb.setToolTip(
            "Repoints the project layer to the new file; display name unchanged",
        )
        out_layout.addWidget(self._single_replace_cb)

        self._single_add_to_project_cb = QCheckBox("Add exported files to project")
        self._single_add_to_project_cb.setToolTip(
            "Load exported files as new layers in the project",
        )
        out_layout.addWidget(self._single_add_to_project_cb)

        self._single_keep_name_cb = QCheckBox("Keep original layer name")
        self._single_keep_name_cb.setToolTip(
            "Use the source layer name instead of the export name when loading",
        )
        out_layout.addWidget(self._single_keep_name_cb)

        layout.addWidget(out_group)
        return tab

    def _build_gpkg_tab(self) -> QWidget:
        """Build the GeoPackage tab with layer table, select buttons, and output GeoPackage config."""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(6)

        self._gpkg_table = LayerTableWidget(show_format=False)
        self._gpkg_table.crs_changed.connect(self._on_target_crs_changed)
        self._gpkg_table.selection_changed.connect(self._update_export_button_state)
        layout.addWidget(self._gpkg_table)

        sel_row = QHBoxLayout()
        all_btn = QPushButton("Select all")
        all_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        all_btn.clicked.connect(self._gpkg_table.check_all)
        sel_row.addWidget(all_btn, 1)
        none_btn = QPushButton("Deselect all")
        none_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        none_btn.clicked.connect(self._gpkg_table.uncheck_all)
        sel_row.addWidget(none_btn, 1)
        refresh_btn = QPushButton("Refresh")
        refresh_btn.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )
        refresh_btn.clicked.connect(self._refresh_layers)
        sel_row.addWidget(refresh_btn, 1)
        layout.addLayout(sel_row)

        extent_row = QHBoxLayout()
        self._gpkg_extent_btn = QPushButton()
        self._gpkg_extent_btn.setMaximumWidth(200)
        self._gpkg_extent_btn.clicked.connect(self._set_global_extent)
        extent_row.addWidget(self._gpkg_extent_btn)
        layout.addLayout(extent_row)

        out_group = QGroupBox("Output GeoPackage")
        out_layout = QVBoxLayout(out_group)

        file_row = QHBoxLayout()
        self._gpkg_path_edit = QLineEdit()
        self._gpkg_path_edit.setPlaceholderText("output.gpkg path...")
        self._gpkg_path_edit.textChanged.connect(self._update_export_button_state)
        file_row.addWidget(self._gpkg_path_edit)
        browse = QPushButton("...")
        browse.setMaximumWidth(36)
        browse.clicked.connect(self._browse_gpkg_path)
        file_row.addWidget(browse)
        out_layout.addLayout(file_row)

        opts_grid = QGridLayout()
        self._gpkg_overwrite_cb = QCheckBox("Overwrite existing GPKG")
        opts_grid.addWidget(self._gpkg_overwrite_cb, 0, 0)

        self._gpkg_style_cb = QCheckBox("Save QML sidecars")
        opts_grid.addWidget(self._gpkg_style_cb, 0, 1)

        self._gpkg_embed_cb = QCheckBox("Embed styles in GPKG")
        self._gpkg_embed_cb.setChecked(True)
        opts_grid.addWidget(self._gpkg_embed_cb, 1, 0)

        self._gpkg_replace_cb = QCheckBox("Replace source in project after export")
        opts_grid.addWidget(self._gpkg_replace_cb, 1, 1)

        self._gpkg_preserve_groups_cb = QCheckBox(
            "Preserve layer groups in table names",
        )
        self._gpkg_preserve_groups_cb.setToolTip(
            "Prefix GPKG table names with the layer tree group path",
        )
        opts_grid.addWidget(self._gpkg_preserve_groups_cb, 2, 0)

        self._gpkg_add_to_project_cb = QCheckBox("Add exported layers to project")
        self._gpkg_add_to_project_cb.setToolTip(
            "Load exported layers as new layers in the project",
        )
        opts_grid.addWidget(self._gpkg_add_to_project_cb, 2, 1)

        self._gpkg_keep_name_cb = QCheckBox("Keep original layer name")
        self._gpkg_keep_name_cb.setToolTip(
            "Use the source layer name instead of the export name when loading",
        )
        opts_grid.addWidget(self._gpkg_keep_name_cb, 3, 0)

        out_layout.addLayout(opts_grid)
        layout.addWidget(out_group)
        return tab

    def _build_project_tab(self) -> QWidget:
        """Create the project archive export tab (.woof / ZIP)."""
        self._project_tab = ProjectExportTab(self.iface, self)
        return self._project_tab

    def _connect_project_signals(self) -> None:
        """Connect to QGIS project signals (layers added/removed, project read) to auto-refresh tables."""
        self._connections = []
        proj = QgsProject.instance()
        for name in (
            "layersAdded",
            "layersRemoved",
            "layerWasAdded",
            "cleared",
            "readProject",
        ):
            sig = getattr(proj, name)
            sig.connect(self._on_layers_changed)
            self._connections.append(sig)

        root = proj.layerTreeRoot()
        root.nameChanged.connect(self._on_layers_changed)
        self._connections.append(root.nameChanged)
        if hasattr(root, "addedChildren"):
            root.addedChildren.connect(self._on_layers_changed)
            self._connections.append(root.addedChildren)
        if hasattr(root, "removedChildren"):
            root.removedChildren.connect(self._on_layers_changed)
            self._connections.append(root.removedChildren)

        for name in ("projectRead", "newProjectCreated"):
            sig = getattr(self.iface, name, None)
            if sig is not None:
                with suppress(TypeError):
                    sig.connect(self._on_layers_changed)
                    self._connections.append(sig)

    def disconnect_all(self) -> None:
        """Disconnect all project signals. Call from dock closeEvent."""
        self._save_settings()

        for sig in self._connections:
            with suppress(Exception):
                sig.disconnect(self._on_layers_changed)

    def _on_layers_changed(self, *_args) -> None:
        """Rebuild all layer tables when the project layer list changes."""
        self._refresh_layers()

    def _refresh_layers(self) -> None:
        """Re-populate all layer tables from the current QGIS project, preserving filters and CRS overrides."""
        all_layers = list(QgsProject.instance().mapLayers().values())
        valid_ids = {layer.id() for layer in all_layers}
        self._filters = {
            lid: expr for lid, expr in self._filters.items() if lid in valid_ids
        }
        self._target_crs = {
            lid: crs for lid, crs in self._target_crs.items() if lid in valid_ids
        }

        for table in (self._single_table, self._gpkg_table):
            table.set_global_formats(self._vector_selected, self._raster_selected)
            table.populate(all_layers)
            for lid, expr in self._filters.items():
                table.set_filter(lid, expr)
            for lid, authid in self._target_crs.items():
                table.set_target_crs(lid, authid)

        if hasattr(self, "_project_tab"):
            self._project_tab._refresh_table()

        self._update_layer_count()
        self._update_single_formats()
        self._update_export_button_state()

    def _update_layer_count(self) -> None:
        """Update the info label showing loaded/selected/filtered layer counts."""
        table = self._active_table()
        total = table.rowCount()
        selected = len(table.selected_layer_ids())
        filtered = table.count_filters()
        parts = [f"{total} layers loaded"]
        if selected:
            parts.append(f"{selected} selected")
        if filtered:
            parts.append(f"{filtered} with filters")
        self._layer_count_label.setText(", ".join(parts))

    def _has_vector_in_table(self) -> bool:
        """Return True if at least one vector layer exists in the single table."""
        for row in range(self._single_table.rowCount()):
            lid = self._single_table._layer_id_for_row(row)
            if lid:
                layer = QgsProject.instance().mapLayer(lid)
                if isinstance(layer, QgsVectorLayer):
                    return True
        return False

    def _has_raster_in_table(self) -> bool:
        """Return True if at least one raster layer exists in the single table."""
        for row in range(self._single_table.rowCount()):
            lid = self._single_table._layer_id_for_row(row)
            if lid:
                layer = QgsProject.instance().mapLayer(lid)
                if isinstance(layer, QgsRasterLayer):
                    return True
        return False

    def _update_single_formats(self) -> None:
        """Show/hide the format configuration button based on available layer types."""
        has_vec = self._has_vector_in_table()
        has_ras = self._has_raster_in_table()
        if hasattr(self, "_fmt_btn"):
            self._fmt_btn.setVisible(has_vec or has_ras)

    def _update_format_button_text(self) -> None:
        """Update the format button label to show selected vector/raster format counts."""
        vec = len(self._vector_selected)
        ras = len(self._raster_selected)
        parts = []
        if vec:
            parts.append(f"{vec} vector")
        if ras:
            parts.append(f"{ras} raster")
        if hasattr(self, "_fmt_btn"):
            self._fmt_btn.setText(f"({', '.join(parts)})" if parts else "")

    def _configure_formats(self) -> None:
        """Open the format selection dialog and apply the chosen formats."""
        dlg = FormatDialog(self._vector_selected, self._raster_selected, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._vector_selected = dlg.get_vector_selected()
            self._raster_selected = dlg.get_raster_selected()
            self._update_format_button_text()
            self._update_export_button_state()
            for table in (self._single_table, self._gpkg_table):
                table.set_global_formats(
                    self._vector_selected,
                    self._raster_selected,
                )

    def _resolve_extent(
        self,
        layer,
        per_layer_extent: str,
    ) -> str:
        """Return the effective extent for a layer: per-layer if set, else global, with CRS transform."""
        extent = per_layer_extent or self._global_extent_coords
        if extent and self._global_extent_crs and layer.crs().isValid():
            global_crs = QgsCoordinateReferenceSystem(self._global_extent_crs)
            layer_crs = layer.crs()
            if global_crs.isValid() and global_crs != layer_crs:
                parts = extent.split(",")
                if len(parts) == 4:
                    try:
                        rect = QgsRectangle(
                            float(parts[0]),
                            float(parts[1]),
                            float(parts[2]),
                            float(parts[3]),
                        )
                        xform = QgsCoordinateTransform(
                            global_crs,
                            layer_crs,
                            QgsProject.instance().transformContext(),
                        )
                        rect = xform.transformBoundingBox(rect)
                        return (
                            f"{rect.xMinimum()},{rect.yMinimum()},"
                            f"{rect.xMaximum()},{rect.yMaximum()}"
                        )
                    except (ValueError, TypeError):
                        pass
        return extent

    def _set_global_extent(self) -> None:
        """Open a dialog with QgsExtentGroupBox to set a global extent filter."""
        dlg = QDialog(self)
        dlg.setWindowTitle("Set global extent filter")
        dlg.setMinimumWidth(500)
        layout = QVBoxLayout(dlg)

        extent_group = QgsExtentGroupBox(dlg)
        extent_group.setCheckable(True)

        has_extent = bool(self._global_extent_coords)
        extent_group.setChecked(has_extent)

        proj = QgsProject.instance()
        extent = QgsRectangle()
        first = True
        for layer in proj.mapLayers().values():
            if isinstance(layer, (QgsVectorLayer, QgsRasterLayer)) and layer.isValid():
                le = layer.extent()
                if not le.isNull():
                    if first:
                        extent = QgsRectangle(le)
                        first = False
                    else:
                        extent.combineExtentWith(le)

        if first:
            extent = QgsRectangle(-180, -90, 180, 90)
        proj_crs = proj.crs()
        ref_crs = (
            proj_crs
            if proj_crs.isValid()
            else QgsCoordinateReferenceSystem("EPSG:4326")
        )
        extent_group.setOriginalExtent(extent, ref_crs)
        extent_group.setCurrentExtent(extent, ref_crs)
        extent_group.setOutputCrs(ref_crs)

        if has_extent:
            parts = self._global_extent_coords.split(",")
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

        if self._global_extent_crs:
            crs = QgsCoordinateReferenceSystem(self._global_extent_crs)
            if crs.isValid():
                extent_group.setOutputCrs(crs)

        extent_group.toggled.connect(
            lambda checked: extent_group.setTitleBase(
                "Extent" if checked else "No global extent",
            ),
        )
        extent_group.setTitleBase("Extent" if has_extent else "No global extent")

        layout.addWidget(extent_group)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
        )
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        layout.addWidget(buttons)

        if dlg.exec():
            if not extent_group.isChecked():
                self._global_extent_coords = ""
                self._global_extent_crs = ""
            else:
                rect = extent_group.outputExtent()
                if not rect.isNull():
                    self._global_extent_coords = (
                        f"{rect.xMinimum()},{rect.yMinimum()},"
                        f"{rect.xMaximum()},{rect.yMaximum()}"
                    )
                    crs = extent_group.outputCrs()
                    self._global_extent_crs = crs.authid() if crs.isValid() else ""
                else:
                    self._global_extent_coords = ""
                    self._global_extent_crs = ""
            self._update_global_extent_buttons()

    def _update_global_extent_buttons(self) -> None:
        """Update button text for both tabs to show current global extent state."""
        if self._global_extent_coords:
            crs_part = (
                f" ({self._global_extent_crs})" if self._global_extent_crs else ""
            )
            text = f"Extent: {self._global_extent_coords}{crs_part}"
        else:
            text = "Set global extent..."
        if hasattr(self, "_extent_btn"):
            self._extent_btn.setText(text)
        if hasattr(self, "_gpkg_extent_btn"):
            self._gpkg_extent_btn.setText(text)

    def _update_export_button_state(self) -> None:
        """Enable/disable the Export button based on current selections and inputs."""
        self._update_layer_count()
        table = self._active_table()
        has_selection = len(table.selected_layer_ids()) > 0

        if self._tabs.currentIndex() == 0:
            has_dir = bool(self._single_dir_edit.text().strip())
            has_vector = bool(self._vector_selected)
            has_raster = bool(self._raster_selected)
            has_format = has_vector or has_raster
            can_export = has_selection and has_dir and has_format
        else:
            has_path = bool(self._gpkg_path_edit.text().strip())
            can_export = has_selection and has_path

        self._export_btn.setEnabled(can_export)

    def _on_tab_changed(self, index: int) -> None:
        """Update UI state when switching between Single Files and GeoPackage tabs."""
        self._update_layer_count()
        self._update_export_button_state()
        self._btn_widget.setVisible(index < 2)

    def _load_settings(self) -> None:
        """Restore all persisted UI state from QgsSettings."""
        s = QgsSettings()
        s.beginGroup(SETTINGS_ROOT)

        single_dir = s.value("single_dir", "", str)
        if single_dir:
            self._single_dir_edit.setText(single_dir)

        single_style = s.value("single_style_idx", 1, int)
        self._single_style_combo.setCurrentIndex(single_style)

        single_replace = s.value("single_replace", False, bool)
        self._single_replace_cb.setChecked(single_replace)

        single_add = s.value("single_add_to_project", False, bool)
        self._single_add_to_project_cb.setChecked(single_add)

        single_keep = s.value("single_keep_name", False, bool)
        self._single_keep_name_cb.setChecked(single_keep)

        naming_template = s.value("naming_template", "", str)
        if naming_template:
            self._naming_template_edit.setText(naming_template)

        gpkg_path = s.value("gpkg_path", "", str)
        if gpkg_path:
            self._gpkg_path_edit.setText(gpkg_path)

        gpkg_overwrite = s.value("gpkg_overwrite", False, bool)
        self._gpkg_overwrite_cb.setChecked(gpkg_overwrite)

        gpkg_style = s.value("gpkg_style", False, bool)
        self._gpkg_style_cb.setChecked(gpkg_style)

        gpkg_embed = s.value("gpkg_embed", True, bool)
        self._gpkg_embed_cb.setChecked(gpkg_embed)

        gpkg_replace = s.value("gpkg_replace", False, bool)
        self._gpkg_replace_cb.setChecked(gpkg_replace)

        gpkg_groups = s.value("gpkg_preserve_groups", False, bool)
        self._gpkg_preserve_groups_cb.setChecked(gpkg_groups)

        gpkg_add = s.value("gpkg_add_to_project", False, bool)
        self._gpkg_add_to_project_cb.setChecked(gpkg_add)

        gpkg_keep = s.value("gpkg_keep_name", False, bool)
        self._gpkg_keep_name_cb.setChecked(gpkg_keep)

        saved_vector = s.value("single_vector_formats", None)
        if saved_vector is not None:
            if isinstance(saved_vector, str):
                saved_vector = [saved_vector]
            self._vector_selected = set(saved_vector)
        else:
            saved_old = s.value("single_formats", ["GPKG"])
            if isinstance(saved_old, str):
                saved_old = [saved_old]
            self._vector_selected = set(saved_old)

        saved_raster = s.value("single_raster_formats", ["GTiff"])
        if isinstance(saved_raster, str):
            saved_raster = [saved_raster]
        self._raster_selected = set(saved_raster)

        self._update_format_button_text()

        log_text = s.value("log_text", "", str)
        if log_text:
            self._append_log_html(log_text)
            self._log_entries = log_text.strip().split("\n")

        filters_json = s.value("filters", "{}", str)
        self._filters = json.loads(filters_json)

        crs_json = s.value("target_crs", "{}", str)
        self._target_crs = json.loads(crs_json)

        names_json = s.value("export_names", "{}", str)
        export_names = json.loads(names_json)
        self._single_table._export_names.update(export_names)
        self._gpkg_table._export_names.update(export_names)

        self._global_extent_coords = s.value("global_extent_coords", "", str)
        self._global_extent_crs = s.value("global_extent_crs", "", str)
        self._update_global_extent_buttons()

        s.endGroup()

    def _save_settings(self) -> None:
        """Persist current UI state to QgsSettings."""
        s = QgsSettings()
        s.beginGroup(SETTINGS_ROOT)

        s.setValue("single_dir", self._single_dir_edit.text().strip())
        s.setValue("single_style_idx", self._single_style_combo.currentIndex())
        s.setValue("single_replace", self._single_replace_cb.isChecked())
        s.setValue("single_add_to_project", self._single_add_to_project_cb.isChecked())
        s.setValue("single_keep_name", self._single_keep_name_cb.isChecked())
        s.setValue("naming_template", self._naming_template_edit.text().strip())
        s.setValue("gpkg_path", self._gpkg_path_edit.text().strip())
        s.setValue("gpkg_overwrite", self._gpkg_overwrite_cb.isChecked())
        s.setValue("gpkg_style", self._gpkg_style_cb.isChecked())
        s.setValue("gpkg_embed", self._gpkg_embed_cb.isChecked())
        s.setValue("gpkg_replace", self._gpkg_replace_cb.isChecked())
        s.setValue("gpkg_preserve_groups", self._gpkg_preserve_groups_cb.isChecked())
        s.setValue("gpkg_add_to_project", self._gpkg_add_to_project_cb.isChecked())
        s.setValue("gpkg_keep_name", self._gpkg_keep_name_cb.isChecked())

        s.setValue("single_vector_formats", list(self._vector_selected))
        s.setValue("single_raster_formats", list(self._raster_selected))

        s.setValue("log_text", self._log_view.toPlainText())

        s.setValue("filters", json.dumps(self._filters))
        s.setValue("target_crs", json.dumps(self._target_crs))
        s.setValue("export_names", json.dumps(self._single_table._export_names))
        s.setValue("global_extent_coords", self._global_extent_coords)
        s.setValue("global_extent_crs", self._global_extent_crs)

        s.endGroup()
        s.sync()

        if hasattr(self, "_project_tab"):
            self._project_tab.save_settings()

    def _reset_all(self) -> None:
        """Reset all filters, CRS overrides, export names, and UI settings to defaults."""
        reply = QMessageBox.question(
            self,
            "Reset All",
            "Reset export names, filters, CRS overrides, and settings to defaults?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._filters.clear()
        self._target_crs.clear()
        self._reset_export_names()
        for table in (self._single_table, self._gpkg_table):
            for row in range(table.rowCount()):
                lid = table._layer_id_for_row(row)
                if lid:
                    table._format_overrides.pop(lid, None)
                    table._update_format_display(lid)
        self._single_dir_edit.clear()
        self._naming_template_edit.clear()
        self._gpkg_path_edit.clear()
        self._single_style_combo.setCurrentIndex(1)
        self._single_replace_cb.setChecked(False)
        self._single_add_to_project_cb.setChecked(False)
        self._single_keep_name_cb.setChecked(False)
        self._gpkg_overwrite_cb.setChecked(False)
        self._gpkg_style_cb.setChecked(False)
        self._gpkg_embed_cb.setChecked(True)
        self._gpkg_replace_cb.setChecked(False)
        self._gpkg_preserve_groups_cb.setChecked(False)
        self._gpkg_add_to_project_cb.setChecked(False)
        self._gpkg_keep_name_cb.setChecked(False)
        self._vector_selected = {"GPKG"}
        self._raster_selected = {"GTiff"}
        self._global_extent_coords = ""
        self._global_extent_crs = ""
        self._update_global_extent_buttons()
        self._update_format_button_text()
        self._clear_log()
        self._log_view.setPlainText("")
        if hasattr(self, "_project_tab"):
            self._project_tab.reset_settings()
        self._refresh_layers()
        self._save_settings()

    def _on_target_crs_changed(self, layer_id: str, authid: str) -> None:
        """Propagate a CRS override change to both tables and the internal dict."""
        self._target_crs[layer_id] = authid
        for table in (self._single_table, self._gpkg_table):
            if table.get_target_crs(layer_id) != authid:
                table.set_target_crs(layer_id, authid)

    def _open_filter_dialog(self) -> None:
        """Open the SQL expression filter dialog for selected vector layers."""
        table = self._active_table()
        checked = table.get_selected_items()

        vector_items = [
            (lid, name)
            for lid, name in checked
            if isinstance(QgsProject.instance().mapLayer(lid), QgsVectorLayer)
        ]

        if not vector_items:
            QMessageBox.information(
                self,
                "No Vector Layers",
                "Select at least one vector layer to set a filter.",
            )
            return

        dlg = SQLFilterDialog(
            layer_items=vector_items,
            current_filters=self._filters,
            parent=self,
        )
        dlg.filter_applied.connect(self._on_filter_applied)
        dlg.exec()

    def _on_filter_applied(self, layer_id: str, expression: str) -> None:
        """Store a filter expression and update both tables."""
        self._filters[layer_id] = expression
        for table in (self._single_table, self._gpkg_table):
            table.set_filter(layer_id, expression)
        self._update_layer_count()

    def _reset_export_names(self) -> None:
        """Revert all per-layer export names to their source layer names."""
        for table in (self._single_table, self._gpkg_table):
            table.reset_export_names()

    NAMING_PLACEHOLDERS: ClassVar[dict[str, str]] = {  # noqa: RUF012
        "{layer_name}": "Source layer name",
        "{date}": "Today's date (YYYY-MM-DD)",
        "{time}": "Current time (HHMMSS)",
        "{crs}": "Layer CRS auth code (e.g. EPSG:4326)",
        "{datetime}": "Date + time (YYYY-MM-DD_HHMMSS)",
    }

    @staticmethod
    def _resolve_template(template: str, layer_name: str, crs_authid: str) -> str:
        """Replace placeholders in a naming template with actual values."""
        now = datetime.now().astimezone()
        result = template
        result = result.replace("{layer_name}", layer_name)
        result = result.replace("{date}", now.strftime("%Y-%m-%d"))
        result = result.replace("{time}", now.strftime("%H%M%S"))
        result = result.replace("{crs}", crs_authid or "no_crs")
        return result.replace("{datetime}", now.strftime("%Y-%m-%d_%H%M%S"))

    def _apply_naming_template(self) -> None:
        """Apply the current naming template to all export names in the single table."""
        template = self._naming_template_edit.text().strip()
        if not template:
            template = "{layer_name}"
        for row in range(self._single_table.rowCount()):
            lid = self._single_table._layer_id_for_row(row)
            if not lid:
                continue
            layer = QgsProject.instance().mapLayer(lid)
            if layer is None:
                continue
            src_name = layer.name()
            crs = layer.crs().authid() if layer.crs().isValid() else ""
            resolved = self._resolve_template(template, src_name, crs)
            sanitized = self._sanitize_name(resolved)
            self._single_table._export_names[lid] = sanitized
            exp_item = self._single_table.item(row, 2)
            if exp_item:
                exp_item.setText(sanitized)
                self._single_table._apply_export_name_style(
                    exp_item,
                    sanitized,
                    src_name,
                )
        self._update_export_button_state()

    def _show_naming_hint(self) -> None:
        """Display an info dialog listing available naming template placeholders."""
        lines = ["Available placeholders:\n"]
        for placeholder, desc in self.NAMING_PLACEHOLDERS.items():
            lines.append(f"  {placeholder}  —  {desc}")
        lines.append("\nExample: export_{layer_name}_{date}")
        lines.append("Result:   export_roads_2026-05-21")
        QMessageBox.information(self, "Naming pattern placeholders", "\n".join(lines))

    @staticmethod
    def _get_group_path(layer_id: str) -> str:
        """Return the sanitized group path for a layer (e.g. 'transport_roads')."""
        root = QgsProject.instance().layerTreeRoot()
        node = root.findLayer(layer_id)
        if node is None:
            return ""
        group_names: list[str] = []
        parent = node.parent()
        while parent is not None and parent != root:
            group_names.append(parent.name())
            parent = parent.parent()
        if not group_names:
            return ""
        group_names.reverse()
        clean = []
        for n in group_names:
            sanitized = ""
            for ch in n:
                sanitized += "_" if ch in r'\/:*?"<>|. ' else ch
            clean.append(sanitized.lower().strip("_"))
        return "_".join(filter(None, clean))

    def _cancel_export(self) -> None:
        """Request cancellation of the current export operation."""
        worker = getattr(self, "_export_worker", None)
        if worker is not None:
            worker.cancel()
        self._cancel_btn.setEnabled(False)

    def _check_duplicate_names(self, specs: list[ExportSpec]) -> list[ExportSpec]:
        """Check for duplicate export names in single-file mode. Warn and ask user."""
        seen: dict[str, int] = {}
        dups: list[tuple[str, str]] = []
        for s in specs:
            if s.target_mode == "single":
                fname = f"{self._sanitize_name(s.export_name)}{s.file_extension}"
                if fname in seen:
                    dups.append((s.export_name, s.source_name))
                else:
                    seen[fname] = 1
        if dups:
            lines = "\n".join(f"  - '{name}' (layer: {src})" for name, src in dups)
            reply = QMessageBox.warning(
                self,
                "Duplicate Export Names",
                "The following export names will create files with conflicting names:"
                f"\n{lines}"
                "\n\nLater exports will overwrite earlier ones. Continue?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return []
        return specs

    def _do_export(self) -> None:
        """Start export for the currently active tab (Single Files or GeoPackage)."""
        if self._tabs.currentIndex() == 0:
            self._export_single()
        else:
            self._export_gpkg()

    def _validate_export_layer(self, lid: str, _exp_name: str, table: LayerTableWidget):
        """Validate layer for export. Returns (layer, target_crs, is_raster, error)."""
        layer = QgsProject.instance().mapLayer(lid)
        if layer is None:
            return None, None, None, "Layer not found"

        block_reason = table.export_warning(lid) or layer_export_block_reason(layer)
        if block_reason:
            return None, None, None, block_reason

        target_crs = self._target_crs.get(lid, "").strip()
        if not target_crs and layer.crs().isValid():
            target_crs = layer.crs().authid()
        if target_crs and not QgsCoordinateReferenceSystem(target_crs).isValid():
            return None, None, None, f"invalid CRS '{target_crs}'"

        return layer, target_crs, isinstance(layer, QgsRasterLayer), None

    def _get_layer_drivers(self, lid: str, is_raster: bool) -> list[str]:
        """Return drivers for a layer. Per-layer override replaces global defaults."""
        override = self._single_table.get_format_override(lid)
        if override:
            return list(override)
        return list(self._raster_selected if is_raster else self._vector_selected) or (
            ["GTiff"] if is_raster else ["GPKG"]
        )

    def _export_single(self) -> None:
        """Build and run ExportSpecs for the Single Files tab."""
        checked = self._single_table.get_selected_items()
        if not checked:
            QMessageBox.warning(self, "Nothing selected", "Check at least one layer.")
            return

        out_dir = self._single_dir_edit.text().strip()
        if not out_dir:
            QMessageBox.warning(
                self,
                "No output directory",
                "Please select an output directory.",
            )
            return

        if not os.path.isdir(out_dir):
            try:
                os.makedirs(out_dir, exist_ok=True)
            except OSError as e:
                QMessageBox.critical(self, "Directory error", str(e))
                return

        style_idx = self._single_style_combo.currentIndex()
        style_mode_map = {
            0: StyleMode.NONE,
            1: StyleMode.QML,
            2: StyleMode.SLD,
            3: StyleMode.BOTH,
            4: StyleMode.EMBED,
        }
        style_mode = style_mode_map.get(style_idx, StyleMode.NONE)
        replace = self._single_replace_cb.isChecked()

        specs: list[ExportSpec] = []
        skipped: list[str] = []
        for lid, exp_name in checked:
            safe_name = self._sanitize_name(exp_name)
            layer, target_crs, is_raster, error = self._validate_export_layer(
                lid,
                exp_name,
                self._single_table,
            )
            if error:
                skipped.append(f"{exp_name}: {error}")
                continue

            drivers = self._get_layer_drivers(lid, is_raster)
            for driver in drivers:
                em = style_mode
                if em == StyleMode.EMBED and driver != "GPKG":
                    em = StyleMode.QML
                specs.append(
                    ExportSpec(
                        source_layer_id=lid,
                        source_name=layer.name(),
                        export_name=safe_name,
                        target_mode="single",
                        output_path=out_dir,
                        driver=driver,
                        filter_expression=self._filters.get(lid, ""),
                        style_mode=em,
                        replace_in_project=replace,
                        target_crs_authid=target_crs,
                        field_names=self._single_table.get_field_filter(lid),
                        field_types=self._single_table.get_field_type_overrides(lid),
                        field_export_names=self._single_table.get_field_export_names(
                            lid
                        ),
                        encoding=self._single_table.get_encoding(lid),
                        save_selected_only=self._single_table.get_save_selected_only(
                            lid
                        ),
                        use_aliases_for_export_name=self._single_table.get_use_aliases(
                            lid
                        ),
                        persist_layer_metadata=self._single_table.get_persist_metadata(
                            lid
                        ),
                        geometry_type_override=self._single_table.get_geometry_type_override(
                            lid
                        ),
                        force_z=self._single_table.get_force_z(lid),
                        force_multi=self._single_table.get_force_multi(lid),
                        filter_extent=self._resolve_extent(
                            layer,
                            self._single_table.get_filter_extent(lid),
                        ),
                        datasource_options=self._single_table.get_datasource_options(
                            lid
                        ),
                        layer_options=self._single_table.get_layer_options(lid),
                        raster_resolution_x=self._single_table.get_raster_resolution_x(
                            lid
                        ),
                        raster_resolution_y=self._single_table.get_raster_resolution_y(
                            lid
                        ),
                        raster_nodata=self._single_table.get_raster_nodata(lid),
                        skip_attribute_creation=self._single_table.get_skip_attribute_creation(
                            lid
                        ),
                        include_constraints=self._single_table.get_include_constraints(
                            lid
                        ),
                        description=self._single_table.get_description(lid),
                        layer_fid=self._single_table.get_layer_fid(lid),
                        geometry_name=self._single_table.get_geometry_name(lid),
                        identifier=self._single_table.get_identifier(lid),
                        spatial_index=self._single_table.get_spatial_index(lid),
                    ),
                )

        if skipped:
            QMessageBox.warning(
                self,
                "Some layers were skipped",
                "Not queued for export:\n" + "\n".join(f"- {s}" for s in skipped),
            )
        if not specs:
            return

        specs = self._check_duplicate_names(specs)
        if not specs:
            return

        self._add_exported_layers = self._single_add_to_project_cb.isChecked()
        self._keep_original_name = self._single_keep_name_cb.isChecked()
        self._run_specs(specs)

    def _export_gpkg(self) -> None:
        """Build and run ExportSpecs for the GeoPackage tab."""
        checked = self._gpkg_table.get_selected_items()
        if not checked:
            QMessageBox.warning(self, "Nothing selected", "Check at least one layer.")
            return

        gpkg_path = self._gpkg_path_edit.text().strip()
        if not gpkg_path:
            QMessageBox.warning(
                self,
                "No output file",
                "Please specify a GeoPackage output path.",
            )
            return
        if not gpkg_path.lower().endswith(".gpkg"):
            gpkg_path += ".gpkg"
            self._gpkg_path_edit.setText(gpkg_path)

        if self._gpkg_overwrite_cb.isChecked() and os.path.exists(gpkg_path):
            try:
                os.remove(gpkg_path)
            except OSError as e:
                QMessageBox.critical(self, "Cannot overwrite", str(e))
                return

        if self._gpkg_embed_cb.isChecked():
            style_mode = StyleMode.EMBED
        elif self._gpkg_style_cb.isChecked():
            style_mode = StyleMode.QML
        else:
            style_mode = StyleMode.NONE
        replace = self._gpkg_replace_cb.isChecked()

        specs: list[ExportSpec] = []
        skipped: list[str] = []
        for lid, exp_name in checked:
            layer, target_crs, is_raster, error = self._validate_export_layer(
                lid,
                exp_name,
                self._gpkg_table,
            )
            if error:
                skipped.append(f"{exp_name}: {error}")
                continue

            safe_name = self._sanitize_name(exp_name)
            if self._gpkg_preserve_groups_cb.isChecked():
                group = self._get_group_path(lid)
                if group:
                    safe_name = f"{group}_{safe_name}"
            specs.append(
                ExportSpec(
                    source_layer_id=lid,
                    source_name=layer.name(),
                    export_name=safe_name,
                    target_mode="gpkg",
                    output_path=gpkg_path,
                    driver="GTiff" if is_raster else "GPKG",
                    filter_expression=self._filters.get(lid, ""),
                    style_mode=style_mode,
                    replace_in_project=replace,
                    target_crs_authid=target_crs,
                    field_names=self._gpkg_table.get_field_filter(lid),
                    field_types=self._gpkg_table.get_field_type_overrides(lid),
                    field_export_names=self._gpkg_table.get_field_export_names(lid),
                    encoding=self._gpkg_table.get_encoding(lid),
                    save_selected_only=self._gpkg_table.get_save_selected_only(lid),
                    use_aliases_for_export_name=self._gpkg_table.get_use_aliases(lid),
                    persist_layer_metadata=self._gpkg_table.get_persist_metadata(lid),
                    geometry_type_override=self._gpkg_table.get_geometry_type_override(
                        lid
                    ),
                    force_z=self._gpkg_table.get_force_z(lid),
                    force_multi=self._gpkg_table.get_force_multi(lid),
                    filter_extent=self._resolve_extent(
                        layer,
                        self._gpkg_table.get_filter_extent(lid),
                    ),
                    datasource_options=self._gpkg_table.get_datasource_options(lid),
                    layer_options=self._gpkg_table.get_layer_options(lid),
                    raster_resolution_x=self._gpkg_table.get_raster_resolution_x(lid),
                    raster_resolution_y=self._gpkg_table.get_raster_resolution_y(lid),
                    raster_nodata=self._gpkg_table.get_raster_nodata(lid),
                    skip_attribute_creation=self._gpkg_table.get_skip_attribute_creation(
                        lid
                    ),
                    include_constraints=self._gpkg_table.get_include_constraints(lid),
                    description=self._gpkg_table.get_description(lid),
                    layer_fid=self._gpkg_table.get_layer_fid(lid),
                    geometry_name=self._gpkg_table.get_geometry_name(lid),
                    identifier=self._gpkg_table.get_identifier(lid),
                    spatial_index=self._gpkg_table.get_spatial_index(lid),
                ),
            )

        if skipped:
            QMessageBox.warning(
                self,
                "Some layers were skipped",
                "Not queued for export:\n" + "\n".join(f"- {s}" for s in skipped),
            )
        if not specs:
            return

        self._add_exported_layers = self._gpkg_add_to_project_cb.isChecked()
        self._keep_original_name = self._gpkg_keep_name_cb.isChecked()
        self._run_specs(specs)

    def _check_overwrite(self, specs: list[ExportSpec]) -> bool:
        """Prompt user before overwriting existing single-file exports. Return True to continue."""
        existing: list[str] = []
        for s in specs:
            if s.target_mode != "single":
                continue
            path = os.path.join(s.output_path, f"{s.export_name}{s.file_extension}")
            if os.path.exists(path):
                existing.append(s.export_name)
        if existing:
            reply = QMessageBox.question(
                self,
                "Overwrite existing files",
                "The following files already exist and will be overwritten:\n"
                + "\n".join(f"  - {n}" for n in existing)
                + "\n\nContinue?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            return reply == QMessageBox.StandardButton.Yes
        return True

    def _run_specs(self, specs: list[ExportSpec]) -> None:
        """Dispatch ExportSpecs in a background thread via ExportWorker."""
        if not specs:
            return

        if not self._check_overwrite(specs):
            return

        self._export_btn.setEnabled(False)
        self._cancel_btn.setVisible(True)
        self._cancel_btn.setEnabled(True)
        self._progress.setVisible(True)
        self._progress.setRange(0, 100)
        self._progress.setValue(0)

        self._start_time = time.time()
        self._specs_count = len(specs)

        self._export_thread = QThread()
        self._export_worker = ExportWorker(specs)
        self._export_worker.moveToThread(self._export_thread)

        self._export_worker.progress.connect(self._on_worker_progress)
        self._export_worker.finished.connect(self._on_worker_finished)
        self._export_thread.started.connect(self._export_worker.run)
        self._export_worker.finished.connect(self._export_thread.quit)
        self._export_worker.finished.connect(self._export_worker.deleteLater)
        self._export_thread.finished.connect(self._export_thread.deleteLater)

        self._export_thread.start()

    def _on_worker_progress(self, current: int, total: int, msg: str) -> None:
        """Update the progress bar and status label during background export."""
        pct = int((100.0 * current) / total) if total else 100
        self._progress.setValue(pct)
        self._status.setText(msg)

    def _append_log_html(self, text: str) -> None:
        """Append colored HTML to the log. Recognizes OK/FAIL/session patterns."""
        html_parts = []
        for line in text.strip().split("\n"):
            if line.startswith("  OK  "):
                html_parts.append(
                    f'<span style="color:#27ae60;">{self._escape_html(line)}</span>',
                )
            elif line.startswith("  FAIL "):
                html_parts.append(
                    f'<span style="color:#c0392b;">{self._escape_html(line)}</span>',
                )
            elif "Export session:" in line or "Export cancelled" in line:
                html_parts.append(
                    f'<b style="color:#2980b9;">{self._escape_html(line)}</b>',
                )
            else:
                html_parts.append(self._escape_html(line))

        cursor = self._log_view.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        for i, part in enumerate(html_parts):
            if i > 0:
                cursor.insertHtml("<br>")
            cursor.insertHtml(part)
        self._log_view.setTextCursor(cursor)
        self._log_view.ensureCursorVisible()

    @staticmethod
    def _escape_html(text: str) -> str:
        return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    def _on_worker_finished(self, results: list[ExportResult]) -> None:
        """Process export results: log, notify user, optionally load layers, save settings."""
        elapsed = time.time() - self._start_time
        was_cancelled = self._export_worker.was_cancelled
        self._progress.setVisible(False)
        self._cancel_btn.setVisible(False)
        self._export_btn.setEnabled(True)
        self._status.setText("")

        log_lines: list[str] = []
        ok = sum(1 for r in results if r.success)
        fail = [r for r in results if not r.success]

        if was_cancelled:
            log_lines.append(
                f"[{time.strftime('%H:%M:%S')}] Export cancelled "
                f"({ok} ok, {len(fail)} failed, {elapsed:.1f}s)",
            )
        else:
            log_lines.append(
                f"[{time.strftime('%H:%M:%S')}] Export session: "
                f"{ok} ok, {len(fail)} failed ({elapsed:.1f}s)",
            )
        for r in results:
            if r.success:
                fcount = r.features_written if r.features_written is not None else "?"
                log_lines.append(
                    f"  OK  {r.spec.export_name} -> {r.output_path} ({fcount} features)",
                )
            else:
                log_lines.append(f"  FAIL {r.spec.export_name}: {r.error}")

        self._log_entries.extend(log_lines)
        self._append_log_html("\n".join(log_lines))

        if fail or was_cancelled:
            self._tabs.setCurrentIndex(3)

        if getattr(self, "_add_exported_layers", False):
            for r in results:
                if r.success:
                    self._add_result_to_project(r)

        if fail:
            QMessageBox.warning(
                self,
                "Some exports failed",
                f"{ok} succeeded, {len(fail)} failed:\n"
                + "\n".join(f"- {r.spec.export_name}: {r.error}" for r in fail),
            )
        elif not was_cancelled:
            QMessageBox.information(
                self,
                "Export complete",
                f"Successfully exported {ok} layer(s).",
            )

        self._save_settings()

    def _add_result_to_project(self, result: ExportResult) -> None:
        """Load a successful export result as a new layer in the project."""
        spec = result.spec
        path = result.output_path
        name = (
            spec.source_name
            if getattr(self, "_keep_original_name", False)
            else spec.export_name
        )
        if spec.is_raster_driver:
            layer = QgsRasterLayer(path, name)
        elif spec.target_mode == "gpkg" and spec.is_raster_driver:
            layer = QgsRasterLayer(f"{path}|layername={name}", name)
        elif spec.target_mode == "gpkg":
            layer = QgsVectorLayer(f"{path}|layername={name}", name, "ogr")
        else:
            layer = QgsVectorLayer(path, name, "ogr")
        if layer and layer.isValid():
            QgsProject.instance().addMapLayer(layer)

    def set_active_layer(self, layer) -> None:
        """Select and scroll to a specific layer in both tables."""
        self._tabs.setCurrentIndex(0)
        self._single_table.set_active_layer(layer)
        self._gpkg_table.set_active_layer(layer)

    def _browse_single_dir(self) -> None:
        """Open a directory chooser and set the Single Files output path."""
        d = QFileDialog.getExistingDirectory(self, "Select Output Directory")
        if d:
            self._single_dir_edit.setText(d)

    def _browse_gpkg_path(self) -> None:
        """Open a save-file dialog and set the GeoPackage output path."""
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save GeoPackage As",
            "",
            "GeoPackage (*.gpkg);;All Files (*)",
        )
        if path:
            if not path.lower().endswith(".gpkg"):
                path += ".gpkg"
            self._gpkg_path_edit.setText(path)

    def _active_table(self) -> LayerTableWidget:
        """Return the currently visible layer table based on the active tab."""
        if self._tabs.currentIndex() == 0:
            return self._single_table
        gpkg = getattr(self, "_gpkg_table", None)
        return gpkg if gpkg is not None else self._single_table
