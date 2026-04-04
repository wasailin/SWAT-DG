"""
SPOTPY integration for SWAT model calibration.

This module provides the SWATModelSetup class that connects SWAT models
to SPOTPY calibration algorithms.

SPOTPY (Statistical Parameter Optimization Tool for Python) provides:
- Multiple optimization algorithms (SCE-UA, DREAM, MCMC, etc.)
- Sensitivity analysis (FAST, Sobol)
- Uncertainty quantification

Example:
    >>> from swat_modern import SWATModel
    >>> from swat_modern.calibration import SWATModelSetup
    >>>
    >>> model = SWATModel("path/to/project")
    >>> setup = SWATModelSetup(
    ...     model=model,
    ...     parameters=["CN2", "ESCO", "GW_DELAY"],
    ...     observed_data=observed_df,
    ...     output_variable="FLOW_OUT",
    ... )
    >>>
    >>> import spotpy
    >>> sampler = spotpy.algorithms.sceua(setup, dbname="calibration")
    >>> sampler.sample(10000)

References:
    SPOTPY documentation: https://spotpy.readthedocs.io/
"""

import shutil
from pathlib import Path
from typing import Dict, List, Optional, Union, Callable
import numpy as np
import pandas as pd
from datetime import datetime

from swat_modern.calibration.parameters import (
    CalibrationParameter,
    ParameterSet,
    CALIBRATION_PARAMETERS,
    get_streamflow_parameters,
)
from swat_modern.calibration.objectives import nse, kge, pbias, ObjectiveFunction


class _CancelSignal(BaseException):
    """Force-break SPOTPY's sampling loop on cancellation.

    Inherits from ``BaseException`` (not ``Exception``) so that no
    ``except Exception:`` handler — whether in our code or in third-party
    libraries — can accidentally swallow it.
    """


def _check_cancel_setup(setup) -> None:
    """Raise ``_CancelSignal`` if cancellation was requested.

    Checks both the in-memory ``_cancel_state.cancel_requested`` flag
    and the ``threading.Event`` directly, for maximum robustness.
    """
    _cs = getattr(setup, "_cancel_state", None)
    if _cs is not None and getattr(_cs, "cancel_requested", False):
        print("[cancel] _CancelSignal raised from simulation/objectivefunction")
        raise _CancelSignal("Calibration cancelled by user")
    _ce = getattr(setup, "_cancel_event", None)
    if _ce is not None and _ce.is_set():
        print("[cancel] _CancelSignal raised (via cancel_event)")
        raise _CancelSignal("Calibration cancelled by user")


def _add_date_column(output: pd.DataFrame, model) -> pd.DataFrame:
    """Build a ``date`` column on a SWAT output DataFrame.

    Handles three SWAT output formats:
    1. Daily with DAY + YEAR columns: MON=month, DAY=day-of-month, YEAR=year
    2. Daily without DAY/YEAR: MON=day-of-year (1–365), year derived from
       the simulation period.
    3. Monthly: MON=month (1–12), row with MON=13 is the annual summary
       and is dropped.

    The format is auto-detected from the MON value range.
    """
    output = output.copy()

    if "MON" not in output.columns:
        raise ValueError("Cannot determine output time step — no MON column")

    # Rev 692+ writes annual-summary rows with MON = year (e.g. 2017)
    # instead of MON = 13.  When a mix of small (1–366) and large (>366)
    # values exists the large ones are annual summaries and must be
    # dropped before auto-detecting the output format.  If ALL values
    # are large this is yearly output (IPRINT=2) and they are kept.
    _year_like = output["MON"] > 366
    if _year_like.any() and not _year_like.all():
        output = output[~_year_like].copy()

    mon_max = int(output["MON"].max())

    # --- Case 1: DAY + YEAR columns present → daily output, MON = month ---
    if "DAY" in output.columns and "YEAR" in output.columns:
        # Drop annual-summary rows (MON == 13 with DAY == 0 or similar)
        output = output[output["MON"] <= 12]
        output["date"] = pd.to_datetime(
            output[["YEAR", "MON", "DAY"]].rename(
                columns={"YEAR": "year", "MON": "month", "DAY": "day"}
            )
        )

    # --- Case 2: MON > 13 → daily output, MON = day-of-year (1–365/366) ---
    elif mon_max > 13:
        start_year = model.config.period.start_year
        nyskip = model.config.period.warmup_years

        # Derive year from the day-of-year wrapping pattern
        years = []
        current_year = start_year + nyskip
        prev_doy = 0
        for doy in output["MON"].values:
            if doy < prev_doy:
                current_year += 1
            years.append(current_year)
            prev_doy = doy

        output["date"] = pd.to_datetime(
            [f"{y}-01-01" for y in years]
        ) + pd.to_timedelta([int(d) - 1 for d in output["MON"].values], unit="D")

    # --- Case 3: MON ≤ 13 → monthly output, MON = month (1–12) ---
    else:
        # Drop annual-summary row (MON = 13)
        output = output[output["MON"] <= 12]

        if "YEAR" in output.columns:
            output["date"] = pd.to_datetime(
                output["YEAR"].astype(str) + "-" +
                output["MON"].astype(str) + "-01"
            )
        else:
            # Derive year from the month wrapping pattern
            start_year = model.config.period.start_year
            years = []
            current_year = start_year
            prev_mon = 0
            for mon in output["MON"].values:
                if mon < prev_mon:
                    current_year += 1
                years.append(current_year)
                prev_mon = mon
            output["date"] = pd.to_datetime(
                [f"{y}-{m}-01" for y, m in zip(years, output["MON"].values)]
            )

    return output


def run_baseline_simulation(
    model,
    observed_df: pd.DataFrame,
    output_variable: str = "FLOW_OUT",
    output_type: str = "rch",
    reach_id: int = 1,
    warmup_years: int = 0,
    upstream_subbasins: Optional[List[int]] = None,
    qswat_shapes_dir: Optional[Path] = None,
    cancel_event=None,
    cancel_file: Optional[str] = None,
    extra_variables: Optional[List[str]] = None,
    print_code: Optional[int] = None,
) -> dict:
    """Run a single SWAT simulation with current parameters and align with observed data.

    This is used to generate a pre-calibration baseline comparison.

    Args:
        model: SWATModel instance (already initialized).
        observed_df: DataFrame with 'date' and 'observed' columns.
        output_variable: SWAT output variable name (e.g. "FLOW_OUT").
        output_type: Output file type ("rch", "sub", "hru").
        reach_id: Reach/subbasin ID to extract.
        warmup_years: Years to skip at start of simulation.
        extra_variables: Optional list of additional SWAT output variables
            to extract from the same run (e.g. ``["FLOW_OUT"]`` when the
            primary variable is ``"SED_OUT"``).  Results are returned in
            ``result["extra_data"]`` keyed by variable name.
        print_code: IPRINT value to write to file.cio before running (0=daily,
            1=monthly, 2=annual). When provided, overrides the current file.cio
            setting so output timestep matches the observation data frequency.

    Returns:
        dict with keys: simulated (np.ndarray), dates (np.ndarray),
        metrics (dict with nse, kge, pbias, etc.), success (bool),
        error (str or None), extra_data (dict of variable -> np.ndarray).
    """
    from swat_modern.calibration.objectives import evaluate_model

    result = {"simulated": None, "dates": None, "metrics": {}, "success": False, "error": None, "extra_data": {}}

    try:
        # Apply IPRINT so output timestep matches observation frequency.
        if print_code is not None:
            try:
                model.config.output.print_code = print_code
                model.config.save()
                print(f"[baseline] Applied IPRINT={print_code} to file.cio")
            except Exception as _e:
                print(f"[baseline] Warning: could not set IPRINT={print_code}: {_e}")

        run_result = model.run(
            capture_output=True,
            cancel_event=cancel_event,
            cancel_file=cancel_file,
        )
        if not run_result.success:
            result["error"] = f"SWAT simulation failed: {getattr(run_result, 'error_message', 'unknown')}"
            return result

        # Detect local-only routing and use accumulated flow if needed
        _local_only = False
        _reach_acc_subs: Dict = {}
        _sub_to_rch: Dict = {}
        _original_sub = reach_id
        fig_path = model.project_dir / "fig.fig"
        if output_type == "rch" and fig_path.exists():
            from swat_modern.io.parsers.fig_parser import (
                FigFileParser, find_qswat_shapes_dir, get_gis_upstream_subbasins,
            )
            _fig = FigFileParser(fig_path)
            _fig.parse()
            _sub_to_rch = dict(_fig.subbasin_to_reach)
            if not _fig.has_accumulated_routing():
                _local_only = True
                _reach_acc_subs = dict(_fig._reach_accumulated_subs)

            # Translate subbasin ID → reach ID if they differ
            if reach_id in _sub_to_rch:
                _mapped = _sub_to_rch[reach_id]
                if _mapped != reach_id:
                    print(
                        f"[baseline] Auto-translated: subbasin {reach_id} "
                        f"-> reach {_mapped} for output extraction"
                    )
                    reach_id = _mapped

            # Override upstream subs: user-specified > fig.fig > GIS fallback.
            # Only applies for local-only routing — for accumulated routing,
            # FLOW_OUT already includes upstream flow (no summing needed).
            if _local_only:
                if upstream_subbasins is not None:
                    _reach_acc_subs[reach_id] = set(upstream_subbasins)
                    print(
                        f"[baseline] Using user-specified "
                        f"{len(upstream_subbasins)} upstream subbasins"
                    )
                elif _reach_acc_subs.get(reach_id):
                    print(
                        f"[baseline] Using fig.fig routing: "
                        f"{len(_reach_acc_subs[reach_id])} upstream subbasins"
                    )
                else:
                    # fig.fig had no upstream subs — try GIS fallback
                    _shapes = (
                        qswat_shapes_dir
                        or find_qswat_shapes_dir(model.project_dir)
                    )
                    if _shapes is not None:
                        try:
                            gis_up = get_gis_upstream_subbasins(
                                _shapes, _original_sub
                            )
                            if gis_up:
                                _reach_acc_subs[reach_id] = gis_up
                                print(
                                    f"[baseline] GIS fallback: "
                                    f"{len(gis_up)} subbasins upstream of "
                                    f"sub {_original_sub} (from rivs1.shp)"
                                )
                        except Exception as e:
                            print(
                                f"[baseline] WARNING: GIS topology failed "
                                f"({e}), no upstream override"
                            )

        if _local_only and _reach_acc_subs:
            upstream_reaches = {
                _sub_to_rch[s]
                for s in _reach_acc_subs.get(reach_id, set())
                if s in _sub_to_rch
            }
            if upstream_reaches:
                all_output = model.get_output(
                    variable=output_variable,
                    output_type=output_type,
                    unit_id=None,
                )
                id_col = "RCH"
                _meta_cols = {id_col, "GIS", "AREAkm2", "YEAR", "MON", "DAY"}
                vc = [c for c in all_output.columns if c not in _meta_cols]
                vc0 = vc[0] if vc else output_variable
                up_out = all_output[all_output[id_col].isin(upstream_reaches)].copy()
                up_out["_ts_idx"] = up_out.groupby(id_col).cumcount()
                summed = up_out.groupby("_ts_idx")[vc0].sum()
                one_rch = next(iter(upstream_reaches))
                output = (
                    all_output[all_output[id_col] == one_rch]
                    .copy()
                    .reset_index(drop=True)
                )
                output[vc0] = summed.values
                output[id_col] = reach_id
                print(
                    f"[baseline] Accumulated flow from "
                    f"{len(upstream_reaches)} upstream reaches: "
                    f"{sorted(upstream_reaches)}"
                )
            else:
                output = model.get_output(
                    variable=output_variable,
                    output_type=output_type,
                    unit_id=reach_id,
                )
        else:
            output = model.get_output(
                variable=output_variable,
                output_type=output_type,
                unit_id=reach_id,
            )

        output = _add_date_column(output, model)

        # Identify the variable column
        _meta = {"RCH", "SUB", "GIS", "YEAR", "MON", "DAY", "AREAkm2", "date"}
        var_cols = [c for c in output.columns if c not in _meta]
        var_col = var_cols[0] if var_cols else output_variable

        output["date"] = output["date"].dt.normalize()

        # Account for NYSKIP already in file.cio.  SWAT skipped
        # file_nyskip years of output already; only filter *additional*
        # years if the user requested more than what SWAT already skipped.
        file_nyskip = model.config.period.warmup_years
        extra_warmup = max(0, warmup_years - file_nyskip)
        if extra_warmup > 0:
            min_date = output["date"].min()
            warmup_end = min_date + pd.DateOffset(years=extra_warmup)
            output = output[output["date"] >= warmup_end]

        # Normalize observed dates
        obs = observed_df.copy()
        date_col = None
        for c in obs.columns:
            if c.lower() in ("date", "datetime"):
                date_col = c
                break
        if date_col is None:
            date_col = obs.columns[0]

        obs[date_col] = pd.to_datetime(obs[date_col]).dt.normalize()

        # Merge
        merged = pd.merge(
            obs[[date_col, "observed"]].rename(columns={date_col: "date"}),
            output[["date", var_col]],
            on="date",
            how="left",
        )

        simulated = merged[var_col].values
        observed_vals = merged["observed"].values
        dates = merged["date"].values

        # Year-month fallback if most values are NaN
        nan_rate = np.isnan(simulated.astype(float)).mean()
        if nan_rate > 0.5 and len(output) > 0:
            print(
                f"WARNING: High NaN rate ({nan_rate*100:.0f}%) in baseline date merge. "
                f"Sim dates: {output['date'].min()} to {output['date'].max()}, "
                f"Obs dates: {obs[date_col].min()} to {obs[date_col].max()}. "
                f"Attempting year-month fallback..."
            )
            obs_norm = obs[[date_col, "observed"]].rename(columns={date_col: "date"})
            obs_ym = obs_norm["date"].dt.to_period("M")
            out_ym = output["date"].dt.to_period("M")

            obs_tmp = obs_norm.copy()
            obs_tmp["_ym"] = obs_ym
            out_tmp = output[["date", var_col]].copy()
            out_tmp["_ym"] = out_ym
            out_tmp = out_tmp.drop_duplicates(subset="_ym", keep="first")

            merged_ym = pd.merge(
                obs_tmp[["_ym"]].reset_index(),
                out_tmp[["_ym", var_col]],
                on="_ym",
                how="left",
            ).sort_values("index").reset_index(drop=True)

            simulated_ym = merged_ym[var_col].values
            new_nan_rate = np.isnan(simulated_ym.astype(float)).mean()
            if new_nan_rate < nan_rate:
                print(
                    f"WARNING: Using year-month merge for baseline. "
                    f"NaN rate: {nan_rate*100:.1f}% -> {new_nan_rate*100:.1f}%"
                )
                simulated = simulated_ym

        result["simulated"] = np.asarray(simulated, dtype=float)
        result["dates"] = dates

        # Calculate metrics (only on dates where both sim and obs exist)
        sim_f = result["simulated"]
        obs_f = np.asarray(observed_vals, dtype=float)
        mask = ~(np.isnan(obs_f) | np.isnan(sim_f))
        n_valid = int(np.sum(mask))
        result["n_valid_pairs"] = n_valid
        result["n_total_obs"] = len(obs_f)
        if n_valid > 10:
            result["metrics"] = evaluate_model(obs_f[mask], sim_f[mask])
        else:
            print(
                f"WARNING: Only {n_valid} valid date pairs (need >10). "
                f"Statistics cannot be computed."
            )

        # Extract extra variables from the same SWAT run (e.g. FLOW_OUT
        # alongside a WQ primary variable for process diagnostics).
        if extra_variables and result["simulated"] is not None:
            extra_data = {}
            for ev in extra_variables:
                try:
                    ev_output = model.get_output(
                        variable=ev,
                        output_type=output_type,
                        unit_id=reach_id,
                    )
                    ev_output = _add_date_column(ev_output, model)
                    ev_meta = {"RCH", "SUB", "GIS", "YEAR", "MON", "DAY", "AREAkm2", "date"}
                    ev_cols = [c for c in ev_output.columns if c not in ev_meta]
                    ev_col = ev_cols[0] if ev_cols else ev
                    ev_output["date"] = ev_output["date"].dt.normalize()

                    # Apply same warmup filtering
                    if extra_warmup > 0:
                        ev_min_date = ev_output["date"].min()
                        ev_warmup_end = ev_min_date + pd.DateOffset(years=extra_warmup)
                        ev_output = ev_output[ev_output["date"] >= ev_warmup_end]

                    # Merge on observed dates to keep alignment
                    ev_merged = pd.merge(
                        merged[["date"]],
                        ev_output[["date", ev_col]],
                        on="date",
                        how="left",
                    )
                    extra_data[ev] = np.asarray(ev_merged[ev_col].values, dtype=float)
                except Exception:
                    pass  # silently skip if extraction fails
            result["extra_data"] = extra_data

        result["success"] = True

    except Exception as e:
        result["error"] = str(e)

    return result


class SWATModelSetup:
    """
    SPOTPY-compatible setup class for SWAT model calibration.

    This class implements the SPOTPY model interface:
    - parameters(): Returns parameter definitions
    - simulation(vector): Runs model with given parameters
    - evaluation(): Returns observed data
    - objectivefunction(simulation, evaluation): Computes fit metric

    Attributes:
        model: SWATModel instance
        parameter_set: ParameterSet with calibration parameters
        observed: Observed time series data
        output_variable: SWAT output variable to compare (e.g., "FLOW_OUT")
        objective_func: Objective function for optimization
    """

    def __init__(
        self,
        model,
        parameters: Union[List[str], List[CalibrationParameter], ParameterSet] = None,
        observed_data: Union[pd.DataFrame, pd.Series, str, Path] = None,
        output_variable: str = "FLOW_OUT",
        output_type: str = "rch",
        reach_id: int = 1,
        objective: str = "nse",
        date_column: str = "date",
        value_column: str = None,
        warmup_years: int = 0,
        parallel: bool = False,
        timeout: int = None,
        partial_basin_reach: Optional[int] = None,
        progress_callback: Optional[Callable] = None,
        print_code: Optional[int] = None,
        hydrology_only: bool = False,
        upstream_subbasins: Optional[List[int]] = None,
        qswat_shapes_dir: Optional[Path] = None,
        custom_sim_period: Optional[tuple] = None,
    ):
        """
        Initialize SWAT model setup for SPOTPY.

        Args:
            model: SWATModel instance (must be initialized with valid project)
            parameters: Parameters to calibrate - can be:
                - List of parameter names (uses defaults from CALIBRATION_PARAMETERS)
                - List of CalibrationParameter objects
                - ParameterSet object
                - None (uses default streamflow parameters)
            observed_data: Observed data for comparison - can be:
                - DataFrame with date and value columns
                - Series with DatetimeIndex
                - Path to CSV file
            output_variable: SWAT output variable name (default: "FLOW_OUT")
            output_type: Output file type - "rch", "sub", or "hru"
            reach_id: Reach/subbasin/HRU ID to extract (default: 1)
            objective: Objective function - "nse", "kge", "log_nse", etc.
            date_column: Column name for dates in observed data
            value_column: Column name for values in observed data
            warmup_years: Number of warmup years to exclude from comparison
            parallel: Enable parallel simulation (experimental)
            timeout: Simulation timeout in seconds
            partial_basin_reach: If specified, generate a truncated fig.fig
                that only simulates subbasins upstream of this reach.
                Skips downstream subbasins to save computation time.
            progress_callback: Optional callable(info_dict) called after each
                simulation. The dict contains: simulation_count, elapsed_seconds,
                avg_time_per_sim, best_score.
            print_code: SWAT output print code (0=monthly, 1=daily).
                If provided, file.cio in the working copy is updated before
                calibration so that the output timestep matches the observed
                data frequency.
            hydrology_only: If True, create calibmode.dat in the working copy
                to enable hydrology-only mode in a custom SWAT executable.
                Skips N/P, sediment, bacteria, and pesticide processes for
                faster streamflow calibration. Requires the custom
                swat_64calib.exe that reads calibmode.dat.
            custom_sim_period: Optional (start_year, end_year) tuple to override
                the simulation period (IYR, NBYR) in the working copy's file.cio.
                Must be within the available weather data range.
        """
        self.output_variable = output_variable
        self.output_type = output_type
        self.reach_id = reach_id
        self.warmup_years = warmup_years
        self.parallel = parallel
        self.timeout = timeout
        self._is_worker = False  # True for instances created by __setstate__

        # Create a working copy next to the original so it stays on the
        # same drive (avoids cross-drive I/O overhead during calibration).
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self._working_dir = model.project_dir.parent / f".swat_calib_{timestamp}"
        shutil.copytree(model.project_dir, self._working_dir)

        from swat_modern.core.model import SWATModel
        self.model = SWATModel(
            self._working_dir,
            executable=model.executable,
        )

        # Store print_code, nyskip, and simulation period so they can be
        # re-applied after every restore() (restore reloads config from
        # the backup).
        self._print_code = print_code
        self._nyskip = warmup_years
        self._custom_sim_period = custom_sim_period  # (start_year, end_year) or None

        # Set SWAT output timestep (IPRINT), warmup years (NYSKIP), and
        # simulation period (IYR/NBYR) on the working copy so the simulation
        # output matches the observation data frequency and warmup period.
        # Force-write on init (don't skip even if value appears correct,
        # because the keyword search might be reading the wrong line).
        self._apply_print_code(force=True)
        self._apply_nyskip(force=True)
        self._apply_sim_period(force=True)

        # Set up parameters
        self.parameter_set = self._setup_parameters(parameters)

        # Load observed data
        self.observed_df = self._load_observed_data(
            observed_data, date_column, value_column
        )

        # Set up objective function
        self.objective_func = ObjectiveFunction(objective)

        # Create backup for restoration between runs
        self._backup_dir = None
        # Compute which file types the selected parameters modify so
        # backup/restore only copies those files (huge speedup when
        # .hru files dominate the project size but no HRU params are
        # being calibrated).
        self._modified_file_types = self._get_modified_file_types()

        # Track simulation count and progress
        self._simulation_count = 0
        self._best_score = -np.inf
        self._start_time = None
        self.progress_callback = progress_callback
        # Per-process counter dir for cross-process progress tracking
        # (parallel SA).  When set, each worker writes its simulation
        # count to a PID-named file in this directory.
        self._progress_counter_dir: Optional[str] = None

        # Calibration mode: auto-detect from output_variable or use
        # hydrology_only flag for backward compatibility.
        # Must be applied BEFORE backup so restore preserves the setting.
        self._hydrology_only = hydrology_only
        self._calibmode = self._detect_calibmode(output_variable, hydrology_only)
        if self._calibmode > 0:
            self._prepare_calibmode(self._calibmode)

        # Routing pattern detection for accumulated flow extraction.
        # In models with local-only routing (e.g. UIRW), output.rch FLOW_OUT
        # contains only local subbasin flow.  When this flag is True, the
        # extraction methods sum FLOW_OUT from all upstream reaches to
        # approximate accumulated streamflow.
        self._local_only_routing = False
        self._reach_accumulated_subs: Dict[int, set] = {}
        self._sub_to_reach: Dict[int, int] = {}
        self._reach_id_translated = False  # prevent double translation

        # GIS-based upstream override
        self._user_upstream_subbasins: Optional[set] = (
            set(upstream_subbasins) if upstream_subbasins else None
        )
        self._qswat_shapes_dir = qswat_shapes_dir
        self._original_subbasin_id = reach_id  # before sub→reach translation

        # Partial-basin simulation: truncated fig.fig + active subbasin list
        self._truncated_fig: Optional[Path] = None
        self._active_subs_file: Optional[Path] = None
        if partial_basin_reach is not None:
            self._prepare_truncated_fig(partial_basin_reach)

        # Detect local-only routing if not already done by _prepare_truncated_fig
        if not self._local_only_routing:
            self._detect_routing_pattern()

        # Auto-translate subbasin ID to reach ID.
        # Users typically specify subbasin numbers, but output.rch is keyed by
        # reach number.  _prepare_truncated_fig() handles this when partial
        # basin is enabled; this covers the remaining case.
        if (
            not self._reach_id_translated
            and self._sub_to_reach
            and self.reach_id in self._sub_to_reach
        ):
            mapped = self._sub_to_reach[self.reach_id]
            if mapped != self.reach_id:
                print(
                    f"Auto-translated: subbasin {self.reach_id} -> "
                    f"reach {mapped} for output extraction"
                )
                self.reach_id = mapped
                self._reach_id_translated = True

    def _apply_print_code(self, force: bool = False) -> None:
        """Apply IPRINT to the working copy's file.cio (if print_code was set).

        Args:
            force: Always write, even if the parsed value already matches.
                   Use on first call (init) because the keyword search may
                   be reading the wrong line.
        """
        if self._print_code is not None:
            try:
                cur = self.model.config.output.print_code
                idx = getattr(self.model.config, "_iprint_line", "?")
                if force or cur != self._print_code:
                    self.model.config.output.print_code = self._print_code
                    self.model.config.save()
                    if force:
                        # Show the raw line for diagnostics
                        raw = ""
                        if isinstance(idx, int) and idx < len(
                            self.model.config._cio_lines
                        ):
                            raw = self.model.config._cio_lines[idx].rstrip()
                        print(
                            f"[iprint] Set IPRINT={self._print_code} at "
                            f"line {idx} (was {cur}). "
                            f"Raw: '{raw}'"
                        )
            except Exception as e:
                print(f"Warning: could not set IPRINT={self._print_code}: {e}")

    def _apply_nyskip(self, force: bool = False) -> None:
        """Apply NYSKIP (warmup years) to the working copy's file.cio.

        This ensures SWAT's own warmup skip matches the user's selection.
        Without this, the original project's NYSKIP persists in the working
        copy, and the Python-level warmup filter adds *extra* years on top,
        causing a double-warmup bug.

        After updating file.cio, ``self.warmup_years`` is set to 0 so
        ``_extract_simulated_values`` does NOT apply additional filtering
        (SWAT already excluded the warmup years from output).

        Args:
            force: Always write, even if the parsed value already matches.
        """
        try:
            cur = self.model.config.period.warmup_years
            idx = getattr(self.model.config, "_nyskip_line", "?")
            target = self._nyskip  # stored at init time, never mutated

            if force or cur != target:
                self.model.config.period.warmup_years = target
                self.model.config.save()
                if force:
                    raw = ""
                    if isinstance(idx, int) and idx < len(
                        self.model.config._cio_lines
                    ):
                        raw = self.model.config._cio_lines[idx].rstrip()
                    print(
                        f"[nyskip] Set NYSKIP={target} at "
                        f"line {idx} (was {cur}). "
                        f"Raw: '{raw}'"
                    )

            # SWAT now handles warmup at the Fortran level (NYSKIP).
            # Disable the Python-level warmup filter to prevent double-skip.
            self.warmup_years = 0

        except Exception as e:
            print(f"Warning: could not set NYSKIP={self._nyskip}: {e}")

    def _apply_sim_period(self, force: bool = False) -> None:
        """Apply custom simulation period (IYR, NBYR) to file.cio.

        Only acts when ``_custom_sim_period`` is set (a ``(start_year,
        end_year)`` tuple selected by the user in the Calibration UI).

        Args:
            force: Always write, even if the parsed value already matches.
        """
        if self._custom_sim_period is None:
            return

        try:
            new_start, new_end = self._custom_sim_period
            cur_start = self.model.config.period.start_year
            cur_end = self.model.config.period.end_year

            if force or cur_start != new_start or cur_end != new_end:
                self.model.config.period.start_year = new_start
                self.model.config.period.end_year = new_end
                self.model.config.save()
                if force:
                    print(
                        f"[sim-period] Set IYR={new_start}, "
                        f"NBYR={new_end - new_start + 1} "
                        f"(was {cur_start}--{cur_end})"
                    )
        except Exception as e:
            print(f"Warning: could not set simulation period: {e}")

    # Calibration mode constants
    CALIBMODE_FULL = 0
    CALIBMODE_STREAMFLOW = 1
    CALIBMODE_SEDIMENT = 2
    CALIBMODE_NUTRIENTS = 3

    # Output variables mapped to calibration modes
    _FLOW_VARS = {"FLOW_OUT", "FLOW_IN"}
    _SED_VARS = {"SED_OUT", "SED_IN", "SED_CONC", "SEDCONC"}
    _NUTRIENT_VARS = {
        "NO3_OUT", "NO3_IN", "ORGN_OUT", "ORGN_IN",
        "ORGP_OUT", "ORGP_IN", "SOLP_OUT", "SOLP_IN",
        "MINP_OUT", "MINP_IN", "NH4_OUT", "NH4_IN",
        "NO2_OUT", "NO2_IN", "TOT_N", "TOT_P",
        "CHLA_OUT", "CBOD_OUT", "DISOX_OUT",
    }
    _CALIBMODE_NAMES = {
        0: "FULL SIMULATION",
        1: "STREAMFLOW ONLY",
        2: "SEDIMENT",
        3: "NUTRIENTS (N+P)",
    }

    @staticmethod
    def _detect_calibmode(output_variable: str, hydrology_only: bool) -> int:
        """Auto-detect calibration mode from the objective variable.

        The custom SWAT calibration exe (swat_681_calib_ifx.exe /
        swat_692_calib_ifx.exe) reads ``calibmode.dat`` and skips
        pesticide/bacteria processes (modes 1-3) and sediment routing
        (mode 1) for faster execution.

        Args:
            output_variable: SWAT output variable name (e.g. "FLOW_OUT").
            hydrology_only: Legacy flag — forces mode 1 if True.

        Returns:
            Integer calibration mode (0-3).
        """
        if hydrology_only:
            return 1

        var = output_variable.upper().replace("CMS", "").replace(
            "TONS", ""
        ).replace("KG", "").replace("MG/L", "").replace("MG_L", "").strip()

        if var in SWATModelSetup._NUTRIENT_VARS:
            return 3
        if var in SWATModelSetup._SED_VARS:
            return 2
        if var in SWATModelSetup._FLOW_VARS:
            return 1
        # Unknown variable — run full simulation for safety
        return 0

    def _prepare_calibmode(self, mode: int) -> None:
        """Write calibmode.dat for the custom SWAT calibration executable.

        The calibration exe reads this file at startup and skips
        unnecessary processes:
          - Mode 1 (streamflow): skip pesticides, bacteria, sediment routing
          - Mode 2 (sediment):   skip pesticides, bacteria
          - Mode 3 (nutrients):  skip pesticides, bacteria

        All modes keep hydrology, plant growth, N/P mineralization, and
        nutrient transport running to maintain correct water balance.

        Args:
            mode: Calibration mode (0=full, 1=streamflow, 2=sediment,
                  3=nutrients).
        """
        calibmode_path = self.model.project_dir / "calibmode.dat"
        mode_name = self._CALIBMODE_NAMES.get(mode, "UNKNOWN")
        calibmode_path.write_text(f"{mode}\n")

        print(f"Calibration mode: {mode} ({mode_name})")

    def _prepare_hydrology_only(self) -> None:
        """Legacy method — delegates to _prepare_calibmode(1)."""
        self._prepare_calibmode(self.CALIBMODE_STREAMFLOW)

    def _prepare_truncated_fig(self, terminal_reach: int) -> None:
        """Generate truncated fig.fig and active_subs.dat for partial-basin simulation.

        Creates two files:
        - fig_partial.fig: truncated fig.fig with downstream route/add removed
        - active_subs.dat: list of upstream subbasin numbers for the custom
          SWAT executable to skip downstream subbasin execution entirely

        **Subbasin/reach auto-detection**: In many SWAT models the subbasin
        numbers differ from the reach numbers (e.g. UIRW: subbasin 10 feeds
        reach 15, while reach 10 receives subbasin 22's water).  If the
        given ``terminal_reach`` is not a valid reach but IS a valid
        subbasin number, this method automatically translates it via
        ``subbasin_to_reach``.  If the number appears as both, a diagnostic
        message is printed showing the mapping.
        """
        from swat_modern.io.parsers.fig_parser import FigFileParser

        fig_path = self.model.project_dir / "fig.fig"
        if not fig_path.exists():
            print(f"Warning: fig.fig not found, skipping partial-basin optimization")
            return

        parser = FigFileParser(fig_path)
        topo = parser.parse()

        # --- Subbasin → reach auto-translation ---
        is_valid_reach = terminal_reach in topo["reaches"]
        is_valid_sub = terminal_reach in topo["subbasins"]
        sub_to_rch = topo["subbasin_to_reach"]

        if is_valid_sub and sub_to_rch.get(terminal_reach) != terminal_reach:
            mapped_reach = sub_to_rch[terminal_reach]
            upstream_via_sub = parser.get_upstream_subbasins(mapped_reach)

            if is_valid_reach:
                # Number exists as both reach and subbasin but they differ
                upstream_via_rch = parser.get_upstream_subbasins(terminal_reach)
                print(
                    f"NOTE: Subbasin {terminal_reach} feeds reach {mapped_reach} "
                    f"(upstream subs: {sorted(upstream_via_sub)}), "
                    f"but reach {terminal_reach} is a separate reach fed by "
                    f"subbasin(s) {sorted(upstream_via_rch)}. "
                    f"Using reach {mapped_reach} (via subbasin_to_reach mapping)."
                )
            else:
                print(
                    f"Auto-translated: subbasin {terminal_reach} -> "
                    f"reach {mapped_reach} (upstream subs: {sorted(upstream_via_sub)})"
                )

            terminal_reach = mapped_reach

            # Also update self.reach_id so output extraction uses the
            # correct RCH row from output.rch.
            self.reach_id = terminal_reach
            self._reach_id_translated = True
        elif not is_valid_reach and is_valid_sub:
            terminal_reach = sub_to_rch.get(terminal_reach, terminal_reach)
            self.reach_id = terminal_reach
            self._reach_id_translated = True

        outlet = topo["outlet_reach"]
        if outlet is not None and terminal_reach == outlet:
            # Target is already the outlet, no truncation needed
            return

        # Detect local-only routing and store topology for accumulated flow
        self._sub_to_reach = dict(parser.subbasin_to_reach)
        if not parser.has_accumulated_routing():
            self._local_only_routing = True
            self._reach_accumulated_subs = dict(parser._reach_accumulated_subs)

        # Resolve upstream subbasins via GIS/user override
        # (updates _reach_accumulated_subs for the target reach)
        self._apply_upstream_override()

        # Determine active subbasins for partial-basin files.
        # For accumulated-routing models, _reach_accumulated_subs
        # is empty (only populated for local-only routing).
        # Fall back to the parser's upstream detection.
        active_subs = self._reach_accumulated_subs.get(terminal_reach, None)
        if active_subs is None:
            active_subs = parser.get_upstream_subbasins(terminal_reach)

        # NOTE: We intentionally do NOT truncate fig.fig.  SWAT's getallo.f
        # dimensions channel arrays by counting route commands (mch), not by
        # the max reach number.  Removing downstream routes shrinks mch below
        # the highest reach number, causing array-bounds access violations
        # (e.g. ch_w(2,22) with mch=6).  The performance gain comes almost
        # entirely from active_subs.dat skipping subbasin execution; routing
        # zero hydrographs through downstream reaches is negligible overhead.
        self._truncated_fig = None

        # Write active_subs template for Fortran-side subbasin skipping.
        self._active_subs_file = self.model.project_dir / "active_subs_partial.dat"
        parser.write_active_subs(
            terminal_reach,
            self._active_subs_file,
            subbasin_list=sorted(active_subs) if active_subs else None,
        )

        total_subs = len(topo["subbasins"])
        n_active = len(active_subs) if active_subs else 0
        print(
            f"Partial-basin: {n_active}/{total_subs} upstream subbasins active "
            f"(downstream subbasin execution skipped via active_subs.dat)"
        )

    def _detect_routing_pattern(self) -> None:
        """Detect local-only routing from fig.fig and apply GIS topology.

        Called from __init__ when _prepare_truncated_fig() was not invoked
        (i.e. no partial-basin optimization).  Sets _local_only_routing,
        _reach_accumulated_subs, and _sub_to_reach.

        Upstream detection priority:
        1. User-specified ``upstream_subbasins`` (manual override)
        2. fig.fig ADD-chain tracing (default)
        3. GIS topology from ``rivs1.shp`` (fallback when fig.fig is empty)
        """
        fig_path = self.model.project_dir / "fig.fig"
        if not fig_path.exists():
            return

        from swat_modern.io.parsers.fig_parser import (
            FigFileParser, find_qswat_shapes_dir, get_gis_upstream_subbasins,
        )

        parser = FigFileParser(fig_path)
        parser.parse()

        self._sub_to_reach = dict(parser.subbasin_to_reach)

        if not parser.has_accumulated_routing():
            self._local_only_routing = True
            self._reach_accumulated_subs = dict(parser._reach_accumulated_subs)

        # Apply upstream override: user-specified > GIS > fig.fig
        self._apply_upstream_override()

    def _apply_upstream_override(self) -> None:
        """Override _reach_accumulated_subs for the target reach using GIS or user data.

        Only applies when routing is local-only (``_local_only_routing`` is
        True, set by ``_detect_routing_pattern``).  For accumulated routing
        models, FLOW_OUT already includes upstream flow — overriding here
        would cause double-counting.

        Priority: user-specified > fig.fig (already set) > GIS (rivs1.shp fallback).
        """
        if not self._local_only_routing:
            return

        from swat_modern.io.parsers.fig_parser import (
            find_qswat_shapes_dir, get_gis_upstream_subbasins,
        )

        # Determine which reach to override (use translated reach if available)
        target_reach = self.reach_id

        if self._user_upstream_subbasins is not None:
            self._reach_accumulated_subs[target_reach] = self._user_upstream_subbasins
            print(
                f"Using user-specified {len(self._user_upstream_subbasins)} "
                f"upstream subbasins for reach {target_reach}"
            )
            return

        # fig.fig is already loaded into _reach_accumulated_subs.
        # Only fall back to GIS if fig.fig gave an empty set.
        fig_subs = self._reach_accumulated_subs.get(target_reach, set())
        if fig_subs:
            print(
                f"Using fig.fig routing: {len(fig_subs)} upstream subbasins "
                f"for reach {target_reach}"
            )
            return

        # fig.fig had no upstream subs — try GIS fallback
        shapes_dir = (
            self._qswat_shapes_dir
            or find_qswat_shapes_dir(self.model.project_dir)
        )
        if shapes_dir is not None:
            try:
                gis_upstream = get_gis_upstream_subbasins(
                    shapes_dir, self._original_subbasin_id
                )
                if gis_upstream:
                    self._reach_accumulated_subs[target_reach] = gis_upstream
                    print(
                        f"GIS fallback: {len(gis_upstream)} subbasins upstream of "
                        f"sub {self._original_subbasin_id} (from rivs1.shp)"
                    )
                    return
            except Exception as e:
                print(
                    f"WARNING: GIS topology parsing failed ({e}), "
                    f"no upstream override available"
                )

        print(
            f"No upstream subbasins found for reach {target_reach} "
            f"(fig.fig empty, no GIS data)"
        )

    def _get_upstream_reach_ids(self, reach_id: int) -> set:
        """Get all reach IDs whose FLOW_OUT should be summed for accumulated flow.

        Translates upstream subbasins to their corresponding reach numbers
        via the subbasin_to_reach mapping.
        """
        upstream_subs = self._reach_accumulated_subs.get(reach_id, set())
        return {
            self._sub_to_reach[sub]
            for sub in upstream_subs
            if sub in self._sub_to_reach
        }

    def _get_accumulated_output(self, reach_id: int, variable: str = None) -> pd.DataFrame:
        """Get accumulated output by summing values from all upstream reaches.

        For models with local-only routing, each reach's output is just
        the local subbasin's routed value.  This method sums the specified
        variable from all upstream reaches to approximate accumulated output.

        The returned DataFrame has the same structure as a single-reach
        get_output() call, so it can be passed to _add_date_column()
        and merged with observed data without changes.

        Args:
            reach_id: Target reach ID.
            variable: SWAT output variable name.  If None, uses
                ``self.output_variable``.
        """
        variable = variable or self.output_variable
        upstream_reaches = self._get_upstream_reach_ids(reach_id)

        if not upstream_reaches:
            return self.model.get_output(
                variable=variable,
                output_type=self.output_type,
                unit_id=reach_id,
            )

        # Parse all reaches at once (output parser reads the full file
        # regardless of unit_id, so there's no extra I/O cost)
        all_output = self.model.get_output(
            variable=variable,
            output_type=self.output_type,
            unit_id=None,
        )

        id_col = "RCH" if self.output_type == "rch" else "SUB"

        # Identify variable column
        _meta = {id_col, "GIS", "AREAkm2", "YEAR", "MON", "DAY"}
        var_cols = [c for c in all_output.columns if c not in _meta]
        var_col = var_cols[0] if var_cols else variable

        # Filter to upstream reaches
        upstream_output = all_output[
            all_output[id_col].isin(upstream_reaches)
        ].copy()

        # Assign within-reach row index for time-step grouping.
        # All reaches share the same time steps in the same order
        # (rchday.f: do j = 1, subtot inside the time loop).
        upstream_output["_ts_idx"] = (
            upstream_output.groupby(id_col).cumcount()
        )

        # Sum the variable across reaches for each time step
        summed_var = upstream_output.groupby("_ts_idx")[var_col].sum()

        # Use one representative reach's rows as the template
        # (preserves MON, DAY, YEAR columns for _add_date_column)
        one_reach_id = next(iter(upstream_reaches))
        template = (
            all_output[all_output[id_col] == one_reach_id]
            .copy()
            .reset_index(drop=True)
        )
        template[var_col] = summed_var.values
        template[id_col] = reach_id  # label as target reach

        if self._simulation_count <= 1:
            print(
                f"[accumulated-flow] Summing {var_col} from "
                f"{len(upstream_reaches)} upstream reaches: "
                f"{sorted(upstream_reaches)}"
            )

        return template

    def _setup_parameters(
        self,
        parameters: Union[List[str], List[CalibrationParameter], ParameterSet, None]
    ) -> ParameterSet:
        """Set up parameter set from various input formats."""

        if parameters is None:
            # Use default streamflow parameters
            params = get_streamflow_parameters()
            return ParameterSet(params)

        if isinstance(parameters, ParameterSet):
            return parameters

        if isinstance(parameters, list):
            pset = ParameterSet()

            for p in parameters:
                if isinstance(p, str):
                    pset.add(p)
                elif isinstance(p, CalibrationParameter):
                    pset.add_parameter(p)
                else:
                    raise TypeError(f"Invalid parameter type: {type(p)}")

            return pset

        raise TypeError(f"Invalid parameters type: {type(parameters)}")

    def _get_modified_file_types(self) -> List[str]:
        """Determine which file types will be modified by the parameter set.

        Examines each parameter's ``file_type`` and accounts for
        basin-to-HRU mapping (e.g. ESCO in .bsn may be applied as
        ESCO_HRU in .hru when subbasin_ids are used).

        Returns:
            Sorted list of unique file extensions (without dot),
            e.g. ``["bsn", "gw", "mgt"]``.
        """
        types: set = set()
        for param in self.parameter_set._parameters.values():
            types.add(param.file_type)
            # If a BSN param has a per-HRU equivalent, the HRU files
            # may also be modified when subbasin-level application is used.
            if param.file_type == "bsn" and param.name in self.parameter_set.BSN_TO_HRU_MAP:
                types.add("hru")
        return sorted(types)

    def _load_observed_data(
        self,
        data: Union[pd.DataFrame, pd.Series, str, Path, None],
        date_column: str,
        value_column: str,
    ) -> pd.DataFrame:
        """Load and validate observed data."""

        if data is None:
            raise ValueError(
                "observed_data is required. Provide a DataFrame, Series, or CSV path."
            )

        # Load from file if string/path
        if isinstance(data, (str, Path)):
            data = pd.read_csv(data, parse_dates=[date_column])

        # Convert Series to DataFrame
        if isinstance(data, pd.Series):
            if not isinstance(data.index, pd.DatetimeIndex):
                raise ValueError("Series must have DatetimeIndex")
            data = data.reset_index()
            data.columns = ["date", "observed"]
            date_column = "date"
            value_column = "observed"

        # Validate DataFrame
        if not isinstance(data, pd.DataFrame):
            raise TypeError(f"Expected DataFrame, got {type(data)}")

        # Find value column if not specified
        if value_column is None:
            # Try common names (case-insensitive)
            col_lower_map = {c.lower(): c for c in data.columns}
            for name in ["observed", "value", "flow", "streamflow", "discharge", "q"]:
                if name in col_lower_map:
                    value_column = col_lower_map[name]
                    break
            if value_column is None:
                # Use first numeric column that's not the date and not
                # Year/Month/Day (leftovers from combine_ymd_columns)
                _skip = {date_column} | {
                    c for c in data.columns
                    if c.lower().strip() in ("year", "month", "day")
                }
                numeric_cols = [
                    c for c in data.select_dtypes(include=[np.number]).columns
                    if c not in _skip
                ]
                if len(numeric_cols) > 0:
                    value_column = numeric_cols[0]
                else:
                    raise ValueError(
                        "Could not find value column. "
                        "Specify value_column parameter."
                    )

        # Ensure date column is datetime
        if date_column not in data.columns:
            raise ValueError(f"Date column '{date_column}' not found in data")

        if not pd.api.types.is_datetime64_any_dtype(data[date_column]):
            data[date_column] = pd.to_datetime(data[date_column])

        print(
            f"[obs-data] columns={list(data.columns)}, "
            f"date_col='{date_column}', value_col='{value_column}', "
            f"shape={data.shape}"
        )

        # Create standardized DataFrame
        result = pd.DataFrame({
            "date": data[date_column],
            "observed": data[value_column].astype(float),
        })

        # Normalize dates to midnight so that merges with SWAT output
        # (which always has midnight timestamps) succeed reliably.
        result["date"] = result["date"].dt.normalize()

        # Sort by date
        result = result.sort_values("date").reset_index(drop=True)

        # Sanity check: warn if observed looks like an index (monotonically
        # increasing integers starting near 0)
        obs_vals = result["observed"].dropna()
        if len(obs_vals) > 100:
            diffs = obs_vals.diff().dropna()
            if (diffs >= 0).all() and obs_vals.iloc[0] < 5 and obs_vals.iloc[-1] > len(obs_vals) * 0.8:
                print(
                    f"WARNING: Observed data looks like an index sequence "
                    f"(min={obs_vals.min():.1f}, max={obs_vals.max():.1f}, "
                    f"monotonically increasing). "
                    f"Check that the correct value column was selected."
                )

        print(
            f"[obs-data] Loaded {len(result)} observations: "
            f"min={result['observed'].min():.2f}, "
            f"max={result['observed'].max():.2f}, "
            f"mean={result['observed'].mean():.2f}"
        )

        # Check for missing values
        n_missing = result["observed"].isna().sum()
        if n_missing > 0:
            print(f"Warning: {n_missing} missing values in observed data")

        return result

    def parameters(self):
        """
        Return SPOTPY parameter array.

        This is called by SPOTPY to get the parameter definitions.
        Returns a numpy structured array via spotpy.parameter.generate().
        """
        import spotpy

        return spotpy.parameter.generate(
            self.parameter_set.get_spotpy_parameters()
        )

    def simulation(self, vector: np.ndarray) -> np.ndarray:
        """
        Run SWAT simulation with given parameter values.

        This is called by SPOTPY with sampled parameter values.

        Args:
            vector: Array of parameter values (in same order as parameters())

        Returns:
            Array of simulated values aligned with observed data
        """
        self._simulation_count += 1

        # Check for external cancel request.
        # Two mechanisms:
        #   1. In-memory: _CancelSignal (BaseException) — breaks SPOTPY's
        #      loop immediately.  Cannot be caught by ``except Exception:``.
        #   2. File-based: _cancel_file on disk (parallel workers) — returns
        #      NaN so the worker finishes its SPOTPY loop gracefully.
        _check_cancel_setup(self)
        _cf = getattr(self, "_cancel_file", None)
        if _cf is not None:
            from pathlib import Path
            if Path(_cf).exists():
                return np.full(len(self.observed_df), np.nan)

        # Start timer on first simulation
        if self._start_time is None:
            import time
            self._start_time = time.time()

        # Create backup on first run — only back up file types that will
        # be modified by the selected parameters (e.g. skip 434 .hru files
        # when only calibrating .gw and .bsn parameters).
        if self._backup_dir is None:
            self._backup_dir = self.model.backup(
                file_types=self._modified_file_types,
            )
            # Write sentinel so subsequent deserializations (pathos re-
            # pickles the setup per task) can reuse this backup instead
            # of creating a new one from the already-modified state.
            sentinel = self.model.project_dir / ".backup_path"
            sentinel.write_text(str(self._backup_dir))

        # Restore from backup — only restore the same file types
        self.model.restore(
            self._backup_dir,
            file_types=self._modified_file_types,
        )

        # Apply parameter values, rounding to each parameter's precision
        param_names = self.parameter_set.names
        param_values = {}
        for name, val in zip(param_names, vector):
            p = self.parameter_set.get_parameter(name)
            param_values[name] = round(float(val), p.decimal_precision)
        self.parameter_set.set_values(param_values)
        self.parameter_set.apply_to_model(self.model)

        # Swap in truncated fig.fig for partial-basin simulation
        if self._truncated_fig is not None and self._truncated_fig.exists():
            shutil.copy2(
                self._truncated_fig,
                self.model.project_dir / "fig.fig",
            )
        # Copy active_subs.dat for Fortran-side subbasin skipping
        if hasattr(self, '_active_subs_file') and self._active_subs_file is not None:
            if self._active_subs_file.exists():
                shutil.copy2(
                    self._active_subs_file,
                    self.model.project_dir / "active_subs.dat",
                )

        # Run simulation — pass cancel_event / cancel_file so the SWAT
        # process can be terminated mid-execution when the user cancels.
        _cancel_ev = None
        _cs = getattr(self, "_cancel_state", None)
        if _cs is not None:
            _cancel_ev = getattr(_cs, "cancel_event", None)
        _cancel_f = getattr(self, "_cancel_file", None)

        try:
            result = self.model.run(
                timeout=self.timeout,
                capture_output=True,
                cancel_event=_cancel_ev,
                cancel_file=_cancel_f,
            )

            if not result.success:
                self._report_progress()
                # Re-check cancel: SWAT process may have been terminated
                # by cancel_event.  Raise _CancelSignal (BaseException)
                # to force-break SPOTPY's loop.
                _check_cancel_setup(self)
                return np.full(len(self.observed_df), np.nan)

        except Exception as e:
            # Re-check: if cancel was requested, raise _CancelSignal
            # instead of swallowing the exception.
            _check_cancel_setup(self)
            print(f"Simulation failed: {e}")
            self._report_progress()
            return np.full(len(self.observed_df), np.nan)

        # Extract simulated values
        try:
            simulated = self._extract_simulated_values()
            self._report_progress()
            return simulated
        except Exception as e:
            print(f"Failed to extract outputs: {e}")
            self._report_progress()
            return np.full(len(self.observed_df), np.nan)

    def _extract_simulated_values(self) -> np.ndarray:
        """
        Extract simulated values and align with observed data.

        Returns array of simulated values with same length as observed.
        """
        # Get SWAT output — use accumulated flow if local-only routing
        if self._local_only_routing and self._reach_accumulated_subs:
            output = self._get_accumulated_output(self.reach_id)
        else:
            output = self.model.get_output(
                variable=self.output_variable,
                output_type=self.output_type,
                unit_id=self.reach_id,
            )

        output = _add_date_column(output, self.model)

        # Identify the actual variable column (get_output may fuzzy-match
        # e.g. "FLOW_OUT" → "FLOW_OUTcms")
        _meta = {"RCH", "SUB", "GIS", "YEAR", "MON", "DAY", "AREAkm2", "date"}
        var_cols = [c for c in output.columns if c not in _meta]
        var_col = var_cols[0] if var_cols else self.output_variable

        # Normalize to midnight so merge keys match observed dates
        output["date"] = output["date"].dt.normalize()

        # Apply warmup filter
        if self.warmup_years > 0:
            min_date = output["date"].min()
            warmup_end = min_date + pd.DateOffset(years=self.warmup_years)
            output = output[output["date"] >= warmup_end]

        # Log SWAT output info on first simulation only
        if self._simulation_count <= 1:
            out_dates = output["date"].sort_values()
            if len(out_dates) > 2:
                _median_dt = out_dates.diff().dt.days.median()
                _ts_label = "daily" if _median_dt < 5 else "monthly" if _median_dt < 40 else "yearly"
            else:
                _median_dt = 0
                _ts_label = "unknown"
            print(
                f"[sim-output] {len(output)} rows, var='{var_col}', "
                f"timestep={_ts_label} (median {_median_dt:.0f} days), "
                f"dates: {out_dates.iloc[0]} to {out_dates.iloc[-1]}, "
                f"IPRINT={self.model.config.output.print_code}"
            )

        # Merge with observed data
        merged = pd.merge(
            self.observed_df,
            output[["date", var_col]],
            on="date",
            how="left",
        )

        # Return simulated values (NaN where no match)
        simulated = merged[var_col].values

        # If most values are NaN, try year-month merge (handles monthly
        # SWAT output aligned against daily observed data).
        nan_rate = np.isnan(simulated).mean()
        if nan_rate > 0.5 and len(output) > 0:
            if self._simulation_count <= 1:
                print(
                    f"WARNING: High NaN rate ({nan_rate*100:.0f}%) after date merge. "
                    f"Sim dates: {output['date'].min()} to {output['date'].max()}, "
                    f"Obs dates: {self.observed_df['date'].min()} to "
                    f"{self.observed_df['date'].max()}. "
                    f"Attempting year-month fallback..."
                )

            obs_ym = self.observed_df["date"].dt.to_period("M")
            out_ym = output["date"].dt.to_period("M")

            obs_tmp = self.observed_df.copy()
            obs_tmp["_ym"] = obs_ym
            out_tmp = output[["date", var_col]].copy()
            out_tmp["_ym"] = out_ym
            out_tmp = out_tmp.drop_duplicates(subset="_ym", keep="first")

            merged_ym = pd.merge(
                obs_tmp[["_ym"]].reset_index(),
                out_tmp[["_ym", var_col]],
                on="_ym",
                how="left",
            ).sort_values("index").reset_index(drop=True)

            simulated_ym = merged_ym[var_col].values
            new_nan_rate = np.isnan(simulated_ym).mean()
            if new_nan_rate < nan_rate:
                if self._simulation_count <= 1:
                    print(
                        f"WARNING: Using year-month merge (daily obs vs monthly output). "
                        f"NaN rate: {nan_rate*100:.1f}% -> {new_nan_rate*100:.1f}%"
                    )
                simulated = simulated_ym

        if np.all(np.isnan(simulated)):
            print(
                f"WARNING: date merge produced all NaN. "
                f"Output dates: {output['date'].min()} to {output['date'].max()} "
                f"({len(output)} rows), "
                f"Observed dates: {self.observed_df['date'].min()} to "
                f"{self.observed_df['date'].max()} ({len(self.observed_df)} rows)"
            )

        return simulated

    def evaluation(self) -> np.ndarray:
        """
        Return observed data array.

        This is called by SPOTPY to get the evaluation (observed) data.
        """
        return self.observed_df["observed"].values

    def objectivefunction(
        self,
        simulation: np.ndarray,
        evaluation: np.ndarray,
        params: dict = None,
    ) -> float:
        """
        Calculate objective function value.

        This is called by SPOTPY to evaluate simulation fitness.

        Args:
            simulation: Simulated values from simulation()
            evaluation: Observed values from evaluation()
            params: Parameter values (optional, not used)

        Returns:
            Objective function value (higher is better for SPOTPY)
        """
        # Backup cancel check — even if simulation() returned normally,
        # catch cancel here before SPOTPY records and iterates.
        _check_cancel_setup(self)

        # Handle NaN values
        mask = ~(np.isnan(simulation) | np.isnan(evaluation))

        if np.sum(mask) < 10:
            # Too few valid points
            return -1e10

        sim_valid = simulation[mask]
        eval_valid = evaluation[mask]

        try:
            score = self.objective_func.score(eval_valid, sim_valid)
            if score > self._best_score:
                self._best_score = score
            return score
        except Exception as e:
            print(f"Objective function error: {e}")
            return -1e10

    def _report_progress(self) -> None:
        """Call progress_callback with current status if set."""
        # Write per-PID counter file for cross-process progress tracking.
        # This survives serialization to worker processes because the dir
        # path is a plain string pointing to the same filesystem location.
        if self._progress_counter_dir:
            try:
                import os
                _cnt_file = Path(self._progress_counter_dir) / f"{os.getpid()}.count"
                _cnt_file.write_text(str(self._simulation_count))
            except Exception:
                pass  # Never let progress tracking break simulation

        if self.progress_callback is None:
            return
        import time
        elapsed = time.time() - self._start_time
        avg_time = elapsed / self._simulation_count if self._simulation_count else 0
        try:
            self.progress_callback({
                "simulation_count": self._simulation_count,
                "elapsed_seconds": elapsed,
                "avg_time_per_sim": avg_time,
                "best_score": self._best_score,
            })
        except _CancelSignal:
            raise  # Never swallow _CancelSignal
        except Exception:
            # If cancel was requested, the callback raised
            # CalibrationCancelled — escalate to _CancelSignal
            # (BaseException) to force-break SPOTPY's loop.
            _check_cancel_setup(self)
            pass  # Swallow other callback errors

    def get_simulation_count(self) -> int:
        """Get number of simulations run."""
        return self._simulation_count

    def cleanup(self) -> None:
        """Clean up temporary files (working copy, backup, and worker dirs)."""
        if self._backup_dir and Path(self._backup_dir).exists():
            shutil.rmtree(self._backup_dir, ignore_errors=True)
            self._backup_dir = None
        if hasattr(self, "_working_dir") and self._working_dir.exists():
            # Also clean up per-process worker directories (pattern: <dir>_w<pid>)
            parent = self._working_dir.parent
            stem = self._working_dir.name
            for worker_dir in parent.glob(f"{stem}_w*"):
                shutil.rmtree(worker_dir, ignore_errors=True)
            shutil.rmtree(self._working_dir, ignore_errors=True)

    def __del__(self) -> None:
        """Safety net: remove working copy if cleanup() was never called.

        Worker instances (created by __setstate__ for parallel execution)
        must NOT delete their working directory — pathos/SPOTPY re-
        deserializes the setup object for every task, so old instances
        get garbage-collected while the worker directory is still needed
        by the next deserialized instance.  Only the primary instance
        (created by __init__) should clean up.
        """
        if getattr(self, "_is_worker", False):
            return
        try:
            self.cleanup()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Pickle support for SPOTPY parallel mode (pathos multiprocessing)
    # ------------------------------------------------------------------
    # When SPOTPY runs with parallel="mpc", it pickles the setup object
    # and sends it to worker processes.  Each worker must have its own
    # isolated working directory to avoid file-locking conflicts on
    # Windows (PermissionError: WinError 32).

    def __getstate__(self):
        """Prepare state for pickling — store info for per-process dir."""
        state = self.__dict__.copy()
        # Store paths needed to recreate model in the worker process
        state["_pickle_source_dir"] = str(self._working_dir)
        state["_pickle_executable"] = (
            str(self.model.executable) if self.model.executable else None
        )
        # Remove objects that shouldn't / can't cross process boundaries
        del state["model"]
        state["_backup_dir"] = None
        # Progress callbacks reference main-process CalibrationState;
        # they won't work across process boundaries.
        state["progress_callback"] = None
        return state

    def __setstate__(self, state):
        """Restore state in worker process with an isolated working dir.

        IMPORTANT: pathos/SPOTPY re-deserializes the setup for every
        simulation task.  This means __setstate__ is called many times
        in the same worker process.  We must:
        1. Only copytree on the first call (worker_dir doesn't exist yet).
        2. Only create the backup once (reuse across tasks so that
           "multiply"-method parameters don't compound).
        3. Mark ourselves as a worker so __del__ does NOT delete the
           shared worker directory.
        """
        import os

        source_dir = Path(state.pop("_pickle_source_dir"))
        exe_path = state.pop("_pickle_executable")

        self.__dict__.update(state)

        # Mark as worker instance so __del__ skips cleanup
        self._is_worker = True

        # Create a per-process working directory so workers don't collide
        pid = os.getpid()
        worker_dir = source_dir.parent / f"{source_dir.name}_w{pid}"

        first_init = not worker_dir.exists()
        if first_init:
            shutil.copytree(source_dir, worker_dir)

        self._working_dir = worker_dir

        # Reuse existing backup from a previous task on this worker so
        # that "multiply"-method parameters restore from the original
        # clean state rather than from an already-modified snapshot.
        # The sentinel file is written after the first backup is created.
        backup_sentinel = worker_dir / ".backup_path"
        if backup_sentinel.exists():
            self._backup_dir = Path(backup_sentinel.read_text().strip())
        else:
            self._backup_dir = None

        # Recreate the SWATModel pointing at the worker directory
        from swat_modern.core.model import SWATModel
        self.model = SWATModel(worker_dir, executable=exe_path)

        # Remap paths that pointed inside the original working dir
        if self._truncated_fig is not None:
            try:
                rel = Path(self._truncated_fig).relative_to(source_dir)
                self._truncated_fig = worker_dir / rel
            except ValueError:
                pass  # path was outside working dir, keep as-is

        if hasattr(self, '_active_subs_file') and self._active_subs_file is not None:
            try:
                rel = Path(self._active_subs_file).relative_to(source_dir)
                self._active_subs_file = worker_dir / rel
            except ValueError:
                pass

        if hasattr(self, 'fig_path_override') and self.fig_path_override is not None:
            try:
                rel = Path(self.fig_path_override).relative_to(source_dir)
                self.fig_path_override = worker_dir / rel
            except ValueError:
                pass

        # Re-apply settings on the worker copy (only on first init).
        # All three must be re-applied because copytree may have copied
        # files from a state where restore() had reverted them.
        if first_init:
            self._apply_print_code(force=True)
            self._apply_nyskip(force=True)
            self._apply_sim_period(force=True)


class MultiSiteSetup(SWATModelSetup):
    """
    SPOTPY setup for multi-site calibration.

    Extends SWATModelSetup to support multiple observation sites
    with weighted objective function.

    Example:
        >>> setup = MultiSiteSetup(
        ...     model=model,
        ...     parameters=["CN2", "ESCO"],
        ...     sites=[
        ...         {"reach_id": 1, "observed": site1_data, "weight": 1.0},
        ...         {"reach_id": 5, "observed": site2_data, "weight": 0.5},
        ...     ]
        ... )
    """

    def __init__(
        self,
        model,
        parameters: Union[List[str], List[CalibrationParameter], ParameterSet] = None,
        sites: List[Dict] = None,
        output_variable: str = "FLOW_OUT",
        output_type: str = "rch",
        objective: str = "nse",
        **kwargs,
    ):
        """
        Initialize multi-site setup.

        Args:
            model: SWATModel instance
            parameters: Calibration parameters
            sites: List of site configurations, each containing:
                - reach_id: Reach/subbasin ID
                - observed: Observed data (DataFrame, Series, or path)
                - weight: Weight for this site (default: 1.0)
                - date_column: Date column name (optional)
                - value_column: Value column name (optional)
            output_variable: SWAT output variable
            output_type: Output file type
            objective: Objective function
            **kwargs: Additional arguments passed to base class
        """
        if not sites or len(sites) == 0:
            raise ValueError("At least one site must be specified")

        # Store site configurations
        self.sites = []
        total_weight = 0

        for site_config in sites:
            reach_id = site_config.get("reach_id", 1)
            observed = site_config.get("observed")
            weight = site_config.get("weight", 1.0)
            date_column = site_config.get("date_column", "date")
            value_column = site_config.get("value_column")

            if observed is None:
                raise ValueError(f"Missing observed data for reach {reach_id}")

            self.sites.append({
                "reach_id": reach_id,
                "weight": weight,
                "date_column": date_column,
                "value_column": value_column,
            })
            total_weight += weight

        # Normalize weights
        for site in self.sites:
            site["weight"] /= total_weight

        # Initialize base class with first site
        first_site = sites[0]
        super().__init__(
            model=model,
            parameters=parameters,
            observed_data=first_site.get("observed"),
            output_variable=output_variable,
            output_type=output_type,
            reach_id=first_site.get("reach_id", 1),
            objective=objective,
            date_column=first_site.get("date_column", "date"),
            value_column=first_site.get("value_column"),
            **kwargs,
        )

        # Load observed data for all sites
        self._site_observed = []
        for i, (site, site_config) in enumerate(zip(self.sites, sites)):
            if i == 0:
                self._site_observed.append(self.observed_df)
            else:
                obs_df = self._load_observed_data(
                    site_config.get("observed"),
                    site.get("date_column", "date"),
                    site.get("value_column"),
                )
                self._site_observed.append(obs_df)

    def simulation(self, vector: np.ndarray) -> List[np.ndarray]:
        """
        Run simulation and return results for all sites.

        Returns list of arrays, one per site.
        """
        self._simulation_count += 1

        # Cancel check — _CancelSignal (BaseException) for in-memory;
        # file-based returns NaN for parallel workers.
        _check_cancel_setup(self)
        _cf = getattr(self, "_cancel_file", None)
        if _cf is not None:
            from pathlib import Path
            if Path(_cf).exists():
                return [np.full(len(obs), np.nan) for obs in self._site_observed]

        # Start timer on first simulation
        if self._start_time is None:
            import time
            self._start_time = time.time()

        # Selective backup/restore — only file types modified by parameters
        if self._backup_dir is None:
            self._backup_dir = self.model.backup(
                file_types=self._modified_file_types,
            )
        self.model.restore(
            self._backup_dir,
            file_types=self._modified_file_types,
        )

        # Apply parameters, rounding to each parameter's precision
        param_names = self.parameter_set.names
        param_values = {}
        for name, val in zip(param_names, vector):
            p = self.parameter_set.get_parameter(name)
            param_values[name] = round(float(val), p.decimal_precision)
        self.parameter_set.set_values(param_values)
        self.parameter_set.apply_to_model(self.model)

        # Copy active_subs.dat for Fortran-side subbasin skipping
        if hasattr(self, '_active_subs_file') and self._active_subs_file is not None:
            if self._active_subs_file.exists():
                shutil.copy2(
                    self._active_subs_file,
                    self.model.project_dir / "active_subs.dat",
                )

        # Run simulation — pass cancel_event / cancel_file for mid-run termination
        _cancel_ev = None
        _cs = getattr(self, "_cancel_state", None)
        if _cs is not None:
            _cancel_ev = getattr(_cs, "cancel_event", None)
        _cancel_f = getattr(self, "_cancel_file", None)

        try:
            result = self.model.run(
                timeout=self.timeout,
                capture_output=True,
                cancel_event=_cancel_ev,
                cancel_file=_cancel_f,
            )

            if not result.success:
                self._report_progress()
                _check_cancel_setup(self)
                return [np.full(len(obs), np.nan) for obs in self._site_observed]

        except Exception as e:
            _check_cancel_setup(self)
            print(f"Simulation failed: {e}")
            self._report_progress()
            return [np.full(len(obs), np.nan) for obs in self._site_observed]

        # Extract values for each site
        simulated_all = []
        for site, obs_df in zip(self.sites, self._site_observed):
            try:
                sim = self._extract_site_values(site["reach_id"], obs_df)
                simulated_all.append(sim)
            except Exception as e:
                print(f"Failed to extract for reach {site['reach_id']}: {e}")
                simulated_all.append(np.full(len(obs_df), np.nan))

        self._report_progress()
        return simulated_all

    def _extract_site_values(
        self,
        reach_id: int,
        obs_df: pd.DataFrame,
    ) -> np.ndarray:
        """Extract simulated values for a specific site."""

        # Use accumulated flow if local-only routing
        if self._local_only_routing and self._reach_accumulated_subs:
            output = self._get_accumulated_output(reach_id)
        else:
            output = self.model.get_output(
                variable=self.output_variable,
                output_type=self.output_type,
                unit_id=reach_id,
            )

        output = _add_date_column(output, self.model)

        # Identify the actual variable column (may differ from
        # self.output_variable due to fuzzy matching in get_output)
        _meta = {"RCH", "SUB", "GIS", "YEAR", "MON", "DAY", "AREAkm2", "date"}
        var_cols = [c for c in output.columns if c not in _meta]
        var_col = var_cols[0] if var_cols else self.output_variable

        # Normalize to midnight so merge keys match observed dates
        output["date"] = output["date"].dt.normalize()

        # Merge with observed
        merged = pd.merge(
            obs_df,
            output[["date", var_col]],
            on="date",
            how="left",
        )

        simulated = merged[var_col].values

        # Year-month fallback for monthly SWAT output vs daily observed
        nan_rate = np.isnan(simulated).mean()
        if nan_rate > 0.5 and len(output) > 0:
            obs_ym = obs_df["date"].dt.to_period("M")
            out_ym = output["date"].dt.to_period("M")

            obs_tmp = obs_df.copy()
            obs_tmp["_ym"] = obs_ym
            out_tmp = output[["date", var_col]].copy()
            out_tmp["_ym"] = out_ym
            out_tmp = out_tmp.drop_duplicates(subset="_ym", keep="first")

            merged_ym = pd.merge(
                obs_tmp[["_ym"]].reset_index(),
                out_tmp[["_ym", var_col]],
                on="_ym",
                how="left",
            ).sort_values("index").reset_index(drop=True)

            simulated_ym = merged_ym[var_col].values
            new_nan_rate = np.isnan(simulated_ym).mean()
            if new_nan_rate < nan_rate:
                simulated = simulated_ym

        return simulated

    def evaluation(self) -> List[np.ndarray]:
        """Return observed data for all sites."""
        return [obs["observed"].values for obs in self._site_observed]

    def objectivefunction(
        self,
        simulation: List[np.ndarray],
        evaluation: List[np.ndarray],
        params: dict = None,
    ) -> float:
        """
        Calculate weighted multi-site objective function.

        Combines scores from all sites using configured weights.
        """
        _check_cancel_setup(self)
        total_score = 0.0

        for i, (sim, obs, site) in enumerate(
            zip(simulation, evaluation, self.sites)
        ):
            mask = ~(np.isnan(sim) | np.isnan(obs))

            if np.sum(mask) < 10:
                total_score += site["weight"] * (-1e10)
                continue

            sim_valid = sim[mask]
            obs_valid = obs[mask]

            try:
                score = self.objective_func.score(obs_valid, sim_valid)
                total_score += site["weight"] * score
            except Exception as e:
                print(f"Objective error for site {i}: {e}")
                total_score += site["weight"] * (-1e10)
                continue

        return total_score


class SubbasinGroupSetup(SWATModelSetup):
    """
    SPOTPY setup that applies parameters only to a subset of subbasins.

    Used in sequential upstream-to-downstream calibration. Parameters are
    applied only to the specified subbasin group, while other subbasins
    retain their previously calibrated values.

    Example:
        >>> setup = SubbasinGroupSetup(
        ...     model=model,
        ...     parameters=["CN2", "ESCO", "GW_DELAY"],
        ...     observed_data=gauge_data,
        ...     subbasin_ids=[1, 2, 3],
        ...     locked_parameters={4: {"CN2": -0.05, "ESCO": 0.85}},
        ...     reach_id=3,
        ... )
    """

    def __init__(
        self,
        model,
        parameters: Union[List[str], List[CalibrationParameter], ParameterSet] = None,
        observed_data: Union[pd.DataFrame, pd.Series, str, Path] = None,
        subbasin_ids: List[int] = None,
        locked_parameters: Optional[Dict[int, Dict[str, float]]] = None,
        fig_path_override: Optional[Path] = None,
        **kwargs,
    ):
        """
        Initialize subbasin-group SPOTPY setup.

        Args:
            model: SWATModel instance
            parameters: Parameters to calibrate for this group
            observed_data: Observed data at the target gauge
            subbasin_ids: Subbasin IDs in this calibration group
            locked_parameters: Previously calibrated parameters.
                Dict mapping subbasin_id -> {param_name: value}.
            fig_path_override: If provided, replace fig.fig before each run
                (for partial-basin simulation)
            **kwargs: Passed to SWATModelSetup (reach_id, objective, etc.)
        """
        super().__init__(
            model=model,
            parameters=parameters,
            observed_data=observed_data,
            **kwargs,
        )
        self.subbasin_ids = subbasin_ids or []
        self.locked_parameters = locked_parameters or {}
        self.fig_path_override = (
            Path(fig_path_override) if fig_path_override else None
        )

        # Extend _modified_file_types with file types touched by locked params
        locked_types: set = set(self._modified_file_types)
        for _lp_params in self.locked_parameters.values():
            for pname in _lp_params:
                pdef = CALIBRATION_PARAMETERS.get(pname.upper())
                if pdef:
                    locked_types.add(pdef.file_type)
                    if pdef.file_type == "bsn" and pname.upper() in ParameterSet.BSN_TO_HRU_MAP:
                        locked_types.add("hru")
        self._modified_file_types = sorted(locked_types)

    def simulation(self, vector: np.ndarray) -> np.ndarray:
        """
        Run simulation with parameters applied only to this subbasin group.

        Steps:
        1. Restore from backup (clean state)
        2. Apply locked parameters from previous calibration steps
        3. Apply trial parameters to THIS subbasin group only
        4. Optionally swap in truncated fig.fig
        5. Run SWAT and extract output
        """
        self._simulation_count += 1

        # Cancel check — _CancelSignal (BaseException) for in-memory;
        # file-based returns NaN for parallel workers.
        _check_cancel_setup(self)
        _cf = getattr(self, "_cancel_file", None)
        if _cf is not None:
            from pathlib import Path
            if Path(_cf).exists():
                return np.full(len(self.observed_df), np.nan)

        # Start timer on first simulation
        if self._start_time is None:
            import time
            self._start_time = time.time()

        # Selective backup/restore — only file types modified by parameters.
        # For SequentialStepSetup, locked params may touch additional file
        # types; _modified_file_types already accounts for these because the
        # parameter set is the union of trial + locked param types.
        if self._backup_dir is None:
            self._backup_dir = self.model.backup(
                file_types=self._modified_file_types,
            )
        self.model.restore(
            self._backup_dir,
            file_types=self._modified_file_types,
        )

        # 1. Apply locked parameters from previous calibration steps
        self._apply_locked_parameters()

        # 2. Apply trial parameters to THIS subbasin group only
        param_names = self.parameter_set.names
        param_values = {}
        for name, val in zip(param_names, vector):
            p = self.parameter_set.get_parameter(name)
            param_values[name] = round(float(val), p.decimal_precision)
        self.parameter_set.set_values(param_values)
        self.parameter_set.apply_to_model(
            self.model, subbasin_ids=self.subbasin_ids
        )

        # 3. Swap in truncated fig.fig for partial-basin simulation
        if self.fig_path_override and self.fig_path_override.exists():
            shutil.copy2(
                self.fig_path_override,
                self.model.project_dir / "fig.fig",
            )
        elif self._truncated_fig is not None and self._truncated_fig.exists():
            shutil.copy2(
                self._truncated_fig,
                self.model.project_dir / "fig.fig",
            )
        # Copy active_subs.dat for Fortran-side subbasin skipping
        if hasattr(self, '_active_subs_file') and self._active_subs_file is not None:
            if self._active_subs_file.exists():
                shutil.copy2(
                    self._active_subs_file,
                    self.model.project_dir / "active_subs.dat",
                )

        # 4. Run simulation — pass cancel_event / cancel_file for mid-run termination
        _cancel_ev = None
        _cs = getattr(self, "_cancel_state", None)
        if _cs is not None:
            _cancel_ev = getattr(_cs, "cancel_event", None)
        _cancel_f = getattr(self, "_cancel_file", None)

        try:
            result = self.model.run(
                timeout=self.timeout,
                capture_output=True,
                cancel_event=_cancel_ev,
                cancel_file=_cancel_f,
            )
            if not result.success:
                self._report_progress()
                _check_cancel_setup(self)
                return np.full(len(self.observed_df), np.nan)
        except Exception as e:
            _check_cancel_setup(self)
            print(f"Simulation failed: {e}")
            self._report_progress()
            return np.full(len(self.observed_df), np.nan)

        # 5. Extract simulated values
        try:
            simulated = self._extract_simulated_values()
            self._report_progress()
            return simulated
        except Exception as e:
            print(f"Failed to extract outputs: {e}")
            self._report_progress()
            return np.full(len(self.observed_df), np.nan)

    def _apply_locked_parameters(self) -> None:
        """Apply previously calibrated parameters for locked subbasins."""
        for sub_id, params in self.locked_parameters.items():
            for param_name, value in params.items():
                param_def = CALIBRATION_PARAMETERS.get(param_name.upper())
                if param_def is None:
                    continue

                # Use per-HRU equivalent for basin-wide params
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
                # Basin-wide params without HRU equivalent: skip per-subbasin
                # (they were calibrated globally in step 1)


class MultiConstituentSetup(SWATModelSetup):
    """SPOTPY setup for calibrating against multiple water quality constituents.

    Extends SWATModelSetup to support simultaneous calibration of sediment,
    nitrogen, and phosphorus loads. Observed concentrations are converted to
    loads using simulated streamflow, then compared against SWAT-simulated
    loads on matching dates.

    Example::

        setup = MultiConstituentSetup(
            model=model,
            parameters=["SPCON", "NPERCO", "PPERCO"],
            constituents=[
                {"name": "TN", "weight": 0.5},
                {"name": "TP", "weight": 0.5},
            ],
            wq_observations=wq_df,  # from WQObservationLoader
            flow_observations=flow_df,  # optional observed streamflow
            reach_id=14,
        )
    """

    def __init__(
        self,
        model,
        parameters=None,
        constituents=None,
        wq_observations=None,
        flow_observations=None,
        comparison_mode: str = "timeseries",
        objective: str = "nse",
        reach_id: int = 1,
        **kwargs,
    ):
        """Initialize multi-constituent calibration setup.

        Args:
            model: SWATModel instance.
            parameters: Calibration parameters (list of names, CalibrationParameter
                objects, or ParameterSet). If None, uses combined sediment + nutrient
                defaults.
            constituents: List of dicts, each with:
                - "name": constituent name (e.g., "TN", "TP", "TSS")
                - "weight": relative weight in objective function (default 1.0)
                e.g., [{"name": "TN", "weight": 0.5}, {"name": "TP", "weight": 0.5}]
            wq_observations: DataFrame from WQObservationLoader with date +
                concentration columns in mg/L.
            flow_observations: Optional DataFrame with date + flow (m3/s) for
                load calculation. If None, a baseline SWAT run provides flow.
            comparison_mode: "timeseries" (compare on individual dates) or
                "volume" (aggregate loads by month before comparing).
            objective: Objective function name ("nse", "kge", "pbias", etc.)
            reach_id: Reach/subbasin ID for output extraction.
            **kwargs: Passed to SWATModelSetup (warmup_years, parallel, etc.)
        """
        from swat_modern.calibration.load_calculator import (
            LoadCalculator,
            CONSTITUENT_TO_SWAT_VARIABLE,
        )

        if wq_observations is None:
            raise ValueError("wq_observations is required for multi-constituent calibration")
        if constituents is None:
            constituents = [{"name": "TN", "weight": 1.0}, {"name": "TP", "weight": 1.0}]

        # Parse constituent configs
        self._constituents = []
        total_weight = 0.0
        for c in constituents:
            if isinstance(c, str):
                c = {"name": c, "weight": 1.0}
            name = c["name"].upper()
            weight = c.get("weight", 1.0)
            self._constituents.append({"name": name, "weight": weight})
            total_weight += weight

        # Normalize weights
        if total_weight > 0:
            for c in self._constituents:
                c["weight"] /= total_weight

        self._comparison_mode = comparison_mode
        self._wq_obs_df = wq_observations.copy()
        self._flow_obs_df = flow_observations

        # Set up default parameters if none provided
        if parameters is None:
            from swat_modern.calibration.parameters import (
                get_sediment_parameters,
                get_nutrient_parameters,
            )
            parameters = get_sediment_parameters() + get_nutrient_parameters()

        # Create LoadCalculator
        constituent_names = [c["name"] for c in self._constituents]
        self._load_calc = LoadCalculator(
            wq_obs_df=wq_observations,
            constituents=constituent_names,
        )

        # We need a "dummy" observed_data for the parent class.
        # Use the first constituent's load dates with placeholder values.
        # The actual evaluation() is overridden below.
        obs_dates = self._load_calc.get_observation_dates()
        if len(obs_dates) == 0:
            raise ValueError("No valid WQ observation dates found for the specified constituents.")

        dummy_obs = pd.DataFrame({
            "date": obs_dates,
            "observed": np.zeros(len(obs_dates)),  # placeholder
        })

        # Initialize parent — uses FLOW_OUT as output_variable (needed for
        # accumulated flow extraction and load calculation)
        super().__init__(
            model=model,
            parameters=parameters,
            observed_data=dummy_obs,
            output_variable="FLOW_OUT",
            reach_id=reach_id,
            objective=objective,
            **kwargs,
        )

        # Store SWAT variable names for each constituent
        self._swat_variables = {}
        for c in self._constituents:
            name = c["name"]
            if name in CONSTITUENT_TO_SWAT_VARIABLE:
                self._swat_variables[name] = CONSTITUENT_TO_SWAT_VARIABLE[name]
            else:
                raise ValueError(f"No SWAT variable mapping for constituent '{name}'")

        # Compute observed loads (will be done after first simulation for
        # simulated-flow mode, or immediately if observed flow is provided)
        self._observed_loads_df = None
        self._observed_loads_computed = False

    def _compute_observed_loads(self, flow_df: pd.DataFrame) -> None:
        """Compute observed loads using the provided flow data."""
        if self._flow_obs_df is not None:
            self._observed_loads_df = self._load_calc.compute_loads_with_fallback(
                sim_flow_df=flow_df,
                obs_flow_df=self._flow_obs_df,
            )
        else:
            self._observed_loads_df = self._load_calc.compute_loads(flow_df)
        self._observed_loads_computed = True

        if self._simulation_count <= 1:
            print(f"[multi-const] Observed loads computed: {len(self._observed_loads_df)} dates")
            for c in self._constituents:
                load_cols = [col for col in self._observed_loads_df.columns
                            if col.startswith(c["name"])]
                for col in load_cols:
                    n_valid = self._observed_loads_df[col].notna().sum()
                    print(f"  {col}: {n_valid} valid values")

    def simulation(self, vector: np.ndarray) -> np.ndarray:
        """Run SWAT and extract simulated loads for all constituents.

        Returns a single concatenated array:
            [constituent1_values..., constituent2_values..., ...]
        Each constituent's values are aligned with observation dates.
        """
        self._simulation_count += 1
        _check_cancel_setup(self)

        # File-based cancel for parallel workers
        _cf = getattr(self, "_cancel_file", None)
        if _cf is not None:
            from pathlib import Path as _P
            if _P(_cf).exists():
                return self._nan_array()

        if self._start_time is None:
            import time
            self._start_time = time.time()

        # Backup/restore
        if self._backup_dir is None:
            self._backup_dir = self.model.backup(
                file_types=self._modified_file_types,
            )
            sentinel = self.model.project_dir / ".backup_path"
            sentinel.write_text(str(self._backup_dir))

        self.model.restore(
            self._backup_dir,
            file_types=self._modified_file_types,
        )

        # Apply parameters
        param_names = self.parameter_set.names
        param_values = {}
        for name, val in zip(param_names, vector):
            p = self.parameter_set.get_parameter(name)
            param_values[name] = round(float(val), p.decimal_precision)
        self.parameter_set.set_values(param_values)
        self.parameter_set.apply_to_model(self.model)

        # Copy active_subs.dat if partial-basin
        if hasattr(self, '_active_subs_file') and self._active_subs_file is not None:
            if self._active_subs_file.exists():
                import shutil
                shutil.copy2(
                    self._active_subs_file,
                    self.model.project_dir / "active_subs.dat",
                )

        # Run SWAT
        _cancel_ev = None
        _cs = getattr(self, "_cancel_state", None)
        if _cs is not None:
            _cancel_ev = getattr(_cs, "cancel_event", None)
        _cancel_f = getattr(self, "_cancel_file", None)

        try:
            result = self.model.run(
                timeout=self.timeout,
                capture_output=True,
                cancel_event=_cancel_ev,
                cancel_file=_cancel_f,
            )
            if not result.success:
                self._report_progress()
                _check_cancel_setup(self)
                return self._nan_array()
        except Exception as e:
            _check_cancel_setup(self)
            print(f"Simulation failed: {e}")
            self._report_progress()
            return self._nan_array()

        try:
            simulated = self._extract_multi_constituent_values()
            self._report_progress()
            return simulated
        except Exception as e:
            print(f"Failed to extract multi-constituent outputs: {e}")
            self._report_progress()
            return self._nan_array()

    def _extract_multi_constituent_values(self) -> np.ndarray:
        """Extract simulated loads for all constituents from SWAT output.

        Steps:
        1. Extract FLOW_OUT for observed load computation (first run only)
        2. For each constituent, extract the SWAT output variable
        3. Align with observation dates
        4. Concatenate into single array
        """
        # Step 1: Get simulated flow for load calculation (first run only)
        if not self._observed_loads_computed:
            if self._local_only_routing and self._reach_accumulated_subs:
                flow_output = self._get_accumulated_output(self.reach_id, variable="FLOW_OUT")
            else:
                flow_output = self.model.get_output(
                    variable="FLOW_OUT",
                    output_type=self.output_type,
                    unit_id=self.reach_id,
                )
            flow_output = _add_date_column(flow_output, self.model)
            flow_output["date"] = flow_output["date"].dt.normalize()

            # Build flow DataFrame for LoadCalculator
            _meta = {"RCH", "SUB", "GIS", "YEAR", "MON", "DAY", "AREAkm2", "date"}
            flow_cols = [c for c in flow_output.columns if c not in _meta]
            flow_col = flow_cols[0] if flow_cols else "FLOW_OUTcms"
            flow_for_loads = flow_output[["date", flow_col]].rename(
                columns={flow_col: "flow_cms"}
            )
            self._compute_observed_loads(flow_for_loads)

        # Step 2-3: Extract each constituent's simulated output
        all_sim_values = []

        for const_config in self._constituents:
            const_name = const_config["name"]
            swat_var = self._swat_variables[const_name]

            # Extract SWAT output for this variable
            if self._local_only_routing and self._reach_accumulated_subs:
                output = self._get_accumulated_output(self.reach_id, variable=swat_var)
            else:
                output = self.model.get_output(
                    variable=swat_var,
                    output_type=self.output_type,
                    unit_id=self.reach_id,
                )

            output = _add_date_column(output, self.model)
            output["date"] = output["date"].dt.normalize()

            # Identify value column
            _meta = {"RCH", "SUB", "GIS", "YEAR", "MON", "DAY", "AREAkm2", "date"}
            var_cols = [c for c in output.columns if c not in _meta]
            var_col = var_cols[0] if var_cols else swat_var

            # Find the matching load column in observed loads
            load_cols = [c for c in self._observed_loads_df.columns
                        if c.startswith(const_name) and c != "date"]
            if not load_cols:
                all_sim_values.append(
                    np.full(len(self._observed_loads_df), np.nan)
                )
                continue
            obs_load_col = load_cols[0]

            # Get observation dates for this constituent
            obs_for_const = self._observed_loads_df[["date", obs_load_col]].dropna(subset=[obs_load_col])

            if self._comparison_mode == "volume":
                # Aggregate by month
                obs_monthly = obs_for_const.copy()
                obs_monthly["_ym"] = obs_monthly["date"].dt.to_period("M")
                obs_agg = obs_monthly.groupby("_ym")[obs_load_col].sum().reset_index()

                sim_monthly = output[["date", var_col]].copy()
                sim_monthly["_ym"] = sim_monthly["date"].dt.to_period("M")
                sim_agg = sim_monthly.groupby("_ym")[var_col].sum().reset_index()

                merged = pd.merge(obs_agg, sim_agg, on="_ym", how="left")
                sim_values = merged[var_col].values
            else:
                # Time-series mode: merge on exact date
                merged = pd.merge(
                    obs_for_const[["date"]],
                    output[["date", var_col]],
                    on="date",
                    how="left",
                )
                sim_values = merged[var_col].values

            all_sim_values.append(sim_values)

        # Concatenate all constituent values
        return np.concatenate(all_sim_values)

    def evaluation(self) -> np.ndarray:
        """Return concatenated observed loads for all constituents.

        Must match the layout of simulation() output.
        """
        if not self._observed_loads_computed:
            # If evaluation() is called before any simulation, return zeros
            # (SPOTPY sometimes calls evaluation() first for array sizing)
            return self._nan_array()

        all_obs_values = []

        for const_config in self._constituents:
            const_name = const_config["name"]

            # Find load column
            load_cols = [c for c in self._observed_loads_df.columns
                        if c.startswith(const_name) and c != "date"]
            if not load_cols:
                all_obs_values.append(np.array([]))
                continue
            obs_load_col = load_cols[0]

            obs_for_const = self._observed_loads_df[["date", obs_load_col]].dropna(subset=[obs_load_col])

            if self._comparison_mode == "volume":
                obs_monthly = obs_for_const.copy()
                obs_monthly["_ym"] = obs_monthly["date"].dt.to_period("M")
                obs_agg = obs_monthly.groupby("_ym")[obs_load_col].sum()
                all_obs_values.append(obs_agg.values)
            else:
                all_obs_values.append(obs_for_const[obs_load_col].values)

        return np.concatenate(all_obs_values)

    def objectivefunction(
        self,
        simulation: np.ndarray,
        evaluation: np.ndarray,
        params=None,
    ) -> float:
        """Weighted multi-constituent objective function.

        Splits the concatenated arrays back into per-constituent segments,
        computes the objective function for each, and returns the weighted
        sum.
        """
        _check_cancel_setup(self)

        if not self._observed_loads_computed:
            return -1e10

        # Split arrays back into per-constituent segments
        total_score = 0.0
        offset = 0

        for const_config in self._constituents:
            const_name = const_config["name"]
            weight = const_config["weight"]

            # Determine segment length
            load_cols = [c for c in self._observed_loads_df.columns
                        if c.startswith(const_name) and c != "date"]
            if not load_cols:
                continue
            obs_load_col = load_cols[0]
            obs_for_const = self._observed_loads_df[obs_load_col].dropna()

            if self._comparison_mode == "volume":
                obs_with_dates = self._observed_loads_df[["date", obs_load_col]].dropna(subset=[obs_load_col])
                obs_with_dates["_ym"] = obs_with_dates["date"].dt.to_period("M")
                n_values = obs_with_dates.groupby("_ym").ngroups
            else:
                n_values = len(obs_for_const)

            if n_values == 0:
                continue

            seg_sim = simulation[offset:offset + n_values]
            seg_obs = evaluation[offset:offset + n_values]
            offset += n_values

            # Compute score for this constituent
            mask = ~(np.isnan(seg_sim) | np.isnan(seg_obs))
            if np.sum(mask) < 3:
                total_score += weight * (-1e10)
                continue

            try:
                score = self.objective_func.score(seg_obs[mask], seg_sim[mask])
                total_score += weight * score
            except Exception as e:
                print(f"Objective error for {const_name}: {e}")
                total_score += weight * (-1e10)

        if total_score > self._best_score:
            self._best_score = total_score

        return total_score

    def _nan_array(self) -> np.ndarray:
        """Return an appropriately-sized NaN array for error returns."""
        if self._observed_loads_computed and self._observed_loads_df is not None:
            # Count total observation points across all constituents
            total = 0
            for c in self._constituents:
                load_cols = [col for col in self._observed_loads_df.columns
                            if col.startswith(c["name"]) and col != "date"]
                for col in load_cols:
                    if self._comparison_mode == "volume":
                        obs = self._observed_loads_df[["date", col]].dropna(subset=[col])
                        obs["_ym"] = obs["date"].dt.to_period("M")
                        total += obs.groupby("_ym").ngroups
                    else:
                        total += self._observed_loads_df[col].notna().sum()
            return np.full(max(total, 1), np.nan)
        # Before loads are computed, use dummy size
        return np.full(len(self.observed_df), np.nan)
