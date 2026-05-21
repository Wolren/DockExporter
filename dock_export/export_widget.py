"""Main export UI with Single Files and GeoPackage tabs. Builds ExportSpec list from table state."""

from __future__ import annotations

import os
import time
from typing import Dict, List

from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)
from qgis.core import (
    Qgis,
    QgsCoordinateReferenceSystem,
    QgsProject,
    QgsRasterLayer,
    QgsSettings,
    QgsVectorLayer,
)

from .export_engine import ExportEngine, ExportResult, layer_export_block_reason
from .layer_table_widget import LayerTableWidget
from .models import ExportSpec, StyleMode
from .sql_filter_widget import SQLFilterDialog
from .style_manager import StyleManager

SETTINGS_ROOT = "DockExport"


class ExportWidget(QWidget):
    """Tabbed export UI embedded in the dock. Builds ExportSpecs from table state."""

    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface = iface
        self._engine = ExportEngine(StyleManager())
        self._filters: Dict[str, str] = {}
        self._target_crs: Dict[str, str] = {}
        self._filter_dialog = None
        self._log_entries: List[str] = []

        self._build_ui()
        self._load_settings()
        self._refresh_layers()
        self._connect_project_signals()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(6)
        root.setContentsMargins(6, 6, 6, 6)

        self._tabs = QTabWidget()
        self._tabs.addTab(self._build_single_tab(), "Single files")
        self._tabs.addTab(self._build_gpkg_tab(), "GeoPackage")
        self._tabs.currentChanged.connect(self._on_tab_changed)
        root.addWidget(self._tabs)

        self._layer_count_label = QLabel("")
        self._layer_count_label.setStyleSheet(
            "font-size:9pt; color:#555; padding:2px 0;"
        )
        root.addWidget(self._layer_count_label)

        self._progress = QProgressBar()
        self._progress.setVisible(False)
        root.addWidget(self._progress)

        self._status = QLabel("")
        self._status.setWordWrap(True)
        self._status.setStyleSheet("font-size:9pt; color:#555;")
        root.addWidget(self._status)

        btn_row = QHBoxLayout()
        btn_row.addStretch()

        self._reset_names_btn = QPushButton("Reset Names")
        self._reset_names_btn.setToolTip("Reset export names to source layer names")
        self._reset_names_btn.clicked.connect(self._reset_export_names)
        btn_row.addWidget(self._reset_names_btn)

        self._filter_btn = QPushButton("Set Filters")
        self._filter_btn.setToolTip("Set per-layer QGIS expression filters")
        self._filter_btn.clicked.connect(self._open_filter_dialog)
        btn_row.addWidget(self._filter_btn)

        self._log_btn = QPushButton("Show Log")
        self._log_btn.setCheckable(True)
        self._log_btn.setToolTip("Show/hide export history log")
        self._log_btn.toggled.connect(self._toggle_log)
        btn_row.addWidget(self._log_btn)

        self._export_btn = QPushButton("Export")
        self._export_btn.setStyleSheet("font-weight:bold; padding:5px 18px;")
        self._export_btn.clicked.connect(self._do_export)
        btn_row.addWidget(self._export_btn)

        root.addLayout(btn_row)

        self._log_view = QPlainTextEdit()
        self._log_view.setReadOnly(True)
        self._log_view.setMaximumBlockCount(500)
        self._log_view.setVisible(False)
        self._log_view.setStyleSheet("font-size:8pt; font-family:monospace;")
        root.addWidget(self._log_view)

    def _build_single_tab(self) -> QWidget:
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
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        refresh_btn.clicked.connect(self._refresh_layers)
        sel_row.addWidget(refresh_btn, 1)
        layout.addLayout(sel_row)

        fmt_group = QGroupBox("Default formats (used when layer format = Default)")
        fmt_grid = QGridLayout(fmt_group)
        self._format_checks: Dict[str, QCheckBox] = {}
        formats = [
            ("GeoPackage", "GPKG", ".gpkg"),
            ("Shapefile", "ESRI Shapefile", ".shp"),
            ("GeoJSON", "GeoJSON", ".geojson"),
            ("KML", "KML", ".kml"),
            ("FlatGeobuf", "FlatGeobuf", ".fgb"),
        ]
        for idx, (label, driver, _ext) in enumerate(formats):
            cb = QCheckBox(label)
            cb.setProperty("driver", driver)
            cb.stateChanged.connect(self._update_export_button_state)
            self._format_checks[driver] = cb
            fmt_grid.addWidget(cb, idx // 3, idx % 3)
        self._format_checks["GPKG"].setChecked(True)
        layout.addWidget(fmt_group)

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
            ["None", "QML", "SLD", "Both", "Embed in GPKG"]
        )
        self._single_style_combo.setCurrentIndex(1)
        style_row.addWidget(self._single_style_combo)
        style_row.addStretch()
        out_layout.addLayout(style_row)

        self._single_replace_cb = QCheckBox("Replace source in project after export")
        self._single_replace_cb.setToolTip(
            "Repoints the project layer to the new file; display name unchanged"
        )
        out_layout.addWidget(self._single_replace_cb)

        layout.addWidget(out_group)
        return tab

    def _build_gpkg_tab(self) -> QWidget:
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
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        refresh_btn.clicked.connect(self._refresh_layers)
        sel_row.addWidget(refresh_btn, 1)
        layout.addLayout(sel_row)

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

        out_layout.addLayout(opts_grid)
        layout.addWidget(out_group)
        return tab

    def _connect_project_signals(self) -> None:
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
                try:
                    sig.connect(self._on_layers_changed)
                    self._connections.append(sig)
                except Exception:
                    pass

    def disconnect_all(self) -> None:
        """Disconnect all project signals. Call from dock closeEvent."""
        self._save_settings()
        for sig in self._connections:
            try:
                sig.disconnect(self._on_layers_changed)
            except Exception:
                pass

    def _on_layers_changed(self, *_args) -> None:
        self._refresh_layers()

    def _refresh_layers(self) -> None:
        all_layers = list(QgsProject.instance().mapLayers().values())
        valid_ids = {layer.id() for layer in all_layers}
        self._filters = {
            lid: expr for lid, expr in self._filters.items() if lid in valid_ids
        }
        self._target_crs = {
            lid: crs for lid, crs in self._target_crs.items() if lid in valid_ids
        }

        for table in (self._single_table, self._gpkg_table):
            table.populate(all_layers)
            for lid, expr in self._filters.items():
                table.set_filter(lid, expr)
            for lid, authid in self._target_crs.items():
                table.set_target_crs(lid, authid)

        self._update_layer_count()
        self._update_export_button_state()

    def _update_layer_count(self) -> None:
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

    def _update_export_button_state(self) -> None:
        self._update_layer_count()
        table = self._active_table()
        has_selection = len(table.selected_layer_ids()) > 0

        if self._tabs.currentIndex() == 0:
            has_dir = bool(self._single_dir_edit.text().strip())
            has_format = any(cb.isChecked() for cb in self._format_checks.values())
            can_export = has_selection and has_dir and has_format
        else:
            has_path = bool(self._gpkg_path_edit.text().strip())
            can_export = has_selection and has_path

        self._export_btn.setEnabled(can_export)

    def _on_tab_changed(self, _index: int) -> None:
        self._update_layer_count()
        self._update_export_button_state()

    def _load_settings(self) -> None:
        s = QgsSettings()
        s.beginGroup(SETTINGS_ROOT)

        single_dir = s.value("single_dir", "", str)
        if single_dir:
            self._single_dir_edit.setText(single_dir)

        single_style = s.value("single_style_idx", 1, int)
        self._single_style_combo.setCurrentIndex(single_style)

        single_replace = s.value("single_replace", False, bool)
        self._single_replace_cb.setChecked(single_replace)

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

        saved_formats = s.value("single_formats", ["GPKG"])
        if isinstance(saved_formats, str):
            saved_formats = [saved_formats]
        if saved_formats:
            for driver, cb in self._format_checks.items():
                cb.setChecked(driver in saved_formats)

        log_text = s.value("log_text", "", str)
        if log_text:
            self._log_view.setPlainText(log_text)
            self._log_entries = log_text.strip().split("\n")

        s.endGroup()

    def _save_settings(self) -> None:
        s = QgsSettings()
        s.beginGroup(SETTINGS_ROOT)

        s.setValue("single_dir", self._single_dir_edit.text().strip())
        s.setValue("single_style_idx", self._single_style_combo.currentIndex())
        s.setValue("single_replace", self._single_replace_cb.isChecked())
        s.setValue("gpkg_path", self._gpkg_path_edit.text().strip())
        s.setValue("gpkg_overwrite", self._gpkg_overwrite_cb.isChecked())
        s.setValue("gpkg_style", self._gpkg_style_cb.isChecked())
        s.setValue("gpkg_embed", self._gpkg_embed_cb.isChecked())
        s.setValue("gpkg_replace", self._gpkg_replace_cb.isChecked())

        checked_formats = [d for d, cb in self._format_checks.items() if cb.isChecked()]
        s.setValue("single_formats", checked_formats)

        s.setValue("log_text", self._log_view.toPlainText())

        s.endGroup()
        s.sync()

    def _toggle_log(self, visible: bool) -> None:
        self._log_view.setVisible(visible)
        self._log_btn.setText("Hide Log" if visible else "Show Log")

    def _on_target_crs_changed(self, layer_id: str, authid: str) -> None:
        self._target_crs[layer_id] = authid
        for table in (self._single_table, self._gpkg_table):
            if table.get_target_crs(layer_id) != authid:
                table.set_target_crs(layer_id, authid)

    def _open_filter_dialog(self) -> None:
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
            layer_items=vector_items, current_filters=self._filters, parent=self
        )
        dlg.filter_applied.connect(self._on_filter_applied)
        dlg.exec()

    def _on_filter_applied(self, layer_id: str, expression: str) -> None:
        self._filters[layer_id] = expression
        for table in (self._single_table, self._gpkg_table):
            table.set_filter(layer_id, expression)
        self._update_layer_count()

    def _reset_export_names(self) -> None:
        for table in (self._single_table, self._gpkg_table):
            table.reset_export_names()

    def _do_export(self) -> None:
        if self._tabs.currentIndex() == 0:
            self._export_single()
        else:
            self._export_gpkg()

    def _validate_export_layer(self, lid: str, exp_name: str, table: LayerTableWidget):
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

    def _get_layer_drivers(self, lid: str, is_raster: bool) -> List[str]:
        """Return drivers to use for a layer. Respects per-layer format override."""
        override = self._single_table.get_format_override(lid)
        if override:
            return [override]
        fallback = [d for d, cb in self._format_checks.items() if cb.isChecked()]
        if not fallback:
            return ["GPKG"] if not is_raster else ["GTiff"]
        return fallback

    def _export_single(self) -> None:
        checked = self._single_table.get_selected_items()
        if not checked:
            QMessageBox.warning(self, "Nothing selected", "Check at least one layer.")
            return

        out_dir = self._single_dir_edit.text().strip()
        if not out_dir:
            QMessageBox.warning(
                self, "No output directory", "Please select an output directory."
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

        specs: List[ExportSpec] = []
        skipped: List[str] = []
        for lid, exp_name in checked:
            layer, target_crs, is_raster, error = self._validate_export_layer(
                lid, exp_name, self._single_table
            )
            if error:
                skipped.append(f"{exp_name}: {error}")
                continue

            drivers = self._get_layer_drivers(lid, is_raster)
            for driver in drivers:
                if is_raster and driver != "GPKG":
                    specs.append(
                        ExportSpec(
                            source_layer_id=lid,
                            export_name=exp_name,
                            target_mode="single",
                            output_path=out_dir,
                            driver="GTiff",
                            filter_expression=self._filters.get(lid, ""),
                            style_mode=style_mode
                            if style_mode != StyleMode.EMBED
                            else StyleMode.QML,
                            replace_in_project=replace,
                            target_crs_authid=target_crs,
                        )
                    )
                    break
                elif not is_raster:
                    specs.append(
                        ExportSpec(
                            source_layer_id=lid,
                            export_name=exp_name,
                            target_mode="single",
                            output_path=out_dir,
                            driver=driver,
                            filter_expression=self._filters.get(lid, ""),
                            style_mode=style_mode,
                            replace_in_project=replace,
                            target_crs_authid=target_crs,
                        )
                    )

        if skipped:
            QMessageBox.warning(
                self,
                "Some layers were skipped",
                "Not queued for export:\n" + "\n".join(f"- {s}" for s in skipped),
            )
        if not specs:
            return

        self._run_specs(specs)

    def _export_gpkg(self) -> None:
        checked = self._gpkg_table.get_selected_items()
        if not checked:
            QMessageBox.warning(self, "Nothing selected", "Check at least one layer.")
            return

        gpkg_path = self._gpkg_path_edit.text().strip()
        if not gpkg_path:
            QMessageBox.warning(
                self, "No output file", "Please specify a GeoPackage output path."
            )
            return
        if not gpkg_path.lower().endswith(".gpkg"):
            gpkg_path += ".gpkg"

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

        specs: List[ExportSpec] = []
        skipped: List[str] = []
        for lid, exp_name in checked:
            layer, target_crs, is_raster, error = self._validate_export_layer(
                lid, exp_name, self._gpkg_table
            )
            if error:
                skipped.append(f"{exp_name}: {error}")
                continue

            specs.append(
                ExportSpec(
                    source_layer_id=lid,
                    export_name=exp_name,
                    target_mode="gpkg",
                    output_path=gpkg_path,
                    driver="GTiff" if is_raster else "GPKG",
                    filter_expression=self._filters.get(lid, ""),
                    style_mode=style_mode,
                    replace_in_project=replace,
                    target_crs_authid=target_crs,
                )
            )

        if skipped:
            QMessageBox.warning(
                self,
                "Some layers were skipped",
                "Not queued for export:\n" + "\n".join(f"- {s}" for s in skipped),
            )
        if not specs:
            return

        self._run_specs(specs)

    def _run_specs(self, specs: List[ExportSpec]) -> None:
        if not specs:
            return

        self._export_btn.setEnabled(False)
        self._progress.setVisible(True)
        self._progress.setRange(0, len(specs))
        self._progress.setValue(0)

        start_time = time.time()
        log_lines: List[str] = []

        def progress_cb(current: int, _total: int, msg: str) -> None:
            self._progress.setValue(current)
            self._status.setText(msg)
            from qgis.PyQt.QtWidgets import QApplication

            QApplication.processEvents()

        results: List[ExportResult] = self._engine.run(specs, progress_cb=progress_cb)

        elapsed = time.time() - start_time
        self._progress.setVisible(False)
        self._export_btn.setEnabled(True)
        self._status.setText("")

        ok = sum(1 for r in results if r.success)
        fail = [r for r in results if not r.success]

        log_lines.append(
            f"[{time.strftime('%H:%M:%S')}] Export session: "
            f"{ok} ok, {len(fail)} failed ({elapsed:.1f}s)"
        )
        for r in results:
            if r.success:
                fcount = r.features_written if r.features_written else "?"
                log_lines.append(
                    f"  OK  {r.spec.export_name} -> {r.output_path} ({fcount} features)"
                )
            else:
                log_lines.append(f"  FAIL {r.spec.export_name}: {r.error}")

        self._log_entries.extend(log_lines)
        self._log_view.appendPlainText("\n".join(log_lines))

        if not self._log_view.isVisible():
            self._log_view.setVisible(True)
            self._log_btn.setChecked(True)
            self._log_btn.setText("Hide Log")

        if fail:
            QMessageBox.warning(
                self,
                "Some exports failed",
                f"{ok} succeeded, {len(fail)} failed:\n"
                + "\n".join(f"- {r.spec.export_name}: {r.error}" for r in fail),
            )
        else:
            QMessageBox.information(
                self, "Export complete", f"Successfully exported {ok} layer(s)."
            )

        self._save_settings()

    def set_active_layer(self, layer) -> None:
        """Select and scroll to a specific layer in both tables."""
        self._tabs.setCurrentIndex(1)
        self._single_table.set_active_layer(layer)
        self._gpkg_table.set_active_layer(layer)

    def _browse_single_dir(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Select Output Directory")
        if d:
            self._single_dir_edit.setText(d)

    def _browse_gpkg_path(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Save GeoPackage As", "", "GeoPackage (*.gpkg);;All Files (*)"
        )
        if path:
            if not path.lower().endswith(".gpkg"):
                path += ".gpkg"
            self._gpkg_path_edit.setText(path)

    def _active_table(self) -> LayerTableWidget:
        return (
            self._single_table if self._tabs.currentIndex() == 0 else self._gpkg_table
        )
