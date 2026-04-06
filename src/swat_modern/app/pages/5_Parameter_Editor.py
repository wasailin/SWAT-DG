"""
Parameter Editor Page - View current parameter values and customize calibration boundaries.

Allows users to:
- Read current parameter values from the loaded SWAT project
- Enable/disable parameters for calibration
- Customize min/max boundaries
- Batch operations by parameter group
- Save/load boundary configurations
"""

import streamlit as st
import pandas as pd
from pathlib import Path
from swat_modern.app.session_persistence import load_session, clear_session, get_param_mtime
from swat_modern.app.loading_utils import hide_deploy_button

st.set_page_config(page_title="Parameter Editor", page_icon="🔧", layout="wide")
hide_deploy_button()

# Restore session state on page load (survives browser refresh)
load_session(st.session_state)

st.title("Parameter Editor")
st.markdown("View current parameter values and customize calibration boundaries.")

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

from swat_modern.calibration.boundary_manager import BoundaryManager
from swat_modern.calibration.parameters import CALIBRATION_PARAMETERS, PARAMETER_GROUPS


# -------------------------------------------------------------------------
# Cached parameter reading (survives page switches & browser refresh)
# -------------------------------------------------------------------------
@st.cache_data(show_spinner="Reading parameter values from project files...")
def _load_project_parameters(project_path: str, param_mtime: float) -> pd.DataFrame:
    """Read all calibration parameters from SWAT project files (cached).

    ``param_mtime`` is a cache-busting key — when parameter files are
    modified on disk (e.g. by calibration), the mtime changes and
    Streamlit re-reads the files automatically.
    """
    from swat_modern.io.parsers.parameter_reader import ProjectParameterReader

    reader = ProjectParameterReader(project_path)
    return reader.read_all_parameters()


def _format_current_value(row) -> str:
    """Format current value: single value or min ~ max range."""
    if row["current_count"] == 0:
        return "N/A"
    if row["current_count"] == 1 or row["current_min"] == row["current_max"]:
        return f"{row['current_mean']:.4f}"
    return f"{row['current_min']:.4f} ~ {row['current_max']:.4f}"


st.markdown("---")

# -------------------------------------------------------------------------
# Initialize boundary manager in session state
# -------------------------------------------------------------------------
if "boundary_manager" not in st.session_state:
    st.session_state.boundary_manager = BoundaryManager()

manager: BoundaryManager = st.session_state.boundary_manager

# -------------------------------------------------------------------------
# Section 1: Current Project Parameters (auto-loaded with cache)
# -------------------------------------------------------------------------
st.header("1. Current Project Parameters")

if st.button("Refresh Parameters from Project"):
    _load_project_parameters.clear()
    st.rerun()

# Auto-load parameters (cached — instant after first load)
param_df = None
try:
    param_df = _load_project_parameters(
        st.session_state.project_path,
        get_param_mtime(st.session_state.project_path),
    )
    st.session_state.project_parameters = param_df
except Exception as e:
    st.error(f"Error reading parameters: {e}")
    with st.expander("Details"):
        st.exception(e)

if param_df is not None:
    # Show summary of parameters with current values
    has_values = param_df[param_df["current_count"] > 0]
    no_values = param_df[param_df["current_count"] == 0]

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Total Parameters", len(param_df))
    with col2:
        st.metric("With Current Values", len(has_values))
    with col3:
        st.metric("Not Found in Files", len(no_values))

    with st.expander("View Current Parameter Values"):
        view_df = param_df.copy()
        view_df["current_value"] = view_df.apply(_format_current_value, axis=1)

        display_cols = [
            "name", "group", "description", "current_value",
            "default_min", "default_max", "method", "units",
        ]
        available_cols = [c for c in display_cols if c in view_df.columns]

        column_config_view = {
            "current_value": st.column_config.TextColumn(
                "Current Value (Range)",
                help="Single value for basin-wide params; min ~ max for spatially-varying params",
            ),
        }

        st.dataframe(
            view_df[available_cols],
            column_config=column_config_view,
            width="stretch",
            hide_index=True,
        )

# -------------------------------------------------------------------------
# Section 2: Sidebar - Group Filters & Batch Operations
# -------------------------------------------------------------------------
with st.sidebar:
    st.markdown("### Parameter Groups")

    # Group filter
    all_groups = sorted(PARAMETER_GROUPS.keys())
    selected_groups = st.multiselect(
        "Filter by group",
        options=all_groups,
        default=all_groups,
        help="Show only parameters from selected groups",
    )

    st.markdown("---")
    st.markdown("### Batch Operations")

    batch_group = st.selectbox(
        "Select group for batch ops",
        options=["(none)"] + all_groups,
    )

    if batch_group != "(none)":
        bcol1, bcol2 = st.columns(2)
        with bcol1:
            if st.button("Enable Group"):
                manager.batch_set_group(batch_group, enabled=True)
                st.rerun()
        with bcol2:
            if st.button("Disable Group"):
                manager.batch_set_group(batch_group, enabled=False)
                st.rerun()

    st.markdown("---")
    st.markdown("### Quick Selection")

    if st.button("Recommended (4)"):
        for name in CALIBRATION_PARAMETERS:
            manager.enable_parameter(name, False)
        for name in ["CN2", "ESCO", "GW_DELAY", "ALPHA_BF"]:
            manager.enable_parameter(name, True)
        st.rerun()

    if st.button("Hydrology Focus (6)"):
        for name in CALIBRATION_PARAMETERS:
            manager.enable_parameter(name, False)
        for name in ["CN2", "ESCO", "EPCO", "SURLAG", "GW_DELAY", "ALPHA_BF"]:
            manager.enable_parameter(name, True)
        st.rerun()

    if st.button("Select All"):
        for name in CALIBRATION_PARAMETERS:
            manager.enable_parameter(name, True)
        st.rerun()

    if st.button("Clear All"):
        for name in CALIBRATION_PARAMETERS:
            manager.enable_parameter(name, False)
        st.rerun()

# -------------------------------------------------------------------------
# Section 3: Interactive Parameter Table
# -------------------------------------------------------------------------
st.markdown("---")
st.header("2. Calibration Boundaries")

st.markdown(
    f"**{len(manager.enabled_parameters)} parameters enabled** for calibration. "
    "Edit the table below to customize boundaries."
)

# Build the editable DataFrame
summary_df = manager.get_summary_dataframe()

# Filter by selected groups
if selected_groups:
    summary_df = summary_df[summary_df["group"].isin(selected_groups)].reset_index(drop=True)

if len(summary_df) == 0:
    st.info("No parameters match the current group filter.")
else:
    # Merge current project values if available (with range info)
    if "project_parameters" in st.session_state:
        proj_df = st.session_state.project_parameters[
            ["name", "current_mean", "current_min", "current_max", "current_count"]
        ].copy()
        proj_df["current_range"] = proj_df.apply(_format_current_value, axis=1)
        summary_df = summary_df.merge(
            proj_df[["name", "current_range"]], on="name", how="left"
        )
    else:
        summary_df["current_range"] = None

    # Prepare columns for data_editor
    display_df = summary_df[[
        "enabled", "name", "group", "description",
        "current_range", "default_min", "default_max",
        "custom_min", "custom_max", "method", "units",
    ]].copy()

    # Column configuration for st.data_editor
    column_config = {
        "enabled": st.column_config.CheckboxColumn(
            "Enable",
            help="Enable this parameter for calibration",
            width="small",
        ),
        "name": st.column_config.TextColumn(
            "Parameter",
            width="small",
            disabled=True,
        ),
        "group": st.column_config.TextColumn(
            "Group",
            width="small",
            disabled=True,
        ),
        "description": st.column_config.TextColumn(
            "Description",
            width="medium",
            disabled=True,
        ),
        "current_range": st.column_config.TextColumn(
            "Current Value",
            help="Single value or min ~ max range across HRUs/subbasins",
            width="small",
            disabled=True,
        ),
        "default_min": st.column_config.NumberColumn(
            "Default Min",
            format="%.4f",
            disabled=True,
        ),
        "default_max": st.column_config.NumberColumn(
            "Default Max",
            format="%.4f",
            disabled=True,
        ),
        "custom_min": st.column_config.NumberColumn(
            "Custom Min",
            help="Override minimum bound (leave empty for default)",
            format="%.4f",
        ),
        "custom_max": st.column_config.NumberColumn(
            "Custom Max",
            help="Override maximum bound (leave empty for default)",
            format="%.4f",
        ),
        "method": st.column_config.TextColumn(
            "Method",
            width="small",
            disabled=True,
        ),
        "units": st.column_config.TextColumn(
            "Units",
            width="small",
            disabled=True,
        ),
    }

    edited_df = st.data_editor(
        display_df,
        column_config=column_config,
        width="stretch",
        hide_index=True,
        num_rows="fixed",
        key="param_editor",
    )

    # Apply edits back to BoundaryManager
    if edited_df is not None:
        for _, row in edited_df.iterrows():
            name = row["name"]
            manager.enable_parameter(name, bool(row["enabled"]))

            # Update custom bounds
            custom_min = row["custom_min"] if pd.notna(row["custom_min"]) else None
            custom_max = row["custom_max"] if pd.notna(row["custom_max"]) else None

            boundary = manager.get_boundary(name)
            boundary.custom_min = custom_min
            boundary.custom_max = custom_max

# -------------------------------------------------------------------------
# Section 4: Save / Load Boundaries
# -------------------------------------------------------------------------
st.markdown("---")
st.header("3. Save / Load Configuration")

save_col, load_col = st.columns(2)

with save_col:
    st.markdown("**Save Boundaries**")

    json_str = manager.to_json()

    st.download_button(
        label="Download Boundaries (JSON)",
        data=json_str,
        file_name="calibration_boundaries.json",
        mime="application/json",
    )

    # Also save to project directory
    if st.button("Save to Project Folder"):
        try:
            save_path = Path(st.session_state.project_path) / "calibration_boundaries.json"
            manager.to_json(str(save_path))
            st.success(f"Saved to {save_path.name}")
        except Exception as e:
            st.error(f"Error saving: {e}")

with load_col:
    st.markdown("**Load Boundaries**")

    uploaded_json = st.file_uploader(
        "Upload boundaries JSON",
        type=["json"],
        help="Load a previously saved boundary configuration",
    )

    if uploaded_json is not None:
        try:
            json_content = uploaded_json.read().decode("utf-8")
            loaded_manager = BoundaryManager.from_json(json_content)
            st.session_state.boundary_manager = loaded_manager
            st.success(f"Loaded boundaries: {len(loaded_manager.enabled_parameters)} enabled")
            st.rerun()
        except Exception as e:
            st.error(f"Error loading boundaries: {e}")

    # Load from project directory
    project_json = Path(st.session_state.project_path) / "calibration_boundaries.json"
    if project_json.exists():
        if st.button("Load from Project Folder"):
            try:
                loaded_manager = BoundaryManager.from_json(str(project_json))
                st.session_state.boundary_manager = loaded_manager
                st.success(f"Loaded {len(loaded_manager.enabled_parameters)} enabled parameters")
                st.rerun()
            except Exception as e:
                st.error(f"Error loading: {e}")

# -------------------------------------------------------------------------
# Section 5: Apply to Calibration
# -------------------------------------------------------------------------
st.markdown("---")
st.header("4. Apply to Calibration")

n_enabled = len(manager.enabled_parameters)

if n_enabled == 0:
    st.warning("No parameters enabled. Enable at least one parameter above.")
else:
    st.info(
        f"**{n_enabled} parameters** will be used for calibration: "
        f"{', '.join(manager.enabled_parameters)}"
    )

    # Show effective bounds summary
    with st.expander("View Effective Bounds"):
        rows = []
        for name in manager.enabled_parameters:
            b = manager.get_boundary(name)
            rows.append({
                "Parameter": name,
                "Min": b.effective_min,
                "Max": b.effective_max,
                "Custom Min": b.custom_min,
                "Custom Max": b.custom_max,
            })
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)

    if st.button("Apply Boundaries to Calibration", type="primary"):
        st.session_state.boundary_manager = manager
        st.session_state.selected_params = manager.enabled_parameters
        st.success(
            f"Boundaries applied. {n_enabled} parameters ready for calibration."
        )
        st.info("Go to **Calibration** page to run auto-calibration with these boundaries.")

# -------------------------------------------------------------------------
# AI Suggestion Placeholder
# -------------------------------------------------------------------------
st.markdown("---")
with st.expander("AI-Assisted Boundary Suggestions (Coming Soon)"):
    st.markdown("""
    **Future Feature:** AI-assisted parameter boundary suggestions based on:
    - Watershed area and characteristics
    - Dominant land use and soil type
    - Climate classification
    - Literature values from similar watersheds

    This feature will use machine learning models trained on successful
    calibrations from hundreds of SWAT studies to suggest narrower,
    more appropriate parameter ranges for your specific watershed.
    """)

    st.button("Suggest Boundaries", disabled=True, help="This feature is under development")

# Navigation
st.markdown("---")
st.markdown("""
**Next Step:** Go to **Calibration** to run auto-calibration with your custom boundaries.
""")
