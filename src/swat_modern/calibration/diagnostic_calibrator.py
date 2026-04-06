"""
Diagnostic-guided calibration for SWAT models.

Instead of blindly sampling parameter space (SCE-UA, DREAM, etc.), this
calibrator analyzes sim-vs-obs hydrographs to identify *which* parameters
need adjusting and *by how much*, converging in 5-20 SWAT runs.

Algorithm:
    Phase 0 — Baseline: run current params, diagnose, early-exit if OK
    Phase 1 — Volume correction: ESCO, CN2 to fix total volume bias
    Phase 2 — Baseflow partition: GWQMN, RCHRG_DP, ALPHA_BF, GW_DELAY
    Phase 3 — Peak correction: CN2, SURLAG
    Phase 4 — Fine-tuning: remaining diagnostic recommendations

Each phase uses proportional heuristics for the first step and a secant
method (linear interpolation from two data points) for subsequent steps.

Does NOT use SPOTPY — manages backup/restore/run directly.

Reference approach:
    SWATtunR (Becker et al.) secant-based auto-calibration concept,
    extended with Eckhardt baseflow separation, Yilmaz FDC decomposition,
    and Gupta KGE decomposition.
"""

import os
import time
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from swat_modern.calibration.diagnostics import (
    diagnose,
    estimate_adjustment,
    flow_duration_curve_metrics,
    kge_components,
    DiagnosticReport,
)

# Process-diagnostic imports — these are added by Worker-1.
# Guard with try/except so the module still loads before Worker-1 merges.
try:
    from swat_modern.calibration.diagnostics import (
        diagnose_sediment,
        diagnose_phosphorus,
        diagnose_nitrogen,
    )
except ImportError:  # pragma: no cover
    diagnose_sediment = None  # type: ignore[assignment,misc]
    diagnose_phosphorus = None  # type: ignore[assignment,misc]
    diagnose_nitrogen = None  # type: ignore[assignment,misc]
from swat_modern.calibration.objectives import evaluate_model, kge, pbias
from swat_modern.calibration.parameters import (
    CALIBRATION_PARAMETERS,
    CalibrationParameter,
    ParameterSet,
)
from swat_modern.calibration.spotpy_setup import run_baseline_simulation


class _DiagnosticCancelled(Exception):
    """Raised when diagnostic calibration is cancelled by the user."""


# ── Dataclasses ──────────────────────────────────────────────────────────

@dataclass
class DiagnosticStep:
    """Record of a single diagnostic calibration iteration."""

    iteration: int
    phase: str  # "baseline", "volume", "baseflow", "peaks", "finetune"
    parameters: Dict[str, float]  # full parameter snapshot
    adjustments: Dict[str, float]  # what changed this step
    metrics: Dict[str, float]  # KGE, PBIAS, etc.
    diagnostic_summary: Dict  # condensed DiagnosticReport.summary_dict()
    runtime: float = 0.0  # elapsed time for this step (seconds)


@dataclass
class DiagnosticCalibrationResult:
    """Result container for diagnostic-guided calibration."""

    best_parameters: Dict[str, float]
    best_metrics: Dict[str, float]
    steps: List[DiagnosticStep]
    total_runs: int
    runtime: float
    converged: bool
    convergence_reason: str
    observed: np.ndarray
    simulated: np.ndarray
    dates: Optional[np.ndarray] = None

    def to_calibration_result(self):
        """Convert to CalibrationResult for UI compatibility."""
        from swat_modern.calibration.calibrator import CalibrationResult

        # Build a DataFrame of all parameter sets tried
        rows = []
        for step in self.steps:
            row = dict(step.parameters)
            row["_iteration"] = step.iteration
            row["_phase"] = step.phase
            rows.append(row)
        all_params = pd.DataFrame(rows) if rows else pd.DataFrame()

        # Build objectives array (KGE per step)
        all_obj = np.array([s.metrics.get("kge", np.nan) for s in self.steps])

        return CalibrationResult(
            best_parameters=self.best_parameters,
            best_objective=self.best_metrics.get("kge", np.nan),
            all_parameters=all_params,
            all_objectives=all_obj,
            observed=self.observed,
            simulated=self.simulated,
            runtime=self.runtime,
            n_iterations=self.total_runs,
            algorithm="diagnostic",
            metrics=self.best_metrics,
            dates=self.dates,
            objective_name="kge",
        )


# ── Phase definitions ────────────────────────────────────────────────────

# Parameters to try per phase (order matters — first is primary lever)
PHASE_PARAMS = {
    "volume": ["ESCO", "CN2"],
    "baseflow": ["GWQMN", "RCHRG_DP", "ALPHA_BF", "GW_DELAY"],
    "peaks": ["CN2", "SURLAG"],
    "finetune": ["GW_REVAP", "REVAPMN", "EPCO", "OV_N", "SOL_AWC", "CH_N2"],
}

# Sediment diagnostic phases
SEDIMENT_PHASE_PARAMS = {
    "sed_volume": ["USLE_P", "SPCON", "ADJ_PKR"],
    "sed_dynamics": ["SPEXP", "CH_COV1", "CH_COV2", "PRF"],
    "sed_finetune": ["LAT_SED", "USLE_K", "SLSUBBSN"],
}

# Nitrogen diagnostic phases
NITROGEN_PHASE_PARAMS = {
    "n_volume": ["CMN", "NPERCO", "CDN"],
    "n_dynamics": ["N_UPDIS", "SDNCO", "ERORGN"],
}

# Phosphorus diagnostic phases
PHOSPHORUS_PHASE_PARAMS = {
    "p_volume": ["PPERCO", "PHOSKD", "PSP"],
    "p_dynamics": ["P_UPDIS", "ERORGP", "GWSOLP"],
}


# ── Main Calibrator ─────────────────────────────────────────────────────

class DiagnosticCalibrator:
    """
    Diagnostic-guided SWAT calibrator.

    Analyzes hydrograph deficiencies and adjusts parameters in targeted
    phases, typically converging in 5-20 SWAT runs.

    Args:
        model: SWATModel instance.
        observed_df: DataFrame with 'date' and 'observed' columns.
        parameter_names: Parameter names to calibrate (default: streamflow set).
        reach_id: Reach/subbasin ID for output extraction.
        output_variable: SWAT output variable (default "FLOW_OUT").
        warmup_years: Extra warmup years to skip beyond file.cio NYSKIP.
        max_iterations: Maximum total SWAT runs (default 15).
        kge_target: KGE convergence target (default 0.70).
        pbias_target: |PBIAS| convergence target (default 10%).
        damping: Secant method damping factor (default 0.5).
        upstream_subbasins: Explicit upstream subbasin list (for accumulated flow).
        qswat_shapes_dir: Path to QSWAT shapes for GIS-based topology.
        progress_callback: Optional callback(current_step, total_steps, message).
    """

    def __init__(
        self,
        model,
        observed_df: pd.DataFrame,
        parameter_names: Optional[List[str]] = None,
        reach_id: int = 1,
        output_variable: str = "FLOW_OUT",
        warmup_years: int = 0,
        max_iterations: int = 15,
        kge_target: float = 0.70,
        pbias_target: float = 10.0,
        damping: float = 0.5,
        upstream_subbasins: Optional[List[int]] = None,
        qswat_shapes_dir: Optional[Path] = None,
        progress_callback: Optional[Callable] = None,
        subbasin_ids: Optional[List[int]] = None,
        locked_parameters: Optional[Dict[int, Dict[str, float]]] = None,
        custom_sim_period: Optional[tuple] = None,
        cancel_state=None,
        constituent: str = "flow",
        partial_basin_reach: Optional[int] = None,
        print_code: Optional[int] = None,
        _use_working_copy: bool = True,
    ):
        # Create working copy to protect original model from modification.
        # Ensemble workers already have their own copies and pass False.
        self._working_dir: Optional[Path] = None
        if _use_working_copy and isinstance(getattr(model, "project_dir", None), Path):
            from datetime import datetime as _dt
            _ts = _dt.now().strftime("%Y%m%d_%H%M%S_%f")
            self._working_dir = model.project_dir.parent / f".swat_diag_{_ts}"
            shutil.copytree(model.project_dir, self._working_dir)
            from swat_modern.core.model import SWATModel
            model = SWATModel(str(self._working_dir), executable=model.executable)

        self.model = model
        self.observed_df = observed_df
        self.reach_id = reach_id
        self.output_variable = output_variable
        self.warmup_years = warmup_years
        self.max_iterations = max_iterations
        self.kge_target = kge_target
        self.pbias_target = pbias_target
        self.damping = damping
        self.upstream_subbasins = upstream_subbasins
        self.qswat_shapes_dir = qswat_shapes_dir
        self._progress_cb = progress_callback
        self.subbasin_ids = subbasin_ids
        self.locked_parameters = locked_parameters or {}
        self._custom_sim_period = custom_sim_period
        self._original_sim_period: Optional[tuple] = None
        self._cancel_state = cancel_state  # CalibrationState for cooperative cancel
        self._cancel_file: Optional[str] = None  # file-based cancel for cross-process
        self.constituent = constituent  # "flow", "sediment", "nitrogen", "phosphorus"
        self._print_code = print_code

        # Apply IPRINT to working copy so baseline and iteration runs use
        # the same output timestep as the observation data.
        if self._print_code is not None:
            try:
                self.model.config.output.print_code = self._print_code
                self.model.config.save()
                print(f"[diagnostic] Applied IPRINT={self._print_code} to working copy file.cio")
            except Exception as _e:
                print(f"[diagnostic] Warning: could not set IPRINT={self._print_code}: {_e}")

        # Build parameter set
        if parameter_names is None:
            parameter_names = [
                "CN2", "ESCO", "EPCO", "SURLAG", "GW_DELAY", "ALPHA_BF",
                "GWQMN", "REVAPMN", "GW_REVAP", "RCHRG_DP", "SOL_AWC",
                "OV_N", "CH_N2",
            ]

        self.parameter_set = ParameterSet()
        for name in parameter_names:
            name_upper = name.upper()
            if name_upper in CALIBRATION_PARAMETERS:
                self.parameter_set.add(name_upper)

        # Current parameter values — read actual file values for "replace"
        # method parameters so the baseline run matches the original model.
        # Hard-coded defaults (e.g. GWQMN=1000) can differ drastically from
        # actual file values (e.g. GWQMN=0), causing the calibrator to start
        # from a degraded state — especially harmful for partial-section
        # calibration where only a subset of subbasins is modified.
        self._current_values: Dict[str, float] = self.parameter_set.values
        self._init_current_values_from_model(model)

        # History per parameter: list of {"param_value": x, "metric_value": y}
        self._param_history: Dict[str, List[Dict]] = {
            n: [] for n in self.parameter_set.names
        }

        # File types that will be modified (for selective backup/restore)
        file_types_set = set()
        for p in self.parameter_set:
            file_types_set.add(p.file_type)
            # If a basin-wide param has a per-HRU equivalent (ESCO, EPCO),
            # apply_to_model() also modifies .hru files.
            if (
                p.file_type in self.parameter_set.BASIN_WIDE_TYPES
                and p.name in self.parameter_set.BSN_TO_HRU_MAP
            ):
                file_types_set.add("hru")
        # Include file types from locked parameters
        for lp_params in self.locked_parameters.values():
            for pname in lp_params:
                pdef = CALIBRATION_PARAMETERS.get(pname.upper())
                if pdef:
                    file_types_set.add(pdef.file_type)
                    if (
                        pdef.file_type in ParameterSet.BASIN_WIDE_TYPES
                        and pname.upper() in ParameterSet.BSN_TO_HRU_MAP
                    ):
                        file_types_set.add("hru")
        # Always include .cio in backup — the calibration pipeline may
        # modify IPRINT, NYSKIP, or the simulation period in file.cio.
        # Without backing it up, cleanup() can leave a corrupted .cio that
        # misaligns output dates (e.g. NYSKIP=0 persisting after calibration).
        file_types_set.add("cio")
        self._modified_file_types = sorted(file_types_set)

        # Partial-basin simulation: write active_subs.dat so the custom
        # SWAT exe skips downstream subbasins.  Uses fig.fig routing
        # (priority) to identify upstream subbasins.
        self._active_subs_file: Optional[Path] = None
        if partial_basin_reach is not None:
            self._init_partial_basin(partial_basin_reach)

        # State
        self._backup_dir: Optional[Path] = None
        self._steps: List[DiagnosticStep] = []
        self._best_kge = -np.inf
        self._best_values: Dict[str, float] = {}
        self._best_metrics: Dict[str, float] = {}
        self._best_simulated: Optional[np.ndarray] = None
        self._last_observed: Optional[np.ndarray] = None
        self._last_dates: Optional[np.ndarray] = None

        # Flow tracking for WQ process diagnostics (sediment/phosphorus)
        self._last_sim_flow: Optional[np.ndarray] = None
        self._last_obs_flow: Optional[np.ndarray] = None
        self._last_wq_report = None  # last WQ diagnostic report (for direction inference)

        # Check if observed_df has a 'flow' column for concurrent flow diagnostics
        if (
            isinstance(self.observed_df, pd.DataFrame)
            and "flow" in self.observed_df.columns
        ):
            self._last_obs_flow = self.observed_df["flow"].values.astype(float)

    # ── Parameter initialization from model files ───────────────────

    def _init_current_values_from_model(self, model) -> None:
        """Read actual parameter values from model files for 'replace' method params.

        For 'replace' method parameters, the hard-coded default_value may
        differ from the actual value in the SWAT input files (e.g.
        GWQMN default=1000 vs file=0).  Starting from wrong values causes
        the baseline run to diverge from the original model — especially
        harmful in partial-section calibration where the mismatch creates
        a discontinuity between section and locked subbasins.

        'Multiply' parameters use default=0 (no change), which is correct
        regardless of the file value.
        """
        for p in self.parameter_set:
            if p.method != "replace":
                continue
            try:
                val = model.get_parameter(
                    p.name, file_type=p.file_type,
                )
                if isinstance(val, dict):
                    # Per-unit parameter: use the mean as starting value
                    vals = [v for v in val.values() if v is not None]
                    if vals:
                        mean_val = sum(vals) / len(vals)
                        if mean_val != self._current_values[p.name]:
                            self._current_values[p.name] = round(
                                mean_val, p.decimal_precision,
                            )
                elif val is not None:
                    if val != self._current_values[p.name]:
                        self._current_values[p.name] = round(
                            float(val), p.decimal_precision,
                        )
            except Exception:
                pass  # keep default if file read fails

    # ── Partial-basin support ─────────────────────────────────────────

    def _init_partial_basin(self, partial_basin_reach: int) -> None:
        """Write active_subs.dat for partial-basin simulation.

        Uses fig.fig routing (priority) to identify upstream subbasins
        of ``partial_basin_reach``.  The file is copied into the working
        directory before each SWAT run by ``_copy_active_subs()``.
        """
        fig_path = self.model.project_dir / "fig.fig"
        if not fig_path.exists():
            print("Warning: fig.fig not found, skipping partial-basin optimization")
            return

        from swat_modern.io.parsers.fig_parser import FigFileParser
        parser = FigFileParser(fig_path)
        topo = parser.parse()

        # Translate subbasin ID → reach ID if needed
        sub_to_rch = topo["subbasin_to_reach"]
        terminal = partial_basin_reach
        if terminal not in topo["reaches"] and terminal in topo["subbasins"]:
            terminal = sub_to_rch.get(terminal, terminal)

        outlet = topo["outlet_reach"]
        if outlet is not None and terminal == outlet:
            return  # Already at outlet — no optimization possible

        active_subs = parser.get_upstream_subbasins(terminal)
        if not active_subs:
            return

        self._active_subs_file = self.model.project_dir / "active_subs_partial.dat"
        parser.write_active_subs(
            terminal,
            self._active_subs_file,
            subbasin_list=sorted(active_subs),
        )

        total_subs = len(topo["subbasins"])
        print(
            f"Partial-basin: {len(active_subs)}/{total_subs} upstream subbasins active "
            f"(downstream subbasin execution skipped via active_subs.dat)"
        )

    def _copy_active_subs(self) -> None:
        """Copy active_subs_partial.dat → active_subs.dat before a SWAT run."""
        if self._active_subs_file is not None and self._active_subs_file.exists():
            shutil.copy2(
                self._active_subs_file,
                self.model.project_dir / "active_subs.dat",
            )

    # ── Cancel support ─────────────────────────────────────────────────

    def _check_cancel(self):
        """Raise ``_DiagnosticCancelled`` if cancellation was requested.

        Two mechanisms (same pattern as SPOTPY setup):
        1. In-memory: ``_cancel_state.cancel_requested`` (same process).
        2. File-based: ``_cancel_file`` exists on disk (cross-process).
        """
        cs = self._cancel_state
        if cs is not None and getattr(cs, "cancel_requested", False):
            print("[cancel] Diagnostic calibration cancelled (in-memory flag)")
            raise _DiagnosticCancelled("Diagnostic calibration cancelled")
        cf = self._cancel_file
        if cf is not None and Path(cf).exists():
            print("[cancel] Diagnostic calibration cancelled (file flag)")
            raise _DiagnosticCancelled("Diagnostic calibration cancelled (file flag)")

    def _get_cancel_event(self):
        """Return the cancel threading.Event (or None) for passing to model.run()."""
        cs = self._cancel_state
        if cs is not None:
            return getattr(cs, "cancel_event", None)
        return None

    # ── Component-to-parent constituent mapping ─────────────────────────

    # Maps individual WQ component names (lowercase) to their parent
    # constituent diagnostic sequence.  This allows DiagnosticCalibrator
    # to accept e.g. constituent="orgp" and route it through the
    # phosphorus diagnostic phases.
    _COMPONENT_TO_PARENT = {
        # Phosphorus components
        "orgp": "phosphorus",
        "minp": "phosphorus",
        "solp": "phosphorus",
        "orgp_out": "phosphorus",
        "minp_out": "phosphorus",
        "solp_out": "phosphorus",
        # Nitrogen components
        "orgn": "nitrogen",
        "no3": "nitrogen",
        "nh4": "nitrogen",
        "no2": "nitrogen",
        "orgn_out": "nitrogen",
        "no3_out": "nitrogen",
        "nh4_out": "nitrogen",
        "no2_out": "nitrogen",
        # Sediment components
        "sedconc": "sediment",
        "sed_out": "sediment",
        "sed_con": "sediment",
    }

    def _resolve_constituent(self) -> str:
        """Return the parent constituent for phase sequence dispatch.

        If ``self.constituent`` is an individual component (e.g. ``"orgp"``),
        returns the parent (e.g. ``"phosphorus"``).  Otherwise returns the
        constituent as-is.
        """
        return self._COMPONENT_TO_PARENT.get(
            self.constituent.lower(), self.constituent
        )

    # ── Phase sequence dispatch ────────────────────────────────────────

    def _get_phase_sequence(self):
        """Return (phase_params_dict, phase_configs) for current constituent.

        Each phase_config tuple is:
            (phase_name, metric_key, target, threshold)

        For flow, the original 4-phase hydrology sequence is used.
        For WQ constituents, simplified volume + dynamics (+ finetune) phases
        are used with load-based metrics (PBIAS, NSE, R2).

        Individual WQ components (e.g. ``"orgp"``, ``"sed_out"``) are
        resolved to their parent constituent via ``_resolve_constituent()``.
        """
        parent = self._resolve_constituent()

        if parent == "flow":
            return PHASE_PARAMS, [
                ("volume", "total_pbias", 0.0, self.pbias_target),
                ("baseflow", "bfi_ratio", 1.0, 0.15),
                ("peaks", "peak_magnitude_ratio", 1.0, 0.15),
                ("finetune", "kge", 1.0, 1.0 - self.kge_target),
            ]
        elif parent == "sediment":
            return SEDIMENT_PHASE_PARAMS, [
                ("sed_volume", "total_pbias", 0.0, self.pbias_target),
                ("sed_dynamics", "rating_slope_ratio", 1.0, 0.30),
                ("sed_finetune", "kge", 1.0, 1.0 - self.kge_target),
            ]
        elif parent == "nitrogen":
            return NITROGEN_PHASE_PARAMS, [
                ("n_volume", "total_pbias", 0.0, self.pbias_target),
                ("n_dynamics", "nse", 1.0, 1.0 - self.kge_target),
            ]
        elif parent == "phosphorus":
            return PHOSPHORUS_PHASE_PARAMS, [
                ("p_volume", "total_pbias", 0.0, self.pbias_target),
                ("p_dynamics", "nse", 1.0, 1.0 - self.kge_target),
            ]
        else:
            raise ValueError(
                f"Unknown constituent: {self.constituent!r} "
                f"(resolved parent: {parent!r}). Supported: flow, sediment, "
                f"nitrogen, phosphorus, or individual components like "
                f"orgp, minp, orgn, no3, sedconc, etc."
            )

    # ── Public API ───────────────────────────────────────────────────────

    def calibrate(self) -> DiagnosticCalibrationResult:
        """
        Run diagnostic-guided calibration.

        Iterates through 4 phases (volume → baseflow → peaks → finetune)
        in multiple passes until KGE target is met, stagnation is detected,
        or max_iterations is reached.

        Returns:
            DiagnosticCalibrationResult with best parameters, metrics, and step history.
        """
        t0 = time.time()

        try:
            # Check cancel before expensive backup creation
            self._check_cancel()

            # Create backup
            self._backup_dir = self.model.backup(
                file_types=self._modified_file_types,
            )

            # Apply custom simulation period (IYR/NBYR) if specified.
            # NOTE: .cio IS in _modified_file_types (for cleanup safety),
            # so _run_and_diagnose's restore() reverts it each iteration.
            # _run_and_diagnose re-applies the custom period after restore.
            if self._custom_sim_period is not None:
                self._apply_custom_sim_period()

            # Phase 0: Baseline
            self._check_cancel()
            self._report_progress(0, "Running baseline simulation...")
            report, sim, obs, dates = self._run_and_diagnose("baseline", {})
            self._last_observed = obs
            self._last_dates = dates
            self._update_best(report, sim)

            if self._converged(report):
                return self._build_result(self._total_runs(), time.time() - t0,
                                          True, "Baseline already satisfactory")

            # Iterate through phases in multiple passes
            max_passes = 3
            prev_pass_kge = -np.inf

            for pass_num in range(max_passes):
                if self._total_runs() >= self.max_iterations:
                    break
                self._check_cancel()

                # On passes > 0, reset to best-known solution and run a fresh
                # diagnostic so phases use up-to-date metrics (not stale ones
                # from the end of the previous pass with different params).
                if pass_num > 0 and self._best_values:
                    self._current_values = dict(self._best_values)
                    if self._total_runs() < self.max_iterations:
                        self._check_cancel()
                        self._report_progress(
                            self._total_runs(),
                            f"Re-evaluating best solution (pass {pass_num+1})...",
                        )
                        report, sim, obs, dates = self._run_and_diagnose(
                            "re-evaluate", {},
                        )
                        self._update_best(report, sim)
                        if self._converged(report):
                            return self._build_result(
                                self._total_runs(), time.time() - t0,
                                True, f"Converged on re-evaluation (pass {pass_num+1})",
                            )

                # Reduce max per-phase runs on later passes (more cautious)
                per_phase = max(1, 3 - pass_num)
                damping_scale = 1.0 / (1 + pass_num * 0.5)  # 1.0, 0.67, 0.5

                # Dispatch to constituent-specific phase sequence
                phase_params_dict, phase_configs = self._get_phase_sequence()

                for phase_name, metric_key, target, threshold in phase_configs:
                    if self._total_runs() >= self.max_iterations:
                        break
                    self._check_cancel()
                    self._run_phase(
                        phase_name, phase_params_dict[phase_name],
                        metric_key=metric_key, target=target,
                        threshold=threshold,
                        max_phase_runs=per_phase,
                        damping_override=self.damping * damping_scale,
                    )
                    if self._converged_overall():
                        return self._build_result(
                            self._total_runs(), time.time() - t0,
                            True, f"Converged after {phase_name} (pass {pass_num+1})",
                        )

                # Check cross-pass stagnation
                current_kge = self._best_metrics.get("kge", -np.inf)
                if current_kge - prev_pass_kge < 0.01:
                    # No meaningful KGE improvement this pass
                    break
                prev_pass_kge = current_kge

            converged = self._converged_overall()
            reason = (
                "Target met" if converged
                else f"Completed {self._total_runs()} runs (best KGE={self._best_kge:.3f})"
            )
            return self._build_result(
                self._total_runs(), time.time() - t0, converged, reason,
            )

        except _DiagnosticCancelled:
            # Return partial results collected so far
            return self._build_result(
                self._total_runs(), time.time() - t0,
                False, "Cancelled by user",
            )

        finally:
            self.cleanup()

    def cleanup(self):
        """Clean up temporary files. If a working copy was created, just
        delete it (original was never touched). Otherwise restore from backup."""
        if self._working_dir is not None:
            # Working copy mode — delete backup and working dir; original is safe.
            if self._backup_dir is not None and self._backup_dir.exists():
                try:
                    shutil.rmtree(self._backup_dir)
                except Exception:
                    pass
                self._backup_dir = None
            if self._working_dir.exists():
                try:
                    shutil.rmtree(self._working_dir)
                except Exception:
                    pass
            self._working_dir = None
            self._original_sim_period = None
        else:
            # No working copy (ensemble worker) — restore original from backup.
            if self._backup_dir is not None and self._backup_dir.exists():
                try:
                    self.model.restore(
                        self._backup_dir,
                        file_types=self._modified_file_types,
                    )
                except Exception:
                    pass
                try:
                    shutil.rmtree(self._backup_dir)
                except Exception:
                    pass
                self._backup_dir = None
            # Restore original simulation period in .cio
            if self._original_sim_period is not None:
                try:
                    orig_start, orig_end = self._original_sim_period
                    self.model.config.period.start_year = orig_start
                    self.model.config.period.end_year = orig_end
                    self.model.config.save()
                except Exception:
                    pass
                self._original_sim_period = None

    def _apply_custom_sim_period(self) -> None:
        """Apply custom simulation period (IYR/NBYR) to file.cio."""
        new_start, new_end = self._custom_sim_period
        self._original_sim_period = (
            self.model.config.period.start_year,
            self.model.config.period.end_year,
        )
        self.model.config.period.start_year = new_start
        self.model.config.period.end_year = new_end
        self.model.config.save()

    def _apply_locked_parameters(self) -> None:
        """Apply previously calibrated parameters for locked subbasins."""
        for sub_id, params in self.locked_parameters.items():
            for param_name, value in params.items():
                param_def = CALIBRATION_PARAMETERS.get(param_name.upper())
                if param_def is None:
                    continue
                if (
                    param_def.file_type in ParameterSet.BASIN_WIDE_TYPES
                    and param_name.upper() in ParameterSet.BSN_TO_HRU_MAP
                ):
                    # Use original name because .hru file label is 'ESCO', not 'ESCO_HRU'
                    self.model.modify_parameter(
                        param_name=param_name,
                        value=value,
                        file_type="hru",
                        method=param_def.method,
                        unit_id=sub_id,
                    )
                elif param_def.file_type not in ParameterSet.BASIN_WIDE_TYPES:
                    self.model.modify_parameter(
                        param_name=param_name,
                        value=value,
                        file_type=param_def.file_type,
                        method=param_def.method,
                        unit_id=sub_id,
                    )

    # ── Phase runner ─────────────────────────────────────────────────────

    def _run_phase(
        self,
        phase_name: str,
        param_candidates: List[str],
        metric_key: str,
        target: float,
        threshold: float,
        max_phase_runs: int = 3,
        damping_override: Optional[float] = None,
    ) -> int:
        """
        Run a calibration phase, adjusting parameters to move metric_key toward target.

        Returns number of SWAT runs used.
        """
        # Filter to params that are actually in our parameter set
        params = [p for p in param_candidates if p in self.parameter_set]
        if not params:
            return 0

        damping = damping_override if damping_override is not None else self.damping
        runs = 0
        prev_metric = None

        for step_i in range(max_phase_runs):
            if self._total_runs() >= self.max_iterations:
                break
            self._check_cancel()

            # Compute adjustments for each parameter.
            # First pass: identify which params need adjusting.
            # Second pass: compute adjustments with n_concurrent so each
            # param's step is scaled down when multiple params move at once
            # (prevents compounding overshoots).
            candidates = []
            last_step = self._steps[-1] if self._steps else None
            if last_step is None:
                break
            diag = last_step.diagnostic_summary
            current_metric = self._extract_metric(diag, metric_key)
            if current_metric is None or np.isnan(current_metric):
                break

            error = current_metric - target
            if abs(error) <= threshold:
                break  # metric already satisfied

            for pname in params:
                cparam = self.parameter_set.get_parameter(pname)
                direction = self._infer_direction(pname, phase_name, error)
                candidates.append((pname, cparam, direction))

            n_concurrent = max(len(candidates), 1)

            adjustments = {}
            for pname, cparam, direction in candidates:
                adj = estimate_adjustment(
                    parameter=pname,
                    direction=direction,
                    error_magnitude=error,
                    param_range=(cparam.min_value, cparam.max_value),
                    sensitivity_weight=0.5,
                    history=self._param_history.get(pname),
                    damping=damping,
                    n_concurrent=n_concurrent,
                )

                if abs(adj) < 1e-10:
                    continue

                adjustments[pname] = adj

            if not adjustments:
                break  # nothing to adjust

            # Apply adjustments
            new_values = dict(self._current_values)
            for pname, adj in adjustments.items():
                cparam = self.parameter_set.get_parameter(pname)
                old_val = new_values[pname]
                new_val = old_val + adj
                # Clamp to parameter bounds
                new_val = max(cparam.min_value, min(cparam.max_value, new_val))
                new_values[pname] = round(new_val, cparam.decimal_precision)

            # Skip the SWAT run if clamping/rounding produced no actual change
            if new_values == self._current_values:
                break

            self._report_progress(
                self._total_runs(),
                f"Phase {phase_name}: adjusting {', '.join(adjustments.keys())}",
            )

            # Run simulation
            report, sim, obs, dates = self._run_and_diagnose(phase_name, adjustments)
            runs += 1
            self._update_best(report, sim)

            # Record history for secant method
            new_metric = self._extract_metric(
                self._steps[-1].diagnostic_summary, metric_key
            )
            for pname in adjustments:
                self._param_history[pname].append({
                    "param_value": new_values[pname],
                    "metric_value": new_metric if new_metric is not None else np.nan,
                })

            # Cross-check: verify previous phase targets still hold
            if not self._previous_phases_ok(phase_name):
                # Reduce step by reverting halfway
                for pname, adj in adjustments.items():
                    cparam = self.parameter_set.get_parameter(pname)
                    half_back = new_values[pname] - adj * 0.5
                    new_values[pname] = round(
                        max(cparam.min_value, min(cparam.max_value, half_back)),
                        cparam.decimal_precision,
                    )
                self._current_values = new_values
                break

            # Check stagnation
            if prev_metric is not None and new_metric is not None:
                improvement = abs(new_metric - target) - abs(prev_metric - target)
                if improvement > -0.01 * abs(target or 1):
                    # No meaningful improvement
                    break

            prev_metric = new_metric

            if self._converged_overall():
                break

        return runs

    # ── WQ diagnostic helpers ─────────────────────────────────────────────

    def _diagnose_wq(self, sim, obs):
        """Simplified diagnostic for WQ constituents (load-based).

        Hydrograph-specific diagnostics (baseflow separation, peak detection)
        don't apply to sparse WQ load time series.  Instead we compute
        standard goodness-of-fit metrics and PBIAS.

        Returns a plain dict with keys: total_pbias, nse, r2, kge, pbias,
        rmse, r_squared, rsr (superset so _extract_metric always finds them).
        """
        mask = ~(np.isnan(sim) | np.isnan(obs))
        if np.sum(mask) < 3:
            return {
                "total_pbias": 0, "nse": -1, "r2": 0, "kge": -1,
                "pbias": 0, "rmse": np.nan, "r_squared": 0, "rsr": np.nan,
            }
        metrics = evaluate_model(obs[mask], sim[mask])
        metrics["total_pbias"] = pbias(obs[mask], sim[mask])
        # Alias r_squared -> r2 for convenience (some phase configs use "r2")
        metrics["r2"] = metrics.get("r_squared", 0)
        return metrics

    class _WQDiagnosticResult:
        """Lightweight stand-in for DiagnosticReport used by WQ constituents.

        Exposes the same .overall_metrics and .summary_dict() interface that
        _record_step, _update_best, and _converged rely on, without needing
        baseflow/peak analysis fields.
        """

        def __init__(self, metrics: Dict[str, float]):
            self.overall_metrics = dict(metrics)

        def summary_dict(self) -> Dict:
            return {
                "total_pbias": self.overall_metrics.get("total_pbias", np.nan),
                "overall_metrics": dict(self.overall_metrics),
                # Provide stubs for keys that _extract_metric may probe
                "bfi_ratio": np.nan,
                "peak_magnitude_ratio": np.nan,
                "nse": self.overall_metrics.get("nse", np.nan),
                "r2": self.overall_metrics.get("r2", np.nan),
            }

    def _make_wq_report(self, metrics: Dict[str, float]):
        """Wrap a WQ metrics dict into a _WQDiagnosticResult."""
        return self._WQDiagnosticResult(metrics)

    def _wq_adjustment_heuristic(self, param_name: str, pbias_val: float) -> int:
        """Return adjustment direction (+1/-1) for WQ parameters based on PBIAS.

        Positive PBIAS = model under-predicting load (obs > sim)
            -> need to *increase* source/transport
        Negative PBIAS = model over-predicting load (sim > obs)
            -> need to *decrease* source/transport

        The dicts below encode how each parameter affects constituent load:
        +1 means "increasing this parameter increases load".
        """
        # Sediment: increasing these params increases sediment yield
        SED_INCREASE = {
            "USLE_P": 1, "SPCON": 1, "ADJ_PKR": 1, "SPEXP": 1,
            "LAT_SED": 1, "USLE_K": 1, "SLSUBBSN": 1,
            "CH_COV1": 1, "CH_COV2": -1, "PRF": 1,
        }
        # Nitrogen: increasing these params increases N export
        N_INCREASE = {
            "CMN": 1, "NPERCO": 1, "CDN": -1,
            "N_UPDIS": -1, "SDNCO": -1, "ERORGN": 1,
        }
        # Phosphorus: increasing these params increases P export
        P_INCREASE = {
            "PPERCO": 1, "PHOSKD": -1, "PSP": 1,
            "P_UPDIS": -1, "ERORGP": 1, "GWSOLP": 1,
        }

        all_dirs = {**SED_INCREASE, **N_INCREASE, **P_INCREASE}

        direction = all_dirs.get(param_name, 1)
        # PBIAS > 0 means under-prediction -> need MORE load -> follow direction
        # PBIAS < 0 means over-prediction  -> need LESS load -> oppose direction
        if pbias_val > 0:
            return direction
        else:
            return -direction

    # ── Simulation runner ────────────────────────────────────────────────

    def _run_and_diagnose(
        self,
        phase: str,
        adjustments: Dict[str, float],
    ) -> Tuple:
        """
        Restore, apply params, run SWAT, extract output, diagnose.

        Returns (report_or_metrics, simulated, observed, dates).

        For flow: report is a DiagnosticReport.
        For WQ constituents: report is a synthetic object with .overall_metrics
        and .summary_dict() (a _WQDiagnosticResult).
        """
        _step_t0 = time.time()

        # Apply adjustments to current values
        for pname, adj in adjustments.items():
            cparam = self.parameter_set.get_parameter(pname)
            old_val = self._current_values[pname]
            new_val = old_val + adj
            new_val = max(cparam.min_value, min(cparam.max_value, new_val))
            self._current_values[pname] = round(new_val, cparam.decimal_precision)

        # Restore clean state (this also reverts .cio to the backup copy,
        # so we must re-apply custom_sim_period afterward).
        self.model.restore(self._backup_dir, file_types=self._modified_file_types)

        # Re-apply custom simulation period — restore() just reverted .cio
        if self._custom_sim_period is not None:
            self._apply_custom_sim_period()

        # Apply locked parameters from previous sequential steps
        if self.locked_parameters:
            self._apply_locked_parameters()

        # Apply parameters (scoped to subbasin group if specified)
        self.parameter_set.set_values(self._current_values)
        if self.subbasin_ids is not None:
            self.parameter_set.apply_to_model(self.model, subbasin_ids=self.subbasin_ids)
        else:
            self.parameter_set.apply_to_model(self.model)

        # Copy active_subs.dat for partial-basin simulation
        self._copy_active_subs()

        # Check cancel before starting a potentially long SWAT run
        self._check_cancel()

        # Determine extra variables to extract alongside the primary WQ var.
        # Sediment/phosphorus process diagnostics need concurrent flow data.
        _extra_vars = None
        _parent = self._resolve_constituent()
        if _parent in ("sediment", "phosphorus") and self.output_variable != "FLOW_OUT":
            _extra_vars = ["FLOW_OUT"]

        # Run baseline simulation (reuse the complex output extraction logic)
        baseline = run_baseline_simulation(
            model=self.model,
            observed_df=self.observed_df,
            output_variable=self.output_variable,
            reach_id=self.reach_id,
            warmup_years=self.warmup_years,
            upstream_subbasins=self.upstream_subbasins,
            qswat_shapes_dir=self.qswat_shapes_dir,
            cancel_event=self._get_cancel_event(),
            cancel_file=self._cancel_file,
            extra_variables=_extra_vars,
            print_code=self._print_code,
        )

        if not baseline["success"]:
            # Return NaN arrays if simulation failed
            n = len(self.observed_df)
            sim = np.full(n, np.nan)
            obs = self.observed_df["observed"].values.astype(float)
            dates = pd.to_datetime(self.observed_df.iloc[:, 0]).values
            if _parent == "flow":
                report = diagnose(obs, sim)
            else:
                report = self._make_wq_report(self._diagnose_wq(sim, obs))
            self._record_step(phase, adjustments, report)
            self._steps[-1].runtime = time.time() - _step_t0
            return report, sim, obs, dates

        sim = baseline["simulated"]
        dates = baseline["dates"]
        obs = self.observed_df["observed"].values.astype(float)

        # Align lengths
        n = min(len(obs), len(sim))
        sim = sim[:n]
        obs = obs[:n]
        if dates is not None:
            dates = dates[:n]

        # Run diagnostic analysis — dispatch based on constituent
        # (use resolved parent so individual components route correctly)
        if _parent == "flow":
            report = diagnose(obs, sim, dates)
        elif _parent == "sediment" and diagnose_sediment is not None:
            sim_flow = self._extract_concurrent_flow(baseline)
            try:
                report = diagnose_sediment(obs, sim, self._last_obs_flow, sim_flow, dates)
            except Exception:
                metrics = self._diagnose_wq(sim, obs)
                report = self._make_wq_report(metrics)
            self._last_wq_report = report
        elif _parent == "phosphorus" and diagnose_phosphorus is not None:
            sim_flow = self._extract_concurrent_flow(baseline)
            try:
                report = diagnose_phosphorus(obs, sim, self._last_obs_flow, sim_flow, dates)
            except Exception:
                metrics = self._diagnose_wq(sim, obs)
                report = self._make_wq_report(metrics)
            self._last_wq_report = report
        elif _parent == "nitrogen" and diagnose_nitrogen is not None:
            sim_flow = self._extract_concurrent_flow(baseline)
            try:
                report = diagnose_nitrogen(obs, sim, self._last_obs_flow, sim_flow, dates)
            except Exception:
                metrics = self._diagnose_wq(sim, obs)
                report = self._make_wq_report(metrics)
            self._last_wq_report = report
        else:
            metrics = self._diagnose_wq(sim, obs)
            report = self._make_wq_report(metrics)
            self._last_wq_report = report

        # Record step
        self._record_step(phase, adjustments, report)
        self._steps[-1].runtime = time.time() - _step_t0

        return report, sim, obs, dates

    def _extract_concurrent_flow(self, baseline_result: dict) -> Optional[np.ndarray]:
        """Extract FLOW_OUT from the same SWAT run (it's in output.rch alongside WQ vars).

        Falls back to the last cached simulated flow if the current run
        does not provide extra data.

        Args:
            baseline_result: Result dict from ``run_baseline_simulation()``.

        Returns:
            Simulated flow array, or None if unavailable.
        """
        extra = baseline_result.get("extra_data", {})
        flow = extra.get("FLOW_OUT")
        if flow is not None:
            self._last_sim_flow = flow
            return flow
        return self._last_sim_flow

    def _record_step(
        self,
        phase: str,
        adjustments: Dict[str, float],
        report,
    ):
        """Record a diagnostic step.

        ``report`` may be a DiagnosticReport (flow) or _WQDiagnosticResult (WQ).
        Both expose .overall_metrics and .summary_dict().
        """
        step = DiagnosticStep(
            iteration=len(self._steps),
            phase=phase,
            parameters=dict(self._current_values),
            adjustments=dict(adjustments),
            metrics=dict(report.overall_metrics),
            diagnostic_summary=report.summary_dict(),
        )
        self._steps.append(step)

    # ── Convergence checks ───────────────────────────────────────────────

    def _converged(self, report) -> bool:
        """Check if a single report meets convergence criteria.

        Works with both DiagnosticReport (flow) and _WQDiagnosticResult (WQ).
        For WQ constituents the primary metric is NSE (stored in kge_target)
        and PBIAS; both are present in .overall_metrics for either type.
        """
        metrics = report.overall_metrics
        kge_val = metrics.get("kge", -np.inf)
        pbias_val = abs(metrics.get("pbias", 999))
        return kge_val >= self.kge_target and pbias_val <= self.pbias_target

    def _converged_overall(self) -> bool:
        """Check overall convergence from best metrics."""
        kge_val = self._best_metrics.get("kge", -np.inf)
        pbias_val = abs(self._best_metrics.get("pbias", 999))
        return kge_val >= self.kge_target and pbias_val <= self.pbias_target

    def _previous_phases_ok(self, current_phase: str) -> bool:
        """Verify that targets from earlier phases haven't been broken.

        For flow: checks volume (PBIAS) and baseflow (BFI) from prior phases.
        For WQ: only checks volume (PBIAS) since BFI doesn't apply.
        """
        if not self._steps:
            return True

        diag = self._steps[-1].diagnostic_summary
        parent = self._resolve_constituent()

        if parent == "flow":
            phase_order = ["volume", "baseflow", "peaks", "finetune"]
        elif parent == "sediment":
            phase_order = ["sed_volume", "sed_dynamics", "sed_finetune"]
        elif parent == "nitrogen":
            phase_order = ["n_volume", "n_dynamics"]
        elif parent == "phosphorus":
            phase_order = ["p_volume", "p_dynamics"]
        else:
            return True

        current_idx = (
            phase_order.index(current_phase)
            if current_phase in phase_order else 0
        )

        # Volume target: |PBIAS| <= pbias_target * 1.5 (allow some slack)
        if current_idx > 0:
            tp = diag.get("total_pbias", 0)
            if tp is not None and not np.isnan(tp) and abs(tp) > self.pbias_target * 1.5:
                return False

        # Baseflow target (flow only): |BFI_ratio - 1| <= 0.25
        if parent == "flow" and current_idx > 1:
            bfi = diag.get("bfi_ratio", 1.0)
            if bfi is not None and not np.isnan(bfi) and abs(bfi - 1.0) > 0.25:
                return False

        return True

    # ── Helpers ──────────────────────────────────────────────────────────

    def _update_best(self, report, sim: np.ndarray):
        """Update best solution if this report improves KGE."""
        kge_val = report.overall_metrics.get("kge", -np.inf)
        if kge_val > self._best_kge:
            self._best_kge = kge_val
            self._best_values = dict(self._current_values)
            self._best_metrics = dict(report.overall_metrics)
            self._best_simulated = sim.copy()

    def _total_runs(self) -> int:
        """Total SWAT runs so far."""
        return len(self._steps)

    def _extract_metric(self, diag_summary: Dict, key: str):
        """Extract a metric value from a diagnostic summary dict.

        Searches direct keys, then nested dicts produced by richer
        diagnostic reports (overall_metrics, rating_curve, event_partition,
        flow_partition).
        """
        # Direct keys
        if key in diag_summary:
            return diag_summary[key]
        # Nested in overall_metrics
        om = diag_summary.get("overall_metrics", {})
        if key in om:
            return om[key]
        # Nested in rating_curve (sediment diagnostic report)
        rc = diag_summary.get("rating_curve", {})
        if key in rc:
            return rc[key]
        # Nested in event_partition (sediment diagnostic report)
        ep = diag_summary.get("event_partition", {})
        if key in ep:
            return ep[key]
        # Nested in flow_partition (phosphorus diagnostic report)
        fp = diag_summary.get("flow_partition", {})
        if key in fp:
            return fp[key]
        return None

    def _infer_direction(self, param: str, phase: str, error: float) -> str:
        """
        Infer whether to increase or decrease a parameter given the phase error.

        Uses domain knowledge of how SWAT parameters affect outputs.
        For WQ constituents, delegates to _wq_adjustment_heuristic().
        """
        # ── WQ constituents: use process-diagnostic findings, then heuristic ──
        if self._resolve_constituent() != "flow":
            # If the last WQ report has findings that directly target this param,
            # use the finding's direction (more precise than generic heuristic).
            if self._last_wq_report is not None and hasattr(self._last_wq_report, "findings"):
                for finding in self._last_wq_report.findings:
                    if hasattr(finding, "parameters") and param in finding.parameters:
                        idx = finding.parameters.index(param)
                        if hasattr(finding, "directions") and idx < len(finding.directions):
                            return finding.directions[idx]

            # Fallback: heuristic table based on PBIAS
            # For WQ volume phases the error is PBIAS (target=0).
            # For dynamics/finetune phases the error is (metric - target),
            # but PBIAS from the latest step is a better signal for
            # parameter direction decisions.
            last_step = self._steps[-1] if self._steps else None
            if last_step is not None:
                wq_pbias = last_step.diagnostic_summary.get("total_pbias", error)
            else:
                wq_pbias = error
            sign = self._wq_adjustment_heuristic(param, wq_pbias)
            return "increase" if sign > 0 else "decrease"

        # ── Flow constituent: original hydrology logic ──
        # Error conventions:
        #   volume: PBIAS > 0 means underestimation (need more water)
        #   baseflow: BFI_ratio < 1 means too little baseflow
        #   peaks: peak_ratio < 1 means peaks too low
        #   finetune: KGE < 1 means imperfect (increase toward 1)

        # Parameter-specific logic
        if param == "ESCO":
            # Higher ESCO → less deep soil evap → more water → reduces positive PBIAS
            return "increase" if error > 0 else "decrease"
        elif param == "CN2":
            if phase == "volume":
                # Higher CN2 → more runoff → reduces positive PBIAS (underprediction)
                return "increase" if error > 0 else "decrease"
            else:
                # For peaks: higher CN2 → higher peaks
                return "increase" if error < 0 else "decrease"
        elif param == "GWQMN":
            # Higher GWQMN → less baseflow return (threshold rises)
            return "decrease" if error < 0 else "increase"
        elif param == "RCHRG_DP":
            # Higher RCHRG_DP → more deep percolation → less baseflow
            return "decrease" if error < 0 else "increase"
        elif param == "ALPHA_BF":
            # Higher → faster baseflow response → less sustained baseflow
            # If BFI too low → decrease ALPHA_BF for slower release
            return "decrease" if error < 0 else "increase"
        elif param == "GW_DELAY":
            # Higher delay → slower GW recharge → less baseflow in short term
            return "decrease" if error < 0 else "increase"
        elif param == "SURLAG":
            # Higher SURLAG → more lag → lower/delayed peaks
            return "increase" if error > 0 else "decrease"
        elif param == "GW_REVAP":
            # Higher → more water revapped from GW → less baseflow
            return "decrease" if error < 0 else "increase"
        elif param == "EPCO":
            # Higher → more plant uptake from deeper soil → less water
            return "decrease" if error > 0 else "increase"
        elif param == "OV_N":
            # Higher → slower overland flow → lower peaks
            return "increase" if error > 0 else "decrease"
        elif param == "SOL_AWC":
            # Higher → more soil storage → less runoff, more ET
            return "decrease" if error > 0 else "increase"
        elif param == "CH_N2":
            # Higher Manning's n → slower channel flow → delayed/lower peaks
            return "increase" if error > 0 else "decrease"
        elif param == "REVAPMN":
            # Higher threshold → less revap → more baseflow
            return "increase" if error < 0 else "decrease"
        else:
            # Default: positive error means sim too low → increase
            return "increase" if error > 0 else "decrease"

    def _report_progress(self, step: int, message: str):
        """Report progress via callback if available."""
        if self._progress_cb is not None:
            try:
                self._progress_cb(step, self.max_iterations, message)
            except Exception:
                # If cancel was requested, let the exception propagate
                cs = self._cancel_state
                if cs is not None and getattr(cs, "cancel_requested", False):
                    raise
                pass  # Swallow other callback errors

    def _build_result(
        self,
        total_runs: int,
        runtime: float,
        converged: bool,
        reason: str,
    ) -> DiagnosticCalibrationResult:
        """Build the final result object."""
        obs = self._last_observed
        sim = self._best_simulated
        if obs is None:
            obs = np.array([])
        if sim is None:
            sim = np.array([])

        return DiagnosticCalibrationResult(
            best_parameters=dict(self._best_values),
            best_metrics=dict(self._best_metrics),
            steps=list(self._steps),
            total_runs=total_runs,
            runtime=runtime,
            converged=converged,
            convergence_reason=reason,
            observed=obs,
            simulated=sim,
            dates=self._last_dates,
        )


# ── Ensemble Parallel Diagnostic Calibration ─────────────────────────────

@dataclass
class EnsembleRecipe:
    """Configuration for one ensemble member."""

    recipe_id: int
    damping: float = 0.5
    phase_order: List[str] = field(
        default_factory=lambda: ["volume", "baseflow", "peaks", "finetune"]
    )
    initial_perturbation: Dict[str, float] = field(default_factory=dict)
    max_per_phase: int = 3
    bfi_max: float = 0.80


def _kill_pool_children(pool):
    """Terminate all child processes of a ProcessPoolExecutor.

    On Windows, ``pool.shutdown(wait=False)`` does NOT kill running
    workers — they keep executing (and holding file locks).  This
    helper uses ``os.kill`` / ``psutil`` to forcibly terminate them
    so temporary directories can be deleted immediately.
    """
    import signal

    # ProcessPoolExecutor stores worker PIDs in pool._processes (dict).
    _procs = getattr(pool, "_processes", None)
    if not _procs:
        return
    for pid in list(_procs):
        try:
            os.kill(pid, signal.SIGTERM)
        except (OSError, ProcessLookupError):
            pass  # already dead
    # Brief pause for OS to release file handles
    import time
    time.sleep(0.5)


def _ensemble_worker(
    worker_dir: str,
    executable: str,
    observed_df: "pd.DataFrame",
    recipe: EnsembleRecipe,
    kwargs: dict,
) -> DiagnosticCalibrationResult:
    """Worker function for ensemble parallelism (module-level for pickling).

    Creates a fresh SWATModel pointing at the copied worker directory,
    instantiates a DiagnosticCalibrator with the recipe's config, applies
    any initial perturbation, and runs calibration.
    """
    # Early cancel check BEFORE any expensive work (backup creation etc.)
    _cf = kwargs.get("_cancel_file")
    if _cf and Path(_cf).exists():
        return DiagnosticCalibrationResult(
            best_parameters={}, best_metrics={}, steps=[],
            total_runs=0, runtime=0, converged=False,
            convergence_reason="Cancelled by user",
            observed=observed_df["observed"].values,
            simulated=np.full(len(observed_df), np.nan),
        )

    from swat_modern.core.model import SWATModel

    model = SWATModel(Path(worker_dir), executable=executable)

    # Write per-run progress to a file so the parent process can poll it.
    _progress_path = Path(worker_dir) / ".diag_progress"

    def _file_progress_cb(step, total, message):
        try:
            _progress_path.write_text(str(step))
        except Exception:
            pass

    calibrator = DiagnosticCalibrator(
        model=model,
        observed_df=observed_df,
        parameter_names=kwargs.get("parameter_names"),
        reach_id=kwargs.get("reach_id", 1),
        output_variable=kwargs.get("output_variable", "FLOW_OUT"),
        warmup_years=kwargs.get("warmup_years", 0),
        max_iterations=kwargs.get("max_iterations", 15),
        kge_target=kwargs.get("kge_target", 0.70),
        pbias_target=kwargs.get("pbias_target", 10.0),
        damping=recipe.damping,
        upstream_subbasins=kwargs.get("upstream_subbasins"),
        qswat_shapes_dir=kwargs.get("qswat_shapes_dir"),
        subbasin_ids=kwargs.get("subbasin_ids"),
        locked_parameters=kwargs.get("locked_parameters"),
        custom_sim_period=kwargs.get("custom_sim_period"),
        progress_callback=_file_progress_cb,
        constituent=kwargs.get("constituent", "flow"),
        partial_basin_reach=kwargs.get("partial_basin_reach"),
        _use_working_copy=False,  # worker already has its own dir copy
    )
    # File-based cancel for cross-process cancellation
    _cf = kwargs.get("_cancel_file")
    if _cf:
        calibrator._cancel_file = _cf

    # Apply initial perturbation if specified
    if recipe.initial_perturbation:
        for pname, delta in recipe.initial_perturbation.items():
            if pname in calibrator._current_values:
                cparam = calibrator.parameter_set.get_parameter(pname)
                new_val = calibrator._current_values[pname] + delta
                new_val = max(cparam.min_value, min(cparam.max_value, new_val))
                calibrator._current_values[pname] = round(
                    new_val, cparam.decimal_precision
                )

    return calibrator.calibrate()


class EnsembleDiagnosticCalibrator:
    """
    Run N independent DiagnosticCalibrators in parallel with diverse configs.

    Each worker gets its own copy of the model directory and a unique
    EnsembleRecipe (damping, phase order, initial perturbation). The best
    result (highest KGE) is returned.

    Same wall-clock time as a single run, but better solution quality
    by exploring different regions of parameter space.

    Args:
        model: SWATModel instance.
        observed_df: DataFrame with 'date' and 'observed' columns.
        n_workers: Number of parallel workers (default: min(4, cpu_count)).
        parameter_names: Parameter names to calibrate.
        recipes: Optional list of EnsembleRecipe configs. Auto-generated if None.
        progress_callback: Optional callback(step, total, message).
        **kwargs: Additional args passed to each DiagnosticCalibrator
            (reach_id, output_variable, warmup_years, max_iterations,
            kge_target, pbias_target, upstream_subbasins, qswat_shapes_dir,
            subbasin_ids, locked_parameters).
    """

    def __init__(
        self,
        model,
        observed_df: pd.DataFrame,
        n_workers: Optional[int] = None,
        parameter_names: Optional[List[str]] = None,
        recipes: Optional[List[EnsembleRecipe]] = None,
        progress_callback: Optional[Callable] = None,
        **kwargs,
    ):
        self.model = model
        self.observed_df = observed_df
        self.n_workers = n_workers or min(4, os.cpu_count() or 1)
        self._progress_cb = progress_callback

        # Store kwargs for workers
        self._worker_kwargs = dict(kwargs)
        self._worker_kwargs["parameter_names"] = parameter_names

        # Generate or use provided recipes
        if recipes is not None:
            self._recipes = recipes
        else:
            _constituent = kwargs.get("constituent", "flow")
            self._recipes = self._generate_recipes(self.n_workers, _constituent)

        # Ensure we have exactly n_workers recipes
        while len(self._recipes) < self.n_workers:
            self._recipes.append(EnsembleRecipe(recipe_id=len(self._recipes)))
        self._recipes = self._recipes[: self.n_workers]

    def _generate_recipes(self, n_workers: int, constituent: str = "flow") -> List[EnsembleRecipe]:
        """Generate diverse recipes for ensemble members.

        Each recipe represents a physically-motivated starting hypothesis about
        whether the model is under- or over-predicting the target constituent.
        Perturbation directions are taken directly from _infer_direction() /
        _wq_adjustment_heuristic() so workers explore genuinely different
        regions of the relevant parameter space.

        Strategy:
        - Recipe 0: Neutral — start at model-file defaults
        - Recipe 1: "Underestimation" hypothesis — pre-shift toward more output
        - Recipe 2: "Overestimation" hypothesis — pre-shift toward less output
        - Recipe 3: Constituent-specific variant (alt phase order for flow;
                    secondary-process emphasis for WQ)
        - Recipe 4+: Half-magnitude blends, varied damping

        The initial_perturbation values are additive offsets on _current_values
        read from the model files; they are clamped to [min, max] in the worker.
        Magnitudes are ~25 % of the typical calibration range so workers start
        in clearly distinct regions without hitting hard boundaries.
        """
        # ── Flow (hydrology) perturbations ───────────────────────────────
        # CN2  : multiply, range [-0.25, 0.25] → ±0.10
        # ESCO : replace,  range [0.01, 1.0]   → ±0.20
        # ALPHA_BF: replace, range [0.0, 1.0]  → ±0.15
        # GW_DELAY: replace, range [0, 500]    → ±60
        # GWQMN:    replace, range [0, 5000]   → ±500
        # SURLAG:   replace, range [0.5, 24]   → ±4
        _flow_under = {   # PBIAS>0 or BFI<1 → need more water/baseflow
            "CN2":      +0.10,
            "ESCO":     +0.20,
            "ALPHA_BF": -0.15,
            "GW_DELAY": -60.0,
            "GWQMN":    -500.0,
        }
        _flow_over = {    # PBIAS<0 or BFI>1 → need less water/baseflow
            "CN2":      -0.10,
            "ESCO":     -0.20,
            "ALPHA_BF": +0.15,
            "GW_DELAY": +60.0,
            "GWQMN":    +500.0,
        }
        _flow_high_peaks = {  # peaks too low, runoff too slow
            "CN2":    +0.08,
            "SURLAG": -4.0,
        }

        # ── Sediment perturbations ────────────────────────────────────────
        # Signs from _wq_adjustment_heuristic SED_INCREASE (+1 = increases load)
        # USLE_P  : replace, [0.1, 1.0],   default 1.0  → ±0.25
        # SPCON   : replace, [0.0001,0.01], default 0.001→ ±0.003
        # ADJ_PKR : replace, [0.5, 2.0],   default 1.0  → ±0.35
        # SPEXP   : replace, [1.0, 2.0],   default 1.0  → ±0.25
        # CH_COV2 : -1 in SED_INCREASE (higher COV2 reduces erosion)
        _sed_under = {   # PBIAS>0 → model under-predicts sediment → increase sources
            "USLE_P":  +0.25,
            "SPCON":   +0.003,
            "ADJ_PKR": +0.35,
            "SPEXP":   +0.25,
        }
        _sed_over = {    # PBIAS<0 → over-predicts sediment → reduce sources
            "USLE_P":  -0.25,
            "SPCON":   -0.003,
            "ADJ_PKR": -0.35,
            "SPEXP":   -0.25,
        }
        _sed_channel = {  # emphasise channel transport parameters
            "CH_COV1": +0.15,   # more channel erodibility
            "PRF":     +0.50,   # higher peak rate → more channel erosion
        }

        # ── Nitrogen perturbations ────────────────────────────────────────
        # N_INCREASE signs: CMN+1, NPERCO+1, CDN-1, N_UPDIS-1, SDNCO-1, ERORGN+1
        # CMN    : replace, [0.0001, 0.003], default 0.0003 → ±0.0008
        # NPERCO : replace, [0.0, 1.0],      default 0.2    → ±0.25
        # CDN    : replace, [0.0, 3.0],      default 1.4    → ±0.75 (sign -1)
        # ERORGN : replace, [0.0, 5.0],      default 0.0    → ±1.0
        _n_under = {   # PBIAS>0 → under-predicts N → increase N sources/transport
            "CMN":    +0.0008,
            "NPERCO": +0.25,
            "CDN":    -0.75,   # lower CDN → less denitrification → more N export
            "ERORGN": +1.0,
        }
        _n_over = {    # PBIAS<0 → over-predicts N → decrease N sources/transport
            "CMN":    -0.0008,
            "NPERCO": -0.25,
            "CDN":    +0.75,
            "ERORGN": -1.0,
        }
        _n_uptake = {  # emphasise plant-uptake / denitrification pathway
            "N_UPDIS": -10.0,   # lower → more uptake from top soil → less leaching
            "SDNCO":   -0.25,   # lower threshold → more denitrification
        }

        # ── Phosphorus perturbations ──────────────────────────────────────
        # P_INCREASE signs: PPERCO+1, PHOSKD-1, PSP+1, P_UPDIS-1, ERORGP+1, GWSOLP+1
        # PPERCO : replace, [10.0, 17.5], default 10.0 → ±2.0
        # PHOSKD : replace, [100, 200],   default 175  → ±25  (sign -1)
        # PSP    : replace, [0.01, 0.7],  default 0.4  → ±0.15
        # ERORGP : replace, [0.0, 5.0],   default 0.0  → ±1.0
        _p_under = {   # PBIAS>0 → under-predicts P → increase P sources/transport
            "PPERCO": +2.0,
            "PHOSKD": -25.0,   # lower PHOSKD → less P sorption → more P in runoff
            "PSP":    +0.15,
            "ERORGP": +1.0,
        }
        _p_over = {    # PBIAS<0 → over-predicts P → decrease P sources/transport
            "PPERCO": -2.0,
            "PHOSKD": +25.0,
            "PSP":    -0.15,
            "ERORGP": -1.0,
        }
        _p_gw = {  # emphasise groundwater P pathway
            "GWSOLP": +0.10,   # higher GW soluble P → more baseflow P load
        }

        # ── Select perturbation sets by constituent ───────────────────────
        c = constituent.lower() if constituent else "flow"
        if c in ("sediment", "sed"):
            _under, _over, _alt = _sed_under, _sed_over, _sed_channel
            _alt_phase_order = None   # sediment has no alt phase order
        elif c in ("nitrogen", "n", "no3", "tn"):
            _under, _over, _alt = _n_under, _n_over, _n_uptake
            _alt_phase_order = None
        elif c in ("phosphorus", "p", "tp", "srp"):
            _under, _over, _alt = _p_under, _p_over, _p_gw
            _alt_phase_order = None
        else:  # flow (default)
            _under, _over, _alt = _flow_under, _flow_over, _flow_high_peaks
            _alt_phase_order = ["volume", "peaks", "baseflow", "finetune"]

        recipes = []

        # Recipe 0: Neutral — start exactly at model-file defaults
        recipes.append(EnsembleRecipe(recipe_id=0, damping=0.5))

        if n_workers >= 2:
            # Recipe 1: "underestimation" hypothesis
            recipes.append(
                EnsembleRecipe(
                    recipe_id=1,
                    damping=0.3,
                    max_per_phase=4,
                    initial_perturbation=_under,
                )
            )

        if n_workers >= 3:
            # Recipe 2: "overestimation" hypothesis
            recipes.append(
                EnsembleRecipe(
                    recipe_id=2,
                    damping=0.7,
                    max_per_phase=2,
                    initial_perturbation=_over,
                )
            )

        if n_workers >= 4:
            # Recipe 3: constituent-specific secondary process emphasis
            r3_kwargs: dict = dict(recipe_id=3, damping=0.5, initial_perturbation=_alt)
            if _alt_phase_order is not None:
                r3_kwargs["phase_order"] = _alt_phase_order
            recipes.append(EnsembleRecipe(**r3_kwargs))

        # Recipes 4+: half-magnitude blends, varied damping
        for i in range(4, n_workers):
            damping = 0.3 + (i - 4) * 0.1
            damping = min(damping, 0.9)
            blend = _under if i % 2 == 0 else _over
            half_blend = {k: v * 0.5 for k, v in blend.items()}
            recipes.append(
                EnsembleRecipe(
                    recipe_id=i,
                    damping=damping,
                    initial_perturbation=half_blend,
                )
            )

        return recipes

    def calibrate(self) -> DiagnosticCalibrationResult:
        """Run ensemble calibration in parallel, return best result."""
        import tempfile
        from concurrent.futures import ProcessPoolExecutor, wait, FIRST_COMPLETED

        _max_iter = self._worker_kwargs.get("max_iterations", 15)
        _total_max = self.n_workers * _max_iter

        # Extract cancel_state (can't cross process boundary) and create
        # a file-based cancel flag that worker processes can check.
        _cancel_state = self._worker_kwargs.pop("cancel_state", None)
        _cancel_dir = Path(tempfile.mkdtemp(prefix="swat_ens_cancel_"))
        _cancel_file = _cancel_dir / "cancel.flag"
        # Pass the cancel file path to workers via kwargs
        worker_kwargs = dict(self._worker_kwargs)
        worker_kwargs["_cancel_file"] = str(_cancel_file)

        # Register cancel file on CalibrationState so request_cancel()
        # writes it IMMEDIATELY (no 2-second polling delay).
        if _cancel_state is not None and hasattr(_cancel_state, "register_cancel_file"):
            _cancel_state.register_cancel_file(str(_cancel_file))

        # Early exit if cancel was already requested before we started
        if _cancel_state is not None and getattr(_cancel_state, "cancel_requested", False):
            _cancel_file.write_text("cancelled")
            return DiagnosticCalibrationResult(
                best_parameters={},
                best_metrics={},
                steps=[],
                total_runs=0,
                runtime=0,
                converged=False,
                convergence_reason="Cancelled by user",
                observed=self.observed_df["observed"].values,
                simulated=np.full(len(self.observed_df), np.nan),
            )

        if self._progress_cb:
            self._progress_cb(
                0, _total_max,
                f"Starting ensemble with {self.n_workers} workers...",
            )

        # 1. Create N model directory copies
        worker_dirs: List[Path] = []
        for i in range(self.n_workers):
            worker_dir = (
                self.model.project_dir.parent
                / f".diag_ensemble_w{i}_{os.getpid()}"
            )
            if worker_dir.exists():
                shutil.rmtree(worker_dir)
            shutil.copytree(self.model.project_dir, worker_dir)
            worker_dirs.append(worker_dir)

        try:
            # 2. Launch workers
            pool = ProcessPoolExecutor(max_workers=self.n_workers)
            futures = []
            try:
                for i, (worker_dir, recipe) in enumerate(
                    zip(worker_dirs, self._recipes)
                ):
                    future = pool.submit(
                        _ensemble_worker,
                        worker_dir=str(worker_dir),
                        executable=str(self.model.executable),
                        observed_df=self.observed_df,
                        recipe=recipe,
                        kwargs=worker_kwargs,
                    )
                    futures.append(future)

                # 3. Collect results — poll worker progress files every 2s
                #    instead of blocking on f.result() (workers are in child
                #    processes and cannot call back to the main thread).
                results = []
                remaining = set(futures)
                _cancelled = False

                while remaining:
                    # Propagate cancel_state → file flag for workers
                    _is_cancel = (
                        _cancel_state is not None
                        and getattr(_cancel_state, "cancel_requested", False)
                    )
                    if _is_cancel and not _cancel_file.exists():
                        try:
                            _cancel_file.parent.mkdir(parents=True, exist_ok=True)
                            _cancel_file.write_text("cancelled")
                            print(f"[cancel] Wrote cancel file (poll): {_cancel_file}")
                        except Exception as exc:
                            print(f"[cancel] ERROR writing cancel file: {exc}")

                    if _is_cancel:
                        _cancelled = True
                        print("[cancel] Ensemble cancellation detected — "
                              "waiting for workers to stop...")
                        break

                    done, remaining = wait(
                        remaining, timeout=2, return_when=FIRST_COMPLETED,
                    )
                    for f in done:
                        try:
                            results.append(f.result())
                        except Exception:
                            pass  # worker crashed — skip

                    # Safety: write cancel file BEFORE progress callback
                    # (the callback may raise CalibrationCancelled which
                    # would exit the loop before the top-of-loop check).
                    if (
                        _cancel_state is not None
                        and getattr(_cancel_state, "cancel_requested", False)
                        and not _cancel_file.exists()
                    ):
                        try:
                            _cancel_file.write_text("cancelled")
                            print(f"[cancel] Wrote cancel file (safety): {_cancel_file}")
                        except Exception as exc:
                            print(f"[cancel] ERROR writing cancel file: {exc}")

                    # Read per-worker progress from .diag_progress files
                    if self._progress_cb:
                        total_runs = 0
                        for wd in worker_dirs:
                            pf = wd / ".diag_progress"
                            if pf.exists():
                                try:
                                    total_runs += int(pf.read_text().strip())
                                except (ValueError, OSError):
                                    pass
                        n_done = len(results)
                        self._progress_cb(
                            total_runs, _total_max,
                            f"Ensemble: {total_runs} runs, "
                            f"{n_done}/{self.n_workers} workers done"
                            + (
                                f" (KGE={results[-1].best_metrics.get('kge', -999):.3f})"
                                if results else ""
                            ),
                        )

            finally:
                # Ensure cancel file is written so workers stop promptly.
                _is_cancelling = (
                    _cancel_state is not None
                    and getattr(_cancel_state, "cancel_requested", False)
                )
                if _is_cancelling and not _cancel_file.exists():
                    try:
                        _cancel_file.write_text("cancelled")
                        print(f"[cancel] Wrote cancel file (finally): {_cancel_file}")
                    except Exception:
                        pass

                if _is_cancelling and futures:
                    # Brief wait for workers — they should detect the cancel
                    # file quickly.  Keep timeout short for responsiveness.
                    _done, _not_done = wait(futures, timeout=5)
                    if _not_done:
                        print(f"[cancel] {len(_not_done)} worker(s) still "
                              f"running — killing child processes")
                        # Kill child processes so files are released and
                        # temp directories can be cleaned up on Windows.
                        _kill_pool_children(pool)

                pool.shutdown(wait=False)

            if _cancelled:
                raise _DiagnosticCancelled("Ensemble calibration cancelled")

            if not results:
                return DiagnosticCalibrationResult(
                    best_parameters={},
                    best_metrics={},
                    steps=[],
                    total_runs=0,
                    runtime=0,
                    converged=False,
                    convergence_reason="All workers failed",
                    observed=self.observed_df["observed"].values,
                    simulated=np.full(len(self.observed_df), np.nan),
                )

            # 4. Pick best by KGE
            best = max(
                results,
                key=lambda r: r.best_metrics.get("kge", -999),
            )
            best.convergence_reason += (
                f" (best of {self.n_workers} ensemble members)"
            )
            return best

        finally:
            # 5. Cleanup worker directories and cancel flag
            for d in worker_dirs:
                shutil.rmtree(d, ignore_errors=True)
            shutil.rmtree(str(_cancel_dir), ignore_errors=True)
