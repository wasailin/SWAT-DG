"""
SWAT+ tabular file reader.

All SWAT+ input files share a common format:
- Line 1: comment/version line
- Line 2: column headers (whitespace-separated)
- Line 3+: data rows (whitespace-separated)

Special cases:
- soils.sol: hierarchical multi-layer format
- weather station files (.pcp, .tmp): header + metadata + daily data
"""

from pathlib import Path
from typing import Dict, List, Optional, Any
import re


class SWATplusReader:
    """Reads all SWAT+ input files from a TxtInOut directory."""

    def __init__(self, txtinout_dir: str):
        self.dir = Path(txtinout_dir)
        if not self.dir.exists():
            raise FileNotFoundError(f"TxtInOut directory not found: {self.dir}")

    def _read_tabular(self, filename: str) -> List[Dict[str, str]]:
        """Read a standard SWAT+ tabular file (1 comment, 1 header, N data rows)."""
        filepath = self.dir / filename
        if not filepath.exists():
            raise FileNotFoundError(f"File not found: {filepath}")

        with open(filepath, "r") as f:
            lines = f.readlines()

        if len(lines) < 2:
            return []

        # Line 0 = comment, Line 1 = headers
        headers = lines[1].split()
        rows = []
        for line in lines[2:]:
            stripped = line.strip()
            if not stripped:
                continue
            values = stripped.split()
            row = {}
            for i, h in enumerate(headers):
                row[h] = values[i] if i < len(values) else ""
            # Capture extra columns beyond headers
            if len(values) > len(headers):
                row["_extra"] = values[len(headers):]
            rows.append(row)
        return rows

    def read_time_sim(self) -> Dict[str, Any]:
        """Read time.sim for simulation period."""
        rows = self._read_tabular("time.sim")
        if not rows:
            raise ValueError("time.sim is empty")
        r = rows[0]
        return {
            "day_start": int(r.get("day_start", 0)),
            "yrc_start": int(r.get("yrc_start", 2000)),
            "day_end": int(r.get("day_end", 0)),
            "yrc_end": int(r.get("yrc_end", 2024)),
            "step": int(r.get("step", 0)),
        }

    def read_object_cnt(self) -> Dict[str, Any]:
        """Read object.cnt for model object counts."""
        rows = self._read_tabular("object.cnt")
        if not rows:
            return {}
        return rows[0]

    def read_hru_data(self) -> List[Dict[str, str]]:
        """Read hru-data.hru (HRU master list with references)."""
        return self._read_tabular("hru-data.hru")

    def read_hru_con(self) -> List[Dict[str, str]]:
        """Read hru.con (HRU connectivity: area, lat/lon, elev, wst)."""
        filepath = self.dir / "hru.con"
        with open(filepath, "r") as f:
            lines = f.readlines()

        headers = lines[1].split()
        rows = []
        for line in lines[2:]:
            stripped = line.strip()
            if not stripped:
                continue
            values = stripped.split()
            row = {}
            for i, h in enumerate(headers):
                row[h] = values[i] if i < len(values) else ""
            # Handle extra routing columns (obj_typ, obj_id, hyd_typ, frac)
            if len(values) > len(headers):
                extra = values[len(headers):]
                if len(extra) >= 1:
                    row["obj_typ"] = extra[0]
                if len(extra) >= 2:
                    row["obj_id"] = extra[1]
                if len(extra) >= 3:
                    row["hyd_typ"] = extra[2]
                if len(extra) >= 4:
                    row["frac"] = extra[3]
            rows.append(row)
        return rows

    def read_soils(self) -> Dict[str, Dict]:
        """
        Read soils.sol (multi-layer hierarchical format).

        Returns dict keyed by soil name, each containing:
        - nly, hyd_grp, dp_tot, anion_excl, perc_crk, texture
        - layers: list of dicts with per-layer properties
        """
        filepath = self.dir / "soils.sol"
        with open(filepath, "r") as f:
            lines = f.readlines()

        # Line 0 = comment, Line 1 = header
        header_line = lines[1].strip().split()

        soils = {}
        i = 2
        while i < len(lines):
            line = lines[i].strip()
            if not line:
                i += 1
                continue

            vals = line.split()
            # This is a soil header row: name nly hyd_grp dp_tot anion_excl perc_crk texture
            soil_name = vals[0]
            nly = int(vals[1]) if len(vals) > 1 else 1
            hyd_grp = vals[2] if len(vals) > 2 else "B"
            dp_tot = float(vals[3]) if len(vals) > 3 else 0.0
            anion_excl = float(vals[4]) if len(vals) > 4 else 0.5
            perc_crk = float(vals[5]) if len(vals) > 5 else 0.5
            texture = vals[6] if len(vals) > 6 else ""

            soil = {
                "name": soil_name,
                "nly": nly,
                "hyd_grp": hyd_grp,
                "dp_tot": dp_tot,
                "anion_excl": anion_excl,
                "perc_crk": perc_crk,
                "texture": texture,
                "layers": [],
            }

            # Read nly layer rows
            layer_cols = [
                "dp", "bd", "awc", "soil_k", "carbon", "clay",
                "silt", "sand", "rock", "alb", "usle_k", "ec",
                "caco3", "ph"
            ]
            for _ in range(nly):
                i += 1
                if i >= len(lines):
                    break
                lvals = lines[i].strip().split()
                layer = {}
                for ci, col in enumerate(layer_cols):
                    if ci < len(lvals):
                        try:
                            layer[col] = float(lvals[ci])
                        except ValueError:
                            layer[col] = 0.0
                    else:
                        layer[col] = 0.0
                soil["layers"].append(layer)

            soils[soil_name] = soil
            i += 1

        return soils

    def read_hydrology(self) -> List[Dict[str, str]]:
        """Read hydrology.hyd (per-HRU hydrology parameters)."""
        return self._read_tabular("hydrology.hyd")

    def read_topography(self) -> List[Dict[str, str]]:
        """Read topography.hyd (per-HRU topographic parameters)."""
        return self._read_tabular("topography.hyd")

    def read_aquifer(self) -> List[Dict[str, str]]:
        """Read aquifer.aqu (aquifer parameters)."""
        return self._read_tabular("aquifer.aqu")

    def read_landuse_lum(self) -> List[Dict[str, str]]:
        """Read landuse.lum (land use master lookup)."""
        return self._read_tabular("landuse.lum")

    def read_cntable(self) -> List[Dict[str, str]]:
        """Read cntable.lum (CN2 lookup table)."""
        return self._read_tabular("cntable.lum")

    def read_ovn_table(self) -> List[Dict[str, str]]:
        """Read ovn_table.lum (Manning's n overland flow)."""
        return self._read_tabular("ovn_table.lum")

    def read_cons_practice(self) -> List[Dict[str, str]]:
        """Read cons_practice.lum (USLE_P conservation practice)."""
        return self._read_tabular("cons_practice.lum")

    def read_channel_lte(self) -> List[Dict[str, str]]:
        """Read channel-lte.cha (channel definitions)."""
        return self._read_tabular("channel-lte.cha")

    def read_hyd_sed_lte(self) -> List[Dict[str, str]]:
        """Read hyd-sed-lte.cha (channel hydraulic/sediment properties)."""
        return self._read_tabular("hyd-sed-lte.cha")

    def read_chandeg_con(self) -> List[Dict[str, str]]:
        """
        Read chandeg.con (channel routing connectivity).

        Standard columns: id name gis_id area lat lon elev lcha wst cst ovfl rule out_tot
        Followed by optional routing: obj_typ obj_id hyd_typ frac (if out_tot > 0)
        """
        filepath = self.dir / "chandeg.con"
        with open(filepath, "r") as f:
            lines = f.readlines()

        std_cols = ["id", "name", "gis_id", "area", "lat", "lon", "elev",
                    "lcha", "wst", "cst", "ovfl", "rule", "out_tot"]

        rows = []
        for line in lines[2:]:
            stripped = line.strip()
            if not stripped:
                continue
            values = stripped.split()
            row = {}
            for i, col in enumerate(std_cols):
                row[col] = values[i] if i < len(values) else ""

            # Parse routing output after out_tot
            n_std = len(std_cols)
            remaining = values[n_std:]
            if len(remaining) >= 4:
                row["obj_typ"] = remaining[0]
                row["obj_id"] = remaining[1]
                row["hyd_typ"] = remaining[2]
                row["frac"] = remaining[3]
            else:
                row["obj_typ"] = ""
                row["obj_id"] = ""

            rows.append(row)
        return rows

    def read_rout_unit_con(self) -> List[Dict[str, str]]:
        """
        Read rout_unit.con (routing unit connectivity).

        This file has variable-width routing output columns that repeat
        based on out_tot. Each output has: obj_typ, obj_id, hyd_typ, frac.
        For our purposes, we extract the first 'sdc' (channel) output
        and the aquifer reference.
        """
        filepath = self.dir / "rout_unit.con"
        with open(filepath, "r") as f:
            lines = f.readlines()

        # Standard columns end at 'out_tot', then routing outputs repeat
        # Header: id name gis_id area lat lon elev rtu wst cst ovfl rule out_tot
        #         obj_typ obj_id hyd_typ frac [obj_typ obj_id hyd_typ frac ...]
        std_cols = ["id", "name", "gis_id", "area", "lat", "lon", "elev",
                    "rtu", "wst", "cst", "ovfl", "rule", "out_tot"]

        rows = []
        for line in lines[2:]:
            stripped = line.strip()
            if not stripped:
                continue
            values = stripped.split()
            row = {}
            for i, col in enumerate(std_cols):
                row[col] = values[i] if i < len(values) else ""

            # Parse routing outputs after out_tot
            n_std = len(std_cols)
            out_tot = int(row.get("out_tot", 0))
            remaining = values[n_std:]

            # Each output is 4 values: obj_typ, obj_id, hyd_typ, frac
            # Find the 'sdc' (channel) and 'aqu' (aquifer) outputs
            row["sdc_id"] = ""
            row["aqu"] = ""
            for j in range(0, len(remaining), 4):
                if j + 3 >= len(remaining):
                    break
                o_typ = remaining[j]
                o_id = remaining[j + 1]
                o_hyd = remaining[j + 2]
                o_frac = remaining[j + 3]
                if o_typ == "sdc":
                    row["obj_typ"] = "sdc"
                    row["obj_id"] = o_id
                    row["sdc_id"] = o_id
                elif o_typ == "aqu":
                    row["aqu"] = o_id

            # If no sdc found, use first output
            if not row.get("obj_typ") and remaining:
                row["obj_typ"] = remaining[0] if len(remaining) > 0 else ""
                row["obj_id"] = remaining[1] if len(remaining) > 1 else ""

            rows.append(row)
        return rows

    def read_rout_unit_def(self) -> List[Dict[str, Any]]:
        """
        Read rout_unit.def (routing unit -> element mapping).

        Element ranges use negative notation: [3656, -3727] means
        elements 3656 through 3727 (inclusive).

        Returns list of dicts with: id, name, elem_tot, elements (expanded list of ints)
        """
        filepath = self.dir / "rout_unit.def"
        with open(filepath, "r") as f:
            lines = f.readlines()

        rows = []
        for line in lines[2:]:
            stripped = line.strip()
            if not stripped:
                continue
            values = stripped.split()
            if len(values) < 3:
                continue

            raw_elements = [int(v) for v in values[3:]]

            # Expand ranges: [start, -end] means start..end inclusive
            expanded = []
            i = 0
            while i < len(raw_elements):
                val = raw_elements[i]
                if val > 0:
                    # Check if next value is negative (range end)
                    if i + 1 < len(raw_elements) and raw_elements[i + 1] < 0:
                        end = abs(raw_elements[i + 1])
                        expanded.extend(range(val, end + 1))
                        i += 2
                    else:
                        expanded.append(val)
                        i += 1
                else:
                    # Shouldn't happen at start, skip
                    i += 1

            row = {
                "id": int(values[0]),
                "name": values[1],
                "elem_tot": int(values[2]),
                "elements": expanded,
            }
            rows.append(row)
        return rows

    def read_rout_unit_ele(self) -> List[Dict[str, str]]:
        """Read rout_unit.ele (routing unit elements with HRU references)."""
        return self._read_tabular("rout_unit.ele")

    def read_weather_sta(self) -> List[Dict[str, str]]:
        """Read weather-sta.cli (weather station -> file mapping)."""
        return self._read_tabular("weather-sta.cli")

    def read_parameters_bsn(self) -> Dict[str, str]:
        """Read parameters.bsn (basin-wide parameters, single row)."""
        rows = self._read_tabular("parameters.bsn")
        return rows[0] if rows else {}

    def read_codes_bsn(self) -> Dict[str, str]:
        """Read codes.bsn (basin simulation codes, single row)."""
        rows = self._read_tabular("codes.bsn")
        return rows[0] if rows else {}

    def read_snow(self) -> Dict[str, str]:
        """Read snow.sno (snow parameters, single row)."""
        rows = self._read_tabular("snow.sno")
        return rows[0] if rows else {}

    def read_weather_wgn(self) -> Dict[str, Dict]:
        """
        Read weather-wgn.cli (weather generator monthly statistics).

        Returns dict keyed by station name, each containing:
        - lat, lon, elev, rain_yrs
        - monthly arrays (12 values each): tmpmx, tmpmn, tmpstdmx, tmpstdmn,
          pcpmm, pcpsd, pcpskw, wetdry, wetwet, pcpd, pcphhr, slrav, dewpt, wndav
        """
        filepath = self.dir / "weather-wgn.cli"
        if not filepath.exists():
            return {}

        with open(filepath, "r") as f:
            lines = f.readlines()

        # Line 0: comment
        # Then repeating blocks: station header + column header + 12 monthly data rows
        stations = {}
        i = 1  # skip comment only
        while i < len(lines):
            line = lines[i].strip()
            if not line:
                i += 1
                continue

            # Station header: name lat lon elev rain_yrs
            vals = line.split()
            if len(vals) < 4:
                i += 1
                continue

            # Skip lines that look like column headers (contain alpha text)
            try:
                float(vals[1])
            except ValueError:
                i += 1
                continue

            sta_name = vals[0]
            sta = {
                "lat": float(vals[1]),
                "lon": float(vals[2]),
                "elev": float(vals[3]),
                "rain_yrs": int(vals[4]) if len(vals) > 4 else 25,
                "monthly": [],
            }

            # Skip column header line
            i += 1
            if i >= len(lines):
                break
            # Read 12 monthly rows
            for _ in range(12):
                i += 1
                if i >= len(lines):
                    break
                mvals = lines[i].strip().split()
                if len(mvals) >= 14:
                    sta["monthly"].append({
                        "tmpmx": float(mvals[0]),
                        "tmpmn": float(mvals[1]),
                        "tmpstdmx": float(mvals[2]),
                        "tmpstdmn": float(mvals[3]),
                        "pcpmm": float(mvals[4]),
                        "pcpsd": float(mvals[5]),
                        "pcpskw": float(mvals[6]),
                        "wetdry": float(mvals[7]),
                        "wetwet": float(mvals[8]),
                        "pcpd": float(mvals[9]),
                        "pcphhr": float(mvals[10]),
                        "slrav": float(mvals[11]),
                        "dewpt": float(mvals[12]),
                        "wndav": float(mvals[13]),
                    })

            if len(sta["monthly"]) == 12:
                stations[sta_name] = sta
            i += 1

        return stations

    def read_weather_file(self, filename: str) -> Dict[str, Any]:
        """
        Read an individual SWAT+ weather station file (.pcp or .tmp).

        Returns:
            dict with keys: nbyr, tstep, lat, lon, elev, data (list of tuples)
            For .pcp: data = [(year, jday, pcp), ...]
            For .tmp: data = [(year, jday, tmin, tmax), ...]
        """
        filepath = self.dir / filename
        if not filepath.exists():
            raise FileNotFoundError(f"Weather file not found: {filepath}")

        with open(filepath, "r") as f:
            lines = f.readlines()

        # Line 0: comment
        # Line 1: header (nbyr tstep lat long elev)
        # Line 2: metadata values
        # Line 3+: data
        meta_vals = lines[2].strip().split()
        result = {
            "nbyr": int(meta_vals[0]) if len(meta_vals) > 0 else 25,
            "tstep": int(meta_vals[1]) if len(meta_vals) > 1 else 0,
            "lat": float(meta_vals[2]) if len(meta_vals) > 2 else 0.0,
            "lon": float(meta_vals[3]) if len(meta_vals) > 3 else 0.0,
            "elev": float(meta_vals[4]) if len(meta_vals) > 4 else 0.0,
            "data": [],
        }

        for line in lines[3:]:
            stripped = line.strip()
            if not stripped:
                continue
            vals = stripped.split()
            year = int(vals[0])
            jday = int(vals[1])
            values = [float(v) for v in vals[2:]]
            result["data"].append((year, jday, *values))

        return result
