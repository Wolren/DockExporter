"""Tab for packaging the entire QGIS project into a single portable file.

Two modes:
  - .woof archive: custom binary format with deduplication
  - ZIP archive: standard .zip file with source files + project"""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
import zipfile
from typing import Dict, List, Optional, Set, Tuple


from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QButtonGroup,
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
    QgsApplication,
    QgsMapLayer,
    QgsProject,
)

from .export_engine import layer_export_block_reason
from .woof_format import pack_woof_to_file

logger = logging.getLogger("DockExport.ProjectExport")


def _source_file_path(layer: QgsMapLayer) -> Optional[str]:
    """Extract the main source file path from a layer, or None if not file-based."""
    raw = layer.source() or ""
    src = raw.split("|")[0].strip()

    # Handle GPKG:path:layername raster URIs (path may contain drive letter on Windows)
    if src.startswith("GPKG:"):
        inner = src[5:]
        path_part = inner.rsplit(":", 1)[0]  # split layername from right
        if os.path.isfile(path_part) or os.path.isdir(path_part):
            return os.path.normpath(path_part)

    if not src or src.startswith(
        (
            "wms:",
            "wmts:",
            "xyz:",
            "wcs:",
            "wfs:",
            "http://",
            "https://",
            "postgresql:",
            "postgis:",
        )
    ):
        return None
    if not os.path.isabs(src):
        proj_path = QgsProject.instance().fileName()
        if proj_path:
            proj_dir = os.path.dirname(proj_path)
            src = os.path.normpath(os.path.join(proj_dir, src))
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


_SIDECAR_EXTS = frozenset(
    {".qml", ".sld", ".tfw", ".pgw", ".jgw", ".gw", ".wld", ".aux.xml"}
)


def _collect_sidecar_files(file_paths: List[str]) -> List[str]:
    """Find companion files (QML, SLD, world files) alongside source files."""
    found: List[str] = []
    seen = set(file_paths)
    for fp in file_paths:
        base, _ = os.path.splitext(fp)
        for ext in _SIDECAR_EXTS:
            companion = base + ext
            if os.path.isfile(companion) and companion not in seen:
                found.append(companion)
                seen.add(companion)
    return found


def _collect_project_resources() -> List[str]:
    """Scan the project for external files referenced outside of layers.

    Catches layout picture sources, HTML files, SVGs, report templates,
    and any file path exposed by QgsLayoutItem subclasses.
    """
    resources: List[str] = []
    mgr = QgsProject.instance().layoutManager()
    if not mgr:
        return resources

    _all_layouts = list(mgr.layouts())
    if hasattr(mgr, "reportLayouts"):
        _all_layouts.extend(mgr.reportLayouts())
    for layout in _all_layouts:
        for item in layout.items():
            try:
                # Picture item (images, SVGs, raster fills)
                path = None
                if hasattr(item, "picturePath"):
                    path = item.picturePath()
                elif hasattr(item, "sourcePath"):
                    path = item.sourcePath()
                if path and os.path.isfile(path):
                    resources.append(os.path.normpath(path))

                # HTML item file sources
                if hasattr(item, "sourceUrl"):
                    url = item.sourceUrl()
                    if url and os.path.isfile(url):
                        resources.append(os.path.normpath(url))

                # SVG items (annotations, stamps)
                if hasattr(item, "svgFilePath"):
                    svg = item.svgFilePath()
                    if svg and os.path.isfile(svg):
                        resources.append(os.path.normpath(svg))

            except Exception:
                pass

        # External layout templates referenced by the layout itself
        try:
            template = layout.templatePath()
            if template and os.path.isfile(template):
                resources.append(os.path.normpath(template))
        except Exception:
            pass

    return list(dict.fromkeys(resources))


class ProjectExportTab(QWidget):
    """Tab that exports all project layers into a single portable file.

    Two modes (radio):
      - .woof archive: custom binary format with deduplication
      - ZIP archive: standard .zip file with source files + project
    """

    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface = iface
        self._mode = "woof"  # "woof" or "zip"
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
        self._zip_rb = QRadioButton("Export as ZIP")
        self._mode_group.addButton(self._zip_rb)
        mode_layout.addWidget(self._zip_rb)
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
        self._mode = "woof" if self._woof_rb.isChecked() else "zip"
        self._sync_ui_to_mode()
        self._path_edit.clear()

    def _sync_ui_to_mode(self) -> None:
        is_woof = self._mode == "woof"
        self._path_edit.setPlaceholderText(
            "Select .woof output path..." if is_woof else "Select .zip output path..."
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
                "Save project ZIP",
                "",
                "ZIP archive (*.zip);;All Files (*)",
            )
            if path:
                if not path.lower().endswith(".zip"):
                    path += ".zip"
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

            local = _source_file_path(layer)
            if local:
                summary = os.path.basename(local)
            elif layer.providerType() == "memory":
                summary = "scratch (not packaged)"
            else:
                summary = f"{layer.providerType()} (remote)"
            src_item = QTableWidgetItem(summary)
            src_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            self._table.setItem(row, 2, src_item)

        self._update_info()

    def _update_info(self) -> None:
        total = self._table.rowCount()
        file_count = remote = scratch = 0
        for row in range(total):
            txt = self._table.item(row, 2).text() if self._table.item(row, 2) else ""
            if "remote" in txt:
                remote += 1
            elif "scratch" in txt:
                scratch += 1
            else:
                file_count += 1
        parts = [f"{total} layers"]
        if file_count:
            parts.append(f"{file_count} file-based")
        if remote:
            parts.append(f"{remote} remote")
        if scratch:
            parts.append(f"{scratch} scratch")
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
            self._do_zip_export(out_path, layers)

    # ── Archive packaging (shared between .woof and .zip) ───────────

    @staticmethod
    def _find_common_parent(paths: List[str]) -> str:
        """Find the longest common parent directory across all paths.

        Falls back to the project directory, then to the first path's drive root.
        """
        try:
            common = os.path.commonpath(paths)
            if common and os.path.isdir(common):
                return common
        except ValueError:
            pass
        # Fallback: use the project directory (avoids ugly cross-drive paths)
        proj_file = QgsProject.instance().fileName()
        if proj_file:
            proj_dir = os.path.dirname(proj_file)
            if os.path.isdir(proj_dir):
                return proj_dir
        # Last resort: use the first path's drive root
        drive = os.path.splitdrive(paths[0])[0]
        return drive + os.sep if drive else os.path.sep

    def _prepare_archive_bundle(
        self, layers: List[QgsMapLayer]
    ) -> Optional[Tuple[List[str], Dict[str, str], str, List[str], List[str]]]:
        """Collect source files, save project with rewritten datasources.

        Remote layers preserve their original datasource URLs in the project XML.
        Returns (all_files, path_map, tmpdir, errors, remote_names).
        Caller must clean up tmpdir.  Returns None on abort.
        """
        self._export_btn.setEnabled(False)
        self._progress.setVisible(True)
        self._progress.setMaximum(100)
        self._progress.setValue(0)
        self._info_label.setText("Collecting source files...")

        errors: List[str] = []
        remote_names: List[str] = []

        # 1. Collect file-based sources
        self._progress.setValue(5)
        source_map = _collect_source_files(layers)
        all_files = list(
            dict.fromkeys(f for flist in source_map.values() for f in flist)
        )

        # 2. Collect companion sidecar files (QML/SLD styles, world files)
        self._progress.setValue(10)
        all_files.extend(_collect_sidecar_files(all_files))

        # 3. Collect project-wide external resources (layout images, SVGs, HTML)
        self._progress.setValue(15)
        all_files.extend(_collect_project_resources())
        all_files = list(dict.fromkeys(all_files))

        for layer in layers:
            if not _source_file_path(layer):
                remote_names.append(layer.name())

        # 4. Create temp workspace for project file
        self._progress.setValue(20)
        tmpdir = tempfile.mkdtemp(prefix="bundle_")

        try:
            # 5. Build path map (remote layers preserve their original datasource URLs)
            self._progress.setValue(30)
            common_parent = self._find_common_parent(all_files) if all_files else tmpdir
            path_map: Dict[str, str] = {}
            for filepath in all_files:
                if not os.path.exists(filepath):
                    errors.append(f"Missing: {filepath}")
                    continue
                try:
                    rel = os.path.relpath(filepath, common_parent)
                except ValueError:
                    rel = filepath.replace(":", "_").replace("\\", "/").lstrip("/")
                path_map[os.path.normpath(filepath)] = rel.replace(os.sep, "/")

            if not all_files and not remote_names:
                QMessageBox.warning(
                    self,
                    "No files to package",
                    "No layers with source files or remote links selected.",
                )
                self._progress.setVisible(False)
                self._export_btn.setEnabled(True)
                return None

            # 6. Save project (paths will be made relative in XML post-processing)
            self._progress.setValue(80)
            proj_path = os.path.join(tmpdir, "project.qgs")
            self._info_label.setText("Saving project file...")
            QgsApplication.processEvents()
            if not QgsProject.instance().write(proj_path):
                raise RuntimeError("Failed to save project file")

            # 7. Rewrite datasource paths in XML
            self._progress.setValue(85)
            self._info_label.setText("Rewriting project paths…")
            self._rewrite_project_sources(proj_path, path_map)

        except Exception as exc:
            shutil.rmtree(tmpdir, ignore_errors=True)
            QMessageBox.warning(self, "Export", str(exc))
            self._progress.setVisible(False)
            self._export_btn.setEnabled(True)
            return None

        return all_files, path_map, tmpdir, errors, remote_names

    def _do_woof_export(self, woof_path: str, layers: List[QgsMapLayer]) -> None:
        result = self._prepare_archive_bundle(layers)
        if result is None:
            return
        all_files, path_map, tmpdir, errors, remote_names = result

        self._info_label.setText("Creating .woof archive...")
        self._progress.setValue(90)

        try:

            def _iter_entries():
                qgs = os.path.join(tmpdir, "project.qgs")
                with open(qgs, "rb") as f:
                    yield "project.qgs", f.read()
                for filepath in all_files:
                    norm = os.path.normpath(filepath)
                    arcname = path_map.get(norm)
                    if arcname:
                        with open(filepath, "rb") as f:
                            yield arcname, f.read()

            pack_woof_to_file(woof_path, _iter_entries(), compress=True)
        except Exception as exc:
            errors.append(f"Failed to create .woof: {exc}")
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

        self._finish_export(woof_path, len(path_map), errors, remote_names)

    def _do_zip_export(self, zip_path: str, layers: List[QgsMapLayer]) -> None:
        result = self._prepare_archive_bundle(layers)
        if result is None:
            return
        all_files, path_map, tmpdir, errors, remote_names = result

        self._info_label.setText("Creating ZIP archive...")
        self._progress.setValue(90)

        try:
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                qgs = os.path.join(tmpdir, "project.qgs")
                zf.write(qgs, "project.qgs")
                for filepath in all_files:
                    norm = os.path.normpath(filepath)
                    arcname = path_map.get(norm)
                    if arcname:
                        zf.write(filepath, arcname)
        except Exception as exc:
            errors.append(f"Failed to create ZIP: {exc}")
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

        self._finish_export(zip_path, len(path_map), errors, remote_names)

    def _finish_export(
        self,
        out_path: str,
        count: int,
        errors: List[str],
        remote_names: List[str],
    ) -> None:
        self._info_label.setText("Done")
        lines = [f"Packaged {count} source files into:", f"  {out_path}"]
        lines.append("\nExtract the archive, then open project.qgs")
        if remote_names:
            lines.append(f"\nRemote layers (not packaged): {', '.join(remote_names)}")
        if errors:
            lines.append("\nWarnings:")
            lines.extend(f"  - {e}" for e in errors)
            QMessageBox.warning(self, "Export", "\n".join(lines))
        else:
            QMessageBox.information(self, "Export", "\n".join(lines))
        self._progress.setVisible(False)
        self._export_btn.setEnabled(True)

    @staticmethod
    def _rewrite_project_sources(proj_path: str, path_map: Dict[str, str]) -> None:
        """Rewrite datasource paths in a .qgs file to point into the archive."""
        proj_src = QgsProject.instance().fileName()
        original_proj_dir = os.path.dirname(proj_src) if proj_src else None

        with open(proj_path, "r", encoding="utf-8") as f:
            xml = f.read()

        # Replace original absolute paths with archive-relative paths
        for orig_path, arcname in path_map.items():
            abs_form = orig_path.replace("\\", "/")
            xml = xml.replace(abs_form, arcname)
            if original_proj_dir:
                try:
                    rel = os.path.relpath(orig_path, original_proj_dir).replace(
                        "\\", "/"
                    )
                    if rel != abs_form:
                        xml = xml.replace(rel, arcname)
                except ValueError:
                    pass

        # Force project to use paths relative to project file
        xml = xml.replace(
            '<Relative type="int">0</Relative>', '<Relative type="int">2</Relative>'
        )
        xml = xml.replace(
            '<Relative type="int">1</Relative>', '<Relative type="int">2</Relative>'
        )

        with open(proj_path, "w", encoding="utf-8") as f:
            f.write(xml)
