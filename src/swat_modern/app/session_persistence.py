"""
Session persistence for SWAT-DG app.

Saves and restores project session state to a local JSON file so that
browser refresh does not lose loaded project data.
"""

import json
import logging
import os
import pickle
from pathlib import Path

_log = logging.getLogger(__name__)

# Keys to persist across browser refreshes
PERSIST_KEYS = [
    "project_path",
    "swat_exe",
    "swat_executable",
    "obs_units",
    "output_type",
    "reach_id",
    "output_variable",
    "calibration_objective",
    "calibration_result",
    "best_parameters",
    # Sensitivity analysis results (survive browser refresh)
    "sensitivity_results",
    "sa_best_params",
    "sa_best_objective",
    "sa_runtime",
    "sa_method_used",
    "sa_n_evaluations",
]

SESSION_DIR = Path.home() / ".swat_modern"


def _session_file(session_state) -> Path:
    """Get session file path, keyed by project_dir to avoid cross-tab conflicts."""
    SESSION_DIR.mkdir(exist_ok=True)
    project_dir = session_state.get("project_path", "")
    if project_dir:
        import hashlib
        suffix = hashlib.md5(str(project_dir).encode()).hexdigest()[:8]
        return SESSION_DIR / f"session_{suffix}.json"
    return SESSION_DIR / "session_default.json"


def save_session(session_state):
    """Save persistable session state keys to a local JSON file."""
    data = {}
    for key in PERSIST_KEYS:
        if key in session_state:
            val = session_state[key]
            # Only save JSON-serializable values
            if isinstance(val, (str, int, float, bool, list, dict, type(None))):
                data[key] = val
    try:
        _session_file(session_state).write_text(
            json.dumps(data, indent=2), encoding="utf-8"
        )
    except Exception:
        pass


def load_session(session_state):
    """Restore persisted session state from the local JSON file."""
    sf = _session_file(session_state)
    if not sf.exists():
        # Migrate from legacy single-file location
        legacy = Path.home() / ".swat_modern_session.json"
        if legacy.exists():
            sf = legacy
        else:
            return
    try:
        data = json.loads(sf.read_text(encoding="utf-8"))
        for key, val in data.items():
            if key not in session_state:
                session_state[key] = val
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Observation data persistence (pickle-based)
# ---------------------------------------------------------------------------
# observed_data is a pandas Series (not JSON-serializable) that must survive
# browser refreshes and session timeouts so that data loaded on the
# Observation Data page carries over to the Calibration page.
_OBSERVATION_DATA_KEYS = [
    "observed_data",
    "observed_data_multi",
    "obs_units",
    "wq_load_data",
]


def _observation_data_file(session_state) -> Path:
    """Return the path for the pickled observation data file."""
    SESSION_DIR.mkdir(exist_ok=True)
    project_dir = session_state.get("project_path", "")
    if project_dir:
        import hashlib
        suffix = hashlib.md5(str(project_dir).encode()).hexdigest()[:8]
        return SESSION_DIR / f"obs_data_{suffix}.pkl"
    return SESSION_DIR / "obs_data_default.pkl"


def save_observation_data(session_state):
    """Persist observation data (pandas objects) to a pickle file.

    Called after processing observation data on the Observation Data page
    so it survives session timeouts and browser refreshes.
    """
    data = {}
    for key in _OBSERVATION_DATA_KEYS:
        if key in session_state:
            data[key] = session_state[key]
    if not data:
        return
    try:
        pkl_path = _observation_data_file(session_state)
        pkl_path.write_bytes(pickle.dumps(data, protocol=pickle.HIGHEST_PROTOCOL))
        _log.debug("Saved observation data to %s", pkl_path)
    except Exception:
        _log.warning("Failed to save observation data", exc_info=True)


def load_observation_data(session_state):
    """Restore observation data from the pickle file.

    Only restores keys that are not already present in session_state
    (avoids overwriting fresher in-memory data).
    """
    pkl_path = _observation_data_file(session_state)
    if not pkl_path.exists():
        return
    try:
        data = pickle.loads(pkl_path.read_bytes())
        for key, val in data.items():
            if key not in session_state:
                session_state[key] = val
        _log.debug("Loaded observation data from %s", pkl_path)
    except Exception:
        _log.warning("Failed to load observation data", exc_info=True)


# ---------------------------------------------------------------------------
# Calibration results persistence (pickle-based)
# ---------------------------------------------------------------------------
# These keys hold complex objects (numpy arrays, custom classes) that cannot
# be JSON-serialized but are essential for the Results page plots.
_CALIBRATION_RESULT_KEYS = [
    "calibration_results_full",
    "calibration_runtime",
    "baseline_results",
    "sequential_results",
    "phased_results",
    "calibration_mode",
    "calibration_reach_id",
    "section_subbasins",
]


def _calibration_results_file(session_state) -> Path:
    """Return the path for the pickled calibration results file."""
    SESSION_DIR.mkdir(exist_ok=True)
    project_dir = session_state.get("project_path", "")
    if project_dir:
        import hashlib
        suffix = hashlib.md5(str(project_dir).encode()).hexdigest()[:8]
        return SESSION_DIR / f"cal_results_{suffix}.pkl"
    return SESSION_DIR / "cal_results_default.pkl"


def save_calibration_results(session_state):
    """Persist complex calibration result objects to a pickle file.

    Called after results are transferred from CalibrationState to
    session_state so they survive session timeouts and browser refreshes.
    """
    data = {}
    for key in _CALIBRATION_RESULT_KEYS:
        if key in session_state:
            data[key] = session_state[key]
    # Also save the JSON-serializable keys that are part of the result set
    for key in ("calibration_result", "best_parameters", "calibration_objective"):
        if key in session_state:
            data[key] = session_state[key]
    if not data:
        return
    try:
        pkl_path = _calibration_results_file(session_state)
        pkl_path.write_bytes(pickle.dumps(data, protocol=pickle.HIGHEST_PROTOCOL))
        _log.debug("Saved calibration results to %s", pkl_path)
    except Exception:
        _log.warning("Failed to save calibration results", exc_info=True)


def load_calibration_results(session_state):
    """Restore calibration results from the pickle file.

    Only restores keys that are not already present in session_state
    (avoids overwriting fresher in-memory data).
    """
    pkl_path = _calibration_results_file(session_state)
    if not pkl_path.exists():
        return
    try:
        data = pickle.loads(pkl_path.read_bytes())
        for key, val in data.items():
            if key not in session_state:
                session_state[key] = val
        _log.debug("Loaded calibration results from %s", pkl_path)
    except Exception:
        _log.warning("Failed to load calibration results", exc_info=True)


def clear_calibration_results(session_state):
    """Delete the persisted calibration results file."""
    try:
        pkl_path = _calibration_results_file(session_state)
        if pkl_path.exists():
            pkl_path.unlink()
    except Exception:
        pass


def clear_session(session_state):
    """Clear all project-related session state and delete the session file."""
    # Keep calibration results pickle on disk — they survive project
    # exit so the user can re-open and still see the last results.
    # Only a new calibration run clears them.

    # Cancel any running background calibration/SA before clearing state
    _cal_state = session_state.get("_calibration_state")
    if _cal_state is not None and hasattr(_cal_state, "request_cancel"):
        _cal_state.request_cancel()
    _sa_state = session_state.get("_sensitivity_state")
    if _sa_state is not None and hasattr(_sa_state, "request_cancel"):
        _sa_state.request_cancel()

    # Clear module-level state registries
    from swat_modern.app.calibration_runner import (
        clear_active_sensitivity_state,
        clear_active_calibration_state,
    )
    clear_active_sensitivity_state()
    clear_active_calibration_state()

    # Clear all project-related keys
    keys_to_clear = list(PERSIST_KEYS) + [
        "model",
        "shapefile_paths",
        "observed_data",
        "observed_data_multi",
        "wq_load_data",
        "boundary_manager",
        "calibration_result",
        "best_parameters",
        "calibration_results_full",
        "calibration_runtime",
        "baseline_results",
        "sequential_results",
        "calibration_objective",
        "section_subbasins",
        "_calibration_state",
        "subbasins_gdf",
        "streams_gdf",
        "_browsed_project_path",
        "_browsed_exe_path",
        "_browsed_shapes_dir",
        "_browsed_obs_file",
        "_browsed_cal_exe_path",
        "_view_file",
        "boundary_gdf",
        "reservoirs_gdf",
        "selected_subbasin_popup",
        "project_parameters",
        "_obs_loaded_df",
        "_obs_source_info",
        "_obs_nwis_units",
        # SA results
        "sensitivity_results",
        "sa_best_params",
        "sa_best_objective",
        "sa_runtime",
        "sa_method_used",
        "sa_n_evaluations",
        "_sensitivity_state",
    ]
    for key in keys_to_clear:
        if key in session_state:
            del session_state[key]
    # Delete the session file and observation data pickle
    for sf in (SESSION_DIR,):
        try:
            if sf.is_dir():
                for f in sf.glob("session_*.json"):
                    f.unlink()
                for f in sf.glob("obs_data_*.pkl"):
                    f.unlink()
        except Exception:
            pass
    # Also remove legacy single file
    try:
        legacy = Path.home() / ".swat_modern_session.json"
        if legacy.exists():
            legacy.unlink()
    except Exception:
        pass


def get_output_mtime(project_path: str) -> float:
    """Return the latest modification time of SWAT output files.

    Used as a cache-busting key for ``@st.cache_resource`` /
    ``@st.cache_data`` so that cached ResultBrowser instances and parsed
    data are automatically invalidated when SWAT produces new output.

    Checks only the three main output files (three ``stat()`` calls —
    negligible overhead).
    """
    max_mt = 0.0
    for name in ("output.rch", "output.sub", "output.hru"):
        try:
            mt = os.path.getmtime(os.path.join(project_path, name))
            if mt > max_mt:
                max_mt = mt
        except OSError:
            pass
    return max_mt


def get_param_mtime(project_path: str) -> float:
    """Return a representative modification time for parameter files.

    Checks ``basins.bsn`` and the first ``.mgt`` file (covers ESCO,
    SURLAG, CN2 — the most commonly calibrated parameters).  Cheap
    enough to call on every page rerun.
    """
    max_mt = 0.0
    proj = Path(project_path)
    # basins.bsn — basin-level params (ESCO, SURLAG, etc.)
    bsn = proj / "basins.bsn"
    if bsn.exists():
        try:
            max_mt = os.path.getmtime(bsn)
        except OSError:
            pass
    # First .mgt file — HRU-level params (CN2, etc.)
    for f in proj.glob("*.mgt"):
        try:
            mt = os.path.getmtime(f)
            if mt > max_mt:
                max_mt = mt
        except OSError:
            pass
        break  # only check the first one
    return max_mt


def _run_dialog_subprocess(mode, title, filter_str=None):
    """Launch _win32_dialog.exe (compiled C# with [STAThread]) and return path.

    Uses .NET COM interop for reliable IFileOpenDialog access.
    The exe is a proper [STAThread] Windows app — avoids all COM/STA issues.

    Returns the selected path, or "" if the user cancelled.
    Raises RuntimeError if the helper exe is missing or broken.
    """
    import ctypes
    import subprocess

    # Find the compiled helper next to this file
    helper = Path(__file__).with_name("_win32_dialog.exe")
    if not helper.exists():
        raise RuntimeError(f"Win32 dialog helper not found: {helper}")

    # Get foreground HWND so the dialog appears on top
    hwnd = ctypes.windll.user32.GetForegroundWindow()

    cmd = [str(helper), mode, "--title", title, "--hwnd", str(hwnd)]

    if filter_str:
        # Convert null-delimited filter to pipe-delimited for CLI
        parts = filter_str.rstrip("\0").split("\0")
        cmd.append("|".join(parts))

    result = subprocess.run(
        cmd, capture_output=True, text=True, timeout=300,
    )
    # Exit code 0 = path selected, 1 = user cancelled, 2+ = error
    if result.returncode == 0:
        return result.stdout.strip()
    if result.returncode == 1:
        return ""  # user cancelled — don't fall through to tkinter
    # Any other exit code means the helper is broken
    raise RuntimeError(f"Win32 dialog helper failed (exit {result.returncode})")


def _browse_folder_win32(title="Select Folder"):
    """Open a modern Windows folder picker (IFileOpenDialog, Vista+ style)."""
    return _run_dialog_subprocess("folder", title)


def _browse_file_win32(title="Select File", filter_str="All files\0*.*\0"):
    """Open a modern Windows file picker (IFileOpenDialog, Vista+ style)."""
    return _run_dialog_subprocess("file", title, filter_str)


def _has_tkinter():
    """Check if tkinter is available (not present in embedded/portable Python)."""
    try:
        import tkinter  # noqa: F401
        return True
    except ImportError:
        return False


def browse_folder(title="Select SWAT Project Folder"):
    """Open a native folder selection dialog. Returns the selected path or empty string."""
    # Prefer tkinter (reliable, topmost); use Win32 exe only when tkinter
    # is unavailable (portable/embedded Python).
    if _has_tkinter():
        try:
            import tkinter as tk
            from tkinter import filedialog
            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            folder = filedialog.askdirectory(title=title, mustexist=True)
            root.destroy()
            return folder if folder else ""
        except Exception:
            pass

    # Fallback to Win32 helper exe (portable package without tkinter)
    if os.name == "nt":
        try:
            return _browse_folder_win32(title)
        except Exception:
            pass

    return ""


def browse_file(title="Select File", filetypes=None):
    """Open a native file selection dialog. Returns the selected path or empty string."""
    # Prefer tkinter (reliable, topmost); use Win32 exe only when tkinter
    # is unavailable (portable/embedded Python).
    if _has_tkinter():
        try:
            import tkinter as tk
            from tkinter import filedialog
            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            if filetypes is None:
                filetypes = [("All files", "*.*")]
            filepath = filedialog.askopenfilename(title=title, filetypes=filetypes)
            root.destroy()
            return filepath if filepath else ""
        except Exception:
            pass

    # Fallback to Win32 helper exe (portable package without tkinter)
    if os.name == "nt":
        try:
            if filetypes:
                parts = []
                for label, pattern in filetypes:
                    parts.append(label)
                    parts.append(pattern)
                filter_str = "\0".join(parts) + "\0"
            else:
                filter_str = "All files\0*.*\0"
            return _browse_file_win32(title, filter_str)
        except Exception:
            pass

    return ""
