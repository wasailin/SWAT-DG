"""
SWAT output file parser.

Parses output.rch, output.sub, output.hru, output.rsv, and output.std files.
"""

import io as _io
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union
import pandas as pd


# Column headers from SWAT header.f
REACH_COLUMNS = [
    "FLOW_INcms", "FLOW_OUTcms", "EVAPcms", "TLOSScms",
    "SED_INtons", "SED_OUTtons", "SEDCONCmg_L",
    "ORGN_INkg", "ORGN_OUTkg", "ORGP_INkg", "ORGP_OUTkg",
    "NO3_INkg", "NO3_OUTkg", "NH4_INkg", "NH4_OUTkg",
    "NO2_INkg", "NO2_OUTkg", "MINP_INkg", "MINP_OUTkg",
    "CHLA_INkg", "CHLA_OUTkg", "CBOD_INkg", "CBOD_OUTkg",
    "DISOX_INkg", "DISOX_OUTkg", "SOLPST_INmg", "SOLPST_OUTmg",
    "SORPST_INmg", "SORPST_OUTmg", "REACTPSTmg", "VOLPSTmg",
    "SETTLPSTmg", "RESUSP_PSTmg", "DIFFUSEPSTmg", "REACBEDPSTmg",
    "BURYPSTmg", "BED_PSTmg", "BACTP_OUTct", "BACTLP_OUTct",
    "CMETAL1kg", "CMETAL2kg", "CMETAL3kg",
    "TOT_Nkg", "TOT_Pkg", "NO3ConcMg_l", "WTMPdegc"
]

SUBBASIN_COLUMNS = [
    "PRECIPmm", "SNOMELTmm", "PETmm", "ETmm",
    "SWmm", "PERCmm", "SURQmm", "GW_Qmm",
    "WYLDmm", "SYLDt_ha", "ORGNkg_ha", "ORGPkg_ha",
    "NSURQkg_ha", "SOLPkg_ha", "SEDPkg_ha", "LAT_Qmm",
    "LATNO3kg_h", "GWNO3kg_ha", "CHOLAmic_L", "CBODUmg_L",
    "DOXQmg_L", "TNO3kg_ha", "QTILEmm", "TVAPkg_ha"
]

HRU_COLUMNS = [
    "PRECIPmm", "SNOFALLmm", "SNOMELTmm", "IRRmm",
    "PETmm", "ETmm", "SW_INITmm", "SW_ENDmm",
    "PERCmm", "GW_RCHGmm", "DA_RCHGmm", "REVAPmm",
    "SA_IRRmm", "DA_IRRmm", "SA_STmm", "DA_STmm",
    "SURQ_GENmm", "SURQ_CNTmm", "TLOSSmm", "LATQGENmm",
    "GW_Qmm", "WYLDmm", "DAILYCN", "TMP_AVdgC",
    "TMP_MXdgC", "TMP_MNdgC", "SOL_TMPdgC", "SOLARMJ_m2",
    "SYLDt_ha", "USLEt_ha", "N_APPkg_ha", "P_APPkg_ha",
    "NAUTOkg_ha", "PAUTOkg_ha", "NGRZkg_ha", "PGRZkg_ha",
    "NCFRTkg_ha", "PCFRTkg_ha", "NRAINkg_ha", "NFIXkg_ha",
    "F_MNkg_ha", "A_MNkg_ha", "A_SNkg_ha", "F_MPkg_ha",
    "AO_LPkg_ha", "L_APkg_ha", "A_SPkg_ha", "DNITkg_ha",
    "NUPkg_ha", "PUPkg_ha", "ORGNkg_ha", "ORGPkg_ha",
    "SEDPkg_ha", "NSURQkg_ha", "NLATQkg_ha", "NO3Lkg_ha",
    "NO3GWkg_ha", "SOLPkg_ha", "P_GWkg_ha", "W_STRS",
    "TMP_STRS", "N_STRS", "P_STRS", "BIOMt_ha",
    "LAI", "YLDt_ha", "BACTPct", "BACTLPct",
    "WTAB_CLIm", "WTAB_SOLm", "SNOmm", "CMUPkg_ha",
    "CMTOTkg_ha", "QTILEmm", "TNO3kg_ha", "LNO3kg_ha",
    "GW_Q_Dmm", "LATQCNTmm", "TVAPkg_ha"
]

# Reservoir output columns from SWAT rsvrout.f
RESERVOIR_COLUMNS = [
    "VOLUMEm3", "FLOW_INcms", "FLOW_OUTcms", "PRECIPm3",
    "EVAPm3", "SEEPAGEm3", "SED_INtons", "SED_OUTtons",
    "SED_CONCppm", "ORGN_INkg", "ORGN_OUTkg", "RES_ORGNppm",
    "ORGP_INkg", "ORGP_OUTkg", "RES_ORGPppm", "NO3_INkg",
    "NO3_OUTkg", "RES_NO3ppm", "NH3_INkg", "NH3_OUTkg",
    "RES_NH3ppm", "NO2_INkg", "NO2_OUTkg", "RES_NO2ppm",
    "MINP_INkg", "MINP_OUTkg", "RES_MINPppm", "CHLA_INkg",
    "CHLA_OUTkg", "SECCHIDEPTHm", "PEST_INmg", "REACTPSTmg",
    "VOLPSTmg", "SETTLPSTmg", "RESUSP_PSTmg", "DIFFUSEPSTmg",
    "REACBEDPSTmg", "BURYPSTmg", "PEST_OUTmg", "PSTCONCppb",
    "BACTP_OUTct", "BACTLP_OUTct"
]

# Sediment routing output columns from SWAT rsedday.f / rsedmon.f / rsedyr.f
SEDIMENT_COLUMNS = [
    "SED_INtons", "SED_OUTtons",
    "SAND_INtons", "SAND_OUTtons",
    "SILT_INtons", "SILT_OUTtons",
    "CLAY_INtons", "CLAY_OUTtons",
    "SMAG_INtons", "SMAG_OUTtons",
    "LAG_INtons", "LAG_OUTtons",
    "GRA_INtons", "GRA_OUTtons",
    "CH_BNKtons", "CH_BEDtons",
    "CH_DEPtons", "FP_DEPtons",
    "TSSmg_L",
]


class OutputParser:
    """
    Parser for SWAT output files.

    Handles output.rch, output.sub, output.hru, and output.rsv files.

    Example:
        >>> parser = OutputParser("output.rch")
        >>> df = parser.parse()
        >>> print(df.columns)
    """

    def __init__(self, file_path: Path):
        """
        Initialize parser.

        Args:
            file_path: Path to output file
        """
        self.file_path = Path(file_path)

        if not self.file_path.exists():
            raise FileNotFoundError(f"Output file not found: {self.file_path}")

        # Determine file type from extension
        self.file_type = self.file_path.suffix.lower().replace(".", "")

    def parse(self) -> Union[pd.DataFrame, Dict]:
        """
        Parse the output file into a DataFrame or dictionary.

        Returns:
            DataFrame with parsed data (for .rch, .sub, .hru, .rsv)
            Dictionary with summary statistics (for .std)
        """
        if self.file_type == "rch":
            return self._parse_reach()
        elif self.file_type == "sub":
            return self._parse_subbasin()
        elif self.file_type == "hru":
            return self._parse_hru()
        elif self.file_type == "rsv":
            return self._parse_reservoir()
        elif self.file_type == "sed":
            return self._parse_sediment()
        elif self.file_type == "std":
            return self._parse_standard()
        else:
            raise ValueError(f"Unknown output file type: {self.file_type}")

    def _parse_reach(self) -> pd.DataFrame:
        """Parse output.rch file."""
        return self._parse_fixed_width(
            id_col="RCH",
            base_columns=REACH_COLUMNS,
        )

    def _parse_subbasin(self) -> pd.DataFrame:
        """Parse output.sub file."""
        return self._parse_fixed_width(
            id_col="SUB",
            base_columns=SUBBASIN_COLUMNS,
        )

    def _parse_hru(self) -> pd.DataFrame:
        """Parse output.hru file."""
        return self._parse_hru_format()

    def _parse_reservoir(self) -> pd.DataFrame:
        """Parse output.rsv file."""
        # Reservoir format is similar to reach
        return self._parse_fixed_width(
            id_col="RES",
            base_columns=RESERVOIR_COLUMNS,
        )

    def _parse_sediment(self) -> pd.DataFrame:
        """Parse output.sed file (reach-based sediment routing)."""
        return self._parse_fixed_width(
            id_col="RCH",
            base_columns=SEDIMENT_COLUMNS,
        )

    def _parse_standard(self) -> Dict:
        """
        Parse output.std file (standard summary output).

        Returns:
            Dictionary with basin-wide summary statistics organized by section.
        """
        results = {
            "simulation_info": {},
            "average_annual_basin": {},
            "average_monthly_basin": {},
            "average_annual_subbasin": [],
            "average_annual_reach": [],
        }

        current_section = None

        with open(self.file_path, 'r') as f:
            lines = f.readlines()

        i = 0
        while i < len(lines):
            line = lines[i].strip()

            # Detect sections
            if "AVE ANNUAL BASIN VALUES" in line.upper():
                current_section = "average_annual_basin"
                i += 1
                continue
            elif "AVE MONTHLY BASIN VALUES" in line.upper():
                current_section = "average_monthly_basin"
                i += 1
                continue
            elif "AVERAGE ANNUAL SUBBASIN" in line.upper() or "AVE ANNUAL SUBBASIN" in line.upper():
                current_section = "average_annual_subbasin"
                i += 1
                continue
            elif "AVERAGE ANNUAL REACH" in line.upper() or "AVE ANNUAL REACH" in line.upper():
                current_section = "average_annual_reach"
                i += 1
                continue

            # Parse values based on section
            if current_section == "average_annual_basin":
                self._parse_std_key_value(line, results["average_annual_basin"])
            elif current_section == "average_monthly_basin":
                self._parse_std_key_value(line, results["average_monthly_basin"])

            i += 1

        return results

    def _parse_std_key_value(self, line: str, target_dict: Dict) -> None:
        """
        Parse a key-value line from output.std.

        Lines are typically formatted as:
        "  PRECIPITATION =   1234.56"
        or "PRECIPITATION            1234.56"
        """
        if not line or line.startswith("-") or line.startswith("="):
            return

        # Try format with '=' sign
        if "=" in line:
            parts = line.split("=")
            if len(parts) == 2:
                key = parts[0].strip()
                try:
                    value = float(parts[1].strip().split()[0])
                    target_dict[key] = value
                except (ValueError, IndexError):
                    pass
            return

        # Try format with whitespace separation
        parts = line.split()
        if len(parts) >= 2:
            # Last part should be the value
            try:
                value = float(parts[-1])
                key = " ".join(parts[:-1])
                if key:
                    target_dict[key] = value
            except ValueError:
                pass

    def _parse_fixed_width(
        self,
        id_col: str,
        base_columns: List[str],
    ) -> pd.DataFrame:
        """
        Parse fixed-width format output files.

        Args:
            id_col: Name for the ID column (RCH, SUB, etc.)
            base_columns: List of data column names
        """
        data_rows = []
        header_found = False
        columns_from_header = []

        with open(self.file_path, 'r') as f:
            for line in f:
                # Skip blank lines
                if not line.strip():
                    continue

                # Look for header line
                if id_col in line and ("GIS" in line or "MON" in line):
                    # Parse column names from header
                    columns_from_header = self._parse_header_line(line)
                    header_found = True
                    continue

                # Skip other header/comment lines
                if not header_found:
                    continue

                # Try to parse data line
                try:
                    row = self._parse_data_line(line, id_col)
                    if row:
                        data_rows.append(row)
                except (ValueError, IndexError):
                    continue

        if not data_rows:
            raise ValueError(f"No data found in {self.file_path}")

        # Create DataFrame
        df = pd.DataFrame(data_rows)

        # Preserve the _is_annual sentinel column before renaming integer keys.
        # It is added by _parse_sub_data_line() (and the standard path) so it
        # only exists for SUB output, but guard generically for safety.
        is_annual_col = None
        if '_is_annual' in df.columns:
            is_annual_col = df['_is_annual'].copy()
            df = df.drop(columns=['_is_annual'])

        # Assign column names based on the actual header line.
        # Check whether DAY and YEAR columns exist in the header rather
        # than guessing from column count (Rev 692+ adds Salt/SAR/EC
        # columns which inflates the count without adding DAY/YEAR).
        header_upper = [c.upper() for c in columns_from_header]
        has_day_year = "DAY" in header_upper and "YEAR" in header_upper
        meta_cols = [id_col, "GIS", "MON", "AREAkm2"]
        if has_day_year:
            meta_cols = [id_col, "GIS", "MON", "DAY", "YEAR", "AREAkm2"]

        # Use base_columns for data columns
        all_cols = meta_cols + base_columns

        # Truncate or pad columns as needed
        if len(df.columns) <= len(all_cols):
            df.columns = all_cols[:len(df.columns)]
        else:
            # More columns than expected - use generic names for extras
            extra_count = len(df.columns) - len(all_cols)
            df.columns = all_cols + [f"VAR_{i}" for i in range(extra_count)]

        # Re-attach _is_annual after column names are assigned (SUB only).
        if is_annual_col is not None:
            df['_is_annual'] = is_annual_col.values

        return df

    def _parse_header_line(self, line: str) -> List[str]:
        """Extract column names from header line."""
        # Remove leading/trailing whitespace and split
        parts = line.split()
        return [p.strip() for p in parts if p.strip()]

    def _parse_data_line(self, line: str, id_col: str) -> Optional[Dict]:
        """
        Parse a data line.

        Returns dictionary of values or None if line is not valid data.

        Handles lines that start with a text label (e.g. "REACH  1  1  1 ...")
        by stripping the label before parsing numeric values.

        For SUB output, delegates to _parse_sub_data_line() to handle the
        Fortran i4+e10.5 merged-token column (iida concatenated with sub_km).
        """
        parts = line.split()

        if len(parts) < 5:
            return None

        # Skip leading text label if present (e.g. "REACH", "SUB", "RES", "BIGSUB")
        try:
            int(parts[0])
        except ValueError:
            parts = parts[1:]
            if len(parts) < 5:
                return None

        # Validate first value is an integer (the ID)
        try:
            int(parts[0])
        except ValueError:
            return None

        # SUB format: iida(i4) and sub_km(e10.5) are adjacent with no separator,
        # so whitespace-split may merge them into one token.  Use dedicated parser.
        if id_col == "SUB":
            return self._parse_sub_data_line(parts)

        # Standard path for RCH, RES, etc.
        # ID columns: ID (index 0), GIS (index 1), MON (index 2),
        # AREAkm2 (index 3 — float).  Data columns start at index 3+.
        values: Dict = {}
        for i, p in enumerate(parts):
            if i < 3:
                # ID columns — always integer.
                # Some SWAT revisions (692+) format certain integer
                # fields with a decimal (e.g. "4.0" for month 4).
                try:
                    values[i] = int(p)
                except ValueError:
                    try:
                        values[i] = int(float(p))
                    except (ValueError, OverflowError):
                        values[i] = p
            else:
                try:
                    values[i] = float(p)
                except ValueError:
                    values[i] = p
        values['_is_annual'] = False
        return values

    def _parse_sub_data_line(self, parts: List[str]) -> Optional[Dict]:
        """
        Parse a whitespace-split token list from an output.sub data line.

        Background: SWAT's subday.f writes iida (Julian day) as ``i4`` and
        sub_km (area) as ``e10.5`` back-to-back with no separator.  When
        iida is a small integer (1-9) the i4 field is right-justified and
        the e10.5 field starts with the first significant digit rather than
        a leading space, causing the two fields to merge into one token,
        e.g. ``"1.18710E+02"`` encodes iida=1 and area=18.71 km².

        In the annual summary (subaa.f) the same position uses ``f4.1``
        for the year counter, which always produces a decimal point without
        an exponent, giving a separate token from the e10.5 area.

        ``parts`` must already have the leading text label stripped, so
        parts[0] = SUB id (int), parts[1] = GIS (int),
        parts[2] = merged-or-annual token, parts[3:] = data values.
        """
        values: Dict = {}
        try:
            values[0] = int(parts[0])   # SUB
            values[1] = int(parts[1])   # GIS
        except (ValueError, IndexError):
            return None

        if len(parts) < 3:
            return None

        tok = parts[2]
        tok_upper = tok.upper()

        if 'E' in tok_upper:
            # Merged daily token: iida and sub_km packed together.
            # The token value equals  iida * 10^exp + area,
            # where exp is the exponent of the e10.5 field.
            # Example: "1.18710E+02"  → exp=2, base=100,
            #           tv=118.71, iida=int(118.71/100)=1, area=18.71
            m = re.search(r'[Ee]([+-]?\d+)', tok)
            if m is None:
                return None
            exp = int(m.group(1))
            base = 10.0 ** exp
            try:
                token_val = float(tok)
            except ValueError:
                return None
            iida = int(token_val / base)    # Julian day (1-366)
            area = token_val - iida * base  # true subbasin area in km²
            values[2] = iida
            values[3] = area
            for i, p in enumerate(parts[3:], 4):
                try:
                    values[i] = float(p)
                except ValueError:
                    values[i] = p
            values['_is_annual'] = False

        elif '.' in tok and 'E' not in tok_upper:
            # Annual summary row (subaa.f): years counter written as f4.1
            # ("1.0", "2.0", ...) splits cleanly from the e10.5 area token.
            try:
                years = int(float(tok))
            except ValueError:
                return None
            values[2] = years   # MON = year-within-simulation counter
            if len(parts) > 3:
                try:
                    values[3] = float(parts[3])   # AREAkm2 (separate token)
                except ValueError:
                    values[3] = 0.0
                for i, p in enumerate(parts[4:], 4):
                    try:
                        values[i] = float(p)
                    except ValueError:
                        values[i] = p
            values['_is_annual'] = True

        else:
            # Fallback: plain integer MON (defensive, should not occur for
            # standard Rev 681 output.sub but handle gracefully).
            try:
                values[2] = int(float(tok))
            except ValueError:
                return None
            for i, p in enumerate(parts[3:], 3):
                try:
                    values[i] = float(p)
                except ValueError:
                    values[i] = p
            values['_is_annual'] = False

        return values

    def _parse_hru_format(self) -> pd.DataFrame:
        """
        Parse HRU output file format using pandas for performance.

        HRU format has a text LULC label followed by integer/float columns.
        Like output.sub, the Fortran hruday.f writes iida (Julian day) as
        ``i4`` and hru_km (area) as ``e10.5`` back-to-back, so they may
        merge into one whitespace token (same pattern as output.sub).
        This method detects that and decodes accordingly.

        Uses ``pandas.read_csv`` via StringIO for a 10-50x speedup over
        line-by-line dict building.
        """
        with open(self.file_path, 'r') as f:
            lines = f.readlines()

        # Find header line
        header_idx: Optional[int] = None
        for i, line in enumerate(lines):
            if "LULC" in line and "HRU" in line:
                header_idx = i
                break
        if header_idx is None:
            raise ValueError(f"No header found in {self.file_path}")

        # Collect data lines that have enough fields
        data_lines = [
            line for line in lines[header_idx + 1:]
            if line.strip() and len(line.split()) >= 10
        ]

        if not data_lines:
            raise ValueError(f"No data found in {self.file_path}")

        # Use pandas C-extension CSV parser — much faster than line-by-line.
        # Read everything as str first so we can inspect the merged token.
        text = ''.join(data_lines)
        try:
            raw = pd.read_csv(
                _io.StringIO(text),
                sep=r'\s+',
                header=None,
                dtype=str,
                on_bad_lines='skip',
                engine='python',
            )
        except Exception as exc:
            raise ValueError(f"Failed to parse {self.file_path}") from exc

        if raw.empty:
            raise ValueError(f"No data found in {self.file_path}")

        result = pd.DataFrame()

        # Column 0: LULC (text land-use code)
        result['LULC'] = raw.iloc[:, 0].astype(str)

        # Columns 1-4: integer IDs — HRU, GIS, SUB, MGT
        # HRU meta layout: LULC(0) HRU(1) GIS(2) SUB(3) MGT(4) MON+area(5or5+6) data…
        # Detect merged MON+AREAkm2 token: same i4+e10.5 Fortran pattern as SUB.
        # Sample the first few rows of column 5 to decide.
        col5_sample = raw.iloc[:min(5, len(raw)), 5].astype(str)
        hru_has_merged = col5_sample.str.contains('[Ee]', na=False).any()

        for col_idx, col_name in enumerate(['HRU', 'GIS', 'SUB', 'MGT'], 1):
            result[col_name] = (
                pd.to_numeric(raw.iloc[:, col_idx], errors='coerce')
                .fillna(0)
                .astype(int)
            )

        if hru_has_merged:
            # Decode the merged token in column 5 row-by-row.
            mon_vals: List[int] = []
            area_vals: List[float] = []
            is_annual_vals: List[bool] = []

            for tok in raw.iloc[:, 5].astype(str):
                tok_upper = tok.upper()
                if 'E' in tok_upper:
                    m = re.search(r'[Ee]([+-]?\d+)', tok)
                    if m:
                        exp = int(m.group(1))
                        base = 10.0 ** exp
                        try:
                            tv = float(tok)
                            iida = int(tv / base)
                            area = tv - iida * base
                            mon_vals.append(iida)
                            area_vals.append(area)
                            is_annual_vals.append(False)
                            continue
                        except ValueError:
                            pass
                    mon_vals.append(0)
                    area_vals.append(0.0)
                    is_annual_vals.append(False)
                elif '.' in tok and 'E' not in tok_upper:
                    # Annual summary: years counter as f4.1, area separate
                    try:
                        mon_vals.append(int(float(tok)))
                    except ValueError:
                        mon_vals.append(0)
                    area_vals.append(0.0)
                    is_annual_vals.append(True)
                else:
                    try:
                        mon_vals.append(int(float(tok)))
                    except ValueError:
                        mon_vals.append(0)
                    area_vals.append(0.0)
                    is_annual_vals.append(False)

            result['MON'] = mon_vals
            result['AREAkm2'] = area_vals
            result['_is_annual'] = is_annual_vals
            data_start_col = 6   # HRU data columns begin at raw column 6

        else:
            # Non-merged format: MON is a plain integer at col 5, area at col 6
            result['MON'] = (
                pd.to_numeric(raw.iloc[:, 5], errors='coerce')
                .fillna(0)
                .astype(int)
            )
            result['AREAkm2'] = pd.to_numeric(raw.iloc[:, 6], errors='coerce').fillna(0.0)
            result['_is_annual'] = False
            data_start_col = 7

        # Map HRU data columns by position
        for i, col_name in enumerate(HRU_COLUMNS):
            raw_col = data_start_col + i
            if raw_col < raw.shape[1]:
                result[col_name] = pd.to_numeric(raw.iloc[:, raw_col], errors='coerce').fillna(0.0)
            else:
                result[col_name] = 0.0

        return result


class CIOParser:
    """
    Parser for file.cio (master input/output control file).

    This is a convenience wrapper around SWATConfig for parsing file.cio.
    """

    def __init__(self, file_path: Path):
        """
        Initialize parser.

        Args:
            file_path: Path to file.cio
        """
        self.file_path = Path(file_path)

        if not self.file_path.exists():
            raise FileNotFoundError(f"file.cio not found: {self.file_path}")

    def parse(self) -> Dict:
        """
        Parse file.cio into a dictionary.

        Returns:
            Dictionary with configuration values
        """
        values = {}

        with open(self.file_path, 'r') as f:
            lines = f.readlines()

        # Use pipe-delimited matching instead of fragile line numbers.
        # Standard file.cio format: "value    | PARAM_NAME : description"
        pipe_mappings = {
            "NBYR": ("nbyr", int),
            "IYR": ("iyr", int),
            "IDAF": ("idaf", int),
            "IDAL": ("idal", int),
            "IPRINT": ("iprint", int),
            "NYSKIP": ("nyskip", int),
        }

        for line in lines:
            if "|" not in line:
                continue
            parts = line.split("|", 1)
            if len(parts) < 2 or not parts[1].strip():
                continue
            label = parts[1].strip().split()[0].rstrip(":").upper()
            if label in pipe_mappings:
                key, dtype = pipe_mappings[label]
                try:
                    values[key] = dtype(parts[0].strip().split()[0])
                except (ValueError, IndexError):
                    pass

        return values
