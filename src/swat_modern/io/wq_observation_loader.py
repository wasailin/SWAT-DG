"""
Water Quality Observation Loader.

Loads water quality observation data from multiple agency formats (ADEQ,
pre-processed OBSfiles, AWRC/WQP STORET, and generic CSV) and produces a
standardized DataFrame with concentrations in mg/L.

Standardized output columns::

    date | TN_mg_L | TP_mg_L | TSS_mg_L | NH4_mg_L | NO3_mg_L |
           OrgN_mg_L | OrthoP_mg_L | TKN_mg_L

All dates are normalized to midnight.  Missing species are NaN.
"""

import logging
import re
from pathlib import Path
from typing import Dict, List, Optional, Union

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Canonical column definitions
# ---------------------------------------------------------------------------

CANONICAL_COLUMNS = {
    "TN_mg_L": "Total Nitrogen",
    "TP_mg_L": "Total Phosphorus",
    "TSS_mg_L": "Total Suspended Solids",
    "NH4_mg_L": "Ammonia-Nitrogen",
    "NO3_mg_L": "Nitrate+Nitrite-Nitrogen",
    "OrgN_mg_L": "Organic Nitrogen",
    "OrthoP_mg_L": "Orthophosphate-Phosphorus",
    "TKN_mg_L": "Total Kjeldahl Nitrogen",
}

# ---------------------------------------------------------------------------
# ADEQ column name -> canonical column mapping
# ---------------------------------------------------------------------------

_ADEQ_COLUMN_MAP = {
    "Total Nitrogen from Lachat (mg/L)": "TN_mg_L",
    "Total Phosphorus (mg/L)": "TP_mg_L",
    "Total suspended solids (mg/L)": "TSS_mg_L",
    "Ammonia-nitrogen (mg/L)": "NH4_mg_L",
    "Nitrite+Nitrate as Nitrogen (mg/L)": "NO3_mg_L",
    "Total Kjeldahl nitrogen (mg/L)": "TKN_mg_L",
    "Orthophosphate (mg/L)": "OrthoP_mg_L",
}

# ---------------------------------------------------------------------------
# AWRC / WQP CharacteristicName -> canonical column mapping
# ---------------------------------------------------------------------------

_AWRC_CHARACTERISTIC_MAP = {
    "Total Nitrogen, mixed forms": "TN_mg_L",
    "Total Phosphorus, mixed forms": "TP_mg_L",
    "Total Suspended Solids": "TSS_mg_L",
    "Inorganic nitrogen (nitrate and nitrite)": "NO3_mg_L",
    "Soluble Reactive Phosphorus (SRP)": "OrthoP_mg_L",
}

# Regex for below-detection-limit strings like "<0.030", "< 0.05", "<MDL"
_BELOW_DETECTION_RE = re.compile(r"^\s*<")


# ============================================================================
# Main loader class
# ============================================================================


class WQObservationLoader:
    """Multi-format water quality observation loader.

    Reads water quality CSV files from several common agency/project
    formats and normalises them into a single wide-format DataFrame with
    concentrations in mg/L and canonical column names.

    Supported formats:

    * **adeq** -- Arkansas Department of Environmental Quality grab-sample
      exports (276-column CSV with ``DateSampled`` / ``StationID``).
    * **obsfiles** -- Pre-processed OBSfiles CSV with columns
      ``StationID, Date, TN(kg/m3), TP(kg/m3), TSS(ton/m3), Year, Month, Day``.
    * **awrc** -- AWRC / EPA STORET / Water Quality Portal long-format CSV
      (one row per parameter per sample, pivoted to wide format).
    * **generic** -- Any CSV with a user-supplied ``column_mapping`` dict.

    Example::

        df = WQObservationLoader.load("adeq_data.csv", format="adeq",
                                       station_id="ILL0001")
    """

    # Expose canonical column mapping as a class attribute for introspection.
    CANONICAL_COLUMNS = CANONICAL_COLUMNS

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    @classmethod
    def load(
        cls,
        filepath: Union[str, Path],
        format: str = "auto",
        station_id: Optional[str] = None,
        column_mapping: Optional[Dict[str, str]] = None,
    ) -> pd.DataFrame:
        """Load water quality observations from *filepath*.

        Parameters
        ----------
        filepath : str or Path
            Path to the data file (CSV).
        format : str
            One of ``"auto"``, ``"adeq"``, ``"obsfiles"``, ``"awrc"``,
            ``"generic"``.  When ``"auto"`` the format is guessed from
            the file header.
        station_id : str, optional
            If given, only rows matching this station identifier are
            returned.
        column_mapping : dict, optional
            Mapping from file column names to canonical column names.
            Required when *format* is ``"generic"``.

        Returns
        -------
        pandas.DataFrame
            Standardized DataFrame sorted by ``date`` with canonical
            concentration columns in mg/L.  Missing species are ``NaN``.
        """
        filepath = Path(filepath)
        if not filepath.exists():
            raise FileNotFoundError(f"File not found: {filepath}")

        if format == "auto":
            format = cls._detect_format(filepath)
            logger.info("Auto-detected format: %s", format)

        loaders = {
            "adeq": cls._load_adeq,
            "obsfiles": cls._load_obsfiles,
            "awrc": cls._load_awrc,
            "generic": cls._load_generic,
        }

        if format not in loaders:
            raise ValueError(
                f"Unknown format '{format}'. "
                f"Expected one of: {', '.join(loaders)}"
            )

        if format == "generic":
            df = cls._load_generic(filepath, column_mapping=column_mapping)
        elif format in ("adeq", "obsfiles", "awrc"):
            df = loaders[format](filepath, station_id=station_id)
        else:
            df = loaders[format](filepath)

        return cls._finalize(df)

    # ------------------------------------------------------------------
    # Format auto-detection
    # ------------------------------------------------------------------

    @classmethod
    def _detect_format(cls, filepath: Path) -> str:
        """Auto-detect the file format by inspecting the header row.

        Reads only the first line (header) of the CSV and checks for
        signature column names unique to each format.

        Returns
        -------
        str
            One of ``"adeq"``, ``"obsfiles"``, ``"awrc"``, ``"generic"``.
        """
        try:
            with open(filepath, "r", encoding="utf-8", errors="replace") as fh:
                header_line = fh.readline()
        except Exception as exc:
            logger.warning("Could not read header for format detection: %s", exc)
            return "generic"

        header_lower = header_line.lower()

        # ADEQ: look for "datesampled" and "stationid"
        if "datesampled" in header_lower and "stationid" in header_lower:
            return "adeq"

        # OBSfiles: look for "tn(kg/m3)" or "tp(kg/m3)"
        if "tn(kg/m3)" in header_lower or "tp(kg/m3)" in header_lower:
            return "obsfiles"

        # AWRC / WQP: look for "characteristicname" and "activitystartdate"
        if "characteristicname" in header_lower and "activitystartdate" in header_lower:
            return "awrc"

        logger.warning(
            "Could not auto-detect WQ file format for '%s'; "
            "falling back to 'generic'.",
            filepath.name,
        )
        return "generic"

    # ------------------------------------------------------------------
    # ADEQ format loader
    # ------------------------------------------------------------------

    @classmethod
    def _load_adeq(
        cls,
        filepath: Path,
        station_id: Optional[str] = None,
    ) -> pd.DataFrame:
        """Load ADEQ CSV format.

        ADEQ files are wide-format CSVs with ~276 columns.  The date
        column is ``DateSampled`` (format ``M/D/YYYY H:MM:SS AM/PM``).
        Stations are identified by ``StationID``.

        Values may contain below-detection-limit strings such as
        ``"<0.030"`` which are converted to ``NaN``.
        """
        # Read only the columns we need to avoid wasting memory on the
        # remaining ~270 columns.  First pass: get all column names.
        try:
            all_cols = pd.read_csv(filepath, nrows=0, encoding="utf-8").columns.tolist()
        except UnicodeDecodeError:
            all_cols = pd.read_csv(filepath, nrows=0, encoding="latin-1").columns.tolist()

        use_cols = ["DateSampled", "StationID"]
        adeq_cols_found: Dict[str, str] = {}
        for adeq_name, canon_name in _ADEQ_COLUMN_MAP.items():
            if adeq_name in all_cols:
                use_cols.append(adeq_name)
                adeq_cols_found[adeq_name] = canon_name
            else:
                logger.debug("ADEQ column '%s' not found in file.", adeq_name)

        missing_required = {"DateSampled", "StationID"} - set(all_cols)
        if missing_required:
            raise ValueError(
                f"ADEQ file is missing required columns: {missing_required}"
            )

        try:
            raw = pd.read_csv(
                filepath,
                usecols=use_cols,
                encoding="utf-8",
                low_memory=False,
            )
        except UnicodeDecodeError:
            raw = pd.read_csv(
                filepath,
                usecols=use_cols,
                encoding="latin-1",
                low_memory=False,
            )

        # Filter by station
        if station_id is not None:
            raw = raw[raw["StationID"].astype(str).str.strip() == str(station_id)]
            if raw.empty:
                logger.warning(
                    "No rows found for station_id='%s' in ADEQ file.", station_id
                )

        # Parse dates
        raw["date"] = pd.to_datetime(
            raw["DateSampled"], format="mixed", dayfirst=False, errors="coerce"
        )
        n_bad_dates = raw["date"].isna().sum() - raw["DateSampled"].isna().sum()
        if n_bad_dates > 0:
            logger.warning("%d date(s) could not be parsed in ADEQ file.", n_bad_dates)

        # Build output DataFrame
        df = pd.DataFrame({"date": raw["date"]})

        for adeq_name, canon_name in adeq_cols_found.items():
            series = raw[adeq_name].copy()
            # Replace below-detection-limit strings with NaN
            if series.dtype == object:
                mask = series.astype(str).apply(
                    lambda v: bool(_BELOW_DETECTION_RE.match(str(v)))
                )
                series[mask] = np.nan
            df[canon_name] = pd.to_numeric(series, errors="coerce")

        return df

    # ------------------------------------------------------------------
    # OBSfiles format loader
    # ------------------------------------------------------------------

    @classmethod
    def _load_obsfiles(
        cls,
        filepath: Path,
        station_id: Optional[str] = None,
    ) -> pd.DataFrame:
        """Load pre-processed OBSfiles CSV format.

        Expected columns::

            StationID, Date, TN(kg/m3), TP(kg/m3), TSS(ton/m3),
            Year, Month, Day

        Unit conversions applied:

        * TN/TP: kg/m3 -> mg/L  (multiply by 1000, since
          1 kg/m3 = 1 g/L = 1000 mg/L).
        * TSS: ton/m3 -> mg/L  (multiply by 1e6, since
          1 ton = 1000 kg, so 1 ton/m3 = 1000 kg/m3 = 1e6 mg/L).
        """
        try:
            raw = pd.read_csv(filepath, encoding="utf-8", low_memory=False)
        except UnicodeDecodeError:
            raw = pd.read_csv(filepath, encoding="latin-1", low_memory=False)

        # Normalise column names (strip whitespace)
        raw.columns = [c.strip() for c in raw.columns]

        # Filter by station
        if station_id is not None and "StationID" in raw.columns:
            raw = raw[raw["StationID"].astype(str).str.strip() == str(station_id)]
            if raw.empty:
                logger.warning(
                    "No rows found for station_id='%s' in OBSfiles.", station_id
                )

        # Parse dates -- prefer "Date" column, fall back to Year/Month/Day
        if "Date" in raw.columns:
            date_series = pd.to_datetime(
                raw["Date"], format="mixed", dayfirst=False, errors="coerce"
            )
        elif {"Year", "Month", "Day"}.issubset(raw.columns):
            date_series = pd.to_datetime(
                raw[["Year", "Month", "Day"]].rename(
                    columns={"Year": "year", "Month": "month", "Day": "day"}
                ),
                errors="coerce",
            )
        else:
            raise ValueError(
                "OBSfiles CSV must have either a 'Date' column or "
                "'Year', 'Month', 'Day' columns."
            )

        df = pd.DataFrame({"date": date_series})

        # Map OBSfiles columns -> canonical columns with unit conversion
        obsfiles_map = {
            "TN(kg/m3)": ("TN_mg_L", 1000.0),
            "TP(kg/m3)": ("TP_mg_L", 1000.0),
            "TSS(ton/m3)": ("TSS_mg_L", 1e6),
        }

        for obs_col, (canon_col, factor) in obsfiles_map.items():
            if obs_col in raw.columns:
                values = pd.to_numeric(raw[obs_col], errors="coerce")
                df[canon_col] = values * factor
            else:
                logger.debug("OBSfiles column '%s' not present.", obs_col)

        return df

    # ------------------------------------------------------------------
    # AWRC / WQP STORET long-format loader
    # ------------------------------------------------------------------

    @classmethod
    def _load_awrc(
        cls,
        filepath: Path,
        station_id: Optional[str] = None,
    ) -> pd.DataFrame:
        """Load AWRC / WQP / STORET long-format CSV.

        Each row represents a single parameter measurement.  Key
        columns are ``ActivityStartDate`` (YYYY-MM-DD),
        ``MonitoringLocationIdentifier``, ``CharacteristicName``, and
        ``ResultMeasureValue``.

        The long-format data is pivoted to a wide DataFrame matching the
        canonical column layout.
        """
        try:
            raw = pd.read_csv(filepath, encoding="utf-8", low_memory=False)
        except UnicodeDecodeError:
            raw = pd.read_csv(filepath, encoding="latin-1", low_memory=False)

        # Normalise column names (strip whitespace)
        raw.columns = [c.strip() for c in raw.columns]

        required = {"ActivityStartDate", "CharacteristicName", "ResultMeasureValue"}
        missing = required - set(raw.columns)
        if missing:
            raise ValueError(
                f"AWRC file is missing required columns: {missing}"
            )

        # Filter by station
        station_col = None
        for candidate in ("MonitoringLocationIdentifier", "MonitoringLocationID"):
            if candidate in raw.columns:
                station_col = candidate
                break

        if station_id is not None:
            if station_col is None:
                logger.warning(
                    "station_id='%s' was requested but no station column "
                    "found in AWRC file; returning all rows.",
                    station_id,
                )
            else:
                raw = raw[raw[station_col].astype(str).str.strip() == str(station_id)]
                if raw.empty:
                    logger.warning(
                        "No rows found for station_id='%s' in AWRC file.",
                        station_id,
                    )

        # Parse dates
        raw["date"] = pd.to_datetime(raw["ActivityStartDate"], errors="coerce")

        # Map CharacteristicName -> canonical column name
        raw["canon_col"] = raw["CharacteristicName"].map(_AWRC_CHARACTERISTIC_MAP)
        mapped = raw.dropna(subset=["canon_col"]).copy()

        if mapped.empty:
            logger.warning(
                "No recognised CharacteristicName values found in AWRC file. "
                "Known names: %s",
                list(_AWRC_CHARACTERISTIC_MAP.keys()),
            )
            return pd.DataFrame(columns=["date"] + list(CANONICAL_COLUMNS.keys()))

        # Convert result values to numeric (handle "<" strings)
        values = mapped["ResultMeasureValue"].copy()
        if values.dtype == object:
            bdl_mask = values.astype(str).apply(
                lambda v: bool(_BELOW_DETECTION_RE.match(str(v)))
            )
            values[bdl_mask] = np.nan
        mapped["value"] = pd.to_numeric(values, errors="coerce")

        # Pivot: rows = date, columns = canonical column name
        # If multiple values exist for the same date+parameter, take the
        # mean (duplicate grab samples on the same day).
        pivoted = mapped.pivot_table(
            index="date",
            columns="canon_col",
            values="value",
            aggfunc="mean",
        ).reset_index()

        # Flatten column names (pivot_table may set a MultiIndex)
        pivoted.columns.name = None

        return pivoted

    # ------------------------------------------------------------------
    # Generic CSV loader
    # ------------------------------------------------------------------

    @classmethod
    def _load_generic(
        cls,
        filepath: Path,
        column_mapping: Optional[Dict[str, str]] = None,
    ) -> pd.DataFrame:
        """Load a generic CSV file with an optional column mapping.

        Parameters
        ----------
        filepath : Path
            Path to the CSV file.
        column_mapping : dict, optional
            Maps file column names to canonical names (e.g.
            ``{"TotalN": "TN_mg_L", "Date": "date"}``).  The mapping
            **must** include a ``"date"`` target.  If ``None``, the
            loader attempts to auto-detect a date column and keeps any
            columns whose names match canonical names exactly.
        """
        try:
            raw = pd.read_csv(filepath, encoding="utf-8", low_memory=False)
        except UnicodeDecodeError:
            raw = pd.read_csv(filepath, encoding="latin-1", low_memory=False)

        raw.columns = [c.strip() for c in raw.columns]

        if column_mapping is not None:
            # Validate the mapping
            reverse_map = {v: k for k, v in column_mapping.items()}
            if "date" not in reverse_map:
                raise ValueError(
                    "column_mapping must include a mapping to 'date' "
                    "(e.g. {'DateCol': 'date'})."
                )

            rename = {}
            for file_col, canon_col in column_mapping.items():
                if file_col in raw.columns:
                    rename[file_col] = canon_col
                else:
                    logger.warning(
                        "Column '%s' from column_mapping not found in file.",
                        file_col,
                    )

            raw = raw.rename(columns=rename)
        else:
            # Auto-detect date column
            date_col = cls._find_date_column(raw)
            if date_col is not None and date_col != "date":
                raw = raw.rename(columns={date_col: "date"})

        if "date" not in raw.columns:
            raise ValueError(
                "Could not identify a date column. Provide a "
                "column_mapping with a 'date' target."
            )

        # Parse dates
        raw["date"] = pd.to_datetime(raw["date"], format="mixed", dayfirst=False, errors="coerce")

        # Keep only date + canonical columns that are present
        keep = ["date"] + [c for c in CANONICAL_COLUMNS if c in raw.columns]
        df = raw[keep].copy()

        # Coerce concentration columns to numeric
        for col in keep:
            if col == "date":
                continue
            if df[col].dtype == object:
                bdl_mask = df[col].astype(str).apply(
                    lambda v: bool(_BELOW_DETECTION_RE.match(str(v)))
                )
                df.loc[bdl_mask, col] = np.nan
            df[col] = pd.to_numeric(df[col], errors="coerce")

        return df

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    @classmethod
    def _finalize(cls, df: pd.DataFrame) -> pd.DataFrame:
        """Normalise and validate the output DataFrame.

        * Ensures ``date`` is datetime, normalised to midnight.
        * Adds any missing canonical columns as all-NaN.
        * Drops rows without a valid date.
        * Sorts by date.
        """
        if df.empty:
            # Return an empty DataFrame with the correct schema
            cols = ["date"] + list(CANONICAL_COLUMNS.keys())
            return pd.DataFrame(columns=cols)

        # Ensure date column exists and is datetime
        if "date" not in df.columns:
            raise ValueError("Loader did not produce a 'date' column.")

        df = df.copy()
        df["date"] = pd.to_datetime(df["date"], errors="coerce")

        # Drop rows with unparseable dates
        n_before = len(df)
        df = df.dropna(subset=["date"])
        n_dropped = n_before - len(df)
        if n_dropped > 0:
            logger.warning(
                "Dropped %d row(s) with unparseable dates.", n_dropped
            )

        # Normalize to midnight
        df["date"] = df["date"].dt.normalize()

        # Ensure all canonical columns exist (fill with NaN if missing)
        for canon_col in CANONICAL_COLUMNS:
            if canon_col not in df.columns:
                df[canon_col] = np.nan

        # Reorder columns: date first, then canonical in defined order
        ordered_cols = ["date"] + list(CANONICAL_COLUMNS.keys())
        df = df[ordered_cols]

        # Sort and reset index
        df = df.sort_values("date").reset_index(drop=True)

        return df

    @staticmethod
    def _find_date_column(df: pd.DataFrame) -> Optional[str]:
        """Heuristically identify the date column in *df*.

        Checks column names first, then tries parsing object columns.
        """
        # Name-based detection (case-insensitive)
        priority_names = [
            "date", "datetime", "datesampled", "activitystartdate",
            "sample_date", "sampledate", "timestamp", "time", "dt",
        ]
        col_lower_map = {c.lower().strip(): c for c in df.columns}
        for name in priority_names:
            if name in col_lower_map:
                return col_lower_map[name]

        # Substring match
        for col in df.columns:
            if "date" in col.lower() or "time" in col.lower():
                return col

        # Content-based detection: try parsing the first few values
        for col in df.columns:
            if df[col].dtype == object:
                try:
                    pd.to_datetime(df[col].dropna().head(5))
                    return col
                except Exception:
                    continue

        return None


# ============================================================================
# Helper functions (module-level)
# ============================================================================


def calculate_total_nitrogen(df: pd.DataFrame) -> pd.DataFrame:
    """Fill missing TN from available nitrogen species.

    Updates ``TN_mg_L`` **in-place** (only for rows where it is NaN)
    using the following priority:

    1. Use ``TN_mg_L`` directly where already available.
    2. ``TN = TKN_mg_L + NO3_mg_L``  (TKN includes OrgN + NH4).
    3. ``TN = NH4_mg_L + NO3_mg_L + OrgN_mg_L``.

    Parameters
    ----------
    df : pandas.DataFrame
        Must contain a ``TN_mg_L`` column (may be all NaN).

    Returns
    -------
    pandas.DataFrame
        The same DataFrame, modified in-place for convenience.
    """
    if "TN_mg_L" not in df.columns:
        df["TN_mg_L"] = np.nan

    missing = df["TN_mg_L"].isna()

    # Priority 2: TKN + NO3
    if "TKN_mg_L" in df.columns and "NO3_mg_L" in df.columns:
        can_calc = missing & df["TKN_mg_L"].notna() & df["NO3_mg_L"].notna()
        df.loc[can_calc, "TN_mg_L"] = (
            df.loc[can_calc, "TKN_mg_L"] + df.loc[can_calc, "NO3_mg_L"]
        )
        missing = df["TN_mg_L"].isna()

    # Priority 3: NH4 + NO3 + OrgN
    if (
        "NH4_mg_L" in df.columns
        and "NO3_mg_L" in df.columns
        and "OrgN_mg_L" in df.columns
    ):
        can_calc = (
            missing
            & df["NH4_mg_L"].notna()
            & df["NO3_mg_L"].notna()
            & df["OrgN_mg_L"].notna()
        )
        df.loc[can_calc, "TN_mg_L"] = (
            df.loc[can_calc, "NH4_mg_L"]
            + df.loc[can_calc, "NO3_mg_L"]
            + df.loc[can_calc, "OrgN_mg_L"]
        )

    return df


def calculate_total_phosphorus(df: pd.DataFrame) -> pd.DataFrame:
    """Fill missing TP from available phosphorus species.

    Updates ``TP_mg_L`` **in-place** (only for rows where it is NaN)
    using the following priority:

    1. Use ``TP_mg_L`` directly where already available.
    2. ``TP = OrthoP_mg_L + OrgP_mg_L``  (if ``OrgP_mg_L`` exists).

    Parameters
    ----------
    df : pandas.DataFrame
        Must contain a ``TP_mg_L`` column (may be all NaN).

    Returns
    -------
    pandas.DataFrame
        The same DataFrame, modified in-place for convenience.
    """
    if "TP_mg_L" not in df.columns:
        df["TP_mg_L"] = np.nan

    missing = df["TP_mg_L"].isna()

    # Priority 2: OrthoP + OrgP
    if "OrthoP_mg_L" in df.columns and "OrgP_mg_L" in df.columns:
        can_calc = (
            missing
            & df["OrthoP_mg_L"].notna()
            & df["OrgP_mg_L"].notna()
        )
        df.loc[can_calc, "TP_mg_L"] = (
            df.loc[can_calc, "OrthoP_mg_L"] + df.loc[can_calc, "OrgP_mg_L"]
        )

    return df


def get_available_stations(
    filepath: Union[str, Path],
    format: str = "auto",
) -> List[str]:
    """Return a sorted list of unique station IDs in the file.

    Parameters
    ----------
    filepath : str or Path
        Path to the water quality data file.
    format : str
        File format (``"auto"``, ``"adeq"``, ``"obsfiles"``, ``"awrc"``).

    Returns
    -------
    list of str
        Unique station identifiers found in the file.
    """
    filepath = Path(filepath)
    if not filepath.exists():
        raise FileNotFoundError(f"File not found: {filepath}")

    if format == "auto":
        format = WQObservationLoader._detect_format(filepath)

    # Determine which column holds the station identifier
    station_col_candidates = {
        "adeq": ["StationID"],
        "obsfiles": ["StationID"],
        "awrc": ["MonitoringLocationIdentifier", "MonitoringLocationID"],
        "generic": ["StationID", "station_id", "Station", "station",
                     "MonitoringLocationIdentifier"],
    }

    candidates = station_col_candidates.get(format, ["StationID"])

    try:
        header_df = pd.read_csv(filepath, nrows=0, encoding="utf-8")
    except UnicodeDecodeError:
        header_df = pd.read_csv(filepath, nrows=0, encoding="latin-1")

    file_cols = [c.strip() for c in header_df.columns]

    station_col = None
    for cand in candidates:
        if cand in file_cols:
            station_col = cand
            break

    if station_col is None:
        logger.warning(
            "No station column found in '%s'. Tried: %s",
            filepath.name,
            candidates,
        )
        return []

    try:
        col_data = pd.read_csv(
            filepath,
            usecols=[station_col],
            encoding="utf-8",
            low_memory=False,
        )
    except UnicodeDecodeError:
        col_data = pd.read_csv(
            filepath,
            usecols=[station_col],
            encoding="latin-1",
            low_memory=False,
        )

    stations = col_data[station_col].dropna().astype(str).str.strip().unique()
    return sorted(stations)
