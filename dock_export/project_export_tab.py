"""Tab for packaging the entire QGIS project into a single portable file.

Two modes:
  - GeoPackage export: re-writes all layer data into a single .gpkg (captures WMS)
  - .woof archive: bundles original source files + project into a ZIP with .woof extension"""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
from typing import Dict, List, Optional, Set, Tuple

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from qgis.core import (
    Qgis,
    QgsApplication,
    QgsDataProvider,
    QgsMapLayer,
    QgsProject,
    QgsRasterLayer,
    QgsVectorFileWriter,
    QgsVectorLayer,
)

from .export_engine import ExportEngine, layer_export_block_reason
from .woof_format import pack_woof_from_directory

logger = logging.getLogger("DockExport.ProjectExport")


def _source_file_path(layer: QgsMapLayer) -> Optional[str]:
    """Extract the main source file path from a layer, or None if not file-based."""
    src = (layer.source() or "").split("|")[0].strip()
    if not src or src.startswith(
        ("wms:", "wmts:", "xyz:", "http://", "https://", "postgresql:", "postgis:")
    ):
        return None
    if os.path.isfile(src) or os.path.isdir(src):
        return src
    return None


def _collect_source_files(layers: List[QgsMapLayer]) -> Dict[str, List[str]]:
    """Collect all underlying files for each source path.

    Uses GDAL GetFileList to find companion files (e.g. .shx, .dbf for .shp).
    Returns {source_path: [list_of_file_paths]}.
    """
    from osgeo import gdal

    collected: Dict[str, List[str]] = {}
    seen: Set[str] = set()

    for layer in layers:
        src = _source_file_path(layer)
        if not src or src in seen:
            continue
        seen.add(src)

        try:
            # Normalize path
            norm = os.path.normpath(src)
            ds = gdal.OpenEx(norm)
            if ds is not None:
                fl = ds.GetFileList()
                ds = None
                if fl:
                    collected[norm] = [os.path.normpath(f) for f in fl]
                    continue
        except Exception:
            pass

        # Fallback: just the source file itself
        collected[norm] = [norm]

    return collected


class ProjectExportTab(QWidget):
    """Tab that exports all project layers into a single portable file.

    Two modes (radio):
      - GeoPackage export with WMS capture
      - .woof archive (ZIP with source files + project)
    """

    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface = iface
        self._engine = ExportEngine()
        self._mode = "woof"  # "woof" or "gpkg"
        self._build_ui()
        self._refresh_table()

    # ── UI ──────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(6)

        # Layer table
        self._table = QTableWidget(0, 3)
        self._table.setHorizontalHeaderLabels(["", "Layer name", "Source"])
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.verticalHeader().setVisible(False)
        hh = self._table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self._table.setColumnWidth(0, 28)
        layout.addWidget(self._table)

        # Mode selector
        mode_group = QGroupBox("Packaging mode")
        mode_layout = QHBoxLayout(mode_group)
        self._mode_group = QButtonGroup(self)
        self._woof_rb = QRadioButton("Package as .woof archive")
        self._woof_rb.setChecked(True)
        self._woof_rb.toggled.connect(self._on_mode_toggled)
        self._mode_group.addButton(self._woof_rb)
        mode_layout.addWidget(self._woof_rb)
        self._gpkg_rb = QRadioButton("Export to GeoPackage (captures WMS)")
        self._mode_group.addButton(self._gpkg_rb)
        mode_layout.addWidget(self._gpkg_rb)
        mode_layout.addStretch()
        layout.addWidget(mode_group)

        # Output group (shared)
        out_group = QGroupBox("Output")
        out_layout = QVBoxLayout(out_group)

        path_row = QHBoxLayout()
        self._path_edit = QLineEdit()
        self._path_edit.setPlaceholderText("Select output path...")
        path_row.addWidget(self._path_edit)
        browse_btn = QPushButton("...")
        browse_btn.setMaximumWidth(36)
        browse_btn.clicked.connect(self._browse_path)
        path_row.addWidget(browse_btn)
        out_layout.addLayout(path_row)

        # GPKG-specific options
        self._gpkg_opts = QHBoxLayout()
        self._repoint_cb = QCheckBox("Repoint layers to GPKG")
        self._repoint_cb.setToolTip(
            "Update all layer data sources to point into the GPKG"
        )
        self._repoint_cb.setChecked(True)
        self._gpkg_opts.addWidget(self._repoint_cb)
        out_layout.addLayout(self._gpkg_opts)

        # .woof-specific options
        self._woof_opts = QHBoxLayout()
        self._woof_compress_cb = QCheckBox("Compress (deflate)")
        self._woof_compress_cb.setChecked(True)
        self._woof_compress_cb.setToolTip("Compress data within the archive")
        self._woof_opts.addWidget(self._woof_compress_cb)
        out_layout.addLayout(self._woof_opts)

        self._info_label = QLabel("")
        self._info_label.setStyleSheet("font-size:9pt; color:#555;")
        out_layout.addWidget(self._info_label)

        layout.addWidget(out_group)

        self._progress = QProgressBar()
        self._progress.setVisible(False)
        layout.addWidget(self._progress)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self._export_btn = QPushButton("Export Project")
        self._export_btn.setStyleSheet("font-weight:bold; padding:5px 18px;")
        self._export_btn.clicked.connect(self._do_export)
        btn_row.addWidget(self._export_btn)
        layout.addLayout(btn_row)

        self._sync_ui_to_mode()

    def _on_mode_toggled(self) -> None:
        self._mode = "woof" if self._woof_rb.isChecked() else "gpkg"
        self._sync_ui_to_mode()
        self._path_edit.clear()

    def _sync_ui_to_mode(self) -> None:
        is_woof = self._mode == "woof"
        self._gpkg_opts.itemAt(0).widget().setVisible(not is_woof)
        self._woof_opts.itemAt(0).widget().setVisible(is_woof)
        self._path_edit.setPlaceholderText(
            "Select .woof output path..." if is_woof else "Select .gpkg output path..."
        )

    def _browse_path(self) -> None:
        if self._mode == "woof":
            path, _ = QFileDialog.getSaveFileName(
                self, "Save project archive", "", "Woof archive (*.woof);;All Files (*)"
            )
            if path:
                if not path.lower().endswith(".woof"):
                    path += ".woof"
                self._path_edit.setText(path)
        else:
            path, _ = QFileDialog.getSaveFileName(
                self,
                "Save project GeoPackage",
                "",
                "GeoPackage (*.gpkg);;All Files (*)",
            )
            if path:
                if not path.lower().endswith(".gpkg"):
                    path += ".gpkg"
                self._path_edit.setText(path)

    # ── Table ───────────────────────────────────────────────────────

    def _refresh_table(self) -> None:
        layers = list(QgsProject.instance().mapLayers().values())
        self._table.setRowCount(0)
        for layer in layers:
            row = self._table.rowCount()
            self._table.insertRow(row)

            chk = QTableWidgetItem("")
            chk.setFlags(
                Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsSelectable
                | Qt.ItemFlag.ItemIsUserCheckable
            )
            chk.setCheckState(Qt.CheckState.Checked)
            chk.setData(Qt.ItemDataRole.UserRole, layer.id())
            rsn = layer_export_block_reason(layer)
            if rsn:
                chk.setCheckState(Qt.CheckState.Unchecked)
                chk.setFlags(Qt.ItemFlag.ItemIsEnabled)
                chk.setToolTip(rsn)
            self._table.setItem(row, 0, chk)

            name_item = QTableWidgetItem(layer.name())
            name_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            name_item.setData(Qt.ItemDataRole.UserRole, layer.id())
            self._table.setItem(row, 1, name_item)

            provider = layer.providerType() or ""
            src = layer.source() or ""
            if provider in ("wms", "wmts", "xyz"):
                summary = f"{provider.upper()} (remote)"
            else:
                local = _source_file_path(layer)
                summary = os.path.basename(local) if local else provider
            src_item = QTableWidgetItem(summary)
            src_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            self._table.setItem(row, 2, src_item)

        self._update_info()

    def _update_info(self) -> None:
        total = self._table.rowCount()
        remote = file_count = 0
        for row in range(total):
            txt = self._table.item(row, 2).text() if self._table.item(row, 2) else ""
            if "remote" in txt:
                remote += 1
            else:
                file_count += 1
        if self._mode == "woof":
            parts = [f"{total} layers"]
            if file_count:
                parts.append(f"{file_count} file-based")
            if remote:
                parts.append(f"{remote} remote (skipped)")
            self._info_label.setText(", ".join(parts))
        else:
            parts = [f"{total} layers"]
            if remote:
                parts.append(f"{remote} remote (will be downloaded)")
            self._info_label.setText(", ".join(parts))

    # ── Export dispatch ─────────────────────────────────────────────

    def _get_checked_layers(self) -> List[QgsMapLayer]:
        result: List[QgsMapLayer] = []
        for row in range(self._table.rowCount()):
            chk = self._table.item(row, 0)
            if chk and chk.checkState() == Qt.CheckState.Checked:
                lid = chk.data(Qt.ItemDataRole.UserRole)
                layer = QgsProject.instance().mapLayer(lid)
                if layer:
                    result.append(layer)
        return result

    def _do_export(self) -> None:
        out_path = self._path_edit.text().strip()
        if not out_path:
            QMessageBox.warning(self, "No output", "Select an output path.")
            return

        layers = self._get_checked_layers()
        if not layers:
            QMessageBox.warning(self, "Nothing selected", "No layers checked.")
            return

        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)

        if self._mode == "woof":
            self._do_woof_export(out_path, layers)
        else:
            self._do_gpkg_export(out_path, layers)

    # ── GPKG export ─────────────────────────────────────────────────

    def _do_gpkg_export(self, gpkg_path: str, layers: List[QgsMapLayer]) -> None:
        if os.path.exists(gpkg_path):
            reply = QMessageBox.question(
                self,
                "Overwrite?",
                f"{os.path.basename(gpkg_path)} already exists. Overwrite?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
            try:
                os.remove(gpkg_path)
            except OSError as e:
                QMessageBox.critical(self, "Error", str(e))
                return

        self._progress.setVisible(True)
        self._progress.setMaximum(len(layers))
        self._progress.setValue(0)
        self._export_btn.setEnabled(False)

        errors: List[str] = []
        ok_count = 0

        for i, layer in enumerate(layers):
            self._progress.setValue(i + 1)
            table_name = layer.name()
            try:
                if isinstance(layer, QgsVectorLayer):
                    ok, err = self._export_vector_to_gpkg(layer, gpkg_path, table_name)
                elif isinstance(layer, QgsRasterLayer):
                    ok, err = self._export_raster_to_gpkg(layer, gpkg_path, table_name)
                else:
                    ok, err = False, "Unsupported layer type"
                if ok:
                    ok_count += 1
                else:
                    errors.append(f"{layer.name()}: {err}")
            except Exception as exc:
                errors.append(f"{layer.name()}: {exc}")

        self._progress.setVisible(False)
        self._export_btn.setEnabled(True)

        if self._repoint_cb.isChecked():
            self._repoint_layers_to_gpkg(gpkg_path, layers)

        proj_path = os.path.splitext(gpkg_path)[0] + ".qgs"
        QgsProject.instance().write(proj_path)

        msg = f"Exported {ok_count}/{len(layers)} layers to GPKG."
        if errors:
            msg += "\n\nErrors:\n" + "\n".join(f"- {e}" for e in errors)
            QMessageBox.warning(self, "Project Export", msg)
        else:
            QMessageBox.information(self, "Project Export", msg)

    def _export_vector_to_gpkg(
        self, layer: QgsVectorLayer, gpkg_path: str, table_name: str
    ) -> Tuple[bool, str]:
        options = QgsVectorFileWriter.SaveVectorOptions()
        options.driverName = "GPKG"
        options.layerName = table_name
        options.fileEncoding = "UTF-8"
        options.symbologyExport = Qgis.FeatureSymbologyExport.NoSymbology
        options.actionOnExistingFile = (
            QgsVectorFileWriter.ActionOnExistingFile.CreateOrOverwriteLayer
            if os.path.exists(gpkg_path)
            else QgsVectorFileWriter.ActionOnExistingFile.CreateOrOverwriteFile
        )
        tc = QgsProject.instance().transformContext()
        writer = QgsVectorFileWriter.create(
            gpkg_path,
            layer.fields(),
            layer.wkbType(),
            layer.crs(),
            tc,
            options,
        )
        if writer is None:
            return False, "QgsVectorFileWriter.create() returned None"
        if writer.hasError() != QgsVectorFileWriter.WriterError.NoError:
            return False, writer.errorMessage()
        if not writer.addFeatures(layer.getFeatures()):
            return False, writer.errorMessage() or "Failed to add features"
        return True, ""

    def _export_raster_to_gpkg(
        self, layer: QgsRasterLayer, gpkg_path: str, table_name: str
    ) -> Tuple[bool, str]:
        provider = layer.providerType().lower()
        src = layer.source() or ""
        if provider == "gdal" and not src.startswith(
            ("wms:", "wmts:", "xyz:", "http://", "https://")
        ):
            from osgeo import gdal

            try:
                gdal.UseExceptions()
                src_ds = gdal.Open(src)
                if src_ds is None:
                    return False, f"GDAL could not open {src}"
                gdal.Translate(
                    gpkg_path,
                    src_ds,
                    format="GPKG",
                    creationOptions=[
                        f"RASTER_TABLE={table_name}",
                        "APPEND_SUBDATASET=YES",
                    ],
                )
                return True, ""
            except Exception as exc:
                return False, f"GDAL error: {exc}"
        # Remote raster (WMS etc.) — use QGIS raster pipe
        return self._engine.export_raster_to_gpkg_via_pipe(layer, gpkg_path, table_name)

    def _repoint_layers_to_gpkg(
        self, gpkg_path: str, layers: List[QgsMapLayer]
    ) -> None:
        proj = QgsProject.instance()
        opts = QgsDataProvider.ProviderOptions()
        opts.transformContext = proj.transformContext()
        for layer in layers:
            try:
                if isinstance(layer, QgsRasterLayer):
                    layer.setDataSource(
                        f"GPKG:{gpkg_path}:{layer.name()}", layer.name(), "gdal", opts
                    )
                else:
                    layer.setDataSource(
                        f"{gpkg_path}|layername={layer.name()}",
                        layer.name(),
                        "ogr",
                        opts,
                    )
            except Exception as exc:
                logger.warning("Could not repoint '%s': %s", layer.name(), exc)

    # ── .woof packaging ─────────────────────────────────────────────

    @staticmethod
    def _find_common_parent(paths: List[str]) -> str:
        """Find the longest common parent directory across all paths.

        Falls back to drive letter roots on Windows if no common path.
        """
        try:
            common = os.path.commonpath(paths)
            if common and os.path.isdir(common):
                return common
        except ValueError:
            pass
        # Fallback: use the first path's drive root
        drive = os.path.splitdrive(paths[0])[0]
        return drive + os.sep if drive else os.path.sep

    def _do_woof_export(self, woof_path: str, layers: List[QgsMapLayer]) -> None:
        self._export_btn.setEnabled(False)
        self._progress.setVisible(True)
        self._progress.setMaximum(100)
        self._progress.setValue(0)
        self._info_label.setText("Collecting source files...")

        errors: List[str] = []
        remote_names: List[str] = []

        # 1. Collect source files
        source_map = _collect_source_files(layers)
        all_files: List[str] = []
        for flist in source_map.values():
            all_files.extend(flist)
        all_files = list(dict.fromkeys(all_files))  # deduplicate preserving order

        # 2. Identify remote-only layers
        for layer in layers:
            if not _source_file_path(layer):
                remote_names.append(layer.name())

        if not all_files:
            QMessageBox.warning(
                self,
                "No local files",
                "The selected layers have only remote sources (WMS/WMTS/DB). "
                "Nothing to package. Use GeoPackage mode instead to capture them.",
            )
            self._progress.setVisible(False)
            self._export_btn.setEnabled(True)
            return

        # 3. Copy files into a temp directory preserving structure
        tmpdir = tempfile.mkdtemp(prefix="woof_")
        data_dir = os.path.join(tmpdir, "data")
        common_parent = self._find_common_parent(all_files)
        copied = 0

        # old_path -> new_path inside data/
        path_map: Dict[str, str] = {}
        for filepath in all_files:
            if not os.path.exists(filepath):
                errors.append(f"Missing: {filepath}")
                continue
            try:
                rel = os.path.relpath(filepath, common_parent)
            except ValueError:
                rel = filepath.replace(":", "_").replace("\\", "/").lstrip("/")
            dst = os.path.join(data_dir, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            if not os.path.exists(dst):
                shutil.copy2(filepath, dst)
            path_map[os.path.normpath(filepath)] = dst
            copied += 1

        # 4. Temporarily repoint layer sources to the copied files
        proj = QgsProject.instance()
        orig_relative = proj.readNumEntry("Paths", "/Relative", 0)[0]
        saved_sources: Dict[str, str] = {}  # layer_id -> original source
        provider_opts = QgsDataProvider.ProviderOptions()
        provider_opts.transformContext = proj.transformContext()

        try:
            for layer in layers:
                src = _source_file_path(layer)
                if not src:
                    continue
                norm_src = os.path.normpath(src)
                new_path = path_map.get(norm_src)
                if new_path is None:
                    continue
                saved_sources[layer.id()] = layer.source()

                new_uri = self._rebuild_source_uri(layer, norm_src, new_path)
                if new_uri:
                    try:
                        new_provider = layer.providerType()
                        layer.setDataSource(
                            new_uri, layer.name(), new_provider, provider_opts
                        )
                    except Exception as e:
                        errors.append(f"Could not repoint '{layer.name()}': {e}")

            # 5. Save project with relative paths
            proj.writeEntry("Paths", "/Relative", 2)  # relative to project dir
            proj_path = os.path.join(tmpdir, "project.qgs")
            self._info_label.setText("Saving project file...")
            QgsApplication.processEvents()
            if not proj.write(proj_path):
                errors.append("Failed to save project file")

        finally:
            # 6. Restore original layer sources
            for layer in layers:
                old_uri = saved_sources.get(layer.id())
                if old_uri:
                    try:
                        layer.setDataSource(
                            old_uri, layer.name(), layer.providerType(), provider_opts
                        )
                    except Exception as e:
                        errors.append(f"Could not restore '{layer.name()}': {e}")
            proj.writeEntry("Paths", "/Relative", orig_relative)

        # 7. Create .woof archive using custom binary format
        self._info_label.setText("Creating archive...")
        self._progress.setValue(90)

        try:
            woof_data = pack_woof_from_directory(
                tmpdir, compress=self._woof_compress_cb.isChecked()
            )
            with open(woof_path, "wb") as f:
                f.write(woof_data)
        except Exception as exc:
            errors.append(f"Failed to create .woof: {exc}")

        shutil.rmtree(tmpdir, ignore_errors=True)

        self._info_label.setText("Done")

        # Summary
        lines = [f"Packaged {copied} source files into:", f"  {woof_path}"]
        lines.append("\nExtract the archive, then open project.qgs")
        if remote_names:
            lines.append(f"\nRemote layers (not packaged): {', '.join(remote_names)}")
        if errors:
            lines.append("\nWarnings:")
            lines.extend(f"  - {e}" for e in errors)
            QMessageBox.warning(self, "Woof Export", "\n".join(lines))
        else:
            QMessageBox.information(self, "Woof Export", "\n".join(lines))

        self._progress.setVisible(False)
        self._export_btn.setEnabled(True)

    def _rebuild_source_uri(
        self, layer: QgsMapLayer, old_path: str, new_path: str
    ) -> Optional[str]:
        """Rebuild a layer's data source URI replacing old_path with new_path."""
        source = layer.source()
        provider = layer.providerType().lower()

        if provider == "ogr":
            if "|layername=" in source:
                parts = source.split("|layername=", 1)
                return f"{new_path}|layername={parts[1]}"
            else:
                return new_path

        if provider == "gdal":
            if source.startswith("GPKG:"):
                # GPKG:/old/path/file.gpkg:layername
                # parts = ["GPKG", "/old/path/file.gpkg", "layername"]
                parts = source.split(":", 2)
                if len(parts) == 3:
                    return f"GPKG:{new_path}:{parts[2]}"
            return new_path

        # Unknown provider — just replace the path portion in the source string
        try:
            return source.replace(old_path, new_path, 1)
        except Exception:
            return new_path
