"""
SWAT-DG Calibration App - Main Entry Point.

A user-friendly web interface for SWAT model calibration.
Runs 100% locally - all data stays on your computer.

Launch:
    streamlit run src/swat_modern/app/main.py
"""

import streamlit as st
from pathlib import Path
from swat_modern.app.session_persistence import load_session, save_session, clear_session

try:
    from swat_modern.app.loading_utils import inject_shimmer_css, hide_deploy_button
except ImportError:
    def inject_shimmer_css(): pass
    def hide_deploy_button(): pass

def main():
    """Main application entry point."""
    inject_shimmer_css()

    # Sidebar - Project info
    with st.sidebar:
        st.image("https://upload.wikimedia.org/wikipedia/commons/thumb/a/a3/Water_drop.svg/200px-Water_drop.svg.png", width=80)
        st.title("SWAT-DG")
        st.markdown("**Calibration Tool**")
        st.markdown("---")

        # Session state info
        if "project_path" in st.session_state:
            st.success(f"Project: {Path(st.session_state.project_path).name}")

            # Exit Project button
            if st.button("Exit Project", type="secondary", width="stretch"):
                clear_session(st.session_state)
                st.rerun()
        else:
            st.info("No project loaded")

        if "shapefile_paths" in st.session_state:
            st.success("Shapefiles detected")

        if "observed_data" in st.session_state:
            st.success("Observation data loaded")

        if "boundary_manager" in st.session_state:
            n_enabled = len(st.session_state.boundary_manager.enabled_parameters)
            if n_enabled > 0:
                st.success(f"Boundaries: {n_enabled} params")

        if "calibration_result" in st.session_state:
            nse = st.session_state.calibration_result.get("nse", 0)
            st.success(f"Calibrated (NSE={nse:.3f})")

        st.markdown("---")
        st.markdown("### Quick Links")
        st.markdown("""
        - [SWAT Documentation](https://swat.tamu.edu/docs/)
        - [GitHub](https://github.com/wasailin/SWAT-DG)
        - [Lynxce](https://www.lynxce-env.com/)
        """)

        st.markdown("---")
        st.caption("Runs 100% locally")
        st.caption("All data stays on your computer")

    # Main content
    st.title("SWAT-DG: Diagnostic-Guided SWAT Calibration")

    st.markdown("""
    **SWAT-DG** calibrates SWAT models by analyzing *what is wrong* with your simulation before
    adjusting parameters — rather than blindly searching a high-dimensional parameter space.
    The result: calibrated parameters in **5–50 model runs** instead of thousands.
    """)

    st.info(
        "**Diagnostic-Guided Calibration** decomposes hydrograph deficiencies "
        "(baseflow index, peak flow bias, FDC shape, volume balance) into targeted parameter "
        "recommendations, then applies them iteratively until performance targets are met.",
        icon="🔬",
    )

    st.markdown("""
    Beyond the diagnostic engine, SWAT-DG also provides:

    - **Ensemble Diagnostic Calibration** — multiple independent diagnostic runs in parallel, returns the best result
    - **Phased Calibration** — sequential hydrology → sediment → nutrients workflow
    - **Multi-constituent WQ Calibration** — sediment, nitrogen, and phosphorus loads
    - **Traditional algorithms** (SCE-UA, DREAM, LHS, Monte Carlo) for comparison or fine-tuning
    - **Interactive watershed map** — visualize subbasins, streams, and simulation output spatially
    - **USGS NWIS integration** — fetch observed streamflow directly, or upload CSV/Excel
    - **Parameter boundary editor** — customize search ranges by parameter group
    - **Session persistence** — reopen the app and continue where you left off

    ---
    """)

    # Getting Started section
    st.header("Workflow")

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("""
        ### Step 1: Load Your Project
        Navigate to **Project Setup** in the sidebar to:
        - Browse to your SWAT `TxtInOut` folder
        - Verify `file.cio` is detected
        - Select the SWAT executable to use
        - Review project dates, subbasins, and routing
        """)

        st.markdown("""
        ### Step 2: View Watershed Map
        In **Watershed Map**:
        - Visualize subbasins, stream network, and watershed boundary
        - Click subbasins to inspect attributes
        - Overlay simulation output as a spatial heatmap
        """)

        st.markdown("""
        ### Step 3: Browse Simulation Results
        In **Simulation Results**:
        - Interactive time series for streamflow, sediment, N, P
        - Compare subbasins or outlets
        - Spatial summaries and accumulated flow at any gauge point
        """)

    with col2:
        st.markdown("""
        ### Step 4: Load Observation Data
        In **Observation Data**:
        - Upload CSV, Excel, or tab-delimited gauge records
        - Fetch daily/monthly streamflow from **USGS NWIS** by station ID
        - Auto-detect date columns and units
        """)

        st.markdown("""
        ### Step 5: Review Parameter Boundaries
        In **Parameter Editor**:
        - See default search ranges for every SWAT parameter
        - Enable/disable individual parameters or entire groups
        - Adjust min/max bounds based on local knowledge
        """)

        st.markdown("""
        ### Steps 6–7: Calibrate & Review Diagnostics
        In **Calibration** and **Results**:
        - **Choose Diagnostic-Guided** for physics-based, fast calibration (5–50 runs)
        - Or choose Ensemble, Phased, or a traditional optimizer
        - Review diagnostic findings: baseflow index, peak bias, FDC metrics, KGE decomposition
        - Inspect per-parameter recommendations with confidence levels
        - Export optimized parameters and performance reports
        """)

    st.markdown("---")

    # Status overview
    st.header("Current Session Status")

    status_cols = st.columns(7)

    with status_cols[0]:
        if "project_path" in st.session_state:
            st.metric("Project", "Loaded")
        else:
            st.metric("Project", "Not loaded")

    with status_cols[1]:
        if "shapefile_paths" in st.session_state:
            st.metric("Map", "Ready")
        else:
            st.metric("Map", "No shapes")

    with status_cols[2]:
        project_path = st.session_state.get("project_path")
        if project_path:
            has_rch = (Path(project_path) / "output.rch").exists()
            st.metric("Results", "Available" if has_rch else "No output")
        else:
            st.metric("Results", "---")

    with status_cols[3]:
        if "observed_data" in st.session_state:
            n_obs = len(st.session_state.observed_data)
            st.metric("Observations", f"{n_obs} pts")
        else:
            st.metric("Observations", "Not loaded")

    with status_cols[4]:
        if "boundary_manager" in st.session_state:
            n = len(st.session_state.boundary_manager.enabled_parameters)
            st.metric("Boundaries", f"{n} params" if n > 0 else "Default")
        else:
            st.metric("Boundaries", "Default")

    with status_cols[5]:
        if "calibration_result" in st.session_state:
            nse = st.session_state.calibration_result.get("nse", 0)
            st.metric("Calibration", f"NSE={nse:.3f}")
        else:
            st.metric("Calibration", "Not run")

    with status_cols[6]:
        if "best_parameters" in st.session_state:
            n_params = len(st.session_state.best_parameters)
            st.metric("Parameters", f"{n_params} optimized")
        else:
            st.metric("Parameters", "Default")

    st.markdown("---")

    # Quick tips
    with st.expander("Tips for Better Calibration"):
        st.markdown("""
        **Recommended: Use Diagnostic-Guided Calibration first**
        - Requires only **5–50 model runs** (vs. thousands for traditional methods)
        - Analyzes baseflow index, peak flow bias, FDC shape (FHV/FMS/FLV), and KGE components
        - Produces targeted recommendations: which parameter to adjust, by how much, and why
        - Use **Diagnostic Ensemble** for more robust results when runtime allows (runs several diagnostics in parallel and picks the best)

        **When to use traditional algorithms instead:**
        - Post-diagnostic fine-tuning with SCE-UA (global optimizer, good convergence)
        - Uncertainty quantification: DREAM (generates posterior parameter distributions)
        - Exploratory sensitivity analysis: Monte Carlo or LHS (random/stratified sampling)
        - Traditional iteration budget: quick test 500–1000; standard 5000–10000; thorough 20000+

        **Parameter groups (for manual boundary editing):**
        - **Hydrology**: CN2, ESCO, SOL_AWC, GW_DELAY, ALPHA_BF, GWQMN, RCHRG_DP
        - **Sediment**: USLE_K, USLE_P, CH_EROD, SPCON, SPEXP
        - **Nutrients**: CDN, SDNCO, ERORGN, ERORGP, BIOMIX

        **Performance targets (Moriasi et al., 2007):**
        - NSE > 0.50: Satisfactory | NSE > 0.65: Good | NSE > 0.75: Very Good
        - PBIAS ±25%: Satisfactory (streamflow) | KGE > 0.50: Satisfactory
        """)

    # Footer
    st.markdown("---")
    st.markdown("""
    <div style='text-align: center; color: gray;'>
        SWAT-DG v0.6.0 | All data processed locally |
        <a href='https://github.com/wasailin/SWAT-DG'>GitHub</a> |
        <a href='https://www.lynxce-env.com/'>Lynxce</a>
    </div>
    """, unsafe_allow_html=True)


if __name__ == "__main__":
    # All Streamlit initialization must be inside this guard.
    # On Windows, multiprocessing.spawn re-executes main.py with
    # __name__ == "__mp_main__"; module-level st.* calls would crash
    # because the Streamlit runtime context doesn't exist in workers.

    # Page configuration
    st.set_page_config(
        page_title="SWAT-DG - Calibration Tool",
        page_icon="💧",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    hide_deploy_button()

    # Restore session state on page load (survives browser refresh)
    load_session(st.session_state)

    # Re-initialize model object if project_path was restored but model is missing
    if "project_path" in st.session_state and "model" not in st.session_state:
        with st.status("Restoring session...", expanded=False) as _restore_status:
            try:
                from swat_modern import SWATModel
                _project_dir = Path(st.session_state.project_path)
                if _project_dir.exists() and (_project_dir / "file.cio").exists():
                    st.write("Reloading project configuration...")
                    _exe = st.session_state.get("swat_exe")
                    st.session_state.model = SWATModel(
                        str(_project_dir), executable=_exe if _exe else None
                    )
                    _restore_status.update(
                        label=f"Session restored — {_project_dir.name}",
                        state="complete",
                        expanded=False,
                    )
                else:
                    _restore_status.update(
                        label="Session restore skipped", state="complete"
                    )
            except Exception:
                _restore_status.update(
                    label="Session restore failed", state="error"
                )

    main()
