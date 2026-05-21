"""Plugin entry point for Dock Export. Manages dock widget lifecycle and context menu."""

from qgis.PyQt.QtCore import Qt, QPoint
from qgis.PyQt.QtWidgets import QAction, QMenu
from qgis.core import QgsMapLayer, QgsProject

from .dock_widget import ExportDockWidget


class DockExportPlugin:
    """Plugin main class. Creates dock, toolbar icon, menu, and layer tree context menu."""

    def __init__(self, iface):
        self.iface = iface
        self._dock: ExportDockWidget = None
        self._action: QAction = None

    def initGui(self):
        """Set up toolbar icon, plugin menu, and layer tree context menu."""
        self._action = QAction("Dock Export", self.iface.mainWindow())
        self._action.setCheckable(True)
        self._action.triggered.connect(self._toggle_dock)
        self.iface.addToolBarIcon(self._action)
        self.iface.addPluginToMenu("&Dock Export", self._action)
        self.layer_tree_view = self.iface.layerTreeView()
        if self.layer_tree_view:
            self.layer_tree_view.setContextMenuPolicy(
                Qt.ContextMenuPolicy.CustomContextMenu
            )
            self._ctx_connection = (
                self.layer_tree_view.customContextMenuRequested.connect(
                    self._on_layer_tree_context_menu
                )
            )

    def unload(self):
        """Remove toolbar icon, menu entries, dock widget, and disconnect signals."""
        self.iface.removeToolBarIcon(self._action)
        self.iface.removePluginMenu("&Dock Export", self._action)
        if self._dock:
            self.iface.removeDockWidget(self._dock)
            self._dock.deleteLater()
            self._dock = None
        if self.layer_tree_view and self._ctx_connection:
            try:
                self.layer_tree_view.customContextMenuRequested.disconnect(
                    self._on_layer_tree_context_menu
                )
            except TypeError:
                pass

    def _toggle_dock(self, checked: bool) -> None:
        if checked:
            if self._dock is None:
                self._dock = ExportDockWidget(self.iface, self.iface.mainWindow())
                self._dock.visibilityChanged.connect(self._on_visibility_changed)
                self.iface.addDockWidget(
                    Qt.DockWidgetArea.RightDockWidgetArea, self._dock
                )
            self._dock.show()
        else:
            if self._dock:
                self._dock.hide()

    def _on_visibility_changed(self, visible: bool) -> None:
        if self._action:
            self._action.setChecked(visible)

    def _on_layer_tree_context_menu(self, point: QPoint) -> None:
        """Add 'Export with Dock exporter' action to the layer tree context menu."""
        if not self.layer_tree_view or not self.layer_tree_view.menuProvider():
            return

        index = self.layer_tree_view.indexAt(point)
        if not index.isValid():
            return

        node = self.layer_tree_view.currentNode()
        if node is None or not node.layer():
            return

        layer = node.layer()
        if layer.type() not in (QgsMapLayer.VectorLayer, QgsMapLayer.RasterLayer):
            return

        menu: QMenu = self.layer_tree_view.menuProvider().createContextMenu()

        menu.addSeparator()
        action = menu.addAction("Export with Dock exporter...")
        action.triggered.connect(lambda: self._open_dock_export_for_layer(layer))

        global_pos = self.layer_tree_view.viewport().mapToGlobal(point)
        menu.exec_(global_pos)

    def _open_dock_export_for_layer(self, layer) -> None:
        """Open dock and select the given layer in the table."""
        if self._dock is None:
            self._toggle_dock(True)
        else:
            self._dock.show()

        self._dock.raise_()

        if hasattr(self._dock, "set_active_layer"):
            self._dock.set_active_layer(layer)
