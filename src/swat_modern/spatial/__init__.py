"""
SWAT-DG Spatial Module.

Provides GIS functionality for loading and visualizing watershed spatial data:
- ShapefileLoader: Discover and load shapefiles / SQLite spatial layers
- WatershedMapBuilder: Build interactive folium maps

Example:
    from swat_modern.spatial import ShapefileLoader, WatershedMapBuilder

    loader = ShapefileLoader("C:/swat_project")
    subbasins = loader.load_subbasins()

    builder = WatershedMapBuilder()
    builder.create_base_map(subbasins)
    builder.add_subbasins(subbasins)
    m = builder.get_map()
"""

from swat_modern.spatial.shapefile_loader import ShapefileLoader
from swat_modern.spatial.map_builder import WatershedMapBuilder

__all__ = ["ShapefileLoader", "WatershedMapBuilder"]
