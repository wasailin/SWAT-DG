"""
Background calibration runner for the Streamlit app.

Runs SWAT model calibration in a daemon thread so it survives tab
switching.  A shared ``CalibrationState`` object communicates progress
from the background thread to the Streamlit UI thread.

Thread safety note
------------------
CPython's GIL guarantees that simple attribute reads/writes are atomic.
There is exactly one writer (background thread) and one reader (UI
thread polling via ``snapshot()``).  No explicit locks are needed.
"""

import threading
import time
import traceback
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Module-level registry for active background states.
# Streamlit session_state is lost on browser refresh, but daemon threads
# survive.  This module-level reference lets us reconnect to a running
# (or just-completed) SA / calibration after a page reload.
# ---------------------------------------------------------------------------

_active_sa_state: Optional["CalibrationState"] = None
_active_cal_state: Optional["CalibrationState"] = None


def get_active_sensitivity_state() -> Optional["CalibrationState"]:
    """Return the module-level SA state if it exists and is still relevant."""
    return _active_sa_state


def clear_active_sensitivity_state():
    """Clear the module-level SA state (called when user dismisses or starts new SA)."""
    global _active_sa_state
    _active_sa_state = None


def get_active_calibration_state() -> Optional["CalibrationState"]:
    """Return the module-level calibration state if it exists and is still relevant."""
    return _active_cal_state


def clear_active_calibration_state():
    """Clear the module-level calibration state."""
    global _active_cal_state
    _active_cal_state = None


# ---------------------------------------------------------------------------
# Cancellation exception
# ---------------------------------------------------------------------------

class CalibrationCancelled(Exception):
    """Raised inside a progress callback when cancellation is requested."""


# ---------------------------------------------------------------------------
# Shared state dataclass
# ---------------------------------------------------------------------------

class CalibrationState:
    """Shared state between the calibration thread and the Streamlit UI.

    ``simulation_count`` is a monotonic property — once set to N, it
    can never be set to a value less than N.  This prevents visual
    "counter decrease" artifacts regardless of which thread/callback
    writes to it.
    """

    def __init__(self):
        # --- status ---
        self.status: str = "idle"  # idle | running | completed | failed | cancelled | cancelling

        # --- progress (updated by callbacks) ---
        self._simulation_count: int = 0  # backing field; use property
        self.total_iterations: int = 0
        self.elapsed_seconds: float = 0.0
        self.avg_time_per_sim: float = 0.0
        self.best_score: float = -1e10

        # sequential-specific progress
        self.current_step: int = 0
        self.total_steps: int = 0
        self.step_message: str = ""

        # calibration mode
        self.mode: str = "single"

        # parallel info (for UI display)
        self.use_parallel: bool = False
        self.n_cores: int = 1
        self.n_iterations_per_core: int = 0  # user-specified iterations

        # --- results (populated on completion) ---
        self.result_calibration_result: Optional[Dict] = None
        self.result_best_parameters: Optional[Dict] = None
        self.result_calibration_results_full: Any = None
        self.result_calibration_runtime: Optional[float] = None
        self.result_baseline_results: Optional[List] = None
        self.result_calibration_objective: Optional[str] = None
        self.result_calibration_mode: Optional[str] = None
        self.result_calibration_reach_id: Optional[int] = None
        self.result_sequential_results: Any = None
        self.result_phased_results: Any = None  # PhasedCalibrationResult

        # --- sensitivity analysis results ---
        self.result_sensitivity: Any = None

        # --- error ---
        self.error_message: str = ""
        self.error_traceback: str = ""

        # --- cancellation ---
        self.cancel_requested: bool = False
        self.cancel_event: threading.Event = threading.Event()
        self.cancel_message: str = ""  # detailed status during cancellation
        self._cancel_file_paths: List[str] = []  # cross-process cancel files

        # --- working directory tracking (for cleanup on cancel) ---
        self._working_dirs: List[str] = []  # paths of temp working copies

        # --- internal ---
        self._thread: Optional[threading.Thread] = None
        self.start_time: Optional[float] = None

    # Monotonic simulation_count — can only increase, never decrease.
    @property
    def simulation_count(self) -> int:
        return self._simulation_count

    @simulation_count.setter
    def simulation_count(self, value: int):
        if value > self._simulation_count:
            self._simulation_count = value

    # ------------------------------------------------------------------
    def snapshot(self) -> dict:
        """Return a dict snapshot of current progress for the UI."""
        return {
            "status": self.status,
            "simulation_count": self.simulation_count,
            "total_iterations": self.total_iterations,
            "elapsed_seconds": self.elapsed_seconds,
            "avg_time_per_sim": self.avg_time_per_sim,
            "best_score": self.best_score,
            "current_step": self.current_step,
            "total_steps": self.total_steps,
            "step_message": self.step_message,
            "mode": self.mode,
            "use_parallel": self.use_parallel,
            "n_cores": self.n_cores,
            "n_iterations_per_core": self.n_iterations_per_core,
            "error_message": self.error_message,
            "cancel_requested": self.cancel_requested,
            "cancel_message": self.cancel_message,
            "start_time": self.start_time,
        }

    def is_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def register_working_dir(self, path: str):
        """Register a temporary working directory for cleanup on cancel."""
        if path not in self._working_dirs:
            self._working_dirs.append(path)

    def register_cancel_file(self, path: str):
        """Register a file-based cancel flag for cross-process cancellation.

        When ``request_cancel()`` is called, this file is written
        immediately so worker processes (which cannot share
        threading.Event) detect cancellation within 0.25 s.

        If cancellation was already requested before this call,
        the file is written immediately (handles the race where
        ``request_cancel()`` ran before the file was registered).
        """
        if path not in self._cancel_file_paths:
            self._cancel_file_paths.append(path)
        # If cancel was already requested, write the file NOW.
        # This closes the race where request_cancel() iterated an
        # empty _cancel_file_paths list before this path was added.
        if self.cancel_requested:
            try:
                from pathlib import Path
                p = Path(path)
                if not p.exists():
                    p.parent.mkdir(parents=True, exist_ok=True)
                    p.write_text("cancelled")
                    print(f"[cancel] Wrote cancel file (late register): {path}")
            except Exception as exc:
                print(f"[cancel] Failed to write cancel file {path}: {exc}")

    def request_cancel(self):
        """Request cooperative cancellation.

        Sets the boolean flag (checked by callbacks between steps),
        the threading.Event (checked by SWATRunner's poll loop for
        same-process cancel), AND writes any registered cancel files
        (checked by SWATRunner's poll loop in worker processes).
        """
        if self.cancel_requested:
            return  # already cancelled — nothing to do
        print("[cancel] Cancellation requested by user")
        self.cancel_requested = True
        self.cancel_event.set()
        self.cancel_message = "Cancellation requested — stopping current simulation..."
        # Immediately write cross-process cancel files so worker SWAT
        # processes are killed within 0.25 s (runner poll interval).
        if not self._cancel_file_paths:
            print("[cancel] Warning: no cancel files registered — "
                  "worker processes may not stop promptly")
        for cf in self._cancel_file_paths:
            try:
                from pathlib import Path
                p = Path(cf)
                if not p.exists():
                    p.parent.mkdir(parents=True, exist_ok=True)
                    p.write_text("cancelled")
                    print(f"[cancel] Wrote cancel file: {cf}")
            except Exception as exc:
                print(f"[cancel] ERROR writing cancel file {cf}: {exc}")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def start_calibration(config: dict) -> CalibrationState:
    """Start calibration in a background daemon thread.

    Parameters
    ----------
    config : dict
        All configuration needed to run calibration.  See
        ``_run_calibration_background`` for expected keys.

    Returns
    -------
    CalibrationState
        Shared state object – store in ``st.session_state["_calibration_state"]``.
    """
    state = CalibrationState()
    state.mode = config.get("mode", "single")
    state.total_iterations = config.get("n_iterations", 0)
    state.use_parallel = config.get("use_parallel", False)
    state.n_cores = config.get("n_cores", 1) or 1
    state.n_iterations_per_core = config.get("n_iterations", 0)
    state.status = "running"
    state.step_message = "Initializing calibration..."
    state.start_time = time.time()

    thread = threading.Thread(
        target=_run_calibration_background,
        args=(state, config),
        daemon=True,
        name="swat-calibration",
    )
    state._thread = thread
    thread.start()

    global _active_cal_state
    _active_cal_state = state

    return state


def check_and_transfer_results(session_state) -> Optional[dict]:
    """Check if background calibration completed and transfer results.

    Call at the top of any page that needs calibration results.

    Returns
    -------
    dict or None
        A ``snapshot()`` dict if a calibration state exists, else ``None``.
        When status is ``"completed"``, results are copied into
        *session_state* under the standard keys the Results page expects.
    """
    cal_state: Optional[CalibrationState] = session_state.get("_calibration_state")
    if cal_state is None:
        return None

    snap = cal_state.snapshot()

    if cal_state.status == "completed":
        _transfer_map = {
            "calibration_result": "result_calibration_result",
            "best_parameters": "result_best_parameters",
            "calibration_results_full": "result_calibration_results_full",
            "calibration_runtime": "result_calibration_runtime",
            "baseline_results": "result_baseline_results",
            "calibration_objective": "result_calibration_objective",
            "calibration_mode": "result_calibration_mode",
            "calibration_reach_id": "result_calibration_reach_id",
        }
        for session_key, state_attr in _transfer_map.items():
            val = getattr(cal_state, state_attr, None)
            if val is not None:
                session_state[session_key] = val

        # Partial-section subbasin list (for scoped parameter application)
        section_subs = getattr(cal_state, "result_section_subbasins", None)
        if section_subs is None:
            # Fallback: use upstream_subbasins stored early in the run
            section_subs = getattr(cal_state, "result_upstream_subbasins", None)
        if section_subs is not None:
            session_state["section_subbasins"] = section_subs

        # Sequential-specific
        seq = getattr(cal_state, "result_sequential_results", None)
        if seq is not None:
            session_state["sequential_results"] = seq

        # Phased (multi-constituent)-specific
        phased = getattr(cal_state, "result_phased_results", None)
        if phased is not None:
            session_state["phased_results"] = phased

        # Persist results to disk so they survive session timeouts
        from swat_modern.app.session_persistence import save_calibration_results
        save_calibration_results(session_state)

        # Mark as transferred so we don't re-copy every rerun
        cal_state.status = "transferred"

    return snap


# ---------------------------------------------------------------------------
# Background thread implementation
# ---------------------------------------------------------------------------

def _check_cancel(state: CalibrationState):
    """Raise ``CalibrationCancelled`` if the user requested cancellation."""
    if state.cancel_requested:
        raise CalibrationCancelled("Calibration cancelled by user")


def _cleanup_working_dirs(state: CalibrationState):
    """Remove temporary working directories registered during calibration."""
    import shutil
    for wd in list(state._working_dirs):
        try:
            from pathlib import Path
            wd_path = Path(wd)
            if wd_path.exists():
                # Also clean up per-process worker directories (pattern: <dir>_w<pid>)
                parent = wd_path.parent
                stem = wd_path.name
                for worker_dir in parent.glob(f"{stem}_w*"):
                    shutil.rmtree(worker_dir, ignore_errors=True)
                shutil.rmtree(wd_path, ignore_errors=True)
        except Exception:
            pass


def _create_shared_cancel_file(state: CalibrationState):
    """Create a single cross-process cancel file and register it on state.

    The returned Path object is used by every setup / calibrator spawned
    during this run so that ``state.request_cancel()`` immediately writes
    the file and every worker process (which cannot share a
    ``threading.Event``) sees the flag on its next ``simulation()`` check.

    Returns
    -------
    pathlib.Path
        The absolute path to the (not-yet-existing) cancel flag file.
        Call :func:`_cleanup_shared_cancel_file` with its parent directory
        when the run completes.
    """
    import tempfile
    from pathlib import Path

    cancel_dir = Path(tempfile.mkdtemp(prefix="swat_cancel_"))
    cancel_file = cancel_dir / "cancel.flag"
    state.register_cancel_file(str(cancel_file))
    return cancel_file


def _cleanup_shared_cancel_file(cancel_file):
    """Remove the temp directory holding the cancel flag."""
    if cancel_file is None:
        return
    try:
        import shutil
        from pathlib import Path
        shutil.rmtree(str(Path(cancel_file).parent), ignore_errors=True)
    except Exception:
        pass


def _run_calibration_background(state: CalibrationState, config: dict):
    """Thread target – runs full calibration pipeline."""
    _shared_cancel_file = None
    try:
        # Suppress Streamlit warnings about missing ScriptRunContext
        # (this thread is not a Streamlit script thread)
        import logging
        logging.getLogger(
            "streamlit.runtime.scriptrunner_utils.script_run_context"
        ).setLevel(logging.ERROR)

        import numpy as np
        import pandas as pd
        from swat_modern import SWATModel
        from swat_modern.calibration import Calibrator
        from swat_modern.calibration.spotpy_setup import run_baseline_simulation

        # Create a cross-process cancel file BEFORE any mode function runs.
        # Every setup / calibrator spawned below receives this path; when
        # the user clicks Cancel in the UI, ``state.request_cancel()``
        # writes the file and parallel SPOTPY workers detect it on their
        # next ``simulation()`` call.  See ``CalibrationState.register_cancel_file``.
        _shared_cancel_file = _create_shared_cancel_file(state)
        config = dict(config)  # don't mutate caller's dict
        config["_cancel_file_path"] = str(_shared_cancel_file)

        state.step_message = "Loading SWAT model..."
        mode = config["mode"]
        exe_path = (config.get("swat_executable") or "").strip() or None
        model = SWATModel(config["project_path"], executable=exe_path)

        state.result_calibration_objective = config["objective"][1]
        state.result_calibration_mode = mode
        state.result_calibration_reach_id = config.get("single_reach")
        # Persist upstream subbasins early so the Results page can recover
        # them even if the runner doesn't reach the end (e.g. cancellation).
        _ups_early = config.get("upstream_subbasins")
        if _ups_early:
            state.result_upstream_subbasins = sorted(_ups_early)

        # Check parallel processing prerequisites (pathos required by SPOTPY)
        if config.get("use_parallel", False):
            try:
                import pathos  # noqa: F401
            except ImportError:
                config = dict(config)  # shallow copy – don't mutate caller's dict
                config["use_parallel"] = False

        # ---- resolve deferred WQ load computation ----
        # When the user chose "Use SWAT simulated streamflow" in the WQ
        # observation UI, the actual load computation was deferred to here.
        # We run SWAT once for flow, then pair with WQ concentrations.
        # This applies to both single-site and multi-site calibration.

        def _resolve_deferred_wq(deferred_info, reach_id, upstream_subs=None):
            """Run SWAT for flow at *reach_id* and compute WQ loads.

            If the user selected a custom simulation period, we temporarily
            apply it to file.cio before running SWAT so the flow output
            covers the full requested range.

            Returns a DataFrame with [date, observed] columns (loads).
            """
            _wq_df = deferred_info["wq_df"]
            _constituent = deferred_info["constituent"]
            _qsd = config.get("qswat_shapes_dir")

            # Apply custom simulation period if specified, so the
            # flow run covers the user's desired range (not just the
            # model's current IYR/NBYR which may be narrower).
            _custom_sp = config.get("custom_sim_period")
            _orig_start = model.config.period.start_year
            _orig_end = model.config.period.end_year
            _orig_nyskip = model.config.period.warmup_years
            _restored = False

            if _custom_sp:
                _sp_start, _sp_end = _custom_sp
                model.config.period.start_year = _sp_start
                model.config.period.end_year = _sp_end
                # Set NYSKIP=0 so output covers full period
                model.config.period.warmup_years = 0
                model.config.save()
                print(
                    f"[wq-deferred] Temporarily set sim period to "
                    f"{_sp_start}--{_sp_end} (NYSKIP=0) for flow run"
                )
                _restored = True

            try:
                _out_start = (
                    model.config.period.start_year
                    + model.config.period.warmup_years
                )
                _out_end = model.config.period.end_year
                _n_days = (
                    pd.Timestamp(f"{_out_end}-12-31")
                    - pd.Timestamp(f"{_out_start}-01-01")
                ).days + 1
                _dummy_obs = pd.DataFrame({
                    "date": pd.date_range(
                        f"{_out_start}-01-01", periods=_n_days, freq="D",
                    ),
                    "observed": np.zeros(_n_days),
                })

                _flow_bl = run_baseline_simulation(
                    model=model,
                    observed_df=_dummy_obs,
                    output_variable="FLOW_OUT",
                    reach_id=reach_id,
                    warmup_years=0,
                    upstream_subbasins=upstream_subs,
                    qswat_shapes_dir=_qsd,
                    cancel_event=state.cancel_event,
                )
            finally:
                # Restore original period so the calibrator's own
                # SWATModelSetup can manage it properly
                if _restored:
                    model.config.period.start_year = _orig_start
                    model.config.period.end_year = _orig_end
                    model.config.period.warmup_years = _orig_nyskip
                    model.config.save()

            if not _flow_bl.get("success"):
                raise RuntimeError(
                    f"SWAT flow simulation failed (reach {reach_id}): "
                    f"{_flow_bl.get('error', 'unknown')}"
                )

            _sim_flow_df = pd.DataFrame({
                "date": pd.to_datetime(_flow_bl["dates"]),
                "flow_cms": _flow_bl["simulated"],
            }).dropna()

            from swat_modern.calibration.load_calculator import LoadCalculator
            _lc = LoadCalculator(_wq_df, constituents=[_constituent])
            _loads = _lc.compute_loads(_sim_flow_df)
            _load_cols = [c for c in _loads.columns if c != "date"]
            if not _load_cols:
                raise RuntimeError(
                    f"No load columns computed for {_constituent}"
                )
            _obs_loads = pd.DataFrame({
                "date": pd.to_datetime(_loads["date"]),
                "observed": _loads[_load_cols[0]].values,
            }).dropna()

            print(
                f"[wq-deferred] Computed {len(_obs_loads)} {_constituent} "
                f"load observations at reach {reach_id} "
                f"({_obs_loads['date'].min().date()} to "
                f"{_obs_loads['date'].max().date()})"
            )
            return _obs_loads

        # Single-site deferred resolution
        if config.get("wq_deferred") is not None:
            state.step_message = (
                "Running SWAT for streamflow to compute WQ loads..."
            )
            config = dict(config)  # don't mutate caller's dict
            config["single_site_observed"] = _resolve_deferred_wq(
                config["wq_deferred"],
                config.get("single_reach", 1),
                config.get("upstream_subbasins"),
            )

        # Multi-site deferred resolution (per-site)
        if config.get("calibration_sites"):
            _any_deferred = any(
                s.get("wq_deferred") for s in config["calibration_sites"]
            )
            if _any_deferred:
                state.step_message = (
                    "Running SWAT for streamflow to compute WQ loads..."
                )
                config = dict(config)  # don't mutate caller's dict
                _resolved_sites = []
                for _site in config["calibration_sites"]:
                    if _site.get("wq_deferred"):
                        _site = dict(_site)
                        _site["observed"] = _resolve_deferred_wq(
                            _site["wq_deferred"],
                            _site["reach_id"],
                            _site.get("upstream_subbasins"),
                        )
                        _site.pop("wq_deferred", None)
                    _resolved_sites.append(_site)
                config["calibration_sites"] = _resolved_sites

        # ---- baseline simulations ----
        _output_var = config.get("output_variable", "FLOW_OUTcms")
        _output_type = config.get("output_type", "rch")

        baseline_sites: list = []
        if mode in ("single", "partial_section"):
            baseline_sites.append({
                "reach_id": config["single_reach"],
                "observed": config["single_site_observed"],
                "upstream_subbasins": config.get("upstream_subbasins"),
            })
        elif mode in ("simultaneous", "sequential"):
            for site in config["calibration_sites"]:
                baseline_sites.append({
                    "reach_id": site["reach_id"],
                    "observed": site["observed"],
                    "upstream_subbasins": site.get("upstream_subbasins"),
                })
        elif mode == "multi_constituent":
            # Multi-constituent uses the single-site flow obs for baseline
            baseline_sites.append({
                "reach_id": config.get("single_reach", 1),
                "observed": config["single_site_observed"],
                "upstream_subbasins": config.get("upstream_subbasins"),
            })

        state.step_message = "Running baseline simulation (pre-calibration)..."
        baseline_results_all: list = []
        _qswat_shapes = config.get("qswat_shapes_dir")

        # Apply custom simulation period for the baseline run so SWAT
        # produces output covering the user's requested range.  Without
        # this, the baseline uses the project's original IYR/NBYR/NYSKIP
        # which may be much narrower, causing a date mismatch with the
        # observation data and a high-NaN-rate warning.
        _bl_custom_sp = config.get("custom_sim_period")
        _bl_orig_start = model.config.period.start_year
        _bl_orig_end = model.config.period.end_year
        _bl_restored = False
        if _bl_custom_sp:
            _bl_sp_start, _bl_sp_end = _bl_custom_sp
            model.config.period.start_year = _bl_sp_start
            model.config.period.end_year = _bl_sp_end
            model.config.save()
            _bl_restored = True
            print(
                f"[baseline] Temporarily set sim period to "
                f"{_bl_sp_start}--{_bl_sp_end} for baseline run"
            )

        # Back up output files before baseline — model.run() deletes them,
        # and if SWAT fails the user's original output would be lost.
        import shutil as _shutil
        _BL_OUTPUT_NAMES = (
            "output.rch", "output.sub", "output.hru",
            "output.rsv", "output.sed", "output.std",
        )
        _bl_output_backups = {}
        for _fname in _BL_OUTPUT_NAMES:
            _src = model.project_dir / _fname
            if _src.exists():
                _bak = _src.with_suffix(_src.suffix + ".bak_bl")
                _shutil.copy2(_src, _bak)
                _bl_output_backups[_fname] = _bak

        try:
            for bsite in baseline_sites:
                _check_cancel(state)
                bl = run_baseline_simulation(
                    model=model,
                    observed_df=bsite["observed"],
                    output_variable=_output_var,
                    output_type=_output_type,
                    reach_id=bsite["reach_id"],
                    warmup_years=config["warmup_years"],
                    upstream_subbasins=bsite.get("upstream_subbasins"),
                    qswat_shapes_dir=_qswat_shapes,
                    cancel_event=state.cancel_event,
                    print_code=config.get("calibration_print_code"),
                )
                bl["reach_id"] = bsite["reach_id"]
                # Use the merged observed values from run_baseline_simulation
                # (aligned with bl["dates"] and bl["simulated"]).  Fall back
                # to raw obs only if the baseline didn't produce them.
                if bl.get("observed") is None:
                    obs_df = bsite["observed"]
                    bl["observed"] = (
                        obs_df["observed"].values
                        if isinstance(obs_df, pd.DataFrame) and "observed" in obs_df.columns
                        else None
                    )
                baseline_results_all.append(bl)
        finally:
            if _bl_restored:
                model.config.period.start_year = _bl_orig_start
                model.config.period.end_year = _bl_orig_end
                model.config.save()
            # Restore original output files after baseline
            for _fname, _bak in _bl_output_backups.items():
                _dst = model.project_dir / _fname
                if _bak.exists():
                    _shutil.copy2(_bak, _dst)
                    _bak.unlink()

        state.result_baseline_results = baseline_results_all
        state.step_message = "Setting up calibration environment..."

        # ---- limit CPU cores for parallel mode ----
        _original_cpu_count = None
        if config.get("use_parallel", False):
            _n_cores = config.get("n_cores")
            if _n_cores and _n_cores > 0:
                import multiprocessing as _mp
                _original_cpu_count = _mp.cpu_count
                _mp.cpu_count = lambda: _n_cores

        # ---- dispatch by mode ----
        state.step_message = "Starting calibration simulations..."
        try:
            if mode == "single":
                _run_single_site(state, config, model)
            elif mode == "simultaneous":
                _run_simultaneous(state, config, model)
            elif mode == "sequential":
                _run_sequential(state, config, model)
            elif mode == "multi_constituent":
                _run_multi_constituent(state, config, model)
            elif mode == "partial_section":
                _run_partial_section(state, config, model)
        finally:
            # Restore original cpu_count
            if _original_cpu_count is not None:
                import multiprocessing as _mp
                _mp.cpu_count = _original_cpu_count

        # Wall-clock time from button click (includes baseline)
        elapsed = time.time() - state.start_time
        state.result_calibration_runtime = elapsed
        state.status = "completed"

    except CalibrationCancelled:
        print("[cancel] CalibrationCancelled caught — cleaning up...")
        state.cancel_message = "Cleaning up temporary files..."
        state.status = "cancelling"
        _cleanup_working_dirs(state)
        print("[cancel] Calibration cancelled successfully.")
        state.cancel_message = "Calibration cancelled successfully."
        state.status = "cancelled"
        state.error_message = "Calibration was cancelled by user."

    except ImportError as exc:
        state.status = "failed"
        state.error_message = f"Missing required package: {exc}"
        state.error_traceback = traceback.format_exc()

    except Exception as exc:
        # If user requested cancel, the exception may be a side-effect
        # of killing the SWAT process (broken pipe, file not found, etc.)
        if state.cancel_requested:
            print(f"[cancel] Exception during cancel ({type(exc).__name__}) — cleaning up...")
            state.cancel_message = "Cleaning up temporary files..."
            state.status = "cancelling"
            _cleanup_working_dirs(state)
            print("[cancel] Calibration cancelled successfully.")
            state.cancel_message = "Calibration cancelled successfully."
            state.status = "cancelled"
            state.error_message = "Calibration was cancelled by user."
        else:
            state.status = "failed"
            state.error_message = f"Calibration failed: {exc}"
            state.error_traceback = traceback.format_exc()

    except BaseException as exc:
        # Safety net for _CancelSignal (BaseException) that may escape
        # from SPOTPY's loop.  Normal exceptions are caught above.
        if state.cancel_requested:
            print(f"[cancel] BaseException during cancel ({type(exc).__name__}) — cleaning up...")
            state.cancel_message = "Cleaning up temporary files..."
            state.status = "cancelling"
            _cleanup_working_dirs(state)
            print("[cancel] Calibration cancelled successfully.")
            state.cancel_message = "Calibration cancelled successfully."
            state.status = "cancelled"
            state.error_message = "Calibration was cancelled by user."
        else:
            # Unexpected BaseException (SystemExit, KeyboardInterrupt, etc.)
            state.status = "failed"
            state.error_message = f"Calibration failed: {exc}"
            state.error_traceback = traceback.format_exc()

    finally:
        _cleanup_shared_cancel_file(_shared_cancel_file)


# ---------------------------------------------------------------------------
# Mode helpers
# ---------------------------------------------------------------------------

def _make_progress_callback(state: CalibrationState):
    """Return a progress callback that updates *state* and checks cancel."""
    def _cb(info: dict):
        _check_cancel(state)
        state.simulation_count = info["simulation_count"]
        state.elapsed_seconds = info["elapsed_seconds"]
        state.avg_time_per_sim = info["avg_time_per_sim"]
        state.best_score = info["best_score"]
        # Allow callers to override total_iterations (e.g. ensemble mode
        # reports worker-level granularity, not per-SWAT-run).
        if "total_iterations" in info:
            state.total_iterations = info["total_iterations"]
    return _cb


def _attach_progress_polling(state: CalibrationState, setup):
    """Set up file-based progress tracking that works in both seq and parallel modes.

    SPOTPY's parallel mode (``parallel="mpc"``) pickles the setup to
    worker processes via :py:meth:`SWATModelSetup.__getstate__`, which
    intentionally nulls ``progress_callback`` (the callback's closure
    references main-process state that can't cross process boundaries).
    Workers therefore call ``simulation()`` and increment their local
    ``_simulation_count`` but never report progress through the callback.

    To make progress visible regardless of parallel mode and algorithm
    (LHS, MC, DREAM, SCE-UA, ROPE, ...), we set ``setup._progress_counter_dir``
    to a shared temp directory.  ``_report_progress()`` writes a file
    ``{pid}.count`` containing the current per-process simulation count.
    A daemon polling thread in *this* process aggregates those files
    and updates ``state.simulation_count`` so the Streamlit UI fragment
    can render the progress bar.

    In sequential mode the in-memory ``progress_callback`` ALSO fires
    and updates state immediately; the file polling is harmless because
    ``state.simulation_count`` is monotonic.

    Returns
    -------
    (stop_event, counter_dir) : tuple
        The caller is responsible for ``stop_event.set()`` and removing
        ``counter_dir`` when calibration completes (typically in a
        ``finally`` block via :func:`_detach_progress_polling`).
    """
    import tempfile
    from pathlib import Path

    counter_dir = Path(tempfile.mkdtemp(prefix="swat_cal_progress_"))
    setup._progress_counter_dir = str(counter_dir)

    stop_event = threading.Event()

    def _poll():
        while not stop_event.is_set():
            total = 0
            try:
                for f in counter_dir.glob("*.count"):
                    try:
                        total += int(f.read_text().strip() or "0")
                    except (ValueError, OSError):
                        pass
            except OSError:
                pass
            if total > 0:
                # Property setter is monotonic — only updates if greater.
                state.simulation_count = total
                if state.start_time:
                    elapsed = time.time() - state.start_time
                    state.elapsed_seconds = elapsed
                    state.avg_time_per_sim = elapsed / total
            stop_event.wait(1.5)

    thread = threading.Thread(
        target=_poll, daemon=True, name="swat-cal-progress-poll",
    )
    thread.start()
    return stop_event, counter_dir


def _detach_progress_polling(stop_event, counter_dir):
    """Stop the polling thread and remove the temporary counter directory."""
    try:
        stop_event.set()
    except Exception:
        pass
    try:
        import shutil
        shutil.rmtree(str(counter_dir), ignore_errors=True)
    except Exception:
        pass


def _make_sequential_callback(state: CalibrationState):
    """Return a sequential-step progress callback."""
    def _cb(step_num: int, total_steps: int, message: str):
        _check_cancel(state)
        state.current_step = step_num
        state.total_steps = total_steps
        state.step_message = message
    return _cb


def _run_single_site(state: CalibrationState, config: dict, model):
    from swat_modern.calibration import Calibrator

    kwargs: dict = dict(
        model=model,
        observed_data=config["single_site_observed"],
        parameters=config["selected_params"],
        output_variable=config.get("output_variable", "FLOW_OUTcms"),
        output_type=config.get("output_type", "rch"),
        reach_id=config["single_reach"],
        objective=config["objective"][1],
        warmup_years=config["warmup_years"],
        print_code=config.get("calibration_print_code"),
        upstream_subbasins=config.get("upstream_subbasins"),
        qswat_shapes_dir=config.get("qswat_shapes_dir"),
    )

    if config.get("custom_sim_period"):
        kwargs["custom_sim_period"] = config["custom_sim_period"]

    if config.get("use_custom_boundaries") and config.get("boundary_manager"):
        kwargs["parameters"] = config["boundary_manager"].to_parameter_set()

    if config.get("use_partial_basin"):
        kwargs["partial_basin_reach"] = config["single_reach"]

    calibrator = Calibrator(**kwargs)
    calibrator._setup._cancel_state = state
    calibrator._setup._cancel_event = state.cancel_event
    # Cross-process cancel: set the shared cancel-flag path so parallel
    # SPOTPY workers (which cannot share threading.Event) detect cancel.
    _cancel_file_path = config.get("_cancel_file_path")
    if _cancel_file_path:
        calibrator._setup._cancel_file = _cancel_file_path
    state.register_working_dir(str(calibrator._setup._working_dir))

    # File-based progress polling — required so SPOTPY parallel workers
    # (which lose the in-memory progress_callback during pickling) can
    # still report progress to the UI.  Also harmlessly active in seq mode.
    _poll_stop, _poll_dir = _attach_progress_polling(state, calibrator._setup)
    try:
        results = calibrator.auto_calibrate(
            n_iterations=config["n_iterations"],
            algorithm=config["algorithm"][1],
            parallel=config.get("use_parallel", False),
            n_cores=config.get("n_cores"),
            verbose=False,
            progress_callback=_make_progress_callback(state),
            n_ensemble_workers=config.get("n_ensemble_workers", 4),
            kge_target=config.get("kge_target", 0.70),
            pbias_target=config.get("pbias_target", 10.0),
        )
    finally:
        _detach_progress_polling(_poll_stop, _poll_dir)
    _check_cancel(state)

    results.reach_id = config["single_reach"]
    state.result_calibration_result = results.metrics
    state.result_best_parameters = results.best_parameters
    state.result_calibration_results_full = results

    # Store upstream subbasins so the Results page can scope parameter
    # application to only the calibrated subbasins.
    _ups = config.get("upstream_subbasins")
    if _ups:
        state.result_section_subbasins = sorted(_ups)


def _run_simultaneous(state: CalibrationState, config: dict, model):
    from swat_modern.calibration import Calibrator

    sites = config["calibration_sites"]
    # Diagnostic algorithms use upstream-to-downstream sequential logic.
    # Delegate to _run_diagnostic_sequential which handles SequentialCalibrationResult
    # properly (state.result_sequential_results, per-step best_params, etc.).
    _algo = config.get("algorithm", ("", "sceua"))[1] if config.get("algorithm") else "sceua"
    if _algo in ("diagnostic", "diagnostic_ensemble"):
        _run_diagnostic_sequential(state, config, model)
        return

    kwargs: dict = dict(
        model=model,
        observed_data=sites[0]["observed"],
        parameters=config["selected_params"],
        output_variable=config.get("output_variable", "FLOW_OUTcms"),
        output_type=config.get("output_type", "rch"),
        reach_id=sites[0]["reach_id"],
        objective=config["objective"][1],
        warmup_years=config["warmup_years"],
        print_code=config.get("calibration_print_code"),
        qswat_shapes_dir=config.get("qswat_shapes_dir"),
    )

    if config.get("custom_sim_period"):
        kwargs["custom_sim_period"] = config["custom_sim_period"]

    # Partial-basin: compute union of upstream subs for all target reaches
    # using fig.fig routing (priority), then pass the most-downstream reach.
    if config.get("use_partial_basin"):
        from swat_modern.io.parsers.fig_parser import get_multi_reach_active_subs
        _fig_path = model.project_dir / "fig.fig"
        _target_reaches = [s["reach_id"] for s in sites]
        _union_subs, _most_downstream = get_multi_reach_active_subs(
            _fig_path, _target_reaches,
        )
        if _most_downstream:
            kwargs["partial_basin_reach"] = _most_downstream
            kwargs["upstream_subbasins"] = sorted(_union_subs) if _union_subs else None

    calibrator = Calibrator(**kwargs)
    calibrator._setup._cancel_state = state
    calibrator._setup._cancel_event = state.cancel_event
    _cancel_file_path = config.get("_cancel_file_path")
    if _cancel_file_path:
        calibrator._setup._cancel_file = _cancel_file_path
    state.register_working_dir(str(calibrator._setup._working_dir))

    # File-based progress polling — Calibrator.multi_site_calibrate creates
    # a fresh MultiSiteSetup internally, so we pass the counter directory
    # through ``progress_counter_dir`` so it lands on the inner setup.
    _poll_stop, _poll_dir = _attach_progress_polling(state, calibrator._setup)
    try:
        results = calibrator.multi_site_calibrate(
            sites=sites,
            mode="simultaneous",
            n_iterations=config["n_iterations"],
            algorithm=config["algorithm"][1],
            parallel=config.get("use_parallel", False),
            verbose=False,
            progress_callback=_make_progress_callback(state),
            progress_counter_dir=str(_poll_dir),
            cancel_state=state,
            cancel_file=_cancel_file_path,
        )
    finally:
        _detach_progress_polling(_poll_stop, _poll_dir)
    _check_cancel(state)

    state.result_calibration_result = results.metrics
    state.result_best_parameters = results.best_parameters
    state.result_calibration_results_full = results

    # Store upstream subbasins so the Results page can scope parameter
    # application to only the calibrated subbasins.
    _ups = config.get("upstream_subbasins")
    if not _ups and config.get("use_partial_basin"):
        _ups = kwargs.get("upstream_subbasins")
    if _ups:
        state.result_section_subbasins = sorted(_ups)


def _run_sequential(state: CalibrationState, config: dict, model):
    _algo = config.get("algorithm", ("", "sceua"))[1] if config.get("algorithm") else "sceua"
    if _algo in ("diagnostic", "diagnostic_ensemble"):
        _run_diagnostic_sequential(state, config, model)
        return

    from swat_modern.calibration.sequential import SequentialCalibrator

    seq = SequentialCalibrator(
        model=model,
        objective=config["objective"][1],
        use_partial_basin=config.get("use_partial_basin", True),
        qswat_shapes_dir=config.get("qswat_shapes_dir"),
    )

    for site in config["calibration_sites"]:
        seq.add_site(
            reach_id=site["reach_id"],
            observed=site["observed"],
            weight=site.get("weight", 1.0),
            upstream_subbasins=site.get("upstream_subbasins"),
        )

    # SequentialCalibrator runs N steps × n_iterations sims; the UI bar
    # tracks total accumulated SWAT runs across all steps.
    _n_steps_seq = len(config.get("calibration_sites", []))
    if _n_steps_seq > 1:
        state.total_iterations = config["n_iterations"] * _n_steps_seq

    # File-based progress counter — shared across all sequential steps.
    # Each step's SubbasinGroupSetup writes per-PID counts here; the
    # polling thread aggregates them and updates state.simulation_count.
    import tempfile
    from pathlib import Path
    _seq_counter_dir = Path(tempfile.mkdtemp(prefix="swat_cal_progress_"))
    _seq_poll_stop = threading.Event()

    def _seq_poll():
        while not _seq_poll_stop.is_set():
            total = 0
            try:
                for f in _seq_counter_dir.glob("*.count"):
                    try:
                        total += int(f.read_text().strip() or "0")
                    except (ValueError, OSError):
                        pass
            except OSError:
                pass
            if total > 0:
                state.simulation_count = total
                if state.start_time:
                    elapsed = time.time() - state.start_time
                    state.elapsed_seconds = elapsed
                    state.avg_time_per_sim = elapsed / total
            _seq_poll_stop.wait(1.5)

    _seq_poll_thread = threading.Thread(
        target=_seq_poll, daemon=True, name="swat-seq-progress-poll",
    )
    _seq_poll_thread.start()

    _seq_kwargs: dict = dict(
        parameters=config["selected_params"],
        n_iterations=config["n_iterations"],
        algorithm=config["algorithm"][1],
        warmup_years=config["warmup_years"],
        output_variable=config.get("output_variable", "FLOW_OUTcms"),
        output_type=config.get("output_type", "rch"),
        parallel=config.get("use_parallel", False),
        verbose=False,
        progress_callback=_make_sequential_callback(state),
        print_code=config.get("calibration_print_code"),
        cancel_state=state,
        cancel_file=config.get("_cancel_file_path"),
        progress_counter_dir=str(_seq_counter_dir),
    )
    if config.get("custom_sim_period"):
        _seq_kwargs["custom_sim_period"] = config["custom_sim_period"]

    try:
        seq_results = seq.run(**_seq_kwargs)
    finally:
        _seq_poll_stop.set()
        try:
            import shutil as _sh
            _sh.rmtree(str(_seq_counter_dir), ignore_errors=True)
        except Exception:
            pass
    _check_cancel(state)

    state.result_sequential_results = seq_results
    last_step = seq_results.steps[-1]
    state.result_calibration_result = last_step.metrics or {}
    all_best: dict = {}
    for step in seq_results.steps:
        if step.best_params:
            all_best.update(step.best_params)
    state.result_best_parameters = all_best
    state.result_calibration_results_full = seq_results


def _run_diagnostic_sequential(state: CalibrationState, config: dict, model):
    from swat_modern.calibration.sequential import SequentialDiagnosticCalibrator

    seq = SequentialDiagnosticCalibrator(
        model=model,
        objective=config["objective"][1],
        qswat_shapes_dir=config.get("qswat_shapes_dir"),
        use_partial_basin=config.get("use_partial_basin", True),
    )

    for site in config["calibration_sites"]:
        seq.add_site(
            reach_id=site["reach_id"],
            observed=site["observed"],
            weight=site.get("weight", 1.0),
            upstream_subbasins=site.get("upstream_subbasins"),
        )

    _check_cancel(state)

    # Separate step-level and run-level callbacks to avoid ambiguity
    # when n_sites == n_ensemble_workers (both produce total_steps with
    # the same value, making it impossible to distinguish levels).
    import re as _re_seq
    _n_sites = len(config["calibration_sites"])
    _is_ensemble = config.get("algorithm", ("", ""))[1] == "diagnostic_ensemble"
    # Auto-upgrade to ensemble when parallel is requested
    _use_parallel = config.get("use_parallel", False)
    if _use_parallel and not _is_ensemble:
        _is_ensemble = True
    _n_workers = config.get("n_ensemble_workers", 4)
    if _is_ensemble and _n_workers < 2:
        import os as _os_seq
        _n_workers = config.get("n_cores") or min(4, _os_seq.cpu_count() or 1)
    # For ensemble, workers report total runs across all workers per step
    # (up to n_workers * max_iterations). For non-ensemble, per-run (0..max_iter).
    _max_per_step = (_n_workers * config["n_iterations"]) if _is_ensemble else config["n_iterations"]
    state.total_iterations = _max_per_step * _n_sites
    _current_step = [0]  # closure var: current sequential step (1-based)

    def _step_cb(step_num, total_steps, message):
        """Step-level: called by SequentialDiagnosticCalibrator."""
        _check_cancel(state)
        _current_step[0] = step_num
        state.current_step = step_num
        state.total_steps = _n_sites
        state.step_message = message

    def _run_cb(run_num, max_runs, message):
        """Run-level: called by DiagnosticCalibrator / Ensemble within a step."""
        _check_cancel(state)
        completed_steps = max(_current_step[0] - 1, 0)
        sim_count = completed_steps * _max_per_step + run_num
        state.simulation_count = sim_count
        # Update timing for ETA computation
        if state.start_time:
            elapsed = time.time() - state.start_time
            state.elapsed_seconds = elapsed
            if sim_count > 0:
                state.avg_time_per_sim = elapsed / sim_count
        # Extract best KGE from message for display
        _m = _re_seq.search(r"KGE=([0-9.\-]+)", message)
        if _m:
            try:
                _kge = float(_m.group(1))
                if _kge > state.best_score:
                    state.best_score = _kge
            except (ValueError, TypeError):
                pass

    seq_results = seq.run(
        parameter_names=config["selected_params"],
        max_iterations_per_step=config["n_iterations"],
        kge_target=config.get("kge_target", 0.70),
        pbias_target=config.get("pbias_target", 10.0),
        warmup_years=config["warmup_years"],
        output_variable=config.get("output_variable", "FLOW_OUTcms"),
        verbose=False,
        progress_callback=_step_cb,
        run_progress_callback=_run_cb,
        use_ensemble=_is_ensemble,
        n_ensemble_workers=_n_workers,
        custom_sim_period=config.get("custom_sim_period"),
        cancel_state=state,
        cancel_file=config.get("_cancel_file_path"),
        print_code=config.get("calibration_print_code"),
    )
    _check_cancel(state)

    state.result_sequential_results = seq_results
    last_step = seq_results.steps[-1]
    state.result_calibration_result = last_step.metrics or {}
    all_best: dict = {}
    for step in seq_results.steps:
        if step.best_params:
            all_best.update(step.best_params)
    state.result_best_parameters = all_best
    state.result_calibration_results_full = seq_results


def _run_partial_section(state: CalibrationState, config: dict, model):
    """Run calibration on a partial section of the watershed.

    Calibrates only the subbasins between start and end points,
    keeping upstream subbasins locked at their current parameter values.
    """
    _algo = (
        config.get("algorithm", ("", "sceua"))[1]
        if config.get("algorithm")
        else "sceua"
    )

    if _algo in ("diagnostic", "diagnostic_ensemble"):
        _run_partial_section_diagnostic(state, config, model)
        return

    _run_partial_section_spotpy(state, config, model)


def _run_partial_section_spotpy(state: CalibrationState, config: dict, model):
    """SPOTPY-based partial section calibration."""
    from swat_modern.calibration import Calibrator
    from swat_modern.calibration.spotpy_setup import SubbasinGroupSetup

    section_subs = config.get("section_subbasins", [])
    if not section_subs:
        # Fallback: compute from topology
        from swat_modern.io.parsers.fig_parser import get_section_subbasins

        _shapes = config.get("qswat_shapes_dir")
        _fig = model.project_dir / "fig.fig"
        section_subs, _ = get_section_subbasins(
            config["partial_section_start"],
            config["partial_section_end"],
            shapes_dir=_shapes,
            fig_path=_fig,
        )
        section_subs = sorted(section_subs)

    setup_kwargs: dict = dict(
        model=model,
        parameters=config["selected_params"],
        observed_data=config["single_site_observed"],
        subbasin_ids=section_subs,
        locked_parameters={},  # upstream stays at current TxtInOut values
        output_variable=config.get("output_variable", "FLOW_OUTcms"),
        output_type=config.get("output_type", "rch"),
        reach_id=config["single_reach"],
        objective=config["objective"][1],
        warmup_years=config["warmup_years"],
        print_code=config.get("calibration_print_code"),
        qswat_shapes_dir=config.get("qswat_shapes_dir"),
    )
    if config.get("use_partial_basin"):
        setup_kwargs["partial_basin_reach"] = config["single_reach"]
    if config.get("custom_sim_period"):
        setup_kwargs["custom_sim_period"] = config["custom_sim_period"]

    setup = SubbasinGroupSetup(**setup_kwargs)
    setup._cancel_state = state
    setup._cancel_event = state.cancel_event
    _cancel_file_path = config.get("_cancel_file_path")
    if _cancel_file_path:
        setup._cancel_file = _cancel_file_path
    state.register_working_dir(str(setup._working_dir))

    # Build a lightweight Calibrator wrapper around the SubbasinGroupSetup
    # so we can reuse auto_calibrate's algorithm dispatch + result extraction.
    cal_kwargs: dict = dict(
        model=model,
        observed_data=config["single_site_observed"],
        parameters=config["selected_params"],
        output_variable=config.get("output_variable", "FLOW_OUTcms"),
        output_type=config.get("output_type", "rch"),
        reach_id=config["single_reach"],
        objective=config["objective"][1],
        warmup_years=config["warmup_years"],
        print_code=config.get("calibration_print_code"),
        upstream_subbasins=config.get("upstream_subbasins"),
        qswat_shapes_dir=config.get("qswat_shapes_dir"),
    )
    if config.get("custom_sim_period"):
        cal_kwargs["custom_sim_period"] = config["custom_sim_period"]

    calibrator = Calibrator(**cal_kwargs)

    # Replace the default setup with our SubbasinGroupSetup
    calibrator._setup.cleanup()
    calibrator._setup = setup

    # File-based progress polling — needed so SPOTPY parallel workers
    # report sim count back to the UI.
    _poll_stop, _poll_dir = _attach_progress_polling(state, calibrator._setup)
    try:
        results = calibrator.auto_calibrate(
            n_iterations=config["n_iterations"],
            algorithm=config["algorithm"][1],
            parallel=config.get("use_parallel", False),
            n_cores=config.get("n_cores"),
            verbose=False,
            progress_callback=_make_progress_callback(state),
            n_ensemble_workers=config.get("n_ensemble_workers", 4),
            kge_target=config.get("kge_target", 0.70),
            pbias_target=config.get("pbias_target", 10.0),
        )
    finally:
        _detach_progress_polling(_poll_stop, _poll_dir)
    _check_cancel(state)

    results.reach_id = config["single_reach"]
    state.result_calibration_result = results.metrics
    state.result_best_parameters = results.best_parameters
    state.result_calibration_results_full = {
        "metrics": results.metrics,
        "best_parameters": results.best_parameters,
        "section_subbasins": section_subs,
        "calibration_result": results,
    }
    # Store section subbasins so the Results page can scope parameter
    # application to only the calibrated subbasins.
    state.result_section_subbasins = section_subs


def _run_partial_section_diagnostic(state: CalibrationState, config: dict, model):
    """Diagnostic-algorithm partial section calibration."""
    import re as _re_ps

    section_subs = config.get("section_subbasins", [])
    if not section_subs:
        from swat_modern.io.parsers.fig_parser import get_section_subbasins

        _shapes = config.get("qswat_shapes_dir")
        _fig = model.project_dir / "fig.fig"
        section_subs, _ = get_section_subbasins(
            config["partial_section_start"],
            config["partial_section_end"],
            shapes_dir=_shapes,
            fig_path=_fig,
        )
        section_subs = sorted(section_subs)

    _is_ensemble = config.get("algorithm", ("", ""))[1] == "diagnostic_ensemble"
    # Auto-upgrade to ensemble when parallel is requested
    _use_parallel = config.get("use_parallel", False)
    if _use_parallel and not _is_ensemble:
        _is_ensemble = True

    import os as _os_ps
    _n_workers = config.get("n_ensemble_workers", 4)
    if _is_ensemble and _n_workers < 2:
        _n_workers = config.get("n_cores") or min(4, _os_ps.cpu_count() or 1)

    _max_runs = config["n_iterations"]
    if _is_ensemble:
        _max_runs = _n_workers * config["n_iterations"]
    state.total_iterations = _max_runs

    def _run_cb(run_num, max_runs, message):
        _check_cancel(state)
        state.simulation_count = run_num
        if state.start_time:
            elapsed = time.time() - state.start_time
            state.elapsed_seconds = elapsed
            if run_num > 0:
                state.avg_time_per_sim = elapsed / run_num
        _m = _re_ps.search(r"KGE=([0-9.\-]+)", message)
        if _m:
            try:
                _kge = float(_m.group(1))
                if _kge > state.best_score:
                    state.best_score = _kge
            except (ValueError, TypeError):
                pass

    diag_kwargs: dict = dict(
        parameter_names=config["selected_params"],
        reach_id=config["single_reach"],
        output_variable=config.get("output_variable", "FLOW_OUTcms"),
        warmup_years=config["warmup_years"],
        max_iterations=config["n_iterations"],
        kge_target=config.get("kge_target", 0.70),
        pbias_target=config.get("pbias_target", 10.0),
        qswat_shapes_dir=config.get("qswat_shapes_dir"),
        subbasin_ids=section_subs,
        locked_parameters=None,
        progress_callback=_run_cb,
        custom_sim_period=config.get("custom_sim_period"),
        cancel_state=state,
        partial_basin_reach=config["single_reach"] if config.get("use_partial_basin") else None,
        print_code=config.get("calibration_print_code"),
    )

    _cancel_file_path = config.get("_cancel_file_path")

    if _is_ensemble:
        from swat_modern.calibration.diagnostic_calibrator import (
            EnsembleDiagnosticCalibrator,
        )

        calibrator = EnsembleDiagnosticCalibrator(
            model=model,
            observed_df=config["single_site_observed"],
            n_workers=_n_workers,
            **diag_kwargs,
        )
        # EnsembleDiagnosticCalibrator manages its own cancel file and
        # registers it on ``state`` inside ``calibrate()`` — nothing to
        # inject here.  The shared cancel file + the ensemble's own file
        # are both written by ``state.request_cancel()``.
    else:
        from swat_modern.calibration.diagnostic_calibrator import (
            DiagnosticCalibrator,
        )

        calibrator = DiagnosticCalibrator(
            model=model,
            observed_df=config["single_site_observed"],
            **diag_kwargs,
        )
        # Non-ensemble: propagate the shared cross-process cancel flag
        # so ``DiagnosticCalibrator._check_cancel`` sees file-based cancel.
        if _cancel_file_path:
            calibrator._cancel_file = _cancel_file_path

    # Register working dir for cleanup on cancel
    if hasattr(calibrator, "_working_dir") and calibrator._working_dir:
        state.register_working_dir(str(calibrator._working_dir))

    result = calibrator.calibrate()
    _check_cancel(state)

    result.reach_id = config["single_reach"]
    state.result_calibration_result = dict(result.best_metrics)
    state.result_best_parameters = dict(result.best_parameters)
    state.result_calibration_results_full = result
    # Store section subbasins so the Results page can scope parameter
    # application to only the calibrated subbasins.
    state.result_section_subbasins = section_subs


def _run_multi_constituent(state: CalibrationState, config: dict, model):
    """Run phased multi-constituent calibration (Flow -> Sed -> N -> P)."""
    from swat_modern.calibration.phased_calibrator import PhasedCalibrator

    flow_obs = config["single_site_observed"]
    wq_obs = config.get("wq_observations")
    reach_id = config.get("single_reach", 1)
    phases = config.get("phased_config")

    # Build extra kwargs for PhasedCalibrator
    extra_kwargs = {}
    if config.get("upstream_subbasins"):
        extra_kwargs["upstream_subbasins"] = config["upstream_subbasins"]
    if config.get("qswat_shapes_dir"):
        extra_kwargs["qswat_shapes_dir"] = config["qswat_shapes_dir"]
    if config.get("calibration_print_code") is not None:
        extra_kwargs["print_code"] = config["calibration_print_code"]
    if config.get("custom_sim_period"):
        extra_kwargs["custom_sim_period"] = config["custom_sim_period"]

    # Count enabled phases for progress tracking
    enabled_phases = [p for p in phases if p.enabled] if phases else []
    state.total_steps = len(enabled_phases)

    # Estimate total iterations across all enabled phases
    total_iter = sum(p.n_iterations for p in enabled_phases) if enabled_phases else 0
    state.total_iterations = total_iter

    # Cumulative simulation count offset (across phases)
    _phase_offset = [0]  # closure var

    def _phased_progress(info: dict):
        """Progress callback from PhasedCalibrator."""
        _check_cancel(state)
        phase_idx = info.get("phase_index", 0)
        total_phases = info.get("total_phases", 1)
        phase_name = info.get("phase", "")
        status = info.get("status", "")

        state.current_step = phase_idx + 1
        state.total_steps = total_phases
        state.step_message = f"{phase_name.replace('_', ' ').title()} -- {status}"

        # Update simulation count from inner SPOTPY callback fields
        sim_count = info.get("simulation_count", 0)
        if sim_count > 0:
            state.simulation_count = _phase_offset[0] + sim_count

        best = info.get("best_score", None)
        if best is not None and best > state.best_score:
            state.best_score = best

        elapsed = info.get("elapsed_seconds", 0)
        if elapsed > 0:
            state.elapsed_seconds = elapsed
            current_total = _phase_offset[0] + sim_count
            if current_total > 0:
                state.avg_time_per_sim = (
                    (time.time() - state.start_time) / current_total
                )

        # When a phase completes, update the offset for the next phase
        if status == "completed" and enabled_phases:
            completed_iters = sum(
                p.n_iterations
                for p in enabled_phases[: phase_idx + 1]
            )
            _phase_offset[0] = completed_iters

    calibrator = PhasedCalibrator(
        model=model,
        flow_observations=flow_obs,
        wq_observations=wq_obs,
        reach_id=reach_id,
        phases=phases,
        warmup_years=config.get("warmup_years", 1),
        progress_callback=_phased_progress,
        cancel_state=state,
        cancel_file=config.get("_cancel_file_path"),
        kge_target=config.get("kge_target", 0.70),
        pbias_target=config.get("pbias_target", 10.0),
        parallel=config.get("use_parallel", False),
        n_cores=config.get("n_cores"),
        n_ensemble_workers=config.get("n_ensemble_workers", 4),
        **extra_kwargs,
    )
    # Register working dir for cleanup on cancel
    if hasattr(calibrator, "_working_dir") and calibrator._working_dir:
        state.register_working_dir(str(calibrator._working_dir))

    phased_result = calibrator.calibrate()
    _check_cancel(state)

    # Store phased result for the UI
    state.result_phased_results = phased_result

    # Also store summary metrics and best params for the standard results display
    state.result_best_parameters = phased_result.all_best_parameters

    # Use the last completed phase's metrics as the headline metric
    _last_metrics = {}
    for pr in reversed(phased_result.phase_results):
        if pr.get("metrics"):
            _last_metrics = pr["metrics"]
            break
    state.result_calibration_result = _last_metrics
    state.result_calibration_results_full = phased_result


# ---------------------------------------------------------------------------
# Sensitivity analysis background runner
# ---------------------------------------------------------------------------

def start_sensitivity(config: dict) -> CalibrationState:
    """Start sensitivity analysis in a background daemon thread.

    Parameters
    ----------
    config : dict
        Keys: project_path, swat_executable, selected_params, objective,
        warmup_years, calibration_print_code, sa_method ("fast" or "sobol"),
        sa_n_samples (int), single_reach, single_site_observed,
        upstream_subbasins, qswat_shapes_dir, output_variable, output_type,
        use_partial_basin, custom_sim_period, use_custom_boundaries,
        boundary_manager.
    """
    state = CalibrationState()
    state.mode = "sensitivity"
    n_params = len(config.get("selected_params", []))
    n_samples = config.get("sa_n_samples", 50)
    sa_method = config.get("sa_method", "fast")
    # For FAST, the calibrator enforces a minimum of 65 per-parameter
    # and passes n_samples * n_params as total repetitions to SPOTPY.
    if sa_method == "fast":
        _effective = max(n_samples, 65)
        state.total_iterations = _effective * max(n_params, 1)
    else:
        state.total_iterations = n_samples * max(n_params, 1)
    state.status = "running"
    state.start_time = time.time()

    thread = threading.Thread(
        target=_run_sensitivity_background,
        args=(state, config),
        daemon=True,
        name="swat-sensitivity",
    )
    state._thread = thread
    thread.start()

    global _active_sa_state
    _active_sa_state = state

    return state


def _run_sensitivity_background(state: CalibrationState, config: dict):
    """Thread target – runs sensitivity analysis."""
    try:
        import logging
        logging.getLogger(
            "streamlit.runtime.scriptrunner_utils.script_run_context"
        ).setLevel(logging.ERROR)

        from pathlib import Path
        from swat_modern import SWATModel
        from swat_modern.calibration import Calibrator

        exe_path = (config.get("swat_executable") or "").strip() or None
        model = SWATModel(config["project_path"], executable=exe_path)

        _cal_mode = config.get("calibration_mode", "single")
        _cal_sites = config.get("calibration_sites")
        _is_multisite = _cal_mode in ("simultaneous", "sequential") and _cal_sites

        if _is_multisite:
            # Multi-site SA: create Calibrator with first site for init,
            # then swap _setup with a MultiSiteSetup that evaluates all sites.
            first_site = _cal_sites[0]
            kwargs = dict(
                model=model,
                observed_data=first_site["observed"],
                parameters=config["selected_params"],
                output_variable=config.get("output_variable", "FLOW_OUTcms"),
                output_type=config.get("output_type", "rch"),
                reach_id=first_site["reach_id"],
                objective=config["objective"][1],
                warmup_years=config["warmup_years"],
                print_code=config.get("calibration_print_code"),
                qswat_shapes_dir=config.get("qswat_shapes_dir"),
            )
            if config.get("custom_sim_period"):
                kwargs["custom_sim_period"] = config["custom_sim_period"]
            if config.get("use_custom_boundaries") and config.get("boundary_manager"):
                kwargs["parameters"] = config["boundary_manager"].to_parameter_set()

            calibrator = Calibrator(**kwargs)

            # Replace the single-site setup with a multi-site setup
            from swat_modern.calibration.spotpy_setup import MultiSiteSetup
            ms_kwargs = dict(
                model=model,
                parameters=calibrator.parameter_set,
                sites=_cal_sites,
                output_variable=config.get("output_variable", "FLOW_OUTcms"),
                output_type=config.get("output_type", "rch"),
                objective=config["objective"][1],
                warmup_years=config["warmup_years"],
                print_code=config.get("calibration_print_code"),
                qswat_shapes_dir=config.get("qswat_shapes_dir"),
            )
            if config.get("custom_sim_period"):
                ms_kwargs["custom_sim_period"] = config["custom_sim_period"]

            # Partial-basin: compute union of upstream subs for all target reaches
            if config.get("use_partial_basin"):
                from swat_modern.io.parsers.fig_parser import get_multi_reach_active_subs
                _fig_path = model.project_dir / "fig.fig"
                _target_reaches = [s["reach_id"] for s in _cal_sites]
                _union_subs, _most_downstream = get_multi_reach_active_subs(
                    _fig_path, _target_reaches,
                )
                if _most_downstream:
                    ms_kwargs["partial_basin_reach"] = _most_downstream
                    ms_kwargs["upstream_subbasins"] = sorted(_union_subs) if _union_subs else None

            # Clean up the single-site setup before replacing
            calibrator._setup.cleanup()
            calibrator._setup = MultiSiteSetup(**ms_kwargs)
        else:
            # Single-site SA
            kwargs = dict(
                model=model,
                observed_data=config["single_site_observed"],
                parameters=config["selected_params"],
                output_variable=config.get("output_variable", "FLOW_OUTcms"),
                output_type=config.get("output_type", "rch"),
                reach_id=config["single_reach"],
                objective=config["objective"][1],
                warmup_years=config["warmup_years"],
                print_code=config.get("calibration_print_code"),
                upstream_subbasins=config.get("upstream_subbasins"),
                qswat_shapes_dir=config.get("qswat_shapes_dir"),
            )

            if config.get("custom_sim_period"):
                kwargs["custom_sim_period"] = config["custom_sim_period"]

            if config.get("use_custom_boundaries") and config.get("boundary_manager"):
                kwargs["parameters"] = config["boundary_manager"].to_parameter_set()

            if config.get("use_partial_basin"):
                kwargs["partial_basin_reach"] = config["single_reach"]

            calibrator = Calibrator(**kwargs)

        # Estimate total runs so the UI can show a real progress bar.
        # SPOTPY FAST divides repetitions by n_params internally
        # (N_per_param = ceil(repetitions / n_params)), so passing
        # n_samples * n_params gives n_samples per parameter.
        # The calibrator enforces a minimum of 65 per-parameter for FAST.
        n_params = len(config["selected_params"])
        sa_n_samples = config.get("sa_n_samples", 50)
        sa_method = config.get("sa_method", "fast")

        if sa_method == "fast":
            # Apply the same minimum the calibrator will enforce
            _effective_per_param = max(sa_n_samples, 65)
            state.total_iterations = _effective_per_param * n_params
        else:
            # Sobol/LHS: total = n_samples * n_params
            state.total_iterations = sa_n_samples * n_params

        _setup = calibrator._setup
        _setup._cancel_state = state  # simulation() checks this for cancel
        _setup._cancel_event = state.cancel_event
        state.register_working_dir(str(_setup._working_dir))
        _is_parallel = config.get("sa_parallel", False)
        _poll_stop = threading.Event()

        # File-based cancel flag: works across processes (parallel mode).
        # simulation() checks if this file exists and returns NaN.
        # The polling thread creates the file when state.cancel_requested
        # becomes True.
        import tempfile
        from pathlib import Path

        _cancel_file = Path(
            tempfile.mkdtemp(prefix="swat_sa_cancel_")
        ) / "cancel.flag"
        _setup._cancel_file = str(_cancel_file)
        # Register on state so request_cancel() writes it immediately
        state.register_cancel_file(str(_cancel_file))

        # Progress callback — same mechanism that calibration uses.
        # For sequential mode this directly updates state from within
        # simulation(), which is the most reliable approach.
        # For parallel mode, the callback is nulled by __getstate__
        # (can't cross process boundaries), so we also set up a
        # counter-file polling thread below.
        def _sa_progress_cb(info):
            state.simulation_count = info["simulation_count"]
            state.elapsed_seconds = info.get("elapsed_seconds", 0)
            state.avg_time_per_sim = info.get("avg_time_per_sim", 0)

        _setup.progress_callback = _sa_progress_cb

        if _is_parallel:
            # Parallel mode: worker processes get serialised copies of the
            # setup object, so closure-based state tracking doesn't work.
            # Instead, each worker writes its simulation count to a
            # PID-named file in a shared temp directory.  A polling thread
            # in *this* thread reads those files and updates ``state``.
            _counter_dir = Path(
                tempfile.mkdtemp(prefix="swat_sa_progress_")
            )
            _setup._progress_counter_dir = str(_counter_dir)

            def _poll_counter_dir():
                while not _poll_stop.is_set():
                    # Propagate cancel to file for worker processes
                    if state.cancel_requested and not _cancel_file.exists():
                        _cancel_file.write_text("cancelled")
                    total = 0
                    try:
                        for f in _counter_dir.glob("*.count"):
                            try:
                                total += int(f.read_text().strip() or "0")
                            except (ValueError, OSError):
                                pass
                    except OSError:
                        pass
                    state.simulation_count = total
                    state.elapsed_seconds = time.time() - (
                        state.start_time or time.time()
                    )
                    if total > 0:
                        state.avg_time_per_sim = (
                            state.elapsed_seconds / total
                        )
                    _poll_stop.wait(2)

            _poll_thread = threading.Thread(
                target=_poll_counter_dir, daemon=True
            )
            _poll_thread.start()

        try:
            results = calibrator.sensitivity_analysis(
                n_samples=sa_n_samples,
                method=sa_method,
                parallel=_is_parallel,
                n_cores=config.get("sa_n_cores"),
                verbose=False,
            )
        finally:
            _poll_stop.set()
            _setup.progress_callback = None  # break ref cycle
            # Clean up cancel file and counter dir
            import shutil
            shutil.rmtree(str(_cancel_file.parent), ignore_errors=True)
            if _is_parallel:
                shutil.rmtree(str(_counter_dir), ignore_errors=True)

        # Check if cancellation was requested (the NaN-return approach
        # lets SPOTPY finish its loop quickly without raising).
        if state.cancel_requested:
            state.status = "cancelled"
            state.error_message = "Sensitivity analysis was cancelled by user."
            return

        state.result_sensitivity = results
        state.elapsed_seconds = time.time() - state.start_time
        state.status = "completed"

    except CalibrationCancelled:
        state.status = "cancelled"
        state.error_message = "Sensitivity analysis was cancelled by user."

    except ImportError as exc:
        state.status = "failed"
        state.error_message = f"Missing required package: {exc}"
        state.error_traceback = traceback.format_exc()

    except Exception as exc:
        # If user requested cancel, NaN results may crash SPOTPY's
        # post-analysis (e.g. Fourier decomposition in FAST).
        # Treat that as cancellation, not failure.
        if state.cancel_requested:
            state.status = "cancelled"
            state.error_message = "Sensitivity analysis was cancelled by user."
        else:
            state.status = "failed"
            state.error_message = f"Sensitivity analysis failed: {exc}"
            state.error_traceback = traceback.format_exc()

    except BaseException as exc:
        # Safety net for _CancelSignal (BaseException)
        if state.cancel_requested:
            state.status = "cancelled"
            state.error_message = "Sensitivity analysis was cancelled by user."
        else:
            state.status = "failed"
            state.error_message = f"Sensitivity analysis failed: {exc}"
            state.error_traceback = traceback.format_exc()
