"""
Results Page - View calibration results and export.
"""

import io
import shutil
import streamlit as st
import pandas as pd
import numpy as np
from pathlib import Path
import json
from datetime import datetime
from swat_modern.app.session_persistence import load_session, clear_session, load_calibration_results
from swat_modern.app.calibration_runner import check_and_transfer_results


def _apply_params_to_copy(project_path: str, best_params: dict, exe_path: str = None) -> Path:
    """Create a copy of TxtInOut and apply calibrated parameters there.

    Returns the path to the new calibrated directory.
    """
    from swat_modern import SWATModel
    from swat_modern.calibration.parameters import CALIBRATION_PARAMETERS

    src_dir = Path(project_path)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest_dir = src_dir.parent / f"{src_dir.name}_calibrated_{timestamp}"

    shutil.copytree(src_dir, dest_dir)

    model = SWATModel(str(dest_dir), executable=exe_path)
    modified_count = 0
    for param_name, value in best_params.items():
        param_def = CALIBRATION_PARAMETERS.get(param_name.upper())
        if param_def:
            model.modify_parameter(
                param_name, value,
                file_type=param_def.file_type,
                method=param_def.method,
            )
        else:
            model.modify_parameter(param_name, value, file_type=None)
        modified_count += 1

    return dest_dir, modified_count


def _apply_partial_section_params_to_copy(
    project_path: str,
    best_params: dict,
    section_subbasins: list,
    exe_path: str = None,
) -> tuple:
    """Create a calibrated copy applying parameters only to section subbasins.

    BSN (global) parameters are applied basin-wide.  Per-subbasin parameters
    (.gw, .mgt, .hru, .rte, .sol, .sub) are applied only to the subbasins
    that were actually calibrated (the section).  Locked upstream subbasins
    keep their original values.
    """
    from swat_modern import SWATModel
    from swat_modern.calibration.parameters import CALIBRATION_PARAMETERS, ParameterSet

    src_dir = Path(project_path)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest_dir = src_dir.parent / f"{src_dir.name}_calibrated_{timestamp}"
    shutil.copytree(src_dir, dest_dir)

    model = SWATModel(str(dest_dir), executable=exe_path)
    modified_count = 0

    for param_name, value in best_params.items():
        pdef = CALIBRATION_PARAMETERS.get(param_name.upper())
        if pdef is None:
            continue

        is_bsn = pdef.file_type in ParameterSet.BASIN_WIDE_TYPES
        has_hru_equiv = param_name.upper() in ParameterSet.BSN_TO_HRU_MAP

        if is_bsn and not has_hru_equiv:
            # Basin-wide param with no per-HRU equivalent (e.g. SURLAG):
            # must apply globally (single basins.bsn file)
            model.modify_parameter(
                param_name, value,
                file_type=pdef.file_type,
                method=pdef.method,
            )
            modified_count += 1
        elif is_bsn and has_hru_equiv:
            # BSN param with HRU equivalent (e.g. ESCO, EPCO):
            # apply via HRU files scoped to section subbasins only
            for sub_id in section_subbasins:
                model.modify_parameter(
                    param_name, value,
                    file_type="hru",
                    method=pdef.method,
                    unit_id=sub_id,
                )
                modified_count += 1
        else:
            # Per-subbasin param: apply only to section subbasins
            for sub_id in section_subbasins:
                model.modify_parameter(
                    param_name, value,
                    file_type=pdef.file_type,
                    method=pdef.method,
                    unit_id=sub_id,
                )
                modified_count += 1

    return dest_dir, modified_count


def _apply_sequential_params_to_copy(project_path: str, seq_steps, exe_path: str = None):
    """Create a calibrated copy applying per-step parameters from sequential calibration.

    BSN (global) parameters use the downstream step's calibrated values — they cannot
    be scoped per-subbasin and the downstream step sees the full basin.
    HRU/sub parameters are applied scoped to each step's subbasin group so that
    upstream and downstream subbasins each keep their own calibrated values.
    """
    from swat_modern import SWATModel
    from swat_modern.calibration.parameters import CALIBRATION_PARAMETERS, ParameterSet

    src_dir = Path(project_path)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest_dir = src_dir.parent / f"{src_dir.name}_calibrated_{timestamp}"
    shutil.copytree(src_dir, dest_dir)

    model = SWATModel(str(dest_dir), executable=exe_path)
    modified_count = 0

    # Pass 1: collect and apply BSN-level (global) params — downstream step wins
    # (steps are ordered upstream→downstream, so iterating forward gives downstream last)
    bsn_final: dict = {}  # param_name -> (value, pdef)
    for step in seq_steps:
        if not step.best_params:
            continue
        for param_name, value in step.best_params.items():
            pdef = CALIBRATION_PARAMETERS.get(param_name.upper())
            if pdef and pdef.file_type in ParameterSet.BASIN_WIDE_TYPES:
                bsn_final[param_name] = (value, pdef)

    for param_name, (value, pdef) in bsn_final.items():
        model.modify_parameter(
            param_name, value,
            file_type=pdef.file_type,
            method=pdef.method,
        )
        modified_count += 1

    # Pass 2: apply HRU/sub params scoped to each step's subbasin group
    for step in seq_steps:
        if not step.best_params:
            continue
        for param_name, value in step.best_params.items():
            pdef = CALIBRATION_PARAMETERS.get(param_name.upper())
            if pdef is None:
                continue
            is_bsn = pdef.file_type in ParameterSet.BASIN_WIDE_TYPES
            has_hru_equiv = param_name.upper() in ParameterSet.BSN_TO_HRU_MAP
            if is_bsn and not has_hru_equiv:
                continue  # already applied globally in pass 1
            if is_bsn and has_hru_equiv:
                # BSN params with HRU equivalent (e.g. ESCO, EPCO): apply via HRU
                # file scoped to each subbasin.  Use original name because the .hru
                # file label is "ESCO", not "ESCO_HRU".
                for sub_id in step.subbasin_ids:
                    model.modify_parameter(
                        param_name, value,
                        file_type="hru",
                        method=pdef.method,
                        unit_id=sub_id,
                    )
                    modified_count += 1
            else:
                # Per-subbasin params (hru, sub, rte, sol, gw, mgt…): scoped to
                # this step's subbasin group only — file_type is passed as-is so
                # .sub and .rte files are handled identically to .hru files.
                for sub_id in step.subbasin_ids:
                    model.modify_parameter(
                        param_name, value,
                        file_type=pdef.file_type,
                        method=pdef.method,
                        unit_id=sub_id,
                    )
                    modified_count += 1

    return dest_dir, modified_count


def _fig_to_png_bytes(fig) -> bytes:
    """Render a matplotlib figure to PNG bytes for download."""
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=200, bbox_inches="tight")
    buf.seek(0)
    return buf.getvalue()

st.set_page_config(page_title="Results", page_icon="📈", layout="wide")

try:
    from swat_modern.app.loading_utils import hide_deploy_button
    hide_deploy_button()
except ImportError:
    pass

# Restore session state on page load (survives browser refresh)
load_session(st.session_state)
load_calibration_results(st.session_state)

try:
    from swat_modern.app.loading_utils import inject_shimmer_css
    inject_shimmer_css()
except ImportError:
    pass

# Check if a background calibration just completed and transfer results
check_and_transfer_results(st.session_state)

# Sidebar: Exit Project button
with st.sidebar:
    if "project_path" in st.session_state:
        if st.button("Exit Project", type="secondary", width="stretch"):
            clear_session(st.session_state)
            st.rerun()

st.title("📈 Calibration Results")
st.markdown("View performance metrics, comparison plots, and export results.")

# Check if calibration has been run
_has_phased = "phased_results" in st.session_state
if "calibration_result" not in st.session_state and not _has_phased:
    st.warning("No calibration results available yet.")
    st.info("Run calibration first in the **Calibration** page, then return here to view results.")

    if st.button("Go to Calibration Page"):
        st.switch_page("pages/6_Calibration.py")
    st.stop()

# -------------------------------------------------------------------------
# Multi-Constituent (Phased) Results Display
# -------------------------------------------------------------------------
if _has_phased:
    import matplotlib.pyplot as plt

    _phased = st.session_state.phased_results

    st.header("Multi-Constituent Calibration Results")
    st.write(f"**Phases completed:** {_phased.phases_completed} / {_phased.phases_total}")
    st.write(f"**Total runtime:** {_phased.total_runtime:.1f}s")

    # Summary table
    _mc_summary_rows = []
    for _pr in _phased.phase_results:
        _m = _pr.get("metrics", {})
        _row = {
            "Phase": _pr["name"].replace("_", " ").capitalize(),
            "Algorithm": _pr.get("algorithm", "N/A"),
        }
        if _pr.get("skipped"):
            _row["Status"] = "Skipped"
        elif _pr.get("error"):
            _row["Status"] = f"Error: {_pr['error']}"
        else:
            _row["Status"] = "Completed"
        _row["NSE"] = f"{_m.get('nse', float('nan')):.3f}" if _m.get("nse") is not None else "N/A"
        _row["KGE"] = f"{_m.get('kge', float('nan')):.3f}" if _m.get("kge") is not None else "N/A"
        _row["PBIAS"] = f"{_m.get('pbias', float('nan')):.1f}%" if _m.get("pbias") is not None else "N/A"
        _row["Iterations"] = _pr.get("n_iterations", "N/A")
        _mc_summary_rows.append(_row)
    if _mc_summary_rows:
        st.table(_mc_summary_rows)

    # Per-phase expandable details
    for _pr in _phased.phase_results:
        _phase_label = _pr["name"].replace("_", " ").capitalize()
        if _pr.get("skipped"):
            continue
        with st.expander(f"{_phase_label} Phase Details"):
            _cal_result = _pr.get("result")

            # Time series plot if result has observed/simulated
            if (
                _cal_result is not None
                and hasattr(_cal_result, "simulated")
                and hasattr(_cal_result, "observed")
                and len(getattr(_cal_result, "observed", [])) > 0
            ):
                _pr_obs = np.asarray(_cal_result.observed, dtype=float)
                _pr_sim = np.asarray(_cal_result.simulated, dtype=float)
                _pr_dates = getattr(_cal_result, "dates", None)

                fig_ph, ax_ph = plt.subplots(figsize=(10, 4))
                if _pr_dates is not None:
                    _pr_x = pd.to_datetime(_pr_dates)
                    ax_ph.plot(_pr_x, _pr_obs, 'k-', label='Observed', alpha=0.7)
                    ax_ph.plot(_pr_x, _pr_sim, 'r-', label='Simulated', alpha=0.7)
                else:
                    ax_ph.plot(_pr_obs, 'k-', label='Observed', alpha=0.7)
                    ax_ph.plot(_pr_sim, 'r-', label='Simulated', alpha=0.7)
                ax_ph.set_title(f"{_phase_label} -- Observed vs Simulated")
                ax_ph.legend()
                ax_ph.set_ylabel(_pr.get("output_variable", "Value"))
                ax_ph.grid(True, alpha=0.3)
                plt.tight_layout()
                st.pyplot(fig_ph)
                plt.close(fig_ph)

                # Scatter plot
                _pr_mask = ~(np.isnan(_pr_obs) | np.isnan(_pr_sim))
                _pr_obs_c = _pr_obs[_pr_mask]
                _pr_sim_c = _pr_sim[_pr_mask]
                if len(_pr_obs_c) > 0:
                    fig_sc, ax_sc = plt.subplots(figsize=(5, 5))
                    ax_sc.scatter(_pr_obs_c, _pr_sim_c, alpha=0.5, s=15)
                    _all_v = np.concatenate([_pr_obs_c, _pr_sim_c])
                    ax_sc.plot(
                        [np.min(_all_v), np.max(_all_v)],
                        [np.min(_all_v), np.max(_all_v)],
                        'k--', linewidth=1, label='1:1 Line',
                    )
                    ax_sc.set_xlabel("Observed")
                    ax_sc.set_ylabel("Simulated")
                    ax_sc.set_title(f"{_phase_label} -- Scatter")
                    ax_sc.legend()
                    ax_sc.set_aspect('equal', adjustable='box')
                    ax_sc.grid(True, alpha=0.3)
                    plt.tight_layout()
                    st.pyplot(fig_sc)
                    plt.close(fig_sc)

            # Best parameters for this phase
            _pr_params = _pr.get("parameters", {})
            if _pr_params:
                st.markdown("**Calibrated Parameters:**")
                _pr_param_df = pd.DataFrame([
                    {"Parameter": k, "Value": f"{v:.4f}"}
                    for k, v in _pr_params.items()
                ])
                st.dataframe(_pr_param_df, hide_index=True)

            # Phase metrics
            _pr_m = _pr.get("metrics", {})
            if _pr_m:
                _pm_cols = st.columns(4)
                with _pm_cols[0]:
                    st.metric("NSE", f"{_pr_m.get('nse', float('nan')):.4f}")
                with _pm_cols[1]:
                    st.metric("KGE", f"{_pr_m.get('kge', float('nan')):.4f}")
                with _pm_cols[2]:
                    st.metric("PBIAS", f"{_pr_m.get('pbias', float('nan')):.2f}%")
                with _pm_cols[3]:
                    st.metric("RSR", f"{_pr_m.get('rsr', float('nan')):.4f}")

            # Seasonal PBIAS bar chart (from diagnostic info if available)
            _diag_info = _pr.get("diagnostic_info", {})
            _seasonal = _diag_info.get("seasonal_bias", {})
            if _seasonal:
                fig_sb, ax_sb = plt.subplots(figsize=(6, 3))
                _seasons = list(_seasonal.keys())
                _biases = [
                    _seasonal[s].get("pbias", 0) if isinstance(_seasonal[s], dict)
                    else float(_seasonal[s])
                    for s in _seasons
                ]
                _colors = [
                    'green' if abs(b) < 15 else 'orange' if abs(b) < 25 else 'red'
                    for b in _biases
                ]
                ax_sb.bar(_seasons, _biases, color=_colors)
                ax_sb.axhline(y=0, color='black', linewidth=0.5)
                ax_sb.set_ylabel("PBIAS (%)")
                ax_sb.set_title(f"{_phase_label} -- Seasonal Bias")
                plt.tight_layout()
                st.pyplot(fig_sb)
                plt.close(fig_sb)

    # Combined parameter table
    st.markdown("---")
    st.subheader("All Calibrated Parameters")
    _all_params = _phased.all_best_parameters
    if _all_params:
        _all_param_rows = [
            {"Parameter": k, "Value": f"{v:.4f}"} for k, v in sorted(_all_params.items())
        ]
        st.dataframe(pd.DataFrame(_all_param_rows), hide_index=True)

    # Export
    st.markdown("---")
    st.subheader("Export Multi-Constituent Results")
    _mc_export_col1, _mc_export_col2 = st.columns(2)
    with _mc_export_col1:
        import json as _mc_json
        _mc_export = {
            "phases_completed": _phased.phases_completed,
            "phases_total": _phased.phases_total,
            "total_runtime": _phased.total_runtime,
            "all_best_parameters": {
                k: float(v) for k, v in _all_params.items()
            } if _all_params else {},
            "phase_metrics": [
                {"name": pr["name"], "metrics": pr.get("metrics", {})}
                for pr in _phased.phase_results
            ],
        }
        st.download_button(
            label="Download Parameters (JSON)",
            data=_mc_json.dumps(_mc_export, indent=2),
            file_name="multi_constituent_parameters.json",
            mime="application/json",
        )
    with _mc_export_col2:
        if _all_params:
            _mc_params_csv = pd.DataFrame([
                {"Parameter": k, "Value": v} for k, v in sorted(_all_params.items())
            ]).to_csv(index=False)
            st.download_button(
                label="Download Parameters (CSV)",
                data=_mc_params_csv,
                file_name="multi_constituent_parameters.csv",
                mime="text/csv",
            )

    # Apply parameters button — creates a copy to preserve the original
    st.markdown("---")
    if _all_params and st.button("Apply All Calibrated Parameters to Model", type="primary"):
        try:
            _exe = st.session_state.get("swat_executable", "").strip() or None
            with st.spinner("Copying project and applying parameters..."):
                _dest, _mod_count = _apply_params_to_copy(
                    st.session_state.project_path, _all_params, _exe,
                )
            st.success(
                f"{_mod_count} parameters applied to a new copy!\n\n"
                f"**Calibrated project:** `{_dest}`\n\n"
                f"The original model is unchanged."
            )
        except Exception as _e:
            st.error(f"Error applying parameters: {_e}")

    # If we also have standard calibration results, continue to show them
    if "calibration_result" not in st.session_state:
        st.stop()

# Get results from session
metrics = st.session_state.calibration_result
best_params = st.session_state.best_parameters
results_full = st.session_state.get("calibration_results_full", None)
# Prefer objective_name from the CalibrationResult itself (most reliable);
# fall back to session state set on the Calibration page.
if results_full is not None and hasattr(results_full, "objective_name"):
    objective_name = results_full.objective_name
else:
    objective_name = st.session_state.get("calibration_objective", "nse")

# Detect result type — distinguish DiagnosticCalibrationResult from true sequential
is_diagnostic = False
if results_full is not None:
    try:
        from swat_modern.calibration.diagnostic_calibrator import (
            DiagnosticCalibrationResult,
        )
        if isinstance(results_full, DiagnosticCalibrationResult):
            is_diagnostic = True
    except ImportError:
        pass

is_sequential = hasattr(results_full, "steps") and not is_diagnostic
is_multisite = (
    hasattr(results_full, "site_results")
    and len(getattr(results_full, "site_results", [])) > 1
)

st.markdown("---")

# Performance Metrics Summary
st.header("1. Performance Metrics")

# Display calibration runtime
_cal_runtime = st.session_state.get("calibration_runtime")
if _cal_runtime is not None:
    _rt_mins, _rt_secs = divmod(int(_cal_runtime), 60)
    _rt_hours, _rt_mins = divmod(_rt_mins, 60)
    if _rt_hours > 0:
        _rt_str = f"{_rt_hours}h {_rt_mins}m {_rt_secs}s"
    elif _rt_mins > 0:
        _rt_str = f"{_rt_mins}m {_rt_secs}s"
    else:
        _rt_str = f"{_cal_runtime:.1f}s"
    st.info(f"Total calibration runtime: **{_rt_str}**")

if is_sequential:
    # Show per-step metrics for sequential calibration
    seq_results = results_full
    for step in seq_results.steps:
        step_metrics = step.metrics or {}
        _step_rt = f", {step.runtime:.1f}s" if step.runtime else ""
        st.markdown(f"**Reach {step.reach_id}** (Step {step.step_number}, {len(step.subbasin_ids)} subbasins{_step_rt})")
        mc1, mc2, mc3, mc4, mc5 = st.columns(5)
        with mc1:
            nse_val = step_metrics.get('nse', 0)
            rating = "Very Good" if nse_val > 0.75 else "Good" if nse_val > 0.65 else "Satisfactory" if nse_val > 0.5 else "Unsatisfactory"
            st.metric("NSE", f"{nse_val:.4f}", help=f"Rating: {rating}")
        with mc2:
            st.metric("KGE", f"{step_metrics.get('kge', 0):.4f}")
        with mc3:
            st.metric("PBIAS", f"{step_metrics.get('pbias', 0):.2f}%")
        with mc4:
            st.metric("RSR", f"{step_metrics.get('rsr', 0):.4f}")
        with mc5:
            st.metric("R²", f"{step_metrics.get('r_squared', 0):.4f}")

elif is_diagnostic:
    # Show per-phase metrics for diagnostic calibration
    diag_result = results_full
    for step in diag_result.steps:
        step_metrics = step.metrics or {}
        _step_rt = f", {step.runtime:.1f}s" if step.runtime else ""
        st.markdown(f"**Phase: {step.phase}** (Iteration {step.iteration}{_step_rt})")
        mc1, mc2, mc3, mc4, mc5 = st.columns(5)
        with mc1:
            nse_val = step_metrics.get('nse', 0)
            rating = "Very Good" if nse_val > 0.75 else "Good" if nse_val > 0.65 else "Satisfactory" if nse_val > 0.5 else "Unsatisfactory"
            st.metric("NSE", f"{nse_val:.4f}", help=f"Rating: {rating}")
        with mc2:
            st.metric("KGE", f"{step_metrics.get('kge', 0):.4f}")
        with mc3:
            st.metric("PBIAS", f"{step_metrics.get('pbias', 0):.2f}%")
        with mc4:
            st.metric("RSR", f"{step_metrics.get('rsr', 0):.4f}")
        with mc5:
            st.metric("R²", f"{step_metrics.get('r_squared', 0):.4f}")

elif is_multisite:
    # Show per-site metrics for multi-site calibration
    for site_data in results_full.site_results:
        site_metrics = site_data.get("metrics", {})
        st.markdown(f"**Reach {site_data['reach_id']}**")
        mc1, mc2, mc3, mc4, mc5 = st.columns(5)
        with mc1:
            nse_val = site_metrics.get('nse', 0)
            rating = "Very Good" if nse_val > 0.75 else "Good" if nse_val > 0.65 else "Satisfactory" if nse_val > 0.5 else "Unsatisfactory"
            st.metric("NSE", f"{nse_val:.4f}", help=f"Rating: {rating}")
        with mc2:
            st.metric("KGE", f"{site_metrics.get('kge', 0):.4f}")
        with mc3:
            st.metric("PBIAS", f"{site_metrics.get('pbias', 0):.2f}%")
        with mc4:
            st.metric("RSR", f"{site_metrics.get('rsr', 0):.4f}")
        with mc5:
            st.metric("R²", f"{site_metrics.get('r_squared', 0):.4f}")

else:
    # Single-site metrics
    col1, col2, col3, col4, col5 = st.columns(5)
    with col1:
        nse_val = metrics.get('nse', 0)
        rating = "Very Good" if nse_val > 0.75 else "Good" if nse_val > 0.65 else "Satisfactory" if nse_val > 0.5 else "Unsatisfactory"
        st.metric("NSE", f"{nse_val:.4f}", help=f"Rating: {rating}")
    with col2:
        st.metric("KGE", f"{metrics.get('kge', 0):.4f}")
    with col3:
        st.metric("PBIAS", f"{metrics.get('pbias', 0):.2f}%")
    with col4:
        st.metric("RSR", f"{metrics.get('rsr', 0):.4f}")
    with col5:
        st.metric("R²", f"{metrics.get('r_squared', 0):.4f}")

# Rating interpretation
st.markdown("---")
with st.expander("📊 Performance Rating Guide (Moriasi et al., 2007)"):
    st.markdown("""
    | Metric | Very Good | Good | Satisfactory | Unsatisfactory |
    |--------|-----------|------|--------------|----------------|
    | NSE | > 0.75 | 0.65-0.75 | 0.50-0.65 | < 0.50 |
    | PBIAS (%) | < 10 | 10-15 | 15-25 | > 25 |
    | RSR | < 0.50 | 0.50-0.60 | 0.60-0.70 | > 0.70 |
    """)


# ---------------------------------------------------------------------------
# Before vs After Calibration Comparison
# ---------------------------------------------------------------------------
_baseline_results = st.session_state.get("baseline_results")
if _baseline_results:
    import matplotlib.pyplot as plt

    st.markdown("---")
    st.header("2. Before vs After Calibration")

    for _bl in _baseline_results:
        if not _bl.get("success"):
            continue

        _bl_rid = _bl.get("reach_id", "")
        _bl_sim = _bl.get("simulated")
        _bl_dates = _bl.get("dates")
        _bl_metrics = _bl.get("metrics", {})
        _bl_obs = _bl.get("observed")

        if _bl_sim is None or _bl_obs is None:
            continue

        # Find the matching calibrated data for this reach
        _cal_sim = None
        _cal_metrics = {}
        if (
            results_full is not None
            and hasattr(results_full, "site_results")
            and results_full.site_results
        ):
            for _sr in results_full.site_results:
                if _sr.get("reach_id") == _bl_rid:
                    _cal_sim = _sr.get("simulated")
                    _cal_metrics = _sr.get("metrics", {})
                    break
        elif (
            results_full is not None
            and is_sequential
        ):
            # Sequential results: find calibrated data from step results
            for _step in results_full.steps:
                if _step.reach_id == _bl_rid:
                    _step_result = getattr(_step, "result", None)
                    if (
                        _step_result is not None
                        and hasattr(_step_result, "simulated")
                        and len(getattr(_step_result, "simulated", [])) > 0
                    ):
                        _cal_sim = _step_result.simulated
                    _cal_metrics = _step.metrics or {}
                    break
        elif (
            results_full is not None
            and hasattr(results_full, "simulated")
        ):
            _cal_sim = results_full.simulated
            _cal_metrics = getattr(results_full, "metrics", metrics)

        st.subheader(f"Reach {_bl_rid}")

        # Metrics comparison table
        _metrics_compare = []
        for _mk in ["nse", "kge", "pbias", "rsr", "r_squared"]:
            _bv = _bl_metrics.get(_mk)
            _cv = _cal_metrics.get(_mk)
            if _bv is not None or _cv is not None:
                _bv_s = f"{_bv:.4f}" if _bv is not None else "N/A"
                _cv_s = f"{_cv:.4f}" if _cv is not None else "N/A"
                _delta = ""
                if _bv is not None and _cv is not None:
                    _diff = _cv - _bv
                    _delta = f"{_diff:+.4f}"
                _metrics_compare.append({
                    "Metric": _mk.upper(),
                    "Before (Baseline)": _bv_s,
                    "After (Calibrated)": _cv_s,
                    "Change": _delta,
                })
        if _metrics_compare:
            st.dataframe(pd.DataFrame(_metrics_compare), hide_index=True)

        # Overlay plot: observed, baseline, calibrated
        _x = pd.to_datetime(_bl_dates) if _bl_dates is not None else np.arange(len(_bl_obs))

        _cmp_obj_val_bl = _bl_metrics.get(objective_name, float("nan"))
        _cmp_obj_label = objective_name.upper()
        _cmp_fmt_bl = f"{_cmp_obj_val_bl:.2f}%" if objective_name == "pbias" else f"{_cmp_obj_val_bl:.3f}"

        fig_cmp, ax_cmp = plt.subplots(figsize=(14, 5))
        ax_cmp.plot(_x, _bl_obs, color="black", linewidth=1, label="Observed", alpha=0.9)
        ax_cmp.plot(
            _x, _bl_sim, color="red", linewidth=1, linestyle="--",
            label=f"Before ({_cmp_obj_label}={_cmp_fmt_bl})", alpha=0.6,
        )
        if _cal_sim is not None and len(_cal_sim) == len(_bl_obs):
            _cmp_obj_val_cal = _cal_metrics.get(objective_name, float("nan"))
            _cmp_fmt_cal = f"{_cmp_obj_val_cal:.2f}%" if objective_name == "pbias" else f"{_cmp_obj_val_cal:.3f}"
            ax_cmp.plot(
                _x, _cal_sim, color="blue", linewidth=1,
                label=f"After ({_cmp_obj_label}={_cmp_fmt_cal})", alpha=0.8,
            )
        ax_cmp.set_xlabel("Date" if _bl_dates is not None else "Time Step")
        ax_cmp.set_ylabel("Value")
        ax_cmp.set_title(f"Reach {_bl_rid} — Before vs After Calibration")
        ax_cmp.legend()
        ax_cmp.grid(True, alpha=0.3)
        plt.tight_layout()
        st.pyplot(fig_cmp)
        st.download_button(
            "Download Before vs After plot",
            data=_fig_to_png_bytes(fig_cmp),
            file_name=f"before_vs_after_reach_{_bl_rid}.png",
            mime="image/png",
            key=f"dl_bva_{_bl_rid}",
        )
        plt.close(fig_cmp)

    # Adjust section numbering for subsequent sections
    _next_section = 3
else:
    _next_section = 2

# ---------------------------------------------------------------------------
# Helper: build a list of site datasets for plotting
# Each entry: {reach_id, dates, observed, simulated, metrics}
# ---------------------------------------------------------------------------
# Simulated/observed arrays are pre-aligned upstream (date-keyed merge in
# spotpy_setup.py run_baseline_simulation / _extract_simulated_values).
# No raw RCH/MON join is performed here — results_full.simulated and
# results_full.observed are already time-indexed numpy arrays that correspond
# 1-to-1 with results_full.dates.
plot_sites = []

if is_sequential:
    # Check if steps have full result objects with observed/simulated data
    # (DiagnosticCalibrationResult stores these)
    for step in results_full.steps:
        _step_result = getattr(step, "result", None)
        if (
            _step_result is not None
            and hasattr(_step_result, "observed")
            and hasattr(_step_result, "simulated")
            and len(getattr(_step_result, "observed", [])) > 0
        ):
            plot_sites.append({
                "reach_id": step.reach_id,
                "dates": getattr(_step_result, "dates", None),
                "observed": _step_result.observed,
                "simulated": _step_result.simulated,
                "metrics": step.metrics or {},
            })

elif is_multisite:
    plot_sites = results_full.site_results

elif results_full is not None and hasattr(results_full, 'observed') and hasattr(results_full, 'simulated'):
    # Single-site CalibrationResult
    dates = getattr(results_full, 'dates', None)
    site_metrics = getattr(results_full, 'metrics', metrics)
    reach_id = getattr(results_full, "reach_id", None)
    if reach_id is None:
        reach_id = (
            st.session_state.get("calibration_reach_id")
            or st.session_state.get("single_reach_id")
            or st.session_state.get("reach_id")
        )
    if reach_id is None:
        _bl_list = st.session_state.get("baseline_results", [])
        reach_id = _bl_list[0].get("reach_id", 1) if _bl_list else 1
    plot_sites = [{
        "reach_id": reach_id,
        "dates": dates,
        "observed": results_full.observed,
        "simulated": results_full.simulated,
        "metrics": site_metrics,
    }]


# ---------------------------------------------------------------------------
# Visualization
# ---------------------------------------------------------------------------
st.markdown("---")
st.header(f"{_next_section}. Visualization")
_next_section += 1

if plot_sites:
    import matplotlib.pyplot as plt

    obj_label = objective_name.upper()

    # Detect WQ variable type for diagnostic dispatch
    _output_var = st.session_state.get("output_variable", "FLOW_OUTcms")
    _SEDIMENT_VARS = {"SED_OUTtons", "SED_CONmg/kg"}
    _NITROGEN_VARS = {"TOT_Nkg", "NO3_OUTkg", "ORGN_OUTkg"}
    _PHOSPHORUS_VARS = {"TOT_Pkg", "SOLP_OUTkg", "ORGP_OUTkg"}

    if _output_var in _SEDIMENT_VARS:
        _wq_type = "sediment"
    elif _output_var in _NITROGEN_VARS:
        _wq_type = "nitrogen"
    elif _output_var in _PHOSPHORUS_VARS:
        _wq_type = "phosphorus"
    else:
        _wq_type = "flow"

    # --- Debug info (collapsed by default) ---
    with st.expander("Debug: Data diagnostics"):
        for i, site_data in enumerate(plot_sites):
            obs_arr = np.asarray(site_data.get("observed", []), dtype=float)
            sim_arr = np.asarray(site_data.get("simulated", []), dtype=float)
            d_arr = site_data.get("dates")
            rid = site_data.get("reach_id", "?")

            st.markdown(f"**Site {i+1} (Reach {rid})**")
            st.text(
                f"  observed  : shape={obs_arr.shape}, dtype={obs_arr.dtype}, "
                f"min={np.nanmin(obs_arr):.4f}, max={np.nanmax(obs_arr):.4f}, "
                f"mean={np.nanmean(obs_arr):.4f}, NaN%={100*np.isnan(obs_arr).mean():.1f}"
            )
            st.text(
                f"  simulated : shape={sim_arr.shape}, dtype={sim_arr.dtype}, "
                f"min={np.nanmin(sim_arr) if not np.all(np.isnan(sim_arr)) else 'ALL NaN'}, "
                f"max={np.nanmax(sim_arr) if not np.all(np.isnan(sim_arr)) else 'ALL NaN'}, "
                f"NaN%={100*np.isnan(sim_arr).mean():.1f}"
            )
            if d_arr is not None:
                d_pd = pd.to_datetime(d_arr)
                st.text(f"  dates     : len={len(d_arr)}, from {d_pd.min()} to {d_pd.max()}")
            else:
                st.text("  dates     : None")
            st.text(f"  objective : {objective_name} (from {'CalibrationResult' if results_full is not None and hasattr(results_full, 'objective_name') else 'session_state'})")
            st.text(f"  metrics   : {site_data.get('metrics', {})}")

        st.caption(
            "If simulated is ALL NaN, the date merge likely failed. "
            "Restart Streamlit (`streamlit run ...`) to reload calibration modules after code changes."
        )

    _diag_tab_label = {
        "flow": "Diagnostics",
        "sediment": "Sediment Diagnostics",
        "phosphorus": "Phosphorus Diagnostics",
        "nitrogen": "Nitrogen Diagnostics",
    }.get(_wq_type, "Diagnostics")
    _tab_names = ["📈 Time Series", "🔵 Scatter Plot", "📉 Flow Duration", "📊 Residuals", f"🔍 {_diag_tab_label}"]
    if st.session_state.get("sensitivity_results") is not None:
        _tab_names.append("📊 Sensitivity")
    _all_tabs = st.tabs(_tab_names)
    tab1, tab2, tab3, tab4, tab_diag = _all_tabs[0], _all_tabs[1], _all_tabs[2], _all_tabs[3], _all_tabs[4]
    tab_sens = _all_tabs[5] if len(_all_tabs) > 5 else None

    with tab1:
        st.subheader("Observed vs Simulated Time Series")

        for site_data in plot_sites:
            observed = np.asarray(site_data["observed"], dtype=float)
            simulated = np.asarray(site_data["simulated"], dtype=float)
            dates = site_data.get("dates")
            site_metrics = site_data.get("metrics", {})
            reach_id = site_data.get("reach_id", "")

            obj_val = site_metrics.get(objective_name, site_metrics.get("nse", 0))

            # Warn if simulated is all NaN
            sim_all_nan = np.all(np.isnan(simulated))
            if sim_all_nan:
                st.warning(
                    f"Reach {reach_id}: Simulated data is all NaN (date merge may have failed). "
                    f"Please **restart the Streamlit app** and re-run calibration."
                )

            # Detect large scale mismatch (e.g. unit difference)
            obs_valid = observed[~np.isnan(observed)]
            sim_valid = simulated[~np.isnan(simulated)] if not sim_all_nan else np.array([])
            scale_mismatch = (
                not sim_all_nan
                and len(sim_valid) > 0
                and len(obs_valid) > 0
                and np.nanmax(obs_valid) > 0
                and np.nanmax(sim_valid) > 0
                and (
                    np.nanmax(obs_valid) / np.nanmax(sim_valid) > 10
                    or np.nanmax(sim_valid) / np.nanmax(obs_valid) > 10
                )
            )

            if scale_mismatch:
                ratio = np.nanmax(obs_valid) / np.nanmax(sim_valid)
                st.warning(
                    f"Reach {reach_id}: Large scale difference detected "
                    f"(observed max: {np.nanmax(obs_valid):.1f}, "
                    f"simulated max: {np.nanmax(sim_valid):.1f}, "
                    f"ratio: {ratio:.1f}x). "
                    f"This may indicate a **unit mismatch** (e.g. observed in cfs vs SWAT output in cms). "
                    f"Using dual y-axes to show both."
                )

            x_axis = pd.to_datetime(dates) if dates is not None else np.arange(len(observed))

            if scale_mismatch:
                # Dual y-axis plot when scales differ significantly
                fig, (ax_top, ax_bot) = plt.subplots(2, 1, figsize=(14, 8), sharex=True)

                ax_top.plot(x_axis, observed, color='blue', linewidth=1, label='Observed', alpha=0.8)
                if not sim_all_nan:
                    ax_top.plot(x_axis, simulated, color='red', linewidth=1, label='Simulated', alpha=0.7)
                ax_top.set_ylabel('Value')
                ax_top.set_title(f'Reach {reach_id} ({obj_label} = {obj_val:.3f})')
                ax_top.legend()
                ax_top.grid(True, alpha=0.3)

                # Separate subplot for simulated alone (visible at its own scale)
                ax_bot.plot(x_axis, simulated, color='red', linewidth=1, label='Simulated (own scale)', alpha=0.8)
                ax_bot.set_xlabel('Date' if dates is not None else 'Time Step')
                ax_bot.set_ylabel('Simulated Value')
                ax_bot.set_title(f'Simulated Only (max = {np.nanmax(sim_valid):.2f})')
                ax_bot.legend()
                ax_bot.grid(True, alpha=0.3)
            else:
                fig, ax_top = plt.subplots(figsize=(14, 5))
                ax_top.plot(x_axis, observed, color='blue', linewidth=1, label='Observed', alpha=0.8)
                if not sim_all_nan:
                    ax_top.plot(x_axis, simulated, color='red', linewidth=1, label='Simulated', alpha=0.7)
                ax_top.set_xlabel('Date' if dates is not None else 'Time Step')
                ax_top.set_ylabel('Value')
                ax_top.set_title(f'Reach {reach_id} ({obj_label} = {obj_val:.3f})')
                ax_top.legend()
                ax_top.grid(True, alpha=0.3)

            plt.tight_layout()
            st.pyplot(fig)
            st.download_button(
                "Download Time Series plot",
                data=_fig_to_png_bytes(fig),
                file_name=f"time_series_reach_{reach_id}.png",
                mime="image/png",
                key=f"dl_ts_{reach_id}",
            )
            plt.close(fig)

    with tab2:
        st.subheader("Observed vs Simulated Scatter Plot")

        for site_data in plot_sites:
            observed = np.asarray(site_data["observed"], dtype=float)
            simulated = np.asarray(site_data["simulated"], dtype=float)
            site_metrics = site_data.get("metrics", {})
            reach_id = site_data.get("reach_id", "")

            mask = ~(np.isnan(observed) | np.isnan(simulated))
            obs_clean = observed[mask]
            sim_clean = simulated[mask]

            if len(obs_clean) == 0:
                st.info(f"Reach {reach_id}: No valid paired data for scatter plot (simulated may be all NaN).")
                continue

            fig, ax = plt.subplots(figsize=(8, 8))
            ax.scatter(obs_clean, sim_clean, alpha=0.5, s=15)

            all_vals = np.concatenate([obs_clean, sim_clean])
            min_val, max_val = np.min(all_vals), np.max(all_vals)
            ax.plot([min_val, max_val], [min_val, max_val], 'k--', linewidth=1.5, label='1:1 Line')

            obj_val = site_metrics.get(objective_name, site_metrics.get("nse", 0))
            ax.set_xlabel('Observed')
            ax.set_ylabel('Simulated')
            ax.set_title(f'Reach {reach_id} - Scatter Plot ({obj_label} = {obj_val:.3f})')
            ax.legend()
            ax.grid(True, alpha=0.3)
            ax.set_aspect('equal', adjustable='box')
            plt.tight_layout()

            st.pyplot(fig)
            st.download_button(
                "Download Scatter Plot",
                data=_fig_to_png_bytes(fig),
                file_name=f"scatter_reach_{reach_id}.png",
                mime="image/png",
                key=f"dl_scatter_{reach_id}",
            )
            plt.close(fig)

    with tab3:
        st.subheader("Flow Duration Curves")

        for site_data in plot_sites:
            observed = np.asarray(site_data["observed"], dtype=float)
            simulated = np.asarray(site_data["simulated"], dtype=float)
            reach_id = site_data.get("reach_id", "")

            mask = ~(np.isnan(observed) | np.isnan(simulated))
            obs_clean = observed[mask]
            sim_clean = simulated[mask]

            if len(obs_clean) == 0:
                st.info(f"Reach {reach_id}: No valid paired data for flow duration curve.")
                continue

            obs_sorted = np.sort(obs_clean)[::-1]
            sim_sorted = np.sort(sim_clean)[::-1]
            n = len(obs_sorted)
            prob = (np.arange(1, n + 1)) / (n + 1) * 100

            fig, ax = plt.subplots(figsize=(10, 6))
            ax.plot(prob, obs_sorted, color='blue', linewidth=1.5, label='Observed')
            ax.plot(prob, sim_sorted, color='red', linewidth=1.5, label='Simulated', alpha=0.8)

            positive_obs = obs_sorted[obs_sorted > 0]
            if len(positive_obs) > 0 and np.min(positive_obs) > 0:
                ax.set_yscale('log')

            ax.set_xlabel('Exceedance Probability (%)')
            ax.set_ylabel('Value')
            ax.set_title(f'Reach {reach_id} - Flow Duration Curve')
            ax.set_xlim(0, 100)
            ax.legend()
            ax.grid(True, alpha=0.3)
            plt.tight_layout()

            st.pyplot(fig)
            st.download_button(
                "Download Flow Duration Curve",
                data=_fig_to_png_bytes(fig),
                file_name=f"flow_duration_reach_{reach_id}.png",
                mime="image/png",
                key=f"dl_fdc_{reach_id}",
            )
            plt.close(fig)

    with tab4:
        st.subheader("Residual Analysis")

        for site_data in plot_sites:
            observed = np.asarray(site_data["observed"], dtype=float)
            simulated = np.asarray(site_data["simulated"], dtype=float)
            reach_id = site_data.get("reach_id", "")

            mask = ~(np.isnan(observed) | np.isnan(simulated))
            obs_clean = observed[mask]
            sim_clean = simulated[mask]

            if len(obs_clean) == 0:
                st.info(f"Reach {reach_id}: No valid paired data for residual analysis.")
                continue

            residuals = sim_clean - obs_clean

            fig, axes = plt.subplots(1, 2, figsize=(12, 4))

            axes[0].hist(residuals, bins=30, edgecolor='black', alpha=0.7)
            axes[0].axvline(x=0, color='red', linestyle='--', linewidth=1)
            axes[0].axvline(x=np.mean(residuals), color='green', linestyle='-',
                           label=f'Mean: {np.mean(residuals):.2f}')
            axes[0].set_xlabel('Residual (Sim - Obs)')
            axes[0].set_ylabel('Frequency')
            axes[0].set_title(f'Reach {reach_id} - Residuals Distribution')
            axes[0].legend()
            axes[0].grid(True, alpha=0.3)

            axes[1].scatter(obs_clean, residuals, alpha=0.5, s=10)
            axes[1].axhline(y=0, color='red', linestyle='--', linewidth=1)
            axes[1].set_xlabel('Observed')
            axes[1].set_ylabel('Residual')
            axes[1].set_title(f'Reach {reach_id} - Residuals vs Observed')
            axes[1].grid(True, alpha=0.3)

            plt.tight_layout()
            st.pyplot(fig)
            st.download_button(
                "Download Residuals plot",
                data=_fig_to_png_bytes(fig),
                file_name=f"residuals_reach_{reach_id}.png",
                mime="image/png",
                key=f"dl_resid_{reach_id}",
            )
            plt.close(fig)

    # --- Diagnostics Tab ---
    with tab_diag:
        # Dispatch title and caption based on output variable type
        _diag_titles = {
            "flow": ("Hydrograph Diagnostic Analysis",
                     "Analyzes differences between observed and simulated flows to identify "
                     "specific model deficiencies and recommend parameter adjustments."),
            "sediment": ("Sediment Diagnostic Analysis",
                         "Analyzes sediment load patterns, rating curve behaviour, and event "
                         "partitioning to identify erosion and transport model deficiencies."),
            "phosphorus": ("Phosphorus Diagnostic Analysis",
                           "Analyzes phosphorus concentration/load patterns across flow regimes "
                           "to identify nutrient cycling and transport model deficiencies."),
            "nitrogen": ("Nitrogen Diagnostic Analysis",
                         "Analyzes nitrogen concentration/load patterns across flow regimes "
                         "to identify nutrient cycling and transport model deficiencies."),
        }
        _dt_title, _dt_caption = _diag_titles.get(_wq_type, _diag_titles["flow"])
        st.subheader(_dt_title)
        st.caption(_dt_caption)

        for site_data in plot_sites:
            observed = np.asarray(site_data["observed"], dtype=float)
            simulated = np.asarray(site_data["simulated"], dtype=float)
            dates = site_data.get("dates")
            reach_id = site_data.get("reach_id", "")

            # Skip if data is unusable
            mask = ~(np.isnan(observed) | np.isnan(simulated))
            if np.sum(mask) < 10:
                st.warning(f"Reach {reach_id}: insufficient valid data for diagnostics.")
                continue

            try:
                if _wq_type == "flow":
                    # --- Streamflow diagnostics (original behaviour) ---
                    from swat_modern.calibration.diagnostics import diagnose
                    from swat_modern.visualization.diagnostics import (
                        plot_baseflow_separation,
                        plot_peak_comparison,
                        plot_seasonal_bias,
                    )

                    dates_dt = pd.to_datetime(dates).values if dates is not None else None
                    report = diagnose(observed, simulated, dates_dt)

                    st.markdown(f"### Reach {reach_id}")

                    # Baseflow separation
                    if dates is not None:
                        _x = pd.to_datetime(dates)
                        _obs_clean = observed[mask]
                        _dates_clean = _x[mask] if len(_x) == len(observed) else _x[:len(_obs_clean)]

                        _bf_col1, _bf_col2 = st.columns(2)
                        with _bf_col1:
                            fig_bf_obs = plot_baseflow_separation(
                                _dates_clean, report.obs_baseflow,
                                report.obs_baseflow,  # will be overwritten below
                                title="Observed: Baseflow Separation",
                            )
                            # Re-plot correctly
                            plt.close(fig_bf_obs)
                            fig_bf_obs = plot_baseflow_separation(
                                _dates_clean,
                                observed[mask],
                                report.obs_baseflow,
                                title=f"Observed (BFI={report.bfi_observed:.3f})",
                            )
                            st.pyplot(fig_bf_obs)
                            plt.close(fig_bf_obs)
                        with _bf_col2:
                            fig_bf_sim = plot_baseflow_separation(
                                _dates_clean,
                                simulated[mask],
                                report.sim_baseflow,
                                title=f"Simulated (BFI={report.bfi_simulated:.3f})",
                            )
                            st.pyplot(fig_bf_sim)
                            plt.close(fig_bf_sim)

                    # Key metrics
                    _diag_col1, _diag_col2, _diag_col3, _diag_col4 = st.columns(4)
                    with _diag_col1:
                        st.metric("BFI Ratio (sim/obs)", f"{report.bfi_ratio:.3f}")
                    with _diag_col2:
                        _pmr = report.peak_comparison.get("peak_magnitude_ratio", float("nan"))
                        st.metric("Peak Mag Ratio", f"{_pmr:.2f}")
                    with _diag_col3:
                        _pte = report.peak_comparison.get("peak_timing_error_days", float("nan"))
                        st.metric("Peak Timing (days)", f"{_pte:+.1f}")
                    with _diag_col4:
                        _vpb = report.volume_metrics.get("total_pbias", float("nan"))
                        st.metric("Volume PBIAS", f"{_vpb:.1f}%")

                    # Seasonal bias
                    _seasonal = report.volume_metrics.get("seasonal_bias", {})
                    if _seasonal:
                        fig_season = plot_seasonal_bias(_seasonal, title=f"Reach {reach_id} — Seasonal Bias")
                        st.pyplot(fig_season)
                        plt.close(fig_season)

                    # Peak comparison
                    _pairs = report.peak_comparison.get("peak_pairs", [])
                    if _pairs and dates is not None:
                        fig_peaks = plot_peak_comparison(
                            _dates_clean, observed[mask], simulated[mask], _pairs,
                            title=f"Reach {reach_id} — Peak Comparison",
                        )
                        st.pyplot(fig_peaks)
                        plt.close(fig_peaks)

                    # Findings and recommendations
                    if report.findings:
                        st.markdown("**Diagnostic Findings:**")
                        for _f in report.findings:
                            st.markdown(f"- **[{_f.confidence.upper()}]** {_f.description}")

                        if report.recommendations:
                            st.markdown("**Parameter Recommendations:**")
                            _rec_rows = []
                            for _r in report.recommendations:
                                _arrow = "\u2191" if _r.direction == "increase" else "\u2193"
                                _rec_rows.append({
                                    "Parameter": _r.parameter,
                                    "Direction": f"{_arrow} {_r.direction}",
                                    "Reason": _r.reason,
                                    "Confidence": _r.confidence,
                                })
                            st.dataframe(pd.DataFrame(_rec_rows), hide_index=True, width="stretch")
                    else:
                        st.success("No significant diagnostic issues found. Model performance is good.")

                elif _wq_type == "sediment":
                    # --- Sediment diagnostics ---
                    from swat_modern.calibration.diagnostics import diagnose_sediment
                    from swat_modern.visualization.diagnostics import plot_seasonal_bias

                    report = diagnose_sediment(observed[mask], simulated[mask])

                    st.markdown(f"### Reach {reach_id}")

                    # Key metrics from overall_metrics
                    _om = report.overall_metrics
                    _diag_col1, _diag_col2, _diag_col3, _diag_col4 = st.columns(4)
                    with _diag_col1:
                        st.metric("NSE", f"{_om.get('nse', float('nan')):.4f}")
                    with _diag_col2:
                        st.metric("PBIAS", f"{_om.get('pbias', float('nan')):.1f}%")
                    with _diag_col3:
                        st.metric("KGE", f"{_om.get('kge', float('nan')):.4f}")
                    with _diag_col4:
                        st.metric("R\u00b2", f"{_om.get('r_squared', float('nan')):.4f}")

                    # Rating curve info (if flow data was available)
                    if report.rating_curve:
                        _rc = report.rating_curve
                        _rc_col1, _rc_col2, _rc_col3 = st.columns(3)
                        with _rc_col1:
                            st.metric("Obs Rating Slope", f"{_rc.get('obs_slope', float('nan')):.3f}")
                        with _rc_col2:
                            st.metric("Sim Rating Slope", f"{_rc.get('sim_slope', float('nan')):.3f}")
                        with _rc_col3:
                            st.metric("Slope Ratio", f"{_rc.get('slope_ratio', float('nan')):.3f}")

                        # Try to show rating curve plot (Worker-1)
                        try:
                            from swat_modern.visualization.diagnostics import plot_rating_curve
                            fig_rc = plot_rating_curve(
                                None, observed[mask], None, simulated[mask],
                                _rc, title=f"Reach {reach_id} — Rating Curve",
                            )
                            st.pyplot(fig_rc)
                            plt.close(fig_rc)
                        except (ImportError, TypeError):
                            pass

                    # Event partition info (if available)
                    if report.event_partition:
                        _ep = report.event_partition
                        _ep_col1, _ep_col2, _ep_col3 = st.columns(3)
                        with _ep_col1:
                            st.metric("Obs Event Frac", f"{_ep.get('obs_event_frac', float('nan')):.3f}")
                        with _ep_col2:
                            st.metric("Sim Event Frac", f"{_ep.get('sim_event_frac', float('nan')):.3f}")
                        with _ep_col3:
                            st.metric("Event Ratio", f"{_ep.get('event_ratio', float('nan')):.3f}")

                        # Try to show event partition plot (Worker-1)
                        try:
                            from swat_modern.visualization.diagnostics import plot_event_partition
                            fig_ep = plot_event_partition(
                                _ep, title=f"Reach {reach_id} — Event Partition",
                            )
                            st.pyplot(fig_ep)
                            plt.close(fig_ep)
                        except (ImportError, TypeError):
                            pass

                    # Seasonal bias
                    _seasonal = report.seasonal_bias
                    if _seasonal:
                        fig_season = plot_seasonal_bias(_seasonal, title=f"Reach {reach_id} — Seasonal Sediment Bias")
                        st.pyplot(fig_season)
                        plt.close(fig_season)

                    # Findings and recommendations
                    if report.findings:
                        st.markdown("**Diagnostic Findings:**")
                        for _f in report.findings:
                            st.markdown(f"- **[{_f.confidence.upper()}]** {_f.description}")

                        if report.recommendations:
                            st.markdown("**Parameter Recommendations:**")
                            _rec_rows = []
                            for _r in report.recommendations:
                                _arrow = "\u2191" if _r.direction == "increase" else "\u2193"
                                _rec_rows.append({
                                    "Parameter": _r.parameter,
                                    "Direction": f"{_arrow} {_r.direction}",
                                    "Reason": _r.reason,
                                    "Confidence": _r.confidence,
                                })
                            st.dataframe(pd.DataFrame(_rec_rows), hide_index=True, width="stretch")
                    else:
                        st.success("No significant sediment diagnostic issues found.")

                elif _wq_type == "phosphorus":
                    # --- Phosphorus diagnostics ---
                    from swat_modern.calibration.diagnostics import diagnose_phosphorus
                    from swat_modern.visualization.diagnostics import plot_seasonal_bias

                    report = diagnose_phosphorus(observed[mask], simulated[mask])

                    st.markdown(f"### Reach {reach_id}")

                    # Key metrics from overall_metrics
                    _om = report.overall_metrics
                    _diag_col1, _diag_col2, _diag_col3, _diag_col4 = st.columns(4)
                    with _diag_col1:
                        st.metric("NSE", f"{_om.get('nse', float('nan')):.4f}")
                    with _diag_col2:
                        st.metric("PBIAS", f"{_om.get('pbias', float('nan')):.1f}%")
                    with _diag_col3:
                        st.metric("KGE", f"{_om.get('kge', float('nan')):.4f}")
                    with _diag_col4:
                        st.metric("R\u00b2", f"{_om.get('r_squared', float('nan')):.4f}")

                    # Flow partition info (if available)
                    if report.flow_partition:
                        _fp = report.flow_partition
                        _fp_col1, _fp_col2 = st.columns(2)
                        with _fp_col1:
                            st.metric("High-Flow P Bias", f"{_fp.get('highflow_pbias', float('nan')):.1f}%")
                        with _fp_col2:
                            st.metric("Low-Flow P Bias", f"{_fp.get('lowflow_pbias', float('nan')):.1f}%")

                        # Try to show flow partition plot (Worker-1)
                        try:
                            from swat_modern.visualization.diagnostics import plot_flow_partition
                            fig_fp = plot_flow_partition(
                                _fp, title=f"Reach {reach_id} — Flow-Partitioned P Bias",
                            )
                            st.pyplot(fig_fp)
                            plt.close(fig_fp)
                        except (ImportError, TypeError):
                            pass

                    # Seasonal bias
                    _seasonal = report.seasonal_bias
                    if _seasonal:
                        fig_season = plot_seasonal_bias(_seasonal, title=f"Reach {reach_id} — Seasonal Phosphorus Bias")
                        st.pyplot(fig_season)
                        plt.close(fig_season)

                    # Findings and recommendations
                    if report.findings:
                        st.markdown("**Diagnostic Findings:**")
                        for _f in report.findings:
                            st.markdown(f"- **[{_f.confidence.upper()}]** {_f.description}")

                        if report.recommendations:
                            st.markdown("**Parameter Recommendations:**")
                            _rec_rows = []
                            for _r in report.recommendations:
                                _arrow = "\u2191" if _r.direction == "increase" else "\u2193"
                                _rec_rows.append({
                                    "Parameter": _r.parameter,
                                    "Direction": f"{_arrow} {_r.direction}",
                                    "Reason": _r.reason,
                                    "Confidence": _r.confidence,
                                })
                            st.dataframe(pd.DataFrame(_rec_rows), hide_index=True, width="stretch")
                    else:
                        st.success("No significant phosphorus diagnostic issues found.")

                elif _wq_type == "nitrogen":
                    # --- Nitrogen diagnostics ---
                    from swat_modern.visualization.diagnostics import plot_seasonal_bias

                    try:
                        from swat_modern.calibration.diagnostics import diagnose_nitrogen
                    except ImportError:
                        st.warning(
                            "Nitrogen diagnostic analysis is not yet available. "
                            "The `diagnose_nitrogen` function has not been implemented."
                        )
                        st.markdown("---")
                        continue

                    report = diagnose_nitrogen(observed[mask], simulated[mask])

                    st.markdown(f"### Reach {reach_id}")

                    # Key metrics from overall_metrics
                    _om = report.overall_metrics
                    _diag_col1, _diag_col2, _diag_col3, _diag_col4 = st.columns(4)
                    with _diag_col1:
                        st.metric("NSE", f"{_om.get('nse', float('nan')):.4f}")
                    with _diag_col2:
                        st.metric("PBIAS", f"{_om.get('pbias', float('nan')):.1f}%")
                    with _diag_col3:
                        st.metric("KGE", f"{_om.get('kge', float('nan')):.4f}")
                    with _diag_col4:
                        st.metric("R\u00b2", f"{_om.get('r_squared', float('nan')):.4f}")

                    # Flow partition info (if available)
                    if report.flow_partition:
                        _fp = report.flow_partition
                        _fp_col1, _fp_col2 = st.columns(2)
                        with _fp_col1:
                            st.metric("High-Flow N Bias", f"{_fp.get('highflow_pbias', float('nan')):.1f}%")
                        with _fp_col2:
                            st.metric("Low-Flow N Bias", f"{_fp.get('lowflow_pbias', float('nan')):.1f}%")

                        # Try to show flow partition plot (Worker-1)
                        try:
                            from swat_modern.visualization.diagnostics import plot_flow_partition
                            fig_fp = plot_flow_partition(
                                _fp, title=f"Reach {reach_id} — Flow-Partitioned N Bias",
                            )
                            st.pyplot(fig_fp)
                            plt.close(fig_fp)
                        except (ImportError, TypeError):
                            pass

                    # Seasonal bias
                    _seasonal = report.seasonal_bias
                    if _seasonal:
                        fig_season = plot_seasonal_bias(_seasonal, title=f"Reach {reach_id} — Seasonal Nitrogen Bias")
                        st.pyplot(fig_season)
                        plt.close(fig_season)

                    # Findings and recommendations
                    if report.findings:
                        st.markdown("**Diagnostic Findings:**")
                        for _f in report.findings:
                            st.markdown(f"- **[{_f.confidence.upper()}]** {_f.description}")

                        if report.recommendations:
                            st.markdown("**Parameter Recommendations:**")
                            _rec_rows = []
                            for _r in report.recommendations:
                                _arrow = "\u2191" if _r.direction == "increase" else "\u2193"
                                _rec_rows.append({
                                    "Parameter": _r.parameter,
                                    "Direction": f"{_arrow} {_r.direction}",
                                    "Reason": _r.reason,
                                    "Confidence": _r.confidence,
                                })
                            st.dataframe(pd.DataFrame(_rec_rows), hide_index=True, width="stretch")
                    else:
                        st.success("No significant nitrogen diagnostic issues found.")

                st.markdown("---")

            except Exception as _diag_err:
                st.error(f"Diagnostic analysis failed for reach {reach_id}: {_diag_err}")

    # --- Sensitivity Tab (if results available) ---
    if tab_sens is not None:
        with tab_sens:
            st.subheader("Parameter Sensitivity Analysis Results")
            _sa_res = st.session_state.get("sensitivity_results")
            if _sa_res is not None:
                try:
                    from swat_modern.visualization.sensitivity import (
                        plot_sensitivity_tornado,
                        sensitivity_ranking_table,
                    )

                    fig_sa = plot_sensitivity_tornado(_sa_res)
                    st.pyplot(fig_sa)
                    st.download_button(
                        "Download Sensitivity Plot",
                        data=_fig_to_png_bytes(fig_sa),
                        file_name="sensitivity_tornado.png",
                        mime="image/png",
                        key="dl_sensitivity",
                    )
                    plt.close(fig_sa)

                    st.markdown("### Ranking Table")
                    _sa_table = sensitivity_ranking_table(_sa_res)
                    st.dataframe(_sa_table, hide_index=True, width="stretch")
                except Exception as _sa_err:
                    st.error(f"Sensitivity visualization failed: {_sa_err}")

elif is_sequential:
    import matplotlib.pyplot as plt

    if not plot_sites:
        st.info(
            "Sequential calibration stores per-step metrics but not full time series. "
            "Re-run the model with calibrated parameters to generate detailed plots."
        )

else:
    st.info("Detailed visualization requires full calibration results. Run calibration with SPOTPY.")

# ---------------------------------------------------------------------------
# Sequential step details (shown regardless of whether plot_sites was populated)
# ---------------------------------------------------------------------------
# Ensure _wq_type is available even when plot_sites was empty
try:
    _wq_type  # noqa: B018 — check if already defined above
except NameError:
    _output_var = st.session_state.get("output_variable", "FLOW_OUTcms")
    _SEDIMENT_VARS = {"SED_OUTtons", "SED_CONmg/kg"}
    _NITROGEN_VARS = {"TOT_Nkg", "NO3_OUTkg", "ORGN_OUTkg"}
    _PHOSPHORUS_VARS = {"TOT_Pkg", "SOLP_OUTkg", "ORGP_OUTkg"}
    if _output_var in _SEDIMENT_VARS:
        _wq_type = "sediment"
    elif _output_var in _NITROGEN_VARS:
        _wq_type = "nitrogen"
    elif _output_var in _PHOSPHORUS_VARS:
        _wq_type = "phosphorus"
    else:
        _wq_type = "flow"

if is_sequential:
    import matplotlib.pyplot as plt

    seq_results = results_full

    # Overall metrics table
    st.subheader("Step-by-Step Metrics")
    metrics_df = seq_results.get_metrics_by_step()
    st.dataframe(metrics_df, hide_index=True, width="stretch")

    # Per-step diagnostic expanders
    st.subheader("Per-Step Diagnostics")
    for step in seq_results.steps:
        _diag = step.diagnostic_summary
        _step_label = (
            f"Step {step.step_number}: Reach {step.reach_id} "
            f"({len(step.subbasin_ids)} subbasins)"
        )

        # Add objective metric to the label if available
        if step.metrics:
            _obj_v = step.metrics.get(objective_name, None)
            if _obj_v is not None:
                _obj_fmt = f"{_obj_v:.2f}%" if objective_name == "pbias" else f"{_obj_v:.4f}"
                _step_label += f" — {objective_name.upper()}={_obj_fmt}"

        with st.expander(_step_label, expanded=(step.step_number == 1)):
            # Parameters calibrated at this step
            if step.best_params:
                st.markdown("**Parameters calibrated at this step:**")
                _param_rows = [
                    {"Parameter": k, "Value": f"{v:.6f}"}
                    for k, v in step.best_params.items()
                ]
                st.dataframe(
                    pd.DataFrame(_param_rows), hide_index=True,
                    width="stretch",
                )

            # Subbasins targeted
            st.markdown(
                f"**Subbasins modified:** {', '.join(str(s) for s in sorted(step.subbasin_ids))}"
            )
            if step.runtime > 0:
                st.markdown(f"**Runtime:** {step.runtime:.1f}s")

            # Diagnostic summary
            if _diag:
                st.markdown("---")
                st.markdown("**Diagnostic Summary:**")

                # Key diagnostic metrics — dispatch by output variable type
                _dc1, _dc2, _dc3, _dc4 = st.columns(4)
                if _wq_type == "flow":
                    with _dc1:
                        st.metric(
                            "BFI Ratio (sim/obs)",
                            f"{_diag.get('bfi_ratio', float('nan')):.3f}",
                        )
                    with _dc2:
                        st.metric(
                            "Peak Mag Ratio",
                            f"{_diag.get('peak_magnitude_ratio', float('nan')):.2f}",
                        )
                    with _dc3:
                        _pte = _diag.get("peak_timing_error", float("nan"))
                        st.metric("Peak Timing (days)", f"{_pte:+.1f}")
                    with _dc4:
                        st.metric(
                            "Volume PBIAS",
                            f"{_diag.get('total_pbias', float('nan')):.1f}%",
                        )
                elif _wq_type == "sediment":
                    with _dc1:
                        st.metric("NSE", f"{_diag.get('nse', float('nan')):.4f}")
                    with _dc2:
                        st.metric("PBIAS", f"{_diag.get('total_pbias', float('nan')):.1f}%")
                    with _dc3:
                        st.metric(
                            "Rating Slope Ratio",
                            f"{_diag.get('rating_slope_ratio', float('nan')):.3f}",
                        )
                    with _dc4:
                        st.metric(
                            "Event Sed Ratio",
                            f"{_diag.get('event_sed_ratio', float('nan')):.3f}",
                        )
                elif _wq_type == "phosphorus":
                    with _dc1:
                        st.metric("NSE", f"{_diag.get('nse', float('nan')):.4f}")
                    with _dc2:
                        st.metric("PBIAS", f"{_diag.get('total_pbias', float('nan')):.1f}%")
                    with _dc3:
                        st.metric(
                            "High-Flow P Bias",
                            f"{_diag.get('highflow_pbias', float('nan')):.1f}%",
                        )
                    with _dc4:
                        st.metric(
                            "Low-Flow P Bias",
                            f"{_diag.get('lowflow_pbias', float('nan')):.1f}%",
                        )
                elif _wq_type == "nitrogen":
                    with _dc1:
                        st.metric("NSE", f"{_diag.get('nse', float('nan')):.4f}")
                    with _dc2:
                        st.metric("PBIAS", f"{_diag.get('total_pbias', float('nan')):.1f}%")
                    with _dc3:
                        st.metric(
                            "High-Flow N Bias",
                            f"{_diag.get('highflow_pbias', float('nan')):.1f}%",
                        )
                    with _dc4:
                        st.metric(
                            "Low-Flow N Bias",
                            f"{_diag.get('lowflow_pbias', float('nan')):.1f}%",
                        )

                # Seasonal bias chart
                _season = _diag.get("seasonal_bias", {})
                if _season:
                    try:
                        from swat_modern.visualization.diagnostics import (
                            plot_seasonal_bias,
                        )
                        fig_sb = plot_seasonal_bias(
                            _season,
                            title=f"Step {step.step_number} — Seasonal Volume Bias",
                        )
                        st.pyplot(fig_sb)
                        plt.close(fig_sb)
                    except Exception:
                        # Fallback: show as simple table
                        st.dataframe(
                            pd.DataFrame([_season]).T.rename(
                                columns={0: "PBIAS (%)"}
                            ),
                            width="stretch",
                        )

                # Findings
                _fnames = _diag.get("finding_names", [])
                if _fnames:
                    st.markdown("**Findings:**")
                    for _fn in _fnames:
                        _fn_display = _fn.replace("_", " ").title()
                        st.markdown(f"- {_fn_display}")

                # Recommendations
                _recs = _diag.get("recommendations", [])
                if _recs:
                    st.markdown("**Parameter Recommendations:**")
                    _rec_rows = []
                    for _r in _recs:
                        _arrow = "\u2191" if _r["direction"] == "increase" else "\u2193"
                        _rec_rows.append({
                            "Parameter": _r["parameter"],
                            "Direction": f"{_arrow} {_r['direction']}",
                            "Reason": _r["reason"],
                        })
                    st.dataframe(
                        pd.DataFrame(_rec_rows), hide_index=True,
                        width="stretch",
                    )

                if not _fnames:
                    st.success("No significant diagnostic issues at this step.")
            else:
                st.caption("No diagnostic data available for this step.")

    # Locked parameters summary across all steps
    if seq_results.locked_parameters:
        st.subheader("Locked Parameters by Subbasin")
        st.markdown(
            "In sequential calibration, parameters are calibrated step-by-step "
            "from upstream to downstream. Once a step completes, its best "
            "parameter values are **locked** for those subbasins — they remain "
            "fixed while downstream subbasins are calibrated. This prevents "
            "downstream calibration from overriding upstream results. The table "
            "below shows each subbasin's locked parameter values."
        )
        _lock_rows = []
        for sub_id, params in sorted(seq_results.locked_parameters.items()):
            for pname, pval in params.items():
                _lock_rows.append({
                    "Subbasin": sub_id,
                    "Parameter": pname,
                    "Locked Value": f"{pval:.6f}",
                })
        st.dataframe(
            pd.DataFrame(_lock_rows), hide_index=True,
            width="stretch",
        )

# Best Parameters
st.markdown("---")
st.header(f"{_next_section}. Optimal Parameters")
_next_section += 1

if is_sequential and results_full is not None:
    from swat_modern.calibration.parameters import CALIBRATION_PARAMETERS, ParameterSet as _PS
    seq_results = results_full
    for step in seq_results.steps:
        if not step.best_params:
            continue
        _step_label = (
            f"Step {step.step_number}: Reach {step.reach_id} — "
            f"Subbasins: {', '.join(str(s) for s in sorted(step.subbasin_ids))}"
        )
        with st.expander(_step_label, expanded=True):
            _param_rows = []
            for k, v in step.best_params.items():
                _pdef = CALIBRATION_PARAMETERS.get(k.upper())
                if _pdef and _pdef.file_type in _PS.BASIN_WIDE_TYPES:
                    _scope = "Global (BSN)"
                else:
                    _ft = _pdef.file_type.upper() if _pdef else "?"
                    _scope = f"Per-Subbasin ({_ft})"
                _param_rows.append({"Parameter": k, "Optimal Value": f"{v:.6f}", "Scope": _scope})
            st.dataframe(pd.DataFrame(_param_rows), hide_index=True, use_container_width=True)
            st.caption(
                "**Per-Subbasin**: applied only to the listed subbasins (.hru/.sub/.rte etc.). "
                "**Global (BSN)**: applied basin-wide — downstream step's value takes effect."
            )
else:
    params_df = pd.DataFrame([
        {"Parameter": k, "Optimal Value": f"{v:.6f}"}
        for k, v in best_params.items()
    ])
    st.dataframe(params_df, width="stretch")

# Export section
st.markdown("---")
st.header(f"{_next_section}. Export Results")
_next_section += 1

export_col1, export_col2, export_col3 = st.columns(3)

with export_col1:
    st.subheader("📄 Parameters (JSON)")

    # Create JSON content
    export_data = {
        "best_parameters": best_params,
        "metrics": {k: float(v) if isinstance(v, (np.floating, float)) else v for k, v in metrics.items()},
        "timestamp": datetime.now().isoformat(),
        "project": st.session_state.get("project_path", "unknown"),
    }

    json_str = json.dumps(export_data, indent=2)

    st.download_button(
        label="⬇️ Download JSON",
        data=json_str,
        file_name="calibration_parameters.json",
        mime="application/json",
    )

with export_col2:
    st.subheader("📊 Metrics (CSV)")

    metrics_df = pd.DataFrame([
        {"Metric": k.upper(), "Value": v}
        for k, v in metrics.items()
    ])

    csv_str = metrics_df.to_csv(index=False)

    st.download_button(
        label="⬇️ Download CSV",
        data=csv_str,
        file_name="calibration_metrics.csv",
        mime="text/csv",
    )

with export_col3:
    st.subheader("📑 Full Report (TXT)")

    report_lines = [
        "=" * 60,
        "SWAT MODEL CALIBRATION REPORT",
        "=" * 60,
        "",
        f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"Project: {st.session_state.get('project_path', 'N/A')}",
        f"Calibration Runtime: {st.session_state.get('calibration_runtime', 'N/A')}s" if st.session_state.get('calibration_runtime') else "",
        "",
        "-" * 60,
        "PERFORMANCE METRICS",
        "-" * 60,
    ]

    for metric, value in metrics.items():
        report_lines.append(f"  {metric.upper():12s}: {value:.4f}")

    report_lines.extend([
        "",
        "-" * 60,
        "OPTIMAL PARAMETERS",
        "-" * 60,
    ])

    for param, value in best_params.items():
        report_lines.append(f"  {param:12s}: {value:.6f}")

    report_lines.extend([
        "",
        "=" * 60,
        "Generated by SWAT-DG Calibration Tool",
        "=" * 60,
    ])

    report_str = "\n".join(report_lines)

    st.download_button(
        label="⬇️ Download Report",
        data=report_str,
        file_name="calibration_report.txt",
        mime="text/plain",
    )

# Apply parameters to model
st.markdown("---")
st.header(f"{_next_section}. Apply Parameters to Model")
_next_section += 1

st.markdown(
    "A **new copy** of your TxtInOut folder will be created with the calibrated "
    "parameters applied. The original model remains unchanged."
)

_section_subs = st.session_state.get("section_subbasins")

# Fallback: if section_subbasins was not stored (calibration ran before the
# fix that persists it), recompute from fig.fig topology.  Only applies to
# single-site calibrations where the calibration reach is NOT the overall
# outlet (i.e. the upstream subbasin set is a proper subset of all subbasins).
if not _section_subs and not is_sequential:
    _reach_for_subs = (
        st.session_state.get("calibration_reach_id")
        or st.session_state.get("single_reach_id")
        or (getattr(results_full, "reach_id", None) if results_full else None)
    )
    if _reach_for_subs is not None:
        try:
            from swat_modern.io.parsers.fig_parser import FigFileParser
            _fig_path = Path(st.session_state.project_path) / "fig.fig"
            if _fig_path.exists():
                _parser = FigFileParser(str(_fig_path))
                _parser.parse()
                _all_subs = _parser.subbasins
                _ups = _parser.get_upstream_subbasins_by_subbasin(int(_reach_for_subs))
                # Only scope if genuinely partial (upstream subset < total)
                if _ups and len(_ups) < len(_all_subs):
                    _section_subs = sorted(_ups)
                    st.session_state["section_subbasins"] = _section_subs
        except Exception:
            pass

_is_partial_section = _section_subs is not None and len(_section_subs) > 0

if is_sequential and results_full is not None:
    st.info(
        "Each calibration step's parameters will be applied only to that step's subbasins "
        "(.hru, .sub, .rte, etc.). BSN (global) parameters use the downstream step's "
        "calibrated values."
    )
elif _is_partial_section:
    st.info(
        f"Parameters will be applied only to the **{len(_section_subs)} section subbasins** "
        f"({sorted(_section_subs)}). Locked upstream subbasins keep their original values."
    )

if st.button("Apply Best Parameters to Model", type="primary"):
    try:
        exe_path = st.session_state.get("swat_executable", "").strip() or None
        with st.spinner("Copying project and applying parameters..."):
            if is_sequential and results_full is not None:
                dest_dir, modified_count = _apply_sequential_params_to_copy(
                    st.session_state.project_path, results_full.steps, exe_path,
                )
            elif _is_partial_section:
                dest_dir, modified_count = _apply_partial_section_params_to_copy(
                    st.session_state.project_path, best_params,
                    _section_subs, exe_path,
                )
            else:
                dest_dir, modified_count = _apply_params_to_copy(
                    st.session_state.project_path, best_params, exe_path,
                )
        st.success(
            f"{modified_count} parameters applied to a new copy!\n\n"
            f"**Calibrated project:** `{dest_dir}`\n\n"
            f"The original model is unchanged."
        )
    except Exception as e:
        st.error(f"Error applying parameters: {e}")
        st.info("You may need to apply parameters manually using the exported JSON file.")

# Navigation
st.markdown("---")
st.markdown("""
**What's Next?**
- Open the calibrated project folder and run a simulation to verify results
- Export parameters and apply to other SWAT projects
- Re-run calibration with different parameters if needed
""")
