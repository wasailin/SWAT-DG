"""
Load Calculator for Water Quality Calibration.

Pairs sparse water quality concentration observations (mg/L) with daily
streamflow to compute loads in SWAT-compatible units for calibration.

SWAT outputs nutrient loads in kg/day (N/P species) and sediment loads in
tons/day.  Observed water quality data is typically reported as concentrations
(mg/L) from grab samples taken monthly or quarterly.  To compare, we compute:

    observed_load = concentration (mg/L) x flow (m3/s) x conversion_factor

The flow source is typically the calibrated SWAT simulated streamflow
(FLOW_OUT from output.rch), or optionally observed streamflow where available.

Usage::

    from swat_modern.io.wq_observation_loader import WQObservationLoader
    from swat_modern.calibration.load_calculator import LoadCalculator

    wq_df = WQObservationLoader.load("wq_data.csv", format="adeq",
                                      station_id="ILL0001")
    calc = LoadCalculator(wq_df, constituents=["TN", "TP", "TSS"])
    loads = calc.compute_loads(sim_flow_df)
"""

import logging
from typing import List, Optional, Union

import numpy as np
import pandas as pd

from swat_modern.io.unit_converter import CONSTITUENT_UNITS, convert_obs_to_load

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constituent name mappings
# ---------------------------------------------------------------------------

# Maps user-facing constituent names to SWAT output.rch variable names.
# These are used for fuzzy column matching when extracting simulated loads
# from output.rch via get_output().
CONSTITUENT_TO_SWAT_VARIABLE = {
    "TN": "TOT_N",
    "TP": "TOT_P",
    "TSS": "SED_OUT",
    "SEDCONC": "SEDCONC",       # Sediment concentration (mg/L) in output.rch
    "NO3": "NO3_OUT",
    "NH4": "NH4_OUT",
    "NO2": "NO2_OUT",
    "ORGN": "ORGN_OUT",
    "ORGP": "ORGP_OUT",
    "MINP": "MINP_OUT",
}

# Maps constituent names to WQ observation DataFrame column names produced
# by WQObservationLoader (see wq_observation_loader.py canonical columns).
#
# Canonical columns from WQObservationLoader:
#   TN_mg_L, TP_mg_L, TSS_mg_L, NH4_mg_L, NO3_mg_L, OrgN_mg_L,
#   OrthoP_mg_L, TKN_mg_L
#
# Notes on phosphorus mapping:
#   - OrthoP (orthophosphate) is dissolved inorganic P, corresponding to
#     MINP_OUT (mineral/soluble P) in SWAT.
#   - ORGP_OUT in SWAT is organic P.  The WQ loader does not produce a
#     direct "OrgP_mg_L" column; it must be computed upstream as
#     TP - OrthoP.  We map ORGP to "OrgP_mg_L" here so that callers who
#     pre-compute that column can use it directly.
CONSTITUENT_TO_OBS_COLUMN = {
    "TN": "TN_mg_L",
    "TP": "TP_mg_L",
    "TSS": "TSS_mg_L",
    "SEDCONC": "TSS_mg_L",     # Concentration-based sediment comparison
    "NO3": "NO3_mg_L",
    "NH4": "NH4_mg_L",
    "ORGN": "OrgN_mg_L",
    "ORGP": "OrgP_mg_L",       # Organic P (computed upstream: TP - OrthoP)
    "MINP": "OrthoP_mg_L",     # Mineral/dissolved P ≈ orthophosphate
}


# ---------------------------------------------------------------------------
# LoadCalculator class
# ---------------------------------------------------------------------------


class LoadCalculator:
    """Compute observed loads by pairing WQ concentrations with streamflow.

    Water quality observations are typically sparse concentration measurements
    (monthly or quarterly).  To compare with SWAT-simulated loads, we multiply
    observed concentrations by daily streamflow:

        load = concentration (mg/L) x flow (m3/s) x conversion_factor

    The flow source is typically the calibrated SWAT simulated streamflow
    (FLOW_OUT from output.rch), or optionally observed streamflow.

    Parameters
    ----------
    wq_obs_df : pandas.DataFrame
        DataFrame from ``WQObservationLoader`` with a ``date`` column and
        concentration columns (``TN_mg_L``, ``TP_mg_L``, ``TSS_mg_L``, etc.).
    constituents : list of str, optional
        List of constituent names to compute loads for (e.g.
        ``["TN", "TP", "TSS"]``).  If ``None``, constituents are
        auto-detected from non-NaN columns in *wq_obs_df*.

    Raises
    ------
    ValueError
        If *wq_obs_df* does not contain a ``date`` column, or if any
        requested constituent is not recognised.

    Example
    -------
    ::

        calc = LoadCalculator(wq_df, constituents=["TN", "TP", "TSS"])
        loads = calc.compute_loads(sim_flow_df)
        print(loads.head())
        #        date  TN_load_kg  TP_load_kg  TSS_load_tons
        # 0  2005-03-15      125.4       12.3           45.6
    """

    def __init__(
        self,
        wq_obs_df: pd.DataFrame,
        constituents: Optional[List[str]] = None,
    ) -> None:
        if "date" not in wq_obs_df.columns:
            raise ValueError(
                "wq_obs_df must contain a 'date' column. "
                "Use WQObservationLoader.load() to produce the expected format."
            )

        self.wq_obs_df = wq_obs_df.copy()
        self.wq_obs_df["date"] = pd.to_datetime(
            self.wq_obs_df["date"]
        ).dt.normalize()

        # Auto-compute OrgP_mg_L from TP - OrthoP if not already present.
        # Organic P is not a standard canonical column from WQObservationLoader,
        # but it can be derived when both TP and OrthoP (mineral/dissolved P)
        # are available.  This enables ORGP calibration without requiring
        # upstream pre-computation.
        self._ensure_orgp_column()

        if constituents is None:
            constituents = self._auto_detect_constituents()
        self.constituents = [c.upper() for c in constituents]

        # Validate constituents
        for c in self.constituents:
            if c not in CONSTITUENT_TO_OBS_COLUMN:
                raise ValueError(
                    f"Unknown constituent '{c}'. "
                    f"Available: {list(CONSTITUENT_TO_OBS_COLUMN.keys())}"
                )

    # ------------------------------------------------------------------
    # Derived columns
    # ------------------------------------------------------------------

    def _ensure_orgp_column(self) -> None:
        """Compute ``OrgP_mg_L`` from ``TP_mg_L - OrthoP_mg_L`` if missing.

        Organic phosphorus is not a standard canonical column from
        ``WQObservationLoader``, but it can be derived where both Total P
        and Orthophosphate are available.  Values are clipped to >= 0 to
        avoid negative concentrations from measurement uncertainty.
        """
        if "OrgP_mg_L" in self.wq_obs_df.columns:
            n_existing = self.wq_obs_df["OrgP_mg_L"].notna().sum()
            if n_existing > 0:
                logger.debug(
                    "OrgP_mg_L already present (%d valid values); "
                    "skipping auto-computation.",
                    n_existing,
                )
                return

        if (
            "TP_mg_L" in self.wq_obs_df.columns
            and "OrthoP_mg_L" in self.wq_obs_df.columns
        ):
            tp = self.wq_obs_df["TP_mg_L"]
            ortho_p = self.wq_obs_df["OrthoP_mg_L"]
            can_calc = tp.notna() & ortho_p.notna()
            n_calc = can_calc.sum()

            if n_calc > 0:
                org_p = (tp - ortho_p).clip(lower=0.0)
                # Only set where both inputs are valid
                self.wq_obs_df["OrgP_mg_L"] = np.where(can_calc, org_p, np.nan)
                logger.info(
                    "Auto-computed OrgP_mg_L = TP - OrthoP for %d observations "
                    "(clipped to >= 0).",
                    n_calc,
                )
            else:
                logger.debug(
                    "Cannot compute OrgP_mg_L: no rows with both TP and "
                    "OrthoP available."
                )

    # ------------------------------------------------------------------
    # Auto-detection
    # ------------------------------------------------------------------

    def _auto_detect_constituents(self) -> List[str]:
        """Auto-detect available constituents from non-NaN observation columns.

        Scans the observation DataFrame for canonical concentration columns
        that contain at least one valid (non-NaN) value.

        Returns
        -------
        list of str
            Detected constituent names (e.g. ``["TN", "TP", "TSS"]``).
            Falls back to ``["TN", "TP", "TSS"]`` if nothing is detected.
        """
        detected: List[str] = []
        for const, obs_col in CONSTITUENT_TO_OBS_COLUMN.items():
            if obs_col in self.wq_obs_df.columns:
                n_valid = self.wq_obs_df[obs_col].notna().sum()
                if n_valid > 0:
                    detected.append(const)
                    logger.debug(
                        "Auto-detected constituent %s (%d valid observations)",
                        const,
                        n_valid,
                    )

        if detected:
            return detected

        # Fallback when no canonical columns are found
        logger.warning(
            "No WQ concentration columns detected; "
            "falling back to default constituents [TN, TP, TSS]."
        )
        return ["TN", "TP", "TSS"]

    # ------------------------------------------------------------------
    # Core load computation
    # ------------------------------------------------------------------

    def compute_loads(self, flow_df: pd.DataFrame) -> pd.DataFrame:
        """Compute observed loads by pairing concentrations with flow.

        For each WQ observation date, looks up the corresponding daily flow
        and computes:

            load = concentration x flow x conversion_factor

        using ``convert_obs_to_load()`` from the unit converter module.

        Parameters
        ----------
        flow_df : pandas.DataFrame
            DataFrame with ``date`` and a flow column (``flow_cms``,
            ``FLOW_OUTcms``, ``flow``, ``Q(CMS)``, or ``streamflow``).
            Flow must be in m3/s.  Can be simulated SWAT output or observed
            streamflow.

        Returns
        -------
        pandas.DataFrame
            DataFrame with columns::

                date | TN_load_kg | TP_load_kg | TSS_load_tons | ...

            Only columns for requested constituents are included.  Only rows
            with valid concentration AND flow data are returned.

        Raises
        ------
        ValueError
            If no flow column can be identified in *flow_df*.
        """
        # Standardize flow_df
        flow = flow_df.copy()
        flow["date"] = pd.to_datetime(flow["date"]).dt.normalize()

        # Find the flow column
        flow_col = self._find_flow_column(flow)

        # Merge WQ observations with flow on date
        merged = pd.merge(
            self.wq_obs_df,
            flow[["date", flow_col]].rename(columns={flow_col: "_flow_cms"}),
            on="date",
            how="left",
        )

        # Log merge statistics
        n_total = len(self.wq_obs_df)
        n_matched = merged["_flow_cms"].notna().sum()
        if n_matched < n_total:
            n_missing = n_total - n_matched
            logger.info(
                "%d/%d WQ observation dates matched with flow data "
                "(%d dates without flow).",
                n_matched,
                n_total,
                n_missing,
            )

        # Compute loads for each constituent
        result = pd.DataFrame({"date": merged["date"]})

        for const in self.constituents:
            obs_col = CONSTITUENT_TO_OBS_COLUMN.get(const)
            if obs_col is None or obs_col not in merged.columns:
                logger.debug(
                    "Observation column '%s' for constituent %s not found "
                    "in WQ DataFrame; skipping.",
                    obs_col,
                    const,
                )
                continue

            conc = merged[obs_col].values
            flow_vals = merged["_flow_cms"].values

            # NaN propagation: NaN conc or NaN flow -> NaN load (numpy default)
            load = convert_obs_to_load(const, conc, flow_vals)

            # Determine the load column name from CONSTITUENT_UNITS
            units = CONSTITUENT_UNITS.get(const, {})
            load_unit = units.get("load_unit", "kg/day")
            if load_unit == "tons/day":
                col_name = f"{const}_load_tons"
            elif load_unit == "kg/day":
                col_name = f"{const}_load_kg"
            else:
                col_name = f"{const}_load"

            result[col_name] = load

        # Drop rows where all load columns are NaN (no usable data)
        load_cols = [c for c in result.columns if c != "date"]
        if load_cols:
            result = result.dropna(subset=load_cols, how="all").reset_index(
                drop=True
            )

        return result

    def compute_loads_with_fallback(
        self,
        sim_flow_df: pd.DataFrame,
        obs_flow_df: Optional[pd.DataFrame] = None,
    ) -> pd.DataFrame:
        """Compute loads using observed flow where available, simulated as fallback.

        When both observed and simulated streamflow are provided, observed
        flow takes priority for dates where it is available.  For remaining
        dates, simulated SWAT flow is used as a fallback.

        Parameters
        ----------
        sim_flow_df : pandas.DataFrame
            Simulated SWAT flow DataFrame (``date`` + flow column).
        obs_flow_df : pandas.DataFrame, optional
            Observed streamflow DataFrame (``date`` + flow column).
            Where available, observed flow takes priority over simulated.

        Returns
        -------
        pandas.DataFrame
            Same format as :meth:`compute_loads`.
        """
        if obs_flow_df is None:
            return self.compute_loads(sim_flow_df)

        # Standardize dates
        sim = sim_flow_df.copy()
        sim["date"] = pd.to_datetime(sim["date"]).dt.normalize()
        obs = obs_flow_df.copy()
        obs["date"] = pd.to_datetime(obs["date"]).dt.normalize()

        # Find flow columns in each DataFrame
        sim_flow_col = self._find_flow_column(sim)
        obs_flow_col = self._find_flow_column(obs)

        # Merge observed flow onto WQ observation dates first
        combined = self.wq_obs_df[["date"]].copy()
        combined = pd.merge(
            combined,
            obs[["date", obs_flow_col]].rename(
                columns={obs_flow_col: "_obs_flow"}
            ),
            on="date",
            how="left",
        )
        combined = pd.merge(
            combined,
            sim[["date", sim_flow_col]].rename(
                columns={sim_flow_col: "_sim_flow"}
            ),
            on="date",
            how="left",
        )

        # Use observed where available, simulated as fallback
        combined["_flow_cms"] = combined["_obs_flow"].fillna(
            combined["_sim_flow"]
        )

        n_obs_used = combined["_obs_flow"].notna().sum()
        n_sim_used = (
            combined["_flow_cms"].notna().sum() - n_obs_used
        )
        logger.info(
            "Flow source: %d dates from observed, %d from simulated.",
            n_obs_used,
            max(0, n_sim_used),
        )

        # Build a flow DataFrame for compute_loads
        flow_for_calc = combined[["date", "_flow_cms"]].rename(
            columns={"_flow_cms": "flow_cms"}
        )
        return self.compute_loads(flow_for_calc)

    # ------------------------------------------------------------------
    # Observation date queries
    # ------------------------------------------------------------------

    def get_observation_dates(
        self, constituent: Optional[str] = None
    ) -> np.ndarray:
        """Get dates where valid observations exist for a constituent.

        Parameters
        ----------
        constituent : str, optional
            Specific constituent name (e.g. ``"TN"``).  If ``None``,
            returns dates where ANY constituent has data.

        Returns
        -------
        numpy.ndarray
            Array of datetime64 values for dates with valid observations.
        """
        if constituent is not None:
            obs_col = CONSTITUENT_TO_OBS_COLUMN.get(constituent.upper())
            if obs_col and obs_col in self.wq_obs_df.columns:
                valid = self.wq_obs_df[self.wq_obs_df[obs_col].notna()]
                return valid["date"].values
            return np.array([], dtype="datetime64[ns]")

        # Any constituent -- find dates where at least one has data
        obs_cols = [
            CONSTITUENT_TO_OBS_COLUMN[c]
            for c in self.constituents
            if CONSTITUENT_TO_OBS_COLUMN.get(c) in self.wq_obs_df.columns
        ]
        if not obs_cols:
            return np.array([], dtype="datetime64[ns]")

        valid = self.wq_obs_df.dropna(subset=obs_cols, how="all")
        return valid["date"].values

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------

    def summary(self) -> str:
        """Return a human-readable summary of available observations.

        Returns
        -------
        str
            Multi-line summary string showing constituents, date range,
            and observation counts.
        """
        lines = ["Load Calculator Summary:"]
        lines.append(f"  Constituents: {self.constituents}")

        date_min = self.wq_obs_df["date"].min()
        date_max = self.wq_obs_df["date"].max()
        lines.append(f"  Date range: {date_min} to {date_max}")
        lines.append(f"  Total observation dates: {len(self.wq_obs_df)}")

        for const in self.constituents:
            obs_col = CONSTITUENT_TO_OBS_COLUMN.get(const)
            if obs_col and obs_col in self.wq_obs_df.columns:
                n_valid = self.wq_obs_df[obs_col].notna().sum()
                lines.append(f"  {const}: {n_valid} valid observations")
            else:
                lines.append(f"  {const}: column not found in data")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _find_flow_column(df: pd.DataFrame) -> str:
        """Find the flow column in a DataFrame.

        Searches for common flow column names in priority order, then
        falls back to the first numeric column.

        Parameters
        ----------
        df : pandas.DataFrame
            DataFrame to search for a flow column.

        Returns
        -------
        str
            Name of the identified flow column.

        Raises
        ------
        ValueError
            If no flow column can be found.
        """
        for candidate in [
            "flow_cms",
            "FLOW_OUTcms",
            "flow",
            "Q(CMS)",
            "streamflow",
        ]:
            if candidate in df.columns:
                return candidate

        # Fall back to first numeric column that is not 'date'
        numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
        if numeric_cols:
            return numeric_cols[0]

        raise ValueError(
            "No flow column found in DataFrame. "
            "Expected one of: flow_cms, FLOW_OUTcms, flow, Q(CMS), streamflow."
        )
