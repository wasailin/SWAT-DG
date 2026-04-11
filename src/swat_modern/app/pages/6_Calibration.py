"""
Calibration Page - Select parameters and run auto-calibration.

Supports three calibration modes:
- Single-site: calibrate against one observation gauge
- Simultaneous multi-site: calibrate against multiple gauges with weighted objective
- Sequential upstream-to-downstream: step-by-step calibration from upstream to downstream
"""

import time
import streamlit as st
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import timedelta
from swat_modern.app.session_persistence import load_session, clear_session, browse_file, load_calibration_results, clear_calibration_results, load_observation_data
from swat_modern.io.observation_loader import ObservationLoader
from swat_modern.app.calibration_runner import (
    start_calibration,
    start_sensitivity,
    check_and_transfer_results,
    get_active_sensitivity_state,
    get_active_calibration_state,
    clear_active_sensitivity_state,
    clear_active_calibration_state,
)

try:
    from swat_modern.app.loading_utils import inject_progress_css, hide_deploy_button
except ImportError:
    def inject_progress_css(): pass
    def hide_deploy_button(): pass


def _load_uploaded_observation(uploaded_file) -> pd.DataFrame:
    """Load observation data from a Streamlit uploaded file using flexible parsing."""
    df = ObservationLoader.load_from_buffer(uploaded_file, uploaded_file.name)
    if df.empty:
        return df
    # Auto-detect and parse date column
    date_col = ObservationLoader.detect_date_column(df)
    if date_col and date_col in df.columns:
        if not pd.api.types.is_datetime64_any_dtype(df[date_col]):
            date_fmt = ObservationLoader.detect_date_format(df[date_col])
            try:
                if date_fmt and date_fmt != "auto":
                    df[date_col] = pd.to_datetime(df[date_col], format=date_fmt)
                else:
                    df[date_col] = pd.to_datetime(df[date_col])
            except Exception:
                pass
    return df

def _calibration_period_picker(obs_df: pd.DataFrame, key_prefix: str = "cal") -> pd.DataFrame:
    """Show date range pickers constrained to observation data and return filtered df.

    The selectable range is the **intersection** of:
    1. The observation data date range.
    2. The SWAT model's available output period (if a project is loaded).

    Parameters
    ----------
    obs_df : pd.DataFrame
        Must contain a datetime 'date' column and an 'observed' column.
    key_prefix : str
        Unique prefix for Streamlit widget keys (avoids collisions in multi-site).

    Returns
    -------
    pd.DataFrame
        Observation data filtered to the selected calibration period.
    """
    date_col = ObservationLoader.detect_date_column(obs_df)
    if date_col is None or date_col not in obs_df.columns:
        return obs_df

    dates = pd.to_datetime(obs_df[date_col], errors="coerce").dropna().sort_values()
    if len(dates) < 2:
        return obs_df

    obs_min = dates.min().date()
    obs_max = dates.max().date()

    # Determine SWAT model periods (current sim + weather data range)
    _sim_min = None   # current simulation output start
    _sim_max = None   # current simulation output end
    _wx_min = None    # available weather data start
    _wx_max = None    # available weather data end
    if "project_path" in st.session_state:
        try:
            from swat_modern.core.config import SWATConfig as _SWATConfig
            from pathlib import Path as _Path
            _cfg = _SWATConfig(_Path(st.session_state.project_path))
            _sim_start_yr = _cfg.period.start_year
            _sim_end_yr = _cfg.period.end_year
            _nyskip = _cfg.period.warmup_years
            _sim_min = pd.Timestamp(f"{_sim_start_yr}-01-01").date()
            _sim_max = pd.Timestamp(f"{_sim_end_yr}-12-31").date()
            _weather = _cfg.get_weather_data_period()
            if _weather:
                _wx_min = pd.Timestamp(f"{_weather[0]}-01-01").date()
                _wx_max = pd.Timestamp(f"{_weather[1]}-12-31").date()
        except Exception:
            pass

    # Effective range = intersection of obs dates and weather data range
    # (weather range is the hard limit; simulation period can be adjusted)
    eff_min = obs_min
    eff_max = obs_max
    _hard_min = _wx_min if _wx_min is not None else _sim_min
    _hard_max = _wx_max if _wx_max is not None else _sim_max
    if _hard_min is not None and _hard_min > eff_min:
        eff_min = _hard_min
    if _hard_max is not None and _hard_max < eff_max:
        eff_max = _hard_max

    # Count records in the effective range
    _eff_mask = (dates.dt.date >= eff_min) & (dates.dt.date <= eff_max)
    _n_effective = _eff_mask.sum()

    st.markdown("**Observation Comparison Window**")

    # Show period info
    _info_parts = [
        f"Observations: **{obs_min}** to **{obs_max}** ({len(dates)} records)",
    ]
    if _sim_min is not None:
        _info_parts.append(
            f"Current simulation: **{_sim_min.year}--{_sim_max.year}** "
            f"({_sim_max.year - _sim_min.year + 1} years, "
            f"warmup: {_nyskip} years)"
        )
    if _wx_min is not None:
        _info_parts.append(
            f"Available weather data: **{_wx_min.year}--{_wx_max.year}** "
            f"({_wx_max.year - _wx_min.year + 1} years)"
        )
    _info_parts.append(
        f"Effective range: **{eff_min}** to **{eff_max}** "
        f"({_n_effective} overlapping records)"
    )
    st.info("  \n".join(_info_parts))

    if _n_effective == 0:
        st.error(
            "No observations overlap with the SWAT model output period. "
            "Check your model simulation dates or upload a different WQ file."
        )
        return obs_df.iloc[:0]

    use_custom = st.checkbox(
        "Restrict observation comparison window",
        value=False,
        key=f"{key_prefix}_use_custom_period",
        help="Select a subset of observation dates for computing fit statistics "
             "(KGE, NSE). Does not change how many years SWAT simulates.",
    )

    if not use_custom:
        # Auto-filter to effective range
        mask = (
            (pd.to_datetime(obs_df[date_col]).dt.date >= eff_min)
            & (pd.to_datetime(obs_df[date_col]).dt.date <= eff_max)
        )
        filtered = obs_df.loc[mask].copy()
        st.caption(
            f"Using full effective period: **{eff_min}** to **{eff_max}** "
            f"({len(filtered)} records)"
        )
        return filtered

    cp_col1, cp_col2 = st.columns(2)
    with cp_col1:
        cal_start = st.date_input(
            "Start date",
            value=eff_min,
            min_value=eff_min,
            max_value=eff_max,
            key=f"{key_prefix}_cal_start",
        )
    with cp_col2:
        cal_end = st.date_input(
            "End date",
            value=eff_max,
            min_value=eff_min,
            max_value=eff_max,
            key=f"{key_prefix}_cal_end",
        )

    if cal_start >= cal_end:
        st.error("Start date must be before end date.")
        return obs_df

    # Filter observation data to the selected period
    mask = (
        (pd.to_datetime(obs_df[date_col]).dt.date >= cal_start)
        & (pd.to_datetime(obs_df[date_col]).dt.date <= cal_end)
    )
    filtered = obs_df.loc[mask].copy()
    n_filtered = len(filtered)

    if n_filtered < 10:
        st.warning(f"Only {n_filtered} observations in the selected period. At least 10 are recommended.")
    else:
        st.caption(
            f"Calibration period: **{cal_start}** to **{cal_end}** "
            f"({n_filtered} of {len(obs_df)} records)"
        )

    return filtered


# -------------------------------------------------------------------------
# WQ Observation + Flow Pairing helper (reused in single-site & multi-site)
# -------------------------------------------------------------------------
# SWAT variable \u2192 constituent short name mapping
_SWAT_VAR_TO_CONSTITUENT = {
    "SED_OUTtons": "TSS", "TOT_Nkg": "TN", "TOT_Pkg": "TP",
    "ORGN_OUTkg": "ORGN", "ORGP_OUTkg": "ORGP", "NO3_OUTkg": "NO3",
    "MINP_OUTkg": "MINP", "NH4_OUTkg": "NH4", "SEDCONCmg_L": "TSS",
}
# Constituent \u2192 WQ observation column mapping
# SWAT ORGP_OUTkg = organic phosphorus (no direct WQ observation column)
# SWAT MINP_OUTkg = mineral/dissolved P ≈ orthophosphate (OrthoP_mg_L)
_CONSTITUENT_TO_WQ_COL = {
    "TN": "TN_mg_L", "TP": "TP_mg_L", "TSS": "TSS_mg_L",
    "NO3": "NO3_mg_L", "NH4": "NH4_mg_L", "ORGN": "OrgN_mg_L",
    "MINP": "OrthoP_mg_L", "TKN": "TKN_mg_L",
    "SedDis": "SedDis_ton_day",
}
# Constituents that are already loads (tons/day) — no flow pairing needed
_DIRECT_LOAD_CONSTITUENTS = {"SedDis"}


def _wq_observation_ui(
    output_variable: str,
    reach_id: int,
    key_prefix: str = "wq",
) -> "pd.DataFrame | None":
    """Render WQ observation upload, station selection, flow pairing, and
    return the computed load DataFrame with [date, observed] columns.

    Returns None if the user hasn't completed all steps yet.
    """
    _constituent = _SWAT_VAR_TO_CONSTITUENT.get(output_variable, "TN")
    _wq_col = _CONSTITUENT_TO_WQ_COL.get(_constituent, "TN_mg_L")

    st.info(
        f"Calibrating **{output_variable}** (water quality \u2014 {_constituent}). "
        f"Upload a WQ concentration file below and pair with streamflow to compute loads. "
        f"Make sure you have applied your best calibrated streamflow parameters first."
    )

    # --- WQ File Upload ---
    st.markdown("**WQ Observation File**")
    _wq_file = st.file_uploader(
        "Upload WQ concentration file (CSV)",
        type=["csv", "txt"],
        key=f"{key_prefix}_wq_file",
        help="CSV with concentration data (mg/L). Supports ADEQ, AWRC/WQP narrow-result, OBSfiles, generic.",
    )

    _wq_df = None  # parsed WQ DataFrame

    if _wq_file is not None:
        import tempfile
        import os as _wq_os
        from swat_modern.io.wq_observation_loader import (
            WQObservationLoader, calculate_total_nitrogen,
            calculate_total_phosphorus, get_available_stations,
        )

        with tempfile.NamedTemporaryFile(delete=False, suffix=".csv") as _tmp:
            _tmp.write(_wq_file.getvalue())
            _tmp_path = _tmp.name

        _wq_fmt_options = {
            "Auto-detect": "auto",
            "Water Quality Portal (WQP)": "awrc",
            "Generic CSV": "generic",
        }
        _wq_fmt_label = st.selectbox(
            "WQ file format",
            list(_wq_fmt_options.keys()),
            key=f"{key_prefix}_wq_fmt",
        )
        _wq_fmt = _wq_fmt_options[_wq_fmt_label]

        # Station detection
        _wq_station = None
        try:
            _stations = get_available_stations(
                _tmp_path,
                format=_wq_fmt if _wq_fmt != "auto" else "auto",
            )
        except Exception:
            _stations = []

        if _stations and len(_stations) > 1:
            _opts = ["(All stations)"] + _stations
            _sel = st.selectbox(
                f"Select station ({len(_stations)} found)",
                options=_opts,
                key=f"{key_prefix}_wq_station",
            )
            if _sel != "(All stations)":
                _wq_station = _sel
        elif _stations and len(_stations) == 1:
            _wq_station = _stations[0]
            st.caption(f"Station: **{_wq_station}**")

        # Load WQ data
        try:
            _wq_df = WQObservationLoader.load(
                _tmp_path,
                format=_wq_fmt if _wq_fmt != "auto" else "auto",
                station_id=_wq_station,
            )
            _wq_df = calculate_total_nitrogen(_wq_df)
            _wq_df = calculate_total_phosphorus(_wq_df)

            if _wq_df is not None and not _wq_df.empty:
                # Store the full WQ DataFrame for multi-constituent mode
                st.session_state[f"{key_prefix}_wq_full"] = _wq_df
                _n_vals = _wq_df[_wq_col].notna().sum() if _wq_col in _wq_df.columns else 0
                _avail = []
                for _c, _l in [
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
                    if _c in _wq_df.columns and _wq_df[_c].notna().sum() > 0:
                        _avail.append(f"{_l}: {_wq_df[_c].notna().sum()}")
                st.success(
                    f"Loaded {len(_wq_df)} WQ records"
                    + (f" (station: {_wq_station})" if _wq_station else "")
                )
                if _avail:
                    st.markdown(
                        "**Available constituents:** " + " | ".join(_avail)
                    )

                # If the file has SedDis_ton_day and we're calibrating
                # SED_OUTtons, let the user choose between TSS (conc→load)
                # and direct sediment discharge (already in tons/day).
                _has_seddis = (
                    "SedDis_ton_day" in _wq_df.columns
                    and _wq_df["SedDis_ton_day"].notna().sum() > 0
                )
                if _has_seddis and output_variable == "SED_OUTtons":
                    _sed_choice = st.radio(
                        "Sediment observation type",
                        ["Suspended Sediment Discharge (tons/day — direct, no flow pairing)",
                         "TSS concentration (mg/L — requires flow pairing)"],
                        key=f"{key_prefix}_sed_choice",
                    )
                    if _sed_choice.startswith("Suspended"):
                        _constituent = "SedDis"
                        _wq_col = "SedDis_ton_day"
                        _n_vals = _wq_df[_wq_col].notna().sum()

                if _n_vals == 0:
                    st.warning(
                        f"No **{_wq_col}** data found for constituent **{_constituent}**. "
                        f"You can map a column from your file below, or check that "
                        f"the file contains this parameter."
                    )
                    # --- Column mapping fallback for any mode ---
                    # Show file columns that have numeric data so the user
                    # can manually pick which column corresponds to the
                    # required constituent.
                    _mappable_cols = [
                        c for c in _wq_df.columns
                        if c != "date"
                        and _wq_df[c].notna().sum() > 0
                    ]
                    if _mappable_cols:
                        _map_opts = ["(none — skip)"] + _mappable_cols
                        _user_mapped = st.selectbox(
                            f"Map a file column to **{_wq_col}** ({_constituent})",
                            options=_map_opts,
                            key=f"{key_prefix}_col_map_{_constituent}",
                            help=(
                                "Select the column that contains concentration "
                                "data (mg/L) for this constituent."
                            ),
                        )
                        if _user_mapped != "(none — skip)":
                            _wq_df[_wq_col] = pd.to_numeric(
                                _wq_df[_user_mapped], errors="coerce"
                            )
                            _n_vals = _wq_df[_wq_col].notna().sum()
                            if _n_vals > 0:
                                st.success(
                                    f"Mapped `{_user_mapped}` → `{_wq_col}`: "
                                    f"**{_n_vals}** values"
                                )
                                # Update stored full DataFrame
                                st.session_state[f"{key_prefix}_wq_full"] = _wq_df
                            else:
                                st.error(
                                    f"Column `{_user_mapped}` has no valid "
                                    f"numeric values."
                                )
            else:
                st.warning("WQ file loaded but contains no data rows.")
                _wq_df = None
        except Exception as _e:
            st.error(f"Failed to load WQ data: {_e}")
            _wq_df = None

        try:
            _wq_os.unlink(_tmp_path)
        except OSError:
            pass

    # --- Direct-load path (e.g. Suspended Sediment Discharge in tons/day) ---
    if (
        _wq_df is not None
        and not _wq_df.empty
        and _constituent in _DIRECT_LOAD_CONSTITUENTS
        and _wq_col in _wq_df.columns
    ):
        _direct = _wq_df[["date", _wq_col]].dropna().copy()
        _direct = _direct.rename(columns={_wq_col: "observed"})
        if not _direct.empty:
            st.success(
                f"**{len(_direct)}** direct load observations "
                f"({_constituent}, tons/day). No flow pairing needed."
            )
            with st.expander("Preview Direct Load Data"):
                st.dataframe(_direct.head(20))
            st.session_state.wq_load_data = _direct
            st.session_state._wq_deferred_flow = False
            return _direct
        else:
            st.warning(f"No valid {_wq_col} values found.")

    # --- Flow Source for Load Computation ---
    if _wq_df is not None and not _wq_df.empty:
        st.markdown("---")
        st.markdown("**Streamflow for Load Computation**")
        _flow_source = st.radio(
            "Flow source",
            ["Use SWAT simulated streamflow",
             "Upload observed streamflow file"],
            key=f"{key_prefix}_flow_source",
            help=(
                "**Simulated** will run SWAT automatically at calibration time "
                "to get daily flow, then pair with WQ concentrations to compute "
                "loads. No extra steps needed.\n\n"
                "**Upload** lets you provide observed flow from a gauge."
            ),
        )

        _flow_df = None

        if _flow_source.startswith("Use SWAT"):
            # Defer the SWAT run to calibration time. Store the WQ
            # concentration data and a flag so the calibration runner
            # knows to run SWAT for flow and compute loads before
            # starting the actual calibration.
            _n_conc = _wq_df[_wq_col].notna().sum() if _wq_col in _wq_df.columns else 0
            _date_range = (
                f"{_wq_df['date'].min().date()} to {_wq_df['date'].max().date()}"
                if "date" in _wq_df.columns else "unknown"
            )
            st.info(
                f"Will use SWAT simulated streamflow to compute "
                f"**{_constituent}** loads at calibration time. "
                f"{_n_conc} concentration values available ({_date_range})."
            )
            # Return a sentinel dict that the calibration runner
            # will detect and resolve into actual load observations.
            st.session_state[f"{key_prefix}_wq_deferred"] = {
                "wq_df": _wq_df,
                "constituent": _constituent,
                "wq_col": _wq_col,
            }
            # Return a placeholder DataFrame so the UI validation
            # passes (non-None = "observation data provided").
            # The calibration runner will replace this with real loads.
            _result = pd.DataFrame({
                "date": _wq_df["date"] if "date" in _wq_df.columns else [],
                "observed": _wq_df[_wq_col] if _wq_col in _wq_df.columns else [],
            }).dropna()
            st.caption(
                f"Using full observation period: "
                f"{_result['date'].min().date()} to "
                f"{_result['date'].max().date()} "
                f"({len(_result)} records)"
            )
            # Persist in session so it survives rerenders
            st.session_state.wq_load_data = _result
            st.session_state._wq_deferred_flow = True
            return _result
        else:
            _flow_file = st.file_uploader(
                "Upload observed streamflow file",
                type=["csv", "xlsx", "xls", "txt", "tsv"],
                key=f"{key_prefix}_flow_file",
            )
            if _flow_file is not None:
                try:
                    _flow_raw = _load_uploaded_observation(_flow_file)
                    _f_date = ObservationLoader.detect_date_column(_flow_raw)
                    _f_vals = ObservationLoader.detect_value_columns(_flow_raw)
                    if _f_date and _f_vals:
                        # Prefer CMS columns over CFS to avoid unit mismatch.
                        # detect_value_columns may return Q(CFS) before Q(CMS).
                        _cms_patterns = ["cms", "m3/s", "m\u00b3/s", "cumec"]
                        _cfs_patterns = ["cfs", "ft3/s", "ft\u00b3/s"]
                        _flow_col_name = _f_vals[0]  # default: first numeric
                        _flow_needs_conversion = False
                        # Check for CMS-named column first
                        for _vc in _f_vals:
                            if any(p in _vc.lower() for p in _cms_patterns):
                                _flow_col_name = _vc
                                break
                        else:
                            # No CMS column found \u2014 check if selected column is CFS
                            if any(p in _flow_col_name.lower() for p in _cfs_patterns):
                                _flow_needs_conversion = True
                                st.warning(
                                    f"Flow column **{_flow_col_name}** appears to be "
                                    f"in CFS (cubic feet per second). Converting to "
                                    f"CMS (m\u00b3/s) automatically (\u00d70.0283168)."
                                )

                        _flow_values = pd.to_numeric(
                            _flow_raw[_flow_col_name], errors="coerce"
                        )
                        if _flow_needs_conversion:
                            _flow_values = _flow_values * 0.0283168

                        _flow_df = pd.DataFrame({
                            "date": pd.to_datetime(_flow_raw[_f_date]),
                            "flow_cms": _flow_values,
                        }).dropna()
                        _conv_note = ", converted CFS\u2192CMS" if _flow_needs_conversion else ""
                        st.caption(
                            f"Loaded {len(_flow_df)} observed flow values "
                            f"(source column: {_flow_col_name}{_conv_note})."
                        )
                except Exception as _e:
                    st.error(f"Error loading flow file: {_e}")

        # --- Compute Loads ---
        if _flow_df is not None:
            try:
                from swat_modern.calibration.load_calculator import LoadCalculator

                _lc = LoadCalculator(_wq_df, constituents=[_constituent])
                _loads = _lc.compute_loads(_flow_df)

                if not _loads.empty:
                    _load_cols = [c for c in _loads.columns if c != "date"]
                    if _load_cols:
                        _load_col = _load_cols[0]
                        # Determine units
                        if "tons" in _load_col:
                            _units = "tons/day"
                        elif "kg" in _load_col:
                            _units = "kg/day"
                        else:
                            _units = "load/day"

                        # Build [date, observed] DataFrame
                        _result = pd.DataFrame({
                            "date": pd.to_datetime(_loads["date"]),
                            "observed": _loads[_load_col].values,
                        }).dropna()

                        st.success(
                            f"Computed **{len(_result)}** paired load observations "
                            f"for {_constituent} ({_units})."
                        )
                        with st.expander("Preview Load Data"):
                            st.dataframe(_result.head(20))
                        # Persist in session so it survives page rerenders
                        # (file uploaders reset on rerun).
                        import streamlit as _st_inner
                        _st_inner.session_state.wq_load_data = _result
                        return _result
                else:
                    st.warning(
                        "No loads computed. Check that WQ dates overlap with flow dates."
                    )
            except Exception as _e:
                st.error(f"Error computing loads: {_e}")

    return None


st.set_page_config(page_title="Calibration", page_icon="\u2699\ufe0f", layout="wide")
hide_deploy_button()

# Restore session state on page load (survives browser refresh)
load_session(st.session_state)
load_observation_data(st.session_state)
load_calibration_results(st.session_state)
inject_progress_css()

# Check if a background calibration just completed and transfer results
_cal_snap = check_and_transfer_results(st.session_state)

st.title("Model Calibration")
st.markdown("Select parameters and run automated calibration using SPOTPY.")

# Sidebar: Exit Project button
with st.sidebar:
    if "project_path" in st.session_state:
        if st.button("Exit Project", type="secondary", width="stretch"):
            clear_session(st.session_state)
            st.rerun()

# Check prerequisites
if "project_path" not in st.session_state:
    st.warning("Please load a SWAT project first in **Project Setup**.")
    st.stop()

#st.markdown("---")

# -------------------------------------------------------------------------
# Check for custom boundaries from Parameter Editor
# -------------------------------------------------------------------------
use_custom_boundaries = False
boundary_manager = None

if "boundary_manager" in st.session_state:
    from swat_modern.calibration.boundary_manager import BoundaryManager
    boundary_manager = st.session_state.boundary_manager

    if len(boundary_manager.enabled_parameters) > 0:
        use_custom_boundaries = True
        st.success(
            f"Using custom boundaries from **Parameter Editor**: "
            f"{len(boundary_manager.enabled_parameters)} parameters enabled"
        )

        with st.expander("View Custom Boundaries"):
            rows = []
            for name in boundary_manager.enabled_parameters:
                b = boundary_manager.get_boundary(name)
                rows.append({
                    "Parameter": name,
                    "Min": b.effective_min,
                    "Max": b.effective_max,
                    "Custom": "Yes" if b.custom_min is not None or b.custom_max is not None else "No",
                })
            st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)

        st.caption("To change boundaries, go to **Parameter Editor**.")

# -------------------------------------------------------------------------
# Output Variable Selection (moved before parameter selection so locking
# and recommended groups can react to the chosen variable)
# -------------------------------------------------------------------------
_section = 1

st.markdown("---")
st.header(f"{_section}. Output Variable")
_section += 1

_output_var_default = st.session_state.get("output_variable", "FLOW_OUTcms")
_output_var_options = [
    "FLOW_OUTcms", "SED_OUTtons", "TOT_Nkg", "TOT_Pkg",
    "ORGN_OUTkg", "NO3_OUTkg", "NH4_OUTkg", "ORGP_OUTkg", "MINP_OUTkg",
]
_output_var_idx = (
    _output_var_options.index(_output_var_default)
    if _output_var_default in _output_var_options
    else 0
)

cal_output_variable = st.selectbox(
    "SWAT output variable to calibrate",
    options=_output_var_options,
    index=_output_var_idx,
    key="cal_output_variable",
    help="Select the SWAT output variable to calibrate against observations.",
)
st.session_state.output_variable = cal_output_variable

_is_wq_variable = cal_output_variable != "FLOW_OUTcms"

# When switching away from a WQ variable, clear stale WQ session state so it
# doesn't bleed into a streamflow calibration run.  The keys below are set by
# the WQ observation UI and the deferred-flow path; if left over from a prior
# WQ run they cause the calibration runner to treat a streamflow run as a WQ
# run (shows "preparing WQ", passes nitrogen observations as single_site_observed).
_prev_wq_variable = st.session_state.get("_prev_is_wq_variable", _is_wq_variable)
if not _is_wq_variable and _prev_wq_variable:
    for _stale_key in (
        "_wq_deferred_flow",
        "single_wq_wq_deferred",
        "wq_wq_deferred",
        "wq_load_data",
    ):
        st.session_state.pop(_stale_key, None)
st.session_state._prev_is_wq_variable = _is_wq_variable

if _is_wq_variable:
    st.info(
        "**Recommended calibration order:** Flow \u2192 Sediment \u2192 Nitrogen \u2192 Phosphorus. "
        "Ensure streamflow is well-calibrated before calibrating water quality. "
        "Apply your best calibrated streamflow parameters to the project folder first."
    )

# Classify the output variable for dynamic UI (locking, recommended groups)
_SEDIMENT_VARS = {"SED_OUTtons", "SEDCONCmg_L"}
_NITROGEN_VARS = {"TOT_Nkg", "ORGN_OUTkg", "NO3_OUTkg", "NH4_OUTkg"}
_PHOSPHORUS_VARS = {"TOT_Pkg", "ORGP_OUTkg", "MINP_OUTkg"}

if cal_output_variable in _SEDIMENT_VARS:
    _output_category = "sediment"
elif cal_output_variable in _NITROGEN_VARS:
    _output_category = "nitrogen"
elif cal_output_variable in _PHOSPHORUS_VARS:
    _output_category = "phosphorus"
else:
    _output_category = "streamflow"

# -------------------------------------------------------------------------
# Parameter selection (fallback when no custom boundaries)
# -------------------------------------------------------------------------

if not use_custom_boundaries:
    st.header(f"{_section}. Select Calibration Parameters")
    _section += 1

    # Define available parameters by category
    PARAMETERS = {
        "Hydrology": {
            "CN2": {"desc": "SCS runoff curve number", "min": -0.25, "max": 0.25, "method": "multiply", "default": True},
            "ESCO": {"desc": "Soil evaporation compensation factor", "min": 0.01, "max": 1.0, "method": "replace", "default": True},
            "EPCO": {"desc": "Plant uptake compensation factor", "min": 0.01, "max": 1.0, "method": "replace", "default": False},
            "SURLAG": {"desc": "Surface runoff lag coefficient", "min": 1.0, "max": 24.0, "method": "replace", "default": False},
            "OV_N": {"desc": "Manning's n for overland flow", "min": 0.01, "max": 0.5, "method": "replace", "default": False},
            "CANMX": {"desc": "Maximum canopy storage (mm H2O)", "min": 0.0, "max": 100.0, "method": "replace", "default": False},
        },
        "Groundwater": {
            "GW_DELAY": {"desc": "Groundwater delay time (days)", "min": 0.0, "max": 500.0, "method": "replace", "default": True},
            "ALPHA_BF": {"desc": "Baseflow alpha factor", "min": 0.0, "max": 1.0, "method": "replace", "default": True},
            "GWQMN": {"desc": "Threshold depth for GW flow (mm)", "min": 0.0, "max": 5000.0, "method": "replace", "default": False},
            "GW_REVAP": {"desc": "Groundwater revap coefficient", "min": 0.02, "max": 0.2, "method": "replace", "default": False},
            "REVAPMN": {"desc": "Threshold for revap (mm)", "min": 0.0, "max": 500.0, "method": "replace", "default": False},
        },
        "Soil": {
            "SOL_AWC": {"desc": "Available water capacity", "min": -0.25, "max": 0.25, "method": "multiply", "default": False},
            "SOL_K": {"desc": "Saturated hydraulic conductivity", "min": -0.25, "max": 0.25, "method": "multiply", "default": False},
            "SOL_BD": {"desc": "Soil bulk density", "min": -0.25, "max": 0.25, "method": "multiply", "default": False},
        },
        "Routing": {
            "CH_N2": {"desc": "Channel Manning's n", "min": 0.01, "max": 0.3, "method": "replace", "default": False},
            "CH_K2": {"desc": "Channel hydraulic conductivity", "min": 0.0, "max": 150.0, "method": "replace", "default": False},
        },
        "Snow": {
            "SMFMX": {"desc": "Max melt rate for snow (mm/deg-C/day)", "min": 0.0, "max": 10.0, "method": "replace", "default": False},
            "SMFMN": {"desc": "Min melt rate for snow (mm/deg-C/day)", "min": 0.0, "max": 10.0, "method": "replace", "default": False},
            "SFTMP": {"desc": "Snowfall temperature (deg-C)", "min": -5.0, "max": 5.0, "method": "replace", "default": False},
            "SMTMP": {"desc": "Snow melt base temperature (deg-C)", "min": -5.0, "max": 5.0, "method": "replace", "default": False},
        },
        "Sediment": {
            "USLE_P": {"desc": "USLE support practice factor", "min": 0.0, "max": 1.0, "method": "replace", "default": False},
            "SPCON": {"desc": "Linear re-entrainment parameter", "min": 0.0001, "max": 0.01, "method": "replace", "default": False},
            "SPEXP": {"desc": "Exponent for sediment re-entrainment", "min": 1.0, "max": 2.0, "method": "replace", "default": False},
            "CH_COV1": {"desc": "Channel erodibility factor", "min": 0.0, "max": 1.0, "method": "replace", "default": False},
            "CH_COV2": {"desc": "Channel cover factor", "min": 0.0, "max": 1.0, "method": "replace", "default": False},
            "PRF": {"desc": "Peak rate adjustment factor", "min": 0.0, "max": 2.0, "method": "replace", "default": False},
            "ADJ_PKR": {"desc": "Peak rate adjustment for sediment routing", "min": 0.5, "max": 2.0, "method": "replace", "default": False},
        },
        "Nitrogen": {
            "CMN": {"desc": "Rate factor for humus mineralization of N", "min": 0.001, "max": 0.003, "method": "replace", "default": False},
            "NPERCO": {"desc": "Nitrogen percolation coefficient", "min": 0.0, "max": 1.0, "method": "replace", "default": False},
            "N_UPDIS": {"desc": "Nitrogen uptake distribution parameter", "min": 1.0, "max": 100.0, "method": "replace", "default": False},
            "CDN": {"desc": "Denitrification exponential rate coefficient", "min": 0.0, "max": 3.0, "method": "replace", "default": False},
            "SDNCO": {"desc": "Denitrification threshold water content", "min": 0.0, "max": 1.0, "method": "replace", "default": False},
            "ERORGN": {"desc": "Organic N enrichment ratio", "min": 0.0, "max": 5.0, "method": "replace", "default": False},
        },
        "Phosphorus": {
            "PPERCO": {"desc": "Phosphorus percolation coefficient", "min": 10.0, "max": 17.5, "method": "replace", "default": False},
            "PHOSKD": {"desc": "Phosphorus soil partitioning coefficient", "min": 100.0, "max": 200.0, "method": "replace", "default": False},
            "PSP": {"desc": "Phosphorus sorption coefficient", "min": 0.01, "max": 0.7, "method": "replace", "default": False},
            "P_UPDIS": {"desc": "Phosphorus uptake distribution parameter", "min": 1.0, "max": 100.0, "method": "replace", "default": False},
            "ERORGP": {"desc": "Organic P enrichment ratio", "min": 0.0, "max": 5.0, "method": "replace", "default": False},
        },
    }

    # Quick selection buttons
    # --- Quick Selection Groups (multi-select, toggle on/off) ---
    # Each group maps to a list of parameter names. Multiple groups can be
    # active simultaneously; the selected parameters are the union.
    QUICK_GROUPS = {
        "Recommended (4)": ["CN2", "ESCO", "GW_DELAY", "ALPHA_BF"],
        "Hydrology Focus": ["CN2", "ESCO", "EPCO", "SURLAG", "GW_DELAY", "ALPHA_BF"],
        "Include Snow": ["CN2", "ESCO", "GW_DELAY", "ALPHA_BF", "SMFMX", "SFTMP"],
        "Sediment Focus": ["USLE_P", "SPCON", "SPEXP", "CH_COV1", "CH_COV2", "PRF", "ADJ_PKR"],
        "Nitrogen Focus": ["CMN", "NPERCO", "N_UPDIS", "CDN", "SDNCO", "ERORGN"],
        "Phosphorus Focus": ["PPERCO", "PHOSKD", "PSP", "P_UPDIS", "ERORGP"],
    }

    # Map output variable category to a recommended quick group
    _CATEGORY_TO_GROUP = {
        "streamflow": "Recommended (4)",
        "sediment": "Sediment Focus",
        "nitrogen": "Nitrogen Focus",
        "phosphorus": "Phosphorus Focus",
    }
    _recommended_group = _CATEGORY_TO_GROUP.get(_output_category, "Recommended (4)")

    # Auto-switch recommended group when user changes the output variable
    _prev_category = st.session_state.get("_prev_output_category", "streamflow")
    if _prev_category != _output_category:
        # Output variable category changed — update the default selection
        st.session_state.active_quick_groups = {_recommended_group}
        _merged = []
        for _grp in st.session_state.active_quick_groups:
            for _p in QUICK_GROUPS.get(_grp, []):
                if _p not in _merged:
                    _merged.append(_p)
        st.session_state.selected_params = _merged
        # Sync checkbox session state keys
        _all_pnames = [p for cat in PARAMETERS.values() for p in cat]
        for _pn in _all_pnames:
            st.session_state[f"param_{_pn}"] = _pn in _merged
        st.session_state._prev_output_category = _output_category

    if "active_quick_groups" not in st.session_state:
        st.session_state.active_quick_groups = {_recommended_group}
        st.session_state._prev_output_category = _output_category

    def _sync_params_from_groups():
        """Recompute selected_params as the union of all active groups."""
        merged = []
        for grp in st.session_state.active_quick_groups:
            for p in QUICK_GROUPS[grp]:
                if p not in merged:
                    merged.append(p)
        st.session_state.selected_params = merged
        _all_param_names = [p for cat in PARAMETERS.values() for p in cat]
        for _pn in _all_param_names:
            st.session_state[f"param_{_pn}"] = _pn in merged

    def _toggle_group(group_name: str):
        if group_name in st.session_state.active_quick_groups:
            st.session_state.active_quick_groups.discard(group_name)
        else:
            st.session_state.active_quick_groups.add(group_name)
        _sync_params_from_groups()

    def _clear_all_groups():
        st.session_state.active_quick_groups = set()
        _sync_params_from_groups()

    st.markdown("**Quick Selection** *(click to toggle, combine multiple groups):*")
    group_names = list(QUICK_GROUPS.keys())

    quick_row1 = st.columns(4)
    quick_row2 = st.columns(4)
    all_slots = quick_row1 + quick_row2  # 8 slots

    for idx, grp_name in enumerate(group_names):
        is_active = grp_name in st.session_state.active_quick_groups
        with all_slots[idx]:
            if st.button(
                f"{'✓ ' if is_active else ''}{grp_name}",
                key=f"qgrp_{grp_name}",
                type="primary" if is_active else "secondary",
            ):
                _toggle_group(grp_name)
                st.rerun()

    # Clear All in the last slot of row 2
    with all_slots[len(group_names)]:
        if st.button("Clear All", key="qgrp_clear"):
            _clear_all_groups()
            st.rerun()

    # Initialize selected parameters
    if "selected_params" not in st.session_state:
        st.session_state.selected_params = ["CN2", "ESCO", "GW_DELAY", "ALPHA_BF"]

    # Parameter checkboxes by category
    st.markdown("---")
    st.markdown("**Select parameters to calibrate:**")

    # WQ parameter locking: when a non-streamflow output variable is selected,
    # auto-lock streamflow params and show a context-aware message
    _STREAMFLOW_CATEGORIES = {"Hydrology", "Groundwater", "Soil", "Routing", "Snow"}
    _wq_params_active = _output_category != "streamflow"

    if _wq_params_active:
        _CATEGORY_LABELS = {
            "sediment": "sediment",
            "nitrogen": "nitrogen",
            "phosphorus": "phosphorus",
        }
        _cat_label = _CATEGORY_LABELS.get(_output_category, "water quality")
        st.warning(
            f"Output variable is **{cal_output_variable}** ({_cat_label}). "
            f"Streamflow parameters are locked by default."
        )
        _unlock_streamflow = st.checkbox(
            "Unlock streamflow parameters (advanced)",
            value=False,
            key="unlock_streamflow_params",
            help="Enable this to modify streamflow-related parameters during WQ calibration.",
        )
    else:
        _unlock_streamflow = True  # all unlocked for streamflow calibration

    selected_params = []

    for category, params in PARAMETERS.items():
        _is_locked = _wq_params_active and not _unlock_streamflow and category in _STREAMFLOW_CATEGORIES
        _cat_label = f"{category}" + (" (locked)" if _is_locked else "")
        with st.expander(_cat_label, expanded=(category in ["Hydrology", "Groundwater"] and not _is_locked)):
            for param_name, param_info in params.items():
                is_selected = param_name in st.session_state.selected_params

                col1, col2, col3, col4 = st.columns([0.5, 2, 1, 1])

                with col1:
                    _pkey = f"param_{param_name}"
                    # Set default in session state (not via widget arg) to avoid
                    # Streamlit's "default value vs session state" warning.
                    if _pkey not in st.session_state:
                        st.session_state[_pkey] = is_selected
                    if _is_locked:
                        st.session_state[_pkey] = False
                        st.checkbox(
                            param_name, disabled=True,
                            key=_pkey,
                        )
                    else:
                        st.checkbox(param_name, key=_pkey)

                with col2:
                    st.caption(param_info["desc"])

                with col3:
                    st.caption(f"Range: [{param_info['min']}, {param_info['max']}]")

                with col4:
                    st.caption(f"Method: {param_info['method']}")

    # Rebuild selected_params from session state keys — these persist
    # across Streamlit reruns even when expanders are collapsed.
    selected_params = [
        param_name
        for category, params in PARAMETERS.items()
        for param_name in params
        if st.session_state.get(f"param_{param_name}", False)
    ]
    st.session_state.selected_params = selected_params

    st.info(f"**Selected:** {len(selected_params)} parameters: {', '.join(selected_params) if selected_params else 'None'}")

    st.caption("For advanced boundary editing, use the **Parameter Editor** page.")
else:
    selected_params = boundary_manager.enabled_parameters

# -------------------------------------------------------------------------
# Calibration Mode Selection
# -------------------------------------------------------------------------
st.markdown("---")
st.header(f"{_section}. Calibration Mode")
_section += 1

calibration_mode = st.radio(
    "Select calibration strategy",
    options=["single", "simultaneous", "sequential", "partial_section", "multi_constituent"],
    format_func=lambda x: {
        "single": "Single-site",
        "simultaneous": "Simultaneous Multi-site",
        "sequential": "Sequential (Upstream-to-Downstream)",
        "partial_section": "Partial Section",
        "multi_constituent": "Multi-Constituent (Flow \u2192 Sediment \u2192 N \u2192 P)",
    }[x],
    horizontal=True,
    help=(
        "**Single-site**: Calibrate against one observation gauge. "
        "**Simultaneous**: Optimize against multiple gauges with weighted objective. "
        "**Sequential**: Calibrate step-by-step from upstream gauges to downstream, "
        "locking parameters at each step. Supports all algorithms including Diagnostic-Guided. "
        "**Partial Section**: Calibrate only the subbasins between two selected points. "
        "Pick an observation location (end) and an upstream boundary (start). "
        "Parameters upstream of the start are locked at current values. "
        "**Multi-Constituent**: Phased calibration of Flow, Sediment, Nitrogen, "
        "and Phosphorus in sequence. Each phase locks its parameters before the "
        "next phase begins."
    ),
)
st.session_state.calibration_mode = calibration_mode

# -------------------------------------------------------------------------
# Multi-Constituent Phase Configuration
# -------------------------------------------------------------------------
if calibration_mode == "multi_constituent":
    st.markdown("---")
    st.subheader("Multi-Constituent Phase Configuration")
    st.info(
        "Configure each calibration phase. Phases run sequentially: "
        "Flow \u2192 Sediment \u2192 Nitrogen \u2192 Phosphorus. "
        "Disable phases you don't need."
    )

    from swat_modern.calibration.phased_calibrator import PhaseConfig
    from swat_modern.calibration.parameters import (
        get_streamflow_parameters, get_sediment_parameters,
        get_nitrogen_parameters, get_phosphorus_parameters,
    )

    _phase_defaults = [
        {"name": "streamflow", "label": "Streamflow", "params_func": get_streamflow_parameters,
         "output_var": "FLOW_OUTcms", "default_algo": "diagnostic", "default_iter": 15,
         "default_obj": "kge", "constituent": None},
        {"name": "sediment", "label": "Sediment", "params_func": get_sediment_parameters,
         "output_var": "SED_OUTtons", "default_algo": "diagnostic", "default_iter": 15,
         "default_obj": "nse", "constituent": "TSS"},
        {"name": "nitrogen", "label": "Nitrogen", "params_func": get_nitrogen_parameters,
         "output_var": "TOT_Nkg", "default_algo": "diagnostic", "default_iter": 15,
         "default_obj": "nse", "constituent": "TN"},
        {"name": "phosphorus", "label": "Phosphorus", "params_func": get_phosphorus_parameters,
         "output_var": "TOT_Pkg", "default_algo": "diagnostic", "default_iter": 15,
         "default_obj": "nse", "constituent": "TP"},
    ]

    _phased_config_list = []
    for _pd in _phase_defaults:
        with st.expander(f"**{_pd['label']}** Phase", expanded=(_pd['name'] == 'streamflow')):
            _pc_cols = st.columns([1, 2, 1, 1])
            _pc_enabled = _pc_cols[0].checkbox(
                "Enabled", value=True, key=f"phase_enabled_{_pd['name']}"
            )
            _pc_algo = _pc_cols[1].selectbox(
                "Algorithm",
                options=["diagnostic", "sceua", "dream", "lhs", "mc"],
                index=0,
                key=f"phase_algo_{_pd['name']}",
            )
            _pc_is_diag = _pc_algo == "diagnostic"
            _pc_n_iter = _pc_cols[2].number_input(
                "Max runs" if _pc_is_diag else "Iterations",
                min_value=5, max_value=10000,
                value=_pd['default_iter'] if _pc_is_diag else 2000,
                key=f"phase_iter_{_pd['name']}",
            )
            if _pc_is_diag:
                _pc_obj = "kge"
                _pc_cols[3].caption("Objective: KGE + PBIAS (built-in)")
            else:
                _pc_obj = _pc_cols[3].selectbox(
                    "Objective",
                    options=["kge", "nse", "log_nse"],
                    index=["kge", "nse", "log_nse"].index(_pd['default_obj']),
                    key=f"phase_obj_{_pd['name']}",
                )

            # Show parameters for this phase
            _pc_param_names = [p.name for p in _pd['params_func']()]
            st.caption(f"Parameters: {', '.join(_pc_param_names)}")

            _pc = PhaseConfig(
                name=_pd['name'],
                parameters=_pc_param_names,
                output_variable=_pd['output_var'],
                n_iterations=_pc_n_iter,
                algorithm=_pc_algo,
                objective=_pc_obj,
                enabled=_pc_enabled,
                constituent=_pd['constituent'],
            )
            _phased_config_list.append(_pc)

    st.session_state._phased_config = _phased_config_list

    # --- Multi-Constituent Observation Data ---
    st.markdown("---")
    st.subheader("Observation Data")

    _mc_reach = st.number_input(
        "Subbasin ID",
        min_value=1,
        value=st.session_state.get("reach_id", 1),
        key="mc_reach_id",
        help="The subbasin number where the gauge is located",
    )

    # Flow observations (required for all phases)
    st.markdown("**Streamflow Observations** (required)")

    # Show pre-loaded data from the Observation Data page if available
    _mc_has_page4 = "observed_data" in st.session_state
    if _mc_has_page4:
        _p4_raw = st.session_state.observed_data
        _p4_n = len(_p4_raw.dropna()) if hasattr(_p4_raw, "dropna") else len(_p4_raw)
        _p4_units = st.session_state.get("obs_units", "")
        try:
            _p4_range = f"{_p4_raw.index.min():%Y-%m-%d} to {_p4_raw.index.max():%Y-%m-%d}"
        except Exception:
            _p4_range = ""
        st.success(
            f"**{_p4_n}** observations loaded from the **Observation Data** page"
            + (f" ({_p4_range})" if _p4_range else "")
            + (f", units: {_p4_units}" if _p4_units else "")
            + "."
        )

    _mc_flow_file = st.file_uploader(
        "Upload a different flow file" if _mc_has_page4 else "Streamflow observation file",
        type=["csv", "xlsx", "xls", "txt", "tsv"],
        key="mc_flow_obs_file",
        help="CSV, Excel, or text file with date and streamflow columns (auto-detected)."
             + (" Leave empty to use the data loaded on the Observation Data page." if _mc_has_page4 else ""),
    )

    _mc_flow_obs = None
    if _mc_flow_file is not None:
        try:
            _mc_flow_obs = _load_uploaded_observation(_mc_flow_file)
            if _mc_flow_obs.empty:
                st.error("Could not parse uploaded flow file.")
                _mc_flow_obs = None
            else:
                _mc_numeric = ObservationLoader.detect_value_columns(_mc_flow_obs)
                if _mc_numeric:
                    _mc_flow_col = _mc_numeric[0]
                    if len(_mc_numeric) > 1:
                        _flow_names = {"flow", "streamflow", "discharge", "q", "observed", "value"}
                        _priority = [c for c in _mc_numeric if c.lower().strip() in _flow_names]
                        _rest = [c for c in _mc_numeric if c not in _priority]
                        _mc_flow_col = st.selectbox(
                            "Flow column", options=_priority + _rest, key="mc_flow_col"
                        )
                    _mc_date_col = ObservationLoader.detect_date_column(_mc_flow_obs)
                    _keep = [c for c in [_mc_date_col, _mc_flow_col] if c and c in _mc_flow_obs.columns]
                    _mc_flow_obs = _mc_flow_obs[_keep].rename(
                        columns={_mc_flow_col: "observed"} if _mc_flow_col != "observed" else {}
                    )
                    st.caption(f"Loaded {len(_mc_flow_obs)} flow observations.")
                else:
                    st.error("No numeric columns detected in flow file.")
                    _mc_flow_obs = None
        except Exception as _e:
            st.error(f"Error loading flow data: {_e}")
    elif "observed_data" in st.session_state:
        _obs_raw = st.session_state.observed_data
        if isinstance(_obs_raw, pd.Series):
            if isinstance(_obs_raw.index, pd.DatetimeIndex):
                _mc_flow_obs = pd.DataFrame({
                    "date": _obs_raw.index, "observed": _obs_raw.values,
                }).reset_index(drop=True)
            else:
                _mc_flow_obs = _obs_raw.reset_index()
                _mc_flow_obs.columns = ["date", "observed"]
        elif isinstance(_obs_raw, pd.DataFrame):
            _mc_flow_obs = _obs_raw

    if _mc_flow_obs is not None and not _mc_flow_obs.empty:
        _mc_flow_obs = _calibration_period_picker(_mc_flow_obs, key_prefix="mc_flow")

    # WQ observations (for enabled WQ phases)
    _wq_phases_enabled = [pc for pc in _phased_config_list if pc.constituent and pc.enabled]
    if _wq_phases_enabled:
        st.markdown("---")
        st.markdown(
            "**Water Quality Observations** "
            f"(needed for: {', '.join(pc.name.capitalize() for pc in _wq_phases_enabled)})"
        )
        _mc_wq_result = _wq_observation_ui(
            output_variable="TOT_Nkg",  # use TN as default to trigger WQ UI
            reach_id=_mc_reach,
            key_prefix="mc_wq",
        )
        if _mc_wq_result is not None:
            st.session_state._mc_wq_obs = _mc_wq_result
        elif "wq_load_data" in st.session_state:
            st.session_state._mc_wq_obs = st.session_state.wq_load_data
            st.caption("Using WQ load data from session (previously computed).")

        # --- Column availability check & manual mapping for WQ phases ---
        _PHASE_REQUIRED_COL = {
            "sediment": "TSS_mg_L",
            "nitrogen": "TN_mg_L",
            "phosphorus": "TP_mg_L",
        }
        # Get the full WQ DataFrame (from deferred dict or direct store)
        _mc_deferred_check = st.session_state.get("mc_wq_wq_deferred")
        _wq_full_check = None
        if _mc_deferred_check and isinstance(_mc_deferred_check, dict):
            _wq_full_check = _mc_deferred_check.get("wq_df")
        if _wq_full_check is None:
            _wq_full_check = st.session_state.get("mc_wq_wq_full")

        if _wq_full_check is not None and not _wq_full_check.empty:
            _missing_phases = []
            for _wp in _wq_phases_enabled:
                _req_col = _PHASE_REQUIRED_COL.get(_wp.name)
                if _req_col and (
                    _req_col not in _wq_full_check.columns
                    or _wq_full_check[_req_col].notna().sum() == 0
                ):
                    _missing_phases.append((_wp.name, _req_col))

            if _missing_phases:
                st.markdown("---")
                st.warning(
                    "The following enabled WQ phases have **no observation data** in the uploaded file: "
                    + ", ".join(f"**{n.capitalize()}** (needs `{c}`)" for n, c in _missing_phases)
                    + ". You can either **disable** those phases above, or **map columns** below."
                )

                # Let user map from file columns to required canonical columns
                _file_numeric_cols = [
                    c for c in _wq_full_check.columns
                    if c != "date" and _wq_full_check[c].dtype in ("float64", "int64", "object")
                    and _wq_full_check[c].notna().sum() > 0
                ]
                if _file_numeric_cols:
                    with st.expander("Manual Column Mapping", expanded=True):
                        st.caption(
                            "Map columns from your WQ file to the required constituent columns. "
                            "Select '(none)' to skip a constituent."
                        )
                        _mapping_changed = False
                        for _phase_name, _req_col in _missing_phases:
                            _opts = ["(none)"] + _file_numeric_cols
                            _mapped = st.selectbox(
                                f"{_phase_name.capitalize()} → `{_req_col}`",
                                options=_opts,
                                key=f"mc_wq_map_{_phase_name}",
                            )
                            if _mapped != "(none)":
                                _wq_full_check[_req_col] = pd.to_numeric(
                                    _wq_full_check[_mapped], errors="coerce"
                                )
                                _n = _wq_full_check[_req_col].notna().sum()
                                if _n > 0:
                                    st.success(f"Mapped `{_mapped}` → `{_req_col}`: {_n} values")
                                    _mapping_changed = True
                                else:
                                    st.error(f"Column `{_mapped}` has no valid numeric values.")

                        if _mapping_changed:
                            # Update the stored full WQ DataFrame
                            if _mc_deferred_check and isinstance(_mc_deferred_check, dict):
                                _mc_deferred_check["wq_df"] = _wq_full_check
                                st.session_state["mc_wq_wq_deferred"] = _mc_deferred_check
                            st.session_state["mc_wq_wq_full"] = _wq_full_check

    # Store flow obs for config assembly
    st.session_state._mc_flow_obs = _mc_flow_obs
    st.session_state._mc_reach = _mc_reach

# -------------------------------------------------------------------------
# Multi-site configuration (for simultaneous and sequential modes)
# -------------------------------------------------------------------------
calibration_sites = []

if calibration_mode in ("simultaneous", "sequential"):
    st.markdown("---")
    st.header(f"{_section}. Observation Sites")
    _section += 1

    if calibration_mode == "sequential":
        st.info(
            "**Sequential mode**: Sites will be automatically ordered from "
            "upstream to downstream based on the watershed routing topology (fig.fig). "
            "Parameters are calibrated for each sub-watershed segment and locked "
            "before proceeding downstream."
        )

    n_sites = st.number_input(
        "Number of observation sites",
        min_value=2,
        max_value=10,
        value=2,
        help="Total number of gauging stations for multi-site calibration",
    )

    for i in range(n_sites):
        site_num = i + 1
        st.markdown(f"**Site {site_num}**")

        s_col1, s_col3 = st.columns([1, 1])
        with s_col1:
            site_reach = st.number_input(
                f"Subbasin ID (Site {site_num})",
                min_value=1,
                value=st.session_state.get("reach_id", 1) if i == 0 else 1,
                key=f"site_reach_{i}",
                help="The subbasin number where the gauge is located",
            )
        with s_col3:
            site_weight = st.slider(
                f"Weight (Site {site_num})",
                0.1, 2.0, 1.0, 0.1,
                key=f"site_weight_{i}",
            )

        if _is_wq_variable:
            # ---- WQ path: per-site WQ upload + flow pairing ----
            _site_wq_result = _wq_observation_ui(
                output_variable=cal_output_variable,
                reach_id=site_reach,
                key_prefix=f"site{i}_wq",
            )
            if _site_wq_result is not None and not _site_wq_result.empty:
                _site_deferred_key = f"site{i}_wq_wq_deferred"
                if st.session_state.get(_site_deferred_key) is not None:
                    st.info(
                        "Calibration period for WQ loads with simulated "
                        "streamflow is controlled by the **Simulation "
                        "Period** and **Warmup Years** settings below."
                    )
                else:
                    _site_wq_result = _calibration_period_picker(
                        _site_wq_result, key_prefix=f"site{i}"
                    )
                _site_entry = {
                    "reach_id": site_reach,
                    "observed": _site_wq_result,
                    "weight": site_weight,
                }
                # Attach deferred WQ info if user chose simulated flow
                _site_deferred = st.session_state.get(f"site{i}_wq_wq_deferred")
                if _site_deferred is not None:
                    _site_entry["wq_deferred"] = _site_deferred
                calibration_sites.append(_site_entry)
        else:
            # ---- Standard streamflow path ----
            site_file = st.file_uploader(
                f"Streamflow observation file (Site {site_num})",
                type=["csv", "xlsx", "xls", "txt", "tsv"],
                key=f"site_file_{i}",
                help="CSV, Excel, or text file with date and streamflow columns (auto-detected)",
            )

            if site_file is not None:
                try:
                    site_df = _load_uploaded_observation(site_file)
                    if site_df.empty:
                        st.error(f"Site {site_num}: Could not parse uploaded file.")
                    else:
                        numeric_cols = ObservationLoader.detect_value_columns(site_df)
                        if len(numeric_cols) == 0:
                            st.error(f"Site {site_num}: No numeric value columns detected.")
                        else:
                            if len(numeric_cols) > 1:
                                _flow_names = {"flow", "streamflow", "discharge", "q", "observed", "value"}
                                _priority = [c for c in numeric_cols if c.lower().strip() in _flow_names]
                                _rest = [c for c in numeric_cols if c not in _priority]
                                _ordered = _priority + _rest
                                chosen_col = st.selectbox(
                                    f"Calibration column (Site {site_num})",
                                    options=_ordered,
                                    key=f"site_value_col_{i}",
                                    help="Select the column containing the values to calibrate against",
                                )
                            else:
                                chosen_col = numeric_cols[0]
                            date_col = ObservationLoader.detect_date_column(site_df)
                            keep = [c for c in [date_col, chosen_col] if c and c in site_df.columns]
                            site_df = site_df[keep].rename(
                                columns={chosen_col: "observed"} if chosen_col != "observed" else {}
                            )
                            site_df = _calibration_period_picker(
                                site_df, key_prefix=f"site{i}"
                            )
                            calibration_sites.append({
                                "reach_id": site_reach,
                                "observed": site_df,
                                "weight": site_weight,
                            })
                            st.caption(
                                f"Loaded {len(site_df)} observations for subbasin {site_reach} "
                                f"(columns: {', '.join(site_df.columns[:5])})"
                            )
                except Exception as e:
                    st.error(f"Error loading Site {site_num} data: {e}")
            else:
                st.caption(f"Upload observation data for Site {site_num}")

    if len(calibration_sites) < 2:
        st.warning(
            "Multi-site calibration requires at least 2 sites with data. "
            "Please upload observation files above."
        )

    st.session_state.calibration_sites_data = calibration_sites

# -------------------------------------------------------------------------
# Partial Section configuration
# -------------------------------------------------------------------------
ps_end_sub = None
ps_start_sub = None
ps_observed = None

if calibration_mode == "partial_section":
    st.markdown("---")
    st.header(f"{_section}. Partial Section Configuration")
    _section += 1

    st.info(
        "**Partial Section** calibrates only the subbasins between two points in your "
        "watershed. Select an **end subbasin** (observation/gauge location) and a "
        "**start subbasin** (upstream boundary). Only the subbasins in that section "
        "will have their parameters optimized; subbasins upstream of the start point "
        "are locked at their current values."
    )

    # End subbasin (observation location)
    ps_end_sub = st.number_input(
        "End subbasin (observation location)",
        min_value=1,
        value=st.session_state.get("reach_id", 1),
        key="ps_end_sub_input",
        help="The subbasin number where the gauge is located (downstream end of the section)",
    )

    # Detect upstream subbasins for the end point
    if st.button("Detect upstream subbasins for end point", key="ps_detect_upstream"):
        try:
            from swat_modern.io.parsers.fig_parser import (
                find_qswat_shapes_dir, get_gis_upstream_subbasins,
                _has_river_shapefile, FigFileParser,
            )
            _proj = st.session_state.project_path

            # Priority: fig.fig > GIS shapefile
            _fig_path = Path(_proj) / "fig.fig"
            if _fig_path.exists():
                _parser = FigFileParser(_fig_path)
                _parser.parse()
                _detected_ups = _parser.get_upstream_subbasins_by_subbasin(ps_end_sub)
                if _detected_ups:
                    st.session_state.ps_upstream_subs = sorted(_detected_ups)
                    st.success(
                        f"fig.fig topology: **{len(_detected_ups)}** subbasins "
                        f"upstream of subbasin {ps_end_sub}: {sorted(_detected_ups)}"
                    )
                else:
                    # fig.fig gave empty set — fall back to GIS
                    _qswat_dir = st.session_state.get("qswat_shapes_input", "")
                    _shapes = (
                        Path(_qswat_dir) if _qswat_dir
                        else find_qswat_shapes_dir(Path(_proj))
                    )
                    if _shapes and _has_river_shapefile(_shapes):
                        _detected_ups = get_gis_upstream_subbasins(_shapes, ps_end_sub)
                        st.session_state.ps_upstream_subs = sorted(_detected_ups)
                        st.warning(
                            f"GIS fallback: **{len(_detected_ups)}** subbasins "
                            f"upstream of subbasin {ps_end_sub}: {sorted(_detected_ups)}"
                        )
                    else:
                        st.warning("fig.fig returned no upstream subbasins and no GIS shapefile found.")
            else:
                # No fig.fig — try GIS
                _qswat_dir = st.session_state.get("qswat_shapes_input", "")
                _shapes = (
                    Path(_qswat_dir) if _qswat_dir
                    else find_qswat_shapes_dir(Path(_proj))
                )
                if _shapes and _has_river_shapefile(_shapes):
                    _detected_ups = get_gis_upstream_subbasins(_shapes, ps_end_sub)
                    st.session_state.ps_upstream_subs = sorted(_detected_ups)
                    st.warning(
                        f"GIS topology: **{len(_detected_ups)}** subbasins "
                        f"upstream of subbasin {ps_end_sub}: {sorted(_detected_ups)}"
                    )
                else:
                    st.error("No fig.fig or river shapefile found.")
        except Exception as _e:
            st.error(f"Upstream detection failed: {_e}")

    # Start subbasin selectbox (only if upstream subs detected)
    _ps_upstream_list = st.session_state.get("ps_upstream_subs", [])
    if _ps_upstream_list:
        ps_start_sub = st.selectbox(
            "Start subbasin (upstream boundary)",
            options=_ps_upstream_list,
            key="ps_start_sub_select",
            help=(
                "The upstream boundary of the section. Subbasins upstream of this "
                "point will have their parameters locked. The start subbasin itself "
                "is included in the calibrated section."
            ),
        )

        # Compute section preview
        if ps_start_sub is not None and ps_end_sub is not None:
            try:
                from swat_modern.io.parsers.fig_parser import (
                    find_qswat_shapes_dir, get_section_subbasins,
                )
                _proj = st.session_state.project_path
                _qswat_dir = st.session_state.get("qswat_shapes_input", "")
                _shapes = (
                    Path(_qswat_dir) if _qswat_dir
                    else find_qswat_shapes_dir(Path(_proj))
                )
                _fig_path = Path(_proj) / "fig.fig"
                section_subs, locked_subs = get_section_subbasins(
                    ps_start_sub, ps_end_sub,
                    fig_path=_fig_path, shapes_dir=_shapes,
                )
                st.session_state.ps_section_subs = sorted(section_subs)
                st.session_state.ps_locked_subs = sorted(locked_subs)
                st.success(
                    f"**Section**: {len(section_subs)} subbasins to calibrate: "
                    f"{sorted(section_subs)}"
                )
                if locked_subs:
                    st.caption(
                        f"Locked (upstream): {len(locked_subs)} subbasins: "
                        f"{sorted(locked_subs)}"
                    )
            except Exception as _e:
                st.error(f"Could not compute section: {_e}")
    else:
        st.caption(
            "Click **Detect upstream subbasins** above to populate the start "
            "subbasin choices."
        )

    # Observation data upload for partial section
    st.markdown("---")
    st.markdown("**Observation Data (at end subbasin)**")

    if _is_wq_variable:
        ps_observed = _wq_observation_ui(
            output_variable=cal_output_variable,
            reach_id=ps_end_sub or 1,
            key_prefix="ps_wq",
        )
        if ps_observed is None and "wq_load_data" in st.session_state:
            _obs_raw = st.session_state.wq_load_data
            if isinstance(_obs_raw, pd.DataFrame) and "observed" in _obs_raw.columns:
                ps_observed = _obs_raw
                st.caption("Using WQ load data from session (previously computed).")
    else:
        # Show pre-loaded data from the Observation Data page if available
        _ps_has_page4 = "observed_data" in st.session_state
        if _ps_has_page4:
            _p4_raw = st.session_state.observed_data
            _p4_n = len(_p4_raw.dropna()) if hasattr(_p4_raw, "dropna") else len(_p4_raw)
            _p4_units = st.session_state.get("obs_units", "")
            try:
                _p4_range = f"{_p4_raw.index.min():%Y-%m-%d} to {_p4_raw.index.max():%Y-%m-%d}"
            except Exception:
                _p4_range = ""
            st.success(
                f"**{_p4_n}** observations loaded from the **Observation Data** page"
                + (f" ({_p4_range})" if _p4_range else "")
                + (f", units: {_p4_units}" if _p4_units else "")
                + "."
            )

        _ps_obs_file = st.file_uploader(
            "Upload a different observation file" if _ps_has_page4 else "Streamflow observation file",
            type=["csv", "xlsx", "xls", "txt", "tsv"],
            key="ps_obs_file",
            help="CSV, Excel, or text file with date and streamflow columns (auto-detected)."
                 + (" Leave empty to use the data loaded on the Observation Data page." if _ps_has_page4 else ""),
        )

        if _ps_obs_file is not None:
            try:
                ps_observed = _load_uploaded_observation(_ps_obs_file)
                if ps_observed.empty:
                    st.error("Could not parse uploaded file.")
                    ps_observed = None
                else:
                    _ps_numeric_cols = ObservationLoader.detect_value_columns(ps_observed)
                    if len(_ps_numeric_cols) == 0:
                        st.error("No numeric value columns detected in the uploaded file.")
                        ps_observed = None
                    else:
                        if len(_ps_numeric_cols) > 1:
                            _flow_names = {"flow", "streamflow", "discharge", "q", "observed", "value"}
                            _priority = [c for c in _ps_numeric_cols if c.lower().strip() in _flow_names]
                            _rest = [c for c in _ps_numeric_cols if c not in _priority]
                            _ordered = _priority + _rest
                            _ps_chosen_col = st.selectbox(
                                "Calibration column",
                                options=_ordered,
                                key="ps_value_col",
                                help="Select the column containing the values to calibrate against",
                            )
                        else:
                            _ps_chosen_col = _ps_numeric_cols[0]
                        _ps_date_col = ObservationLoader.detect_date_column(ps_observed)
                        _ps_keep = [c for c in [_ps_date_col, _ps_chosen_col] if c and c in ps_observed.columns]
                        ps_observed = ps_observed[_ps_keep].rename(
                            columns={_ps_chosen_col: "observed"} if _ps_chosen_col != "observed" else {}
                        )
                        st.caption(
                            f"Loaded {len(ps_observed)} observations "
                            f"(columns: {', '.join(ps_observed.columns[:5])})"
                        )
            except Exception as _e:
                st.error(f"Error loading observation data: {_e}")
        elif "observed_data" in st.session_state:
            _obs_raw = st.session_state.observed_data
            if isinstance(_obs_raw, pd.Series):
                if isinstance(_obs_raw.index, pd.DatetimeIndex):
                    ps_observed = pd.DataFrame({
                        "date": _obs_raw.index, "observed": _obs_raw.values,
                    }).reset_index(drop=True)
                else:
                    ps_observed = _obs_raw.reset_index()
                    ps_observed.columns = ["date", "observed"]
            elif isinstance(_obs_raw, pd.DataFrame):
                ps_observed = _obs_raw
            else:
                ps_observed = _obs_raw
        else:
            st.warning(
                "No observation data available. Load data on the **Observation Data** page "
                "or upload a file above."
            )

    # Calibration period selection for partial section
    if ps_observed is not None and not ps_observed.empty:
        ps_observed = _calibration_period_picker(ps_observed, key_prefix="ps")

# -------------------------------------------------------------------------
# Single-site observation data (upload directly on this page)
# -------------------------------------------------------------------------
single_site_observed = None
single_reach = None

# Wire partial_section values into single_reach / single_site_observed
# for downstream compatibility
if calibration_mode == "partial_section":
    single_reach = ps_end_sub
    single_site_observed = ps_observed

if calibration_mode == "single":
    st.markdown("---")
    st.header(f"{_section}. Observation Data")
    _section += 1

    single_reach = st.number_input(
        "Subbasin ID",
        min_value=1,
        value=st.session_state.get("reach_id", 1),
        key="single_reach_id",
        help="The subbasin number where the gauge is located (auto-translated to reach ID internally)",
    )

    if _is_wq_variable:
        # ---- WQ path: upload concentration file + pair with flow ----
        single_site_observed = _wq_observation_ui(
            output_variable=cal_output_variable,
            reach_id=single_reach,
            key_prefix="single_wq",
        )
        # Fallback: check if LOAD data (not raw concentrations) was stored
        # in session state from the Observation Data page or a previous render.
        # IMPORTANT: For WQ variables, the fallback must contain load data
        # (kg/day or tons/day), NOT raw concentrations (mg/L). Using raw
        # concentrations would cause massive unit mismatch vs SWAT loads.
        if single_site_observed is None and "wq_load_data" in st.session_state:
            _obs_raw = st.session_state.wq_load_data
            if isinstance(_obs_raw, pd.DataFrame) and "observed" in _obs_raw.columns:
                single_site_observed = _obs_raw
                st.caption("Using WQ load data from session (previously computed).")
        if single_site_observed is None and "observed_data" in st.session_state:
            _obs_raw = st.session_state.observed_data
            # Sanity check: WQ load values should typically be > 1 kg/day.
            # Concentrations are typically 0.01-50 mg/L. If median < 1,
            # this is likely raw concentration data \u2014 warn and skip.
            _obs_vals = None
            if isinstance(_obs_raw, pd.Series):
                _obs_vals = _obs_raw.dropna()
            elif isinstance(_obs_raw, pd.DataFrame):
                for _cand in ["observed", "value"]:
                    if _cand in _obs_raw.columns:
                        _obs_vals = _obs_raw[_cand].dropna()
                        break
            if _obs_vals is not None and len(_obs_vals) > 0:
                _median_val = float(_obs_vals.median())
                if _median_val < 1.0:
                    st.warning(
                        f"Session data appears to contain raw concentrations "
                        f"(median={_median_val:.3f}), not loads (kg/day). "
                        f"Please upload the WQ file and flow file above to "
                        f"compute loads for calibration."
                    )
                else:
                    if isinstance(_obs_raw, pd.Series):
                        if isinstance(_obs_raw.index, pd.DatetimeIndex):
                            single_site_observed = pd.DataFrame({
                                "date": _obs_raw.index,
                                "observed": _obs_raw.values,
                            }).reset_index(drop=True)
                        else:
                            single_site_observed = _obs_raw.reset_index()
                            single_site_observed.columns = ["date", "observed"]
                    elif isinstance(_obs_raw, pd.DataFrame):
                        single_site_observed = _obs_raw
                    else:
                        single_site_observed = _obs_raw
                    st.caption("Using WQ load data from the **Observation Data** page.")
    else:
        # ---- Standard streamflow path ----
        # Show pre-loaded data from the Observation Data page if available
        _has_page4_obs = "observed_data" in st.session_state
        if _has_page4_obs:
            _p4_raw = st.session_state.observed_data
            _p4_n = len(_p4_raw.dropna()) if hasattr(_p4_raw, "dropna") else len(_p4_raw)
            _p4_units = st.session_state.get("obs_units", "")
            try:
                _p4_range = f"{_p4_raw.index.min():%Y-%m-%d} to {_p4_raw.index.max():%Y-%m-%d}"
            except Exception:
                _p4_range = ""
            st.success(
                f"**{_p4_n}** observations loaded from the **Observation Data** page"
                + (f" ({_p4_range})" if _p4_range else "")
                + (f", units: {_p4_units}" if _p4_units else "")
                + "."
            )

        single_obs_file = st.file_uploader(
            "Upload a different observation file" if _has_page4_obs else "Streamflow observation file",
            type=["csv", "xlsx", "xls", "txt", "tsv"],
            key="single_obs_file",
            help="CSV, Excel, or text file with date and streamflow columns (auto-detected)."
                 + (" Leave empty to use the data loaded on the Observation Data page." if _has_page4_obs else ""),
        )

        if single_obs_file is not None:
            try:
                single_site_observed = _load_uploaded_observation(single_obs_file)
                if single_site_observed.empty:
                    st.error("Could not parse uploaded file.")
                    single_site_observed = None
                else:
                    numeric_cols = ObservationLoader.detect_value_columns(single_site_observed)
                    if len(numeric_cols) == 0:
                        st.error("No numeric value columns detected in the uploaded file.")
                        single_site_observed = None
                    else:
                        if len(numeric_cols) > 1:
                            _flow_names = {"flow", "streamflow", "discharge", "q", "observed", "value"}
                            _priority = [c for c in numeric_cols if c.lower().strip() in _flow_names]
                            _rest = [c for c in numeric_cols if c not in _priority]
                            _ordered = _priority + _rest
                            chosen_col = st.selectbox(
                                "Calibration column",
                                options=_ordered,
                                key="single_value_col",
                                help="Select the column containing the values to calibrate against",
                            )
                        else:
                            chosen_col = numeric_cols[0]
                        date_col = ObservationLoader.detect_date_column(single_site_observed)
                        keep = [c for c in [date_col, chosen_col] if c and c in single_site_observed.columns]
                        _renames = {}
                        if date_col and date_col != "date":
                            _renames[date_col] = "date"
                        if chosen_col != "observed":
                            _renames[chosen_col] = "observed"
                        single_site_observed = single_site_observed[keep].rename(
                            columns=_renames
                        )
                        _obs_vals = single_site_observed["observed"]
                        if (
                            len(_obs_vals) > 50
                            and _obs_vals.is_monotonic_increasing
                            and _obs_vals.iloc[0] < 5
                            and _obs_vals.iloc[-1] > len(_obs_vals) * 0.8
                        ):
                            st.warning(
                                f"The selected column **{chosen_col}** appears to contain "
                                f"row indices (values {_obs_vals.iloc[0]:.0f} to "
                                f"{_obs_vals.iloc[-1]:.0f}), not observation data. "
                                f"Please select a different column."
                            )
                        st.caption(
                            f"Loaded {len(single_site_observed)} observations "
                            f"(columns: {', '.join(single_site_observed.columns[:5])})"
                        )
            except Exception as e:
                st.error(f"Error loading observation data: {e}")
        elif "observed_data" in st.session_state:
            _obs_raw = st.session_state.observed_data
            if isinstance(_obs_raw, pd.Series):
                if isinstance(_obs_raw.index, pd.DatetimeIndex):
                    single_site_observed = pd.DataFrame({
                        "date": _obs_raw.index,
                        "observed": _obs_raw.values,
                    }).reset_index(drop=True)
                else:
                    single_site_observed = _obs_raw.reset_index()
                    single_site_observed.columns = ["date", "observed"]
            elif isinstance(_obs_raw, pd.DataFrame):
                single_site_observed = _obs_raw
            else:
                single_site_observed = _obs_raw
        else:
            st.warning(
                "No observation data available. Load data on the **Observation Data** page "
                "or upload a file above."
            )

    # --- Calibration period selection for single-site ---
    if single_site_observed is not None and not single_site_observed.empty:
        if st.session_state.get("_wq_deferred_flow"):
            # When using SWAT simulated streamflow for WQ load computation,
            # the effective calibration period is determined by the
            # Simulation Period setting below (IYR/NBYR + warmup).
            # Showing a separate period picker here would be misleading
            # because _resolve_deferred_wq replaces the observation data
            # entirely at calibration time.
            st.info(
                "The calibration period for WQ loads with simulated streamflow "
                "is controlled by the **Simulation Period** and **Warmup Years** "
                "settings below."
            )
        else:
            single_site_observed = _calibration_period_picker(
                single_site_observed, key_prefix="single"
            )

# -------------------------------------------------------------------------
# SWAT Executable path
# -------------------------------------------------------------------------
st.markdown("---")
st.header(f"{_section}. SWAT Executable")
_section += 1

import os as _os
default_exe = st.session_state.get("swat_executable", _os.environ.get("SWAT_EXE", ""))

# Apply browsed exe path if user selected one via the file dialog
_browsed_cal_exe = st.session_state.get("_browsed_cal_exe_path", "")

col_exe, col_exe_browse = st.columns([4, 1])
with col_exe:
    swat_executable = st.text_input(
        "Path to SWAT executable (.exe)",
        value=_browsed_cal_exe or default_exe,
        placeholder="e.g. C:/SWAT/swat2012.exe",
        help=(
            "Full path to the SWAT executable. If left blank, the tool will search "
            "common locations inside the project directory and the SWAT_EXE environment variable."
        ),
    )
with col_exe_browse:
    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("Browse...", key="browse_cal_exe", width="stretch"):
        selected_exe = browse_file(
            title="Select SWAT Executable",
            filetypes=[("Executable files", "*.exe"), ("All files", "*.*")],
        )
        if selected_exe:
            st.session_state._browsed_cal_exe_path = selected_exe
            st.rerun()

if swat_executable:
    swat_executable = swat_executable.strip()
    st.session_state.swat_executable = swat_executable
    # Clear the browsed path once applied
    st.session_state.pop("_browsed_cal_exe_path", None)

# -------------------------------------------------------------------------
# Algorithm and settings
# -------------------------------------------------------------------------
st.markdown("---")
st.header(f"{_section}. Calibration Settings")
_section += 1

settings_col1, settings_col2, settings_col3 = st.columns(3)

with settings_col1:
    algorithm = st.selectbox(
        "Optimization Algorithm",
        options=[
            ("Diagnostic-Guided (5-50 runs)", "diagnostic"),
            ("SCE-UA (Shuffled Complex Evolution)", "sceua"),
            ("DREAM (Bayesian)", "dream"),
            ("Monte Carlo", "mc"),
            ("Latin Hypercube", "lhs"),
        ],
        format_func=lambda x: x[0],
        help="SCE-UA is recommended for most calibration tasks. "
             "Diagnostic-Guided analyzes hydrograph deficiencies to adjust "
             "parameters intelligently in very few runs. "
             "Enable parallel processing to run multiple diagnostic "
             "calibrators as an ensemble."
    )

    _is_diagnostic = algorithm[1] == "diagnostic"

    if _is_diagnostic:
        n_iterations = st.slider(
            "Max SWAT Runs",
            min_value=5,
            max_value=50,
            value=15,
            step=1,
            help="Maximum number of SWAT runs. Typically converges in 5-15 runs."
        )
        _diag_target_col1, _diag_target_col2 = st.columns(2)
        with _diag_target_col1:
            kge_target = st.slider(
                "KGE Target",
                min_value=0.30,
                max_value=0.95,
                value=0.70,
                step=0.05,
                help=(
                    "Stop calibration when KGE reaches this target. "
                    "0.50 = satisfactory, 0.70 = good, 0.80+ = very good."
                ),
            )
        with _diag_target_col2:
            pbias_target = st.slider(
                "|PBIAS| Target (%)",
                min_value=5.0,
                max_value=25.0,
                value=10.0,
                step=1.0,
                help=(
                    "Stop when absolute PBIAS is below this. "
                    "10% = good, 15% = satisfactory, 25% = unsatisfactory."
                ),
            )
        # n_ensemble_workers is set in the Optimization Settings section
        # based on whether parallel processing is enabled.
        n_ensemble_workers = 1  # default; overridden below if parallel enabled
        st.info(
            "Diagnostic-Guided calibration analyzes sim-vs-obs hydrographs "
            "(volume, baseflow, peaks, timing) and adjusts parameters in "
            "targeted phases. Does **not** use random sampling. "
            "Enable **parallel processing** below to run as an ensemble."
        )
    else:
        n_ensemble_workers = 1
        kge_target = 0.70
        pbias_target = 10.0
        iter_label = "Iterations per step" if calibration_mode == "sequential" else "Number of Iterations"
        # DREAM requires nChains >= 7 (2*delta+1) for the chains to even
        # initialize, and needs many more iterations beyond the burn-in to
        # produce useful posterior samples. Enforce a higher floor and default
        # for DREAM so users can't accidentally pick a value that fails or
        # converges to nothing.
        _is_dream = algorithm[1] == "dream"
        if _is_dream:
            _iter_min = 100
            _iter_default = 2000
            _iter_help = (
                "DREAM uses 7 MCMC chains with burn-in. Minimum 100 iterations "
                "is required for the sampler to initialize; 1000-5000+ is "
                "recommended for meaningful posterior sampling."
            )
        else:
            _iter_min = 2
            _iter_default = 1000
            _iter_help = "More iterations = better results but longer runtime"
        n_iterations = st.slider(
            iter_label,
            min_value=_iter_min,
            max_value=50000,
            value=_iter_default,
            step=1,
            help=_iter_help,
        )

with settings_col2:
    if not _is_diagnostic:
        objective = st.selectbox(
            "Objective Function",
            options=[
                ("NSE (Nash-Sutcliffe)", "nse"),
                ("KGE (Kling-Gupta)", "kge"),
                ("Log-NSE (for low flows)", "log_nse"),
                ("PBIAS (Percent Bias)", "pbias"),
            ],
            format_func=lambda x: x[0],
            help="NSE is the most common choice for streamflow. "
                 "PBIAS measures systematic over/under-prediction (target: 0%)."
        )
    else:
        # Diagnostic mode uses KGE + PBIAS internally; targets are set via
        # the sliders in the algorithm column.
        objective = ("KGE (Kling-Gupta)", "kge")

    # Derive max warmup from the model's simulation length (NBYR - 1)
    _max_warmup = 20  # generous default
    if "project_path" in st.session_state:
        try:
            from swat_modern.core.config import SWATConfig as _WCfg
            _wcfg = _WCfg(Path(st.session_state.project_path))
            _nbyr = _wcfg.period.end_year - _wcfg.period.start_year + 1
            _max_warmup = max(_nbyr - 1, 1)
        except Exception:
            pass
    warmup_years = st.number_input(
        "Warmup Years",
        min_value=0,
        max_value=_max_warmup,
        value=min(1, _max_warmup),
        help=f"Years to exclude from calibration statistics (max {_max_warmup} based on simulation length)"
    )

with settings_col3:
    # Auto-detect observation frequency for default
    _detected_timestep = "Daily"
    _obs_for_detect = None
    if calibration_mode in ("single", "partial_section") and single_site_observed is not None:
        _obs_for_detect = single_site_observed
    elif calibration_mode in ("simultaneous", "sequential") and calibration_sites:
        _obs_for_detect = calibration_sites[0].get("observed")
    if _obs_for_detect is not None and isinstance(_obs_for_detect, pd.DataFrame):
        _dcol = ObservationLoader.detect_date_column(_obs_for_detect)
        if _dcol and _dcol in _obs_for_detect.columns:
            _dates = pd.to_datetime(_obs_for_detect[_dcol], errors="coerce").dropna().sort_values()
            if len(_dates) > 2:
                _med_days = _dates.diff().dt.days.median()
                if _med_days is not None and _med_days > 300:
                    _detected_timestep = "Yearly"
                elif _med_days is not None and _med_days > 20:
                    _detected_timestep = "Monthly"

    _timestep_options = ["Daily", "Monthly", "Yearly"]
    _timestep_index = _timestep_options.index(_detected_timestep) if _detected_timestep in _timestep_options else 0
    calibration_timestep = st.selectbox(
        "Calibration Timestep",
        options=_timestep_options,
        index=_timestep_index,
        help=(
            "Must match the observation data frequency. "
            "Daily (IPRINT=1), Monthly (IPRINT=0), Yearly (IPRINT=2). "
            "Auto-detected from uploaded observation data."
        ),
    )
    if _detected_timestep != calibration_timestep:
        st.caption(
            f"Auto-detected: **{_detected_timestep}** from observation data"
        )

    # Map to SWAT IPRINT value
    _timestep_to_iprint = {"Daily": 1, "Monthly": 0, "Yearly": 2}
    calibration_print_code = _timestep_to_iprint[calibration_timestep]

# -------------------------------------------------------------------------
# Simulation Period
# -------------------------------------------------------------------------
_custom_sim_period = None  # (start_year, end_year) or None

with st.expander("SWAT Simulation Years (IYR / NBYR)"):
    from swat_modern.core.config import SWATConfig as _SWATConfig

    try:
        _cfg = _SWATConfig(Path(st.session_state.project_path))
        _cur_start = _cfg.period.start_year
        _cur_end = _cfg.period.end_year
        _weather = _cfg.get_weather_data_period()

        if _weather:
            _wx_start, _wx_end = _weather
            st.caption(
                f"Current simulation: **{_cur_start}--{_cur_end}** "
                f"({_cur_end - _cur_start + 1} years)  |  "
                f"Available weather data: **{_wx_start}--{_wx_end}** "
                f"({_wx_end - _wx_start + 1} years)"
            )
        else:
            _wx_start, _wx_end = _cur_start, _cur_end
            st.caption(
                f"Current simulation: **{_cur_start}--{_cur_end}** "
                f"({_cur_end - _cur_start + 1} years)  |  "
                f"Weather data period: could not detect (.pcp files)"
            )

        _use_custom_sim = st.checkbox(
            "Override SWAT simulation years (IYR / NBYR)",
            value=False,
            key="use_custom_sim_period",
            help=(
                "Change the start year and duration in the calibration "
                "working copy of file.cio. Controls how many years SWAT "
                "actually runs. The model must have weather data covering "
                "the selected range."
            ),
        )

        if _use_custom_sim:
            _sp_col1, _sp_col2 = st.columns(2)
            with _sp_col1:
                _sim_start = st.number_input(
                    "Start year (IYR)",
                    min_value=_wx_start,
                    max_value=_wx_end - 1,
                    value=_cur_start,
                    key="custom_sim_start",
                )
            with _sp_col2:
                _sim_end = st.number_input(
                    "End year",
                    min_value=_sim_start + 1,
                    max_value=_wx_end,
                    value=min(_cur_end, _wx_end),
                    key="custom_sim_end",
                )

            if _sim_start != _cur_start or _sim_end != _cur_end:
                _custom_sim_period = (_sim_start, _sim_end)
                st.info(
                    f"Calibration will simulate **{_sim_start}--{_sim_end}** "
                    f"({_sim_end - _sim_start + 1} years, "
                    f"NBYR={_sim_end - _sim_start + 1})"
                )
            else:
                st.caption("Same as current simulation period -- no change needed.")

    except Exception as _e:
        st.warning(f"Could not read project configuration: {_e}")

    # Warn if both observation window AND simulation years are customized
    _obs_custom_keys = [
        k for k in st.session_state
        if k.endswith("_use_custom_period") and st.session_state[k]
    ]
    if _custom_sim_period is not None and _obs_custom_keys:
        st.warning(
            "Both the observation comparison window and SWAT simulation years "
            "are customized. Only dates that fall within **both** ranges "
            "(after warmup) will affect calibration statistics."
        )

# -------------------------------------------------------------------------
# Optimization Settings
# -------------------------------------------------------------------------
with st.expander("Optimization Settings (Speed)"):
    opt_col1, opt_col2 = st.columns(2)

    with opt_col1:
        use_partial_basin = st.checkbox(
            "Enable partial-basin simulation",
            value=True,
            help=(
                "When the calibration target is not at the watershed outlet, "
                "only simulate upstream subbasins. This can significantly "
                "reduce runtime by skipping downstream computations."
            ),
        )

        use_parallel = st.checkbox(
            "Enable parallel processing",
            value=False,
            help=(
                "Run multiple SWAT simulations in parallel using available CPU cores. "
                "May speed up calibration 2-4x on multi-core machines. "
                "GPU acceleration is not available for SWAT2012 (compiled Fortran)."
            ),
        )

        if use_parallel:
            import os as _os_cpu
            _n_cpus = _os_cpu.cpu_count() or 1
            _half_cpus = max(2, _n_cpus // 2)
            n_cores = st.number_input(
                "CPU cores to use",
                min_value=2,
                max_value=_n_cpus,
                value=2,
                help=f"Detected {_n_cpus} cores. Using fewer keeps your machine responsive.",
            )
            if n_cores > _half_cpus:
                st.warning(
                    f"Using more than half of available cores ({_half_cpus}/{_n_cpus}) "
                    "may make your machine unresponsive."
                )
            if _is_diagnostic:
                n_ensemble_workers = n_cores
                st.info(
                    "**Ensemble mode**: runs multiple independent diagnostic "
                    "calibrators in parallel, each with different damping and "
                    "phase-order settings. Same wall-clock time as a single "
                    "run, but better solution quality (picks best of N)."
                )
        else:
            n_cores = 1

    with opt_col2:
        st.markdown("**SWAT2012 Subprocess Info**")
        st.caption(
            "SWAT2012 cannot selectively disable sediment, nutrient, or bacteria "
            "calculations at runtime (compiled Fortran). Partial-basin simulation "
            "and parallel processing are the primary runtime optimizations available."
        )

# -------------------------------------------------------------------------
# Advanced: QSWAT / Upstream Subbasin Settings
# -------------------------------------------------------------------------
with st.expander("Advanced: Upstream Subbasin Detection"):
    st.markdown(
        "By default, upstream subbasins are detected from fig.fig routing "
        "if available, falling back to GIS river shapefile (rivs1.shp or riv1.shp). "
        "You can specify the QSWAT shapes path or manually override upstream subbasins."
    )

    _adv_col1, _adv_col2 = st.columns(2)
    with _adv_col1:
        _default_shapes = st.session_state.get("qswat_shapes_input", "")
        qswat_shapes_dir = st.text_input(
            "QSWAT Shapes directory",
            value=_default_shapes,
            placeholder="e.g. C:/MyProject/Watershed/Shapes",
            help=(
                "Path to the Watershed/Shapes/ directory containing "
                "rivs1.shp or riv1.shp. "
                "Auto-detected from the project directory if left blank."
            ),
            key="qswat_shapes_input",
        )
        if qswat_shapes_dir:
            qswat_shapes_dir = qswat_shapes_dir.strip()
            _shapes_path = Path(qswat_shapes_dir)
            from swat_modern.io.parsers.fig_parser import (
                _has_river_shapefile as _has_riv_shp,
            )
            if _has_riv_shp(_shapes_path):
                st.caption("River shapefile found.")
            else:
                st.warning(
                    "No river shapefile (rivs1.shp or riv1.shp) found "
                    "in the specified directory."
                )

    with _adv_col2:
        upstream_override_str = st.text_input(
            "Override upstream subbasins (comma-separated)",
            value="",
            placeholder="e.g. 1,2,4,5,6,7,8,9,10,11,12,13",
            help=(
                "Leave blank for auto-detection from fig.fig/GIS. "
                "If specified, these subbasin IDs will be used as the "
                "upstream set for single-site calibration."
            ),
            key="upstream_override_input",
        )

    # Detect button
    if st.button("Detect upstream subbasins"):
        try:
            from swat_modern.io.parsers.fig_parser import (
                find_qswat_shapes_dir, get_gis_upstream_subbasins,
                _has_river_shapefile, FigFileParser,
            )
            _proj = st.session_state.project_path

            _target_sub = (
                single_reach if calibration_mode in ("single", "partial_section")
                else (calibration_sites[0]["reach_id"] if calibration_sites else 1)
            )

            # Priority: fig.fig > GIS shapefile
            _fig_path = Path(_proj) / "fig.fig"
            if _fig_path.exists():
                _parser = FigFileParser(_fig_path)
                _parser.parse()
                _detected = _parser.get_upstream_subbasins_by_subbasin(_target_sub)
                if _detected:
                    st.success(
                        f"fig.fig topology: **{len(_detected)}** subbasins "
                        f"upstream of subbasin {_target_sub}: {sorted(_detected)}"
                    )
                else:
                    # fig.fig gave empty set — fall back to GIS
                    _shapes = (
                        Path(qswat_shapes_dir) if qswat_shapes_dir
                        else find_qswat_shapes_dir(Path(_proj))
                    )
                    if _shapes and _has_river_shapefile(_shapes):
                        _detected = get_gis_upstream_subbasins(_shapes, _target_sub)
                        st.warning(
                            f"GIS fallback: **{len(_detected)}** subbasins "
                            f"upstream of subbasin {_target_sub}: {sorted(_detected)}"
                        )
                    else:
                        st.warning("fig.fig returned no upstream subbasins and no GIS shapefile found.")
            else:
                # No fig.fig — try GIS
                _shapes = (
                    Path(qswat_shapes_dir) if qswat_shapes_dir
                    else find_qswat_shapes_dir(Path(_proj))
                )
                if _shapes and _has_river_shapefile(_shapes):
                    _detected = get_gis_upstream_subbasins(_shapes, _target_sub)
                    st.warning(
                        f"GIS topology: **{len(_detected)}** subbasins "
                        f"upstream of subbasin {_target_sub}: {sorted(_detected)}"
                    )
                else:
                    st.error("No fig.fig or river shapefile found.")
        except Exception as e:
            st.error(f"Detection failed: {e}")

# Parse upstream override into a list if provided
_parsed_upstream_override = None
if upstream_override_str and upstream_override_str.strip():
    try:
        _parsed_upstream_override = [
            int(x.strip()) for x in upstream_override_str.split(",") if x.strip()
        ]
    except ValueError:
        st.warning("Invalid upstream subbasin override. Use comma-separated integers.")

# Estimated runtime
if calibration_mode == "sequential" and len(calibration_sites) >= 2:
    n_steps = len(calibration_sites)
    estimated_time = n_iterations * 0.5 * n_steps
    step_note = f" ({n_steps} steps x {n_iterations} iterations)"
else:
    estimated_time = n_iterations * 0.5
    step_note = ""

if estimated_time < 60:
    time_str = f"~{int(estimated_time)} seconds"
elif estimated_time < 3600:
    time_str = f"~{int(estimated_time/60)} minutes"
else:
    time_str = f"~{estimated_time/3600:.1f} hours"

st.caption(f"Estimated runtime: {time_str}{step_note}")

# -------------------------------------------------------------------------
# Sensitivity Analysis (optional, before calibration)
# -------------------------------------------------------------------------
st.markdown("---")
st.header(f"{_section}. Sensitivity Analysis (Optional)")
_section += 1

st.markdown(
    "Sensitivity analysis identifies which parameters most influence model output. "
    "**When to use it:**\n"
    "- You have many candidate parameters (>10) and want to focus on the most influential ones\n"
    "- You're unsure which parameters drive model behavior at your site\n"
    "- You want to reduce calibration time by excluding insensitive parameters\n\n"
    "*You can skip this step if you already know which parameters to calibrate "
    "(e.g., from literature or prior experience).*"
)

# Reconnect to a running/completed SA after browser refresh.
# The daemon thread survives but session_state is reset.
if "_sensitivity_state" not in st.session_state:
    _reconnected_sa = get_active_sensitivity_state()
    if _reconnected_sa is not None and _reconnected_sa.status in ("running", "completed"):
        st.session_state["_sensitivity_state"] = _reconnected_sa

_sa_state = st.session_state.get("_sensitivity_state")
_sa_running = _sa_state is not None and _sa_state.status == "running"

with st.expander("Sensitivity Analysis Settings", expanded=False):
    _sa_col1, _sa_col2 = st.columns(2)
    with _sa_col1:
        sa_method = st.selectbox(
            "Method",
            options=["fast", "sobol"],
            format_func=lambda x: {"fast": "FAST (Recommended)", "sobol": "Sobol (Approximate)"}[x],
            key="sa_method",
            help="FAST uses Fourier Amplitude Sensitivity Test. Sobol uses variance-based decomposition.",
        )
    with _sa_col2:
        # FAST requires minimum 65 samples/param (Fourier decomposition
        # needs interference parameter m >= 1).  Sobol has no minimum.
        if sa_method == "fast":
            _sa_slider_min = 65
            _sa_slider_default = max(65, st.session_state.get("sa_n_samples", 65))
        else:
            _sa_slider_min = 10
            _sa_slider_default = st.session_state.get("sa_n_samples", 50)
        sa_n_samples = st.slider(
            "Samples per parameter",
            min_value=_sa_slider_min, max_value=500,
            value=min(max(_sa_slider_default, _sa_slider_min), 500),
            step=5 if sa_method == "sobol" else 10,
            key="sa_n_samples",
            help="More samples = more accurate but slower. Total runs = samples x n_params. "
                 "50 samples is sufficient for parameter ranking; use 200+ for publication-quality indices."
                 + (" FAST requires minimum 65 samples/param." if sa_method == "fast" else ""),
        )

    if sa_method == "fast":
        st.info(
            "FAST requires a minimum of **65 samples per parameter** for valid "
            "Fourier decomposition. For a quicker screening analysis with fewer "
            "samples, switch to the **Sobol** method."
        )

    _sa_col3, _sa_col4 = st.columns(2)
    with _sa_col3:
        import multiprocessing as _mp_mod
        _cpu_count = _mp_mod.cpu_count()
        sa_parallel = st.checkbox(
            "Parallel processing",
            value=False,
            key="sa_parallel",
            help=f"Run SWAT simulations on multiple CPU cores simultaneously. "
                 f"Each worker gets its own copy of the project directory. "
                 f"Available cores: {_cpu_count}. Requires the 'pathos' package.",
        )
    with _sa_col4:
        if sa_parallel:
            sa_n_cores = st.slider(
                "CPU cores",
                min_value=2, max_value=_cpu_count, value=max(2, _cpu_count // 2), step=1,
                key="sa_n_cores",
                help="Number of parallel workers. Using half of available cores is a safe default.",
            )
        else:
            sa_n_cores = None

    _n_sa_params = max(len(selected_params), 1)
    _sa_total_runs = sa_n_samples * _n_sa_params
    _sa_time_hint = ""
    if sa_parallel and sa_n_cores and sa_n_cores > 1:
        _sa_time_hint = f" (~{sa_n_cores}x faster with parallel)"
    st.caption(
        f"Estimated total SWAT runs: **{_sa_total_runs:,}** "
        f"({_n_sa_params} params x {sa_n_samples} samples/param)"
        f"{_sa_time_hint}"
    )

# SA progress / results / start button
if _sa_running:
    @st.fragment(run_every=timedelta(seconds=3))
    def _show_sa_progress():
        _ss = st.session_state.get("_sensitivity_state")
        if _ss is None:
            return
        if _ss.status != "running":
            st.rerun(scope="app")
            return

        st.markdown(
            '<div style="padding: 0.75rem 1rem; background: linear-gradient(135deg, #e6510010, #f5711a15); '
            'border-left: 4px solid #e65100; border-radius: 0 8px 8px 0; margin-bottom: 1rem;">'
            '<strong>Sensitivity Analysis Running</strong><br>'
            '<span style="color: #666; font-size: 0.9em;">Running in the background \u2014 you can safely browse other tabs</span>'
            '</div>',
            unsafe_allow_html=True,
        )

        _sim_count = _ss.simulation_count
        _total = max(_ss.total_iterations, 1)
        _elapsed = time.time() - (_ss.start_time or time.time())
        _em, _es = divmod(int(_elapsed), 60)

        # Progress bar — true percentage
        _pct = min(int(100 * _sim_count / _total), 100)
        st.progress(_pct)
        st.caption(f"**{_pct}%** complete")

        # Live metrics
        _mc1, _mc2, _mc3, _mc4 = st.columns(4)
        with _mc1:
            st.metric("Simulations", f"{_sim_count:,} / {_total:,}")
        with _mc2:
            st.metric("Elapsed", f"{_em}m {_es}s" if _em else f"{int(_elapsed)}s")
        with _mc3:
            if _sim_count > 0:
                _avg = _elapsed / _sim_count
                _remaining = _avg * max(_total - _sim_count, 0)
                _rm, _rs = divmod(int(_remaining), 60)
                st.metric("ETA", f"{_rm}m {_rs}s" if _rm else f"{int(_remaining)}s")
            else:
                st.metric("ETA", "Calculating...")
        with _mc4:
            if _sim_count > 0 and _elapsed > 0:
                _speed = _sim_count / (_elapsed / 60)
                st.metric("Speed", f"{_speed:.1f}/min")
            else:
                st.metric("Speed", "\u2014")

        if st.button("Cancel Sensitivity Analysis", key="cancel_sa"):
            _ss.request_cancel()
            # Persist the cancel in session_state so it survives
            # auto-refresh cycles where the button returns False.
            st.session_state["_sa_cancel_requested"] = True
        elif st.session_state.get("_sa_cancel_requested"):
            # Re-apply cancel on every fragment rerun until the
            # background thread acknowledges it.
            _ss.request_cancel()
    _show_sa_progress()

elif _sa_state is not None and _sa_state.status == "completed" and _sa_state.result_sensitivity is not None:
    _sa_result_obj = _sa_state.result_sensitivity
    # SensitivityResult: unpack .sensitivity (dict/DataFrame) for visualization
    # and .best_parameters / .best_objective for display.
    if hasattr(_sa_result_obj, "sensitivity"):
        st.session_state["sensitivity_results"] = _sa_result_obj.sensitivity
        st.session_state["sa_best_params"] = _sa_result_obj.best_parameters
        st.session_state["sa_best_objective"] = _sa_result_obj.best_objective
        st.session_state["sa_runtime"] = getattr(_sa_result_obj, "runtime", None)
        st.session_state["sa_method_used"] = getattr(_sa_result_obj, "method", None)
        st.session_state["sa_n_evaluations"] = getattr(_sa_result_obj, "n_evaluations", None)
    else:
        # Fallback for legacy format (plain dict/DataFrame)
        st.session_state["sensitivity_results"] = _sa_result_obj
    st.session_state.pop("_sensitivity_state", None)
    st.session_state.pop("_sa_cancel_requested", None)
    clear_active_sensitivity_state()
    # Persist SA results to disk so they survive browser refresh
    from swat_modern.app.session_persistence import save_session
    save_session(st.session_state)

elif _sa_state is not None and _sa_state.status == "cancelled":
    st.warning("Sensitivity analysis was cancelled.")
    st.session_state.pop("_sa_cancel_requested", None)
    if st.button("Dismiss", key="dismiss_sa_cancel"):
        st.session_state.pop("_sensitivity_state", None)
        clear_active_sensitivity_state()
        st.rerun()

elif _sa_state is not None and _sa_state.status == "failed":
    st.error(f"Sensitivity analysis failed: {_sa_state.error_message}")
    st.session_state.pop("_sa_cancel_requested", None)
    if _sa_state.error_traceback:
        with st.expander("Error details"):
            st.code(_sa_state.error_traceback)
    if st.button("Dismiss SA Error", key="dismiss_sa"):
        st.session_state.pop("_sensitivity_state", None)
        clear_active_sensitivity_state()
        st.rerun()

# Show previous SA results if available
_sa_results = st.session_state.get("sensitivity_results")
if _sa_results is not None:
    import matplotlib.pyplot as plt
    from swat_modern.visualization.sensitivity import (
        plot_sensitivity_tornado,
        sensitivity_ranking_table,
        get_suggested_parameters,
    )

    # Summary metrics: runtime, method, evaluations
    _sa_rt = st.session_state.get("sa_runtime")
    _sa_meth = st.session_state.get("sa_method_used")
    _sa_nevals = st.session_state.get("sa_n_evaluations")
    _sa_summary_parts = ["Sensitivity analysis results available."]
    if _sa_meth:
        _sa_summary_parts.append(f"Method: **{_sa_meth.upper()}**")
    if _sa_nevals:
        _sa_summary_parts.append(f"Evaluations: **{_sa_nevals:,}**")
    if _sa_rt and _sa_rt > 0:
        _rt_m, _rt_s = divmod(int(_sa_rt), 60)
        _rt_h, _rt_m = divmod(_rt_m, 60)
        if _rt_h:
            _sa_summary_parts.append(f"Total time: **{_rt_h}h {_rt_m}m {_rt_s}s**")
        elif _rt_m:
            _sa_summary_parts.append(f"Total time: **{_rt_m}m {_rt_s}s**")
        else:
            _sa_summary_parts.append(f"Total time: **{_rt_s}s**")
    st.success(" | ".join(_sa_summary_parts))

    _sa_tab1, _sa_tab2 = st.tabs(["Tornado Plot", "Ranking Table"])
    with _sa_tab1:
        fig_sa = plot_sensitivity_tornado(_sa_results, top_n=min(15, len(selected_params)))
        st.pyplot(fig_sa)
        plt.close(fig_sa)

    with _sa_tab2:
        _sa_table = sensitivity_ranking_table(_sa_results)
        st.dataframe(_sa_table, hide_index=True, width="stretch")

    # Auto-select button
    _suggested = get_suggested_parameters(_sa_results, top_n=10, min_threshold=0.01)
    if _suggested:
        st.markdown(f"**Suggested parameters** (S1 >= 0.01): {', '.join(_suggested)}")
        if st.button("Auto-select suggested parameters", key="sa_auto_select"):
            st.session_state.selected_params = _suggested
            st.rerun()

    # --- Best parameter set found during SA ---
    _sa_best = st.session_state.get("sa_best_params")
    _sa_best_obj = st.session_state.get("sa_best_objective")
    if _sa_best:
        st.markdown("---")
        st.subheader("Best Parameter Set from SA")
        st.caption(
            "During sensitivity analysis, the parameter combination below "
            "produced the highest objective function value. You can narrow "
            "calibration boundaries around these values for a more focused search."
        )
        _bc1, _bc2 = st.columns([1, 3])
        with _bc1:
            st.metric("Best Objective", f"{_sa_best_obj:.4f}")
        with _bc2:
            _best_df = pd.DataFrame([
                {"Parameter": k, "Value": round(v, 6)}
                for k, v in _sa_best.items()
            ])
            st.dataframe(_best_df, hide_index=True, width="stretch")

        if st.button("Narrow boundaries around best SA values", key="apply_sa_best"):
            from swat_modern.calibration.boundary_manager import BoundaryManager
            from swat_modern.calibration.parameters import CALIBRATION_PARAMETERS

            if "boundary_manager" not in st.session_state:
                bm = BoundaryManager()
                st.session_state["boundary_manager"] = bm
            else:
                bm = st.session_state["boundary_manager"]

            for _pname, _bval in _sa_best.items():
                _pinfo = CALIBRATION_PARAMETERS.get(_pname.upper())
                if _pinfo is None:
                    continue
                _default_range = _pinfo.max_value - _pinfo.min_value
                # Narrow to +/-25% of the default range, centered on best value
                _margin = max(_default_range * 0.25, 0.001)
                _new_min = max(_bval - _margin, _pinfo.min_value)
                _new_max = min(_bval + _margin, _pinfo.max_value)
                bm.set_boundary(_pname, min_value=_new_min, max_value=_new_max)
                bm.enable_parameter(_pname, True)

            st.success(
                "Boundaries narrowed around best SA values. "
                "Review them in the **Parameter Editor** page."
            )
            st.rerun()

if _sa_results is not None and not _sa_running:
    if st.button("Restart Sensitivity Analysis", type="secondary", key="restart_sa_btn"):
        for _k in [
            "sensitivity_results", "sa_best_params", "sa_best_objective",
            "sa_runtime", "sa_method_used", "sa_n_evaluations",
            "_sensitivity_state",
        ]:
            st.session_state.pop(_k, None)
        clear_active_sensitivity_state()
        # Re-save so load_session won't restore the cleared keys
        from swat_modern.app.session_persistence import save_session
        save_session(st.session_state)
        st.rerun()

if not _sa_running and _sa_results is None:
    # Show "Run SA" button or guidance if prerequisites aren't met
    _sa_can_run = bool(selected_params)
    if calibration_mode == "single":
        _sa_can_run = _sa_can_run and single_site_observed is not None
    elif calibration_mode == "partial_section":
        _sa_can_run = _sa_can_run and single_site_observed is not None
    elif calibration_mode in ("simultaneous", "sequential"):
        _sa_can_run = _sa_can_run and len(calibration_sites) >= 2

    if not selected_params:
        st.info("Select at least one parameter above to run sensitivity analysis.")
    elif calibration_mode in ("single", "partial_section") and single_site_observed is None:
        st.info("Load observation data and select a reach to run sensitivity analysis.")
    elif _sa_can_run:
        if st.button("Run Sensitivity Analysis", type="secondary", key="start_sa_btn"):
            _sa_config = {
                "project_path": st.session_state.project_path,
                "swat_executable": st.session_state.get("swat_executable", ""),
                "selected_params": selected_params,
                "objective": objective,
                "warmup_years": warmup_years,
                "calibration_print_code": calibration_print_code,
                "custom_sim_period": _custom_sim_period,
                "use_partial_basin": use_partial_basin,
                "output_variable": st.session_state.get("output_variable", "FLOW_OUTcms"),
                "output_type": st.session_state.get("output_type", "rch"),
                "use_custom_boundaries": use_custom_boundaries,
                "boundary_manager": boundary_manager,
                "qswat_shapes_dir": Path(qswat_shapes_dir) if qswat_shapes_dir else None,
                "single_reach": (
                    single_reach if calibration_mode in ("single", "partial_section")
                    else None
                ),
                "single_site_observed": (
                    single_site_observed if calibration_mode in ("single", "partial_section")
                    else None
                ),
                "upstream_subbasins": _parsed_upstream_override if _parsed_upstream_override else None,
                "wq_deferred": (
                    st.session_state.get("single_wq_wq_deferred")
                    or st.session_state.get("wq_wq_deferred")
                ) if st.session_state.get("_wq_deferred_flow") else None,
                "sa_method": st.session_state.get("sa_method", "fast"),
                "sa_n_samples": st.session_state.get("sa_n_samples", 50),
                "sa_parallel": st.session_state.get("sa_parallel", False),
                "sa_n_cores": st.session_state.get("sa_n_cores"),
                "calibration_mode": calibration_mode,
                "calibration_sites": calibration_sites if calibration_mode in ("simultaneous", "sequential") else None,
            }
            _sa_new = start_sensitivity(_sa_config)
            st.session_state["_sensitivity_state"] = _sa_new
            st.rerun()

# -------------------------------------------------------------------------
# Run calibration (state machine: idle \u2192 running \u2192 completed/failed)
# -------------------------------------------------------------------------
st.markdown("---")
st.header(f"{_section}. Run Calibration")

# Reconnect to a running calibration after browser refresh.
if "_calibration_state" not in st.session_state:
    _reconnected_cal = get_active_calibration_state()
    if _reconnected_cal is not None and _reconnected_cal.status in ("running", "cancelling", "completed"):
        st.session_state["_calibration_state"] = _reconnected_cal

_cal_state = st.session_state.get("_calibration_state")
_is_cal_running = _cal_state is not None and _cal_state.status in ("running", "cancelling")

mode_label = {
    "single": "Single-Site",
    "simultaneous": "Simultaneous Multi-Site",
    "sequential": "Sequential Upstream-to-Downstream",
    "partial_section": "Partial Section",
    "multi_constituent": "Multi-Constituent",
}.get(calibration_mode, calibration_mode)

# ---------- RUNNING: show live progress via auto-refreshing fragment ----------
@st.fragment(run_every=timedelta(seconds=2))
def _show_calibration_progress():
    """Auto-refreshing fragment that polls calibration progress.

    Using ``st.fragment(run_every=...)`` instead of ``time.sleep`` +
    ``st.rerun()`` avoids a Tornado WebSocketClosedError that occurs
    when a full-page rerun tears down the old WebSocket connection.
    """
    _cs = st.session_state.get("_calibration_state")
    if _cs is None:
        return

    # Calibration finished \u2014 trigger full page rerun so
    # check_and_transfer_results() at the top can process results.
    if _cs.status not in ("running", "cancelling"):
        st.session_state.pop("_cal_cancel_requested", None)
        st.rerun(scope="app")
        return

    _snap = _cs.snapshot()

    _ml = {
        "single": "Single-Site",
        "simultaneous": "Simultaneous Multi-Site",
        "sequential": "Sequential Upstream-to-Downstream",
        "partial_section": "Partial Section",
        "multi_constituent": "Multi-Constituent",
    }.get(st.session_state.get("calibration_mode", "single"), "")

    # Show cancellation-in-progress UI
    if _snap["cancel_requested"]:
        _cancel_msg = _snap.get("cancel_message", "Cancelling...")
        st.warning(f"**Cancelling {_ml} calibration...** {_cancel_msg}")
        st.progress(100)
        st.caption("Terminating SWAT processes and cleaning up temporary files...")
        # Re-apply cancel on every fragment rerun (in case button state was lost)
        _cs.request_cancel()
        return

    st.markdown(
        '<div style="padding: 0.75rem 1rem; background: linear-gradient(135deg, #e6510010, #f5711a15); '
        'border-left: 4px solid #e65100; border-radius: 0 8px 8px 0; margin-bottom: 1rem;">'
        f'<strong>{_ml} Calibration Running</strong><br>'
        '<span style="color: #666; font-size: 0.9em;">Running in the background \u2014 you can safely browse other tabs</span>'
        '</div>',
        unsafe_allow_html=True,
    )

    # Progress bar — true percentage based on simulation count
    _total = max(_snap["total_iterations"], 1)
    _sim_count = _snap["simulation_count"]
    _pct = min(int(100 * _sim_count / _total), 100)

    # Show preparing/baseline status when no simulations have started yet
    if _sim_count == 0:
        _step_msg_current = _snap.get("step_message", "")
        if _step_msg_current:
            st.info(f"**Preparing:** {_step_msg_current}")
        else:
            st.info("**Preparing:** Setting up calibration environment...")
        st.progress(0)
        st.caption("Waiting for first calibration simulation...")
    else:
        st.progress(_pct)
        st.caption(f"**{_pct}%** complete")

    # Parallel info for display
    _is_parallel = _snap.get("use_parallel", False)
    _n_cores_display = _snap.get("n_cores", 1)
    _n_iter_per_core = _snap.get("n_iterations_per_core", 0)

    # Live metrics \u2014 elapsed is wall-clock time from button click
    _elapsed = time.time() - _snap["start_time"] if _snap["start_time"] else 0
    _pc1, _pc2, _pc3, _pc4, _pc5 = st.columns(5)
    with _pc1:
        if _is_parallel and _n_cores_display > 1:
            st.metric(
                "Simulations",
                f"{_sim_count:,} / {_snap['total_iterations']:,}",
                help=f"{_n_cores_display} cores \u00d7 {_n_iter_per_core:,} iterations = {_snap['total_iterations']:,} total",
            )
            st.caption(f"{_n_cores_display} cores \u00d7 {_n_iter_per_core:,} iter")
        else:
            st.metric("Simulations", f"{_sim_count:,} / {_snap['total_iterations']:,}")
    with _pc2:
        _em, _es = divmod(int(_elapsed), 60)
        st.metric("Elapsed", f"{_em}m {_es}s" if _em else f"{_elapsed:.0f}s")
    with _pc3:
        _remaining = _snap["avg_time_per_sim"] * max(_snap["total_iterations"] - _sim_count, 0)
        _rm, _rs = divmod(int(_remaining), 60)
        st.metric("ETA", f"{_rm}m {_rs}s" if _rm else f"{_remaining:.0f}s")
    with _pc4:
        _best = _snap["best_score"]
        st.metric("Best Score", f"{_best:.4f}" if _best > -1e9 else "N/A")
    with _pc5:
        if _sim_count > 0 and _elapsed > 0:
            _speed = _sim_count / (_elapsed / 60)
            st.metric("Speed", f"{_speed:.1f}/min")
        else:
            st.metric("Speed", "\u2014")

    # Sequential / phased step info with visual indicators
    if _snap["mode"] in ("sequential", "multi_constituent") and _snap["total_steps"] > 0:
        _cur = _snap["current_step"]
        _tot = _snap["total_steps"]
        _step_msg = _snap["step_message"]

        # Pulse animation for active step
        st.markdown(
            '<style>'
            '@keyframes pulse {'
            '    0%, 100% { opacity: 1; transform: scale(1); }'
            '    50% { opacity: 0.7; transform: scale(1.1); }'
            '}'
            '</style>',
            unsafe_allow_html=True,
        )

        # Visual step indicators
        _step_cols = st.columns(_tot)
        for _i in range(_tot):
            with _step_cols[_i]:
                if _i + 1 < _cur:
                    st.markdown(
                        '<div style="text-align:center;padding:4px;background:#4CAF50;color:white;'
                        'border-radius:50%;width:28px;height:28px;margin:auto;line-height:20px;'
                        f'font-size:14px;">&#10003;</div>',
                        unsafe_allow_html=True,
                    )
                elif _i + 1 == _cur:
                    st.markdown(
                        '<div style="text-align:center;padding:4px;background:#2196F3;color:white;'
                        'border-radius:50%;width:28px;height:28px;margin:auto;line-height:20px;'
                        f'font-size:14px;animation:pulse 1.5s infinite;">{_i + 1}</div>',
                        unsafe_allow_html=True,
                    )
                else:
                    st.markdown(
                        '<div style="text-align:center;padding:4px;background:#e0e0e0;color:#999;'
                        'border-radius:50%;width:28px;height:28px;margin:auto;line-height:20px;'
                        f'font-size:14px;">{_i + 1}</div>',
                        unsafe_allow_html=True,
                    )
        st.caption(f"Step {_cur}/{_tot}: {_step_msg}")

    # Cancel button \u2014 persist across fragment reruns
    if st.button("Cancel Calibration", type="secondary", key="cancel_cal"):
        _cs.request_cancel()
        st.session_state["_cal_cancel_requested"] = True
    elif st.session_state.get("_cal_cancel_requested"):
        # Re-apply cancel on every fragment rerun until acknowledged
        _cs.request_cancel()

_is_cal_running_or_cancelling = (
    _cal_state is not None and _cal_state.status in ("running", "cancelling")
)

if _is_cal_running_or_cancelling:
    _show_calibration_progress()

# ---------- FAILED: show error ----------
elif _cal_state is not None and _cal_state.status == "failed":
    st.error(f"Calibration failed: {_cal_state.error_message}")
    if _cal_state.error_traceback:
        with st.expander("Error details"):
            st.code(_cal_state.error_traceback)
    if st.button("Dismiss Error"):
        st.session_state.pop("_calibration_state", None)
        st.session_state.pop("_cal_cancel_requested", None)
        clear_active_calibration_state()
        st.rerun()

# ---------- CANCELLED ----------
elif _cal_state is not None and _cal_state.status == "cancelled":
    st.warning("Calibration was cancelled successfully. All SWAT processes have been stopped and temporary files cleaned up.")
    if st.button("OK"):
        st.session_state.pop("_calibration_state", None)
        st.session_state.pop("_cal_cancel_requested", None)
        clear_active_calibration_state()
        st.rerun()

# ---------- IDLE / NO STATE: show start button ----------
else:
    # Validation
    _can_start = True
    if calibration_mode == "multi_constituent":
        # Multi-constituent: parameters come from phase config, not manual selection
        _mc_flow = st.session_state.get("_mc_flow_obs")
        if _mc_flow is None or (isinstance(_mc_flow, pd.DataFrame) and _mc_flow.empty):
            st.warning("Please upload streamflow observation data for multi-constituent calibration.")
            _can_start = False
        _mc_phases = st.session_state.get("_phased_config", [])
        _mc_enabled = [p for p in _mc_phases if p.enabled]
        if not _mc_enabled:
            st.warning("At least one phase must be enabled.")
            _can_start = False

        # Validate WQ observation data for enabled WQ phases
        _PHASE_REQ = {"sediment": "TSS_mg_L", "nitrogen": "TN_mg_L", "phosphorus": "TP_mg_L"}
        _wq_enabled = [p for p in _mc_enabled if p.name in _PHASE_REQ]
        if _wq_enabled:
            _mc_d = st.session_state.get("mc_wq_wq_deferred")
            _wq_check = None
            if _mc_d and isinstance(_mc_d, dict):
                _wq_check = _mc_d.get("wq_df")
            if _wq_check is None:
                _wq_check = st.session_state.get("mc_wq_wq_full")

            _missing_wq = []
            for _wp in _wq_enabled:
                _rc = _PHASE_REQ[_wp.name]
                if (
                    _wq_check is None
                    or _rc not in _wq_check.columns
                    or _wq_check[_rc].notna().sum() == 0
                ):
                    _missing_wq.append(f"**{_wp.name.capitalize()}** (`{_rc}`)")

            if _missing_wq:
                st.warning(
                    "The following WQ phases are enabled but have no observation data: "
                    + ", ".join(_missing_wq)
                    + ". Either upload WQ data with these columns, use the column mapping, "
                    "or disable those phases."
                )
                _can_start = False
    elif not selected_params:
        st.warning("Please select at least one parameter to calibrate.")
        _can_start = False
    elif calibration_mode == "single" and single_site_observed is None:
        st.warning("Please upload observation data above or load it on the **Observation Data** page.")
        _can_start = False
    elif calibration_mode == "partial_section":
        if single_site_observed is None:
            st.warning("Please upload observation data for the end subbasin.")
            _can_start = False
        if not st.session_state.get("ps_section_subs"):
            st.warning("Please detect upstream subbasins and select a start subbasin to define the calibration section.")
            _can_start = False
    elif (
        calibration_mode in ("simultaneous", "sequential")
        and len(calibration_sites) < 2
    ):
        st.warning("Multi-site calibration requires at least 2 sites with observation data.")
        _can_start = False

    # --- WQ observation data quality check (all non-multi-constituent modes) ---
    # When calibrating a WQ variable (SED_OUTtons, TOT_Nkg, etc.), verify
    # the observation data actually has values for the target constituent.
    # This catches cases where format auto-detection failed, columns didn't
    # map, or the user uploaded the wrong file — BEFORE burning SWAT runs.
    if (
        _can_start
        and calibration_mode != "multi_constituent"
        and _is_wq_variable
    ):
        _wq_target_col = _CONSTITUENT_TO_WQ_COL.get(
            _SWAT_VAR_TO_CONSTITUENT.get(cal_output_variable, ""), ""
        )
        _wq_target_const = _SWAT_VAR_TO_CONSTITUENT.get(cal_output_variable, "")

        if calibration_mode in ("single", "partial_section"):
            # Check the observation DataFrame — it should have 'observed' column
            # with actual data. Also check the deferred WQ dict if present.
            _obs_to_check = single_site_observed
            if _obs_to_check is not None and isinstance(_obs_to_check, pd.DataFrame):
                _obs_valid = (
                    "observed" in _obs_to_check.columns
                    and _obs_to_check["observed"].notna().sum() > 0
                )
                if not _obs_valid:
                    _prefix = "single_wq" if calibration_mode == "single" else "ps_wq"
                    st.warning(
                        f"The observation data for **{cal_output_variable}** "
                        f"({_wq_target_const}) has no valid values. "
                        f"Please upload a WQ file with **{_wq_target_col}** data "
                        f"or use the column mapping to select the right column."
                    )
                    _can_start = False

        elif calibration_mode in ("simultaneous", "sequential"):
            # Check each site's observation data
            _bad_sites = []
            for _si, _site in enumerate(calibration_sites):
                _site_obs = _site.get("observed")
                if _site_obs is not None and isinstance(_site_obs, pd.DataFrame):
                    if (
                        "observed" not in _site_obs.columns
                        or _site_obs["observed"].notna().sum() == 0
                    ):
                        _bad_sites.append(f"Site {_si + 1} (reach {_site.get('reach_id', '?')})")
            if _bad_sites:
                st.warning(
                    f"The following sites have no valid **{_wq_target_col}** "
                    f"({_wq_target_const}) observation data: "
                    + ", ".join(_bad_sites)
                    + ". Please check the WQ file and column mapping."
                )
                _can_start = False

    if _can_start and st.button(f"Start {mode_label} Calibration", type="primary"):
        # Build config dict for the background thread
        _config = {
            "mode": calibration_mode,
            "project_path": st.session_state.project_path,
            "swat_executable": st.session_state.get("swat_executable", ""),
            "selected_params": selected_params,
            "algorithm": algorithm,
            "n_iterations": n_iterations,
            "objective": objective,
            "warmup_years": warmup_years,
            "calibration_print_code": calibration_print_code,
            "custom_sim_period": _custom_sim_period,
            "use_partial_basin": use_partial_basin,
            "use_parallel": use_parallel,
            "n_cores": n_cores if use_parallel else None,
            "output_variable": st.session_state.get("output_variable", "FLOW_OUTcms"),
            "output_type": st.session_state.get("output_type", "rch"),
            "use_custom_boundaries": use_custom_boundaries,
            "boundary_manager": boundary_manager,
            "qswat_shapes_dir": Path(qswat_shapes_dir) if qswat_shapes_dir else None,
            "n_ensemble_workers": n_ensemble_workers,
            "kge_target": kge_target,
            "pbias_target": pbias_target,
        }

        if calibration_mode == "multi_constituent":
            _config["mode"] = "multi_constituent"
            _config["phased_config"] = st.session_state.get("_phased_config", [])
            _config["single_reach"] = st.session_state.get("_mc_reach", 1)
            _config["single_site_observed"] = st.session_state.get("_mc_flow_obs")
            # For multi-constituent, PhasedCalibrator needs the full WQ
            # DataFrame with canonical columns (TSS_mg_L, TN_mg_L, TP_mg_L, …),
            # NOT the single-column [date, observed] returned by _wq_observation_ui.
            # The deferred dict stores the full WQ DataFrame.
            # Priority: deferred dict → full WQ DataFrame → single-column fallback
            _mc_deferred = st.session_state.get("mc_wq_wq_deferred")
            _mc_wq_full = st.session_state.get("mc_wq_wq_full")
            if _mc_deferred and isinstance(_mc_deferred, dict) and "wq_df" in _mc_deferred:
                _config["wq_observations"] = _mc_deferred["wq_df"]
            elif _mc_wq_full is not None:
                _config["wq_observations"] = _mc_wq_full
            elif st.session_state.get("_mc_wq_obs") is not None:
                _config["wq_observations"] = st.session_state._mc_wq_obs
            elif "wq_load_data" in st.session_state:
                _config["wq_observations"] = st.session_state.wq_load_data
            if _parsed_upstream_override:
                _config["upstream_subbasins"] = _parsed_upstream_override
        elif calibration_mode == "single":
            _config["single_reach"] = single_reach
            _config["single_site_observed"] = single_site_observed
            # Pass deferred WQ info so calibration_runner can compute
            # loads from simulated flow at calibration time.
            if st.session_state.get("_wq_deferred_flow"):
                _deferred = st.session_state.get("single_wq_wq_deferred")
                if _deferred is None:
                    _deferred = st.session_state.get("wq_wq_deferred")
                if _deferred is not None:
                    _config["wq_deferred"] = _deferred
            if _parsed_upstream_override:
                _config["upstream_subbasins"] = _parsed_upstream_override
        elif calibration_mode == "partial_section":
            _config["single_reach"] = ps_end_sub
            _config["single_site_observed"] = single_site_observed
            _config["partial_section_start"] = ps_start_sub
            _config["partial_section_end"] = ps_end_sub
            _config["section_subbasins"] = st.session_state.get("ps_section_subs", [])
            _config["use_partial_basin"] = use_partial_basin
            _config["qswat_shapes_dir"] = Path(qswat_shapes_dir) if qswat_shapes_dir else None
            if _parsed_upstream_override:
                _config["upstream_subbasins"] = _parsed_upstream_override
        elif calibration_mode in ("simultaneous", "sequential"):
            _config["calibration_sites"] = calibration_sites

        # Clear any previous results before starting a new run
        for _key in [
            "calibration_result", "best_parameters", "calibration_results_full",
            "calibration_runtime", "baseline_results", "sequential_results",
            "calibration_objective", "phased_results", "calibration_reach_id",
        ]:
            st.session_state.pop(_key, None)
        clear_calibration_results(st.session_state)

        _new_state = start_calibration(_config)
        st.session_state["_calibration_state"] = _new_state
        st.rerun()

# -------------------------------------------------------------------------
# Persistent results display (survives tab switching)
# -------------------------------------------------------------------------
st.markdown("---")
st.header("Calibration Status")

if "calibration_result" in st.session_state:
    import matplotlib.pyplot as plt

    _cal_runtime = st.session_state.get("calibration_runtime")
    _last_mode = st.session_state.get("calibration_mode", "single")

    # Runtime banner
    if _cal_runtime is not None:
        _rt_mins, _rt_secs = divmod(int(_cal_runtime), 60)
        if _rt_mins > 0:
            _rt_str = f"{_rt_mins}m {_rt_secs}s"
        else:
            _rt_str = f"{_cal_runtime:.1f}s"
        _mode_disp = {
            "single": "Single-Site",
            "simultaneous": "Simultaneous Multi-Site",
            "sequential": "Sequential",
            "partial_section": "Partial Section",
            "multi_constituent": "Multi-Constituent",
        }.get(_last_mode, "")
        st.success(f"**{_mode_disp} Calibration** completed in **{_rt_str}**")

    # --- Baseline (pre-calibration) plots ---
    # Baseline data comes from run_baseline_simulation() which merges on
    # the reconstructed "date" column (year+month+day), not raw RCH/MON.
    # _bl_obs / _bl_sim are pre-aligned numpy arrays — no RCH/MON join here.
    _baseline_results = st.session_state.get("baseline_results")
    if _baseline_results:
        with st.expander("Pre-Calibration Baseline", expanded=False):
            _bl_ok = [b for b in _baseline_results if b.get("success")]
            for _bl in _bl_ok:
                _bl_obs = _bl.get("observed")
                _bl_sim = _bl.get("simulated")
                _bl_dates = _bl.get("dates")
                _bl_metrics = _bl.get("metrics", {})
                _bl_rid = _bl.get("reach_id", "")

                if _bl_obs is not None and _bl_sim is not None:
                    _bl_obj_name = st.session_state.get("calibration_objective", "nse")
                    _bl_obj_val = _bl_metrics.get(_bl_obj_name, float("nan"))
                    _bl_obj_label = _bl_obj_name.upper()

                    _x = pd.to_datetime(_bl_dates) if _bl_dates is not None else np.arange(len(_bl_obs))

                    fig_bl, ax_bl = plt.subplots(figsize=(14, 4))
                    ax_bl.plot(_x, _bl_obs, color="black", linewidth=1, label="Observed", alpha=0.9)
                    ax_bl.plot(_x, _bl_sim, color="red", linewidth=1, linestyle="--", label="Simulated (baseline)", alpha=0.7)
                    ax_bl.set_xlabel("Date" if _bl_dates is not None else "Time Step")
                    ax_bl.set_ylabel(cal_output_variable)
                    _bl_fmt = f"{_bl_obj_val:.2f}%" if _bl_obj_name == "pbias" else f"{_bl_obj_val:.3f}"
                    ax_bl.set_title(
                        f"Pre-Calibration Baseline \u2014 Reach {_bl_rid} "
                        f"({_bl_obj_label}={_bl_fmt})"
                    )
                    ax_bl.legend()
                    ax_bl.grid(True, alpha=0.3)
                    plt.tight_layout()
                    st.pyplot(fig_bl)
                    plt.close(fig_bl)

                    st.caption(
                        f"Baseline metrics \u2014 NSE: {_bl_metrics.get('nse', float('nan')):.4f}, "
                        f"KGE: {_bl_metrics.get('kge', float('nan')):.4f}, "
                        f"PBIAS: {_bl_metrics.get('pbias', float('nan')):.2f}%"
                    )

                    # --- Baseline Diagnostic Analysis ---
                    try:
                        _bl_obs_arr = np.asarray(_bl_obs, dtype=np.float64)
                        _bl_sim_arr = np.asarray(_bl_sim, dtype=np.float64)
                        _bl_dates_dt = pd.to_datetime(_bl_dates).values if _bl_dates is not None else None

                        if _output_category == "sediment":
                            from swat_modern.calibration.diagnostics import diagnose_sediment
                            _bl_report = diagnose_sediment(_bl_obs_arr, _bl_sim_arr, dates=_bl_dates_dt)
                        elif _output_category == "nitrogen":
                            from swat_modern.calibration.diagnostics import diagnose_nitrogen
                            _bl_report = diagnose_nitrogen(_bl_obs_arr, _bl_sim_arr, dates=_bl_dates_dt)
                        elif _output_category == "phosphorus":
                            from swat_modern.calibration.diagnostics import diagnose_phosphorus
                            _bl_report = diagnose_phosphorus(_bl_obs_arr, _bl_sim_arr, dates=_bl_dates_dt)
                        else:
                            from swat_modern.calibration.diagnostics import diagnose
                            _bl_report = diagnose(_bl_obs_arr, _bl_sim_arr, _bl_dates_dt)

                        if _bl_report.findings:
                            st.markdown("**Diagnostic Findings:**")
                            for _f in _bl_report.findings:
                                st.markdown(f"- [{_f.confidence.upper()}] {_f.description}")

                            if _bl_report.recommendations:
                                st.markdown("**Parameter Recommendations:**")
                                _rec_data = []
                                for _r in _bl_report.recommendations:
                                    _arrow = "\u2191" if _r.direction == "increase" else "\u2193"
                                    _rec_data.append({
                                        "Parameter": _r.parameter,
                                        "Direction": f"{_arrow} {_r.direction}",
                                        "Reason": _r.reason,
                                        "Confidence": _r.confidence,
                                    })
                                st.dataframe(pd.DataFrame(_rec_data), hide_index=True, width="stretch")
                        else:
                            _no_issue_label = {
                                "sediment": "sediment", "nitrogen": "nitrogen",
                                "phosphorus": "phosphorus",
                            }.get(_output_category, "hydrograph")
                            st.info(f"No significant {_no_issue_label} diagnostic issues found in baseline.")

                    except Exception as _diag_err:
                        st.caption(f"Diagnostic analysis unavailable: {_diag_err}")

    # --- Performance Metrics ---
    st.subheader("Performance Metrics")
    _result_metrics = st.session_state.calibration_result

    if "sequential_results" in st.session_state:
        _seq_res = st.session_state.sequential_results
        for _step in _seq_res.steps:
            _step_m = _step.metrics or {}
            st.markdown(
                f"**Step {_step.step_number}: Reach {_step.reach_id}** "
                f"({len(_step.subbasin_ids)} subbasins, {_step.runtime:.1f}s)"
            )
            _smc1, _smc2, _smc3, _smc4 = st.columns(4)
            with _smc1:
                st.metric("NSE", f"{_step_m.get('nse', 0):.4f}")
            with _smc2:
                st.metric("KGE", f"{_step_m.get('kge', 0):.4f}")
            with _smc3:
                st.metric("PBIAS", f"{_step_m.get('pbias', 0):.2f}%")
            with _smc4:
                st.metric("RSR", f"{_step_m.get('rsr', 0):.4f}")

            if _step.best_params:
                with st.expander(f"Step {_step.step_number} Parameters"):
                    _sp_df = pd.DataFrame([
                        {"Parameter": k, "Value": f"{v:.6f}"}
                        for k, v in _step.best_params.items()
                    ])
                    st.table(_sp_df)

        st.markdown("**Summary**")
        _seq_metrics_df = _seq_res.get_metrics_by_step()
        st.dataframe(_seq_metrics_df, hide_index=True)

    elif "phased_results" in st.session_state:
        _phased_res = st.session_state.phased_results

        st.markdown(
            f"**Phases completed:** {_phased_res.phases_completed} / "
            f"{_phased_res.phases_total}"
        )

        # Per-phase metrics table
        _phase_rows = []
        for _pr in _phased_res.phase_results:
            _pr_metrics = _pr.get("metrics", {})
            _row = {"Phase": _pr["name"].replace("_", " ").title()}
            if _pr.get("skipped"):
                _row["Status"] = "Skipped"
            elif _pr.get("error"):
                _row["Status"] = f"Error: {_pr['error']}"
            else:
                _row["Status"] = "Completed"
                for _mk in ("nse", "kge", "pbias", "rsr"):
                    _mv = _pr_metrics.get(_mk)
                    if _mv is not None:
                        _row[_mk.upper()] = f"{_mv:.4f}"
            _phase_rows.append(_row)

        st.dataframe(pd.DataFrame(_phase_rows), hide_index=True, width="stretch")

        # Per-phase parameter details
        for _pr in _phased_res.phase_results:
            if _pr.get("parameters"):
                with st.expander(f"Phase: {_pr['name'].replace('_', ' ').title()} -- Parameters"):
                    _pr_params = _pr["parameters"]
                    _pr_metrics = _pr.get("metrics", {})

                    # Show metrics for this phase
                    if _pr_metrics:
                        _pmc1, _pmc2, _pmc3, _pmc4 = st.columns(4)
                        with _pmc1:
                            st.metric("NSE", f"{_pr_metrics.get('nse', 0):.4f}")
                        with _pmc2:
                            st.metric("KGE", f"{_pr_metrics.get('kge', 0):.4f}")
                        with _pmc3:
                            st.metric("PBIAS", f"{_pr_metrics.get('pbias', 0):.2f}%")
                        with _pmc4:
                            st.metric("RSR", f"{_pr_metrics.get('rsr', 0):.4f}")

                    _pp_df = pd.DataFrame([
                        {"Parameter": k, "Value": f"{v:.6f}"}
                        for k, v in _pr_params.items()
                    ])
                    st.table(_pp_df)

    else:
        _rmc1, _rmc2, _rmc3, _rmc4 = st.columns(4)
        with _rmc1:
            st.metric("NSE", f"{_result_metrics.get('nse', 0):.4f}")
        with _rmc2:
            st.metric("KGE", f"{_result_metrics.get('kge', 0):.4f}")
        with _rmc3:
            st.metric("PBIAS", f"{_result_metrics.get('pbias', 0):.2f}%")
        with _rmc4:
            st.metric("RSR", f"{_result_metrics.get('rsr', 0):.4f}")

    # --- Best Parameters ---
    st.subheader("Best Parameters Found")
    _best_params = st.session_state.get("best_parameters", {})
    if _best_params:
        _bp_df = pd.DataFrame([
            {"Parameter": k, "Value": f"{v:.6f}"}
            for k, v in _best_params.items()
        ])
        st.table(_bp_df)

    st.info("Go to **Results** page for detailed plots and export options.")

    # Allow starting a new calibration
    if st.button("Start New Calibration"):
        for _key in [
            "calibration_result", "best_parameters", "calibration_results_full",
            "calibration_runtime", "baseline_results", "sequential_results",
            "calibration_objective", "_calibration_state", "phased_results",
            "calibration_reach_id",
        ]:
            st.session_state.pop(_key, None)
        clear_calibration_results(st.session_state)
        st.rerun()

elif not _is_cal_running and (_cal_state is None or _cal_state.status not in ("running", "cancelling", "completed", "error", "cancelled")):
    st.info("No calibration run yet. Configure settings and click 'Start Calibration'.")
