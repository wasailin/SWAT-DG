"""
USGS National Water Information System (NWIS) data loader.

Fetches daily values from the USGS NWIS web services and parses
downloaded RDB files.
"""

from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

import pandas as pd

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False


# USGS parameter codes mapped to SWAT output variables
PARAMETER_CODES = {
    "00060": {
        "name": "Streamflow",
        "units": "cfs",
        "swat_var": "FLOW_OUTcms",
        "description": "Discharge, cubic feet per second",
    },
    "00065": {
        "name": "Gage Height",
        "units": "ft",
        "swat_var": None,
        "description": "Gage height, feet",
    },
    "00010": {
        "name": "Water Temperature",
        "units": "deg C",
        "swat_var": "WTMPdegc",
        "description": "Temperature, water, degrees Celsius",
    },
    "00630": {
        "name": "Nitrate+Nitrite",
        "units": "mg/L",
        "swat_var": "NO3_OUTkg",
        "description": "Nitrate plus nitrite, mg/L as N",
    },
    "00671": {
        "name": "Orthophosphate",
        "units": "mg/L",
        "swat_var": "MINP_OUTkg",
        "description": "Orthophosphate, mg/L as P",
    },
    "80154": {
        "name": "Suspended Sediment",
        "units": "mg/L",
        "swat_var": "SEDCONCmg_L",
        "description": "Suspended sediment concentration, mg/L",
    },
    "00680": {
        "name": "Organic Carbon",
        "units": "mg/L",
        "swat_var": None,
        "description": "Organic carbon, mg/L",
    },
    "00665": {
        "name": "Total Phosphorus",
        "units": "mg/L",
        "swat_var": "TOT_Pkg",
        "description": "Phosphorus, total, mg/L as P",
    },
}


class NWISLoader:
    """
    Load data from USGS National Water Information System.

    Example:
        >>> loader = NWISLoader()
        >>> df = loader.fetch_daily_values("07196500", "00060",
        ...                                start_date="2010-01-01",
        ...                                end_date="2020-12-31")
    """

    BASE_URL = "https://waterservices.usgs.gov/nwis"

    @classmethod
    def fetch_daily_values(
        cls,
        site_number: str,
        parameter_code: str = "00060",
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> pd.DataFrame:
        """
        Fetch daily values from USGS NWIS web service.

        Args:
            site_number: USGS site number (e.g., "07196500").
            parameter_code: USGS parameter code (default: "00060" for streamflow).
            start_date: Start date as "YYYY-MM-DD".
            end_date: End date as "YYYY-MM-DD".

        Returns:
            DataFrame with columns: 'date', 'value', 'qualifiers'.
        """
        if not HAS_REQUESTS:
            raise ImportError(
                "requests is required for NWIS data fetching. "
                "Install with: pip install swat-dg[data]"
            )

        params = {
            "format": "rdb",
            "sites": site_number,
            "parameterCd": parameter_code,
            "statCd": "00003",  # Mean daily value
        }

        if start_date:
            params["startDT"] = start_date
        if end_date:
            params["endDT"] = end_date

        url = f"{cls.BASE_URL}/dv/"
        param_info = PARAMETER_CODES.get(parameter_code, {})
        param_name = param_info.get("name", parameter_code)
        print(f"[NWIS] Fetching {param_name} (code {parameter_code}) for site {site_number}")
        if start_date or end_date:
            print(f"[NWIS] Date range: {start_date or 'earliest'} to {end_date or 'latest'}")
        print(f"[NWIS] URL: {url}")

        response = requests.get(url, params=params, timeout=60)
        print(f"[NWIS] Response: HTTP {response.status_code} ({len(response.text):,} bytes)")
        response.raise_for_status()

        df = cls._parse_rdb_response(response.text, parameter_code)
        print(f"[NWIS] Parsed {len(df)} daily values")
        if not df.empty:
            print(f"[NWIS] Period: {df['date'].min()} to {df['date'].max()}")
        return df

    @classmethod
    def parse_rdb_file(cls, filepath: Union[str, Path]) -> pd.DataFrame:
        """
        Parse a downloaded USGS RDB file.

        Args:
            filepath: Path to the .rdb or .txt file.

        Returns:
            DataFrame with columns: 'date', 'value'.
        """
        with open(filepath, "r") as f:
            content = f.read()
        return cls._parse_rdb_response(content)

    @classmethod
    def search_sites(
        cls,
        state_code: Optional[str] = None,
        bounding_box: Optional[Tuple[float, float, float, float]] = None,
        parameter_code: str = "00060",
        site_type: str = "ST",
    ) -> pd.DataFrame:
        """
        Search for USGS monitoring sites.

        Args:
            state_code: Two-letter state code (e.g., "AR", "OK").
            bounding_box: (west_lon, south_lat, east_lon, north_lat).
            parameter_code: Filter by parameter code.
            site_type: Site type ("ST" for stream, "GW" for groundwater).

        Returns:
            DataFrame with columns: site_no, station_nm, dec_lat_va,
            dec_long_va, etc.
        """
        if not HAS_REQUESTS:
            raise ImportError("requests is required. Install with: pip install swat-dg[data]")

        params = {
            "format": "rdb",
            "parameterCd": parameter_code,
            "siteType": site_type,
            "siteStatus": "active",
            "hasDataTypeCd": "dv",
        }

        if state_code:
            params["stateCd"] = state_code
        elif bounding_box:
            params["bBox"] = ",".join(str(x) for x in bounding_box)
        else:
            raise ValueError("Provide either state_code or bounding_box")

        url = f"{cls.BASE_URL}/../site/"
        location = state_code or f"bbox({bounding_box})"
        print(f"[NWIS] Searching sites in {location} (param {parameter_code}, type {site_type})")
        print(f"[NWIS] URL: {url}")

        response = requests.get(url, params=params, timeout=60)
        print(f"[NWIS] Response: HTTP {response.status_code} ({len(response.text):,} bytes)")
        response.raise_for_status()

        df = cls._parse_site_response(response.text)
        print(f"[NWIS] Found {len(df)} sites")
        return df

    @staticmethod
    def get_parameter_info(code: str) -> Dict:
        """Get information about a USGS parameter code."""
        return PARAMETER_CODES.get(code, {
            "name": f"Parameter {code}",
            "units": "unknown",
            "swat_var": None,
            "description": f"USGS parameter code {code}",
        })

    @staticmethod
    def list_parameter_codes() -> Dict[str, Dict]:
        """List all known USGS parameter codes with their metadata."""
        return PARAMETER_CODES.copy()

    # -------------------------------------------------------------------------
    # Private parsers
    # -------------------------------------------------------------------------

    @staticmethod
    def _parse_rdb_response(text: str, parameter_code: str = None) -> pd.DataFrame:
        """Parse RDB-formatted text response into a DataFrame."""
        lines = text.strip().split("\n")

        # Skip comment lines (starting with #)
        data_lines = []
        header = None
        skip_format = True

        for line in lines:
            if line.startswith("#"):
                continue
            if header is None:
                header = line.strip().split("\t")
                continue
            if skip_format:
                # Skip the format definition line
                skip_format = False
                continue
            data_lines.append(line.strip().split("\t"))

        if header is None or not data_lines:
            return pd.DataFrame(columns=["date", "value"])

        df = pd.DataFrame(data_lines, columns=header[:len(data_lines[0])])

        # Find the value column (contains the parameter code)
        value_col = None
        for col in df.columns:
            if parameter_code and parameter_code in col:
                value_col = col
                break

        # Find date column
        date_col = None
        for col in df.columns:
            if "datetime" in col.lower() or "dt" in col.lower():
                date_col = col
                break

        if date_col is None:
            date_col = df.columns[2] if len(df.columns) > 2 else df.columns[0]

        if value_col is None:
            # Try to find any numeric column that's not the site number
            for col in df.columns:
                if col not in (date_col, "agency_cd", "site_no"):
                    try:
                        pd.to_numeric(df[col].head(5).replace("", pd.NA))
                        if "_cd" not in col:  # Skip qualifier columns
                            value_col = col
                            break
                    except (ValueError, TypeError):
                        continue

        if value_col is None:
            return pd.DataFrame(columns=["date", "value"])

        result = pd.DataFrame({
            "date": pd.to_datetime(df[date_col], errors="coerce"),
            "value": pd.to_numeric(df[value_col], errors="coerce"),
        })

        # Add qualifier column if available
        qual_col = f"{value_col}_cd" if f"{value_col}_cd" in df.columns else None
        if qual_col:
            result["qualifiers"] = df[qual_col].values

        # Add site info
        if "site_no" in df.columns:
            result["site_no"] = df["site_no"].values

        return result.dropna(subset=["date", "value"])

    @staticmethod
    def _parse_site_response(text: str) -> pd.DataFrame:
        """Parse site search RDB response."""
        lines = text.strip().split("\n")

        header = None
        data_lines = []
        skip_format = True

        for line in lines:
            if line.startswith("#"):
                continue
            if header is None:
                header = line.strip().split("\t")
                continue
            if skip_format:
                skip_format = False
                continue
            data_lines.append(line.strip().split("\t"))

        if header is None or not data_lines:
            return pd.DataFrame()

        df = pd.DataFrame(data_lines, columns=header[:len(data_lines[0])])

        # Convert lat/lon to numeric
        for col in ["dec_lat_va", "dec_long_va"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        return df
