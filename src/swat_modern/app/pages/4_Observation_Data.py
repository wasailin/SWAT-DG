"""
Observation Data Page - Load observed data from multiple formats for calibration.

Supports: CSV, Excel, tab-delimited, space-delimited, USGS NWIS.
"""

import streamlit as st
import pandas as pd
import numpy as np
from pathlib import Path
from swat_modern.app.session_persistence import load_session, clear_session, browse_file, get_output_mtime, load_observation_data
from swat_modern.app.loading_utils import hide_deploy_button

st.set_page_config(page_title="Observation Data", page_icon="📊", layout="wide")
hide_deploy_button()

# Restore session state on page load (survives browser refresh)
load_session(st.session_state)
load_observation_data(st.session_state)

st.title("Observation Data")
st.markdown("Load observed streamflow or water quality data for calibration.")


# ---- CFS/CMS conversion constant ----
CFS_TO_CMS = 0.0283168466


def _detect_usgs_cfs(df: pd.DataFrame) -> bool:
    """Return True if any column name matches the USGS discharge pattern (00060)."""
    for col in df.columns:
        col_str = str(col)
        if "00060" in col_str and "_cd" not in col_str:
            return True
    return False

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

from swat_modern.io.observation_loader import ObservationLoader

# WQ-related constants
# Maps SWAT output variable names to constituent short names used by LoadCalculator
_SWAT_VAR_TO_CONSTITUENT = {
    "SED_OUTtons": "TSS",
    "TOT_Nkg": "TN",
    "TOT_Pkg": "TP",
    "ORGN_OUTkg": "ORGN",
    "ORGP_OUTkg": "ORGP",
    "NO3_OUTkg": "NO3",
    "MINP_OUTkg": "MINP",
    "NH4_OUTkg": "NH4",
    "SEDCONCmg_L": "TSS",
}
_WQ_VARIABLES = set(_SWAT_VAR_TO_CONSTITUENT.keys())


# ---------------------------------------------------------------------------
# Cached helper: detect routing pattern and upstream subbasins
# ---------------------------------------------------------------------------
@st.cache_data(show_spinner=False)
def _detect_routing_and_upstream(
    project_path: str, subbasin_id: int
) -> dict:
    """Detect whether output.rch has accumulated or local-only routing.

    For local-only routing, determine the set of upstream reach IDs
    (translated from subbasin IDs via fig.fig's subbasin_to_reach mapping)
    so the caller can sum FLOW_OUT across them in output.rch.

    IMPORTANT: The RCH column in output.rch contains REACH numbers, not
    subbasin numbers. Each reach routes a different subbasin's flow as
    determined by fig.fig.  To get subbasin N's flow, read the reach that
    routes it: ``sub_to_reach[N]``.

    Cached by Streamlit on (project_path, subbasin_id).
    """
    from swat_modern.io.parsers.fig_parser import (
        FigFileParser,
        find_qswat_shapes_dir,
        get_gis_upstream_subbasins,
    )

    project_dir = Path(project_path)
    fig_path = project_dir / "fig.fig"

    result = {
        "needs_accumulation": False,
        "upstream_reach_ids": set(),
        "upstream_subbasins": set(),
        "target_reach": subbasin_id,  # default: assume RCH = subbasin
        "sub_to_reach": {},
        "source": "direct",
        "message": "",
    }

    if not fig_path.exists():
        return result

    parser = FigFileParser(fig_path)
    parser.parse()

    sub_to_reach = dict(parser.subbasin_to_reach)
    result["sub_to_reach"] = sub_to_reach
    result["target_reach"] = sub_to_reach.get(subbasin_id, subbasin_id)

    if parser.has_accumulated_routing():
        result["source"] = "accumulated_routing"
        result["message"] = (
            "Routing is accumulated (traditional SWAT). "
            "FLOW_OUT already includes upstream flow."
        )
        return result

    # Local-only routing — need to sum upstream reaches
    result["needs_accumulation"] = True
    upstream_subs = set()

    # Priority 1: GIS topology (rivs1.shp or riv1.shp) — authoritative
    # physical routing.  For SWAT+ converted projects, the GIS shapefiles
    # come from the original SWAT+ model and reflect correct channel
    # connectivity.  The fig.fig may have incorrect topology.
    shapes_dir = find_qswat_shapes_dir(project_dir)
    if shapes_dir is not None:
        try:
            gis_subs = get_gis_upstream_subbasins(shapes_dir, subbasin_id)
            if gis_subs:
                upstream_subs = gis_subs
                result["source"] = "gis"
        except Exception:
            pass

    # Priority 2: fig.fig ADD-chain tracing — fallback if no GIS shapefiles
    if not upstream_subs:
        upstream_subs = parser.get_upstream_subbasins_by_subbasin(subbasin_id)
        result["source"] = "fig"

    # Translate subbasin IDs → reach IDs for output.rch filtering
    upstream_reaches = {
        sub_to_reach[int(s)]
        for s in upstream_subs
        if int(s) in sub_to_reach
    }
    result["upstream_subbasins"] = upstream_subs
    result["upstream_reach_ids"] = upstream_reaches
    result["message"] = (
        f"Local-only routing detected. Auto-detected "
        f"{len(upstream_subs)} upstream subbasins "
        f"via {result['source'].upper()} topology."
    )
    return result


@st.cache_data(show_spinner=False)
def _read_subbasin_areas(project_path: str) -> dict:
    """Read SUB_KM from each .sub file. Returns {sub_id: area_km2}."""
    import re
    areas = {}
    proj = Path(project_path)
    for f in sorted(proj.glob("*.sub")):
        name = f.stem
        if len(name) != 9 or not name.isdigit():
            continue
        sub_id = int(name[:5])
        with open(f) as fh:
            for line in fh:
                if "SUB_KM" in line:
                    try:
                        areas[sub_id] = float(line.split("|")[0].strip())
                    except ValueError:
                        pass
                    break
    return areas


st.markdown("---")

# -------------------------------------------------------------------------
# Section 1: Data Source Selection
# -------------------------------------------------------------------------
st.header("1. Load Observation Data")

tab_file, tab_nwis, tab_wq = st.tabs(
    ["Upload Streamflow observation", "USGS NWIS", "Upload Water Quality observation"]
)

# Track whether data was freshly loaded this run (vs restored from session)
_newly_loaded = False
# Flags set by specific loading tabs
_nwis_units = None  # units string when loaded via NWIS

# Restore previously loaded data from session state
df = st.session_state.get("_obs_loaded_df")
source_info = st.session_state.get("_obs_source_info", "")
_nwis_units = st.session_state.get("_obs_nwis_units")

with tab_file:
    uploaded_file = st.file_uploader(
        "Upload observation data file",
        type=["csv", "xlsx", "xls", "txt", "tsv", "rdb", "dat"],
        help="Supports CSV, Excel, tab/space-delimited, and USGS RDB formats",
    )

    if uploaded_file is not None:
        try:
            _new_df = ObservationLoader.load_from_buffer(uploaded_file, uploaded_file.name)
            df = _new_df
            source_info = f"Uploaded: {uploaded_file.name}"
            _nwis_units = None
            _newly_loaded = True
            st.success(f"Loaded {len(df)} rows from {uploaded_file.name}")
        except Exception as e:
            st.error(f"Error reading file: {e}")

with tab_nwis:
    st.markdown("Fetch data directly from the **USGS National Water Information System**.")

    nwis_col1, nwis_col2 = st.columns(2)

    with nwis_col1:
        site_number = st.text_input(
            "USGS Site Number",
            placeholder="07196500",
            help="Enter the USGS gage station number",
        )

        try:
            from swat_modern.io.nwis_loader import NWISLoader, PARAMETER_CODES
            param_options = {
                code: f"{info['name']} ({info['units']}) - {code}"
                for code, info in PARAMETER_CODES.items()
            }
            param_code = st.selectbox(
                "Parameter",
                options=list(param_options.keys()),
                format_func=lambda x: param_options[x],
            )
            nwis_available = True
        except ImportError:
            st.warning("Install `requests` for NWIS data: `pip install swat-dg[data]`")
            param_code = "00060"
            nwis_available = False

    with nwis_col2:
        nwis_start = st.date_input("Start Date", value=pd.Timestamp("2010-01-01"))
        nwis_end = st.date_input("End Date", value=pd.Timestamp("2020-12-31"))

    if nwis_available and site_number:
        if st.button("Fetch USGS Data", type="primary"):
            try:
                with st.status(
                    f"Fetching USGS data for site {site_number}...",
                    expanded=True,
                ) as fetch_status:
                    st.write(f"Connecting to USGS NWIS service...")
                    nwis_df = NWISLoader.fetch_daily_values(
                        site_number=site_number,
                        parameter_code=param_code,
                        start_date=str(nwis_start),
                        end_date=str(nwis_end),
                    )
                    st.write(f"Processing response...")

                    if len(nwis_df) > 0:
                        fetch_status.update(
                            label=f"Fetched {len(nwis_df)} daily values from USGS",
                            state="complete",
                        )
                    else:
                        fetch_status.update(
                            label="No data returned — check site number and date range",
                            state="error",
                        )

                if len(nwis_df) > 0:
                    df = nwis_df
                    source_info = f"USGS {site_number} ({PARAMETER_CODES[param_code]['name']})"
                    _nwis_units = PARAMETER_CODES[param_code]["units"]
                    _newly_loaded = True
                    # Store for download button persistence
                    st.session_state["_nwis_fetched_df"] = nwis_df
                    st.session_state["_nwis_fetched_site"] = site_number
                else:
                    st.warning("No data returned. Check site number and date range.")
            except Exception as e:
                st.error(f"Error fetching USGS data: {e}")

    # Download button for previously fetched NWIS data
    if "_nwis_fetched_df" in st.session_state:
        _nwis_dl_df = st.session_state["_nwis_fetched_df"]
        _nwis_dl_site = st.session_state.get("_nwis_fetched_site", "usgs")
        _nwis_csv = _nwis_dl_df.to_csv(index=False)
        st.download_button(
            label=f"Download fetched data ({len(_nwis_dl_df)} rows)",
            data=_nwis_csv,
            file_name=f"USGS_{_nwis_dl_site}.csv",
            mime="text/csv",
            key="nwis_download_btn",
        )

with tab_wq:
    st.markdown(
        "Load water quality concentration data (mg/L) from multi-format WQ files. "
        "Supported formats: ADEQ CSV, OBSfiles, AWRC/WQP narrow-result, generic CSV."
    )

    _wq_source = st.radio(
        "WQ data source",
        ["Upload file", "File path"],
        horizontal=True,
        key="obs_wq_source_radio",
    )

    _wq_file_path = None  # resolved path to the WQ file on disk

    if _wq_source == "Upload file":
        wq_uploaded = st.file_uploader(
            "Upload WQ observation file",
            type=["csv", "xlsx", "xls", "txt"],
            key="obs_wq_upload",
            help="CSV or text file with water quality concentration data",
        )
        if wq_uploaded is not None:
            import tempfile
            import os as _wq_os
            # Write to temp file so loader can read it
            with tempfile.NamedTemporaryFile(
                delete=False, suffix=Path(wq_uploaded.name).suffix or ".csv"
            ) as _wqtmp:
                _wqtmp.write(wq_uploaded.getvalue())
                _wq_file_path = _wqtmp.name
    else:
        wq_uploaded = None  # not used in path mode
        # Apply browsed path
        _browsed_wq = st.session_state.get("_browsed_wq_file", "")
        _wq_col_p, _wq_col_b = st.columns([4, 1])
        with _wq_col_p:
            _wq_path_input = st.text_input(
                "WQ file path:",
                value=_browsed_wq,
                placeholder="C:/path/to/narrowresult.csv",
                help="Full path to your WQ concentration data file",
                key="obs_wq_path_input",
            )
        with _wq_col_b:
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("Browse...", key="browse_wq_file", width="stretch"):
                _wq_selected = browse_file(
                    title="Select WQ Observation File",
                    filetypes=[
                        ("CSV files", "*.csv"),
                        ("Text files", "*.txt;*.tsv;*.dat"),
                        ("All files", "*.*"),
                    ],
                )
                if _wq_selected:
                    st.session_state._browsed_wq_file = _wq_selected
                    st.rerun()

        if _wq_path_input and Path(_wq_path_input).exists():
            _wq_file_path = _wq_path_input
        elif _wq_path_input:
            st.warning("File not found. Check the path.")

    if _wq_file_path is not None:
        try:
            from swat_modern.io.wq_observation_loader import (
                WQObservationLoader,
                calculate_total_nitrogen,
                calculate_total_phosphorus,
                get_available_stations,
            )

            _wq_is_temp = _wq_source == "Upload file"  # temp file needs cleanup

            # --- Format selection ---
            _wq_format_options = {
                "Auto-detect": "auto",
                "Water Quality Portal (WQP)": "awrc",
                "Generic CSV": "generic",
            }
            _wq_format_label = st.selectbox(
                "WQ file format",
                list(_wq_format_options.keys()),
                key="obs_wq_format",
                help="Auto-detect tries all formats. Select a specific format if auto fails.",
            )
            wq_format = _wq_format_options[_wq_format_label]

            # --- Station detection and selection ---
            wq_station_id = None
            try:
                _wq_stations = get_available_stations(
                    _wq_file_path,
                    format=wq_format if wq_format != "auto" else "auto",
                )
            except Exception:
                _wq_stations = []

            if _wq_stations and len(_wq_stations) > 1:
                st.markdown(
                    f"**{len(_wq_stations)} stations** detected in this file."
                )
                # Let user browse stations with a selectbox
                _station_options = ["(All stations)"] + _wq_stations
                _selected_station = st.selectbox(
                    "Select station",
                    options=_station_options,
                    key="obs_wq_station_select",
                    help=(
                        "Choose a specific monitoring station to load data from. "
                        "Or select '(All stations)' to load all."
                    ),
                )
                if _selected_station != "(All stations)":
                    wq_station_id = _selected_station

                # Also allow searching by typing
                with st.expander("Search stations"):
                    _search = st.text_input(
                        "Filter stations",
                        key="obs_wq_station_search",
                        placeholder="Type to filter (e.g. ARK, USGS, OK121700)",
                    )
                    if _search:
                        _matches = [
                            s for s in _wq_stations
                            if _search.upper() in s.upper()
                        ]
                        if _matches:
                            st.caption(f"{len(_matches)} matches:")
                            for _m in _matches[:20]:
                                st.text(_m)
                            if len(_matches) > 20:
                                st.caption(f"... and {len(_matches) - 20} more")
                        else:
                            st.caption("No matches found.")
            elif _wq_stations and len(_wq_stations) == 1:
                wq_station_id = _wq_stations[0]
                st.caption(f"Single station detected: **{wq_station_id}**")
            else:
                # No station column or couldn't detect — allow manual entry
                _manual_station = st.text_input(
                    "Station ID (optional, for multi-station files)",
                    key="obs_wq_station_manual",
                )
                if _manual_station and _manual_station.strip():
                    wq_station_id = _manual_station.strip()

            # --- Load WQ data ---
            if st.button("Load WQ Data", key="obs_wq_load_btn", type="primary"):
                try:
                    wq_raw = WQObservationLoader.load(
                        _wq_file_path,
                        format=wq_format if wq_format != "auto" else "auto",
                        station_id=wq_station_id,
                    )
                except Exception as e:
                    st.error(f"Failed to load WQ data: {e}")
                    wq_raw = None

                if wq_raw is not None and not wq_raw.empty:
                    # Calculate TN/TP from species if needed
                    wq_raw = calculate_total_nitrogen(wq_raw)
                    wq_raw = calculate_total_phosphorus(wq_raw)

                    _station_label = (
                        f" (station: {wq_station_id})" if wq_station_id else ""
                    )
                    st.success(
                        f"Loaded {len(wq_raw)} WQ observation records"
                        f"{_station_label}"
                    )

                    # Show available constituents
                    _wq_avail = []
                    for _wqcol, _wqlbl in [
                        ("TN_mg_L", "Total Nitrogen"),
                        ("TP_mg_L", "Total Phosphorus"),
                        ("TSS_mg_L", "TSS"),
                        ("NO3_mg_L", "NO3"),
                        ("NH4_mg_L", "NH4"),
                        ("OrgN_mg_L", "Organic N"),
                        ("OrthoP_mg_L", "Ortho-P"),
                        ("TKN_mg_L", "TKN"),
                        ("SedDis_ton_day", "Sed. Discharge (tons/day)"),
                    ]:
                        if _wqcol in wq_raw.columns:
                            _n = wq_raw[_wqcol].notna().sum()
                            if _n > 0:
                                _wq_avail.append(f"{_wqlbl}: {_n} samples")
                    if _wq_avail:
                        st.markdown(
                            "**Available constituents:** " + " | ".join(_wq_avail)
                        )

                    with st.expander("Preview WQ Data"):
                        st.dataframe(wq_raw.head(20))

                    # Store raw WQ DataFrame for flow pairing later
                    st.session_state["_wq_raw_df"] = wq_raw
                    _newly_loaded = True
                    _wq_display_name = wq_uploaded.name if wq_uploaded is not None else Path(_wq_file_path).name
                    source_info = f"WQ: {_wq_display_name}{_station_label}"
                elif wq_raw is not None:
                    st.warning("WQ file loaded but contains no data rows.")
            else:
                # Show previously loaded WQ data if available
                if "_wq_raw_df" in st.session_state:
                    _prev_wq = st.session_state["_wq_raw_df"]
                    st.caption(
                        f"Previously loaded: {len(_prev_wq)} WQ records. "
                        f"Click **Load WQ Data** to reload with new settings."
                    )

            # Clean up temp file if we created one (upload mode only)
            if _wq_is_temp:
                import os as _wq_os
                try:
                    _wq_os.unlink(_wq_file_path)
                except OSError:
                    pass

        except ImportError:
            st.warning(
                "WQ observation loader not available. "
                "Ensure swat_modern.io.wq_observation_loader is installed."
            )

# Persist loaded data in session state so tab switches don't lose it
if _newly_loaded and df is not None:
    st.session_state["_obs_loaded_df"] = df
    st.session_state["_obs_source_info"] = source_info
    st.session_state["_obs_nwis_units"] = _nwis_units
    st.session_state.pop("_obs_do_process", None)
elif df is not None and not _newly_loaded:
    # Restored from session — show reminder
    st.info(f"Using previously loaded data: **{source_info}** ({len(df)} rows)")

# -------------------------------------------------------------------------
# Section 2: Column Configuration
# -------------------------------------------------------------------------
if df is not None and not df.empty:
    st.markdown("---")
    st.header("2. Configure Columns")

    # Auto-detect columns
    auto_date_col = ObservationLoader.detect_date_column(df)
    value_cols = ObservationLoader.detect_value_columns(df)

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("**Date column:**")
        all_cols = df.columns.tolist()
        date_idx = all_cols.index(auto_date_col) if auto_date_col in all_cols else 0
        date_col = st.selectbox(
            "Date column",
            options=all_cols,
            index=date_idx,
        )

        # Show detected date format
        if date_col in df.columns:
            detected_fmt = ObservationLoader.detect_date_format(df[date_col])
            fmt_display = detected_fmt if detected_fmt else "Auto-detect"

            date_format = st.selectbox(
                "Date format",
                options=[
                    "Auto-detect",
                    "%Y-%m-%d",
                    "%m/%d/%Y",
                    "%d/%m/%Y",
                    "%Y/%m/%d",
                    "%Y-%m-%d %H:%M:%S",
                    "%Y%m%d",
                ],
                index=0,
                help=f"Detected: {fmt_display}",
            )

    with col2:
        st.markdown("**Value column:**")
        value_idx = all_cols.index(value_cols[0]) if value_cols and value_cols[0] in all_cols else min(1, len(all_cols) - 1)
        value_col = st.selectbox(
            "Observed value column",
            options=all_cols,
            index=value_idx,
        )

        # Auto-detect units from NWIS metadata or USGS column patterns
        _is_usgs_cfs = _nwis_units == "cfs" or _detect_usgs_cfs(df)
        _units_list = ["m3/s", "cfs", "mm/day", "mg/L", "kg/day", "ug/L",
                       "tons/day", "ft3/s", "deg C"]
        _default_unit_idx = _units_list.index("cfs") if _is_usgs_cfs else 0
        units = st.selectbox(
            "Units",
            options=_units_list,
            index=_default_unit_idx,
        )

    # Prominent CFS -> CMS conversion when CFS is detected
    convert_cfs_to_cms = False
    if units == "cfs":
        st.warning(
            "Observed data appears to be in **cubic feet per second (CFS)**. "
            "SWAT outputs streamflow in **cubic meters per second (CMS)**. "
            "Enable conversion below for correct comparison.",
            icon="\u26a0\ufe0f",
        )
        convert_cfs_to_cms = st.checkbox(
            "Convert CFS to CMS (multiply by 0.0283168)",
            value=True,
            help="Applies CFS \u00d7 0.0283168 = CMS conversion before comparison.",
        )

    # General unit conversion option (for non-CFS cases)
    convert_units = False
    target_units = units
    if not convert_cfs_to_cms:
        with st.expander("Unit Conversion (optional)"):
            convert_units = st.checkbox("Convert units before processing")
            if convert_units:
                target_units = st.selectbox(
                    "Convert to:",
                    options=["m3/s", "cfs", "mg/L", "kg/day"],
                )
                st.caption("Conversion will be applied when processing the data.")

    # -------------------------------------------------------------------------
    # Section 3: Calibration Target
    # -------------------------------------------------------------------------
    st.markdown("---")
    st.header("3. Calibration Target")

    target_col1, target_col2 = st.columns(2)

    with target_col1:
        output_type = st.selectbox(
            "Output type to calibrate",
            options=["rch (Reach)", "sub (Subbasin)", "hru (HRU)"],
        )

    with target_col2:
        _id_label = "HRU ID" if "hru" in output_type else "Subbasin ID"
        reach_id = st.number_input(
            _id_label,
            min_value=1,
            value=1,
            help="Subbasin number where the gauge is located (matches RCH column in output.rch). For local-only routing, upstream flow is accumulated automatically.",
        )

    # Variable selection
    if "rch" in output_type:
        variable = st.selectbox(
            "SWAT output variable",
            options=["FLOW_OUTcms", "SED_OUTtons", "ORGN_OUTkg", "ORGP_OUTkg",
                     "NO3_OUTkg", "MINP_OUTkg", "NH4_OUTkg", "SEDCONCmg_L",
                     "TOT_Nkg", "TOT_Pkg"],
        )
    elif "sub" in output_type:
        variable = st.selectbox(
            "SWAT output variable",
            options=["WYLDmm", "SYLDt_ha", "ORGNkg_ha", "ORGPkg_ha",
                     "NSURQkg_ha", "SOLPkg_ha", "SEDPkg_ha"],
        )
    else:
        variable = st.selectbox(
            "SWAT output variable",
            options=["WYLDmm", "SYLDt_ha", "ORGNkg_ha", "ORGPkg_ha",
                     "NSURQkg_ha", "SOLPkg_ha"],
        )

    # -------------------------------------------------------------------------
    # Upstream subbasin configuration (rch output only)
    # -------------------------------------------------------------------------
    _obs_upstream_subs = None  # None = no accumulation, set = accumulate

    if "rch" in output_type and "project_path" in st.session_state:
        with st.expander("Upstream Subbasins (for flow accumulation)", expanded=False):
            st.markdown(
                "For **local-only routing** models, FLOW_OUT in output.rch contains "
                "only local subbasin flow. To compare against a gauge that measures "
                "accumulated upstream flow, specify which subbasins to sum."
            )

            # Read subbasin areas
            _sub_areas = _read_subbasin_areas(st.session_state.project_path)

            # Auto-detect suggestion from fig.fig
            _routing = _detect_routing_and_upstream(
                st.session_state.project_path, reach_id
            )
            _auto_subs = sorted(_routing.get("upstream_subbasins", set()))

            if _routing.get("source") == "accumulated_routing":
                st.info(
                    "Routing is **accumulated** (traditional SWAT). "
                    "FLOW_OUT already includes upstream flow — no manual "
                    "accumulation needed."
                )
            else:
                # Show auto-detected suggestion
                if _auto_subs:
                    _auto_area = sum(_sub_areas.get(s, 0) for s in _auto_subs)
                    _det_src = _routing.get("source", "auto").upper()
                    st.caption(
                        f"Auto-detected ({_det_src}): {_auto_subs} "
                        f"(total area: {_auto_area:,.0f} km2)"
                    )

                # User input for upstream subbasins
                _default_val = (
                    ", ".join(str(s) for s in _auto_subs) if _auto_subs else ""
                )
                _ups_input = st.text_input(
                    "Upstream subbasins (comma-separated, leave blank for local flow only)",
                    value=st.session_state.get("obs_upstream_override", _default_val),
                    placeholder="e.g. 1,2,4,5,6,10",
                    key="obs_upstream_input",
                    help=(
                        "Subbasin IDs to sum for accumulated flow. "
                        "Use the area table below to verify your selection."
                    ),
                )
                # Store for session persistence
                st.session_state["obs_upstream_override"] = _ups_input

                if _ups_input and _ups_input.strip():
                    try:
                        _obs_upstream_subs = {
                            int(x.strip())
                            for x in _ups_input.split(",")
                            if x.strip()
                        }
                        _sel_area = sum(
                            _sub_areas.get(s, 0) for s in _obs_upstream_subs
                        )
                        _total_area = sum(_sub_areas.values())
                        st.caption(
                            f"Selected: {len(_obs_upstream_subs)} subbasins, "
                            f"total area: **{_sel_area:,.0f} km2** "
                            f"({100 * _sel_area / _total_area:.1f}% of watershed)"
                        )
                    except ValueError:
                        st.warning("Invalid input. Use comma-separated integers.")

                # Show area reference table
                if _sub_areas:
                    with st.expander("Subbasin areas (from .sub files)"):
                        _area_rows = [
                            {"Sub": s, "Area (km2)": f"{a:,.1f}"}
                            for s, a in sorted(_sub_areas.items())
                        ]
                        st.dataframe(
                            pd.DataFrame(_area_rows),
                            hide_index=True,
                            height=250,
                        )
                        st.caption(
                            f"Total watershed area: {sum(_sub_areas.values()):,.0f} km2"
                        )

    # -------------------------------------------------------------------------
    # Section 3b: WQ Flow Pairing (when WQ variable selected)
    # -------------------------------------------------------------------------
    _is_wq = "rch" in output_type and variable in _WQ_VARIABLES
    _wq_load_result = None  # Will hold computed load DataFrame if WQ pairing succeeds

    if _is_wq and "_wq_raw_df" in st.session_state:
        st.markdown("---")
        st.header("3b. Pair WQ Concentrations with Flow")

        _constituent = _SWAT_VAR_TO_CONSTITUENT.get(variable, "TN")
        st.info(
            f"WQ observations are concentrations (mg/L). SWAT outputs **{variable}** "
            f"as loads. To compare, observed loads are computed as: "
            f"**load = concentration x flow x conversion factor**."
        )

        _wq_flow_source = st.radio(
            "Flow source for load computation",
            ["Use current simulated streamflow (output.rch on disk)",
             "Upload observed streamflow file"],
            key="obs_wq_flow_source",
            help=(
                "Simulated flow reads FLOW_OUT from the current output.rch. "
                "Upload if you have observed streamflow for more accurate loads."
            ),
        )

        _wq_flow_df = None

        if _wq_flow_source.startswith("Use current"):
            # Read FLOW_OUT from output.rch for the selected reach
            if "project_path" in st.session_state:
                try:
                    from swat_modern.io.parsers.result_browser import ResultBrowser

                    @st.cache_resource
                    def _get_wq_browser(path: str, mtime: float) -> "ResultBrowser":
                        return ResultBrowser(path)

                    _wq_browser = _get_wq_browser(
                        st.session_state.project_path,
                        get_output_mtime(st.session_state.project_path),
                    )

                    # Determine target reach ID
                    _wq_routing = _detect_routing_and_upstream(
                        st.session_state.project_path, reach_id
                    )
                    _wq_target_rch = _wq_routing.get("target_reach", reach_id)

                    # Get flow time series (accumulated if needed)
                    if (
                        _obs_upstream_subs
                        and len(_obs_upstream_subs) > 0
                        and _wq_routing
                    ):
                        _wq_s2r = _wq_routing.get("sub_to_reach", {})
                        _wq_upstream_reaches = {
                            _wq_s2r[s] for s in _obs_upstream_subs if s in _wq_s2r
                        }
                        if _wq_upstream_reaches:
                            _wq_flow_ts = _wq_browser.get_accumulated_time_series(
                                "rch", "FLOW_OUTcms",
                                _wq_upstream_reaches, _wq_target_rch,
                            )
                        else:
                            _wq_flow_ts = _wq_browser.get_time_series(
                                "rch", "FLOW_OUTcms", _wq_target_rch
                            )
                    else:
                        _wq_flow_ts = _wq_browser.get_time_series(
                            "rch", "FLOW_OUTcms", _wq_target_rch
                        )

                    if not _wq_flow_ts.empty:
                        _wq_flow_df = pd.DataFrame({
                            "date": _wq_flow_ts.index,
                            "flow_cms": _wq_flow_ts["FLOW_OUTcms"].values,
                        })
                        st.caption(
                            f"Loaded {len(_wq_flow_df)} daily simulated flow values "
                            f"from output.rch (reach {_wq_target_rch})."
                        )
                    else:
                        st.warning(
                            "No simulated flow data found in output.rch. "
                            "Run SWAT first, or upload observed streamflow."
                        )
                except Exception as _wq_err:
                    st.warning(f"Could not read simulated flow: {_wq_err}")
            else:
                st.warning("Load a SWAT project first to use simulated flow.")
        else:
            # Upload observed streamflow
            _wq_obs_flow_file = st.file_uploader(
                "Upload observed streamflow file",
                type=["csv", "xlsx", "xls", "txt", "tsv"],
                key="obs_wq_flow_upload",
            )
            if _wq_obs_flow_file is not None:
                try:
                    _wq_flow_raw = ObservationLoader.load_from_buffer(
                        _wq_obs_flow_file, _wq_obs_flow_file.name
                    )
                    _wq_date_col = ObservationLoader.detect_date_column(_wq_flow_raw)
                    _wq_val_cols = ObservationLoader.detect_value_columns(_wq_flow_raw)
                    if _wq_date_col and _wq_val_cols:
                        _wq_flow_df = pd.DataFrame({
                            "date": pd.to_datetime(_wq_flow_raw[_wq_date_col]),
                            "flow_cms": pd.to_numeric(
                                _wq_flow_raw[_wq_val_cols[0]], errors="coerce"
                            ),
                        }).dropna()
                        st.caption(
                            f"Loaded {len(_wq_flow_df)} observed flow values "
                            f"from {_wq_obs_flow_file.name}."
                        )
                    else:
                        st.error("Could not detect date/value columns in flow file.")
                except Exception as _e:
                    st.error(f"Error loading flow file: {_e}")

        # Compute loads
        if _wq_flow_df is not None:
            try:
                from swat_modern.calibration.load_calculator import LoadCalculator

                _wq_raw = st.session_state["_wq_raw_df"]
                _lc = LoadCalculator(_wq_raw, constituents=[_constituent])
                _wq_loads = _lc.compute_loads(_wq_flow_df)

                if not _wq_loads.empty:
                    # Find the load column
                    _load_cols = [c for c in _wq_loads.columns if c != "date"]
                    if _load_cols:
                        _wq_load_result = _wq_loads
                        st.success(
                            f"Computed {len(_wq_loads)} paired load observations "
                            f"for **{_constituent}** (column: {_load_cols[0]})."
                        )
                        with st.expander("Preview Load Data"):
                            st.dataframe(_wq_loads.head(20))
                else:
                    st.warning(
                        "No loads computed. Check that WQ observation dates "
                        "overlap with flow data dates."
                    )
            except Exception as _e:
                st.error(f"Error computing loads: {_e}")

    elif _is_wq and "_wq_raw_df" not in st.session_state:
        st.markdown("---")
        st.info(
            f"**{variable}** is a water quality variable. "
            f"To load concentration observations, use the **Upload Water Quality observation** "
            f"tab above, then return here to pair with flow data."
        )

    # -------------------------------------------------------------------------
    # Section 4: Process & Validate
    # -------------------------------------------------------------------------
    st.markdown("---")

    # Determine button label based on WQ state
    _process_label = "Process and Validate Data"
    if _is_wq and _wq_load_result is not None:
        _process_label = "Process WQ Load Data"

    if st.button(_process_label, type="primary"):
        st.session_state["_obs_do_process"] = True

    if st.session_state.get("_obs_do_process", False):
        try:
            # --- WQ load path: use pre-computed load result ---
            if _is_wq and _wq_load_result is not None:
                _load_cols = [c for c in _wq_load_result.columns if c != "date"]
                _load_col = _load_cols[0]
                dates = pd.to_datetime(_wq_load_result["date"])
                values = _wq_load_result[_load_col].values
                # Determine units from load column name
                if "tons" in _load_col:
                    units = "tons/day"
                elif "kg" in _load_col:
                    units = "kg/day"
                else:
                    units = "load/day"
                convert_cfs_to_cms = False
                convert_units = False
            else:
                # --- Standard path: parse from loaded DataFrame ---
                # Parse dates (if already datetime, skip re-parsing)
                if pd.api.types.is_datetime64_any_dtype(df[date_col]):
                    dates = df[date_col]
                elif date_format == "Auto-detect":
                    dates = pd.to_datetime(df[date_col])
                else:
                    dates = pd.to_datetime(df[date_col], format=date_format)

                # Get values
                values = pd.to_numeric(df[value_col], errors="coerce")

            # Apply CFS -> CMS conversion
            if convert_cfs_to_cms:
                values = values * CFS_TO_CMS
                units = "m3/s"
                st.info(
                    f"Converted CFS \u2192 CMS "
                    f"(\u00d7 {CFS_TO_CMS})"
                )
            # Apply general unit conversion if requested
            elif convert_units:
                try:
                    from swat_modern.io.unit_converter import convert_flow
                    values = convert_flow(values, units, target_units)
                    units = target_units
                    st.info(f"Units converted to {target_units}")
                except Exception as e:
                    st.warning(f"Unit conversion skipped: {e}")

            # Create clean dataframe
            obs_df = pd.DataFrame({
                "date": dates,
                "observed": values,
            }).dropna()
            obs_df = obs_df.set_index("date").sort_index()

            # Store in session state (backward compatible)
            st.session_state.observed_data = obs_df["observed"]
            st.session_state.obs_units = units
            st.session_state.output_type = output_type.split()[0]
            st.session_state.reach_id = reach_id
            st.session_state.output_variable = variable
            # Store WQ constituent if applicable
            if _is_wq and _wq_load_result is not None:
                st.session_state.wq_constituent = _SWAT_VAR_TO_CONSTITUENT.get(
                    variable
                )
            else:
                st.session_state.pop("wq_constituent", None)

            # Also store in multi-site format
            if "observed_data_multi" not in st.session_state:
                st.session_state.observed_data_multi = {}
            st.session_state.observed_data_multi[reach_id] = obs_df["observed"]

            # Persist observation data to disk so it survives browser refreshes
            # and carries over to the Calibration page
            from swat_modern.app.session_persistence import save_observation_data, save_session
            save_observation_data(st.session_state)
            save_session(st.session_state)

            st.success(f"Processed {len(obs_df)} valid observations")

            # Summary statistics
            st.header("4. Data Summary")

            stat_col1, stat_col2, stat_col3, stat_col4 = st.columns(4)
            with stat_col1:
                st.metric("Total Observations", len(obs_df))
            with stat_col2:
                date_range = f"{obs_df.index.min().strftime('%Y-%m-%d')} to {obs_df.index.max().strftime('%Y-%m-%d')}"
                st.metric("Date Range", date_range)
            with stat_col3:
                st.metric("Mean Value", f"{obs_df['observed'].mean():.2f} {units}")
            with stat_col4:
                st.metric("Max Value", f"{obs_df['observed'].max():.2f} {units}")

            # Interactive plot
            st.header("5. Data Preview")

            # Try to load matching simulation output for overlay
            sim_series = None
            sim_label = None
            _routing_info = None

            if "project_path" in st.session_state:
                try:
                    from swat_modern.io.parsers.result_browser import ResultBrowser

                    @st.cache_resource
                    def _get_browser(path: str, output_mtime: float) -> ResultBrowser:
                        return ResultBrowser(path)

                    browser = _get_browser(
                        st.session_state.project_path,
                        get_output_mtime(st.session_state.project_path),
                    )
                    out_type = output_type.split()[0]  # e.g. "rch"

                    if out_type in browser.list_available_outputs():
                        # Determine the reach ID to query in output.rch.
                        # RCH column = reach number, not subbasin number.
                        _routing_info = None
                        _target_rch = reach_id  # default if no fig.fig

                        if out_type == "rch":
                            _routing_info = _detect_routing_and_upstream(
                                st.session_state.project_path, reach_id
                            )
                            if _routing_info:
                                _target_rch = _routing_info.get(
                                    "target_reach", reach_id
                                )

                        # Use user-specified upstream subs from the UI
                        if (
                            out_type == "rch"
                            and _obs_upstream_subs
                            and len(_obs_upstream_subs) > 0
                            and _routing_info
                        ):
                            _s2r = _routing_info.get("sub_to_reach", {})
                            _upstream_reaches = {
                                _s2r[s] for s in _obs_upstream_subs
                                if s in _s2r
                            }
                            if _upstream_reaches:
                                ts_df = browser.get_accumulated_time_series(
                                    out_type, variable,
                                    _upstream_reaches, _target_rch,
                                )
                                if not ts_df.empty:
                                    sim_series = ts_df[variable]
                                    sim_label = (
                                        f"{variable} (accumulated, "
                                        f"{len(_obs_upstream_subs)} subbasins)"
                                    )
                                    _routing_info = dict(_routing_info)
                                    _routing_info["message"] = (
                                        f"Accumulating flow from "
                                        f"{len(_obs_upstream_subs)} subbasins "
                                        f"({len(_upstream_reaches)} reaches)."
                                    )
                                    _routing_info["source"] = "user_specified"
                        if sim_series is None:
                            ts_df = browser.get_time_series(
                                out_type, variable, _target_rch
                            )
                            if not ts_df.empty:
                                sim_series = ts_df[variable]
                                sim_label = f"{variable} (simulated)"
                except Exception:
                    pass  # Simulation output not available — show observed only

            # Show routing detection info
            if _routing_info and _routing_info.get("message"):
                _src = _routing_info.get("source", "")
                if _src == "accumulated_routing":
                    st.info(_routing_info["message"], icon="\u2705")
                elif _src == "user_specified":
                    st.info(_routing_info["message"], icon="\u2705")
                elif _src in ("gis", "fig", "user_override"):
                    st.warning(_routing_info["message"], icon="\u26a0\ufe0f")

            try:
                from swat_modern.visualization.plotly_charts import _require_plotly
                import plotly.graph_objects as go
                _require_plotly()

                fig = go.Figure()

                # Simulated trace (behind observed)
                if sim_series is not None:
                    fig.add_trace(go.Scatter(
                        x=sim_series.index,
                        y=sim_series.values,
                        mode="lines",
                        name=sim_label,
                        line=dict(color="#ff7f0e", width=1.2),
                        hovertemplate=f"{sim_label}: %{{y:.3f}}<extra></extra>",
                    ))

                # Observed trace
                fig.add_trace(go.Scatter(
                    x=obs_df.index,
                    y=obs_df["observed"],
                    mode="lines",
                    name="Observed",
                    line=dict(color="#1f77b4", width=1.5),
                    hovertemplate="Observed: %{y:.3f}<extra></extra>",
                ))

                chart_title = f"Observed vs Simulated - {source_info}" if sim_series is not None else f"Observed Data - {source_info}"
                fig.update_layout(
                    title=chart_title,
                    yaxis_title=f"Value ({units})",
                    xaxis_title="Date",
                    height=450,
                    hovermode="x unified",
                    legend=dict(orientation="h", yanchor="bottom", y=1.02,
                                xanchor="right", x=1),
                    template="plotly_white",
                )
                fig.update_xaxes(rangeslider_visible=True)
                st.plotly_chart(fig, width="stretch")

                if sim_series is None:
                    st.caption("No simulation output found. Run SWAT first to compare observed vs simulated.")

            except ImportError:
                import matplotlib.pyplot as plt
                fig, ax = plt.subplots(figsize=(12, 4))
                ax.plot(obs_df.index, obs_df["observed"], color="#1f77b4",
                        linewidth=0.8, label="Observed")
                if sim_series is not None:
                    ax.plot(sim_series.index, sim_series.values, color="#ff7f0e",
                            linewidth=0.8, label=sim_label)
                    ax.legend()
                ax.set_xlabel("Date")
                ax.set_ylabel(f"Value ({units})")
                ax.set_title("Observed vs Simulated" if sim_series is not None
                             else "Observed Data Time Series")
                ax.grid(True, alpha=0.3)
                plt.tight_layout()
                st.pyplot(fig)

            # ----------------------------------------------------------
            # Pre-Calibration Statistics (observed vs simulated)
            # ----------------------------------------------------------
            if sim_series is not None:
                try:
                    from swat_modern.calibration.objectives import (
                        evaluate_model, model_performance_rating,
                    )

                    # Detect temporal frequencies
                    def _detect_freq(idx):
                        if len(idx) < 3:
                            return "unknown"
                        diffs = pd.Series(idx).diff().dt.days.dropna()
                        med = diffs.median()
                        if med < 5:
                            return "daily"
                        elif med < 45:
                            return "monthly"
                        return "annual"

                    _obs_freq = _detect_freq(obs_df.index)
                    _sim_freq = _detect_freq(sim_series.index)

                    # Aggregate to common resolution (deduplicate dates first)
                    _obs_aligned = obs_df["observed"].copy()
                    if _obs_aligned.index.duplicated().any():
                        _obs_aligned = _obs_aligned.groupby(_obs_aligned.index).mean()
                    _sim_aligned = sim_series.copy()
                    if _sim_aligned.index.duplicated().any():
                        _sim_aligned = _sim_aligned.groupby(_sim_aligned.index).mean()

                    _freq_rank = {"daily": 0, "monthly": 1, "annual": 2, "unknown": -1}
                    _target_freq = max(_obs_freq, _sim_freq, key=lambda f: _freq_rank.get(f, -1))

                    if _target_freq == "monthly" or (
                        _obs_freq == "monthly" or _sim_freq == "monthly"
                    ):
                        # Aggregate both to year-month and merge by period
                        # so that different day-of-month values (1st vs 31st)
                        # still match within the same month.
                        _obs_ym = _obs_aligned.groupby(
                            _obs_aligned.index.to_period("M")
                        ).mean()
                        _sim_ym = _sim_aligned.groupby(
                            _sim_aligned.index.to_period("M")
                        ).mean()
                        _common_periods = _obs_ym.index.intersection(_sim_ym.index)
                        _obs_aligned = _obs_ym.loc[_common_periods]
                        _sim_aligned = _sim_ym.loc[_common_periods]
                        # Convert period index back to timestamp for display
                        _obs_aligned.index = _common_periods.to_timestamp()
                        _sim_aligned.index = _common_periods.to_timestamp()
                    elif _target_freq == "annual":
                        _obs_yr = _obs_aligned.groupby(
                            _obs_aligned.index.year
                        ).mean()
                        _sim_yr = _sim_aligned.groupby(
                            _sim_aligned.index.year
                        ).mean()
                        _common_yrs = _obs_yr.index.intersection(_sim_yr.index)
                        _obs_aligned = _obs_yr.loc[_common_yrs]
                        _sim_aligned = _sim_yr.loc[_common_yrs]
                        _obs_aligned.index = pd.to_datetime(_common_yrs, format="%Y")
                        _sim_aligned.index = pd.to_datetime(_common_yrs, format="%Y")
                    else:
                        # Daily or unknown: exact date match as before
                        pass

                    # Find overlapping period
                    _common_idx = _obs_aligned.index.intersection(_sim_aligned.index)
                    if len(_common_idx) > 0:
                        _o = _obs_aligned.loc[_common_idx].values.astype(float)
                        _s = _sim_aligned.loc[_common_idx].values.astype(float)
                        _mask = ~(np.isnan(_o) | np.isnan(_s))

                        if np.sum(_mask) >= 10:
                            _metrics = evaluate_model(_o[_mask], _s[_mask])

                            st.header("6. Pre-Calibration Statistics")
                            _mc1, _mc2, _mc3, _mc4, _mc5 = st.columns(5)
                            with _mc1:
                                st.metric("NSE", f"{_metrics['nse']:.4f}")
                            with _mc2:
                                st.metric("KGE", f"{_metrics['kge']:.4f}")
                            with _mc3:
                                st.metric("PBIAS", f"{_metrics['pbias']:.2f}%")
                            with _mc4:
                                st.metric("RMSE", f"{_metrics['rmse']:.3f}")
                            with _mc5:
                                st.metric("R\u00b2", f"{_metrics['r_squared']:.4f}")

                            _rating = model_performance_rating(_metrics["nse"])
                            _disp_freq = _obs_freq if _obs_freq != "unknown" else _sim_freq
                            st.caption(
                                f"Performance rating (Moriasi et al. 2007): **{_rating}** | "
                                f"Overlap: {_common_idx.min():%Y-%m-%d} to "
                                f"{_common_idx.max():%Y-%m-%d} | "
                                f"Resolution: {_disp_freq} | "
                                f"Points: {int(np.sum(_mask))}"
                            )
                        elif len(_common_idx) > 0:
                            st.warning(
                                f"Only {int(np.sum(_mask))} overlapping points found "
                                f"(need at least 10 for statistics). "
                                f"Check that observation and simulation periods overlap."
                            )
                    else:
                        st.warning(
                            "No overlapping dates between observed and simulated data. "
                            f"Observed: {obs_df.index.min():%Y-%m-%d} to {obs_df.index.max():%Y-%m-%d} | "
                            f"Simulated: {sim_series.index.min():%Y-%m-%d} to {sim_series.index.max():%Y-%m-%d}"
                        )
                except ImportError:
                    pass  # objectives module not available
                except Exception as _stats_err:
                    st.caption(f"Could not compute statistics: {_stats_err}")

            # Data table
            with st.expander("View Data Table"):
                st.dataframe(obs_df.head(100))
                if len(obs_df) > 100:
                    st.info(f"Showing first 100 of {len(obs_df)} rows")

        except Exception as e:
            st.error(f"Error processing data: {e}")
            with st.expander("Details"):
                st.exception(e)

# -------------------------------------------------------------------------
# Multi-site observations
# -------------------------------------------------------------------------
if "observed_data_multi" in st.session_state and len(st.session_state.observed_data_multi) > 0:
    st.markdown("---")
    st.header("Multi-Site Observations")

    for rid, obs in st.session_state.observed_data_multi.items():
        st.caption(
            f"  Site {rid}: {len(obs)} observations "
            f"({obs.index.min().strftime('%Y-%m-%d')} to {obs.index.max().strftime('%Y-%m-%d')})"
        )

# -------------------------------------------------------------------------
# Current Status
# -------------------------------------------------------------------------
st.markdown("---")
st.header("Current Status")

_cur_var = st.session_state.get("output_variable", "FLOW_OUTcms")
_cur_is_wq = _cur_var in _WQ_VARIABLES

if "observed_data" in st.session_state:
    obs = st.session_state.observed_data
    _data_type = "WQ load" if _cur_is_wq else "Streamflow"
    st.success(f"""
    **{_data_type} observation data loaded:**
    - {len(obs)} observations
    - From {obs.index.min().strftime('%Y-%m-%d')} to {obs.index.max().strftime('%Y-%m-%d')}
    - Target: {st.session_state.get('output_type', 'rch')} #{st.session_state.get('reach_id', 1)}
    - Variable: {_cur_var}
    """)
else:
    if _cur_is_wq:
        st.info(
            f"No WQ observation data loaded yet. Use the **Upload Water Quality observation** "
            f"tab above to load concentration data and pair with flow."
        )
    else:
        st.info("No streamflow observation data loaded yet.")

# WQ raw data status (independent of processed observation data)
if "_wq_raw_df" in st.session_state:
    _wq_raw = st.session_state["_wq_raw_df"]
    _wq_cols = [c for c in _wq_raw.columns if c != "date" and _wq_raw[c].notna().any()]
    st.caption(
        f"WQ concentration data loaded: {len(_wq_raw)} records, "
        f"constituents: {', '.join(_wq_cols)}"
    )

# Navigation
st.markdown("---")
st.markdown("""
**Next Step:** Go to **Parameter Editor** to review and customize calibration boundaries,
or go to **Calibration** to run auto-calibration.
""")
