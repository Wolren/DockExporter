"""Generate ArcPy scripts for opening exported data in ArcGIS Pro."""

import textwrap


def generate_script_text() -> str:
    """Return the ArcPy script as a string (embedded in archive and companion file)."""
    return textwrap.dedent("""\
        \"\"\"Open exported QGIS data in ArcGIS Pro with original layer group structure.\"\"\"
        from __future__ import annotations

        import arcpy
        import json
        import os
        import sys


        def _guess_data_file(layer_name: str, search_dir: str) -> str | None:
            gis_exts = {'.gpkg', '.shp', '.geojson', '.json', '.tif', '.tiff',
                       '.img', '.vrt', '.dem', '.png', '.jpg', '.jpeg', '.jp2',
                       '.mbtiles', '.nc', '.grib', '.hdf', '.h5', '.xls', '.xlsx',
                       '.csv', '.gml', '.dxf', '.dgn', '.tab', '.mif', '.kml', '.kmz'}
            for root, _dirs, files in os.walk(search_dir):
                for fn in files:
                    name, ext = os.path.splitext(fn)
                    if ext.lower() in gis_exts and name == layer_name:
                        return os.path.join(root, fn)
            return None


        def main(tree: dict, data_dir: str, aprx_path: str | None = None) -> str:
            \"\"\"Create an ArcGIS Pro project from the exported data.\"\"\"
            if aprx_path is None:
                aprx_path = os.path.join(data_dir, "project.aprx")

            arcpy.env.overwriteOutput = True

            # --- Create a new project ---
            created_from_current = False
            try:
                aprx_folder = os.path.dirname(aprx_path)
                project_name = os.path.splitext(os.path.basename(aprx_path))[0]
                arcpy.CreateProject_management(aprx_folder, project_name)
            except AttributeError:
                # Fallback: start from the current open project
                aprx = arcpy.mp.ArcGISProject("CURRENT")
                m = aprx.createMap("Exported Map")
                created_from_current = True

            if not created_from_current:
                aprx = arcpy.mp.ArcGISProject(aprx_path)
                maps = aprx.listMaps()
                # New project may have no maps — create one if needed
                m = maps[0] if maps else aprx.createMap("Main Map")

            # --- Build group / layer structure ---
            def _add_tree(node, group=None):
                if node["type"] == "group":
                    grp = m.createGroupLayer(node["name"])
                    for child in node.get("children", []):
                        _add_tree(child, group=grp)
                else:
                    data_file = _guess_data_file(node["name"], data_dir)
                    if not data_file:
                        return
                    lyr = m.addDataFromPath(data_file)
                    if group is not None:
                        # Move layer into the group
                        m.addLayerToGroup(group, lyr)
                        # Remove the root copy (addLayerToGroup creates a copy)
                        try:
                            m.removeLayer(lyr)
                        except Exception:
                            pass

            _add_tree(tree)

            if created_from_current:
                aprx.saveACopy(aprx_path)
                # Clean up — remove the exported map from current project
                aprx.deleteItem(m)
            else:
                aprx.save()
            return aprx_path


        def run_from(data_dir: str) -> None:
            tree_path = os.path.join(data_dir, "layer_tree.json")
            if not os.path.exists(tree_path):
                print("layer_tree.json not found in", data_dir)
                sys.exit(1)
            with open(tree_path, encoding="utf-8") as f:
                tree = json.load(f)
            aprx = main(tree, data_dir)
            print("Created:", aprx)


        if __name__ == "__main__":
            try:
                script_dir = os.path.dirname(os.path.abspath(__file__))
            except NameError:
                script_dir = os.getcwd()
            tree_path = os.path.join(script_dir, "layer_tree.json")
            if not os.path.exists(tree_path):
                print("layer_tree.json not found in", script_dir)
                sys.exit(1)
            with open(tree_path, encoding="utf-8") as f:
                tree = json.load(f)
            aprx = main(tree, script_dir)
            print("Created:", aprx)
    """)
