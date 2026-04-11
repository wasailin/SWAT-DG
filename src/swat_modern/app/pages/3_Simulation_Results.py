"""
Simulation Results Page - Browse SWAT output files and visualize results.
"""

import streamlit as st
import pandas as pd
from pathlib import Path
from swat_modern.app.session_persistence import load_session, clear_session, get_output_mtime
from swat_modern.app.loading_utils import hide_deploy_button

st.set_page_config(page_title="Simulation Results", page_icon="📊", layout="wide")
hide_deploy_button()

# Restore session state on page load (survives browser refresh)
load_session(st.session_state)

st.title("Simulation Results")
st.markdown("Browse SWAT output files and visualize simulation results.")

# Sidebar: Exit Project button
with st.sidebar:
    if "project_path" in st.session_state:
        if st.button("Exit Project", type="secondary", width="stretch"):
            clear_session(st.session_state)
            st.rerun()

# Check if project is loaded
try:
    from swat_modern.app.loading_utils import page_requires_project, inject_shimmer_css
    page_requires_project()
    inject_shimmer_css()
except ImportError:
    if "project_path" not in st.session_state:
        st.warning("Please load a SWAT project first in **Project Setup**.")
        st.stop()

project_path = st.session_state.project_path

# Import required modules
try:
    from swat_modern.io.parsers.result_browser import ResultBrowser, PRIORITY_VARIABLES
    from swat_modern.visualization.plotly_charts import (
        plotly_time_series,
        plotly_bar_summary,
    )
except ImportError as e:
    st.error(f"Missing dependency: {e}")
    st.stop()

# Version tag — bump to force @st.cache_resource to drop stale ResultBrowser instances
# after parser code changes (Streamlit only invalidates when function body changes).
_BROWSER_VERSION = 2

@st.cache_resource(show_spinner="Initializing result browser...")
def get_browser(path: str, output_mtime: float, _v: int = _BROWSER_VERSION) -> ResultBrowser:
    return ResultBrowser(path)

try:
    browser = get_browser(project_path, get_output_mtime(project_path))
except Exception as e:
    st.error(f"Could not initialize result browser: {e}")
    st.stop()


@st.cache_data
def _get_reach_subbasin_maps(proj_path: str):
    """Return (sub_to_reach, reach_to_sub) dicts from fig.fig, or empty dicts."""
    try:
        from swat_modern.io.parsers.fig_parser import FigFileParser
        fig_path = Path(proj_path) / "fig.fig"
        if fig_path.exists():
            fp = FigFileParser(str(fig_path))
            s2r = fp.subbasin_to_reach  # {sub_id: reach_id}
            r2s = {v: k for k, v in s2r.items()}
            return s2r, r2s
    except Exception:
        pass
    return {}, {}


_sub_to_reach, _reach_to_sub = _get_reach_subbasin_maps(project_path)


# Auto-load spatial data (subbasins, streams, reservoirs) if not already in session state
if "subbasins_gdf" not in st.session_state:
    try:
        from swat_modern.spatial import ShapefileLoader

        @st.cache_resource(show_spinner="Discovering spatial layers...")
        def _discover_spatial_layers(proj_path: str):
            """Try to find and load spatial layers from project or nearby dirs."""
            proj = Path(proj_path)
            loader = ShapefileLoader(proj)
            all_found = {}

            # 1. Standard discovery (project dir + parent Watershed/Shapes)
            found = loader.find_shapefiles()
            all_found.update(found)

            # 2. Search sibling directories for Watershed/Shapes or Results
            if "subbasins" not in all_found:
                for sibling in proj.parent.iterdir():
                    if not sibling.is_dir() or sibling == proj:
                        continue
                    for sub in [
                        sibling / "Watershed" / "Shapes",
                        sibling / "Scenarios" / "Default" / "Results",
                    ]:
                        if sub.exists():
                            sibling_found = loader.scan_custom_directory(str(sub))
                            for key, path in sibling_found.items():
                                if key not in all_found:
                                    all_found[key] = path
                    if "subbasins" in all_found:
                        break

            # Load each layer found
            result = {}
            for layer_type in ("subbasins", "streams", "reservoirs"):
                if layer_type in all_found:
                    try:
                        result[layer_type] = loader.load_shapefile(all_found[layer_type])
                    except Exception:
                        pass
            return result

        _layers = _discover_spatial_layers(project_path)
        for _layer_type, _gdf in _layers.items():
            st.session_state[f"{_layer_type}_gdf"] = _gdf
    except (ImportError, Exception):
        pass

# -------------------------------------------------------------------------
# Section 1: Available Output Files
# -------------------------------------------------------------------------
st.markdown("---")
st.header("1. Available Output Files")

available = browser.list_available_outputs()

output_cols = st.columns(5)
output_labels = {
    "rch": "Reach (output.rch)",
    "sub": "Subbasin (output.sub)",
    "sed": "Sediment (output.sed)",
    "rsv": "Reservoir (output.rsv)",
    "std": "Summary (output.std)",
}

for i, (ext, label) in enumerate(output_labels.items()):
    with output_cols[i]:
        if available.get(ext, False):
            st.success(f"{label}")
        else:
            st.error(f"{label}")

available_types = [ext for ext, exists in available.items() if exists and ext != "std"]

if not available_types:
    st.warning("No output files found. Run a SWAT simulation first to generate output files.")
    st.stop()

# -------------------------------------------------------------------------
# Section 2: Output Type & Variable Selection
# -------------------------------------------------------------------------
st.markdown("---")
st.header("2. Select Output & Variable")

sel_col1, sel_col2, sel_col3 = st.columns(3)

with sel_col1:
    output_type = st.selectbox(
        "Output Type",
        options=available_types,
        format_func=lambda x: {"rch": "Reach", "sub": "Subbasin",
                                "sed": "Sediment", "rsv": "Reservoir"}.get(x, x),
    )

# Get priority variables for the selected output type
priority_vars = browser.get_priority_variables(output_type)
all_vars = browser.get_variables(output_type)

with sel_col2:
    # Build categorized variable list
    var_options = []
    for category, vars_list in priority_vars.items():
        for v in vars_list:
            if v in all_vars:
                var_options.append(f"[{category}] {v}")

    # Add remaining variables
    priority_flat = [v for vl in priority_vars.values() for v in vl]
    for v in all_vars:
        if v not in priority_flat:
            var_options.append(f"[Other] {v}")

    selected_var_label = st.selectbox(
        "Variable",
        options=var_options,
        index=0 if var_options else None,
    )

    # Extract variable name from label
    variable = selected_var_label.split("] ")[1] if selected_var_label else None

with sel_col3:
    # Get unit IDs
    try:
        unit_ids = browser.get_unit_ids(output_type)
    except Exception:
        unit_ids = []

    if unit_ids:
        unit_id = st.selectbox(
            {"rch": "Reach", "sub": "Subbasin", "sed": "Reach", "rsv": "Reservoir"}.get(output_type, "Unit") + " ID",
            options=unit_ids,
        )
    else:
        unit_id = st.number_input("Unit ID", min_value=1, value=1)

if variable is None:
    st.stop()

# -------------------------------------------------------------------------
# Section 3: Time Series Plot
# -------------------------------------------------------------------------
st.markdown("---")
st.header("3. Time Series")

try:
    ts_df = browser.get_time_series(output_type, variable, unit_id)

    if len(ts_df) == 0:
        st.warning("No data found for the selected combination.")
    else:
        type_label = {"rch": "Reach", "sub": "Subbasin", "sed": "Sediment", "rsv": "Reservoir"}.get(output_type, output_type)

        fig = plotly_time_series(
            ts_df,
            value_cols=[variable],
            title=f"{variable} - {type_label} {unit_id}",
            ylabel=variable,
            show_rangeslider=True,
        )
        st.plotly_chart(fig, width="stretch")

        # Summary statistics
        stats_col1, stats_col2, stats_col3, stats_col4, stats_col5 = st.columns(5)
        values = ts_df[variable]

        with stats_col1:
            st.metric("Mean", f"{values.mean():.4f}")
        with stats_col2:
            st.metric("Std Dev", f"{values.std():.4f}")
        with stats_col3:
            st.metric("Min", f"{values.min():.4f}")
        with stats_col4:
            st.metric("Max", f"{values.max():.4f}")
        with stats_col5:
            st.metric("Count", f"{len(values)}")

except FileNotFoundError as e:
    st.error(f"Output file not found: {e}")
except Exception as e:
    st.error(f"Error loading data: {e}")
    with st.expander("Details"):
        st.exception(e)

# -------------------------------------------------------------------------
# Section 4: Multi-Unit Comparison
# -------------------------------------------------------------------------
st.markdown("---")
st.header("4. Compare Across Units")

with st.expander("Compare multiple units", expanded=False):
    if unit_ids:
        # --- Interactive map selection (if subbasins loaded) ---
        has_map = "subbasins_gdf" in st.session_state
        if has_map:
            try:
                from shapely.geometry import Point
                from streamlit_folium import st_folium
                from swat_modern.spatial import WatershedMapBuilder

                subbasins_gdf = st.session_state["subbasins_gdf"]

                # Detect the subbasin ID column in the GeoDataFrame
                _id_col = None
                for _cand in ["Subbasin", "SubbasinR", "SUB", "ID", "FID", "OBJECTID"]:
                    if _cand in subbasins_gdf.columns:
                        _id_col = _cand
                        break

                if _id_col is not None:
                    # Ensure valid unit IDs only (intersect GDF ids with output ids)
                    gdf_ids = set(subbasins_gdf[_id_col].dropna().astype(int).tolist())
                    # For rch output: map shows subbasin IDs but output uses
                    # reach IDs.  Accept subbasins whose reach exists in output.
                    if output_type in ("rch", "sed") and _sub_to_reach:
                        _reach_set = set(unit_ids)
                        valid_ids = sorted(
                            s for s in gdf_ids
                            if _sub_to_reach.get(s) in _reach_set
                        )
                    else:
                        valid_ids = sorted(gdf_ids & set(unit_ids))

                    # Initialize session state for map selection
                    if "compare_selected_units" not in st.session_state:
                        st.session_state.compare_selected_units = []

                    st.markdown("**Right-click** subbasins on the map to select/deselect units for comparison.")

                    # Use @st.fragment so map clicks only rerun this section
                    # (prevents grey-out of the entire page)
                    @st.fragment
                    def _render_compare_map():
                        import geopandas as _gpd
                        import folium
                        from folium.features import GeoJsonTooltip
                        from branca.element import MacroElement
                        from jinja2 import Template

                        # Sync from multiselect widget key → shared state
                        # so the map reflects dropdown changes on the same rerun
                        if "compare_multiselect" in st.session_state:
                            st.session_state.compare_selected_units = [
                                u for u in st.session_state.compare_multiselect
                                if u in valid_ids
                            ]

                        selected_set = set(st.session_state.compare_selected_units)

                        # Ensure data is in WGS84 (EPSG:4326) for folium
                        def _ensure_wgs84(gdf):
                            """Reproject to WGS84 if not already."""
                            if not hasattr(gdf, "geometry") or gdf.geometry is None:
                                return gdf
                            if gdf.crs is not None and gdf.crs.to_epsg() != 4326:
                                return gdf.to_crs("EPSG:4326")
                            if gdf.crs is None:
                                # Check if coords look like projected (outside valid lat/lon)
                                b = gdf.total_bounds
                                if abs(b[0]) > 180 or abs(b[1]) > 90 or abs(b[2]) > 180 or abs(b[3]) > 90:
                                    # Try common SWAT CRS options
                                    for epsg in [4269, 32615, 32616, 26915, 26916]:
                                        try:
                                            return gdf.set_crs(f"EPSG:{epsg}").to_crs("EPSG:4326")
                                        except Exception:
                                            continue
                                return gdf.set_crs("EPSG:4326", allow_override=True)
                            return gdf

                        import json as _json

                        _gdf_4326 = _ensure_wgs84(subbasins_gdf.copy())
                        _gdf_4326["_selected"] = _gdf_4326[_id_col].astype(int).isin(selected_set)

                        # Compute bounds for initial fit
                        bounds = _gdf_4326.total_bounds
                        _center = ((bounds[1] + bounds[3]) / 2, (bounds[0] + bounds[2]) / 2)
                        _sw = [float(bounds[1]), float(bounds[0])]
                        _ne = [float(bounds[3]), float(bounds[2])]

                        _fmap = folium.Map(
                            location=_center,
                            zoom_start=10,
                            tiles="OpenStreetMap",
                            scrollWheelZoom=True,
                            control_scale=True,
                        )
                        # NOTE: fit_bounds is NOT called here.
                        # The MacroElement JS below handles initial fit vs
                        # restoring saved view on reruns (selection change).

                        # -- Streams layer (if available) --
                        if "streams_gdf" in st.session_state:
                            _streams = _ensure_wgs84(st.session_state["streams_gdf"])
                            _stream_fields = [c for c in _streams.columns if c != "geometry"][:3]
                            folium.GeoJson(
                                _streams,
                                name="Streams",
                                style_function=lambda x: {
                                    "color": "#0066cc",
                                    "weight": 2,
                                    "opacity": 0.7,
                                },
                                tooltip=GeoJsonTooltip(
                                    fields=_stream_fields,
                                    aliases=[c.replace("_", " ").title() for c in _stream_fields],
                                ) if _stream_fields else None,
                            ).add_to(_fmap)

                        # -- Subbasins layer (clickable, selection-aware) --
                        def _compare_style(feature):
                            is_sel = feature["properties"].get("_selected", False)
                            if is_sel:
                                return {
                                    "fillColor": "#2ca02c",
                                    "color": "#1a6e1a",
                                    "weight": 3,
                                    "fillOpacity": 0.55,
                                }
                            return {
                                "fillColor": "#3388ff",
                                "color": "#333333",
                                "weight": 1.5,
                                "fillOpacity": 0.25,
                            }

                        _highlight = lambda x: {
                            "fillColor": "#ffff00",
                            "color": "#000000",
                            "weight": 3,
                            "fillOpacity": 0.6,
                        }

                        _tooltip_fields = [_id_col] + [
                            c for c in subbasins_gdf.columns
                            if c not in ("geometry", _id_col, "_selected")
                        ][:2]

                        folium.GeoJson(
                            _gdf_4326,
                            name="Subbasins",
                            style_function=_compare_style,
                            highlight_function=_highlight,
                            tooltip=GeoJsonTooltip(
                                fields=_tooltip_fields,
                                aliases=[c.replace("_", " ").title() for c in _tooltip_fields],
                                sticky=False,
                            ),
                        ).add_to(_fmap)

                        # -- Reservoirs layer (if available) --
                        if "reservoirs_gdf" in st.session_state:
                            _reservoirs = _ensure_wgs84(st.session_state["reservoirs_gdf"])
                            _res_layer = folium.FeatureGroup(name="Reservoirs")
                            for _, _rrow in _reservoirs.iterrows():
                                _geom = _rrow.geometry
                                if _geom is None:
                                    continue
                                _pt = _geom.centroid if _geom.geom_type in ("Polygon", "MultiPolygon") else _geom
                                _rattrs = {k: v for k, v in _rrow.items() if k != "geometry"}
                                _popup_html = "<br>".join(
                                    f"<b>{k}:</b> {v}" for k, v in list(_rattrs.items())[:5]
                                )
                                folium.Marker(
                                    location=[_pt.y, _pt.x],
                                    popup=folium.Popup(_popup_html, max_width=250),
                                    icon=folium.Icon(color="blue", icon="tint", prefix="fa"),
                                ).add_to(_res_layer)
                            _res_layer.add_to(_fmap)

                        # -- JS: right-click selection + view state persistence --
                        class _MapHelper(MacroElement):
                            """Right-click→click + save/restore map view across reruns."""
                            def __init__(self, sw, ne):
                                super().__init__()
                                self._name = "MapHelper"
                                self._sw = _json.dumps(sw)
                                self._ne = _json.dumps(ne)
                            _template = Template("""
                                {% macro script(this, kwargs) %}
                                (function(){
                                    var map = {{ this._parent.get_name() }};
                                    var sw = {{ this._sw }};
                                    var ne = {{ this._ne }};
                                    var stateKey = '_swat_cmp_'
                                        + Math.round(sw[0]*100) + '_'
                                        + Math.round(sw[1]*100);

                                    /* --- Restore saved view or fit to bounds --- */
                                    try {
                                        var s = JSON.parse(localStorage.getItem(stateKey));
                                        if (s && typeof s.lat === 'number') {
                                            map.setView([s.lat, s.lng], s.zoom);
                                        } else {
                                            map.fitBounds([sw, ne]);
                                        }
                                    } catch(ex) { map.fitBounds([sw, ne]); }

                                    /* --- Save view on every pan / zoom --- */
                                    map.on('moveend', function(){
                                        var c = map.getCenter();
                                        try {
                                            localStorage.setItem(stateKey,
                                                JSON.stringify({lat:c.lat, lng:c.lng, zoom:map.getZoom()})
                                            );
                                        } catch(ex){}
                                    });

                                    /* --- Disable browser context menu on map --- */
                                    map.getContainer().addEventListener(
                                        'contextmenu', function(e){ e.preventDefault(); }
                                    );

                                    /* --- Right-click on features → DOM click --- */
                                    function bindRC(){
                                        map.eachLayer(function(layer){
                                            if (layer.eachLayer) {
                                                layer.eachLayer(function(f){
                                                    if (f.feature && !f._rc) {
                                                        f._rc = true;
                                                        f.on('contextmenu', function(e){
                                                            L.DomEvent.preventDefault(e);
                                                            var synth = new MouseEvent('click', {
                                                                bubbles: true,
                                                                cancelable: true,
                                                                view: window,
                                                                clientX: e.originalEvent.clientX,
                                                                clientY: e.originalEvent.clientY
                                                            });
                                                            e.originalEvent.target
                                                                .dispatchEvent(synth);
                                                        });
                                                    }
                                                });
                                            }
                                        });
                                    }
                                    bindRC();
                                    setTimeout(bindRC, 300);
                                    setTimeout(bindRC, 800);
                                })();
                                {% endmacro %}
                            """)

                        _MapHelper(_sw, _ne).add_to(_fmap)

                        folium.LayerControl(collapsed=True).add_to(_fmap)

                        map_data = st_folium(
                            _fmap,
                            width=None,
                            height=400,
                            key="compare_map",
                            returned_objects=["last_object_clicked"],
                        )

                        # Handle click / right-click → toggle selection
                        if map_data and map_data.get("last_object_clicked"):
                            click = map_data["last_object_clicked"]
                            click_key = (round(click["lat"], 8), round(click["lng"], 8))
                            if click_key != st.session_state.get("_compare_last_click"):
                                st.session_state._compare_last_click = click_key
                                click_point = Point(click["lng"], click["lat"])
                                for _, row in _gdf_4326.iterrows():
                                    if row.geometry is not None and row.geometry.contains(click_point):
                                        clicked_id = int(row[_id_col])
                                        if clicked_id in valid_ids:
                                            sel = list(st.session_state.compare_selected_units)
                                            if clicked_id in sel:
                                                sel.remove(clicked_id)
                                            else:
                                                sel.append(clicked_id)
                                            st.session_state.compare_selected_units = sel
                                            st.session_state.compare_multiselect = sel
                                            st.rerun()
                                        break

                        # Multiselect synced with map selection
                        _compare_units = st.multiselect(
                            "Selected units to compare:",
                            options=valid_ids,
                            default=[u for u in st.session_state.compare_selected_units if u in valid_ids],
                            key="compare_multiselect",
                        )
                        # Sync multiselect back to session state
                        st.session_state.compare_selected_units = list(_compare_units)

                        # Comparison chart (inside fragment so it updates with selection)
                        if _compare_units and variable:
                            try:
                                _combined = pd.DataFrame()
                                for _uid in _compare_units:
                                    # Translate subbasin ID → reach ID for rch output
                                    _qid = _sub_to_reach.get(_uid, _uid) if output_type in ("rch", "sed") and _sub_to_reach else _uid
                                    _ts = browser.get_time_series(output_type, variable, _qid)
                                    _col = f"Sub {_uid}" if _qid != _uid else f"{output_type.upper()} {_uid}"
                                    if _combined.empty:
                                        _combined = _ts.rename(columns={variable: _col})
                                    else:
                                        _combined[_col] = _ts[variable].values[:len(_combined)]

                                if not _combined.empty:
                                    _fig = plotly_time_series(
                                        _combined,
                                        title=f"{variable} - Comparison",
                                        ylabel=variable,
                                    )
                                    st.plotly_chart(_fig, width="stretch")
                            except Exception as _e:
                                st.error(f"Error comparing units: {_e}")

                    _render_compare_map()
                else:
                    has_map = False  # no usable ID column
            except ImportError:
                has_map = False
            except Exception as e:
                st.warning(f"Could not load map selection: {e}")
                has_map = False

        # Fallback: plain multiselect without map + chart
        if not has_map:
            compare_units = st.multiselect(
                "Select units to compare:",
                options=unit_ids,
                default=unit_ids[:min(3, len(unit_ids))],
            )

            if compare_units and variable:
                try:
                    combined = pd.DataFrame()
                    for uid in compare_units:
                        ts = browser.get_time_series(output_type, variable, uid)
                        col_name = f"{output_type.upper()} {uid}"
                        if combined.empty:
                            combined = ts.rename(columns={variable: col_name})
                        else:
                            combined[col_name] = ts[variable].values[:len(combined)]

                    if not combined.empty:
                        fig = plotly_time_series(
                            combined,
                            title=f"{variable} - Comparison",
                            ylabel=variable,
                        )
                        st.plotly_chart(fig, width="stretch")
                except Exception as e:
                    st.error(f"Error comparing units: {e}")

# -------------------------------------------------------------------------
# Section 5: Spatial Summary
# -------------------------------------------------------------------------
st.markdown("---")
st.header("5. Spatial Summary")

spatial_col1, spatial_col2 = st.columns([1, 3])

with spatial_col1:
    aggregation = st.selectbox(
        "Aggregation",
        options=["mean", "sum", "max", "min", "std"],
        index=0,
    )

with spatial_col2:
    st.markdown(f"**{variable}** aggregated by **{aggregation}** across all time steps")

try:
    spatial_df = browser.get_spatial_summary(output_type, variable, aggregation)

    if len(spatial_df) > 0:
        # Bar chart
        id_col = spatial_df.columns[0]
        fig = plotly_bar_summary(
            spatial_df,
            category_col=id_col,
            value_col=variable,
            title=f"{aggregation.title()} {variable} by {id_col}",
        )
        st.plotly_chart(fig, width="stretch")

        # Spatial heatmap on map (if subbasins are loaded)
        if "subbasins_gdf" in st.session_state and output_type in ("rch", "sub", "sed"):
            try:
                import geopandas as gpd
                from streamlit_folium import st_folium
                from swat_modern.spatial import WatershedMapBuilder

                subbasins_gdf = st.session_state["subbasins_gdf"].copy()

                # Try to merge spatial summary with subbasin geometries
                # Detect ID column in the GeoDataFrame
                merge_col = None
                for candidate in ["Subbasin", "SubbasinR", "SUB", "ID", "FID", "OBJECTID"]:
                    if candidate in subbasins_gdf.columns:
                        merge_col = candidate
                        break

                if merge_col:
                    # For RCH output: the id_col ("RCH") contains reach numbers
                    # which may differ from subbasin numbers (e.g. SWAT+ converted
                    # projects).  Map reach → subbasin so the merge matches the
                    # shapefile's subbasin IDs.
                    _merge_spatial = spatial_df.copy()
                    _right_key = id_col
                    if output_type in ("rch", "sed") and _reach_to_sub:
                        _merge_spatial["_sub_id"] = (
                            _merge_spatial[id_col].map(_reach_to_sub)
                        )
                        _merge_spatial = _merge_spatial.dropna(subset=["_sub_id"])
                        _merge_spatial["_sub_id"] = _merge_spatial["_sub_id"].astype(int)
                        _right_key = "_sub_id"

                    merged = subbasins_gdf.merge(
                        _merge_spatial,
                        left_on=merge_col,
                        right_on=_right_key,
                        how="left",
                    )

                    builder = WatershedMapBuilder()
                    builder.create_base_map(merged)
                    builder.add_result_heatmap(
                        merged,
                        value_column=variable,
                        legend_name=f"{aggregation.title()} {variable}",
                    )
                    folium_map = builder.get_map()
                    st_folium(folium_map, width=None, height=450, returned_objects=[])
                else:
                    st.info("Could not match subbasin IDs for spatial mapping.")
            except ImportError:
                st.info("Install folium and streamlit-folium for spatial heatmaps.")
            except Exception as e:
                st.warning(f"Could not create spatial heatmap: {e}")

        # Data table
        with st.expander("View data table"):
            st.dataframe(spatial_df, width="stretch")

except Exception as e:
    st.error(f"Error computing spatial summary: {e}")

# -------------------------------------------------------------------------
# Section 6: Full Statistics Table
# -------------------------------------------------------------------------
st.markdown("---")
with st.expander("Detailed Statistics Table"):
    try:
        stats_df = browser.get_summary_statistics(output_type, variable)
        st.dataframe(stats_df, width="stretch")
    except Exception as e:
        st.error(f"Error computing statistics: {e}")

# Navigation
st.markdown("---")
st.markdown("""
**Next Step:** Go to **Observation Data** to load observed measurements,
or go to **Parameter Editor** to review and customize calibration parameters.
""")
