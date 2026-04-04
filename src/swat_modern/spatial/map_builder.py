"""
Watershed map builder using folium.

Creates interactive maps with subbasin polygons, stream networks,
watershed boundaries, and result-based choropleth heatmaps.
"""

from typing import Dict, List, Optional, Tuple, Union

import numpy as np

try:
    import folium
    from folium.features import GeoJsonPopup, GeoJsonTooltip
    from folium.plugins import Fullscreen
    import branca.colormap as cm
    HAS_FOLIUM = True
except ImportError:
    HAS_FOLIUM = False

try:
    import geopandas as gpd
    HAS_GEOPANDAS = True
except ImportError:
    HAS_GEOPANDAS = False


def _require_folium():
    if not HAS_FOLIUM:
        raise ImportError(
            "folium is required for map visualization. "
            "Install with: pip install swat-dg[app]"
        )


def _require_geopandas():
    if not HAS_GEOPANDAS:
        raise ImportError(
            "geopandas is required for spatial operations. "
            "Install with: pip install swat-dg[gis]"
        )


class WatershedMapBuilder:
    """
    Build interactive folium maps for SWAT watershed visualization.

    Example:
        >>> builder = WatershedMapBuilder()
        >>> builder.create_base_map(subbasins_gdf)
        >>> builder.add_subbasins(subbasins_gdf)
        >>> builder.add_streams(streams_gdf)
        >>> m = builder.get_map()
    """

    def __init__(self):
        _require_folium()
        self._map: Optional[folium.Map] = None
        self._layers: Dict[str, folium.FeatureGroup] = {}

    def create_base_map(
        self,
        gdf: Optional["gpd.GeoDataFrame"] = None,
        center: Optional[Tuple[float, float]] = None,
        zoom_start: int = 10,
        tiles: str = "OpenStreetMap",
    ) -> "folium.Map":
        """
        Create a base folium map centered on the watershed.

        Args:
            gdf: GeoDataFrame to compute center from (uses centroid of total bounds).
            center: Explicit (lat, lon) center. Overrides gdf.
            zoom_start: Initial zoom level.
            tiles: Tile provider name.

        Returns:
            folium.Map object.
        """
        if center is None and gdf is not None:
            _require_geopandas()
            bounds = gdf.total_bounds  # [minx, miny, maxx, maxy]
            center = (
                (bounds[1] + bounds[3]) / 2,  # lat = avg of miny, maxy
                (bounds[0] + bounds[2]) / 2,  # lon = avg of minx, maxx
            )
        elif center is None:
            center = (35.0, -97.0)  # Default to central US

        self._map = folium.Map(
            location=center,
            zoom_start=zoom_start,
            tiles=tiles,
            control_scale=True,
        )

        # Add alternative tile layers
        folium.TileLayer("CartoDB positron", name="Light").add_to(self._map)
        folium.TileLayer("CartoDB dark_matter", name="Dark").add_to(self._map)
        folium.TileLayer(
            tiles="https://server.arcgisonline.com/ArcGIS/rest/services/"
                  "World_Imagery/MapServer/tile/{z}/{y}/{x}",
            attr="Esri",
            name="Satellite",
        ).add_to(self._map)

        return self._map

    def add_subbasins(
        self,
        gdf: "gpd.GeoDataFrame",
        id_column: Optional[str] = None,
        popup_columns: Optional[List[str]] = None,
        fill_color: str = "#3388ff",
        fill_opacity: float = 0.3,
        line_weight: int = 2,
    ) -> None:
        """
        Add subbasin polygons to the map.

        Args:
            gdf: GeoDataFrame with subbasin polygons in EPSG:4326.
            id_column: Column name for subbasin ID. Auto-detected if None.
            popup_columns: Columns to show in popup on click.
            fill_color: Default fill color.
            fill_opacity: Fill transparency (0-1).
            line_weight: Border line weight.
        """
        _require_geopandas()
        if self._map is None:
            self.create_base_map(gdf)

        if id_column is None:
            id_column = self._detect_id_column(gdf)

        layer = folium.FeatureGroup(name="Subbasins")

        # Determine popup columns
        if popup_columns is None:
            popup_columns = [c for c in gdf.columns if c != "geometry"][:6]

        style_function = lambda x: {
            "fillColor": fill_color,
            "color": "#333333",
            "weight": line_weight,
            "fillOpacity": fill_opacity,
        }

        highlight_function = lambda x: {
            "fillColor": "#ffff00",
            "color": "#000000",
            "weight": 3,
            "fillOpacity": 0.6,
        }

        geojson = folium.GeoJson(
            gdf,
            name="Subbasins",
            style_function=style_function,
            highlight_function=highlight_function,
            tooltip=GeoJsonTooltip(
                fields=popup_columns[:3],
                aliases=[c.replace("_", " ").title() for c in popup_columns[:3]],
                sticky=False,
            ),
            popup=GeoJsonPopup(
                fields=popup_columns,
                aliases=[c.replace("_", " ").title() for c in popup_columns],
            ),
        )

        geojson.add_to(layer)
        layer.add_to(self._map)
        self._layers["subbasins"] = layer

    def add_streams(
        self,
        gdf: "gpd.GeoDataFrame",
        color: str = "#0066cc",
        weight: int = 2,
        opacity: float = 0.8,
    ) -> None:
        """
        Add stream network lines to the map.

        Args:
            gdf: GeoDataFrame with stream line features in EPSG:4326.
            color: Line color.
            weight: Line weight in pixels.
            opacity: Line opacity (0-1).
        """
        _require_geopandas()
        if self._map is None:
            self.create_base_map(gdf)

        layer = folium.FeatureGroup(name="Streams")

        style_function = lambda x: {
            "color": color,
            "weight": weight,
            "opacity": opacity,
        }

        tooltip_fields = [c for c in gdf.columns if c != "geometry"][:3]

        folium.GeoJson(
            gdf,
            name="Streams",
            style_function=style_function,
            tooltip=GeoJsonTooltip(
                fields=tooltip_fields,
                aliases=[c.replace("_", " ").title() for c in tooltip_fields],
            ) if tooltip_fields else None,
        ).add_to(layer)

        layer.add_to(self._map)
        self._layers["streams"] = layer

    def add_boundary(
        self,
        gdf: "gpd.GeoDataFrame",
        color: str = "#000000",
        weight: int = 3,
        fill: bool = False,
        dash_array: str = "5 5",
    ) -> None:
        """
        Add watershed boundary outline to the map.

        Args:
            gdf: GeoDataFrame with boundary polygon in EPSG:4326.
            color: Outline color.
            weight: Line weight in pixels.
            fill: Whether to fill the polygon.
            dash_array: Dash pattern for the line.
        """
        _require_geopandas()
        if self._map is None:
            self.create_base_map(gdf)

        layer = folium.FeatureGroup(name="Watershed Boundary")

        style_function = lambda x: {
            "color": color,
            "weight": weight,
            "fillOpacity": 0.05 if fill else 0,
            "dashArray": dash_array,
        }

        folium.GeoJson(
            gdf,
            name="Boundary",
            style_function=style_function,
        ).add_to(layer)

        layer.add_to(self._map)
        self._layers["boundary"] = layer

    def add_reservoirs(
        self,
        gdf: "gpd.GeoDataFrame",
        color: str = "#006699",
        icon: str = "tint",
    ) -> None:
        """
        Add reservoir markers to the map.

        Args:
            gdf: GeoDataFrame with reservoir features in EPSG:4326.
            color: Marker color.
            icon: Font Awesome icon name.
        """
        _require_geopandas()
        if self._map is None:
            self.create_base_map(gdf)

        layer = folium.FeatureGroup(name="Reservoirs")

        for _, row in gdf.iterrows():
            geom = row.geometry
            if geom is None:
                continue

            # Get centroid for point placement
            if geom.geom_type in ("Polygon", "MultiPolygon"):
                point = geom.centroid
            else:
                point = geom

            # Build popup text from attributes
            attrs = {k: v for k, v in row.items() if k != "geometry"}
            popup_html = "<br>".join(f"<b>{k}:</b> {v}" for k, v in list(attrs.items())[:5])

            folium.Marker(
                location=[point.y, point.x],
                popup=folium.Popup(popup_html, max_width=250),
                icon=folium.Icon(color=color, icon=icon, prefix="fa"),
            ).add_to(layer)

        layer.add_to(self._map)
        self._layers["reservoirs"] = layer

    def add_result_heatmap(
        self,
        gdf: "gpd.GeoDataFrame",
        value_column: str,
        legend_name: str = "Value",
        colormap_name: str = "YlOrRd",
        line_weight: int = 1,
        fill_opacity: float = 0.6,
    ) -> None:
        """
        Color subbasin polygons by a result variable (choropleth).

        Args:
            gdf: GeoDataFrame with subbasin polygons AND a value column.
            value_column: Column name containing numeric values to map.
            legend_name: Legend title.
            colormap_name: Branca colormap name (YlOrRd, Blues, Greens, etc.).
            line_weight: Border line weight.
            fill_opacity: Fill opacity (0-1).
        """
        _require_geopandas()
        if self._map is None:
            self.create_base_map(gdf)

        # Remove the plain subbasins layer if it exists
        if "subbasins" in self._layers:
            self._map._children.pop(
                self._layers["subbasins"]._name, None
            )

        values = gdf[value_column].dropna()
        if len(values) == 0:
            return

        vmin = float(values.min())
        vmax = float(values.max())

        # Create colormap
        colormap = cm.LinearColormap(
            colors=self._get_colormap_colors(colormap_name),
            vmin=vmin,
            vmax=vmax,
            caption=legend_name,
        )

        layer = folium.FeatureGroup(name=f"Results: {legend_name}")

        def style_function(feature):
            val = feature["properties"].get(value_column)
            if val is None or (isinstance(val, float) and np.isnan(val)):
                fill = "#cccccc"
            else:
                fill = colormap(val)
            return {
                "fillColor": fill,
                "color": "#333333",
                "weight": line_weight,
                "fillOpacity": fill_opacity,
            }

        tooltip_fields = [c for c in gdf.columns if c != "geometry"][:4]

        folium.GeoJson(
            gdf,
            style_function=style_function,
            tooltip=GeoJsonTooltip(
                fields=tooltip_fields,
                aliases=[c.replace("_", " ").title() for c in tooltip_fields],
            ),
        ).add_to(layer)

        layer.add_to(self._map)
        colormap.add_to(self._map)
        self._layers["result_heatmap"] = layer

    def fit_bounds(self, gdf: "gpd.GeoDataFrame") -> None:
        """Fit map bounds to the extent of a GeoDataFrame."""
        if self._map is None:
            return
        bounds = gdf.total_bounds  # [minx, miny, maxx, maxy]
        self._map.fit_bounds([
            [bounds[1], bounds[0]],  # southwest
            [bounds[3], bounds[2]],  # northeast
        ])

    def get_map(self) -> "folium.Map":
        """
        Return the folium Map object.

        Returns:
            Configured folium.Map with all added layers.
        """
        if self._map is None:
            raise ValueError("No map created. Call create_base_map() first.")

        # Add fullscreen control
        Fullscreen(
            position="topleft",
            title="Enter fullscreen",
            title_cancel="Exit fullscreen",
            force_separate_button=True,
        ).add_to(self._map)

        # Add layer control
        folium.LayerControl(collapsed=False).add_to(self._map)
        return self._map

    # -------------------------------------------------------------------------
    # Private helpers
    # -------------------------------------------------------------------------

    @staticmethod
    def _detect_id_column(gdf: "gpd.GeoDataFrame") -> Optional[str]:
        """Detect the most likely ID column in a GeoDataFrame."""
        candidates = ["Subbasin", "SubbasinR", "SUBBASIN", "SUB", "ID",
                       "FID", "OBJECTID", "id", "Sub", "Name"]
        for col in candidates:
            if col in gdf.columns:
                return col
        # Fall back to first non-geometry column
        non_geom = [c for c in gdf.columns if c != "geometry"]
        return non_geom[0] if non_geom else None

    @staticmethod
    def _get_colormap_colors(name: str) -> List[str]:
        """Get a list of colors for a named colormap."""
        colormaps = {
            "YlOrRd": ["#ffffb2", "#fed976", "#feb24c", "#fd8d3c",
                        "#fc4e2a", "#e31a1c", "#b10026"],
            "Blues": ["#f7fbff", "#deebf7", "#c6dbef", "#9ecae1",
                      "#6baed6", "#3182bd", "#08519c"],
            "Greens": ["#f7fcf5", "#e5f5e0", "#c7e9c0", "#a1d99b",
                        "#74c476", "#31a354", "#006d2c"],
            "RdYlGn": ["#d73027", "#fc8d59", "#fee08b", "#ffffbf",
                        "#d9ef8b", "#91cf60", "#1a9850"],
            "Spectral": ["#d53e4f", "#fc8d59", "#fee08b", "#ffffbf",
                          "#e6f598", "#99d594", "#3288bd"],
            "Oranges": ["#fff5eb", "#fee6ce", "#fdd0a2", "#fdae6b",
                         "#fd8d3c", "#e6550d", "#a63603"],
        }
        return colormaps.get(name, colormaps["YlOrRd"])
