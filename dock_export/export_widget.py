"""
export_widget.py  –  Main tabbed export widget for the dock.

Architecture
------------
* Two tabs: "Single Files" and "GeoPackage"
* Both use LayerTableWidget → inline editable Export Name column
* Export names are read from the table at click time, injected into
  ExportSpec.export_name → engine uses SaveVectorOptions.layerName
* Live project layers are NEVER renamed
* Filter dialog operates on (layer_id, export_name) tuples only
* Export runs in the main thread with a QProgressBar
  (async via QThread is left as an optional TODO comment)
"""
from __future__ import annotations

import os
from typing import Dict, List, Optional

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
    QProgressBar,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from qgis.core import (
    QgsProject,
    QgsRasterLayer,
    QgsVectorLayer,
)

from .export_engine import ExportEngine, ExportResult
from .layer_table_widget import LayerTableWidget
from .models import ExportSpec
from .sql_filter_widget import SQLFilterDialog
from .style_manager import StyleManager


class ExportWidget(QWidget):
    """
    Top-level widget embedded in the dock.

    Design contract
    ---------------
    * reads export names from LayerTableWidget (not from live layers)
    * builds ExportSpec objects (no layer references in specs)
    * hands specs to ExportEngine.run()
    """

    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface = iface
        self._engine = ExportEngine(StyleManager())
        self._filters: Dict[str, str] = {}   # layer_id → expression
        self._filter_dialog: Optional[SQLFilterDialog] = None

        self._build_ui()
        self._refresh_layers()
        self._connect_project_signals()

    # ------------------------------------------------------------------ #
    # UI construction                                                      #
    # ------------------------------------------------------------------ #

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(6)
        root.setContentsMargins(6, 6, 6, 6)

        self._tabs = QTabWidget()
        self._tabs.addTab(self._build_single_tab(), "Single files")
        self._tabs.addTab(self._build_gpkg_tab(),   "GeoPackage")
        root.addWidget(self._tabs)

        # Progress + status
        self._progress = QProgressBar()
        self._progress.setVisible(False)
        root.addWidget(self._progress)

        self._status = QLabel("")
        self._status.setWordWrap(True)
        self._status.setStyleSheet("font-size:9pt; color:#555;")
        root.addWidget(self._status)

        # Bottom button row
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        self._filter_btn = QPushButton("Set Filters")
        self._filter_btn.setToolTip(
            "Set per-layer QGIS expression filters for selected layers"
        )
        self._filter_btn.clicked.connect(self._open_filter_dialog)
        btn_row.addWidget(self._filter_btn)

        self._export_btn = QPushButton("Export")
        self._export_btn.setStyleSheet(
            "font-weight:bold; padding:5px 18px;"
        )
        self._export_btn.clicked.connect(self._do_export)
        btn_row.addWidget(self._export_btn)

        root.addLayout(btn_row)

    # ---- Single files tab -------------------------------------------- #

    def _build_single_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(6)

        self._single_table = LayerTableWidget()
        self._single_table.export_name_changed.connect(
            self._on_export_name_changed
        )
        layout.addWidget(self._single_table)

        sel_row = QHBoxLayout()
        all_btn = QPushButton("All")
        all_btn.setMaximumWidth(60)
        all_btn.clicked.connect(self._single_table.check_all)
        sel_row.addWidget(all_btn)
        none_btn = QPushButton("None")
        none_btn.setMaximumWidth(60)
        none_btn.clicked.connect(self._single_table.uncheck_all)
        sel_row.addWidget(none_btn)
        sel_row.addStretch()
        layout.addLayout(sel_row)

        # Format selection
        fmt_group = QGroupBox("Vector formats")
        fmt_grid = QGridLayout(fmt_group)
        self._format_checks: Dict[str, QCheckBox] = {}
        formats = [
            ("GeoPackage",  "GPKG",           ".gpkg"),
            ("Shapefile",   "ESRI Shapefile",  ".shp"),
            ("GeoJSON",     "GeoJSON",         ".geojson"),
            ("KML",         "KML",             ".kml"),
            ("FlatGeobuf",  "FlatGeobuf",      ".fgb"),
        ]
        for idx, (label, driver, _ext) in enumerate(formats):
            cb = QCheckBox(label)
            cb.setProperty("driver", driver)
            self._format_checks[driver] = cb
            fmt_grid.addWidget(cb, idx // 3, idx % 3)
        self._format_checks["GPKG"].setChecked(True)
        layout.addWidget(fmt_group)

        # Output dir + style
        out_group = QGroupBox("Output")
        out_layout = QVBoxLayout(out_group)

        dir_row = QHBoxLayout()
        self._single_dir_edit = QLineEdit()
        self._single_dir_edit.setPlaceholderText("Select output directory…")
        dir_row.addWidget(self._single_dir_edit)
        browse = QPushButton("…")
        browse.setMaximumWidth(36)
        browse.clicked.connect(self._browse_single_dir)
        dir_row.addWidget(browse)
        out_layout.addLayout(dir_row)

        style_row = QHBoxLayout()
        style_row.addWidget(QLabel("Style:"))
        self._single_style_combo = QComboBox()
        self._single_style_combo.addItems(["None", "QML", "SLD", "Both", "Embed in GPKG"])
        self._single_style_combo.setCurrentIndex(1)
        style_row.addWidget(self._single_style_combo)
        style_row.addStretch()
        out_layout.addLayout(style_row)

        self._single_replace_cb = QCheckBox("Replace source in project after export")
        self._single_replace_cb.setToolTip(
            "After export, repoints the project layer to the new file\n"
            "(layer display name stays unchanged)"
        )
        out_layout.addWidget(self._single_replace_cb)

        layout.addWidget(out_group)
        return tab

    # ---- GeoPackage tab ---------------------------------------------- #

    def _build_gpkg_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(6)

        self._gpkg_table = LayerTableWidget()
        self._gpkg_table.export_name_changed.connect(
            self._on_export_name_changed
        )
        layout.addWidget(self._gpkg_table)

        sel_row = QHBoxLayout()
        all_btn = QPushButton("All")
        all_btn.setMaximumWidth(60)
        all_btn.clicked.connect(self._gpkg_table.check_all)
        sel_row.addWidget(all_btn)
        none_btn = QPushButton("None")
        none_btn.setMaximumWidth(60)
        none_btn.clicked.connect(self._gpkg_table.uncheck_all)
        sel_row.addWidget(none_btn)
        sel_row.addStretch()
        layout.addLayout(sel_row)

        out_group = QGroupBox("Output GeoPackage")
        out_layout = QVBoxLayout(out_group)

        file_row = QHBoxLayout()
        self._gpkg_path_edit = QLineEdit()
        self._gpkg_path_edit.setPlaceholderText("output.gpkg path…")
        file_row.addWidget(self._gpkg_path_edit)
        browse = QPushButton("…")
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

    # ------------------------------------------------------------------ #
    # Project signal connections                                           #
    # ------------------------------------------------------------------ #

    def _connect_project_signals(self) -> None:
        proj = QgsProject.instance()
        proj.layersAdded.connect(self._on_layers_changed)
        proj.layersRemoved.connect(self._on_layers_changed)
        root = proj.layerTreeRoot()
        root.nameChanged.connect(self._on_layers_changed)

    def disconnect_all(self) -> None:
        """Call from dock closeEvent to avoid dangling signal connections."""
        try:
            proj = QgsProject.instance()
            proj.layersAdded.disconnect(self._on_layers_changed)
            proj.layersRemoved.disconnect(self._on_layers_changed)
            proj.layerTreeRoot().nameChanged.disconnect(self._on_layers_changed)
        except Exception:
            pass

    def _on_layers_changed(self, *_args) -> None:
        self._refresh_layers()

    # ------------------------------------------------------------------ #
    # Refresh layer tables                                                 #
    # ------------------------------------------------------------------ #

    def _refresh_layers(self) -> None:
        all_layers = list(QgsProject.instance().mapLayers().values())
        # Re-apply stored filters to tables
        for table in (self._single_table, self._gpkg_table):
            table.populate(all_layers)
            for lid, expr in self._filters.items():
                table.set_filter(lid, expr)

    # ------------------------------------------------------------------ #
    # Export name changes                                                  #
    # ------------------------------------------------------------------ #

    def _on_export_name_changed(self, layer_id: str, new_name: str) -> None:
        # Keep both tables in sync (shared export name store in each table)
        # Each table tracks its own _export_names dict; that's fine – they
        # are read independently at export time.
        pass  # tables maintain their own state

    # ------------------------------------------------------------------ #
    # Filter dialog                                                        #
    # ------------------------------------------------------------------ #

    def _open_filter_dialog(self) -> None:
        table = self._active_table()
        checked = table.get_checked_items()

        # Build (layer_id, export_name) tuples for vector layers only
        vector_items = []
        for lid, exp_name in checked:
            layer = QgsProject.instance().mapLayer(lid)
            if layer and isinstance(layer, QgsVectorLayer):
                vector_items.append((lid, exp_name))

        if not vector_items:
            QMessageBox.information(
                self, "No Vector Layers",
                "Select at least one vector layer to set a filter."
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
        self._filters[layer_id] = expression
        for table in (self._single_table, self._gpkg_table):
            table.set_filter(layer_id, expression)

    # ------------------------------------------------------------------ #
    # Export dispatch                                                      #
    # ------------------------------------------------------------------ #

    def _do_export(self) -> None:
        if self._tabs.currentIndex() == 0:
            self._export_single()
        else:
            self._export_gpkg()

    # ---- Single files ------------------------------------------------- #

    def _export_single(self) -> None:
        checked = self._single_table.get_checked_items()
        if not checked:
            QMessageBox.warning(self, "Nothing selected",
                                "Check at least one layer.")
            return

        out_dir = self._single_dir_edit.text().strip()
        if not out_dir:
            QMessageBox.warning(self, "No output directory",
                                "Please select an output directory.")
            return

        if not os.path.isdir(out_dir):
            try:
                os.makedirs(out_dir, exist_ok=True)
            except OSError as e:
                QMessageBox.critical(self, "Directory error", str(e))
                return

        selected_drivers = [
            d for d, cb in self._format_checks.items() if cb.isChecked()
        ]
        if not selected_drivers:
            QMessageBox.warning(self, "No format", "Select at least one format.")
            return

        style_idx = self._single_style_combo.currentIndex()
        style_mode_map = {0: "none", 1: "qml", 2: "sld", 3: "both", 4: "embed"}
        style_mode = style_mode_map.get(style_idx, "none")
        replace = self._single_replace_cb.isChecked()

        specs: List[ExportSpec] = []
        for lid, exp_name in checked:
            layer = QgsProject.instance().mapLayer(lid)
            if layer is None:
                continue
            is_raster = isinstance(layer, QgsRasterLayer)

            for driver in selected_drivers:
                # Raster: only GTiff makes sense for single-file export
                if is_raster and driver != "GPKG":
                    raster_driver = "GTiff"
                    spec = ExportSpec(
                        source_layer_id=lid,
                        export_name=exp_name,
                        target_mode="single",
                        output_path=out_dir,
                        driver=raster_driver,
                        filter_expression=self._filters.get(lid, ""),
                        style_mode=style_mode if style_mode != "embed" else "qml",
                        replace_in_project=replace,
                    )
                    specs.append(spec)
                    break  # only one raster format
                elif not is_raster:
                    spec = ExportSpec(
                        source_layer_id=lid,
                        export_name=exp_name,
                        target_mode="single",
                        output_path=out_dir,
                        driver=driver,
                        filter_expression=self._filters.get(lid, ""),
                        style_mode=style_mode,
                        replace_in_project=replace,
                    )
                    specs.append(spec)

        self._run_specs(specs)

    # ---- GeoPackage ---------------------------------------------------- #

    def _export_gpkg(self) -> None:
        checked = self._gpkg_table.get_checked_items()
        if not checked:
            QMessageBox.warning(self, "Nothing selected",
                                "Check at least one layer.")
            return

        gpkg_path = self._gpkg_path_edit.text().strip()
        if not gpkg_path:
            QMessageBox.warning(self, "No output file",
                                "Please specify a GeoPackage output path.")
            return
        if not gpkg_path.lower().endswith(".gpkg"):
            gpkg_path += ".gpkg"

        overwrite = self._gpkg_overwrite_cb.isChecked()
        if overwrite and os.path.exists(gpkg_path):
            try:
                os.remove(gpkg_path)
            except OSError as e:
                QMessageBox.critical(
                    self, "Cannot overwrite", f"Could not delete existing file:\n{e}"
                )
                return

        save_qml = self._gpkg_style_cb.isChecked()
        embed = self._gpkg_embed_cb.isChecked()
        replace = self._gpkg_replace_cb.isChecked()

        if embed:
            style_mode = "embed"
        elif save_qml:
            style_mode = "qml"
        else:
            style_mode = "none"

        specs: List[ExportSpec] = []
        for lid, exp_name in checked:
            layer = QgsProject.instance().mapLayer(lid)
            if layer is None:
                continue
            is_raster = isinstance(layer, QgsRasterLayer)

            spec = ExportSpec(
                source_layer_id=lid,
                export_name=exp_name,
                target_mode="gpkg",
                output_path=gpkg_path,
                driver="GTiff" if is_raster else "GPKG",
                filter_expression=self._filters.get(lid, ""),
                style_mode=style_mode,
                replace_in_project=replace,
            )
            specs.append(spec)

        self._run_specs(specs)

    # ------------------------------------------------------------------ #
    # Engine runner (in-thread with progress bar)                          #
    # ------------------------------------------------------------------ #

    def _run_specs(self, specs: List[ExportSpec]) -> None:
        if not specs:
            return

        self._export_btn.setEnabled(False)
        self._progress.setVisible(True)
        self._progress.setRange(0, len(specs))
        self._progress.setValue(0)

        errors = []
        total = len(specs)

        def progress_cb(current: int, _total: int, msg: str) -> None:
            self._progress.setValue(current)
            self._status.setText(msg)
            # Force UI update (we're in the main thread)
            from qgis.PyQt.QtWidgets import QApplication
            QApplication.processEvents()

        results: List[ExportResult] = self._engine.run(
            specs, progress_cb=progress_cb
        )

        self._progress.setVisible(False)
        self._export_btn.setEnabled(True)
        self._status.setText("")

        ok = sum(1 for r in results if r.success)
        fail = [r for r in results if not r.success]

        if fail:
            err_lines = "\n".join(
                f"• {r.spec.export_name}: {r.error}" for r in fail
            )
            QMessageBox.warning(
                self, "Some exports failed",
                f"{ok} succeeded, {len(fail)} failed:\n\n{err_lines}"
            )
        else:
            QMessageBox.information(
                self, "Export complete",
                f"Successfully exported {ok} layer(s)."
            )

    # ------------------------------------------------------------------ #
    # Browse helpers                                                       #
    # ------------------------------------------------------------------ #

    def _browse_single_dir(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Select Output Directory")
        if d:
            self._single_dir_edit.setText(d)

    def _browse_gpkg_path(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Save GeoPackage As", "",
            "GeoPackage (*.gpkg);;All Files (*)"
        )
        if path:
            if not path.lower().endswith(".gpkg"):
                path += ".gpkg"
            self._gpkg_path_edit.setText(path)

    # ------------------------------------------------------------------ #
    # Helpers                                                              #
    # ------------------------------------------------------------------ #

    def _active_table(self) -> LayerTableWidget:
        return (
            self._single_table
            if self._tabs.currentIndex() == 0
            else self._gpkg_table
        )
