"""
dock_widget.py  –  QgsDockWidget wrapper for ExportWidget.
"""
from qgis.gui import QgsDockWidget
from qgis.PyQt.QtCore import Qt

from .export_widget import ExportWidget


class ExportDockWidget(QgsDockWidget):
    """Thin wrapper so the dock can tell ExportWidget to clean up on close."""

    def __init__(self, iface, parent=None):
        super().__init__("Dock Export", parent)
        self.setObjectName("DockExportDockWidget")
        self.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea |
            Qt.DockWidgetArea.RightDockWidgetArea
        )

        self._export_widget = ExportWidget(iface, parent=self)
        self.setWidget(self._export_widget)

    def closeEvent(self, event):
        self._export_widget.disconnect_all()
        super().closeEvent(event)

    def set_active_layer(self, layer):
        self.active_layer = layer
        for i in range(self.single_layer_list.count()):
            item = self.single_layer_list.item(i)
            data = item.data(Qt.UserRole)
            if data:
                qlayer, layer_type, export_name = data
                if qlayer.id() == layer.id():
                    self.single_layer_list.clearSelection()
                    item.setSelected(True)
                    break
