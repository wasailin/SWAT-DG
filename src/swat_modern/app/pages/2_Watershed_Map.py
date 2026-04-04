"""
Watershed Map Page - Interactive map viewer for SWAT project spatial data.
"""

import streamlit as st
from pathlib import Path
from swat_modern.app.session_persistence import load_session, clear_session, browse_folder, browse_file
from swat_modern.app.loading_utils import hide_deploy_button

st.set_page_config(page_title="Watershed Map", page_icon="🗺️", layout="wide")
hide_deploy_button()

# Restore session state on page load (survives browser refresh)
load_session(st.session_state)

st.title("Watershed Map")
st.markdown("View your watershed subbasins, stream network, and spatial features.")

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

# Check dependencies
try:
    import geopandas as gpd
    from streamlit_folium import st_folium
    from swat_modern.spatial import ShapefileLoader, WatershedMapBuilder
except ImportError as e:
    st.error(f"Missing dependency: {e}")
    st.info("Install with: `pip install swat-dg[full]`")
    st.stop()

st.markdown("---")

# -------------------------------------------------------------------------
# Section 1: Shapefile Configuration
# -------------------------------------------------------------------------
st.header("1. Spatial Data Sources")

project_path = st.session_state.project_path

# Infer default shapes directory from project path
# e.g. ~\Scenarios\Default\TxtInOut -> ~\Watershed\Shapes
_proj = Path(project_path)
_inferred_shapes_dir = ""
_txtinout_parts = _proj.parts[-3:] if len(_proj.parts) >= 3 else ()
if (len(_txtinout_parts) == 3
        and _txtinout_parts[0].lower() == "scenarios"
        and _txtinout_parts[2].lower() == "txtinout"):
    _candidate = _proj.parent.parent.parent / "Watershed" / "Shapes"
    if _candidate.exists():
        _inferred_shapes_dir = str(_candidate)

# Auto-discover shapefiles
loader = ShapefileLoader(project_path)

# Try to find shapefiles automatically
with st.status("Scanning for shapefiles...", expanded=False) as scan_status:
    found_shapefiles = loader.find_shapefiles()
    found_sqlite = loader.find_sqlite_layers()

    if found_shapefiles:
        for layer_type, path in found_shapefiles.items():
            st.caption(f"  {layer_type}: {path.name}")
        scan_status.update(
            label=f"Found {len(found_shapefiles)} shapefile layer(s)",
            state="complete",
        )
    elif found_sqlite:
        scan_status.update(
            label=f"Found {len(found_sqlite)} SQLite spatial layer(s)",
            state="complete",
        )
    else:
        scan_status.update(
            label="No shapefiles auto-detected — specify paths below",
            state="complete",
        )

# Allow manual path override and auto-detection from custom directory
# Apply browsed shapes dir before widget renders
_browsed_shapes_dir = st.session_state.get("_browsed_shapes_dir", None)
_browsed_subbasin = st.session_state.get("_browsed_subbasin", None)
_browsed_stream = st.session_state.get("_browsed_stream", None)
_browsed_boundary = st.session_state.get("_browsed_boundary", None)
_browsed_reservoir = st.session_state.get("_browsed_reservoir", None)

with st.expander("Manual shapefile paths", expanded=not found_shapefiles):
    # Shapes directory selection with auto-detection
    col_dir, col_dir_browse = st.columns([4, 1])
    with col_dir:
        _default_shapes = _browsed_shapes_dir \
            or (str(found_shapefiles.get("subbasins", "").parent)
                if found_shapefiles.get("subbasins") else "") \
            or _inferred_shapes_dir
        _shapes_gen = st.session_state.get("_shapes_dir_gen", 0)
        shapes_dir = st.text_input(
            "Shapes directory:",
            value=_default_shapes,
            placeholder="C:/path/to/Watershed/Shapes",
            help="Directory containing .shp files - shapefiles will be auto-detected",
            key=f"_shapes_dir_input_{_shapes_gen}",
        )
    with col_dir_browse:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("Browse...", key="browse_shapes_dir", width="stretch"):
            selected = browse_folder()
            if selected:
                st.session_state["_browsed_shapes_dir"] = selected
                st.session_state["_shapes_dir_gen"] = _shapes_gen + 1
                st.rerun()

    # Auto-detect shapefiles from the shapes directory if provided
    custom_detected = {}
    if shapes_dir and Path(shapes_dir).exists():
        custom_detected = loader.scan_custom_directory(shapes_dir)
        if custom_detected:
            st.success(f"Auto-detected {len(custom_detected)} shapefile(s) from directory")
            for layer_type, path in custom_detected.items():
                st.caption(f"  {layer_type}: {path.name}")

    # Merge custom detected with originally found shapefiles
    # Priority: browsed individual files > custom directory detection > original detection
    detected_shapefiles = {**found_shapefiles, **custom_detected}

    # Update widget session state so text_input widgets reflect detected paths
    # (Streamlit widget keys preserve old values across reruns, overriding `value=`)
    _key_map = {
        "subbasins": "subbasin_path_input",
        "streams": "stream_path_input",
        "boundary": "boundary_path_input",
        "reservoirs": "reservoir_path_input",
    }
    if custom_detected:
        for layer_type, wkey in _key_map.items():
            if layer_type in custom_detected:
                st.session_state[wkey] = str(custom_detected[layer_type])
        # Also merge into found_shapefiles so the map section uses them
        found_shapefiles.update(custom_detected)

    st.markdown("**Individual Shapefiles:**")
    col1, col2 = st.columns(2)

    with col1:
        # Subbasins shapefile
        col_sub, col_sub_browse = st.columns([3, 1])
        with col_sub:
            _default_subbasin = _browsed_subbasin or str(detected_shapefiles.get("subbasins", ""))
            subbasin_path = st.text_input(
                "Subbasins shapefile:",
                value=_default_subbasin,
                placeholder="subs1.shp",
                key="subbasin_path_input",
            )
        with col_sub_browse:
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("Browse", key="browse_subbasin", width="stretch"):
                selected = browse_file(
                    title="Select Subbasins Shapefile",
                    filetypes=[("Shapefiles", "*.shp"), ("All files", "*.*")]
                )
                if selected:
                    st.session_state["_browsed_subbasin"] = selected
                    st.session_state["subbasin_path_input"] = selected
                    st.rerun()

        # Streams shapefile
        col_stream, col_stream_browse = st.columns([3, 1])
        with col_stream:
            _default_stream = _browsed_stream or str(detected_shapefiles.get("streams", ""))
            stream_path = st.text_input(
                "Streams shapefile:",
                value=_default_stream,
                placeholder="rivs1.shp",
                key="stream_path_input",
            )
        with col_stream_browse:
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("Browse", key="browse_stream", width="stretch"):
                selected = browse_file(
                    title="Select Streams Shapefile",
                    filetypes=[("Shapefiles", "*.shp"), ("All files", "*.*")]
                )
                if selected:
                    st.session_state["_browsed_stream"] = selected
                    st.session_state["stream_path_input"] = selected
                    st.rerun()

    with col2:
        # Boundary shapefile
        col_boundary, col_boundary_browse = st.columns([3, 1])
        with col_boundary:
            _default_boundary = _browsed_boundary or str(detected_shapefiles.get("boundary", ""))
            boundary_path = st.text_input(
                "Watershed boundary shapefile:",
                value=_default_boundary,
                placeholder="watershed.shp",
                key="boundary_path_input",
            )
        with col_boundary_browse:
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("Browse", key="browse_boundary", width="stretch"):
                selected = browse_file(
                    title="Select Boundary Shapefile",
                    filetypes=[("Shapefiles", "*.shp"), ("All files", "*.*")]
                )
                if selected:
                    st.session_state["_browsed_boundary"] = selected
                    st.session_state["boundary_path_input"] = selected
                    st.rerun()

        # Reservoirs shapefile
        col_reservoir, col_reservoir_browse = st.columns([3, 1])
        with col_reservoir:
            _default_reservoir = _browsed_reservoir or str(detected_shapefiles.get("reservoirs", ""))
            reservoir_path = st.text_input(
                "Reservoirs shapefile:",
                value=_default_reservoir,
                placeholder="reservoirs.shp",
                key="reservoir_path_input",
            )
        with col_reservoir_browse:
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("Browse", key="browse_reservoir", width="stretch"):
                selected = browse_file(
                    title="Select Reservoirs Shapefile",
                    filetypes=[("Shapefiles", "*.shp"), ("All files", "*.*")]
                )
                if selected:
                    st.session_state["_browsed_reservoir"] = selected
                    st.session_state["reservoir_path_input"] = selected
                    st.rerun()

    # Update paths from manual input if provided
    if subbasin_path and Path(subbasin_path).exists():
        found_shapefiles["subbasins"] = Path(subbasin_path)
    if stream_path and Path(stream_path).exists():
        found_shapefiles["streams"] = Path(stream_path)
    if boundary_path and Path(boundary_path).exists():
        found_shapefiles["boundary"] = Path(boundary_path)
    if reservoir_path and Path(reservoir_path).exists():
        found_shapefiles["reservoirs"] = Path(reservoir_path)

# SQLite layers
if found_sqlite:
    with st.expander("SWAT+ SQLite spatial layers"):
        for layer_name, (db_path, table) in found_sqlite.items():
            st.caption(f"  {layer_name} ({db_path.name})")

# -------------------------------------------------------------------------
# Section 2: Load and Display Map
# -------------------------------------------------------------------------
st.markdown("---")
st.header("2. Watershed Map")

if not found_shapefiles and not found_sqlite:
    st.warning("No spatial data sources available. Please provide shapefile paths above.")
    st.stop()

# Load data and build map
@st.cache_data(show_spinner="Loading spatial layers...")
def load_spatial_data(paths_str: dict) -> dict:
    """Load all available spatial layers."""
    data = {}
    loader_inner = ShapefileLoader(".")

    for layer_type, path_s in paths_str.items():
        try:
            gdf = loader_inner.load_shapefile(Path(path_s))
            data[layer_type] = gdf
        except Exception as e:
            st.warning(f"Could not load {layer_type}: {e}")
    return data


# Load ALL available layers for data up front (cached).
paths_to_load = {
    k: v for k, v in found_shapefiles.items()
    if k in ("subbasins", "streams", "boundary", "reservoirs")
}

paths_str = {k: str(v) for k, v in paths_to_load.items()}

with st.status("Loading spatial data...", expanded=False) as _load_status:
    spatial_data = load_spatial_data(paths_str) if paths_str else {}
    _n_loaded = len(spatial_data)
    if _n_loaded:
        _load_status.update(label=f"Loaded {_n_loaded} spatial layer(s)", state="complete")
    else:
        _load_status.update(label="No spatial layers loaded", state="complete")

# Store in session state for other pages
for layer_type, gdf in spatial_data.items():
    st.session_state[f"{layer_type}_gdf"] = gdf

# Build the map with all available layers.
# Layer visibility is controlled via folium's built-in LayerControl
# (the checkbox panel in the top-right of the map). This runs entirely
# client-side in the browser — no Streamlit reruns, so the map never
# disappears when toggling layers.
builder = WatershedMapBuilder()

if spatial_data:
    first_gdf = next(iter(spatial_data.values()))
    builder.create_base_map(first_gdf)
else:
    builder.create_base_map()

# Add all available layers — folium LayerControl lets users toggle them
fitted = False
if "boundary" in spatial_data:
    builder.add_boundary(spatial_data["boundary"])
    builder.fit_bounds(spatial_data["boundary"])
    fitted = True

if "subbasins" in spatial_data:
    builder.add_subbasins(spatial_data["subbasins"])
    if not fitted:
        builder.fit_bounds(spatial_data["subbasins"])
        fitted = True

if "streams" in spatial_data:
    builder.add_streams(spatial_data["streams"])

if "reservoirs" in spatial_data:
    builder.add_reservoirs(spatial_data["reservoirs"])

# Display map — returned_objects=[] prevents any map interaction from
# triggering a Streamlit rerun.
folium_map = builder.get_map()
st_folium(folium_map, width=None, height=550, returned_objects=[])

# -------------------------------------------------------------------------
# Section 3: Subbasin Selection & Details
# -------------------------------------------------------------------------
st.markdown("---")
st.header("3. Feature Details")

# Show summary statistics for loaded layers
if "subbasins" in spatial_data:
    gdf = spatial_data["subbasins"]

    with st.expander("Subbasin Summary", expanded=True):
        summary_col1, summary_col2, summary_col3 = st.columns(3)

        with summary_col1:
            st.metric("Total Subbasins", len(gdf))

        with summary_col2:
            # Try to compute total area
            if "Area" in gdf.columns or "AreaC" in gdf.columns:
                area_col = "Area" if "Area" in gdf.columns else "AreaC"
                total_area = gdf[area_col].sum()
                st.metric("Total Area", f"{total_area:,.1f}")
            elif gdf.crs and gdf.crs.is_projected:
                total_area = gdf.geometry.area.sum() / 1e6  # m2 to km2
                st.metric("Total Area", f"{total_area:,.1f} km2")

        with summary_col3:
            if gdf.crs:
                st.metric("CRS", str(gdf.crs.to_epsg() or gdf.crs))

        # Show attribute table
        st.markdown("**Attribute Table:**")
        display_cols = [c for c in gdf.columns if c != "geometry"]
        st.dataframe(gdf[display_cols], width="stretch")

if "streams" in spatial_data:
    with st.expander("Stream Network Summary"):
        gdf = spatial_data["streams"]
        st.metric("Stream Segments", len(gdf))
        display_cols = [c for c in gdf.columns if c != "geometry"]
        if display_cols:
            st.dataframe(gdf[display_cols].head(20), width="stretch")

# Navigation
st.markdown("---")
st.markdown("""
**Next Step:** Go to **Simulation Results** to view model output data, or
go to **Observation Data** to load observed measurements for calibration.
""")
