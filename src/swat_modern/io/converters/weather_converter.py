"""
Converts SWAT+ weather station files to SWAT 2012 format.

SWAT+ format: individual files per station (e.g., pcp111101030101.pcp)
  - Line 0: comment
  - Line 1: header (nbyr tstep lat long elev)
  - Line 2: metadata values
  - Line 3+: year jday value

SWAT 2012 format: combined file (pcp1.pcp)
  - Line 0: comment with station info
  - Line 1: station header (lat, lon, elev for each station)
  - Line 2+: YYYYMMDD value1 value2 ... (one column per station)
"""

from pathlib import Path
from typing import Dict, List, Set, Tuple, Any
from datetime import date, timedelta
import logging

logger = logging.getLogger(__name__)


def _jday_to_date(year: int, jday: int) -> date:
    """Convert year + Julian day to date."""
    return date(year, 1, 1) + timedelta(days=jday - 1)


def _date_to_str(d: date) -> str:
    """Format date as YYYYMMDD."""
    return d.strftime("%Y%m%d")


class WeatherConverter:
    """Converts SWAT+ weather files to SWAT 2012 format."""

    def __init__(self, reader):
        """
        Args:
            reader: SWATplusReader instance
        """
        self.reader = reader

    def get_stations_for_hrus(self, hru_cons: List[Dict]) -> Set[str]:
        """Get unique weather station names from HRU connectivity."""
        stations = set()
        for hru in hru_cons:
            wst = hru.get("wst", "")
            if wst and wst != "null":
                stations.add(wst)
        return stations

    def convert_precipitation(
        self,
        station_names: Set[str],
        output_dir: Path,
        output_filename: str = "pcp1.pcp",
    ) -> None:
        """
        Convert SWAT+ precipitation files to SWAT 2012 format.

        Args:
            station_names: Weather station names to include
            output_dir: Where to write output file
            output_filename: Name of output file
        """
        weather_sta = self.reader.read_weather_sta()

        # Build station -> pcp file mapping
        sta_to_file = {}
        for sta in weather_sta:
            name = sta.get("name", "")
            pcp_file = sta.get("pcp", "null")
            if name in station_names and pcp_file != "null":
                sta_to_file[name] = pcp_file

        if not sta_to_file:
            logger.warning("No precipitation stations found for selected HRUs")
            return

        # Read all station data
        station_data = {}
        station_meta = {}
        for sta_name, pcp_file in sta_to_file.items():
            try:
                data = self.reader.read_weather_file(pcp_file)
                station_data[sta_name] = data
                station_meta[sta_name] = {
                    "lat": data["lat"],
                    "lon": data["lon"],
                    "elev": data["elev"],
                }
            except FileNotFoundError:
                logger.warning(f"PCP file not found: {pcp_file}")

        if not station_data:
            logger.warning("No precipitation data could be read")
            return

        # Get station order (sorted for deterministic output)
        ordered_stations = sorted(station_data.keys())

        # Build date index from all stations' data
        all_dates = set()
        for sta_name, data in station_data.items():
            for record in data["data"]:
                year, jday = record[0], record[1]
                try:
                    d = _jday_to_date(year, jday)
                    all_dates.add(d)
                except ValueError:
                    pass

        sorted_dates = sorted(all_dates)

        # Build lookup: (station, date) -> value
        pcp_lookup = {}
        for sta_name, data in station_data.items():
            for record in data["data"]:
                year, jday = record[0], record[1]
                pcp = record[2] if len(record) > 2 else 0.0
                try:
                    d = _jday_to_date(year, jday)
                    pcp_lookup[(sta_name, d)] = pcp
                except ValueError:
                    pass

        # Write SWAT 2012 format matching Fortran read formats:
        # openwth.f: 3 titldum + elevations in format (7x,1800i5)
        # pmeas.f: first line (i4,i3,1800f5.1), subsequent (7x,1800f5.1)
        lines = []
        # 3 header lines (titldum)
        lines.append("Precipitation Input File pcp1.pcp")
        lines.append("Precipitation data - SWAT+ to SWAT2012 Conversion")
        lines.append("Lati    Long    Elev")
        # Line 4: elevations in format (7x,1800i5) - 7 skip + 5-char ints
        elev_str = " " * 7
        for sta in ordered_stations:
            m = station_meta.get(sta, {"elev": 0})
            elev_str += f"{int(m['elev']):5d}"
        lines.append(elev_str)

        # Data lines: format (i4,i3,1800f5.1) = year(4)+jday(3)+values(5.1)
        for d in sorted_dates:
            year = d.year
            jday = (d - date(d.year, 1, 1)).days + 1
            values = []
            for sta in ordered_stations:
                val = pcp_lookup.get((sta, d), -99.0)
                values.append(f"{val:5.1f}")
            lines.append(f"{year:4d}{jday:3d}{''.join(values)}")

        filepath = output_dir / output_filename
        with open(filepath, "w") as f:
            f.write("\n".join(lines) + "\n")
        logger.info(f"Wrote {filepath} with {len(ordered_stations)} stations and {len(sorted_dates)} days")

    def convert_temperature(
        self,
        station_names: Set[str],
        output_dir: Path,
        output_filename: str = "tmp1.tmp",
    ) -> None:
        """
        Convert SWAT+ temperature files to SWAT 2012 format.

        SWAT+ tmp files have: year jday tmax tmin
        SWAT 2012 format: YYYYMMDD tmax tmin (per station)
        """
        weather_sta = self.reader.read_weather_sta()

        sta_to_file = {}
        for sta in weather_sta:
            name = sta.get("name", "")
            tmp_file = sta.get("tmp", "null")
            if name in station_names and tmp_file != "null":
                sta_to_file[name] = tmp_file

        if not sta_to_file:
            logger.warning("No temperature stations found")
            return

        station_data = {}
        station_meta = {}
        for sta_name, tmp_file in sta_to_file.items():
            try:
                data = self.reader.read_weather_file(tmp_file)
                station_data[sta_name] = data
                station_meta[sta_name] = {
                    "lat": data["lat"],
                    "lon": data["lon"],
                    "elev": data["elev"],
                }
            except FileNotFoundError:
                logger.warning(f"TMP file not found: {tmp_file}")

        if not station_data:
            return

        ordered_stations = sorted(station_data.keys())

        all_dates = set()
        for sta_name, data in station_data.items():
            for record in data["data"]:
                year, jday = record[0], record[1]
                try:
                    d = _jday_to_date(year, jday)
                    all_dates.add(d)
                except ValueError:
                    pass

        sorted_dates = sorted(all_dates)

        # Build lookup: (station, date) -> (tmax, tmin)
        # SWAT+ tmp format: year jday tmin tmax (note order may vary)
        tmp_lookup = {}
        for sta_name, data in station_data.items():
            for record in data["data"]:
                year, jday = record[0], record[1]
                # SWAT+ stores tmin first, then tmax
                tmin = record[2] if len(record) > 2 else 10.0
                tmax = record[3] if len(record) > 3 else 20.0
                try:
                    d = _jday_to_date(year, jday)
                    tmp_lookup[(sta_name, d)] = (tmax, tmin)
                except ValueError:
                    pass

        # Write SWAT 2012 format matching Fortran read formats:
        # openwth.f: 3 titldum + elevations in format (7x,1800i10)
        # tmeas.f: first line (i4,i3,3600f5.1), subsequent (7x,3600f5.1)
        # Values alternate: tmax1 tmin1 tmax2 tmin2 ...
        lines = []
        # 3 header lines
        lines.append("Temperature Input File tmp1.tmp")
        lines.append("Temperature data - SWAT+ to SWAT2012 Conversion")
        lines.append("Lati    Long    Elev")
        # Line 4: elevations in format (7x,1800i10) - 7 skip + 10-char ints
        elev_str = " " * 7
        for sta in ordered_stations:
            m = station_meta.get(sta, {"elev": 0})
            elev_str += f"{int(m['elev']):10d}"
        lines.append(elev_str)

        # Data lines: format (i4,i3,3600f5.1) = year(4)+jday(3)+tmax1(5.1)+tmin1(5.1)+tmax2...
        for d in sorted_dates:
            year = d.year
            jday = (d - date(d.year, 1, 1)).days + 1
            values = []
            for sta in ordered_stations:
                tmax, tmin = tmp_lookup.get((sta, d), (-99.0, -99.0))
                values.append(f"{tmax:5.1f}{tmin:5.1f}")
            lines.append(f"{year:4d}{jday:3d}{''.join(values)}")

        filepath = output_dir / output_filename
        with open(filepath, "w") as f:
            f.write("\n".join(lines) + "\n")
        logger.info(f"Wrote {filepath} with {len(ordered_stations)} stations and {len(sorted_dates)} days")
