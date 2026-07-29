"""QGIS stubs for headless testing.
Creates proper module objects so ``import qgis.core`` and friends work.
"""
import sys
import types


def _make_stub_module(name: str) -> types.ModuleType:
    """Create a proper module object with auto-stubbing __getattr__."""
    mod = types.ModuleType(name)
    mod.__path__ = []
    mod.__package__ = name
    mod.__spec__ = types.SimpleNamespace(
        name=name,
        loader=None,
        origin="stub",
        submodule_search_locations=[],
    )
    # Auto-stub any attribute access -- catches all 'from qgis.core import Xxx' 
    orig_getattr = getattr(mod, "__getattr__", None)
    def __getattr__(name):
        # Return a generic type for any missing import
        return type(name, (object,), {"__init__": lambda self, *a, **kw: None})
    mod.__getattr__ = __getattr__
    sys.modules[name] = mod
    return mod


# Also stub common non-QGIS optional dependencies
for _name in ["osgeo", "osgeo.gdal", "osgeo.ogr", "osgeo.osr", "osgeo.gdal_array"]:
    if _name not in sys.modules:
        _make_stub_module(_name)
qgis = _make_stub_module("qgis")

qgis_core = _make_stub_module("qgis.core")
qgis_core.Qgis = types.SimpleNamespace(
    QGIS_VERSION="3.99.0-test",
    QGIS_RELEASE_NAME="Test",
    QGIS_DEV_VERSION="test",
)
qgis_core.QgsMapLayer = object
qgis_core.QgsMessageLog = object
qgis_core.QgsSettings = object
qgis_core.QgsProject = object

qgis_gui = _make_stub_module("qgis.gui")
qgis_gui.QgsDockWidget = object
qgis_gui.QgsMapLayerComboBox = object

qgis_pyqt = _make_stub_module("qgis.PyQt")

qgis_qtcore = _make_stub_module("qgis.PyQt.QtCore")
qgis_qtcore.QT_VERSION_STR = "6.5.0"
qgis_qtcore.PYQT_VERSION_STR = "6.5.0"
qgis_qtcore.QObject = type("QObject", (), {})
qgis_qtcore.pyqtSignal = lambda *a, **kw: object()
qgis_qtcore.pyqtBoundSignal = type("pyqtBoundSignal", (object,), {"__init__": lambda self, *a, **kw: None})
qgis_qtcore.QCoreApplication = type("QCoreApplication", (), {"translate": staticmethod(lambda a, b: b)})
qgis_qtcore.QPoint = type("QPoint", (object,), {"__init__": lambda self, *a, **kw: None})
qgis_qtcore.QSize = type("QSize", (object,), {"__init__": lambda self, *a, **kw: None})
qgis_qtcore.QRect = type("QRect", (object,), {"__init__": lambda self, *a, **kw: None})
qgis_qtcore.QTimer = type("QTimer", (object,), {"__init__": lambda self, *a, **kw: None})
qgis_qtcore.QFile = type("QFile", (object,), {"__init__": lambda self, *a, **kw: None})
qgis_qtcore.Qt = type("Qt", (), {
    "Widget": 1,
    "RightDockWidgetArea": 2,
    "DockWidgetArea": type("DockWidgetArea", (), {"RightDockWidgetArea": 2})(),
    "ContextMenuPolicy": type("CM", (), {"CustomContextMenu": 3})(),
})

qgis_qtgui = _make_stub_module("qgis.PyQt.QtGui")
qgis_qtgui.QAction = type("QAction", (object,), {"__init__": lambda self, *a, **kw: None})
qgis_qtgui.QIcon = type("QIcon", (object,), {"__init__": lambda self, *a, **kw: None})
qgis_qtgui.QColor = type("QColor", (object,), {"__init__": lambda self, *a, **kw: None})
qgis_qtgui.QFont = type("QFont", (object,), {"__init__": lambda self, *a, **kw: None})
qgis_qtgui.QPixmap = type("QPixmap", (object,), {"__init__": lambda self, *a, **kw: None})

qgis_qtwidgets = _make_stub_module("qgis.PyQt.QtWidgets")
qgis_qtwidgets.QAction = qgis_qtgui.QAction
qgis_qtwidgets.QMenu = type("QMenu", (object,), {"__init__": lambda self, *a, **kw: None})
qgis_qtwidgets.QWidget = type("QWidget", (object,), {"__init__": lambda self, *a, **kw: None})
qgis_qtwidgets.QMainWindow = type("QMainWindow", (object,), {"__init__": lambda self, *a, **kw: None})
qgis_qtwidgets.QDialog = type("QDialog", (object,), {"__init__": lambda self, *a, **kw: None})
qgis_qtwidgets.QFileDialog = type("QFileDialog", (object,), {"__init__": lambda self, *a, **kw: None})
qgis_qtwidgets.QMessageBox = type("QMessageBox", (object,), {"__init__": lambda self, *a, **kw: None})
qgis_qtwidgets.QApplication = type("QApplication", (object,), {"__init__": lambda self, *a, **kw: None})
qgis_qtwidgets.QTreeView = type("QTreeView", (object,), {"__init__": lambda self, *a, **kw: None})
qgis_qtwidgets.QPushButton = type("QPushButton", (object,), {"__init__": lambda self, *a, **kw: None})
qgis_qtwidgets.QComboBox = type("QComboBox", (object,), {"__init__": lambda self, *a, **kw: None})
qgis_qtwidgets.QVBoxLayout = type("QVBoxLayout", (object,), {"__init__": lambda self, *a, **kw: None})
