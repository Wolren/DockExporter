"""Plugin entry point. Manages dock widget lifecycle, toolbar, menus, and layer tree context menu."""

import os
from contextlib import suppress

from qgis.core import QgsMapLayer
from qgis.PyQt.QtCore import QPoint, Qt
from qgis.PyQt.QtGui import QAction, QIcon
from qgis.PyQt.QtWidgets import QFileDialog, QMenu, QMessageBox

from .ui.dock_widget import ExportDockWidget
from .woof.woof_storage import open_woof_project


class DockExportPlugin:
    """Creates the dock widget, toolbar icon, plugin menu, and layer tree context menu entries."""

    def __init__(self, iface):
        self.iface = iface
        self._dock: ExportDockWidget = None
        self._action: QAction = None
        self._open_woof_action: QAction = None

    def initGui(self):
        """Set up toolbar icon, plugin menus, and layer tree context menu."""
        icon_path = os.path.join(os.path.dirname(__file__), "icons", "dock_export.svg")
        self._action = QAction(QIcon(icon_path), "Dock Export", self.iface.mainWindow())
        self._action.setCheckable(True)
        self._action.triggered.connect(self._toggle_dock)
        self.iface.addToolBarIcon(self._action)
        self.iface.addPluginToMenu("&Dock Export", self._action)

        # Add "Open .woof Project..." to Plugin menu and Project → Open From
        self._open_woof_action = QAction(
            QIcon(icon_path),
            "Open .woof Project...",
            self.iface.mainWindow(),
        )
        self._open_woof_action.triggered.connect(self._on_open_woof)
        self.iface.addPluginToMenu("&Dock Export", self._open_woof_action)

        self._open_woof_parent = None
        project_menu = self.iface.projectMenu()
        if project_menu:
            for action in project_menu.actions():
                sub = action.menu()
                if sub and "open" in action.text().lower():
                    sub.addAction(self._open_woof_action)
                    self._open_woof_parent = sub
                    break
            if self._open_woof_parent is None:
                project_menu.addSeparator()
                project_menu.addAction(self._open_woof_action)
                self._open_woof_parent = project_menu

        self.layer_tree_view = self.iface.layerTreeView()
        if self.layer_tree_view:
            self.layer_tree_view.setContextMenuPolicy(
                Qt.ContextMenuPolicy.CustomContextMenu,
            )
            self._ctx_connection = self.layer_tree_view.customContextMenuRequested.connect(
                self._on_layer_tree_context_menu,
            )

    def unload(self):
        """Remove toolbar icon, menu entries, dock widget, and disconnect signals."""
        self.iface.removeToolBarIcon(self._action)
        self.iface.removePluginMenu("&Dock Export", self._action)
        self.iface.removePluginMenu("&Dock Export", self._open_woof_action)
        if self._open_woof_action and self._open_woof_parent:
            self._open_woof_parent.removeAction(self._open_woof_action)
        if self._dock:
            self.iface.removeDockWidget(self._dock)
            self._dock.deleteLater()
            self._dock = None
        if self.layer_tree_view and self._ctx_connection:
            with suppress(TypeError):
                self.layer_tree_view.customContextMenuRequested.disconnect(
                    self._on_layer_tree_context_menu,
                )

    def _toggle_dock(self, checked: bool) -> None:
        """Show or hide the export dock widget."""
        if checked:
            if self._dock is None:
                self._dock = ExportDockWidget(self.iface, self.iface.mainWindow())
                self._dock.visibilityChanged.connect(self._on_visibility_changed)
                self.iface.addDockWidget(
                    Qt.DockWidgetArea.RightDockWidgetArea,
                    self._dock,
                )
            self._dock.show()
        elif self._dock:
            self._dock.hide()

    def _on_open_woof(self) -> None:
        """Show a file picker for .woof archives, then extract and open the project."""
        path, _ = QFileDialog.getOpenFileName(
            self.iface.mainWindow(),
            "Open .woof Project",
            "",
            "Woof archive (*.woof);;All Files (*)",
        )
        if not path:
            return

        if not open_woof_project(path):
            QMessageBox.warning(
                self.iface.mainWindow(),
                "Open Woof",
                f"Could not open {os.path.basename(path)}.\n"
                "Make sure the file is a valid .woof archive.",
            )

    def _on_visibility_changed(self, visible: bool) -> None:
        """Sync toolbar button checked state with dock visibility."""
        if self._action:
            self._action.setChecked(visible)

    def _on_layer_tree_context_menu(self, point: QPoint) -> None:
        """Inject 'Export with Dock exporter' action into the layer tree context menu."""
        if not self.layer_tree_view or not self.layer_tree_view.menuProvider():
            return

        index = self.layer_tree_view.indexAt(point)
        if not index.isValid():
            return

        node = self.layer_tree_view.currentNode()
        if node is None or not node.layer():
            return

        layer = node.layer()
        if layer.type() not in (
            QgsMapLayer.LayerType.VectorLayer,
            QgsMapLayer.LayerType.RasterLayer,
        ):
            return

        menu: QMenu = self.layer_tree_view.menuProvider().createContextMenu()

        menu.addSeparator()
        action = menu.addAction("Export with Dock exporter...")
        action.triggered.connect(lambda: self._open_dock_export_for_layer(layer))

        global_pos = self.layer_tree_view.viewport().mapToGlobal(point)
        menu.exec(global_pos)

    def _open_dock_export_for_layer(self, layer) -> None:
        """Open the dock and select *layer* in the export table."""
        if self._dock is None:
            self._toggle_dock(True)
        else:
            self._dock.show()

        self._dock.raise_()

        if hasattr(self._dock, "set_active_layer"):
            self._dock.set_active_layer(layer)
