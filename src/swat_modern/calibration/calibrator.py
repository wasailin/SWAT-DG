"""
High-level Calibrator class for SWAT model calibration.

Provides a simple, beginner-friendly interface for automated calibration
of SWAT models using SPOTPY algorithms.

Example:
    >>> from swat_modern import SWATModel
    >>> from swat_modern.calibration import Calibrator
    >>>
    >>> # Load model and create calibrator
    >>> model = SWATModel("C:/my_watershed")
    >>> calibrator = Calibrator(model, observed_data="streamflow.csv")
    >>>
    >>> # Run calibration with defaults
    >>> results = calibrator.auto_calibrate()
    >>>
    >>> # View results
    >>> results.plot_comparison()
    >>> results.save_best_parameters("best_params.json")
"""

import os
from pathlib import Path
from typing import Dict, List, Optional, Union, Callable
from dataclasses import dataclass, field
from datetime import datetime
import numpy as np
import pandas as pd

from swat_modern.calibration.parameters import (
    CalibrationParameter,
    ParameterSet,
    get_streamflow_parameters,
    get_sediment_parameters,
    get_nutrient_parameters,
)
from swat_modern.calibration.objectives import (
    ObjectiveFunction,
    evaluate_model,
    model_performance_rating,
    nse,
    kge,
    pbias,
)
from swat_modern.calibration.spotpy_setup import SWATModelSetup, MultiSiteSetup, _CancelSignal


@dataclass
class CalibrationResult:
    """
    Container for calibration results.

    Attributes:
        best_parameters: Dictionary of optimal parameter values
        best_objective: Best objective function value achieved
        all_parameters: DataFrame of all parameter sets tried
        all_objectives: Array of all objective values
        observed: Observed data used
        simulated: Best simulation results
        runtime: Total calibration time in seconds
        n_iterations: Number of iterations/evaluations
        algorithm: Algorithm used
        metrics: Dictionary of performance metrics (NSE, KGE, etc.)
        dates: Date array aligned with observed/simulated (optional)
        objective_name: Name of the objective function used (e.g. "nse", "kge")
        site_results: Per-site data for multi-site calibration. Each dict
            contains keys: reach_id, dates, observed, simulated, metrics.
        reach_id: Reach/subbasin ID for single-site calibration (optional).
    """

    best_parameters: Dict[str, float]
    best_objective: float
    all_parameters: pd.DataFrame
    all_objectives: np.ndarray
    observed: np.ndarray
    simulated: np.ndarray
    runtime: float
    n_iterations: int
    algorithm: str
    metrics: Dict[str, float] = field(default_factory=dict)
    dates: Optional[np.ndarray] = None
    objective_name: str = "nse"
    site_results: List[Dict] = field(default_factory=list)
    reach_id: Optional[int] = None

    def __post_init__(self):
        """Calculate metrics if not provided."""
        if not self.metrics and len(self.simulated) > 0:
            mask = ~(np.isnan(self.observed) | np.isnan(self.simulated))
            if np.sum(mask) > 10:
                obs = self.observed[mask]
                sim = self.simulated[mask]
                self.metrics = evaluate_model(obs, sim)

    def summary(self) -> str:
        """Generate summary text of calibration results."""
        lines = [
            "=" * 60,
            "CALIBRATION RESULTS SUMMARY",
            "=" * 60,
            f"Algorithm: {self.algorithm}",
            f"Iterations: {self.n_iterations:,}",
            f"Runtime: {self.runtime:.1f} seconds",
            "",
            "BEST OBJECTIVE FUNCTION VALUE:",
            f"  {self.best_objective:.4f}",
            "",
            "PERFORMANCE METRICS:",
        ]

        for metric, value in self.metrics.items():
            lines.append(f"  {metric.upper()}: {value:.4f}")

        if "nse" in self.metrics:
            rating = model_performance_rating(self.metrics["nse"])
            lines.append(f"  Rating: {rating}")

        lines.extend([
            "",
            "BEST PARAMETERS:",
        ])

        for param, value in self.best_parameters.items():
            lines.append(f"  {param}: {value:.6f}")

        lines.append("=" * 60)

        return "\n".join(lines)

    def print_summary(self) -> None:
        """Print calibration summary."""
        print(self.summary())

    def plot_comparison(
        self,
        figsize: tuple = (12, 6),
        title: str = None,
        show: bool = True,
        save_path: str = None,
    ):
        """
        Plot observed vs simulated time series.

        Args:
            figsize: Figure size (width, height)
            title: Plot title (auto-generated if None)
            show: Whether to display plot
            save_path: Path to save figure (optional)

        Returns:
            matplotlib figure
        """
        try:
            import matplotlib.pyplot as plt
        except ImportError:
            raise ImportError("matplotlib is required for plotting")

        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=figsize)

        # Time series plot
        x_axis = self.dates if self.dates is not None else np.arange(len(self.observed))
        ax1.plot(x_axis, self.observed, label="Observed", color="blue", linewidth=1)
        ax1.plot(x_axis, self.simulated, label="Simulated", color="red", linewidth=1, alpha=0.7)
        ax1.set_xlabel("Date" if self.dates is not None else "Time Step")
        ax1.set_ylabel("Value")
        ax1.legend()

        if title is None:
            obj_name = self.objective_name.upper()
            obj_val = self.metrics.get(self.objective_name, 0)
            title = f"Calibration Results ({obj_name} = {obj_val:.3f})"
        ax1.set_title(title)
        ax1.grid(True, alpha=0.3)

        # Scatter plot
        mask = ~(np.isnan(self.observed) | np.isnan(self.simulated))
        obs_valid = self.observed[mask]
        sim_valid = self.simulated[mask]

        ax2.scatter(obs_valid, sim_valid, alpha=0.5, s=10)

        # 1:1 line
        max_val = max(obs_valid.max(), sim_valid.max())
        min_val = min(obs_valid.min(), sim_valid.min())
        ax2.plot([min_val, max_val], [min_val, max_val], "k--", label="1:1 Line")

        ax2.set_xlabel("Observed")
        ax2.set_ylabel("Simulated")
        ax2.set_title("Observed vs Simulated")
        ax2.legend()
        ax2.grid(True, alpha=0.3)

        plt.tight_layout()

        if save_path:
            plt.savefig(save_path, dpi=150, bbox_inches="tight")

        if show:
            plt.show()

        return fig

    def plot_parameter_evolution(
        self,
        parameters: List[str] = None,
        figsize: tuple = None,
        show: bool = True,
    ):
        """
        Plot parameter values over calibration iterations.

        Args:
            parameters: Parameters to plot (default: all)
            figsize: Figure size
            show: Whether to display plot

        Returns:
            matplotlib figure
        """
        try:
            import matplotlib.pyplot as plt
        except ImportError:
            raise ImportError("matplotlib is required for plotting")

        if parameters is None:
            parameters = list(self.best_parameters.keys())

        n_params = len(parameters)

        if figsize is None:
            figsize = (12, 3 * n_params)

        fig, axes = plt.subplots(n_params, 1, figsize=figsize)

        if n_params == 1:
            axes = [axes]

        for ax, param in zip(axes, parameters):
            if param in self.all_parameters.columns:
                values = self.all_parameters[param].values
                ax.plot(values, alpha=0.7)
                ax.axhline(
                    self.best_parameters[param],
                    color="red",
                    linestyle="--",
                    label=f"Best: {self.best_parameters[param]:.4f}"
                )
                ax.set_ylabel(param)
                ax.legend()
                ax.grid(True, alpha=0.3)

        axes[-1].set_xlabel("Iteration")
        plt.suptitle("Parameter Evolution During Calibration")
        plt.tight_layout()

        if show:
            plt.show()

        return fig

    def save_best_parameters(self, filepath: str) -> None:
        """
        Save best parameters to JSON file.

        Args:
            filepath: Output file path
        """
        import json

        data = {
            "best_parameters": self.best_parameters,
            "best_objective": self.best_objective,
            "metrics": self.metrics,
            "algorithm": self.algorithm,
            "n_iterations": self.n_iterations,
            "timestamp": datetime.now().isoformat(),
        }

        with open(filepath, "w") as f:
            json.dump(data, f, indent=2)

        print(f"Parameters saved to: {filepath}")

    def save_full_results(self, filepath: str) -> None:
        """
        Save complete calibration results to CSV.

        Args:
            filepath: Output file path
        """
        # Combine parameters with objectives
        results = self.all_parameters.copy()
        results["objective"] = self.all_objectives

        results.to_csv(filepath, index=False)
        print(f"Full results saved to: {filepath}")


@dataclass
class SensitivityResult:
    """Container for sensitivity analysis results.

    Attributes:
        sensitivity: Sensitivity indices -- dict {param: S1} for FAST,
            or DataFrame with 'Parameter' and 'S1' columns for Sobol.
        best_parameters: Best-performing parameter set (highest objective).
        best_objective: Best objective function value found during SA.
        n_evaluations: Total number of model evaluations.
        runtime: Total runtime in seconds.
        method: SA method used ("fast" or "sobol").
    """

    sensitivity: Union[Dict[str, float], pd.DataFrame]
    best_parameters: Dict[str, float]
    best_objective: float
    n_evaluations: int
    runtime: float
    method: str


class Calibrator:
    """
    High-level interface for SWAT model calibration.

    This class provides a simple, beginner-friendly way to calibrate SWAT models
    using SPOTPY optimization algorithms.

    Supported algorithms:
    - SCE-UA (default): Shuffled Complex Evolution - robust global optimizer
    - DREAM: Differential Evolution Adaptive Metropolis - Bayesian
    - MC: Monte Carlo sampling
    - LHS: Latin Hypercube Sampling
    - ROPE: Robust Parameter Estimation

    Example:
        >>> from swat_modern import SWATModel
        >>> from swat_modern.calibration import Calibrator
        >>>
        >>> model = SWATModel("C:/my_watershed")
        >>> calibrator = Calibrator(
        ...     model=model,
        ...     observed_data="streamflow.csv",
        ...     parameters=["CN2", "ESCO", "GW_DELAY"]  # or None for defaults
        ... )
        >>>
        >>> # Quick calibration
        >>> results = calibrator.auto_calibrate(n_iterations=1000)
        >>> results.print_summary()
    """

    # Available algorithms with descriptions
    ALGORITHMS = {
        "sceua": "SCE-UA - Robust global optimization (recommended)",
        "dream": "DREAM - Bayesian sampling with uncertainty",
        "mc": "Monte Carlo - Random sampling",
        "lhs": "Latin Hypercube - Stratified random sampling",
        "rope": "ROPE - Robust parameter estimation",
        "demcz": "DE-MCZ - Differential Evolution MCMC",
        "abc": "ABC - Approximate Bayesian Computation",
        "fscabc": "FSCABC - Fast ABC",
        "diagnostic": "Diagnostic-Guided - Expert hydrograph analysis (5-20 runs)",
        "diagnostic_ensemble": "Diagnostic Ensemble - Parallel multi-start (5-20 runs x N cores)",
    }

    def __init__(
        self,
        model,
        observed_data: Union[pd.DataFrame, pd.Series, str, Path] = None,
        parameters: Union[List[str], List[CalibrationParameter], ParameterSet] = None,
        output_variable: str = "FLOW_OUT",
        output_type: str = "rch",
        reach_id: int = 1,
        objective: str = "nse",
        warmup_years: int = 1,
        **kwargs,
    ):
        """
        Initialize Calibrator.

        Args:
            model: SWATModel instance
            observed_data: Observed data (DataFrame, Series, or CSV path)
            parameters: Parameters to calibrate (list of names, CalibrationParameter
                        objects, ParameterSet, or None for defaults)
            output_variable: SWAT output variable to calibrate (default: FLOW_OUT)
            output_type: Output file type - "rch", "sub", or "hru"
            reach_id: Reach/subbasin/HRU ID for output extraction
            objective: Objective function - "nse", "kge", "pbias", "log_nse"
            warmup_years: Years to exclude from calibration (default: 1)
            **kwargs: Additional arguments passed to SWATModelSetup

        Example:
            >>> # Using default parameters for streamflow
            >>> calibrator = Calibrator(model, observed_data="flow.csv")

            >>> # Specifying parameters
            >>> calibrator = Calibrator(
            ...     model,
            ...     observed_data="flow.csv",
            ...     parameters=["CN2", "ESCO", "GW_DELAY", "ALPHA_BF"]
            ... )
        """
        self.model = model
        self.output_variable = output_variable
        self.output_type = output_type
        self.reach_id = reach_id
        self.objective = objective
        self.warmup_years = warmup_years
        self._print_code = kwargs.get("print_code")

        # Set default parameters if not provided
        if parameters is None:
            print("Using default streamflow calibration parameters:")
            default_params = get_streamflow_parameters()
            parameters = [p.name for p in default_params[:10]]
            print(f"  {', '.join(parameters)}")

        # Create SPOTPY setup
        self._setup = SWATModelSetup(
            model=model,
            parameters=parameters,
            observed_data=observed_data,
            output_variable=output_variable,
            output_type=output_type,
            reach_id=reach_id,
            objective=objective,
            warmup_years=warmup_years,
            **kwargs,
        )

        # Store for later
        self._last_result: Optional[CalibrationResult] = None

    @property
    def parameters(self) -> List[str]:
        """Get list of calibration parameter names."""
        return self._setup.parameter_set.names

    @property
    def parameter_set(self) -> ParameterSet:
        """Get the ParameterSet object."""
        return self._setup.parameter_set

    # Map SWAT output variable names to diagnostic constituent types
    _OUTPUT_VAR_TO_CONSTITUENT = {
        "FLOW_OUT": "flow", "FLOW_OUTcms": "flow",
        "SED_OUT": "sediment", "SED_OUTtons": "sediment",
        "SEDCONCmg_L": "sediment",
        "TOT_N": "nitrogen", "TOT_Nkg": "nitrogen",
        "ORGN_OUT": "nitrogen", "ORGN_OUTkg": "nitrogen",
        "NO3_OUT": "nitrogen", "NO3_OUTkg": "nitrogen",
        "NH4_OUT": "nitrogen", "NH4_OUTkg": "nitrogen",
        "TOT_P": "phosphorus", "TOT_Pkg": "phosphorus",
        "ORGP_OUT": "phosphorus", "ORGP_OUTkg": "phosphorus",
        "MINP_OUT": "phosphorus", "MINP_OUTkg": "phosphorus",
    }

    def _detect_constituent(self) -> str:
        """Auto-detect diagnostic constituent from the output variable."""
        ov = getattr(self._setup, "output_variable", "FLOW_OUT")
        # Try exact match first, then prefix match
        constituent = self._OUTPUT_VAR_TO_CONSTITUENT.get(ov)
        if constituent is None:
            for key, val in self._OUTPUT_VAR_TO_CONSTITUENT.items():
                if ov.startswith(key) or key.startswith(ov):
                    constituent = val
                    break
        return constituent or "flow"

    def auto_calibrate(
        self,
        n_iterations: int = 5000,
        algorithm: str = "sceua",
        parallel: bool = False,
        n_cores: int = None,
        dbname: str = None,
        dbformat: str = "csv",
        verbose: bool = True,
        progress_callback: Optional[Callable] = None,
        **kwargs,
    ) -> CalibrationResult:
        """
        Run automatic calibration.

        This is the main calibration method. It runs the specified algorithm
        for the given number of iterations.

        Args:
            n_iterations: Number of model evaluations (default: 5000)
                - Quick test: 500-1000
                - Standard: 5000-10000
                - Thorough: 20000-50000
            algorithm: Optimization algorithm (default: "sceua")
                - "sceua": SCE-UA (recommended for most cases)
                - "dream": DREAM (for uncertainty analysis)
                - "mc": Monte Carlo (simple random sampling)
                - "lhs": Latin Hypercube Sampling
            parallel: Enable parallel processing (experimental)
            n_cores: Number of CPU cores for parallel mode (default: all).
            dbname: Database name for saving results (optional)
            dbformat: Database format - "csv" or "sql"
            verbose: Print progress messages

        Returns:
            CalibrationResult with best parameters and performance metrics

        Example:
            >>> # Quick calibration
            >>> results = calibrator.auto_calibrate(n_iterations=1000)

            >>> # Full calibration with results saved
            >>> results = calibrator.auto_calibrate(
            ...     n_iterations=10000,
            ...     algorithm="sceua",
            ...     dbname="my_calibration"
            ... )
        """
        algorithm = algorithm.lower()
        if algorithm not in self.ALGORITHMS:
            available = ", ".join(self.ALGORITHMS.keys())
            raise ValueError(f"Unknown algorithm '{algorithm}'. Available: {available}")

        # Diagnostic-guided calibration (does not use SPOTPY)
        if algorithm in ("diagnostic", "diagnostic_ensemble"):
            # Auto-detect constituent from output variable
            _constituent = self._detect_constituent()
            # When parallel requested with diagnostic, auto-upgrade to ensemble
            if algorithm == "diagnostic" and parallel:
                import os as _os_diag
                _n_workers = kwargs.get("n_ensemble_workers", min(4, _os_diag.cpu_count() or 1))
                if _n_workers < 2:
                    _n_workers = n_cores or min(4, _os_diag.cpu_count() or 1)
                return self.ensemble_diagnostic_calibrate(
                    n_workers=_n_workers,
                    max_iterations=n_iterations,
                    kge_target=kwargs.get("kge_target", 0.70),
                    pbias_target=kwargs.get("pbias_target", 10.0),
                    verbose=verbose,
                    progress_callback=progress_callback,
                    constituent=_constituent,
                )
            elif algorithm == "diagnostic":
                return self.diagnostic_calibrate(
                    max_iterations=n_iterations,
                    kge_target=kwargs.get("kge_target", 0.70),
                    pbias_target=kwargs.get("pbias_target", 10.0),
                    verbose=verbose,
                    progress_callback=progress_callback,
                    constituent=_constituent,
                )
            else:
                return self.ensemble_diagnostic_calibrate(
                    n_workers=kwargs.get("n_ensemble_workers", 4),
                    max_iterations=n_iterations,
                    kge_target=kwargs.get("kge_target", 0.70),
                    pbias_target=kwargs.get("pbias_target", 10.0),
                    verbose=verbose,
                    progress_callback=progress_callback,
                    constituent=_constituent,
                )

        try:
            import spotpy
        except ImportError:
            raise ImportError(
                "SPOTPY is required for calibration.\n"
                "Install with: pip install spotpy"
            )

        if verbose:
            print(f"\n{'='*60}")
            print("SWAT MODEL CALIBRATION")
            print(f"{'='*60}")
            print(f"Algorithm: {algorithm.upper()} - {self.ALGORITHMS[algorithm]}")
            print(f"Parameters: {len(self.parameters)}")
            print(f"Iterations: {n_iterations:,}")
            print(f"Objective: {self.objective.upper()}")
            print(f"{'='*60}\n")

        # Set up database
        if dbname is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            dbname = f"calibration_{timestamp}"

        # Get algorithm class
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

        # Set progress callback on setup
        self._setup.progress_callback = progress_callback

        # Run calibration
        start_time = datetime.now()

        # Determine parallel mode and limit worker count
        _original_cpu_count = None
        parallel_mode = "seq"
        if parallel:
            try:
                import pathos  # noqa: F401
                parallel_mode = "mpc"
                if n_cores and n_cores > 0:
                    import multiprocessing as _mp
                    _original_cpu_count = _mp.cpu_count
                    _mp.cpu_count = lambda: n_cores
                    try:
                        import spotpy.parallel.mproc as _mproc
                        _mproc.process_count = n_cores
                    except (ImportError, AttributeError):
                        pass
                if verbose:
                    import multiprocessing as _mp
                    print(f"Parallel mode: {parallel_mode} ({_mp.cpu_count()} workers)")
            except ImportError:
                if verbose:
                    print("Warning: pathos not installed, falling back to sequential")

        try:
            sampler = AlgorithmClass(
                self._setup,
                dbname=dbname,
                dbformat=dbformat,
                parallel=parallel_mode,
            )

            if verbose:
                print("Starting calibration...")

            # Different algorithms have different sampling methods
            if algorithm in ["sceua", "rope"]:
                sampler.sample(n_iterations, ngs=len(self.parameters) + 1)
            elif algorithm == "dream":
                # DREAM requires nChains >= 2*delta+1 (default delta=3 -> min 7).
                # Passing fewer chains makes spotpy's sample() return None before
                # initializing self.datawriter, causing getdata() to crash with
                # AttributeError. Use 7 chains as the safe minimum.
                sampler.sample(n_iterations, nChains=7)
            else:
                sampler.sample(n_iterations)

            end_time = datetime.now()
            runtime = (end_time - start_time).total_seconds()

            if verbose:
                print(f"\nCalibration completed in {runtime:.1f} seconds")
                print(f"Simulations run: {self._setup.get_simulation_count()}")

            # Get results
            results = sampler.getdata()

            # Extract parameter columns
            param_columns = [
                col for col in results.dtype.names
                if col.startswith("par")
            ]

            # Get best run
            best_idx = np.argmax(results["like1"])
            best_params = {}
            for i, param_name in enumerate(self.parameters):
                col_name = param_columns[i]
                best_params[param_name] = float(results[col_name][best_idx])

            best_objective = float(results["like1"][best_idx])

            # Create DataFrame of all parameters
            all_params_df = pd.DataFrame({
                name: results[col]
                for name, col in zip(self.parameters, param_columns)
            })

            # Run best simulation on the working copy to get outputs.
            # Restore from backup first so "multiply" parameters are applied
            # to original file values, not values from the last trial.
            if verbose:
                print("\nRunning best parameter set...")

            if self._setup._backup_dir is not None:
                self._setup.model.restore(self._setup._backup_dir)
                self._setup._apply_print_code()
                self._setup._apply_nyskip()
                self._setup._apply_sim_period()

            # For SubbasinGroupSetup: apply locked parameters first,
            # then apply trial parameters only to the target subbasins.
            # Without this, partial-section calibration applies parameters
            # globally, causing severe degradation in non-section subbasins.
            if hasattr(self._setup, '_apply_locked_parameters'):
                self._setup._apply_locked_parameters()

            self._setup.parameter_set.set_values(best_params)
            _subbasin_ids = getattr(self._setup, 'subbasin_ids', None)
            if _subbasin_ids:
                self._setup.parameter_set.apply_to_model(
                    self._setup.model, subbasin_ids=_subbasin_ids
                )
            else:
                self._setup.parameter_set.apply_to_model(self._setup.model)

            # For partial-basin simulation: swap in truncated fig.fig and
            # active_subs.dat (these are not part of the selective backup).
            import shutil as _shutil_final
            _fig_override = getattr(self._setup, 'fig_path_override', None)
            if _fig_override and Path(_fig_override).exists():
                _shutil_final.copy2(
                    _fig_override,
                    self._setup.model.project_dir / "fig.fig",
                )
            elif getattr(self._setup, '_truncated_fig', None) is not None:
                if self._setup._truncated_fig.exists():
                    _shutil_final.copy2(
                        self._setup._truncated_fig,
                        self._setup.model.project_dir / "fig.fig",
                    )
            _active_subs = getattr(self._setup, '_active_subs_file', None)
            if _active_subs is not None and Path(_active_subs).exists():
                _shutil_final.copy2(
                    _active_subs,
                    self._setup.model.project_dir / "active_subs.dat",
                )

            run_result = self._setup.model.run(capture_output=True)

            if not run_result.success:
                print(
                    f"Warning: Final best-parameter run failed: "
                    f"{getattr(run_result, 'error_message', 'unknown error')}"
                )

            # Get simulated values
            simulated = self._setup._extract_simulated_values()
            observed = self._setup.evaluation()

            # Create result object
            result = CalibrationResult(
                best_parameters=best_params,
                best_objective=best_objective,
                all_parameters=all_params_df,
                all_objectives=results["like1"],
                observed=observed,
                simulated=simulated,
                runtime=runtime,
                n_iterations=n_iterations,
                algorithm=algorithm,
                dates=self._setup.observed_df["date"].values,
                objective_name=self.objective,
            )

            self._last_result = result

            if verbose:
                result.print_summary()

            return result

        except _CancelSignal:
            # _CancelSignal is a BaseException — convert to a regular
            # Exception so the caller's ``except Exception:`` handler
            # (which checks cancel_requested) can catch it.
            print("[cancel] _CancelSignal caught in auto_calibrate — propagating")
            raise Exception("Calibration cancelled by user")

        finally:
            if _original_cpu_count is not None:
                import multiprocessing as _mp
                _mp.cpu_count = _original_cpu_count
            self._setup.cleanup()

    def diagnostic_calibrate(
        self,
        max_iterations: int = 15,
        kge_target: float = 0.70,
        pbias_target: float = 10.0,
        damping: float = 0.5,
        verbose: bool = True,
        progress_callback: Optional[Callable] = None,
        constituent: str = "flow",
    ) -> CalibrationResult:
        """
        Run diagnostic-guided calibration (5-20 SWAT runs).

        Analyzes hydrograph deficiencies (volume, baseflow, peaks) and
        adjusts parameters intelligently, without sampling parameter space.

        Args:
            max_iterations: Maximum SWAT runs (default 15).
            kge_target: KGE convergence target (default 0.70).
            pbias_target: |PBIAS| convergence target (default 10%).
            damping: Secant method damping factor (default 0.5).
            verbose: Print progress messages.
            progress_callback: Optional callback(step, total, message).

        Returns:
            CalibrationResult with best parameters and metrics.
        """
        from swat_modern.calibration.diagnostic_calibrator import DiagnosticCalibrator

        if verbose:
            print(f"\n{'='*60}")
            print("DIAGNOSTIC-GUIDED CALIBRATION")
            print(f"{'='*60}")
            print(f"Parameters: {len(self.parameters)}")
            print(f"Max iterations: {max_iterations}")
            print(f"Targets: KGE >= {kge_target}, |PBIAS| <= {pbias_target}%")
            print(f"{'='*60}\n")

        param_names = list(self.parameters)  # already List[str]

        # Adapt SPOTPY-style progress callback to diagnostic-style (step, total, msg)
        diag_callback = None
        if progress_callback is not None:
            import re as _re_mod
            import time as _time_mod
            _diag_start = _time_mod.time()
            _best_kge = [float("-inf")]

            def diag_callback(step, total, message):
                try:
                    _elapsed = _time_mod.time() - _diag_start
                    _avg = _elapsed / max(step, 1)
                    # Extract KGE from message (e.g. "KGE=0.650")
                    _m = _re_mod.search(r"KGE=([0-9.\-]+)", message)
                    if _m:
                        _kge_val = float(_m.group(1))
                        if _kge_val > _best_kge[0]:
                            _best_kge[0] = _kge_val
                    progress_callback({
                        "simulation_count": step,
                        "total_iterations": total,
                        "elapsed_seconds": _elapsed,
                        "avg_time_per_sim": _avg,
                        "best_score": _best_kge[0] if _best_kge[0] > float("-inf") else -1e10,
                    })
                except Exception:
                    pass

        # Pass partial_basin_reach if SWATModelSetup prepared active_subs
        _pbr = None
        if getattr(self._setup, "_active_subs_file", None) is not None:
            _pbr = self._setup.reach_id

        calibrator = DiagnosticCalibrator(
            model=self._setup.model,  # use working copy, not original
            observed_df=self._setup.observed_df,
            parameter_names=param_names,
            reach_id=self._setup.reach_id,
            output_variable=self._setup.output_variable,
            warmup_years=self._setup.warmup_years,
            max_iterations=max_iterations,
            kge_target=kge_target,
            pbias_target=pbias_target,
            damping=damping,
            upstream_subbasins=getattr(self._setup, "upstream_subbasins", None),
            qswat_shapes_dir=getattr(self._setup, "qswat_shapes_dir", None),
            progress_callback=diag_callback,
            custom_sim_period=getattr(self._setup, "_custom_sim_period", None),
            cancel_state=getattr(self._setup, "_cancel_state", None),
            constituent=constituent,
            partial_basin_reach=_pbr,
            print_code=self._print_code,
            _use_working_copy=False,  # SWATModelSetup already created a copy
        )
        # Propagate cross-process cancel flag for file-based cancel check.
        _cf_attached = getattr(self._setup, "_cancel_file", None)
        if _cf_attached is not None:
            calibrator._cancel_file = _cf_attached

        diag_result = calibrator.calibrate()

        if verbose:
            status = "CONVERGED" if diag_result.converged else "COMPLETED"
            print(f"\n{status}: {diag_result.convergence_reason}")
            print(f"Total SWAT runs: {diag_result.total_runs}")
            print(f"Runtime: {diag_result.runtime:.1f}s")
            best_kge = diag_result.best_metrics.get("kge", np.nan)
            best_pb = diag_result.best_metrics.get("pbias", np.nan)
            print(f"Best KGE: {best_kge:.3f}, PBIAS: {best_pb:.1f}%")

        return diag_result.to_calibration_result()

    def ensemble_diagnostic_calibrate(
        self,
        n_workers: int = 4,
        max_iterations: int = 15,
        kge_target: float = 0.70,
        pbias_target: float = 10.0,
        damping: float = 0.5,
        verbose: bool = True,
        progress_callback: Optional[Callable] = None,
        constituent: str = "flow",
    ) -> CalibrationResult:
        """
        Run ensemble parallel diagnostic calibration (multi-start).

        Launches N independent DiagnosticCalibrators with diverse configs
        (damping, phase order) in parallel, then returns the best result.
        Same wall-clock time as single diagnostic, better solution quality.

        Args:
            n_workers: Number of parallel workers (default 4).
            max_iterations: Max SWAT runs per worker (default 15).
            kge_target: KGE convergence target (default 0.70).
            pbias_target: |PBIAS| convergence target (default 10%).
            damping: Base damping factor (workers vary around this).
            verbose: Print progress messages.
            progress_callback: Optional callback(step, total, message).

        Returns:
            CalibrationResult with best parameters and metrics.
        """
        from swat_modern.calibration.diagnostic_calibrator import (
            EnsembleDiagnosticCalibrator,
        )

        if verbose:
            print(f"\n{'='*60}")
            print("ENSEMBLE DIAGNOSTIC CALIBRATION")
            print(f"{'='*60}")
            print(f"Workers: {n_workers}")
            print(f"Parameters: {len(self.parameters)}")
            print(f"Max iterations per worker: {max_iterations}")
            print(f"Targets: KGE >= {kge_target}, |PBIAS| <= {pbias_target}%")
            print(f"{'='*60}\n")

        param_names = list(self.parameters)

        diag_callback = None
        if progress_callback is not None:
            import re as _re_mod2
            import time as _time_mod2
            _ens_start = _time_mod2.time()
            _best_kge2 = [float("-inf")]

            def diag_callback(step, total, message):
                try:
                    _elapsed = _time_mod2.time() - _ens_start
                    _avg = _elapsed / max(step, 1)
                    _m = _re_mod2.search(r"KGE=([0-9.\-]+)", message)
                    if _m:
                        _kge_val = float(_m.group(1))
                        if _kge_val > _best_kge2[0]:
                            _best_kge2[0] = _kge_val
                    progress_callback({
                        "simulation_count": step,
                        "total_iterations": total,
                        "elapsed_seconds": _elapsed,
                        "avg_time_per_sim": _avg,
                        "best_score": _best_kge2[0] if _best_kge2[0] > float("-inf") else -1e10,
                    })
                except Exception:
                    pass

        # Pass partial_basin_reach if SWATModelSetup prepared active_subs
        _pbr2 = None
        if getattr(self._setup, "_active_subs_file", None) is not None:
            _pbr2 = self._setup.reach_id

        calibrator = EnsembleDiagnosticCalibrator(
            model=self._setup.model,  # use working copy, not original
            observed_df=self._setup.observed_df,
            n_workers=n_workers,
            parameter_names=param_names,
            reach_id=self._setup.reach_id,
            output_variable=self._setup.output_variable,
            warmup_years=self._setup.warmup_years,
            max_iterations=max_iterations,
            kge_target=kge_target,
            pbias_target=pbias_target,
            upstream_subbasins=getattr(self._setup, "upstream_subbasins", None),
            qswat_shapes_dir=getattr(self._setup, "qswat_shapes_dir", None),
            progress_callback=diag_callback,
            custom_sim_period=getattr(self._setup, "_custom_sim_period", None),
            cancel_state=getattr(self._setup, "_cancel_state", None),
            constituent=constituent,
            partial_basin_reach=_pbr2,
            print_code=self._print_code,
        )
        # EnsembleDiagnosticCalibrator creates its own cancel file
        # internally and registers it on ``cancel_state``. The shared
        # cancel_file (if any) is still written by ``state.request_cancel``
        # because it was registered at runner startup.

        diag_result = calibrator.calibrate()

        if verbose:
            status = "CONVERGED" if diag_result.converged else "COMPLETED"
            print(f"\n{status}: {diag_result.convergence_reason}")
            print(f"Total SWAT runs: {diag_result.total_runs}")
            print(f"Runtime: {diag_result.runtime:.1f}s")
            best_kge = diag_result.best_metrics.get("kge", np.nan)
            best_pb = diag_result.best_metrics.get("pbias", np.nan)
            print(f"Best KGE: {best_kge:.3f}, PBIAS: {best_pb:.1f}%")

        result = diag_result.to_calibration_result()
        result.algorithm = "diagnostic_ensemble"
        return result

    def phased_calibrate(
        self,
        wq_observations: pd.DataFrame,
        phases: List = None,
        progress_callback: Optional[Callable] = None,
        cancel_state=None,
        cancel_file: Optional[str] = None,
        verbose: bool = True,
        **kwargs,
    ):
        """Run phased multi-constituent calibration (Flow -> Sed -> N -> P).

        Uses the existing streamflow observation data (from this Calibrator's
        constructor) for the flow phase, and the provided WQ observations for
        sediment, nitrogen, and phosphorus phases.

        Args:
            wq_observations: DataFrame from WQObservationLoader with date +
                concentration columns (TN_mg_L, TP_mg_L, TSS_mg_L, etc.).
            phases: Optional list of PhaseConfig objects. If None, default
                4-phase sequence is used with WQ phases auto-enabled based
                on available observation columns.
            progress_callback: Optional callback(dict) for UI progress.
            cancel_state: CalibrationState for cooperative cancellation.
            verbose: Print progress messages.
            **kwargs: Forwarded to PhasedCalibrator constructor.

        Returns:
            PhasedCalibrationResult with per-phase results and merged
            best parameter set.

        Example::

            calibrator = Calibrator(model, observed_data="streamflow.csv")
            wq_df = WQObservationLoader.load("wq_data.csv", format="adeq",
                                              station_id="ILL0001")
            result = calibrator.phased_calibrate(wq_df)
            result.print_summary()
        """
        from swat_modern.calibration.phased_calibrator import (
            PhasedCalibrator,
            PhasedCalibrationResult,
        )

        if verbose:
            print(f"\n{'='*60}")
            print("PHASED MULTI-CONSTITUENT CALIBRATION")
            print(f"{'='*60}")
            if phases:
                print(f"Custom phases: {len(phases)}")
            else:
                print("Phases: Flow -> Sediment -> Nitrogen -> Phosphorus")
                print("  (WQ phases auto-enabled based on observation data)")
            print(f"{'='*60}\n")

        # Use observed_df from the current SPOTPY setup as flow observations
        flow_obs = self._setup.observed_df.copy()

        # Build kwargs for PhasedCalibrator
        phased_kwargs = dict(kwargs)
        phased_kwargs.setdefault("warmup_years", self.warmup_years)
        for attr_name in ("upstream_subbasins", "qswat_shapes_dir",
                          "_custom_sim_period"):
            val = getattr(self._setup, attr_name, None)
            if val is not None:
                key = attr_name.lstrip("_")
                phased_kwargs.setdefault(key, val)
        if self._print_code is not None:
            phased_kwargs.setdefault("print_code", self._print_code)

        # Fall back to setup-attached cancel_file if not provided.
        if cancel_file is None:
            cancel_file = getattr(self._setup, "_cancel_file", None)

        calibrator = PhasedCalibrator(
            model=self.model,
            flow_observations=flow_obs,
            wq_observations=wq_observations,
            reach_id=self.reach_id,
            phases=phases,
            progress_callback=progress_callback,
            cancel_state=cancel_state,
            cancel_file=cancel_file,
            **phased_kwargs,
        )

        return calibrator.calibrate()

    def sensitivity_analysis(
        self,
        n_samples: int = 1000,
        method: str = "fast",
        parallel: bool = False,
        n_cores: int = None,
        verbose: bool = True,
    ) -> "SensitivityResult":
        """
        Run sensitivity analysis on calibration parameters.

        Identifies which parameters have the most influence on model output.

        Args:
            n_samples: Number of samples per parameter
            method: Sensitivity method - "fast" (recommended) or "sobol"
            parallel: If True, run SWAT simulations in parallel using
                multiple CPU cores.  Each worker gets its own copy of
                the SWAT project directory to avoid file conflicts.
                Requires the ``pathos`` package.
            n_cores: Number of CPU cores for parallel mode (default: all).
            verbose: Print progress messages

        Returns:
            DataFrame with sensitivity indices for each parameter

        Example:
            >>> sensitivity = calibrator.sensitivity_analysis(n_samples=500)
            >>> print(sensitivity.sort_values("S1", ascending=False))
        """
        try:
            import spotpy
        except ImportError:
            raise ImportError(
                "SPOTPY is required for sensitivity analysis.\n"
                "Install with: pip install spotpy"
            )

        method = method.lower()

        # Determine parallel mode string for SPOTPY.
        # FAST requires ordered results for Fourier spectral analysis, so
        # it MUST use "mpc" (ordered multiprocessing).  "umpc" (unordered)
        # scrambles result order and corrupts the FFT → empty Sp arrays.
        # LHS/Sobol are order-independent and can use the faster "umpc".
        parallel_mode = "seq"
        _original_cpu_count = None
        if parallel:
            try:
                import pathos  # noqa: F401
                if method == "fast":
                    parallel_mode = "mpc"  # ordered — required for FAST
                else:
                    parallel_mode = "umpc"  # unordered — safe for LHS/Sobol
                if n_cores and n_cores > 0:
                    import multiprocessing as _mp
                    _original_cpu_count = _mp.cpu_count
                    _mp.cpu_count = lambda: n_cores
                    # Also set SPOTPY's module-level process_count so
                    # pathos ProcessingPool uses the right size (pathos
                    # has its own cpu_count that ignores the monkey-patch).
                    try:
                        if method == "fast":
                            import spotpy.parallel.mproc as _mproc
                            _mproc.process_count = n_cores
                        else:
                            import spotpy.parallel.umproc as _umproc
                            _umproc.process_count = n_cores
                    except (ImportError, AttributeError):
                        pass
                if verbose:
                    import multiprocessing as _mp
                    print(f"Parallel mode: {parallel_mode} ({_mp.cpu_count()} workers)")
            except ImportError:
                if verbose:
                    print("Warning: pathos not installed, falling back to sequential")
                parallel_mode = "seq"

        if verbose:
            print(f"\n{'='*60}")
            print(f"SENSITIVITY ANALYSIS ({method.upper()})")
            print(f"{'='*60}")
            print(f"Parameters: {len(self.parameters)}")
            print(f"Samples: {n_samples:,}")
            print(f"Parallel: {parallel_mode}")
            print(f"{'='*60}\n")

        start_time = datetime.now()

        try:
            if method == "fast":
                # SPOTPY FAST divides repetitions by n_params internally:
                #   N_per_param = ceil(repetitions / n_params)
                # So to get n_samples per parameter, pass n_samples * n_params.
                #
                # FAST's Fourier decomposition requires the interference
                # parameter M >= 1.  With SPOTPY's default M=4:
                #   omega_0 = floor((N-1) / (2*M)) = floor((N-1)/8)
                #   m = floor(omega_0 / (2*M)) = floor(omega_0 / 8)
                # For m >= 1: omega_0 >= 8 → N >= 65 per parameter.
                # Below this, FAST produces a RuntimeWarning (divide by zero)
                # and unreliable sensitivity indices.
                _fast_min_per_param = 65
                if n_samples < _fast_min_per_param:
                    if verbose:
                        print(
                            f"Warning: FAST requires >= {_fast_min_per_param} "
                            f"samples/param for valid Fourier decomposition "
                            f"(got {n_samples}).  "
                            f"Automatically increasing to {_fast_min_per_param}."
                        )
                    n_samples = _fast_min_per_param

                _n_params = len(self.parameters)
                _total_reps = n_samples * _n_params
                if verbose:
                    print(
                        f"FAST: {n_samples} samples/param x {_n_params} params "
                        f"= {_total_reps} total evaluations"
                    )

                sampler = spotpy.algorithms.fast(
                    self._setup,
                    dbname="sensitivity",
                    dbformat="ram",
                    parallel=parallel_mode,
                )
                sampler.sample(_total_reps)

                # Get FAST results.
                # SPOTPY's get_sensitivity_of_fast returns
                # {'S1': [val, ...], 'ST': [val, ...]} where the lists
                # are ordered by parameter.  Convert to a dict
                # {param_name: S1_value} for consistent downstream use.
                results = sampler.getdata()
                si_raw = spotpy.analyser.get_sensitivity_of_fast(results)
                param_names = self.parameters
                si = {
                    name: float(si_raw["S1"][i])
                    for i, name in enumerate(param_names)
                }

            elif method == "sobol":
                import warnings
                warnings.warn(
                    "Sobol sensitivity uses an approximate variance-based method "
                    "(binned first-order indices). For rigorous sensitivity analysis, "
                    "use method='fast' instead.",
                    UserWarning,
                    stacklevel=2,
                )
                # Sobol requires more samples
                sampler = spotpy.algorithms.lhs(
                    self._setup,
                    dbname="sensitivity",
                    dbformat="ram",
                    parallel=parallel_mode,
                )
                sampler.sample(n_samples * len(self.parameters))

                # Get Sobol indices (simplified)
                results = sampler.getdata()
                param_columns = [
                    col for col in results.dtype.names
                    if col.startswith("par")
                ]

                # Calculate variance-based indices
                objectives = results["like1"]
                total_var = np.var(objectives)

                si = []
                for i, param_name in enumerate(self.parameters):
                    param_values = results[param_columns[i]]

                    # First-order index (simplified)
                    bins = np.linspace(param_values.min(), param_values.max(), 10)
                    bin_means = []
                    for j in range(len(bins) - 1):
                        mask = (param_values >= bins[j]) & (param_values < bins[j+1])
                        if np.sum(mask) > 0:
                            bin_means.append(np.mean(objectives[mask]))

                    if len(bin_means) > 0:
                        s1 = np.var(bin_means) / total_var if total_var > 0 else 0
                    else:
                        s1 = 0

                    si.append({
                        "Parameter": param_name,
                        "S1": s1,
                    })

                si = pd.DataFrame(si)

            else:
                raise ValueError(f"Unknown method: {method}. Use 'fast' or 'sobol'")

            # --- Extract best parameter set from SA results ---
            # Same pattern as auto_calibrate() — results["like1"] has
            # objective values and results["parN"] has parameter values.
            param_columns = [
                col for col in results.dtype.names if col.startswith("par")
            ]
            best_idx = np.argmax(results["like1"])
            best_params = {}
            for i, param_name in enumerate(self.parameters):
                best_params[param_name] = float(
                    results[param_columns[i]][best_idx]
                )
            best_objective = float(results["like1"][best_idx])

            end_time = datetime.now()
            runtime = (end_time - start_time).total_seconds()

            if verbose:
                print(f"\nSensitivity analysis completed in {runtime:.1f} seconds")
                print(f"Best objective value found: {best_objective:.4f}")
                print("\nParameter Sensitivity Ranking:")
                print("-" * 40)

                if isinstance(si, pd.DataFrame):
                    sorted_si = si.sort_values("S1", ascending=False)
                    for _, row in sorted_si.iterrows():
                        print(f"  {row['Parameter']:15s}: {row['S1']:.4f}")
                else:
                    # FAST returns dict
                    sorted_items = sorted(si.items(), key=lambda x: x[1], reverse=True)
                    for param, value in sorted_items:
                        print(f"  {param:15s}: {value:.4f}")

            return SensitivityResult(
                sensitivity=si,
                best_parameters=best_params,
                best_objective=best_objective,
                n_evaluations=len(results["like1"]),
                runtime=runtime,
                method=method,
            )

        except _CancelSignal:
            print("[cancel] _CancelSignal caught in sensitivity_analysis — propagating")
            raise Exception("Calibration cancelled by user")

        finally:
            self._setup.cleanup()
            if _original_cpu_count is not None:
                import multiprocessing as _mp
                _mp.cpu_count = _original_cpu_count

    def manual_run(
        self,
        parameters: Dict[str, float],
        verbose: bool = True,
    ) -> Dict[str, float]:
        """
        Run simulation with manually specified parameters.

        Useful for testing specific parameter sets.

        Args:
            parameters: Dictionary of {parameter_name: value}
            verbose: Print results

        Returns:
            Dictionary of performance metrics

        Example:
            >>> metrics = calibrator.manual_run({
            ...     "CN2": -0.1,
            ...     "ESCO": 0.85,
            ...     "GW_DELAY": 45.0
            ... })
        """
        # Validate parameters
        for name in parameters:
            if name.upper() not in [p.upper() for p in self.parameters]:
                raise ValueError(f"Unknown parameter: {name}")

        # Set parameters on the working copy (not the original model)
        self._setup.parameter_set.set_values(parameters)
        self._setup.parameter_set.apply_to_model(self._setup.model)

        # Run simulation on the working copy
        if verbose:
            print("Running simulation with specified parameters...")

        result = self._setup.model.run()

        if not result.success:
            raise RuntimeError(f"Simulation failed: {result.error_message}")

        # Get outputs
        simulated = self._setup._extract_simulated_values()
        observed = self._setup.evaluation()

        # Calculate metrics
        mask = ~(np.isnan(observed) | np.isnan(simulated))
        metrics = evaluate_model(observed[mask], simulated[mask])

        if verbose:
            print("\nPerformance Metrics:")
            print("-" * 30)
            for metric, value in metrics.items():
                print(f"  {metric.upper():10s}: {value:.4f}")

            if "nse" in metrics:
                rating = model_performance_rating(metrics["nse"])
                print(f"  Rating: {rating}")

        return metrics

    def multi_site_calibrate(
        self,
        sites: List[Dict],
        mode: str = "simultaneous",
        n_iterations: int = 5000,
        algorithm: str = "sceua",
        parallel: bool = False,
        use_partial_basin: bool = True,
        verbose: bool = True,
        progress_callback=None,
        progress_counter_dir: Optional[str] = None,
        cancel_state=None,
        cancel_file: Optional[str] = None,
    ) -> Union["CalibrationResult", "SequentialCalibrationResult"]:
        """
        Multi-site calibration with two modes.

        Args:
            sites: List of site configs, each containing:
                - reach_id (int): Reach/subbasin ID
                - observed (DataFrame/Series/path): Observation data
                - weight (float, optional): Site weight (default 1.0)
            mode: Calibration strategy:
                - "simultaneous": Single optimization against all sites
                  with weighted objective function
                - "sequential": Upstream-to-downstream step-by-step
                  calibration with parameter locking
            n_iterations: SPOTPY iterations (per step for sequential)
            algorithm: SPOTPY algorithm name, OR "diagnostic"/"diagnostic_ensemble".
                When "diagnostic" or "diagnostic_ensemble" is used with
                mode="simultaneous", calibration follows upstream-to-downstream
                order (identical to mode="diagnostic_sequential").
            use_partial_basin: For sequential mode, truncate fig.fig to
                only simulate relevant subbasins per step
            verbose: Print progress messages
            progress_callback: Optional callable(step, total, message)

        Returns:
            CalibrationResult for simultaneous mode,
            SequentialCalibrationResult for sequential mode

        Example:
            >>> results = calibrator.multi_site_calibrate(
            ...     sites=[
            ...         {"reach_id": 3, "observed": upstream_df},
            ...         {"reach_id": 7, "observed": outlet_df},
            ...     ],
            ...     mode="sequential",
            ...     n_iterations=5000,
            ... )
        """
        if not sites or len(sites) < 2:
            raise ValueError("multi_site_calibrate requires at least 2 sites")

        if mode == "simultaneous":
            return self._run_simultaneous(
                sites=sites,
                n_iterations=n_iterations,
                algorithm=algorithm,
                parallel=parallel,
                verbose=verbose,
                progress_callback=progress_callback,
                progress_counter_dir=progress_counter_dir,
                cancel_state=cancel_state,
                cancel_file=cancel_file,
            )
        elif mode == "sequential":
            return self._run_sequential(
                sites=sites,
                n_iterations=n_iterations,
                algorithm=algorithm,
                parallel=parallel,
                use_partial_basin=use_partial_basin,
                verbose=verbose,
                progress_callback=progress_callback,
                cancel_state=cancel_state,
                cancel_file=cancel_file,
            )
        elif mode == "diagnostic_sequential":
            return self._run_diagnostic_sequential(
                sites=sites,
                n_iterations=n_iterations,
                verbose=verbose,
                progress_callback=progress_callback,
                cancel_state=cancel_state,
                cancel_file=cancel_file,
            )
        else:
            raise ValueError(
                f"Unknown mode '{mode}'. "
                "Use 'simultaneous', 'sequential', or 'diagnostic_sequential'."
            )

    def _run_simultaneous(
        self,
        sites: List[Dict],
        n_iterations: int,
        algorithm: str,
        parallel: bool = False,
        verbose: bool = True,
        progress_callback: Optional[Callable] = None,
        progress_counter_dir: Optional[str] = None,
        cancel_state=None,
        cancel_file: Optional[str] = None,
    ) -> "CalibrationResult":
        """Run simultaneous multi-site calibration using MultiSiteSetup."""
        # Diagnostic algorithms use sequential upstream-to-downstream logic
        # regardless of mode — check FIRST, before creating any working-dir copy.
        if algorithm.lower() in ("diagnostic", "diagnostic_ensemble"):
            return self._run_diagnostic_sequential(
                sites=sites,
                n_iterations=n_iterations,
                verbose=verbose,
                progress_callback=progress_callback,
                cancel_state=cancel_state,
                cancel_file=cancel_file,
            )

        try:
            import spotpy
        except ImportError:
            raise ImportError("SPOTPY is required. Install with: pip install spotpy")

        # Create MultiSiteSetup
        ms_kwargs = dict(
            model=self.model,
            parameters=self.parameter_set,
            sites=sites,
            output_variable=self.output_variable,
            output_type=self.output_type,
            objective=self.objective,
            warmup_years=self.warmup_years,
            progress_callback=progress_callback,
        )
        if self._print_code is not None:
            ms_kwargs["print_code"] = self._print_code
        setup = MultiSiteSetup(**ms_kwargs)

        # Wire file-based progress tracking so parallel SPOTPY workers
        # (which lose the in-memory progress_callback during pickling)
        # can still report per-simulation progress to the caller.
        if progress_counter_dir is not None:
            setup._progress_counter_dir = progress_counter_dir

        # Wire cross-process cancellation so ``simulation()`` can short-
        # circuit and parallel SPOTPY workers detect cancel via the file
        # flag (threading.Event does not cross process boundaries).
        if cancel_state is not None:
            setup._cancel_state = cancel_state
            setup._cancel_event = getattr(cancel_state, "cancel_event", None)
        if cancel_file is not None:
            setup._cancel_file = cancel_file

        if verbose:
            print(f"\n{'=' * 60}")
            print("SIMULTANEOUS MULTI-SITE CALIBRATION")
            print(f"{'=' * 60}")
            print(f"Sites: {len(sites)}")
            for s in sites:
                print(f"  Reach {s['reach_id']} (weight={s.get('weight', 1.0)})")
            print(f"Algorithm: {algorithm.upper()}")
            print(f"Iterations: {n_iterations:,}")
            print(f"{'=' * 60}\n")

        # Run calibration
        algorithm_classes = {
            "sceua": spotpy.algorithms.sceua,
            "dream": spotpy.algorithms.dream,
            "mc": spotpy.algorithms.mc,
            "lhs": spotpy.algorithms.lhs,
        }

        AlgorithmClass = algorithm_classes.get(algorithm.lower())
        if AlgorithmClass is None:
            raise ValueError(f"Unknown algorithm: {algorithm}")

        start_time = datetime.now()

        try:
            sampler = AlgorithmClass(
                setup,
                dbname="multisite_calibration",
                dbformat="ram",
                parallel="seq" if not parallel else "mpc",
            )

            if algorithm.lower() in ["sceua", "rope"]:
                sampler.sample(n_iterations, ngs=len(self.parameters) + 1)
            elif algorithm.lower() == "dream":
                # DREAM requires nChains >= 2*delta+1 (min 7 with default delta=3)
                sampler.sample(n_iterations, nChains=7)
            else:
                sampler.sample(n_iterations)

            end_time = datetime.now()
            runtime = (end_time - start_time).total_seconds()

            # Extract results
            results = sampler.getdata()
            param_columns = [
                col for col in results.dtype.names if col.startswith("par")
            ]

            best_idx = np.argmax(results["like1"])
            best_params = {}
            for i, param_name in enumerate(self.parameters):
                best_params[param_name] = float(results[param_columns[i]][best_idx])

            best_objective = float(results["like1"][best_idx])

            all_params_df = pd.DataFrame({
                name: results[col]
                for name, col in zip(self.parameters, param_columns)
            })

            # Run best simulation to get per-site outputs.
            # Restore from backup first so "multiply" parameters are applied
            # to original file values, not values from the last trial.
            if setup._backup_dir is not None:
                setup.model.restore(setup._backup_dir)
                setup._apply_print_code()
                setup._apply_nyskip()
                setup._apply_sim_period()
            setup.parameter_set.set_values(best_params)
            setup.parameter_set.apply_to_model(setup.model)
            run_result = setup.model.run(capture_output=True)

            if not run_result.success:
                print(
                    f"Warning: Final best-parameter run failed: "
                    f"{getattr(run_result, 'error_message', 'unknown error')}"
                )

            # Collect per-site results
            per_site_results = []
            for i, (site_cfg, site_info, obs_df) in enumerate(
                zip(sites, setup.sites, setup._site_observed)
            ):
                sim_vals = setup._extract_site_values(
                    site_info["reach_id"], obs_df
                )
                obs_vals = obs_df["observed"].values
                date_vals = obs_df["date"].values

                # Compute per-site metrics
                site_metrics = {}
                mask = ~(np.isnan(obs_vals) | np.isnan(sim_vals))
                if np.sum(mask) > 10:
                    site_metrics = evaluate_model(obs_vals[mask], sim_vals[mask])

                per_site_results.append({
                    "reach_id": site_info["reach_id"],
                    "dates": date_vals,
                    "observed": obs_vals,
                    "simulated": sim_vals,
                    "metrics": site_metrics,
                })

            # Use first site for top-level observed/simulated
            observed = per_site_results[0]["observed"]
            simulated = per_site_results[0]["simulated"]

            result = CalibrationResult(
                best_parameters=best_params,
                best_objective=best_objective,
                all_parameters=all_params_df,
                all_objectives=results["like1"],
                observed=observed,
                simulated=simulated,
                runtime=runtime,
                n_iterations=n_iterations,
                algorithm=algorithm,
                dates=per_site_results[0]["dates"],
                objective_name=self.objective,
                site_results=per_site_results,
            )

            if verbose:
                result.print_summary()

            return result

        except _CancelSignal:
            print("[cancel] _CancelSignal caught in _run_simultaneous — propagating")
            raise Exception("Calibration cancelled by user")

        finally:
            setup.cleanup()

    def _run_sequential(
        self,
        sites: List[Dict],
        n_iterations: int,
        algorithm: str,
        parallel: bool = False,
        use_partial_basin: bool = True,
        verbose: bool = True,
        progress_callback=None,
        cancel_state=None,
        cancel_file: Optional[str] = None,
    ):
        """Run sequential upstream-to-downstream calibration."""
        from swat_modern.calibration.sequential import SequentialCalibrator

        seq = SequentialCalibrator(
            model=self.model,
            objective=self.objective,
            use_partial_basin=use_partial_basin,
        )

        for site in sites:
            seq.add_site(
                reach_id=site["reach_id"],
                observed=site["observed"],
                weight=site.get("weight", 1.0),
            )

        # Build parameter list from current calibrator's parameters
        params = self.parameters if hasattr(self, 'parameters') else None

        # Fall back to setup-attached values if not explicitly provided.
        if cancel_state is None:
            cancel_state = getattr(self._setup, "_cancel_state", None)
        if cancel_file is None:
            cancel_file = getattr(self._setup, "_cancel_file", None)

        seq_kwargs = dict(
            parameters=params,
            n_iterations=n_iterations,
            algorithm=algorithm,
            warmup_years=self.warmup_years,
            output_variable=self.output_variable,
            output_type=self.output_type,
            parallel=parallel,
            verbose=verbose,
            progress_callback=progress_callback,
            cancel_state=cancel_state,
            cancel_file=cancel_file,
        )
        if self._print_code is not None:
            seq_kwargs["print_code"] = self._print_code
        return seq.run(**seq_kwargs)

    def _run_diagnostic_sequential(
        self,
        sites: List[Dict],
        n_iterations: int = 15,
        verbose: bool = True,
        progress_callback=None,
        cancel_state=None,
        cancel_file: Optional[str] = None,
    ):
        """Run sequential upstream-to-downstream diagnostic calibration."""
        from swat_modern.calibration.sequential import (
            SequentialDiagnosticCalibrator,
        )

        # Pass use_partial_basin=True if SWATModelSetup prepared active_subs
        _use_pb = getattr(self._setup, "_active_subs_file", None) is not None
        seq = SequentialDiagnosticCalibrator(
            model=self.model,
            objective=self.objective,
            qswat_shapes_dir=getattr(self._setup, "qswat_shapes_dir", None),
            use_partial_basin=_use_pb,
        )

        for site in sites:
            seq.add_site(
                reach_id=site["reach_id"],
                observed=site["observed"],
                weight=site.get("weight", 1.0),
                upstream_subbasins=site.get("upstream_subbasins"),
            )

        params = self.parameters if hasattr(self, "parameters") else None

        # Fall back to setup-attached values if not explicitly provided.
        if cancel_state is None:
            cancel_state = getattr(self._setup, "_cancel_state", None)
        if cancel_file is None:
            cancel_file = getattr(self._setup, "_cancel_file", None)

        seq_run_kwargs = dict(
            parameter_names=params,
            max_iterations_per_step=n_iterations,
            warmup_years=self.warmup_years,
            output_variable=self.output_variable,
            verbose=verbose,
            progress_callback=progress_callback,
            cancel_state=cancel_state,
            cancel_file=cancel_file,
        )
        if self._print_code is not None:
            seq_run_kwargs["print_code"] = self._print_code
        return seq.run(**seq_run_kwargs)

    @staticmethod
    def available_algorithms() -> None:
        """Print available calibration algorithms."""
        print("\nAvailable Calibration Algorithms:")
        print("=" * 60)
        for name, desc in Calibrator.ALGORITHMS.items():
            print(f"  {name:10s}: {desc}")
        print("\nRecommended: 'sceua' for optimization, 'dream' for uncertainty")
