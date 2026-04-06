"""
Multi-format observation data loader.

Supports CSV, Excel, tab-delimited, and space-delimited files
with automatic delimiter and date format detection.
"""

import csv
import io
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

import numpy as np
import pandas as pd


class ObservationLoader:
    """
    Load observation data from multiple file formats.

    Supports: CSV, Excel (.xlsx/.xls), tab-delimited (.txt/.tsv),
    space-delimited, and USGS RDB format.

    Example:
        >>> loader = ObservationLoader()
        >>> df = loader.load("streamflow.csv")
        >>> df = loader.load("data.xlsx", date_column="Date", value_column="Flow")
    """

    SUPPORTED_EXTENSIONS = {
        ".csv": "Comma-separated values",
        ".xlsx": "Excel workbook",
        ".xls": "Excel workbook (legacy)",
        ".txt": "Text file (auto-detect delimiter)",
        ".tsv": "Tab-separated values",
        ".rdb": "USGS RDB format",
        ".dat": "Data file (auto-detect delimiter)",
    }

    @classmethod
    def load(
        cls,
        filepath: Union[str, Path],
        delimiter: Optional[str] = None,
        date_column: Optional[str] = None,
        value_column: Optional[str] = None,
        date_format: Optional[str] = None,
        skip_rows: int = 0,
        sheet_name: Union[str, int] = 0,
    ) -> pd.DataFrame:
        """
        Load observation data from any supported format.

        Auto-detects delimiter and date format when not specified.

        Args:
            filepath: Path to the data file.
            delimiter: Column delimiter. Auto-detected if None.
            date_column: Name of the date column. Auto-detected if None.
            value_column: Name of the value column. If None, keeps all numeric cols.
            date_format: Date parsing format. Auto-detected if None.
            skip_rows: Number of header rows to skip.
            sheet_name: Excel sheet name or index (only for .xlsx/.xls).

        Returns:
            DataFrame with parsed data.
        """
        filepath = Path(filepath)
        ext = filepath.suffix.lower()

        if ext in (".xlsx", ".xls"):
            df = cls._load_excel(filepath, sheet_name, skip_rows)
        elif ext == ".rdb" or cls._is_usgs_rdb_file(filepath):
            df = cls._load_rdb(filepath)
        else:
            if delimiter is None:
                delimiter = cls.detect_delimiter(filepath, skip_rows)
            df = cls._load_text(filepath, delimiter, skip_rows)

        if df.empty:
            return df

        # Drop unnamed index columns
        unnamed = [c for c in df.columns if str(c).startswith("Unnamed")]
        if unnamed:
            df = df.drop(columns=unnamed)

        # Combine separate Year/Month/Day columns into a single 'date' column
        df = cls.combine_ymd_columns(df)

        # Auto-detect date column if not specified
        if date_column is None:
            date_column = cls.detect_date_column(df)

        # Parse dates if a date column was found (skip if already datetime)
        if date_column and date_column in df.columns:
            if not pd.api.types.is_datetime64_any_dtype(df[date_column]):
                if date_format is None:
                    date_format = cls.detect_date_format(df[date_column])
                try:
                    if date_format and date_format != "auto":
                        df[date_column] = pd.to_datetime(df[date_column], format=date_format)
                    else:
                        df[date_column] = pd.to_datetime(df[date_column])
                except Exception:
                    pass  # Leave dates as-is if parsing fails

        # Filter to specific value column if requested
        if value_column and value_column in df.columns:
            keep_cols = [date_column, value_column] if date_column else [value_column]
            keep_cols = [c for c in keep_cols if c in df.columns]
            df = df[keep_cols]

        return df

    @classmethod
    def load_from_buffer(
        cls,
        buffer,
        filename: str,
        delimiter: Optional[str] = None,
        **kwargs,
    ) -> pd.DataFrame:
        """
        Load data from a file-like buffer (e.g., Streamlit uploaded file).

        Args:
            buffer: File-like object with .read() method.
            filename: Original filename (used for format detection).
            delimiter: Column delimiter.
            **kwargs: Additional arguments passed to load().
        """
        ext = Path(filename).suffix.lower()

        if ext in (".xlsx", ".xls"):
            return pd.read_excel(buffer, **{k: v for k, v in kwargs.items()
                                             if k in ("sheet_name", "skip_rows")})

        content = buffer.read()
        if isinstance(content, bytes):
            content = content.decode("utf-8", errors="replace")

        # Detect USGS RDB format from content (handles files with any extension)
        if cls._is_usgs_rdb_content(content):
            return cls._load_rdb_from_text(content)

        if delimiter is None:
            delimiter = cls._detect_delimiter_from_text(content)

        try:
            df = pd.read_csv(
                io.StringIO(content),
                sep=delimiter,
                skipinitialspace=True,
            )
            # Drop unnamed index columns (created when CSV was saved with
            # df.to_csv() without index=False).
            unnamed = [c for c in df.columns if str(c).startswith("Unnamed")]
            if unnamed:
                df = df.drop(columns=unnamed)
            return cls.combine_ymd_columns(df)
        except Exception:
            return pd.DataFrame()

    @staticmethod
    def detect_delimiter(
        filepath: Union[str, Path],
        skip_rows: int = 0,
    ) -> str:
        """
        Auto-detect the delimiter of a text file.

        Args:
            filepath: Path to the file.
            skip_rows: Number of rows to skip before detecting.

        Returns:
            Detected delimiter character.
        """
        with open(filepath, "r", errors="replace") as f:
            # Skip initial rows
            for _ in range(skip_rows):
                f.readline()
            # Read sample lines (skip comment lines starting with #)
            sample_lines = []
            for line in f:
                if line.strip() and not line.startswith("#"):
                    sample_lines.append(line)
                    if len(sample_lines) >= 10:
                        break

        sample = "\n".join(sample_lines)
        return ObservationLoader._detect_delimiter_from_text(sample)

    @staticmethod
    def _detect_delimiter_from_text(text: str) -> str:
        """Detect delimiter from a text sample."""
        try:
            dialect = csv.Sniffer().sniff(text, delimiters=",\t;|")
            return dialect.delimiter
        except csv.Error:
            pass

        # Manual heuristic: count delimiters in first data line
        lines = [l for l in text.split("\n") if l.strip() and not l.startswith("#")]
        if not lines:
            return ","

        line = lines[0]
        counts = {
            "\t": line.count("\t"),
            ",": line.count(","),
            ";": line.count(";"),
            "|": line.count("|"),
        }

        # Check for multiple-space delimiter
        import re
        space_count = len(re.findall(r"\s{2,}", line))
        if space_count > 0:
            counts["\\s+"] = space_count

        best = max(counts, key=counts.get)
        if counts[best] == 0:
            return ","  # Default to comma
        return best

    @classmethod
    def combine_ymd_columns(cls, df: pd.DataFrame) -> pd.DataFrame:
        """
        Detect separate Year/Month/Day columns and combine into a single 'date' column.

        Common in SWAT observation files where dates are stored as three integer columns.

        Args:
            df: DataFrame that may contain Year, Month, Day columns.

        Returns:
            DataFrame with a 'date' column inserted at position 0 if YMD columns were found.
        """
        col_lower = {c: c.lower().strip() for c in df.columns}
        year_col = next((c for c, low in col_lower.items() if low == "year"), None)
        month_col = next((c for c, low in col_lower.items() if low == "month"), None)
        day_col = next((c for c, low in col_lower.items() if low == "day"), None)

        if year_col and month_col and day_col:
            try:
                df = df.copy()
                df.insert(0, "date", pd.to_datetime(
                    df[[year_col, month_col, day_col]].rename(
                        columns={year_col: "year", month_col: "month", day_col: "day"}
                    )
                ))
            except Exception:
                pass

        return df

    @staticmethod
    def detect_date_column(df: pd.DataFrame) -> Optional[str]:
        """
        Find the column most likely to contain dates.

        Checks column names first, then content patterns.

        Args:
            df: DataFrame to analyze.

        Returns:
            Column name or None if no date column detected.
        """
        # Check column names — iterate by priority so "date" matches before "day"
        date_names = ["date", "datetime", "time", "timestamp",
                      "dt", "dates", "observation_date", "day"]
        col_lookup = {c.lower().strip(): c for c in df.columns}
        for name in date_names:
            if name in col_lookup:
                return col_lookup[name]

        # Check for columns with 'date' in the name
        for col in df.columns:
            if "date" in col.lower() or "time" in col.lower():
                return col

        # Try parsing first non-numeric column as date
        for col in df.columns:
            if df[col].dtype == "object":
                try:
                    pd.to_datetime(df[col].head(5))
                    return col
                except Exception:
                    continue

        return None

    @staticmethod
    def detect_date_format(date_series: pd.Series) -> Optional[str]:
        """
        Detect the date format from a sample of values.

        Args:
            date_series: Series containing date strings.

        Returns:
            Format string or None for auto-detection.
        """
        common_formats = [
            "%Y-%m-%d",
            "%m/%d/%Y",
            "%d/%m/%Y",
            "%Y/%m/%d",
            "%Y-%m-%d %H:%M:%S",
            "%m/%d/%Y %H:%M",
            "%d-%m-%Y",
            "%Y%m%d",
            "%m-%d-%Y",
        ]

        sample = date_series.dropna().head(10).astype(str)
        if len(sample) == 0:
            return None

        best_format = None
        best_count = 0

        for fmt in common_formats:
            count = 0
            for val in sample:
                try:
                    pd.to_datetime(val.strip(), format=fmt)
                    count += 1
                except Exception:
                    continue
            if count > best_count:
                best_count = count
                best_format = fmt

        # Only return format if it matches most samples
        if best_count >= len(sample) * 0.7:
            return best_format

        return None  # Use auto-detection

    # Column names that should never be treated as observation values.
    _INDEX_LIKE_NAMES = frozenset([
        "unnamed", "index", "id", "no", "row", "record",
        "fid", "objectid", "oid",
    ])

    @staticmethod
    def detect_value_columns(df: pd.DataFrame) -> List[str]:
        """
        Find columns containing numeric observation data.

        Excludes date columns, low-cardinality ID columns,
        unnamed index columns, and monotonically increasing row-number columns.

        Args:
            df: DataFrame to analyze.

        Returns:
            List of numeric column names.
        """
        date_col = ObservationLoader.detect_date_column(df)
        numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()

        result = []
        for col in numeric_cols:
            if col == date_col:
                continue

            col_clean = str(col).lower().strip()

            # Skip unnamed pandas index columns (e.g. "Unnamed: 0")
            if col_clean.startswith("unnamed"):
                continue

            # Skip common index / ID column names
            if col_clean in ObservationLoader._INDEX_LIKE_NAMES:
                continue

            # Skip likely ID columns (low cardinality integers)
            if df[col].dtype in ("int64", "int32"):
                if df[col].nunique() < max(5, len(df) * 0.01):
                    continue

            # Skip columns that look like row numbers (0..N-1 or 1..N)
            if (
                len(df) > 50
                and df[col].dtype in ("int64", "int32", "float64")
                and df[col].is_monotonic_increasing
            ):
                vals = df[col].dropna()
                if len(vals) == len(df) and (
                    (vals.iloc[0] == 0 and vals.iloc[-1] == len(df) - 1)
                    or (vals.iloc[0] == 1 and vals.iloc[-1] == len(df))
                ):
                    continue

            result.append(col)

        return result

    # -------------------------------------------------------------------------
    # Private loaders
    # -------------------------------------------------------------------------

    @staticmethod
    def _load_text(
        filepath: Path,
        delimiter: str,
        skip_rows: int,
    ) -> pd.DataFrame:
        """Load a text file with the given delimiter."""
        try:
            sep = delimiter if delimiter != "\\s+" else r"\s+"
            return pd.read_csv(
                filepath,
                sep=sep,
                skiprows=skip_rows,
                skipinitialspace=True,
                comment="#",
                engine="python" if sep == r"\s+" else "c",
            )
        except Exception:
            return pd.DataFrame()

    @staticmethod
    def _load_excel(
        filepath: Path,
        sheet_name: Union[str, int] = 0,
        skip_rows: int = 0,
    ) -> pd.DataFrame:
        """Load an Excel file."""
        try:
            return pd.read_excel(
                filepath,
                sheet_name=sheet_name,
                skiprows=skip_rows,
            )
        except ImportError:
            raise ImportError(
                "openpyxl is required for Excel files. "
                "Install with: pip install swat-dg[data]"
            )
        except Exception:
            return pd.DataFrame()

    @staticmethod
    def _is_usgs_rdb_file(filepath: Union[str, Path]) -> bool:
        """Check if a file is USGS RDB format regardless of extension.

        Detects files that start with ``#`` comment lines followed by a
        tab-delimited header containing ``agency_cd``.
        """
        try:
            with open(filepath, "r", errors="replace") as f:
                for line in f:
                    if line.startswith("#"):
                        continue
                    # First non-comment line is the header
                    return "agency_cd" in line and "\t" in line
        except Exception:
            pass
        return False

    @staticmethod
    def _is_usgs_rdb_content(text: str) -> bool:
        """Check if text content is USGS RDB format."""
        for line in text.split("\n"):
            if line.startswith("#"):
                continue
            return "agency_cd" in line and "\t" in line
        return False

    @staticmethod
    def _load_rdb(filepath: Path) -> pd.DataFrame:
        """
        Load a USGS RDB (tab-delimited) file.

        RDB files have:
        - Comment lines starting with #
        - A header line with column names
        - A format definition line (e.g., 5s 15s 10n)
        - Data lines
        """
        lines = []
        header = None

        with open(filepath, "r") as f:
            for line in f:
                # Skip comment lines
                if line.startswith("#"):
                    continue
                if header is None:
                    # First non-comment line is the header
                    header = line.strip().split("\t")
                    continue
                # Skip format definition line (contains only 's', 'n', 'd' types)
                stripped = line.strip()
                parts = stripped.split("\t")
                if all(p.strip().rstrip("snd").isdigit() or p.strip() in ("s", "n", "d")
                       for p in parts if p.strip()):
                    continue
                lines.append(stripped)

        if header is None:
            return pd.DataFrame()

        data = [line.split("\t") for line in lines]
        df = pd.DataFrame(data, columns=header[:len(data[0])] if data else header)

        # Convert numeric columns
        for col in df.columns:
            try:
                df[col] = pd.to_numeric(df[col])
            except (ValueError, TypeError):
                pass

        return df

    @classmethod
    def _load_rdb_from_text(cls, text: str) -> pd.DataFrame:
        """Load USGS RDB data from a text string (for uploaded buffers)."""
        lines = []
        header = None

        for line in text.split("\n"):
            if line.startswith("#"):
                continue
            if header is None:
                header = line.strip().split("\t")
                continue
            stripped = line.strip()
            if not stripped:
                continue
            parts = stripped.split("\t")
            if all(p.strip().rstrip("snd").isdigit() or p.strip() in ("s", "n", "d")
                   for p in parts if p.strip()):
                continue
            lines.append(stripped)

        if header is None:
            return pd.DataFrame()

        data = [line.split("\t") for line in lines]
        df = pd.DataFrame(data, columns=header[:len(data[0])] if data else header)

        for col in df.columns:
            try:
                df[col] = pd.to_numeric(df[col])
            except (ValueError, TypeError):
                pass

        return df
