"""
Project Setup Page - Load and configure SWAT project.
"""

import streamlit as st
from pathlib import Path
from collections import defaultdict
import subprocess
import os

from swat_modern.app.session_persistence import (
    load_session, save_session, clear_session, browse_folder
)

try:
    from swat_modern.app.loading_utils import inject_shimmer_css, hide_deploy_button
except ImportError:
    def inject_shimmer_css(): pass
    def hide_deploy_button(): pass

st.set_page_config(page_title="Project Setup", page_icon="📁", layout="wide")
hide_deploy_button()

# Restore session state on page load (survives browser refresh)
load_session(st.session_state)
inject_shimmer_css()


def _open_in_editor(filepath: str):
    """Open a file in the system's default text editor."""
    try:
        if os.name == "nt":
            # Windows: try Notepad++ first, then fall back to notepad
            npp_paths = [
                r"C:\Program Files\Notepad++\notepad++.exe",
                r"C:\Program Files (x86)\Notepad++\notepad++.exe",
            ]
            for npp in npp_paths:
                if Path(npp).exists():
                    subprocess.Popen([npp, filepath])
                    return
            # Fall back to default associated program
            os.startfile(filepath)
        else:
            # macOS / Linux
            subprocess.Popen(["xdg-open", filepath])
    except Exception:
        pass


def _find_swat_exe(project_dir: Path):
    """Search for SWAT executable in common locations."""
    candidates = [
        project_dir / "swat.exe",
        project_dir / "swat2012.exe",
        project_dir / "SWAT_64rel.exe",
        project_dir / "rev681_64rel.exe",
        project_dir / "SWAT_Rev681.exe",
        project_dir.parent / "swat2012.exe",
        project_dir.parent / "SWAT_Rev681.exe",
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


# Re-initialize model object if project_path was restored but model is missing
if "project_path" in st.session_state and "model" not in st.session_state:
    try:
        from swat_modern import SWATModel
        _project_dir = Path(st.session_state.project_path)
        if _project_dir.exists() and (_project_dir / "file.cio").exists():
            _exe = st.session_state.get("swat_exe") or _find_swat_exe(_project_dir)
            _exe_arg = str(_exe) if _exe else None
            st.session_state.model = SWATModel(str(_project_dir), executable=_exe_arg)
    except Exception:
        pass

st.title("📁 Project Setup")
st.markdown("Load your SWAT project folder and verify configuration.")

# -- Sidebar: Exit Project button --
with st.sidebar:
    if "project_path" in st.session_state:
        if st.button("Exit Project", type="secondary", width="stretch"):
            clear_session(st.session_state)
            st.rerun()

st.markdown("---")

# -------------------------------------------------------------------------
# Section 1: Project folder input
# -------------------------------------------------------------------------
st.header("1. Select SWAT Project Folder")

# Determine default path: browsed path > loaded project path > empty
default_path = st.session_state.get("_browsed_project_path", "") \
    or st.session_state.get("project_path", "")

# Use a generation counter to force Streamlit to treat the widget as new after browse
_proj_gen = st.session_state.get("_proj_path_gen", 0)

col_path, col_browse = st.columns([4, 1])

with col_path:
    project_path = st.text_input(
        "Enter the full path to your SWAT project folder:",
        value=default_path,
        placeholder="C:/path/to/your/swat_project",
        help="This should be the folder containing file.cio",
        key=f"_project_path_input_{_proj_gen}",
    )

with col_browse:
    st.markdown("<br>", unsafe_allow_html=True)  # align with text input
    if st.button("Browse...", width="stretch"):
        selected = browse_folder()
        if selected:
            st.session_state["_browsed_project_path"] = selected
            st.session_state["_proj_path_gen"] = _proj_gen + 1
            st.rerun()

st.info("💡 **Tip:** Click **Browse...** to select your project folder, or paste the path directly.")

if st.button("📂 Load Project", type="primary"):
    if project_path:
        project_dir = Path(project_path)

        if project_dir.exists():
            # Check for file.cio
            cio_path = project_dir / "file.cio"

            if cio_path.exists():
                with st.status("Loading SWAT project...", expanded=True) as _load_status:
                    st.session_state.project_path = str(project_dir)

                    # Step 1: Validate
                    st.write("⏳ Validating project folder...")
                    st.write(f"Found `file.cio` in `{project_dir.name}`")

                    # Step 2: Find executable
                    st.write("⏳ Finding SWAT executable...")
                    found_exe = _find_swat_exe(project_dir)
                    if found_exe:
                        st.session_state.swat_exe = str(found_exe)
                        st.write(f"Found executable: `{found_exe.name}`")
                    else:
                        st.write("No executable auto-detected (can set manually below)")

                    # Step 3: Load project config
                    st.write("⏳ Reading project configuration...")
                    try:
                        from swat_modern import SWATModel
                        exe_arg = str(found_exe) if found_exe else None
                        model = SWATModel(str(project_dir), executable=exe_arg)
                        st.session_state.model = model
                        st.write("Configuration parsed successfully")
                    except Exception as e:
                        st.write(f"⚠️ Couldn't parse details: {e}")

                    # Step 4: Scan for shapefiles
                    st.write("⏳ Scanning for shapefiles...")
                    try:
                        from swat_modern.spatial.shapefile_loader import ShapefileLoader
                        loader = ShapefileLoader(str(project_dir))
                        shapefile_paths = loader.find_shapefiles()
                        if shapefile_paths:
                            st.session_state.shapefile_paths = shapefile_paths
                            st.write(f"Found {len(shapefile_paths)} shapefile layer(s)")
                        else:
                            st.write("No shapefiles auto-detected")
                    except ImportError:
                        st.write("Spatial module not available")
                    except Exception:
                        st.write("Shapefile scan skipped")

                    # Complete
                    _summary = f"Project **{project_dir.name}** loaded"
                    if found_exe:
                        _summary += f" with {found_exe.name}"
                    _load_status.update(label=_summary, state="complete", expanded=False)

                # Clean up browsed path now that project is loaded
                st.session_state.pop("_browsed_project_path", None)
                # Bump widget generation so text_input picks up the loaded path
                st.session_state["_proj_path_gen"] = _proj_gen + 1
                # Save session state to disk for refresh persistence
                save_session(st.session_state)
                st.rerun()

            else:
                st.error("file.cio not found in this folder. Please select a valid SWAT project folder.")
        else:
            st.error("Folder does not exist. Please check the path.")
    else:
        st.warning("Please enter a project path.")

# -------------------------------------------------------------------------
# Section 2: Project Information (shown when project is loaded)
# -------------------------------------------------------------------------
st.markdown("---")

if "project_path" in st.session_state:
    project_dir = Path(st.session_state.project_path)

    st.header("2. Project Information")
    st.success(f"**Loaded Project:** {project_dir.name}")

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("**Project Details:**")
        st.write(f"- **Path:** {project_dir}")
        st.write(f"- **Name:** {project_dir.name}")

        # Count files
        file_types = {
            ".sub": "Subbasin files",
            ".hru": "HRU files",
            ".sol": "Soil files",
            ".mgt": "Management files",
        }

        for ext, name in file_types.items():
            count = len([f for f in project_dir.glob(f"*{ext}") if not f.stem.startswith("output")])
            st.write(f"- **{name}:** {count}")

    with col2:
        st.markdown("**Configuration (file.cio):**")
        model = st.session_state.get("model")
        if model and hasattr(model, 'config'):
            config = model.config
            period = getattr(config, 'period', None)
            if period:
                st.write(f"- **Simulation Start:** {period.start_year}")
                st.write(f"- **Simulation End:** {period.end_year}")
                st.write(f"- **Warmup Years:** {period.warmup_years}")
            else:
                st.write("- **Simulation Start:** N/A")
                st.write("- **Simulation End:** N/A")
                st.write("- **Warmup Years:** N/A")
        else:
            st.write("Configuration loaded")

    if "shapefile_paths" in st.session_state:
        found_layers = [k for k, v in st.session_state.shapefile_paths.items() if v is not None]
        if found_layers:
            st.success(f"Found shapefiles: {', '.join(found_layers)}")

# -------------------------------------------------------------------------
# Section 3: Current Status & File Browser
# -------------------------------------------------------------------------
st.markdown("---")
st.header("3. Current Status")

if "project_path" in st.session_state:
    project_dir = Path(st.session_state.project_path)

    # ----- View Project Files (categorized by extension) -----
    with st.expander("📄 View Project Files"):
        all_files = sorted(project_dir.glob("*.*"))

        if not all_files:
            st.info("No files found in the project directory.")
        else:
            # Group files by extension
            files_by_ext = defaultdict(list)
            for f in all_files:
                ext = f.suffix.lower() if f.suffix else "(no extension)"
                files_by_ext[ext].append(f)

            # Show summary
            st.caption(f"Total: {len(all_files)} files in {len(files_by_ext)} categories")

            # Build flat list of files for selectbox
            all_file_names = ["(select a file to view)"] + [f.name for f in all_files]

            # Display each category as a collapsible section
            for ext in sorted(files_by_ext.keys()):
                file_list = files_by_ext[ext]
                with st.expander(f"{ext} ({len(file_list)} files)"):
                    for f in file_list:
                        col_name, col_open = st.columns([4, 1])
                        with col_name:
                            st.text(f.name)
                        with col_open:
                            if st.button("Open", key=f"open_{f.name}", width="stretch"):
                                _open_in_editor(str(f))

            st.markdown("---")

            # File viewer: selectbox + inline preview
            selected_file = st.selectbox(
                "Preview file content:",
                options=all_file_names,
                index=0,
                key="file_preview_select",
            )

            if selected_file != "(select a file to view)":
                fpath = project_dir / selected_file
                if fpath.exists():
                    try:
                        content = fpath.read_text(encoding="utf-8", errors="replace")
                        lines = content.splitlines()
                        total_lines = len(lines)
                        if total_lines > 200:
                            st.warning(f"Showing first 200 of {total_lines} lines. Click **Open** next to the file to view it fully.")
                            content = "\n".join(lines[:200])
                        st.text_area(
                            f"{selected_file} ({total_lines} lines)",
                            value=content,
                            height=400,
                            disabled=True,
                        )
                    except Exception as e:
                        st.error(f"Cannot read file as text: {e}")

    # SWAT executable check
    st.markdown("---")
    st.header("4. SWAT Executable")

    found_exe = _find_swat_exe(project_dir)

    if found_exe:
        st.success(f"Found SWAT executable: {found_exe.name}")
        st.session_state.swat_exe = str(found_exe)
        save_session(st.session_state)
    else:
        st.warning("No SWAT executable found in project folder.")

        # Apply browsed exe path before widget renders
        _browsed_exe = st.session_state.get("_browsed_exe_path", "")

        col_exe, col_exe_browse = st.columns([4, 1])
        with col_exe:
            custom_exe = st.text_input(
                "Enter path to SWAT executable (optional):",
                value=_browsed_exe,
                placeholder="C:/path/to/swat.exe",
            )
        with col_exe_browse:
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("Browse...", key="browse_exe", width="stretch"):
                from swat_modern.app.session_persistence import browse_file
                selected_exe = browse_file(
                    title="Select SWAT Executable",
                    filetypes=[("Executable files", "*.exe"), ("All files", "*.*")],
                )
                if selected_exe:
                    st.session_state._browsed_exe_path = selected_exe
                    st.rerun()

        if custom_exe and Path(custom_exe).exists():
            st.session_state.swat_exe = custom_exe
            st.session_state.pop("_browsed_exe_path", None)
            save_session(st.session_state)
            st.success(f"Using custom executable: {custom_exe}")

else:
    st.info("No project loaded yet. Enter a path above and click 'Load Project'.")

# Navigation hint
st.markdown("---")
st.markdown("""
**Next Step:** Go to **Watershed Map** to view your project spatially, or **Simulation Results** to browse model outputs.
""")


