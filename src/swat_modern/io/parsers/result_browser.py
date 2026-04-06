"""
SWAT simulation result browser.

High-level wrapper around OutputParser for browsing and extracting
simulation results from SWAT output files.
"""

import calendar
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Union

import numpy as np
import pandas as pd

from swat_modern.io.parsers.output_parser import (
    OutputParser,
    REACH_COLUMNS,
    SUBBASIN_COLUMNS,
    HRU_COLUMNS,
    RESERVOIR_COLUMNS,
    SEDIMENT_COLUMNS,
)


# Priority variables organized by category for UI display
PRIORITY_VARIABLES = {
    "rch": {
        "Streamflow": ["FLOW_INcms", "FLOW_OUTcms"],
        "Sediment": ["SED_INtons", "SED_OUTtons", "SEDCONCmg_L"],
        "Nitrogen": ["ORGN_INkg", "ORGN_OUTkg", "NO3_INkg", "NO3_OUTkg",
                      "NH4_INkg", "NH4_OUTkg"],
        "Phosphorus": ["ORGP_INkg", "ORGP_OUTkg", "MINP_INkg", "MINP_OUTkg"],
        "Other": ["EVAPcms", "TLOSScms", "WTMPdegc", "TOT_Nkg", "TOT_Pkg"],
    },
    "sub": {
        "Water Balance": ["PRECIPmm", "PETmm", "ETmm", "SWmm", "PERCmm",
                          "SURQmm", "GW_Qmm", "WYLDmm", "LAT_Qmm"],
        "Sediment": ["SYLDt_ha"],
        "Nitrogen": ["ORGNkg_ha", "NSURQkg_ha", "LATNO3kg_h", "GWNO3kg_ha",
                      "TNO3kg_ha"],
        "Phosphorus": ["ORGPkg_ha", "SOLPkg_ha", "SEDPkg_ha"],
        "Snow": ["SNOMELTmm"],
    },
    "hru": {
        "Water Balance": ["PRECIPmm", "PETmm", "ETmm", "SW_ENDmm", "PERCmm",
                          "SURQmm", "GW_Qmm", "WYLDmm", "LAT_Qmm"],
        "Sediment": ["SYLDt_ha"],
        "Nitrogen": ["ORGNkg_ha", "NSURQkg_ha", "LATNO3kg_h", "GWNO3kg_ha"],
        "Phosphorus": ["ORGPkg_ha", "SOLPkg_ha", "SEDPkg_ha"],
        "Snow": ["SNOFALLmm", "SNOMELTmm"],
    },
    "sed": {
        "Total Sediment": ["SED_INtons", "SED_OUTtons"],
        "Sand": ["SAND_INtons", "SAND_OUTtons"],
        "Silt": ["SILT_INtons", "SILT_OUTtons"],
        "Clay": ["CLAY_INtons", "CLAY_OUTtons"],
        "Small Aggregate": ["SMAG_INtons", "SMAG_OUTtons"],
        "Large Aggregate": ["LAG_INtons", "LAG_OUTtons"],
        "Gravel": ["GRA_INtons", "GRA_OUTtons"],
        "Channel Erosion": ["CH_BNKtons", "CH_BEDtons", "CH_DEPtons", "FP_DEPtons"],
        "Concentration": ["TSSmg_L"],
    },
}

# Column name mappings for all output types
OUTPUT_COLUMNS = {
    "rch": REACH_COLUMNS,
    "sub": SUBBASIN_COLUMNS,
    "hru": HRU_COLUMNS,
    "rsv": RESERVOIR_COLUMNS,
    "sed": SEDIMENT_COLUMNS,
}

# ID column names per output type
ID_COLUMN = {
    "rch": "RCH",
    "sub": "SUB",
    "hru": "HRU",
    "rsv": "RES",
    "sed": "RCH",
}


class ResultBrowser:
    """
    Browse SWAT simulation output files.

    Provides a high-level interface for listing available outputs,
    extracting time series, and computing summaries.

    Example:
        >>> browser = ResultBrowser("C:/swat_project")
        >>> available = browser.list_available_outputs()
        >>> variables = browser.get_variables("rch")
        >>> ts = browser.get_time_series("rch", "FLOW_OUTcms", unit_id=1)
    """

    def __init__(
        self,
        project_dir: Union[str, Path],
        start_year: Optional[int] = None,
        start_day: int = 1,
        print_code: int = 0,
        warmup_years: int = 0,
    ):
        """
        Initialize result browser.

        Args:
            project_dir: Path to SWAT project directory.
            start_year: Simulation start year. If None, tries to read from file.cio.
            start_day: Simulation start Julian day.
            print_code: Output print code (0=monthly, 1=daily, 2=yearly).
            warmup_years: Number of warmup years to skip.
        """
        self.project_dir = Path(project_dir)
        self._cache: Dict[str, pd.DataFrame] = {}

        # Try to get config from file.cio
        if start_year is None:
            try:
                from swat_modern.core.config import SWATConfig
                config = SWATConfig(self.project_dir)
                self._start_year = config.period.start_year
                self._start_day = config.period.start_day
                self._print_code = config.output.print_code
                self._warmup_years = config.period.warmup_years
                self._end_year = config.period.end_year
            except Exception:
                self._start_year = 2000
                self._start_day = start_day
                self._print_code = print_code
                self._warmup_years = warmup_years
                self._end_year = None
        else:
            self._start_year = start_year
            self._start_day = start_day
            self._print_code = print_code
            self._warmup_years = warmup_years
            self._end_year = None

    def list_available_outputs(self) -> Dict[str, bool]:
        """
        Check which output files exist in the project directory.

        Returns:
            Dict mapping output type to existence boolean.
            e.g., {'rch': True, 'sub': True, 'hru': False, 'rsv': False, 'std': True}
        """
        result = {}
        for ext in ["rch", "sub", "sed", "rsv", "std"]:
            output_file = self.project_dir / f"output.{ext}"
            result[ext] = output_file.exists()
        return result

    def get_variables(self, output_type: str) -> List[str]:
        """
        Get list of available variable names for an output type.

        Args:
            output_type: 'rch', 'sub', 'hru', or 'rsv'.

        Returns:
            List of column names available in that output file.
        """
        if output_type in OUTPUT_COLUMNS:
            return OUTPUT_COLUMNS[output_type]
        raise ValueError(f"Unknown output type: {output_type}")

    def get_priority_variables(self, output_type: str) -> Dict[str, List[str]]:
        """
        Get priority variables organized by category.

        Args:
            output_type: 'rch', 'sub', or 'hru'.

        Returns:
            Dict mapping category name to list of variable names.
        """
        return PRIORITY_VARIABLES.get(output_type, {})

    def get_unit_ids(self, output_type: str) -> List[int]:
        """
        Get list of unique unit IDs from the output file.

        For HRU output, uses a fast scan that reads only the first time step
        (terminates after one full cycle of HRU IDs) to avoid parsing the
        entire ~1.75M row file just to populate the dropdown.
        """
        if output_type == 'hru':
            return self._get_hru_ids_fast_scan()
        df = self._get_parsed_data(output_type)
        id_col = ID_COLUMN.get(output_type)
        if id_col and id_col in df.columns:
            return sorted(df[id_col].unique().tolist())
        return []

    def _get_hru_ids_fast_scan(self) -> List[int]:
        """
        Read HRU IDs from the first time step only.

        HRU output writes all HRUs for time step 1, then all HRUs for time
        step 2, etc.  We read lines until we see a repeated HRU ID — at that
        point we have collected exactly one full cycle (= all HRU numbers).

        Falls back to full parse if HRU data is already in the in-memory cache
        (avoids duplicate reads when the data was pre-loaded by another call).
        """
        # If full data is already cached, just extract IDs from it
        if 'hru' in self._cache:
            df = self._cache['hru']
            if 'HRU' in df.columns:
                return sorted(df['HRU'].unique().tolist())

        output_file = self.project_dir / "output.hru"
        if not output_file.exists():
            return []

        ids: List[int] = []
        seen: set = set()

        with open(output_file, 'r') as f:
            # Advance past header lines
            header_found = False
            for line in f:
                if "LULC" in line and "HRU" in line:
                    header_found = True
                    break
            if not header_found:
                return []

            for line in f:
                if not line.strip():
                    continue
                parts = line.split()
                if len(parts) < 5:
                    continue
                try:
                    # HRU format: LULC(0) HRU(1) GIS(2) SUB(3) MGT(4) ...
                    hru_id = int(parts[1])
                except (ValueError, IndexError):
                    continue

                if hru_id in seen:
                    break  # Second cycle started — we have all unique IDs
                seen.add(hru_id)
                ids.append(hru_id)

        return sorted(ids)

    def get_time_series(
        self,
        output_type: str,
        variable: str,
        unit_id: int,
    ) -> pd.DataFrame:
        """
        Extract a time series for a specific variable and spatial unit.

        Reconstructs dates from YEAR/MON/DAY columns based on the
        simulation configuration.

        Args:
            output_type: 'rch', 'sub', 'hru', or 'rsv'.
            variable: Variable column name (e.g., 'FLOW_OUTcms').
            unit_id: Spatial unit ID (reach, subbasin, or HRU number).

        Returns:
            DataFrame with 'date' index and the variable as column.
        """
        df = self._get_parsed_data(output_type)
        id_col = ID_COLUMN.get(output_type)

        if id_col is None or id_col not in df.columns:
            raise ValueError(f"ID column not found for output type: {output_type}")

        if variable not in df.columns:
            raise ValueError(
                f"Variable '{variable}' not found. "
                f"Available: {[c for c in df.columns if c not in [id_col, 'GIS', 'MON', 'DAY', 'YEAR', 'AREAkm2']]}"
            )

        # Filter to specific unit
        unit_df = df[df[id_col] == unit_id].copy()

        # Filter out annual summary rows (present in output.sub, flagged by _is_annual=True).
        # These have MON = year counter (1..N) instead of Julian day; including them
        # corrupts the date sequence.
        if '_is_annual' in unit_df.columns:
            unit_df = unit_df[~unit_df['_is_annual']].copy()

        if len(unit_df) == 0:
            raise ValueError(f"No data found for {id_col}={unit_id}")

        # Reconstruct dates
        dates = self._reconstruct_dates(unit_df)
        if dates is not None:
            result = pd.DataFrame({
                "date": dates,
                variable: unit_df[variable].values,
            })
            result = result.set_index("date").sort_index()
        else:
            # Fallback: use row index
            result = pd.DataFrame({variable: unit_df[variable].values})

        return result

    def get_accumulated_time_series(
        self,
        output_type: str,
        variable: str,
        upstream_reach_ids: set,
        label_id: int,
    ) -> pd.DataFrame:
        """
        Sum a variable across multiple reaches and return as a time series.

        Used when output.rch contains local-only flow (no accumulated routing)
        and the caller needs accumulated streamflow at a gauge location.

        IMPORTANT: The RCH column in output.rch contains **reach numbers**,
        not subbasin numbers. Each reach routes a different subbasin's flow
        as determined by fig.fig. Callers must translate subbasin IDs to
        reach IDs via ``FigFileParser.subbasin_to_reach`` before passing
        them here.

        Each reach's rows share the same time steps in the same order
        (SWAT writes all reaches per time step sequentially).  This method
        groups by within-reach row index and sums the variable.

        Args:
            output_type: 'rch' (only type where accumulation applies).
            variable: Variable column name (e.g., 'FLOW_OUTcms').
            upstream_reach_ids: Set of **reach IDs** (RCH column values)
                to sum across.  Must be translated from subbasin IDs
                via ``subbasin_to_reach``.
            label_id: ID to label the output RCH column with.

        Returns:
            DataFrame with 'date' index and the variable as column,
            same format as ``get_time_series()``.
        """
        if not upstream_reach_ids:
            raise ValueError("upstream_subbasin_ids must be a non-empty set")

        df = self._get_parsed_data(output_type)
        id_col = ID_COLUMN.get(output_type, "RCH")

        if variable not in df.columns:
            raise ValueError(
                f"Variable '{variable}' not found. "
                f"Available: {[c for c in df.columns if c not in [id_col, 'GIS', 'MON', 'DAY', 'YEAR', 'AREAkm2']]}"
            )

        # Filter to upstream reaches only
        upstream_df = df[df[id_col].isin(upstream_reach_ids)].copy()

        if len(upstream_df) == 0:
            raise ValueError(
                f"No data found for any upstream reaches: "
                f"{sorted(upstream_reach_ids)}"
            )

        # Assign within-reach row index for time-step grouping
        upstream_df["_ts_idx"] = upstream_df.groupby(id_col).cumcount()

        # Sum the variable across reaches for each time step
        summed = upstream_df.groupby("_ts_idx")[variable].sum()

        # Use one reach's rows as template (preserves MON/DAY/YEAR)
        one_sub = next(iter(upstream_reach_ids))
        template = (
            df[df[id_col] == one_sub]
            .copy()
            .reset_index(drop=True)
        )
        template[variable] = summed.values
        template[id_col] = label_id

        # Filter annual summary rows from template before date reconstruction
        if '_is_annual' in template.columns:
            template = template[~template['_is_annual']].reset_index(drop=True)
            template[variable] = summed.values[:len(template)]

        # Reconstruct dates from the template
        dates = self._reconstruct_dates(template)
        if dates is not None:
            result = pd.DataFrame({
                "date": dates,
                variable: template[variable].values,
            })
            result = result.set_index("date").sort_index()
        else:
            result = pd.DataFrame({variable: template[variable].values})

        return result

    def get_spatial_summary(
        self,
        output_type: str,
        variable: str,
        aggregation: str = "mean",
    ) -> pd.DataFrame:
        """
        Aggregate a variable across time for each spatial unit.

        Useful for coloring subbasins on a map.

        Args:
            output_type: 'rch', 'sub', 'hru', or 'rsv'.
            variable: Variable to aggregate.
            aggregation: 'mean', 'sum', 'max', 'min', 'std'.

        Returns:
            DataFrame with columns: [id_column, variable].
        """
        df = self._get_parsed_data(output_type)
        id_col = ID_COLUMN.get(output_type)

        if id_col is None or id_col not in df.columns:
            raise ValueError(f"ID column not found for output type: {output_type}")

        if variable not in df.columns:
            raise ValueError(f"Variable '{variable}' not found")

        agg_func = {
            "mean": "mean",
            "sum": "sum",
            "max": "max",
            "min": "min",
            "std": "std",
        }.get(aggregation)

        if agg_func is None:
            raise ValueError(f"Unknown aggregation: {aggregation}")

        result = df.groupby(id_col)[variable].agg(agg_func).reset_index()
        result.columns = [id_col, variable]
        return result

    def get_summary_statistics(
        self,
        output_type: str,
        variable: str,
        unit_id: Optional[int] = None,
    ) -> pd.DataFrame:
        """
        Compute summary statistics for a variable.

        Args:
            output_type: 'rch', 'sub', 'hru', or 'rsv'.
            variable: Variable to summarize.
            unit_id: If specified, compute stats for only that unit.
                     If None, compute stats for each unit.

        Returns:
            DataFrame with statistics.
        """
        df = self._get_parsed_data(output_type)
        id_col = ID_COLUMN.get(output_type)

        if variable not in df.columns:
            raise ValueError(f"Variable '{variable}' not found")

        if unit_id is not None:
            subset = df[df[id_col] == unit_id][variable]
            stats = {
                id_col: [unit_id],
                "count": [len(subset)],
                "mean": [subset.mean()],
                "std": [subset.std()],
                "min": [subset.min()],
                "25%": [subset.quantile(0.25)],
                "median": [subset.median()],
                "75%": [subset.quantile(0.75)],
                "max": [subset.max()],
            }
            return pd.DataFrame(stats)
        else:
            grouped = df.groupby(id_col)[variable]
            return grouped.describe().reset_index()

    def get_raw_data(self, output_type: str) -> pd.DataFrame:
        """
        Get the full parsed DataFrame for an output type.

        Args:
            output_type: 'rch', 'sub', 'hru', 'rsv', or 'std'.

        Returns:
            Parsed DataFrame.
        """
        return self._get_parsed_data(output_type)

    # -------------------------------------------------------------------------
    # Private helpers
    # -------------------------------------------------------------------------

    def _get_parsed_data(self, output_type: str) -> pd.DataFrame:
        """Load and cache parsed output data."""
        if output_type in self._cache:
            return self._cache[output_type]

        output_file = self.project_dir / f"output.{output_type}"
        if not output_file.exists():
            raise FileNotFoundError(f"Output file not found: {output_file}")

        # Parquet disk cache — invalidated when output file is newer
        parquet_file = output_file.parent / f"{output_file.name}.parquet"
        if parquet_file.exists():
            try:
                if parquet_file.stat().st_mtime >= output_file.stat().st_mtime:
                    result = pd.read_parquet(parquet_file)
                    self._cache[output_type] = result
                    return result
            except Exception:
                pass  # corrupted or incompatible cache → fall through to full parse

        parser = OutputParser(output_file)
        result = parser.parse()

        if isinstance(result, dict):
            # output.std returns a dict, not a DataFrame
            return pd.DataFrame()

        # Save parquet for faster subsequent loads
        try:
            result.to_parquet(parquet_file, index=False)
        except Exception:
            pass  # non-fatal; proceed without disk cache

        self._cache[output_type] = result
        return result

    def _reconstruct_dates(self, df: pd.DataFrame) -> Optional[pd.DatetimeIndex]:
        """
        Reconstruct dates from YEAR/MON/DAY columns.

        Handles daily (print_code=1), monthly (print_code=0),
        and yearly (print_code=2) output.

        For daily output without explicit YEAR/DAY columns, the MON column
        contains Julian day-of-year values (1-366) and the year is inferred
        from the simulation start year and warmup period.
        """
        has_year = "YEAR" in df.columns
        has_mon = "MON" in df.columns
        has_day = "DAY" in df.columns

        try:
            if has_year and has_day and has_mon:
                # Daily output with explicit date columns
                dates = []
                for _, row in df.iterrows():
                    year = int(row["YEAR"])
                    day_of_year = int(row["DAY"])
                    d = date(year, 1, 1) + timedelta(days=day_of_year - 1)
                    dates.append(d)
                return pd.DatetimeIndex(dates)

            elif has_mon and not has_year:
                mon_values = df["MON"].values
                max_mon = int(max(mon_values))

                if max_mon > 12:
                    # Daily output: MON contains Julian day-of-year (1-366)
                    return self._reconstruct_daily_dates(mon_values)
                else:
                    # Monthly output: MON contains month numbers 1-12
                    return self._reconstruct_monthly_dates(mon_values)

            elif has_mon and has_year:
                # Has both MON and YEAR
                dates = []
                for _, row in df.iterrows():
                    year = int(row["YEAR"])
                    mon = int(row["MON"])
                    if 1 <= mon <= 12:
                        last_day = calendar.monthrange(year, mon)[1]
                        dates.append(date(year, mon, last_day))
                    else:
                        dates.append(date(year, 12, 31))
                return pd.DatetimeIndex(dates)

        except Exception:
            pass

        return None

    def _reconstruct_daily_dates(self, mon_values) -> pd.DatetimeIndex:
        """
        Reconstruct dates for daily output where MON = Julian day-of-year.

        Year increments when the day-of-year resets to a smaller value.
        """
        dates = []
        current_year = self._start_year + self._warmup_years
        prev_day = 0

        for jday in mon_values:
            jday = int(jday)
            if jday < prev_day:
                # Day-of-year reset means new year
                current_year += 1
            prev_day = jday
            d = date(current_year, 1, 1) + timedelta(days=jday - 1)
            dates.append(d)

        return pd.DatetimeIndex(dates)

    def _reconstruct_monthly_dates(self, mon_values) -> pd.DatetimeIndex:
        """
        Reconstruct dates for monthly output where MON = month number (1-12).

        Year increments when month resets to a smaller value.
        """
        dates = []
        current_year = self._start_year + self._warmup_years
        prev_mon = 0

        for mon in mon_values:
            mon = int(mon)
            if mon < prev_mon:
                current_year += 1
            prev_mon = mon

            if 1 <= mon <= 12:
                last_day = calendar.monthrange(current_year, mon)[1]
                dates.append(date(current_year, mon, last_day))
            else:
                # Annual summary row
                dates.append(date(current_year, 12, 31))

        return pd.DatetimeIndex(dates)
