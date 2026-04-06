"""
Weather data retrieval and processing for SWAT models.

This module provides tools to:
- Fetch weather data from NOAA Climate Data Online (CDO)
- Find nearby weather stations
- Generate SWAT weather input files (.pcp, .tmp, .slr, .wnd, .hmd)
- Calculate weather generator parameters (WGEN)

Data sources supported:
- NOAA GHCND (Global Historical Climatology Network - Daily)
- NOAA LCD (Local Climatological Data)

Example:
    >>> fetcher = WeatherDataFetcher(api_token="your_noaa_token")
    >>> stations = fetcher.find_stations(lat=30.5, lon=-96.5, radius_km=50)
    >>> weather = fetcher.get_daily_weather(
    ...     station_id=stations[0].id,
    ...     start_date="2000-01-01",
    ...     end_date="2020-12-31"
    ... )
    >>> weather.to_swat_files("output_dir/")

API Token:
    Get a free NOAA CDO API token at: https://www.ncdc.noaa.gov/cdo-web/token
"""

import os
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Union, Tuple
from datetime import datetime, date
import numpy as np
import pandas as pd
import warnings

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False


# NOAA CDO API endpoints
NOAA_CDO_BASE_URL = "https://www.ncdc.noaa.gov/cdo-web/api/v2"

# SWAT weather variable mappings
SWAT_WEATHER_VARS = {
    "PRCP": "precipitation",  # mm
    "TMAX": "temp_max",       # C
    "TMIN": "temp_min",       # C
    "TAVG": "temp_avg",       # C (calculated if not available)
    "AWND": "wind_speed",     # m/s
    "RHUM": "rel_humidity",   # %
    "TSUN": "solar_rad",      # MJ/m2
}


@dataclass
class WeatherStation:
    """
    Weather station metadata.

    Attributes:
        id: Station identifier (e.g., "GHCND:USW00012960")
        name: Station name
        latitude: Latitude in decimal degrees
        longitude: Longitude in decimal degrees
        elevation: Elevation in meters
        min_date: First date with data
        max_date: Last date with data
        data_coverage: Fraction of days with data (0-1)
        distance_km: Distance from search point (if applicable)
    """

    id: str
    name: str
    latitude: float
    longitude: float
    elevation: float = 0.0
    min_date: str = ""
    max_date: str = ""
    data_coverage: float = 0.0
    distance_km: float = 0.0

    def __repr__(self) -> str:
        return (
            f"WeatherStation('{self.name}', "
            f"lat={self.latitude:.4f}, lon={self.longitude:.4f}, "
            f"elev={self.elevation:.1f}m)"
        )


@dataclass
class WeatherData:
    """
    Container for weather time series data.

    Attributes:
        station: WeatherStation metadata
        data: DataFrame with weather variables
        start_date: First date in data
        end_date: Last date in data

    The DataFrame contains columns:
        - date: Date
        - precip: Precipitation (mm)
        - temp_max: Maximum temperature (C)
        - temp_min: Minimum temperature (C)
        - temp_avg: Average temperature (C)
        - solar_rad: Solar radiation (MJ/m2) - optional
        - wind_speed: Wind speed (m/s) - optional
        - rel_humidity: Relative humidity (%) - optional
    """

    station: WeatherStation
    data: pd.DataFrame
    start_date: date = None
    end_date: date = None

    def __post_init__(self):
        """Set date range from data."""
        if len(self.data) > 0:
            self.data["date"] = pd.to_datetime(self.data["date"])
            self.start_date = self.data["date"].min().date()
            self.end_date = self.data["date"].max().date()

    @property
    def n_days(self) -> int:
        """Number of days in dataset."""
        return len(self.data)

    @property
    def n_years(self) -> float:
        """Number of years in dataset."""
        if self.start_date and self.end_date:
            return (self.end_date - self.start_date).days / 365.25
        return 0

    @property
    def completeness(self) -> Dict[str, float]:
        """Calculate data completeness for each variable."""
        result = {}
        for col in ["precip", "temp_max", "temp_min", "temp_avg"]:
            if col in self.data.columns:
                result[col] = 1 - self.data[col].isna().mean()
        return result

    def fill_missing(self, method: str = "interpolate") -> "WeatherData":
        """
        Fill missing values in weather data.

        Args:
            method: Fill method - "interpolate", "mean", or "zero"

        Returns:
            WeatherData with filled values (modifies in place)
        """
        df = self.data.copy()

        numeric_cols = ["precip", "temp_max", "temp_min", "temp_avg",
                        "solar_rad", "wind_speed", "rel_humidity"]

        for col in numeric_cols:
            if col not in df.columns:
                continue

            if method == "interpolate":
                df[col] = df[col].interpolate(method="linear", limit_direction="both")
            elif method == "mean":
                df[col] = df[col].fillna(df[col].mean())
            elif method == "zero":
                if col == "precip":
                    df[col] = df[col].fillna(0)
                else:
                    df[col] = df[col].fillna(df[col].mean())

        self.data = df
        return self

    def to_swat_files(
        self,
        output_dir: Union[str, Path],
        station_prefix: str = "station",
        generate_wgn: bool = True,
    ) -> Dict[str, Path]:
        """
        Generate SWAT weather input files.

        Creates:
        - .pcp file (precipitation)
        - .tmp file (temperature)
        - .slr file (solar radiation) - if data available
        - .wnd file (wind speed) - if data available
        - .hmd file (relative humidity) - if data available

        Args:
            output_dir: Directory for output files
            station_prefix: Prefix for file names
            generate_wgn: Also generate weather generator parameters

        Returns:
            Dictionary of {file_type: file_path}
        """
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        files = {}

        # Precipitation file (.pcp)
        pcp_file = output_dir / f"{station_prefix}.pcp"
        self._write_pcp_file(pcp_file)
        files["pcp"] = pcp_file

        # Temperature file (.tmp)
        tmp_file = output_dir / f"{station_prefix}.tmp"
        self._write_tmp_file(tmp_file)
        files["tmp"] = tmp_file

        # Solar radiation file (.slr) - if available
        if "solar_rad" in self.data.columns and not self.data["solar_rad"].isna().all():
            slr_file = output_dir / f"{station_prefix}.slr"
            self._write_slr_file(slr_file)
            files["slr"] = slr_file

        # Wind speed file (.wnd) - if available
        if "wind_speed" in self.data.columns and not self.data["wind_speed"].isna().all():
            wnd_file = output_dir / f"{station_prefix}.wnd"
            self._write_wnd_file(wnd_file)
            files["wnd"] = wnd_file

        # Relative humidity file (.hmd) - if available
        if "rel_humidity" in self.data.columns and not self.data["rel_humidity"].isna().all():
            hmd_file = output_dir / f"{station_prefix}.hmd"
            self._write_hmd_file(hmd_file)
            files["hmd"] = hmd_file

        # Weather generator parameters
        if generate_wgn:
            wgn_file = output_dir / f"{station_prefix}_wgn.txt"
            self._write_wgn_parameters(wgn_file)
            files["wgn"] = wgn_file

        return files

    def _write_pcp_file(self, filepath: Path) -> None:
        """Write SWAT precipitation file."""
        with open(filepath, "w") as f:
            # Header
            f.write(f"Precipitation data from {self.station.name}\n")

            # Data
            for _, row in self.data.iterrows():
                date = row["date"]
                precip = row.get("precip", 0)
                if pd.isna(precip):
                    precip = 0

                # SWAT format: YYYYJJJ (year + julian day)
                year = date.year
                jday = date.timetuple().tm_yday

                f.write(f"{year:4d}{jday:03d}{precip:5.1f}\n")

    def _write_tmp_file(self, filepath: Path) -> None:
        """Write SWAT temperature file."""
        with open(filepath, "w") as f:
            # Header
            f.write(f"Temperature data from {self.station.name}\n")

            # Data
            for _, row in self.data.iterrows():
                date = row["date"]
                tmax = row.get("temp_max", 20)
                tmin = row.get("temp_min", 10)

                if pd.isna(tmax):
                    tmax = 20
                if pd.isna(tmin):
                    tmin = 10

                year = date.year
                jday = date.timetuple().tm_yday

                f.write(f"{year:4d}{jday:03d}{tmax:5.1f}{tmin:5.1f}\n")

    def _write_slr_file(self, filepath: Path) -> None:
        """Write SWAT solar radiation file."""
        with open(filepath, "w") as f:
            f.write(f"Solar radiation data from {self.station.name}\n")

            for _, row in self.data.iterrows():
                date = row["date"]
                slr = row.get("solar_rad", 15)

                if pd.isna(slr):
                    slr = 15

                year = date.year
                jday = date.timetuple().tm_yday

                f.write(f"{year:4d}{jday:03d}{slr:5.1f}\n")

    def _write_wnd_file(self, filepath: Path) -> None:
        """Write SWAT wind speed file."""
        with open(filepath, "w") as f:
            f.write(f"Wind speed data from {self.station.name}\n")

            for _, row in self.data.iterrows():
                date = row["date"]
                wnd = row.get("wind_speed", 2)

                if pd.isna(wnd):
                    wnd = 2

                year = date.year
                jday = date.timetuple().tm_yday

                f.write(f"{year:4d}{jday:03d}{wnd:5.2f}\n")

    def _write_hmd_file(self, filepath: Path) -> None:
        """Write SWAT relative humidity file."""
        with open(filepath, "w") as f:
            f.write(f"Relative humidity data from {self.station.name}\n")

            for _, row in self.data.iterrows():
                date = row["date"]
                hmd = row.get("rel_humidity", 70)

                if pd.isna(hmd):
                    hmd = 70

                year = date.year
                jday = date.timetuple().tm_yday

                f.write(f"{year:4d}{jday:03d}{hmd:5.1f}\n")

    def _write_wgn_parameters(self, filepath: Path) -> None:
        """
        Calculate and write SWAT weather generator (WGEN) parameters.

        Computes monthly statistics required for SWAT weather generation.
        """
        df = self.data.copy()
        df["month"] = df["date"].dt.month

        # Initialize parameters
        params = {
            "TMPMX": [],    # Mean max temp
            "TMPMN": [],    # Mean min temp
            "TMPSTDMX": [], # Std dev max temp
            "TMPSTDMN": [], # Std dev min temp
            "PCPMM": [],    # Mean monthly precip
            "PCPSTD": [],   # Std dev daily precip
            "PCPSKW": [],   # Skew of daily precip
            "PR_W1": [],    # Prob of wet day after dry
            "PR_W2": [],    # Prob of wet day after wet
            "PCPD": [],     # Average days of precip
            "RAINHHMX": [], # Max 0.5hr rain fraction
            "SOLARAV": [],  # Mean daily solar radiation
            "DEWPT": [],    # Mean daily dew point
            "WNDAV": [],    # Mean daily wind speed
        }

        for month in range(1, 13):
            month_data = df[df["month"] == month]

            if len(month_data) == 0:
                # Fill with defaults
                for key in params:
                    params[key].append(0)
                continue

            # Temperature stats
            if "temp_max" in month_data.columns:
                params["TMPMX"].append(month_data["temp_max"].mean())
                params["TMPSTDMX"].append(month_data["temp_max"].std())
            else:
                params["TMPMX"].append(20)
                params["TMPSTDMX"].append(5)

            if "temp_min" in month_data.columns:
                params["TMPMN"].append(month_data["temp_min"].mean())
                params["TMPSTDMN"].append(month_data["temp_min"].std())
            else:
                params["TMPMN"].append(10)
                params["TMPSTDMN"].append(5)

            # Precipitation stats
            if "precip" in month_data.columns:
                precip = month_data["precip"].dropna()
                params["PCPMM"].append(precip.sum() / (len(df) / 12 / 30.4))  # Monthly avg

                wet_days = precip[precip > 0.1]
                if len(wet_days) > 0:
                    params["PCPSTD"].append(wet_days.std())
                    skew = wet_days.skew() if len(wet_days) > 2 else 0
                    params["PCPSKW"].append(skew if not pd.isna(skew) else 0)
                else:
                    params["PCPSTD"].append(0)
                    params["PCPSKW"].append(0)

                # Wet/dry transition probabilities
                is_wet = (precip > 0.1).values
                n_days = len(is_wet)
                if n_days > 1:
                    dry_to_wet = sum(
                        (not is_wet[i]) and is_wet[i+1]
                        for i in range(n_days - 1)
                    )
                    wet_to_wet = sum(
                        is_wet[i] and is_wet[i+1]
                        for i in range(n_days - 1)
                    )
                    n_dry = sum(not w for w in is_wet[:-1])
                    n_wet = sum(is_wet[:-1])

                    params["PR_W1"].append(dry_to_wet / n_dry if n_dry > 0 else 0.3)
                    params["PR_W2"].append(wet_to_wet / n_wet if n_wet > 0 else 0.5)
                else:
                    params["PR_W1"].append(0.3)
                    params["PR_W2"].append(0.5)

                params["PCPD"].append(sum(is_wet) / (len(df) / 12 / 30.4))
            else:
                params["PCPMM"].append(50)
                params["PCPSTD"].append(10)
                params["PCPSKW"].append(0)
                params["PR_W1"].append(0.3)
                params["PR_W2"].append(0.5)
                params["PCPD"].append(10)

            # Default for max half-hour rainfall
            params["RAINHHMX"].append(0.5)

            # Solar radiation
            if "solar_rad" in month_data.columns:
                params["SOLARAV"].append(month_data["solar_rad"].mean())
            else:
                params["SOLARAV"].append(15)

            # Dew point (estimate from humidity and temp if available)
            if "rel_humidity" in month_data.columns and "temp_avg" in month_data.columns:
                rh = month_data["rel_humidity"].mean()
                t = month_data["temp_avg"].mean()
                # Magnus formula approximation
                dewpt = t - ((100 - rh) / 5)
                params["DEWPT"].append(dewpt)
            else:
                params["DEWPT"].append(10)

            # Wind speed
            if "wind_speed" in month_data.columns:
                params["WNDAV"].append(month_data["wind_speed"].mean())
            else:
                params["WNDAV"].append(2)

        # Write parameters
        with open(filepath, "w") as f:
            f.write(f"Weather Generator Parameters for {self.station.name}\n")
            f.write(f"Latitude: {self.station.latitude:.4f}\n")
            f.write(f"Longitude: {self.station.longitude:.4f}\n")
            f.write(f"Elevation: {self.station.elevation:.1f} m\n")
            f.write(f"Data period: {self.start_date} to {self.end_date}\n")
            f.write("\n")
            f.write("Month   TMPMX   TMPMN TMPSTDMX TMPSTDMN   PCPMM  PCPSTD  PCPSKW   PR_W1   PR_W2    PCPD RAINHHMX SOLARAV   DEWPT   WNDAV\n")

            for i in range(12):
                f.write(
                    f"{i+1:5d}"
                    f"{params['TMPMX'][i]:8.2f}"
                    f"{params['TMPMN'][i]:8.2f}"
                    f"{params['TMPSTDMX'][i]:9.2f}"
                    f"{params['TMPSTDMN'][i]:9.2f}"
                    f"{params['PCPMM'][i]:8.2f}"
                    f"{params['PCPSTD'][i]:8.2f}"
                    f"{params['PCPSKW'][i]:8.2f}"
                    f"{params['PR_W1'][i]:8.3f}"
                    f"{params['PR_W2'][i]:8.3f}"
                    f"{params['PCPD'][i]:8.2f}"
                    f"{params['RAINHHMX'][i]:9.2f}"
                    f"{params['SOLARAV'][i]:8.2f}"
                    f"{params['DEWPT'][i]:8.2f}"
                    f"{params['WNDAV'][i]:8.2f}"
                    f"\n"
                )

    def summary(self) -> str:
        """Generate summary of weather data."""
        lines = [
            f"Weather Data Summary",
            f"=" * 50,
            f"Station: {self.station.name}",
            f"Location: ({self.station.latitude:.4f}, {self.station.longitude:.4f})",
            f"Elevation: {self.station.elevation:.1f} m",
            f"Period: {self.start_date} to {self.end_date}",
            f"Days: {self.n_days} ({self.n_years:.1f} years)",
            f"",
            f"Data Completeness:",
        ]

        for var, pct in self.completeness.items():
            lines.append(f"  {var}: {pct*100:.1f}%")

        if "precip" in self.data.columns:
            lines.extend([
                f"",
                f"Precipitation:",
                f"  Annual mean: {self.data['precip'].sum() / self.n_years:.1f} mm",
                f"  Daily mean: {self.data['precip'].mean():.2f} mm",
                f"  Max daily: {self.data['precip'].max():.1f} mm",
            ])

        if "temp_max" in self.data.columns:
            lines.extend([
                f"",
                f"Temperature:",
                f"  Mean max: {self.data['temp_max'].mean():.1f} C",
                f"  Mean min: {self.data['temp_min'].mean():.1f} C",
                f"  Absolute max: {self.data['temp_max'].max():.1f} C",
                f"  Absolute min: {self.data['temp_min'].min():.1f} C",
            ])

        return "\n".join(lines)


class NOAAClient:
    """
    Client for NOAA Climate Data Online (CDO) API.

    Provides access to weather station data from the Global Historical
    Climatology Network - Daily (GHCND) dataset.

    Example:
        >>> client = NOAAClient(api_token="your_token")
        >>> stations = client.find_stations(lat=30.5, lon=-96.5)
        >>> data = client.get_daily_data("GHCND:USW00012960", "2020-01-01", "2020-12-31")
    """

    def __init__(self, api_token: str = None):
        """
        Initialize NOAA client.

        Args:
            api_token: NOAA CDO API token
                Get one free at: https://www.ncdc.noaa.gov/cdo-web/token
                Can also set NOAA_API_TOKEN environment variable
        """
        if not HAS_REQUESTS:
            raise ImportError(
                "requests library is required for weather data retrieval. "
                "Install with: pip install requests"
            )

        self.api_token = api_token or os.environ.get("NOAA_API_TOKEN")

        if not self.api_token:
            raise ValueError(
                "NOAA API token is required. "
                "Get one at: https://www.ncdc.noaa.gov/cdo-web/token "
                "Then pass it as api_token or set NOAA_API_TOKEN environment variable."
            )

        self.base_url = NOAA_CDO_BASE_URL
        self.session = requests.Session()
        self.session.headers["token"] = self.api_token

    def _request(
        self,
        endpoint: str,
        params: dict = None,
    ) -> dict:
        """Make API request."""
        url = f"{self.base_url}/{endpoint}"

        response = self.session.get(url, params=params)
        response.raise_for_status()

        return response.json()

    def find_stations(
        self,
        lat: float,
        lon: float,
        radius_km: float = 50,
        dataset: str = "GHCND",
        min_date: str = None,
        max_date: str = None,
        limit: int = 25,
    ) -> List[WeatherStation]:
        """
        Find weather stations near a location.

        Args:
            lat: Latitude in decimal degrees
            lon: Longitude in decimal degrees
            radius_km: Search radius in kilometers
            dataset: Dataset ID (default: GHCND)
            min_date: Stations with data after this date (YYYY-MM-DD)
            max_date: Stations with data before this date (YYYY-MM-DD)
            limit: Maximum number of stations to return

        Returns:
            List of WeatherStation objects sorted by distance
        """
        # Create bounding box (approximate)
        lat_delta = radius_km / 111  # ~111 km per degree latitude
        lon_delta = radius_km / (111 * np.cos(np.radians(lat)))

        extent = f"{lat - lat_delta},{lon - lon_delta},{lat + lat_delta},{lon + lon_delta}"

        params = {
            "datasetid": dataset,
            "extent": extent,
            "limit": min(limit * 2, 1000),  # Get extra to filter
        }

        if min_date:
            params["startdate"] = min_date
        if max_date:
            params["enddate"] = max_date

        try:
            result = self._request("stations", params)
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 429:
                raise RuntimeError(
                    "NOAA API rate limit exceeded. "
                    "Wait a moment and try again, or reduce request frequency."
                )
            raise

        if "results" not in result:
            return []

        stations = []
        for item in result["results"]:
            # Calculate distance
            station_lat = item.get("latitude", 0)
            station_lon = item.get("longitude", 0)
            distance = self._haversine(lat, lon, station_lat, station_lon)

            if distance > radius_km:
                continue

            station = WeatherStation(
                id=item.get("id", ""),
                name=item.get("name", "Unknown"),
                latitude=station_lat,
                longitude=station_lon,
                elevation=item.get("elevation", 0) or 0,
                min_date=item.get("mindate", ""),
                max_date=item.get("maxdate", ""),
                data_coverage=item.get("datacoverage", 0),
                distance_km=distance,
            )
            stations.append(station)

        # Sort by distance
        stations.sort(key=lambda s: s.distance_km)

        return stations[:limit]

    def _haversine(
        self,
        lat1: float,
        lon1: float,
        lat2: float,
        lon2: float,
    ) -> float:
        """Calculate distance between two points in km."""
        R = 6371  # Earth radius in km

        lat1, lon1, lat2, lon2 = map(np.radians, [lat1, lon1, lat2, lon2])

        dlat = lat2 - lat1
        dlon = lon2 - lon1

        a = np.sin(dlat/2)**2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon/2)**2
        c = 2 * np.arcsin(np.sqrt(a))

        return R * c

    def get_daily_data(
        self,
        station_id: str,
        start_date: str,
        end_date: str,
        datatypes: List[str] = None,
    ) -> pd.DataFrame:
        """
        Get daily weather data for a station.

        Args:
            station_id: Station ID (e.g., "GHCND:USW00012960")
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            datatypes: List of data types (default: PRCP, TMAX, TMIN)

        Returns:
            DataFrame with daily weather data
        """
        if datatypes is None:
            datatypes = ["PRCP", "TMAX", "TMIN", "TAVG", "AWND"]

        # NOAA API limits to 1 year per request
        start = datetime.strptime(start_date, "%Y-%m-%d")
        end = datetime.strptime(end_date, "%Y-%m-%d")

        all_data = []

        current_start = start
        while current_start < end:
            # Get 1 year at a time
            current_end = min(
                current_start.replace(year=current_start.year + 1) - pd.Timedelta(days=1),
                end
            )

            params = {
                "datasetid": "GHCND",
                "stationid": station_id,
                "startdate": current_start.strftime("%Y-%m-%d"),
                "enddate": current_end.strftime("%Y-%m-%d"),
                "datatypeid": ",".join(datatypes),
                "units": "metric",
                "limit": 1000,
            }

            try:
                result = self._request("data", params)

                if "results" in result:
                    for item in result["results"]:
                        all_data.append({
                            "date": item["date"][:10],
                            "datatype": item["datatype"],
                            "value": item["value"],
                        })

            except requests.exceptions.HTTPError as e:
                warnings.warn(f"Error fetching data for {current_start.year}: {e}")

            current_start = current_end + pd.Timedelta(days=1)

        if not all_data:
            return pd.DataFrame()

        # Pivot to wide format
        df = pd.DataFrame(all_data)
        df["date"] = pd.to_datetime(df["date"])

        # Pivot and rename
        df_wide = df.pivot_table(
            index="date",
            columns="datatype",
            values="value",
            aggfunc="first"
        ).reset_index()

        # Rename columns to standard names
        column_map = {
            "PRCP": "precip",
            "TMAX": "temp_max",
            "TMIN": "temp_min",
            "TAVG": "temp_avg",
            "AWND": "wind_speed",
        }

        df_wide = df_wide.rename(columns=column_map)

        # No unit conversion needed: the API request uses "units": "metric"
        # which returns PRCP in mm and temperatures in °C directly.
        # (Raw GHCND without units=metric would be tenths of mm/°C.)

        # Calculate temp_avg if not available
        if "temp_avg" not in df_wide.columns and "temp_max" in df_wide.columns:
            df_wide["temp_avg"] = (df_wide["temp_max"] + df_wide["temp_min"]) / 2

        return df_wide


class WeatherDataFetcher:
    """
    High-level interface for fetching weather data.

    Simplifies the process of finding stations and retrieving data.

    Example:
        >>> fetcher = WeatherDataFetcher(api_token="your_token")
        >>> weather = fetcher.get_daily_weather(
        ...     lat=30.5, lon=-96.5,
        ...     start_date="2000-01-01",
        ...     end_date="2020-12-31"
        ... )
        >>> weather.to_swat_files("output/")
    """

    def __init__(self, api_token: str = None):
        """
        Initialize weather data fetcher.

        Args:
            api_token: NOAA CDO API token (or set NOAA_API_TOKEN env var)
        """
        self.client = NOAAClient(api_token=api_token)

    def find_stations(
        self,
        lat: float,
        lon: float,
        radius_km: float = 50,
        min_date: str = None,
        max_date: str = None,
    ) -> List[WeatherStation]:
        """
        Find weather stations near a location.

        Args:
            lat: Latitude
            lon: Longitude
            radius_km: Search radius in km
            min_date: Minimum data date (YYYY-MM-DD)
            max_date: Maximum data date (YYYY-MM-DD)

        Returns:
            List of WeatherStation objects
        """
        return self.client.find_stations(
            lat=lat,
            lon=lon,
            radius_km=radius_km,
            min_date=min_date,
            max_date=max_date,
        )

    def get_daily_weather(
        self,
        lat: float = None,
        lon: float = None,
        station_id: str = None,
        start_date: str = "2000-01-01",
        end_date: str = "2020-12-31",
        search_radius_km: float = 50,
    ) -> WeatherData:
        """
        Get daily weather data for a location or station.

        Either provide (lat, lon) to find nearest station, or station_id directly.

        Args:
            lat: Latitude (required if station_id not provided)
            lon: Longitude (required if station_id not provided)
            station_id: Station ID (alternative to lat/lon)
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            search_radius_km: Radius to search for stations

        Returns:
            WeatherData object with daily data
        """
        # Find station if needed
        if station_id is None:
            if lat is None or lon is None:
                raise ValueError("Must provide either (lat, lon) or station_id")

            stations = self.find_stations(
                lat=lat,
                lon=lon,
                radius_km=search_radius_km,
                min_date=start_date,
                max_date=end_date,
            )

            if not stations:
                raise ValueError(
                    f"No weather stations found within {search_radius_km} km "
                    f"of ({lat}, {lon})"
                )

            station = stations[0]
            station_id = station.id
            print(f"Using station: {station.name} ({station.distance_km:.1f} km away)")
        else:
            # Get station info
            station = WeatherStation(
                id=station_id,
                name=station_id,
                latitude=lat or 0,
                longitude=lon or 0,
            )

        # Get data
        df = self.client.get_daily_data(
            station_id=station_id,
            start_date=start_date,
            end_date=end_date,
        )

        if len(df) == 0:
            raise ValueError(f"No data available for station {station_id}")

        return WeatherData(station=station, data=df)

    @staticmethod
    def from_csv(
        filepath: Union[str, Path],
        station_name: str = "Custom Station",
        latitude: float = 0,
        longitude: float = 0,
        elevation: float = 0,
        date_column: str = "date",
        precip_column: str = "precip",
        tmax_column: str = "temp_max",
        tmin_column: str = "temp_min",
    ) -> WeatherData:
        """
        Load weather data from CSV file.

        Args:
            filepath: Path to CSV file
            station_name: Station name for metadata
            latitude: Station latitude
            longitude: Station longitude
            elevation: Station elevation (m)
            date_column: Name of date column
            precip_column: Name of precipitation column (mm)
            tmax_column: Name of max temperature column (C)
            tmin_column: Name of min temperature column (C)

        Returns:
            WeatherData object
        """
        df = pd.read_csv(filepath, parse_dates=[date_column])

        # Rename columns
        df = df.rename(columns={
            date_column: "date",
            precip_column: "precip",
            tmax_column: "temp_max",
            tmin_column: "temp_min",
        })

        # Calculate average temp if not present
        if "temp_avg" not in df.columns:
            df["temp_avg"] = (df["temp_max"] + df["temp_min"]) / 2

        station = WeatherStation(
            id="CUSTOM",
            name=station_name,
            latitude=latitude,
            longitude=longitude,
            elevation=elevation,
        )

        return WeatherData(station=station, data=df)
