def classFactory(iface):
    from .plugin import DockExportPlugin
    return DockExportPlugin(iface)
