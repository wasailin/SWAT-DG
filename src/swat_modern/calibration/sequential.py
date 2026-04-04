"""
Sequential upstream-to-downstream calibration engine.

Calibrates SWAT model parameters step-by-step, starting from the most
upstream observation site and proceeding downstream. At each step:
1. Only subbasins between the current gauge and previously calibrated
   upstream gauges are modified.
2. Previously calibrated parameters are locked.
3. Optionally, a truncated fig.fig is used so only the relevant
   subbasins are simulated (partial-basin optimization).

Example:
    >>> from swat_modern import SWATModel
    >>> from swat_modern.calibration.sequential import SequentialCalibrator
    >>>
    >>> model = SWATModel("C:/project")
    >>> calibrator = SequentialCalibrator(model)
    >>> calibrator.add_site(reach_id=3, observed=upstream_df)
    >>> calibrator.add_site(reach_id=7, observed=downstream_df)
    >>> results = calibrator.run(
    ...     parameters=["CN2", "ESCO", "GW_DELAY"],
    ...     n_iterations=5000,
    ... )
    >>> results.print_summary()
"""

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Union

import numpy as np
import pandas as pd

from swat_modern.calibration.parameters import (
    CalibrationParameter,
    ParameterSet,
    CALIBRATION_PARAMETERS,
)
from swat_modern.calibration.objectives import evaluate_model, model_performance_rating


@dataclass
class CalibrationStep:
    """One step in sequential calibration."""

    step_number: int
    reach_id: int
    subbasin_ids: List[int]
    observed_data: Union[pd.DataFrame, pd.Series, str, Path]
    weight: float = 1.0
    result: Optional[object] = None  # CalibrationResult from calibrator
    best_params: Optional[Dict[str, float]] = None
    metrics: Optional[Dict[str, float]] = None
    diagnostic_summary: Optional[Dict] = None
    runtime: float = 0.0

    def summary_line(self) -> str:
        """One-line summary for this step."""
        nse_str = f"{self.metrics['nse']:.4f}" if self.metrics else "N/A"
        return (
            f"Step {self.step_number}: Reach {self.reach_id} | "
            f"{len(self.subbasin_ids)} subbasins | NSE={nse_str} | "
            f"{self.runtime:.1f}s"
        )


@dataclass
class SequentialCalibrationResult:
    """Results from a complete sequential calibration run."""

    steps: List[CalibrationStep]
    total_runtime: float
    locked_parameters: Dict[int, Dict[str, float]]
    algorithm: str = "sceua"
    n_iterations_per_step: int = 5000

    def print_summary(self) -> None:
        """Print summary of all calibration steps."""
        print("\n" + "=" * 70)
        print("SEQUENTIAL CALIBRATION RESULTS")
        print("=" * 70)
        print(f"Algorithm: {self.algorithm.upper()}")
        print(f"Iterations per step: {self.n_iterations_per_step:,}")
        print(f"Total runtime: {self.total_runtime:.1f} seconds")
        print(f"Steps: {len(self.steps)}")
        print("-" * 70)

        for step in self.steps:
            print(step.summary_line())
            if step.best_params:
                for k, v in step.best_params.items():
                    print(f"    {k}: {v:.6f}")

        print("=" * 70)
        print(f"Total subbasins calibrated: {len(self.locked_parameters)}")
        print("=" * 70)

    def get_all_best_parameters(self) -> Dict[int, Dict[str, float]]:
        """Get best parameters for all subbasins (sub_id -> {param: value})."""
        return dict(self.locked_parameters)

    def get_metrics_by_step(self) -> pd.DataFrame:
        """Get performance metrics for each step as a DataFrame."""
        rows = []
        for step in self.steps:
            row = {
                "step": step.step_number,
                "reach_id": step.reach_id,
                "n_subbasins": len(step.subbasin_ids),
                "runtime_s": step.runtime,
            }
            if step.metrics:
                row.update(step.metrics)
            rows.append(row)
        return pd.DataFrame(rows)

    def summary(self) -> str:
        """Generate summary text."""
        lines = [
            "=" * 70,
            "SEQUENTIAL CALIBRATION RESULTS",
            "=" * 70,
            f"Algorithm: {self.algorithm.upper()}",
            f"Iterations per step: {self.n_iterations_per_step:,}",
            f"Total runtime: {self.total_runtime:.1f} seconds",
            f"Steps: {len(self.steps)}",
            "-" * 70,
        ]
        for step in self.steps:
            lines.append(step.summary_line())
        lines.append("=" * 70)
        return "\n".join(lines)


class SequentialCalibrator:
    """
    Upstream-to-downstream sequential calibrator.

    Strategy:
    1. Parse fig.fig to extract routing topology
    2. Order observation sites from upstream to downstream
    3. For each site (upstream first):
       a. Identify subbasins between this site and previously calibrated sites
       b. Run SPOTPY calibration modifying only those subbasins
       c. Lock the best parameters for those subbasins
       d. Proceed to next downstream site
    """

    ALGORITHMS = {
        "sceua": "SCE-UA",
        "dream": "DREAM",
        "mc": "Monte Carlo",
        "lhs": "Latin Hypercube",
        "rope": "ROPE",
        "demcz": "DE-MCZ",
        "abc": "ABC",
        "fscabc": "FSCABC",
    }

    def __init__(
        self,
        model,
        objective: str = "nse",
        use_partial_basin: bool = True,
        hydrology_only: bool = False,
        qswat_shapes_dir: Optional[Path] = None,
    ):
        """
        Initialize sequential calibrator.

        Args:
            model: SWATModel instance
            objective: Objective function for all steps
            use_partial_basin: If True, generate truncated fig.fig per step
                to skip downstream subbasins (significant speedup)
            hydrology_only: If True, enable hydrology-only mode to skip
                N/P, sediment, bacteria, and pesticide processes. Requires
                the custom swat_64calib.exe executable.
            qswat_shapes_dir: Path to QSWAT Watershed/Shapes directory
                containing rivs1.shp for GIS-based upstream detection.
                Auto-discovered from model project dir if not specified.
        """
        self.model = model
        self.objective = objective
        self.use_partial_basin = use_partial_basin
        self.hydrology_only = hydrology_only
        self._qswat_shapes_dir = qswat_shapes_dir
        self.sites: List[dict] = []
        self._topology = None

    def add_site(
        self,
        reach_id: int,
        observed: Union[pd.DataFrame, pd.Series, str, Path],
        weight: float = 1.0,
        upstream_subbasins: Optional[List[int]] = None,
    ) -> None:
        """
        Add an observation site for calibration.

        Args:
            reach_id: Reach/subbasin ID where observations are located
            observed: Observed data (DataFrame, Series, or CSV path)
            weight: Weight for this site (used in final reporting)
            upstream_subbasins: If provided, use this list instead of
                auto-detecting from GIS/fig.fig topology.
        """
        self.sites.append({
            "reach_id": reach_id,
            "observed": observed,
            "weight": weight,
            "upstream_subbasins": upstream_subbasins,
        })

    def _parse_topology(self):
        """Parse fig.fig to extract routing topology."""
        from swat_modern.io.parsers.fig_parser import FigFileParser

        fig_path = self.model.project_dir / "fig.fig"
        parser = FigFileParser(fig_path)
        parser.parse()
        self._topology = parser
        return parser

    def _order_sites_upstream_to_downstream(
        self, topology
    ) -> List[dict]:
        """
        Order sites from upstream to downstream.

        Sites with fewer upstream subbasins are more upstream.

        Upstream detection priority:
        1. User-specified ``upstream_subbasins`` per site
        2. GIS topology from ``rivs1.shp`` (auto-discovered or explicit)
        3. fig.fig ADD-chain tracing via ``get_upstream_subbasins_by_subbasin``
        """
        from swat_modern.io.parsers.fig_parser import (
            find_qswat_shapes_dir, get_gis_upstream_subbasins,
        )

        shapes_dir = (
            self._qswat_shapes_dir
            or find_qswat_shapes_dir(self.model.project_dir)
        )

        for site in self.sites:
            sub_id = site["reach_id"]  # user-provided subbasin ID

            if site.get("upstream_subbasins") is not None:
                upstream = set(site["upstream_subbasins"])
                upstream.add(sub_id)
            elif shapes_dir is not None:
                try:
                    upstream = get_gis_upstream_subbasins(shapes_dir, sub_id)
                except Exception:
                    upstream = topology.get_upstream_subbasins_by_subbasin(sub_id)
            else:
                upstream = topology.get_upstream_subbasins_by_subbasin(sub_id)

            site["_upstream_count"] = len(upstream)
            site["_upstream_subs"] = upstream
            # Store the translated reach ID for build_truncated_fig
            site["_translated_reach_id"] = topology.get_reach_for_subbasin(sub_id) or sub_id

        return sorted(self.sites, key=lambda s: s["_upstream_count"])

    def _compute_calibration_groups(
        self,
        ordered_sites: List[dict],
    ) -> List[CalibrationStep]:
        """
        For each site, determine which subbasins to calibrate.

        The first (most upstream) site calibrates all its upstream subbasins.
        Each subsequent site calibrates only subbasins NOT already covered.
        """
        steps = []
        calibrated_subs = set()

        for i, site in enumerate(ordered_sites):
            all_upstream = site["_upstream_subs"]
            new_subs = all_upstream - calibrated_subs

            step = CalibrationStep(
                step_number=i + 1,
                reach_id=site["reach_id"],
                subbasin_ids=sorted(list(new_subs)),
                observed_data=site["observed"],
                weight=site["weight"],
            )
            # Store translated reach ID for build_truncated_fig / output extraction
            step._translated_reach_id = site.get("_translated_reach_id", site["reach_id"])
            # Carry per-site upstream override for SWATModelSetup
            step._upstream_subbasins = site.get("upstream_subbasins")
            # Carry full resolved upstream set (GIS/user/fig) for build_truncated_fig
            step._all_upstream_subs = all_upstream
            steps.append(step)

            calibrated_subs.update(new_subs)

        return steps

    def run(
        self,
        parameters: Union[List[str], List[CalibrationParameter], ParameterSet] = None,
        n_iterations: int = 5000,
        algorithm: str = "sceua",
        warmup_years: int = 1,
        output_variable: str = "FLOW_OUT",
        output_type: str = "rch",
        parallel: bool = False,
        verbose: bool = True,
        progress_callback=None,
        print_code: Optional[int] = None,
        custom_sim_period: Optional[tuple] = None,
        cancel_state=None,
    ) -> SequentialCalibrationResult:
        """
        Run sequential upstream-to-downstream calibration.

        Args:
            parameters: Parameters to calibrate (names, objects, or ParameterSet)
            n_iterations: SPOTPY iterations per step
            algorithm: SPOTPY algorithm name
            warmup_years: Warmup years to skip in objective calculation
            output_variable: SWAT output variable
            output_type: Output file type (rch, sub, hru)
            verbose: Print progress messages
            progress_callback: Optional callable(step_number, total_steps, message)
                for UI progress reporting
            print_code: SWAT output print code (0=monthly, 1=daily).
                Passed to each SubbasinGroupSetup working copy.

        Returns:
            SequentialCalibrationResult with all step results
        """
        try:
            import spotpy
        except ImportError:
            raise ImportError(
                "SPOTPY is required for calibration.\n"
                "Install with: pip install spotpy"
            )

        if len(self.sites) < 2:
            raise ValueError(
                "Sequential calibration requires at least 2 observation sites. "
                "Use regular Calibrator for single-site calibration."
            )

        algorithm = algorithm.lower()
        if algorithm not in self.ALGORITHMS:
            available = ", ".join(self.ALGORITHMS.keys())
            raise ValueError(f"Unknown algorithm '{algorithm}'. Available: {available}")

        start_time = time.time()

        # Parse topology
        if verbose:
            print("\nParsing watershed topology from fig.fig...")
        topology = self._parse_topology()

        # Order sites and compute groups
        ordered_sites = self._order_sites_upstream_to_downstream(topology)
        steps = self._compute_calibration_groups(ordered_sites)

        if verbose:
            print(f"\n{'=' * 70}")
            print("SEQUENTIAL UPSTREAM-TO-DOWNSTREAM CALIBRATION")
            print(f"{'=' * 70}")
            print(f"Algorithm: {algorithm.upper()} - {self.ALGORITHMS[algorithm]}")
            print(f"Iterations per step: {n_iterations:,}")
            print(f"Objective: {self.objective.upper()}")
            print(f"Steps: {len(steps)}")
            print(f"Partial-basin optimization: {'ON' if self.use_partial_basin else 'OFF'}")
            print(f"Hydrology-only mode: {'ON' if self.hydrology_only else 'OFF'}")
            for step in steps:
                print(
                    f"  Step {step.step_number}: Reach {step.reach_id} "
                    f"({len(step.subbasin_ids)} subbasins: "
                    f"{step.subbasin_ids[:5]}{'...' if len(step.subbasin_ids) > 5 else ''})"
                )
            print(f"{'=' * 70}\n")

        locked_params: Dict[int, Dict[str, float]] = {}

        for step in steps:
            # Check cancel before starting a potentially long step
            if cancel_state is not None and getattr(cancel_state, "cancel_requested", False):
                break

            step_start = time.time()

            if verbose:
                print(
                    f"\n--- Step {step.step_number}/{len(steps)}: "
                    f"Calibrating reach {step.reach_id} "
                    f"({len(step.subbasin_ids)} subbasins) ---"
                )

            if progress_callback:
                progress_callback(
                    step.step_number,
                    len(steps),
                    f"Step {step.step_number}: Calibrating reach {step.reach_id}",
                )

            # Generate truncated fig.fig for partial-basin simulation
            # Use the translated reach ID (subbasin→reach) for topology ops
            _topo_reach = getattr(step, "_translated_reach_id", step.reach_id)
            fig_override = None
            if self.use_partial_basin:
                fig_override = (
                    self.model.project_dir
                    / f"fig_step{step.step_number}.fig"
                )
                # Use GIS/user-resolved upstream subbasins if available
                _active_subs = getattr(step, "_all_upstream_subs", None)

                n_subs = topology.build_truncated_fig(
                    _topo_reach, fig_override,
                    active_subbasins=_active_subs,
                )
                if verbose:
                    total_subs = len(topology.subbasins)
                    print(
                        f"  Partial-basin routing: {n_subs}/{total_subs} "
                        f"upstream subbasins (all {total_subs} simulated; "
                        f"downstream routing skipped)"
                    )

            # Create SPOTPY setup for this step
            from swat_modern.calibration.spotpy_setup import SubbasinGroupSetup

            setup_kwargs = dict(
                model=self.model,
                parameters=parameters,
                observed_data=step.observed_data,
                subbasin_ids=step.subbasin_ids,
                locked_parameters=locked_params,
                fig_path_override=fig_override,
                output_variable=output_variable,
                output_type=output_type,
                reach_id=step.reach_id,
                partial_basin_reach=step.reach_id if self.use_partial_basin else None,
                objective=self.objective,
                warmup_years=warmup_years,
                hydrology_only=self.hydrology_only,
                upstream_subbasins=getattr(step, "_upstream_subbasins", None),
                qswat_shapes_dir=self._qswat_shapes_dir,
            )
            if print_code is not None:
                setup_kwargs["print_code"] = print_code
            if custom_sim_period is not None:
                setup_kwargs["custom_sim_period"] = custom_sim_period
            setup = SubbasinGroupSetup(**setup_kwargs)

            # Attach cancel_state so simulation() can short-circuit
            if cancel_state is not None:
                setup._cancel_state = cancel_state
                setup._cancel_event = getattr(cancel_state, "cancel_event", None)

            # Create and run SPOTPY sampler
            algorithm_classes = {
                "sceua": spotpy.algorithms.sceua,
                "dream": spotpy.algorithms.dream,
                "mc": spotpy.algorithms.mc,
                "lhs": spotpy.algorithms.lhs,
                "rope": spotpy.algorithms.rope,
                "demcz": spotpy.algorithms.demcz,
                "abc": spotpy.algorithms.abc,
                "fscabc": spotpy.algorithms.fscabc,
            }

            AlgorithmClass = algorithm_classes[algorithm]

            from swat_modern.calibration.spotpy_setup import _CancelSignal

            sampler = AlgorithmClass(
                setup,
                dbname=f"seq_step{step.step_number}",
                dbformat="ram",
                parallel="seq" if not parallel else "mpc",
            )

            try:
                if algorithm in ["sceua", "rope"]:
                    n_params = len(setup.parameter_set.names)
                    sampler.sample(n_iterations, ngs=n_params + 1)
                elif algorithm == "dream":
                    sampler.sample(n_iterations, nChains=4)
                else:
                    sampler.sample(n_iterations)
            except _CancelSignal:
                print("[cancel] _CancelSignal caught in SequentialCalibrator — propagating")
                raise Exception("Calibration cancelled by user")

            # Extract best parameters
            results = sampler.getdata()
            param_columns = [
                col for col in results.dtype.names if col.startswith("par")
            ]

            best_idx = np.argmax(results["like1"])
            best_values = {}
            for j, pname in enumerate(setup.parameter_set.names):
                best_values[pname] = float(results[param_columns[j]][best_idx])

            step.best_params = best_values

            # Calculate metrics for this step (use setup.model, the working copy)
            setup.parameter_set.set_values(best_values)
            setup.parameter_set.apply_to_model(
                setup.model, subbasin_ids=step.subbasin_ids
            )
            # Apply locked params too for the final evaluation
            setup._apply_locked_parameters()

            try:
                setup.model.run(capture_output=True)
                simulated = setup._extract_simulated_values()
                observed = setup.evaluation()

                mask = ~(np.isnan(observed) | np.isnan(simulated))
                if np.sum(mask) > 10:
                    step.metrics = evaluate_model(observed[mask], simulated[mask])

                    # Run diagnostic analysis for this step
                    try:
                        from swat_modern.calibration.diagnostics import diagnose
                        _diag_report = diagnose(observed[mask], simulated[mask])
                        step.diagnostic_summary = _diag_report.summary_dict()
                    except Exception:
                        pass  # Diagnostics are optional
            except Exception as e:
                if verbose:
                    print(f"  Warning: Could not compute final metrics: {e}")

            step.runtime = time.time() - step_start

            # Lock parameters for subsequent steps
            for sub_id in step.subbasin_ids:
                locked_params[sub_id] = best_values.copy()

            if verbose:
                print(f"  Completed in {step.runtime:.1f}s")
                if step.metrics:
                    nse_val = step.metrics.get("nse", 0)
                    kge_val = step.metrics.get("kge", 0)
                    print(f"  NSE={nse_val:.4f}, KGE={kge_val:.4f}")
                print(f"  Best parameters: {best_values}")

            # Clean up this step's SPOTPY setup
            setup.cleanup()

            # Clean up temporary fig.fig
            if fig_override and fig_override.exists():
                fig_override.unlink()

        total_runtime = time.time() - start_time

        result = SequentialCalibrationResult(
            steps=steps,
            total_runtime=total_runtime,
            locked_parameters=locked_params,
            algorithm=algorithm,
            n_iterations_per_step=n_iterations,
        )

        if verbose:
            result.print_summary()

        return result


# ── Sequential Diagnostic Calibration ────────────────────────────────────

@dataclass
class SequentialDiagnosticResult:
    """Results from sequential diagnostic calibration."""

    steps: List[CalibrationStep]
    total_runtime: float
    locked_parameters: Dict[int, Dict[str, float]]
    total_runs: int

    def print_summary(self) -> None:
        """Print summary of all calibration steps."""
        print("\n" + "=" * 70)
        print("SEQUENTIAL DIAGNOSTIC CALIBRATION RESULTS")
        print("=" * 70)
        print(f"Total SWAT runs: {self.total_runs}")
        print(f"Total runtime: {self.total_runtime:.1f} seconds")
        print(f"Steps: {len(self.steps)}")
        print("-" * 70)

        for step in self.steps:
            kge_str = f"{step.metrics['kge']:.4f}" if step.metrics and "kge" in step.metrics else "N/A"
            pbias_str = f"{step.metrics['pbias']:.1f}%" if step.metrics and "pbias" in step.metrics else "N/A"
            print(
                f"Step {step.step_number}: Reach {step.reach_id} | "
                f"{len(step.subbasin_ids)} subbasins | KGE={kge_str} | "
                f"PBIAS={pbias_str} | {step.runtime:.1f}s"
            )
            if step.best_params:
                for k, v in step.best_params.items():
                    print(f"    {k}: {v:.6f}")

        print("=" * 70)
        print(f"Total subbasins calibrated: {len(self.locked_parameters)}")
        print("=" * 70)

    def get_all_best_parameters(self) -> Dict[int, Dict[str, float]]:
        """Get best parameters for all subbasins (sub_id -> {param: value})."""
        return dict(self.locked_parameters)

    def get_metrics_by_step(self) -> "pd.DataFrame":
        """Get performance metrics for each step as a DataFrame."""
        rows = []
        for step in self.steps:
            row = {
                "step": step.step_number,
                "reach_id": step.reach_id,
                "n_subbasins": len(step.subbasin_ids),
                "runtime_s": step.runtime,
            }
            if step.metrics:
                row.update(step.metrics)
            rows.append(row)
        return pd.DataFrame(rows)

    def summary(self) -> str:
        """Generate summary text."""
        lines = [
            "=" * 70,
            "SEQUENTIAL DIAGNOSTIC CALIBRATION RESULTS",
            "=" * 70,
            f"Total SWAT runs: {self.total_runs}",
            f"Total runtime: {self.total_runtime:.1f} seconds",
            f"Steps: {len(self.steps)}",
            "-" * 70,
        ]
        for step in self.steps:
            kge_str = f"{step.metrics['kge']:.4f}" if step.metrics and "kge" in step.metrics else "N/A"
            lines.append(
                f"Step {step.step_number}: Reach {step.reach_id} | "
                f"{len(step.subbasin_ids)} subbasins | KGE={kge_str} | "
                f"{step.runtime:.1f}s"
            )
        lines.append("=" * 70)
        return "\n".join(lines)


class SequentialDiagnosticCalibrator:
    """
    Sequential upstream-to-downstream diagnostic calibration.

    At each gauge site (ordered upstream first), runs DiagnosticCalibrator
    with parameters scoped to the incremental subbasins (those between
    this gauge and previously calibrated upstream gauges). Previously
    calibrated parameters are locked.

    Reuses topology parsing, site ordering, and calibration group
    computation from SequentialCalibrator.

    Args:
        model: SWATModel instance.
        objective: Objective function name (for reporting).
        qswat_shapes_dir: Path to QSWAT shapes for GIS topology.
    """

    def __init__(
        self,
        model,
        objective: str = "kge",
        qswat_shapes_dir: Optional[Path] = None,
        use_partial_basin: bool = True,
    ):
        self.model = model
        self.objective = objective
        self._qswat_shapes_dir = qswat_shapes_dir
        self.use_partial_basin = use_partial_basin
        self.sites: List[dict] = []
        self._topology = None

    def add_site(
        self,
        reach_id: int,
        observed: Union[pd.DataFrame, pd.Series, str, Path],
        weight: float = 1.0,
        upstream_subbasins: Optional[List[int]] = None,
    ) -> None:
        """Add an observation site for calibration."""
        self.sites.append({
            "reach_id": reach_id,
            "observed": observed,
            "weight": weight,
            "upstream_subbasins": upstream_subbasins,
        })

    def run(
        self,
        parameter_names: Optional[List[str]] = None,
        max_iterations_per_step: int = 15,
        kge_target: float = 0.70,
        pbias_target: float = 10.0,
        damping: float = 0.5,
        warmup_years: int = 0,
        output_variable: str = "FLOW_OUT",
        verbose: bool = True,
        progress_callback: Optional[Callable] = None,
        use_ensemble: bool = False,
        n_ensemble_workers: int = 4,
        custom_sim_period: Optional[tuple] = None,
        run_progress_callback: Optional[Callable] = None,
        cancel_state=None,
    ) -> SequentialDiagnosticResult:
        """
        Run sequential diagnostic calibration.

        Args:
            parameter_names: Parameters to calibrate (default: streamflow set).
            max_iterations_per_step: Max SWAT runs per site (default 15).
            kge_target: KGE convergence target.
            pbias_target: |PBIAS| convergence target.
            damping: Secant method damping.
            warmup_years: Extra warmup years to skip.
            output_variable: SWAT output variable.
            verbose: Print progress.
            progress_callback: Optional callable(step, total_steps, message)
                for step-level progress.
            use_ensemble: If True, use ensemble parallelism within each step.
            n_ensemble_workers: Workers per step for ensemble mode.

        Returns:
            SequentialDiagnosticResult with per-step results.
        """
        if len(self.sites) < 2:
            raise ValueError(
                "Sequential calibration requires at least 2 observation sites."
            )

        start_time = time.time()

        # Reuse SequentialCalibrator topology parsing
        _seq = SequentialCalibrator(
            model=self.model,
            objective=self.objective,
            qswat_shapes_dir=self._qswat_shapes_dir,
        )
        _seq.sites = list(self.sites)
        topology = _seq._parse_topology()
        ordered_sites = _seq._order_sites_upstream_to_downstream(topology)
        steps = _seq._compute_calibration_groups(ordered_sites)

        if verbose:
            print(f"\n{'=' * 70}")
            print("SEQUENTIAL DIAGNOSTIC CALIBRATION")
            print(f"{'=' * 70}")
            mode_str = "Ensemble" if use_ensemble else "Single"
            print(f"Mode: {mode_str} diagnostic per step")
            print(f"Max runs per step: {max_iterations_per_step}")
            print(f"Targets: KGE >= {kge_target}, |PBIAS| <= {pbias_target}%")
            print(f"Steps: {len(steps)}")
            for step in steps:
                print(
                    f"  Step {step.step_number}: Reach {step.reach_id} "
                    f"({len(step.subbasin_ids)} subbasins: "
                    f"{step.subbasin_ids[:5]}{'...' if len(step.subbasin_ids) > 5 else ''})"
                )
            print(f"{'=' * 70}\n")

        locked_params: Dict[int, Dict[str, float]] = {}
        total_runs = 0

        for step in steps:
            step_start = time.time()

            if verbose:
                print(
                    f"\n--- Step {step.step_number}/{len(steps)}: "
                    f"Calibrating reach {step.reach_id} "
                    f"({len(step.subbasin_ids)} subbasins) ---"
                )

            if progress_callback:
                progress_callback(
                    step.step_number,
                    len(steps),
                    f"Step {step.step_number}: Diagnostic calibration "
                    f"for reach {step.reach_id}",
                )

            # Check cancel before starting next step
            if cancel_state is not None and getattr(cancel_state, "cancel_requested", False):
                break

            # Auto-detect constituent from output variable for WQ support
            _OV_TO_CONST = {
                "FLOW_OUT": "flow", "FLOW_OUTcms": "flow",
                "SED_OUT": "sediment", "SED_OUTtons": "sediment",
                "TOT_N": "nitrogen", "TOT_Nkg": "nitrogen",
                "ORGN_OUT": "nitrogen", "ORGN_OUTkg": "nitrogen",
                "NO3_OUT": "nitrogen", "NO3_OUTkg": "nitrogen",
                "NH4_OUT": "nitrogen", "NH4_OUTkg": "nitrogen",
                "TOT_P": "phosphorus", "TOT_Pkg": "phosphorus",
                "ORGP_OUT": "phosphorus", "ORGP_OUTkg": "phosphorus",
                "MINP_OUT": "phosphorus", "MINP_OUTkg": "phosphorus",
            }
            _detected_constituent = _OV_TO_CONST.get(output_variable, "flow")

            # Common kwargs for DiagnosticCalibrator
            diag_kwargs = dict(
                parameter_names=parameter_names,
                reach_id=step.reach_id,
                output_variable=output_variable,
                warmup_years=warmup_years,
                max_iterations=max_iterations_per_step,
                kge_target=kge_target,
                pbias_target=pbias_target,
                damping=damping,
                upstream_subbasins=getattr(step, "_upstream_subbasins", None),
                qswat_shapes_dir=self._qswat_shapes_dir,
                subbasin_ids=step.subbasin_ids,
                locked_parameters=locked_params if locked_params else None,
                progress_callback=run_progress_callback or progress_callback,
                custom_sim_period=custom_sim_period,
                cancel_state=cancel_state,
                constituent=_detected_constituent,
                partial_basin_reach=step.reach_id if self.use_partial_basin else None,
            )

            if use_ensemble:
                from swat_modern.calibration.diagnostic_calibrator import (
                    EnsembleDiagnosticCalibrator,
                )
                calibrator = EnsembleDiagnosticCalibrator(
                    model=self.model,
                    observed_df=step.observed_data,
                    n_workers=n_ensemble_workers,
                    **diag_kwargs,
                )
            else:
                from swat_modern.calibration.diagnostic_calibrator import (
                    DiagnosticCalibrator,
                )
                calibrator = DiagnosticCalibrator(
                    model=self.model,
                    observed_df=step.observed_data,
                    **diag_kwargs,
                )

            result = calibrator.calibrate()
            total_runs += result.total_runs

            # Record step results
            step.best_params = dict(result.best_parameters)
            step.metrics = dict(result.best_metrics)
            step.diagnostic_summary = (
                result.steps[-1].diagnostic_summary if result.steps else None
            )
            step.result = result  # store full result for plots
            step.runtime = time.time() - step_start

            # Lock best parameters for these subbasins
            for sub_id in step.subbasin_ids:
                locked_params[sub_id] = dict(result.best_parameters)

            if verbose:
                kge_val = result.best_metrics.get("kge", float("nan"))
                pbias_val = result.best_metrics.get("pbias", float("nan"))
                status = "CONVERGED" if result.converged else "COMPLETED"
                print(
                    f"  {status}: {result.convergence_reason}"
                )
                print(
                    f"  KGE={kge_val:.4f}, PBIAS={pbias_val:.1f}%, "
                    f"{result.total_runs} runs, {step.runtime:.1f}s"
                )

        total_runtime = time.time() - start_time

        seq_result = SequentialDiagnosticResult(
            steps=steps,
            total_runtime=total_runtime,
            locked_parameters=locked_params,
            total_runs=total_runs,
        )

        if verbose:
            seq_result.print_summary()

        return seq_result
