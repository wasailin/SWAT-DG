"""
Phased Calibrator for sequential multi-constituent SWAT calibration.

Runs sequential phases: Flow -> Sediment -> Nitrogen -> Phosphorus.
After each phase, best parameters are locked (written into model files),
and the next phase calibrates its own parameter set on top.

This reuses existing calibration infrastructure:
- ``Calibrator`` + SPOTPY algorithms for the streamflow phase
- ``MultiConstituentSetup`` + SPOTPY for water quality phases
- ``DiagnosticCalibrator`` as an optional streamflow algorithm

Parameter locking strategy:
    After each phase completes, the best parameter values are written
    directly into the SWAT model files.  When the next phase creates its
    own backup (via Calibrator or MultiConstituentSetup), the locked
    parameters are baked into that backup.  Subsequent backup/restore
    cycles preserve them without any special logic.

Example::

    from swat_modern import SWATModel
    from swat_modern.calibration.phased_calibrator import PhasedCalibrator

    model = SWATModel("C:/my_watershed")
    calibrator = PhasedCalibrator(
        model=model,
        flow_observations=flow_df,
        wq_observations=wq_df,
        reach_id=14,
    )
    result = calibrator.calibrate()
    result.print_summary()
"""

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Dict, List, Optional

import numpy as np
import pandas as pd

from swat_modern.calibration.parameters import (
    CALIBRATION_PARAMETERS,
    CalibrationParameter,
    ParameterSet,
    CONSTITUENT_PHASES,
    get_streamflow_parameters,
    get_sediment_parameters,
    get_nitrogen_parameters,
    get_phosphorus_parameters,
)

logger = logging.getLogger(__name__)

# Mapping from phase name to WQ constituent name used by LoadCalculator
_PHASE_TO_CONSTITUENT = {
    "sediment": "TSS",
    "nitrogen": "TN",
    "phosphorus": "TP",
}

# Mapping from phase name to the WQ observation column expected in wq_observations
_PHASE_TO_OBS_COLUMN = {
    "sediment": "TSS_mg_L",
    "nitrogen": "TN_mg_L",
    "phosphorus": "TP_mg_L",
}


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class PhaseConfig:
    """Configuration for a single calibration phase.

    Attributes:
        name: Phase identifier -- one of "streamflow", "sediment",
            "nitrogen", "phosphorus", or a custom name.
        parameters: List of SWAT parameter names to calibrate in this phase.
        output_variable: SWAT output variable (e.g. "FLOW_OUT", "SED_OUT").
        n_iterations: Number of SPOTPY iterations (or diagnostic max runs).
        algorithm: Calibration algorithm -- "sceua", "dream", "lhs", "mc",
            "diagnostic", or "diagnostic_ensemble".
        objective: Objective function name -- "nse", "kge", "pbias", etc.
        enabled: Whether this phase should be executed.
        constituent: Water quality constituent name for WQ phases
            (e.g. "TN", "TP", "TSS").  None for streamflow.
        weight: Constituent weight for multi-objective evaluation.
    """

    name: str
    parameters: List[str]
    output_variable: str
    n_iterations: int
    algorithm: str
    objective: str
    enabled: bool = True
    constituent: Optional[str] = None
    weight: float = 1.0


@dataclass
class PhasedCalibrationResult:
    """Result container for phased multi-constituent calibration.

    Attributes:
        phase_results: Per-phase results, each a dict with keys:
            name, parameters, metrics, result (CalibrationResult or None).
        all_best_parameters: Merged best parameters from all completed phases.
        total_runtime: Wall-clock time for the entire phased calibration.
        phases_completed: Number of phases that ran successfully.
        phases_total: Total number of enabled phases.
    """

    phase_results: List[Dict]
    all_best_parameters: Dict[str, float]
    total_runtime: float
    phases_completed: int
    phases_total: int

    def print_summary(self) -> None:
        """Print a human-readable summary of the phased calibration."""
        lines = [
            "=" * 70,
            "PHASED CALIBRATION RESULTS",
            "=" * 70,
            f"Phases completed: {self.phases_completed}/{self.phases_total}",
            f"Total runtime: {self.total_runtime:.1f} seconds",
            "",
        ]

        for i, pr in enumerate(self.phase_results, 1):
            lines.append(f"--- Phase {i}: {pr['name'].upper()} ---")
            if pr.get("skipped"):
                lines.append("  (skipped -- no observation data)")
                lines.append("")
                continue
            if pr.get("error"):
                lines.append(f"  ERROR: {pr['error']}")
                lines.append("")
                continue

            metrics = pr.get("metrics", {})
            for metric_name, metric_val in metrics.items():
                lines.append(f"  {metric_name.upper():10s}: {metric_val:.4f}")

            params = pr.get("parameters", {})
            if params:
                lines.append(f"  Parameters ({len(params)}):")
                for pname, pval in params.items():
                    lines.append(f"    {pname}: {pval:.6f}")
            lines.append("")

        lines.append("ALL LOCKED PARAMETERS:")
        for pname, pval in self.all_best_parameters.items():
            lines.append(f"  {pname}: {pval:.6f}")
        lines.append("=" * 70)

        print("\n".join(lines))

    def summary(self) -> str:
        """Return summary as a string."""
        import io
        import contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.print_summary()
        return buf.getvalue()


# ---------------------------------------------------------------------------
# PhasedCalibrator
# ---------------------------------------------------------------------------

class PhasedCalibrator:
    """Sequential multi-constituent calibrator.

    Runs calibration phases in order (typically Flow -> Sediment ->
    Nitrogen -> Phosphorus).  After each phase the best parameter values
    are written into the model files ("locked"), so subsequent phases
    build on top of the calibrated hydrology/sediment/etc.

    Args:
        model: SWATModel instance.
        flow_observations: DataFrame with ``date`` and ``observed`` columns
            containing daily streamflow (m3/s or cms).
        wq_observations: DataFrame from ``WQObservationLoader`` with ``date``
            and concentration columns (``TN_mg_L``, ``TP_mg_L``,
            ``TSS_mg_L``, etc.).  Required for WQ phases; can be None if
            only streamflow is calibrated.
        reach_id: Reach (or subbasin) ID for output extraction.
        phases: Custom list of :class:`PhaseConfig` objects.  If None,
            the default 4-phase sequence is built from
            :data:`CONSTITUENT_PHASES`, with WQ phases auto-disabled when
            the corresponding observation column is missing.
        warmup_years: Simulation warmup years to exclude from evaluation.
        progress_callback: Optional callable receiving a dict with progress
            information (``phase``, ``phase_index``, ``total_phases``,
            ``simulation_count``, ``elapsed_seconds``, etc.).
        cancel_state: A ``CalibrationState``-like object with a
            ``cancel_requested`` attribute for cooperative cancellation.
        **kwargs: Extra keyword arguments forwarded to ``Calibrator`` and
            ``MultiConstituentSetup`` constructors (e.g.
            ``upstream_subbasins``, ``qswat_shapes_dir``, ``print_code``,
            ``custom_sim_period``).

    Example::

        calibrator = PhasedCalibrator(
            model=model,
            flow_observations=flow_df,
            wq_observations=wq_df,
            reach_id=14,
            warmup_years=2,
        )
        result = calibrator.calibrate()
        result.print_summary()
    """

    def __init__(
        self,
        model,
        flow_observations: pd.DataFrame,
        wq_observations: pd.DataFrame = None,
        reach_id: int = 1,
        phases: List[PhaseConfig] = None,
        warmup_years: int = 1,
        progress_callback: Optional[Callable] = None,
        cancel_state=None,
        cancel_file: Optional[str] = None,
        **kwargs,
    ):
        # Create working copy so locked params between phases don't
        # modify the original model directory.
        import shutil
        _ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        self._working_dir = model.project_dir.parent / f".swat_phased_{_ts}"
        shutil.copytree(model.project_dir, self._working_dir)
        from swat_modern.core.model import SWATModel
        self.model = SWATModel(str(self._working_dir), executable=model.executable)

        self.flow_observations = flow_observations
        self.wq_observations = wq_observations
        self.reach_id = reach_id
        self.warmup_years = warmup_years
        self.progress_callback = progress_callback
        self.cancel_state = cancel_state
        # Cross-process cancel flag path for parallel SPOTPY workers.
        # Propagated to every phase's inner setup so ``simulation()`` can
        # short-circuit when the user clicks Cancel in the UI.
        self.cancel_file = cancel_file
        self.kge_target = kwargs.pop("kge_target", 0.70)
        self.pbias_target = kwargs.pop("pbias_target", 10.0)
        self.parallel = kwargs.pop("parallel", False)
        self.n_cores = kwargs.pop("n_cores", None)
        self.n_ensemble_workers = kwargs.pop("n_ensemble_workers", 4)
        self.kwargs = kwargs

        # Accumulated locked parameters (name -> value) from completed phases
        self._locked_params: Dict[str, float] = {}

        # Build default phases if none provided
        if phases is not None:
            self.phases = phases
        else:
            self.phases = self._build_default_phases()

        logger.info(
            "PhasedCalibrator initialized: %d phases, reach_id=%d",
            len(self.phases),
            self.reach_id,
        )

    # ------------------------------------------------------------------
    # Default phase construction
    # ------------------------------------------------------------------

    def _build_default_phases(self) -> List[PhaseConfig]:
        """Build the default 4-phase sequence from CONSTITUENT_PHASES.

        Phase 1 (streamflow) is always enabled.  WQ phases are enabled
        only if the corresponding observation column exists in
        ``wq_observations``.
        """
        phases = []

        # Phase 1: streamflow (always included)
        flow_info = CONSTITUENT_PHASES["streamflow"]
        flow_params = [p.name for p in flow_info["parameters_func"]()]
        phases.append(PhaseConfig(
            name="streamflow",
            parameters=flow_params,
            output_variable=flow_info["output_variable"],
            n_iterations=flow_info["default_iterations"],
            algorithm="sceua",
            objective=flow_info["default_objective"],
            enabled=True,
            constituent=None,
        ))

        # WQ phases: sediment, nitrogen, phosphorus
        for phase_name in ("sediment", "nitrogen", "phosphorus"):
            phase_info = CONSTITUENT_PHASES[phase_name]
            param_objs = phase_info["parameters_func"]()
            param_names = [p.name for p in param_objs]
            obs_col = _PHASE_TO_OBS_COLUMN.get(phase_name)
            constituent = _PHASE_TO_CONSTITUENT.get(phase_name)

            # Auto-enable only if observation data is available
            enabled = False
            if self.wq_observations is not None and obs_col is not None:
                if obs_col in self.wq_observations.columns:
                    n_valid = self.wq_observations[obs_col].notna().sum()
                    enabled = n_valid > 0

            phases.append(PhaseConfig(
                name=phase_name,
                parameters=param_names,
                output_variable=phase_info["output_variable"],
                n_iterations=phase_info["default_iterations"],
                algorithm="sceua",
                objective=phase_info["default_objective"],
                enabled=enabled,
                constituent=constituent,
            ))

        return phases

    @classmethod
    def get_default_phases(cls) -> List[PhaseConfig]:
        """Return a list of PhaseConfig for the default 4-phase sequence.

        All phases are enabled.  Callers can selectively disable phases
        or override algorithm/iterations before passing the list to the
        constructor.

        Returns:
            List of four PhaseConfig objects (streamflow, sediment,
            nitrogen, phosphorus).
        """
        phases = []
        for phase_name in ("streamflow", "sediment", "nitrogen", "phosphorus"):
            phase_info = CONSTITUENT_PHASES[phase_name]
            param_objs = phase_info["parameters_func"]()
            param_names = [p.name for p in param_objs]
            constituent = _PHASE_TO_CONSTITUENT.get(phase_name)

            phases.append(PhaseConfig(
                name=phase_name,
                parameters=param_names,
                output_variable=phase_info["output_variable"],
                n_iterations=phase_info["default_iterations"],
                algorithm="sceua",
                objective=phase_info["default_objective"],
                enabled=True,
                constituent=constituent,
            ))
        return phases

    # ------------------------------------------------------------------
    # Cancellation helper
    # ------------------------------------------------------------------

    def _is_cancelled(self) -> bool:
        """Check whether the user has requested cancellation."""
        if self.cancel_state is not None:
            return getattr(self.cancel_state, "cancel_requested", False)
        return False

    # ------------------------------------------------------------------
    # Progress reporting
    # ------------------------------------------------------------------

    def _report_phase_progress(
        self,
        phase_index: int,
        phase_name: str,
        status: str,
        extra: Optional[Dict] = None,
    ) -> None:
        """Send a progress update to the callback, if set."""
        if self.progress_callback is None:
            return
        enabled_phases = [p for p in self.phases if p.enabled]
        info = {
            "phase": phase_name,
            "phase_index": phase_index,
            "total_phases": len(enabled_phases),
            "status": status,
        }
        if extra:
            info.update(extra)
        try:
            self.progress_callback(info)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Main calibration loop
    # ------------------------------------------------------------------

    def calibrate(self) -> PhasedCalibrationResult:
        """Run all enabled phases sequentially.

        Returns:
            PhasedCalibrationResult with per-phase results and the merged
            best parameter set.
        """
        enabled_phases = [p for p in self.phases if p.enabled]
        total_phases = len(enabled_phases)

        logger.info(
            "Starting phased calibration: %d enabled phases out of %d total",
            total_phases,
            len(self.phases),
        )

        phase_results: List[Dict] = []
        phases_completed = 0
        start_time = time.time()

        try:
            for idx, phase in enumerate(enabled_phases):
                if self._is_cancelled():
                    logger.info("Phased calibration cancelled before phase '%s'", phase.name)
                    break

                # Phase header
                print(f"\n{'#' * 70}")
                print(f"# PHASE {idx + 1}/{total_phases}: {phase.name.upper()}")
                print(f"#   Parameters: {len(phase.parameters)}")
                print(f"#   Algorithm:  {phase.algorithm}")
                print(f"#   Iterations: {phase.n_iterations:,}")
                print(f"#   Objective:  {phase.objective}")
                if phase.constituent:
                    print(f"#   Constituent: {phase.constituent}")
                print(f"{'#' * 70}")

                self._report_phase_progress(idx, phase.name, "starting")

                try:
                    # Check WQ observation data availability before running
                    if phase.name != "streamflow":
                        obs_col = _PHASE_TO_OBS_COLUMN.get(phase.name)
                        if (
                            self.wq_observations is None
                            or obs_col is None
                            or obs_col not in self.wq_observations.columns
                            or self.wq_observations[obs_col].notna().sum() == 0
                        ):
                            reason = (
                                "no WQ observation data"
                                if self.wq_observations is None
                                else f"missing column '{obs_col}' in observation data"
                            )
                            print(f"\n  Skipping phase '{phase.name}': {reason}")
                            phase_results.append({
                                "name": phase.name,
                                "parameters": {},
                                "metrics": {},
                                "result": None,
                                "skipped": True,
                                "error": None,
                                "algorithm": phase.algorithm,
                                "n_iterations": phase.n_iterations,
                                "output_variable": phase.output_variable,
                                "diagnostic_info": {},
                            })
                            self._report_phase_progress(idx, phase.name, "skipped")
                            continue

                    diagnostic_info = {}
                    if phase.name == "streamflow":
                        cal_result = self._run_flow_phase(phase)
                    elif phase.algorithm in ("diagnostic", "diagnostic_ensemble"):
                        cal_result, diag_result = self._run_wq_diagnostic_phase(phase)
                        diagnostic_info = self._extract_diagnostic_info(diag_result)
                    else:
                        cal_result = self._run_wq_phase(phase)

                    # Collect best parameters from this phase
                    best_params = cal_result.best_parameters
                    metrics = cal_result.metrics

                    # Lock the best parameters
                    self._locked_params.update(best_params)
                    self._apply_locked_params_to_model(best_params)

                    phase_results.append({
                        "name": phase.name,
                        "parameters": dict(best_params),
                        "metrics": dict(metrics),
                        "result": cal_result,
                        "skipped": False,
                        "error": None,
                        "algorithm": phase.algorithm,
                        "n_iterations": phase.n_iterations,
                        "output_variable": phase.output_variable,
                        "diagnostic_info": diagnostic_info,
                    })
                    phases_completed += 1

                    logger.info(
                        "Phase '%s' completed: best_obj=%.4f, %d params locked",
                        phase.name,
                        cal_result.best_objective,
                        len(best_params),
                    )

                    self._report_phase_progress(idx, phase.name, "completed", {
                        "best_objective": cal_result.best_objective,
                        "metrics": metrics,
                    })

                except Exception as e:
                    logger.error("Phase '%s' failed: %s", phase.name, e, exc_info=True)
                    print(f"\nERROR in phase '{phase.name}': {e}")

                    phase_results.append({
                        "name": phase.name,
                        "parameters": {},
                        "metrics": {},
                        "result": None,
                        "skipped": False,
                        "error": str(e),
                        "algorithm": phase.algorithm,
                        "n_iterations": phase.n_iterations,
                        "output_variable": phase.output_variable,
                        "diagnostic_info": {},
                    })

                    self._report_phase_progress(idx, phase.name, "error", {
                        "error": str(e),
                    })

                    # Continue to next phase -- downstream phases can still
                    # run with whatever parameters are currently in the model.
                    continue

        finally:
            # Clean up working copy — original model is never modified.
            self._cleanup_working_dir()

        total_runtime = time.time() - start_time

        result = PhasedCalibrationResult(
            phase_results=phase_results,
            all_best_parameters=dict(self._locked_params),
            total_runtime=total_runtime,
            phases_completed=phases_completed,
            phases_total=total_phases,
        )

        print(f"\nPhased calibration finished: "
              f"{phases_completed}/{total_phases} phases in {total_runtime:.1f}s")
        result.print_summary()

        return result

    def _cleanup_working_dir(self):
        """Remove the temporary working directory."""
        import shutil
        if hasattr(self, "_working_dir") and self._working_dir is not None:
            if self._working_dir.exists():
                try:
                    shutil.rmtree(self._working_dir)
                except Exception:
                    pass
            self._working_dir = None

    # ------------------------------------------------------------------
    # Phase runners
    # ------------------------------------------------------------------

    def _run_flow_phase(self, phase: PhaseConfig):
        """Run the streamflow calibration phase.

        Uses the existing ``Calibrator`` class which handles SPOTPY setup,
        algorithm dispatch, backup/restore, and result extraction.

        Args:
            phase: PhaseConfig for the streamflow phase.

        Returns:
            CalibrationResult from the calibration run.
        """
        from swat_modern.calibration.calibrator import Calibrator

        # Build a per-phase progress callback that wraps our outer callback
        inner_callback = self._make_inner_callback(phase.name)

        calibrator = Calibrator(
            model=self.model,
            observed_data=self.flow_observations,
            parameters=phase.parameters,
            output_variable=phase.output_variable,
            output_type="rch",
            reach_id=self.reach_id,
            objective=phase.objective,
            warmup_years=self.warmup_years,
            **self._filter_kwargs_for_calibrator(),
        )

        # Attach cancel state + event to the SPOTPY setup so cooperative
        # cancellation works inside the simulation loop AND the runner
        # can terminate the SWAT process mid-execution.
        if self.cancel_state is not None:
            calibrator._setup._cancel_state = self.cancel_state
            calibrator._setup._cancel_event = getattr(
                self.cancel_state, "cancel_event", None
            )
        # Cross-process cancel flag — required for parallel SPOTPY
        # workers (threading.Event does not cross process boundaries).
        if self.cancel_file is not None:
            calibrator._setup._cancel_file = self.cancel_file

        result = calibrator.auto_calibrate(
            n_iterations=phase.n_iterations,
            algorithm=phase.algorithm,
            verbose=True,
            progress_callback=inner_callback,
            kge_target=self.kge_target,
            pbias_target=self.pbias_target,
            parallel=self.parallel,
            n_cores=self.n_cores,
            n_ensemble_workers=self.n_ensemble_workers,
        )

        return result

    def _run_wq_phase(self, phase: PhaseConfig):
        """Run a water quality calibration phase (sediment, nitrogen, or phosphorus).

        Steps:
        1. Apply all previously locked parameters to the model files.
        2. Create a MultiConstituentSetup for the phase's constituent.
        3. Run a SPOTPY algorithm on the setup.
        4. Extract and return the CalibrationResult.

        Args:
            phase: PhaseConfig for a WQ phase (sediment, nitrogen, phosphorus).

        Returns:
            CalibrationResult from the calibration run.

        Raises:
            ImportError: If SPOTPY is not installed.
            ValueError: If wq_observations is None or missing the required
                constituent column.
        """
        import spotpy
        from swat_modern.calibration.spotpy_setup import (
            MultiConstituentSetup,
            _CancelSignal,
        )
        from swat_modern.calibration.calibrator import CalibrationResult
        from swat_modern.calibration.objectives import evaluate_model

        if self.wq_observations is None:
            raise ValueError(
                f"wq_observations is required for phase '{phase.name}'"
            )

        constituent = phase.constituent
        if constituent is None:
            constituent = _PHASE_TO_CONSTITUENT.get(phase.name)
        if constituent is None:
            raise ValueError(
                f"No constituent mapping for phase '{phase.name}'. "
                f"Set phase.constituent explicitly."
            )

        # Step 1: Locked parameters from earlier phases are already in the
        # model files (applied by _apply_locked_params_to_model after each
        # phase).  Re-apply them to be safe in case the model was restored
        # externally.
        self._apply_locked_params_to_model(self._locked_params)

        # Step 2: Create MultiConstituentSetup
        constituents = [{"name": constituent, "weight": phase.weight}]

        setup_kwargs = {
            "warmup_years": self.warmup_years,
        }
        # Forward relevant kwargs
        for key in ("upstream_subbasins", "qswat_shapes_dir",
                     "print_code", "custom_sim_period", "timeout"):
            if key in self.kwargs:
                setup_kwargs[key] = self.kwargs[key]

        setup = MultiConstituentSetup(
            model=self.model,
            parameters=phase.parameters,
            constituents=constituents,
            wq_observations=self.wq_observations,
            flow_observations=self.flow_observations,
            comparison_mode="timeseries",
            objective=phase.objective,
            reach_id=self.reach_id,
            **setup_kwargs,
        )

        # Attach cancel state + event
        if self.cancel_state is not None:
            setup._cancel_state = self.cancel_state
            setup._cancel_event = getattr(
                self.cancel_state, "cancel_event", None
            )
        # Cross-process cancel flag — required for parallel SPOTPY workers.
        if self.cancel_file is not None:
            setup._cancel_file = self.cancel_file

        # Inner progress callback
        inner_callback = self._make_inner_callback(phase.name)
        setup.progress_callback = inner_callback

        # Step 3: Run SPOTPY algorithm
        algorithm_classes = {
            "sceua": spotpy.algorithms.sceua,
            "dream": spotpy.algorithms.dream,
            "mc": spotpy.algorithms.mc,
            "lhs": spotpy.algorithms.lhs,
            "rope": spotpy.algorithms.rope,
            "demcz": spotpy.algorithms.demcz,
        }

        algorithm = phase.algorithm.lower()
        AlgorithmClass = algorithm_classes.get(algorithm)
        if AlgorithmClass is None:
            raise ValueError(
                f"Unsupported algorithm '{phase.algorithm}' for WQ phase. "
                f"Available: {list(algorithm_classes.keys())}"
            )

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        dbname = f"phased_{phase.name}_{timestamp}"

        start_time = datetime.now()

        # Determine parallel mode
        parallel_mode = "seq"
        if self.parallel:
            try:
                import multiprocessing as _mp
                parallel_mode = "umpc"
                if self.n_cores and self.n_cores > 0:
                    _mp.cpu_count = lambda: self.n_cores
                    try:
                        import spotpy.parallel.mproc as _mproc
                        _mproc.cpu_count = lambda: self.n_cores
                    except ImportError:
                        pass
                logger.info(
                    "WQ phase '%s': parallel mode=%s, cores=%s",
                    phase.name, parallel_mode, self.n_cores or "auto",
                )
            except Exception as _pe:
                logger.warning("Could not enable parallel for WQ phase: %s", _pe)
                parallel_mode = "seq"

        try:
            sampler = AlgorithmClass(
                setup,
                dbname=dbname,
                dbformat="ram",
                parallel=parallel_mode,
            )

            if algorithm in ("sceua", "rope"):
                sampler.sample(
                    phase.n_iterations,
                    ngs=len(phase.parameters) + 1,
                )
            elif algorithm == "dream":
                # DREAM requires nChains >= 2*delta+1 (min 7 with default delta=3)
                sampler.sample(phase.n_iterations, nChains=7)
            else:
                sampler.sample(phase.n_iterations)

            end_time = datetime.now()
            runtime = (end_time - start_time).total_seconds()

            # Step 4: Extract results
            results = sampler.getdata()
            param_columns = [
                col for col in results.dtype.names if col.startswith("par")
            ]

            best_idx = np.argmax(results["like1"])
            best_params = {}
            for i, param_name in enumerate(phase.parameters):
                col_name = param_columns[i]
                best_params[param_name] = float(results[col_name][best_idx])

            best_objective = float(results["like1"][best_idx])

            all_params_df = pd.DataFrame({
                name: results[col]
                for name, col in zip(phase.parameters, param_columns)
            })

            # Run best simulation to get final outputs
            if setup._backup_dir is not None:
                setup.model.restore(
                    setup._backup_dir,
                    file_types=getattr(setup, "_modified_file_types", None),
                )
                setup._apply_print_code()
                setup._apply_nyskip()
                setup._apply_sim_period()

            # Re-apply locked params from earlier phases (restore wiped them)
            self._apply_locked_params_to_model(self._locked_params)

            # Apply best WQ params
            setup.parameter_set.set_values(best_params)
            setup.parameter_set.apply_to_model(setup.model)

            run_result = setup.model.run(capture_output=True)
            if not run_result.success:
                logger.warning(
                    "Final best-parameter run for phase '%s' failed: %s",
                    phase.name,
                    getattr(run_result, "error_message", "unknown error"),
                )

            # Extract final simulated/observed for metrics
            try:
                simulated = setup._extract_multi_constituent_values()
                observed = setup.evaluation()
            except Exception:
                simulated = np.array([])
                observed = np.array([])

            # Compute metrics
            metrics = {}
            if len(simulated) > 0 and len(observed) > 0:
                mask = ~(np.isnan(observed) | np.isnan(simulated))
                if np.sum(mask) > 3:
                    metrics = evaluate_model(observed[mask], simulated[mask])

            cal_result = CalibrationResult(
                best_parameters=best_params,
                best_objective=best_objective,
                all_parameters=all_params_df,
                all_objectives=results["like1"],
                observed=observed,
                simulated=simulated,
                runtime=runtime,
                n_iterations=phase.n_iterations,
                algorithm=phase.algorithm,
                metrics=metrics,
                objective_name=phase.objective,
            )

            print(f"\nPhase '{phase.name}' completed in {runtime:.1f}s")
            print(f"  Best {phase.objective.upper()}: {best_objective:.4f}")
            for k, v in metrics.items():
                print(f"  {k.upper()}: {v:.4f}")

            return cal_result

        except _CancelSignal:
            logger.info("WQ phase '%s' cancelled by user", phase.name)
            raise Exception(f"Phase '{phase.name}' cancelled by user")

        finally:
            setup.cleanup()

    def _run_wq_diagnostic_phase(self, phase: PhaseConfig):
        """Run a WQ phase using DiagnosticCalibrator instead of SPOTPY.

        This is selected when ``phase.algorithm`` is ``"diagnostic"`` or
        ``"diagnostic_ensemble"``.  The diagnostic calibrator analyses
        process-level metrics (sediment rating curves, phosphorus flow
        partitioning, etc.) and adjusts parameters in 5-20 targeted SWAT
        runs rather than blind sampling.

        When ``"diagnostic_ensemble"`` is selected (or ``"diagnostic"``
        with ``self.parallel=True``), dispatches to
        ``EnsembleDiagnosticCalibrator`` which runs N independent
        calibrators in parallel with diverse starting configs.

        Args:
            phase: PhaseConfig for a WQ phase with a diagnostic algorithm.

        Returns:
            Tuple of (CalibrationResult, DiagnosticCalibrationResult).
            The CalibrationResult is for standard pipeline consumption;
            the DiagnosticCalibrationResult carries diagnostic details
            (seasonal bias, rating curves, etc.) for UI display.
        """
        from swat_modern.calibration.diagnostic_calibrator import DiagnosticCalibrator

        if self.wq_observations is None:
            raise ValueError(
                f"wq_observations is required for phase '{phase.name}'"
            )

        # Prepare a DataFrame with 'date' and 'observed' columns from WQ obs
        wq_obs_df = self._prepare_wq_obs_for_diagnostic(phase)
        if wq_obs_df is None:
            raise ValueError(
                f"Could not prepare observation data for phase '{phase.name}'"
            )

        # Map phase name to constituent identifier used by DiagnosticCalibrator
        constituent_map = {
            "sediment": "sediment",
            "nitrogen": "nitrogen",
            "phosphorus": "phosphorus",
        }
        constituent = constituent_map.get(phase.name, phase.name)

        # Re-apply locked params before creating DiagnosticCalibrator
        # (it will create its own backup from current model state)
        self._apply_locked_params_to_model(self._locked_params)

        # Build extra kwargs shared by both single and ensemble calibrators
        extra = {}
        for key in ("upstream_subbasins", "qswat_shapes_dir", "custom_sim_period",
                     "print_code"):
            if key in self.kwargs:
                extra[key] = self.kwargs[key]

        # Decide whether to use ensemble (parallel multi-start) mode.
        # Ensemble is used when: algorithm is "diagnostic_ensemble", OR
        # algorithm is "diagnostic" with parallel=True.
        use_ensemble = (
            phase.algorithm == "diagnostic_ensemble"
            or (phase.algorithm == "diagnostic" and self.parallel)
        )

        if use_ensemble:
            from swat_modern.calibration.diagnostic_calibrator import (
                EnsembleDiagnosticCalibrator,
            )
            n_workers = self.n_ensemble_workers or self.n_cores or 4

            logger.info(
                "WQ diagnostic ensemble for phase '%s': %d workers",
                phase.name, n_workers,
            )

            dc = EnsembleDiagnosticCalibrator(
                model=self.model,
                observed_df=wq_obs_df,
                n_workers=n_workers,
                parameter_names=phase.parameters,
                reach_id=self.reach_id,
                output_variable=phase.output_variable,
                constituent=constituent,
                max_iterations=phase.n_iterations,
                warmup_years=self.warmup_years,
                kge_target=self.kge_target,
                pbias_target=self.pbias_target,
                upstream_subbasins=extra.get("upstream_subbasins"),
                qswat_shapes_dir=extra.get("qswat_shapes_dir"),
                progress_callback=self._make_phase_progress_cb(phase),
                cancel_state=self.cancel_state,
                custom_sim_period=extra.get("custom_sim_period"),
                print_code=extra.get("print_code"),
            )
        else:
            dc = DiagnosticCalibrator(
                model=self.model,
                observed_df=wq_obs_df,
                parameter_names=phase.parameters,
                reach_id=self.reach_id,
                output_variable=phase.output_variable,
                constituent=constituent,
                max_iterations=phase.n_iterations,
                warmup_years=self.warmup_years,
                kge_target=self.kge_target,
                pbias_target=self.pbias_target,
                upstream_subbasins=extra.get("upstream_subbasins"),
                qswat_shapes_dir=extra.get("qswat_shapes_dir"),
                progress_callback=self._make_phase_progress_cb(phase),
                cancel_state=self.cancel_state,
                custom_sim_period=extra.get("custom_sim_period"),
                print_code=extra.get("print_code"),
                _use_working_copy=False,  # PhasedCalibrator already has a working copy
            )

        diag_result = dc.calibrate()
        cal_result = diag_result.to_calibration_result()
        return cal_result, diag_result

    def _prepare_wq_obs_for_diagnostic(self, phase: PhaseConfig) -> Optional[pd.DataFrame]:
        """Prepare a DataFrame with 'date' and 'observed' columns for a WQ phase.

        DiagnosticCalibrator expects the same format as flow observations:
        a DataFrame with 'date' and 'observed' columns.  The observed values
        must be in the same units as the SWAT output variable (loads: kg/day
        for N/P, tons/day for sediment).

        WQ observations from ``WQObservationLoader`` are concentrations
        (mg/L).  This method converts them to loads by pairing with
        streamflow data (observed flow where available, otherwise a
        baseline SWAT simulation).

        Args:
            phase: PhaseConfig for the WQ phase.

        Returns:
            DataFrame with 'date' and 'observed' columns (loads in
            SWAT-compatible units), or None if the required observation
            column is missing.
        """
        from swat_modern.io.unit_converter import convert_obs_to_load

        obs_col = _PHASE_TO_OBS_COLUMN.get(phase.name)
        if obs_col is None or obs_col not in self.wq_observations.columns:
            return None

        constituent = _PHASE_TO_CONSTITUENT.get(phase.name)
        if constituent is None:
            return None

        # Find the date column in wq_observations
        date_col = None
        for c in self.wq_observations.columns:
            if c.lower() in ("date", "datetime"):
                date_col = c
                break
        if date_col is None:
            date_col = self.wq_observations.columns[0]

        df = self.wq_observations[[date_col, obs_col]].copy()
        df = df.rename(columns={date_col: "date"})
        df["date"] = pd.to_datetime(df["date"]).dt.normalize()
        df = df.dropna(subset=[obs_col])

        # --- Build a flow time series for concentration → load conversion ---
        # Priority: observed flow > baseline SWAT simulation
        flow_series = None

        if self.flow_observations is not None and isinstance(self.flow_observations, pd.DataFrame):
            flow_date_col = None
            for c in self.flow_observations.columns:
                if c.lower() in ("date", "datetime"):
                    flow_date_col = c
                    break
            if flow_date_col is None:
                flow_date_col = self.flow_observations.columns[0]

            if "observed" in self.flow_observations.columns:
                flow_df = self.flow_observations[[flow_date_col, "observed"]].copy()
                flow_df = flow_df.rename(columns={flow_date_col: "date", "observed": "flow_cms"})
                flow_df["date"] = pd.to_datetime(flow_df["date"]).dt.normalize()
                df = pd.merge(df, flow_df, on="date", how="left")
                flow_series = df["flow_cms"]

        # If no observed flow (or too many gaps), run a baseline SWAT
        # simulation with locked hydrology params to get simulated flow.
        if flow_series is None or flow_series.notna().sum() < 5:
            logger.info(
                "Running baseline SWAT simulation to obtain flow "
                "for WQ observation load conversion (phase '%s')...",
                phase.name,
            )
            # Back up output files — model.run() deletes them, and if SWAT
            # fails the working copy's output needed by later phases is lost.
            import shutil
            _WQ_OUTPUT_NAMES = (
                "output.rch", "output.sub", "output.hru",
                "output.rsv", "output.sed", "output.std",
            )
            _wq_output_backups = {}
            for _fname in _WQ_OUTPUT_NAMES:
                _src = self.model.project_dir / _fname
                if _src.exists():
                    _bak = _src.with_suffix(_src.suffix + ".bak_wq")
                    shutil.copy2(_src, _bak)
                    _wq_output_backups[_fname] = _bak

            try:
                self._apply_locked_params_to_model(self._locked_params)
                from swat_modern.calibration.spotpy_setup import run_baseline_simulation
                # Use a dummy observed_df just to get the full simulated time series
                dummy_obs = pd.DataFrame({
                    "date": df["date"],
                    "observed": np.zeros(len(df)),
                })
                baseline = run_baseline_simulation(
                    model=self.model,
                    observed_df=dummy_obs,
                    output_variable="FLOW_OUT",
                    reach_id=self.reach_id,
                    warmup_years=self.warmup_years,
                    upstream_subbasins=self.kwargs.get("upstream_subbasins"),
                    qswat_shapes_dir=self.kwargs.get("qswat_shapes_dir"),
                    print_code=self.kwargs.get("print_code"),
                )
                if baseline["success"] and baseline["simulated"] is not None:
                    sim_flow_df = pd.DataFrame({
                        "date": pd.to_datetime(baseline["dates"]),
                        "flow_cms": baseline["simulated"],
                    })
                    sim_flow_df["date"] = sim_flow_df["date"].dt.normalize()
                    df = df.drop(columns=["flow_cms"], errors="ignore")
                    df = pd.merge(df, sim_flow_df, on="date", how="left")
                    flow_series = df["flow_cms"]
                    logger.info(
                        "Baseline flow obtained: %d/%d WQ dates matched.",
                        flow_series.notna().sum(), len(df),
                    )
                else:
                    logger.warning(
                        "Baseline simulation failed for flow extraction; "
                        "WQ observations will remain as concentrations."
                    )
            except Exception as e:
                logger.warning(
                    "Could not run baseline for flow: %s; "
                    "WQ observations will remain as concentrations.",
                    e,
                )
            finally:
                # Restore output files so later phases find them intact.
                for _fname, _bak in _wq_output_backups.items():
                    _dst = self.model.project_dir / _fname
                    if _bak.exists():
                        shutil.copy2(_bak, _dst)
                        _bak.unlink()

        # --- Convert concentration to load ---
        if "flow_cms" in df.columns and df["flow_cms"].notna().any():
            concentration = df[obs_col].values
            flow_vals = df["flow_cms"].values
            loads = convert_obs_to_load(constituent, concentration, flow_vals)
            df["observed"] = loads
            df = df.dropna(subset=["observed"])
            logger.info(
                "Converted %d %s observations from concentration (mg/L) "
                "to load (%s).",
                len(df), phase.name,
                "tons/day" if constituent == "TSS" else "kg/day",
            )
        else:
            # Fallback: pass concentrations (will be unit-mismatched but
            # avoids a hard failure).  Log a clear warning.
            logger.warning(
                "No flow data available for phase '%s'; passing raw "
                "concentrations (mg/L) as observations.  Calibration "
                "metrics will be unreliable!",
                phase.name,
            )
            df["observed"] = df[obs_col]
            df = df.dropna(subset=["observed"])

        # Keep only date, observed, and optionally flow for process diagnostics
        keep_cols = ["date", "observed"]
        if "flow_cms" in df.columns:
            df = df.rename(columns={"flow_cms": "flow"})
            keep_cols.append("flow")
        df = df[keep_cols].reset_index(drop=True)

        return df

    def _make_phase_progress_cb(self, phase: PhaseConfig) -> Optional[Callable]:
        """Create a progress callback for DiagnosticCalibrator phases.

        DiagnosticCalibrator progress callbacks have signature
        ``(step, total, message)`` — different from SPOTPY's dict-based
        format.  This adapter translates to the phased-calibrator format.

        Args:
            phase: PhaseConfig for the current phase.

        Returns:
            A callable suitable for DiagnosticCalibrator.progress_callback,
            or None if no outer callback is set.
        """
        if self.progress_callback is None:
            return None

        enabled = [p for p in self.phases if p.enabled]
        phase_idx = next(
            (i for i, p in enumerate(enabled) if p.name == phase.name),
            0,
        )
        total = len(enabled)
        outer = self.progress_callback

        def _diag_cb(step: int, max_steps: int, message: str) -> None:
            """Translate diagnostic progress to phased progress format."""
            try:
                outer({
                    "phase": phase.name,
                    "phase_index": phase_idx,
                    "total_phases": total,
                    "status": "running",
                    "simulation_count": step,
                    "step_message": message,
                })
            except Exception:
                pass

        return _diag_cb

    # ------------------------------------------------------------------
    # Diagnostic info extraction
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_diagnostic_info(diag_result) -> Dict:
        """Extract UI-friendly diagnostic details from a DiagnosticCalibrationResult.

        Pulls seasonal bias, rating curve, flow partition, timing, event
        partition, and finding names from the last diagnostic step's
        summary dict so that the Results page can render charts without
        importing internal calibration types.

        Args:
            diag_result: A ``DiagnosticCalibrationResult`` instance.

        Returns:
            Dict with keys ``seasonal_bias``, ``rating_curve``,
            ``flow_partition``, ``timing``, ``event_partition``,
            ``finding_names``, ``convergence_reason``, ``converged``,
            and ``total_runs``.
        """
        info: Dict = {}

        if diag_result.steps:
            last_step = diag_result.steps[-1]
            diag_summary = last_step.diagnostic_summary

            # Extract diagnostic sub-dicts that the UI may render
            info["seasonal_bias"] = diag_summary.get("seasonal_bias", {})
            info["rating_curve"] = diag_summary.get("rating_curve", {})
            info["flow_partition"] = diag_summary.get("flow_partition", {})
            info["timing"] = diag_summary.get("timing", {})
            info["event_partition"] = diag_summary.get("event_partition", {})
            info["finding_names"] = diag_summary.get("finding_names", [])

        info["convergence_reason"] = diag_result.convergence_reason
        info["converged"] = diag_result.converged
        info["total_runs"] = diag_result.total_runs

        return info

    # ------------------------------------------------------------------
    # Parameter locking
    # ------------------------------------------------------------------

    def _apply_locked_params_to_model(self, params: Dict[str, float]) -> None:
        """Write parameter values directly into the SWAT model files.

        This is the mechanism that "locks" parameters between phases.
        Subsequent phases create their own backup from the current model
        state, so these values are preserved across backup/restore cycles.

        Args:
            params: Dict of {parameter_name: calibrated_value}.
        """
        for param_name, value in params.items():
            param_def = CALIBRATION_PARAMETERS.get(param_name.upper())
            if param_def is None:
                logger.warning(
                    "Cannot lock unknown parameter '%s' -- skipping",
                    param_name,
                )
                continue

            try:
                self.model.modify_parameter(
                    param_name=param_name,
                    value=value,
                    file_type=param_def.file_type,
                    method=param_def.method,
                    decimal_precision=param_def.decimal_precision,
                )
                # Also apply per-HRU version for basin-wide params that have
                # an HRU equivalent (e.g. ESCO), same as ParameterSet.apply_to_model
                if (
                    param_def.file_type in ParameterSet.BASIN_WIDE_TYPES
                    and param_name.upper() in ParameterSet.BSN_TO_HRU_MAP
                ):
                    self.model.modify_parameter(
                        param_name=param_name,
                        value=value,
                        file_type="hru",
                        method=param_def.method,
                        decimal_precision=param_def.decimal_precision,
                    )
            except Exception as e:
                logger.warning(
                    "Failed to lock parameter '%s' = %s: %s",
                    param_name,
                    value,
                    e,
                )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _make_inner_callback(self, phase_name: str) -> Optional[Callable]:
        """Create a per-phase progress callback that wraps the outer one.

        The inner callback translates per-phase SPOTPY progress dicts
        into the phased-calibrator progress format.

        Args:
            phase_name: Name of the current phase.

        Returns:
            A callable suitable for SPOTPY progress_callback, or None if
            no outer callback is set.
        """
        if self.progress_callback is None:
            return None

        enabled = [p for p in self.phases if p.enabled]
        phase_idx = next(
            (i for i, p in enumerate(enabled) if p.name == phase_name),
            0,
        )
        total = len(enabled)
        outer = self.progress_callback

        def _inner(info: dict) -> None:
            """Forward SPOTPY progress with phase context."""
            try:
                wrapped = dict(info) if isinstance(info, dict) else {}
                wrapped["phase"] = phase_name
                wrapped["phase_index"] = phase_idx
                wrapped["total_phases"] = total
                outer(wrapped)
            except Exception:
                pass

        return _inner

    def _filter_kwargs_for_calibrator(self) -> Dict:
        """Extract kwargs that are safe to pass to Calibrator's constructor.

        Calibrator forwards unknown kwargs to SWATModelSetup, so we
        selectively pass through the ones that SWATModelSetup recognizes.

        Returns:
            Filtered dict of keyword arguments.
        """
        allowed = {
            "upstream_subbasins",
            "qswat_shapes_dir",
            "print_code",
            "custom_sim_period",
            "timeout",
        }
        return {k: v for k, v in self.kwargs.items() if k in allowed}
