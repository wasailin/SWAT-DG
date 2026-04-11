"""
SWAT parameter modification utilities.

Handles modification of parameters in SWAT input files.
"""

import re
from pathlib import Path
from typing import Dict, List, Optional, Union


# Physical bounds for SWAT parameters.
# Values are clamped to these ranges AFTER applying any modification
# (replace, multiply, add) to prevent physically impossible values
# that crash the Fortran executable (e.g., CN2 > 100 → negative
# retention parameter → access violation).
PHYSICAL_BOUNDS = {
    "CN2": (0, 98),
    "ESCO": (0, 1),
    "EPCO": (0, 1),
    "ALPHA_BF": (0, 1),
    "GW_REVAP": (0.02, 0.2),
    "RCHRG_DP": (0, 1),
    "OV_N": (0.01, 30),
    "CH_N2": (0.01, 0.3),
    "SURLAG": (0.05, 24),
    "TIMP": (0, 1),
    "SNO50COV": (0, 1),
    "SNOCOVMX": (0, 500),
    "PRF": (0, 2),
    "ADJ_PKR": (0.5, 2),
    "SPCON": (0.0001, 0.01),
    "SPEXP": (1.0, 2.0),
    "GWSOLP": (0, 0.5),
}


# Parameter locations in SWAT input files
# Format: {parameter_name: (file_extension, line_pattern_or_number)}
PARAMETER_LOCATIONS = {
    # Basin-wide parameters (.bsn)
    "SFTMP": ("bsn", 1),
    "SMTMP": ("bsn", 2),
    "SMFMX": ("bsn", 3),
    "SMFMN": ("bsn", 4),
    "TIMP": ("bsn", 5),
    "SNOCOVMX": ("bsn", 6),
    "SNO50COV": ("bsn", 7),
    "IPET": ("bsn", 8),
    "ESCO": ("bsn", 9),  # Can also be in .hru
    "EPCO": ("bsn", 10),  # Can also be in .hru
    "SURLAG": ("bsn", 13),
    "MSK_CO1": ("bsn", 35),
    "MSK_CO2": ("bsn", 36),

    # HRU parameters (.hru)
    "SLSUBBSN": ("hru", 2),
    "HRU_SLP": ("hru", 3),
    "OV_N": ("hru", 4),
    "LAT_TTIME": ("hru", 5),
    "LAT_SED": ("hru", 6),
    "CANMX": ("hru", 10),
    "ESCO_HRU": ("hru", 11),
    "EPCO_HRU": ("hru", 12),
    "RSDIN": ("hru", 13),
    "ERORGN": ("hru", 18),
    "ERORGP": ("hru", 19),

    # Groundwater parameters (.gw)
    "SHALLST": ("gw", 1),
    "DEEPST": ("gw", 2),
    "GW_DELAY": ("gw", 3),
    "ALPHA_BF": ("gw", 4),
    "GWQMN": ("gw", 5),
    "GW_REVAP": ("gw", 6),
    "REVAPMN": ("gw", 7),
    "RCHRG_DP": ("gw", 8),
    "GWHT": ("gw", 9),
    "GW_SPYLD": ("gw", 10),
    "SHALLST_N": ("gw", 11),
    "GWSOLP": ("gw", 12),
    "HLIFE_NGW": ("gw", 13),
    "ALPHA_BF_D": ("gw", 19),

    # Soil parameters (.sol)
    "HYDGRP": ("sol", 3),
    "SOL_ZMX": ("sol", 4),
    "ANION_EXCL": ("sol", 5),
    "SOL_CRK": ("sol", 6),

    # Routing parameters (.rte)
    "CH_W2": ("rte", 1),
    "CH_D": ("rte", 2),
    "CH_S2": ("rte", 3),
    "CH_L2": ("rte", 4),
    "CH_N2": ("rte", 5),
    "CH_K2": ("rte", 6),
    "CH_COV1": ("rte", 8),
    "CH_COV2": ("rte", 9),

    # Management parameters (.mgt)
    "CN2": ("mgt", 3),
    "BIOMIX": ("mgt", 9),
    "FILTERW": ("mgt", 10),

    # Sediment routing parameters.
    # ADJ_PKR is a true basin-wide scalar (readbsn.f:410 reads adj_pkr
    # directly, used in readwgn.f for precipitation peak adjustment).
    # PRF / SPCON / SPEXP are per-reach arrays read from .rte files
    # (readrte.f:135-139); the basin-wide *_bsn values are only fallbacks
    # when the per-reach value <= 0 (readrte.f:155-157).  rtsed.f uses
    # prf(jrch), spcon(jrch), spexp(jrch) for channel sediment routing,
    # so these must be modified in .rte files, not basins.bsn.
    "ADJ_PKR": ("bsn", 16),
    "PRF": ("rte", 26),
    "SPCON": ("rte", 27),
    "SPEXP": ("rte", 28),

    # Soil layer parameters (.sol) — handled by pipe format (SOL_AWC1,
    # SOL_AWC2, …) or old tabular format fallback.
    "SOL_AWC": ("sol", None),
    "SOL_K": ("sol", None),
    "SOL_BD": ("sol", None),
    "SOL_CBN": ("sol", None),
    "SOL_Z": ("sol", None),
    "USLE_K": ("sol", None),
}


# Mapping from soil-layer parameter names to their descriptive labels in
# the old ArcSWAT/QSWAT tabular .sol format (no pipe delimiters).
# Each line contains space-separated values for all layers after a colon.
_SOL_OLD_FORMAT_LABELS = {
    "SOL_AWC": "Ave. AW Incl. Rock Frag",
    "SOL_K": "Ksat.",
    "SOL_BD": "Bulk Density Moist",
    "SOL_CBN": "Organic Carbon",
    "SOL_Z": "Depth",
    "USLE_K": "Erosion K",
}


class ParameterModifier:
    """
    Modifies parameters in SWAT input files.

    Supports three modification methods:
    - replace: Set parameter to exact value
    - multiply: Multiply current value by factor (relative change)
    - add: Add value to current parameter (absolute change)

    Example:
        >>> modifier = ParameterModifier("C:/project")
        >>> modifier.modify("CN2", -0.1, method="multiply")  # Reduce CN2 by 10%
        >>> modifier.modify("ESCO", 0.9, method="replace")   # Set ESCO to 0.9
    """

    def __init__(self, project_dir: Path):
        """
        Initialize modifier.

        Args:
            project_dir: Path to SWAT project directory
        """
        self.project_dir = Path(project_dir)

        if not self.project_dir.exists():
            raise FileNotFoundError(f"Project directory not found: {self.project_dir}")

    def modify(
        self,
        param_name: str,
        value: float,
        file_type: Optional[str] = None,
        method: str = "replace",
        unit_id: Optional[int] = None,
        decimal_precision: int = 4,
    ) -> int:
        """
        Modify a parameter in SWAT input files.

        Args:
            param_name: Parameter name (case insensitive)
            value: Value to apply
            file_type: File type to modify (if None, uses PARAMETER_LOCATIONS)
            method: "replace", "multiply", or "add"
            unit_id: Specific unit to modify (None = all files)
            decimal_precision: Number of decimal places for formatting (default 4)

        Returns:
            Number of files modified
        """
        param_name = param_name.upper()

        # Determine file type
        if file_type is None:
            if param_name in PARAMETER_LOCATIONS:
                file_type = PARAMETER_LOCATIONS[param_name][0]
            else:
                raise ValueError(
                    f"Unknown parameter '{param_name}'. "
                    f"Please specify file_type explicitly."
                )

        # Find files to modify
        pattern = f"*.{file_type}"
        if unit_id is not None:
            pattern = f"{unit_id:05d}*.{file_type}"

        files = list(self.project_dir.glob(pattern))

        if not files:
            raise FileNotFoundError(
                f"No {file_type} files found in {self.project_dir}"
            )

        # Modify each file
        found_count = 0
        modified_count = 0
        for file_path in files:
            found, modified = self._modify_file(
                file_path, param_name, value, method, decimal_precision,
            )
            if found:
                found_count += 1
            if modified:
                modified_count += 1

        # Return found_count so callers know the parameter was recognized,
        # even if values were unchanged (modified_count could be 0).
        return found_count

    def _modify_file(
        self,
        file_path: Path,
        param_name: str,
        value: float,
        method: str,
        decimal_precision: int = 4,
    ) -> tuple:
        """
        Modify a parameter in a single file.

        Returns (found, modified) — found=True if parameter label was
        matched in at least one line, modified=True if a value actually
        changed and the file was rewritten.
        """
        with open(file_path, 'r', errors='surrogateescape') as f:
            lines = f.readlines()

        found = False
        modified = False
        new_lines = []

        for line in lines:
            # Check if this line contains the parameter
            # SWAT format: value followed by | and parameter name
            if f"| {param_name}" in line.upper():
                found = True
                new_line = self._modify_line(line, param_name, value, method, decimal_precision)
                if new_line != line:
                    modified = True
                new_lines.append(new_line)
            else:
                new_lines.append(line)

        # Fallback: old ArcSWAT/QSWAT tabular .sol format (no pipe delimiters).
        # Lines look like: " Ave. AW Incl. Rock Frag  :  0.23  0.19  0.02  0.06"
        # with multiple layer values on one line after a descriptive label.
        if not found:
            old_label = _SOL_OLD_FORMAT_LABELS.get(param_name)
            if old_label:
                new_lines = []
                for line in lines:
                    if old_label.lower() in line.lower():
                        found = True
                        new_line = self._modify_tabular_line(
                            line, value, method, decimal_precision,
                        )
                        if new_line != line:
                            modified = True
                        new_lines.append(new_line)
                    else:
                        new_lines.append(line)

        if modified:
            with open(file_path, 'w', errors='surrogateescape') as f:
                f.writelines(new_lines)

        return found, modified

    def _modify_line(
        self,
        line: str,
        param_name: str,
        value: float,
        method: str,
        decimal_precision: int = 4,
    ) -> str:
        """
        Modify a parameter value in a line.

        SWAT format: "   0.95    | ESCO : ..."
        """
        # Find the value at the start of the line
        parts = line.split("|")
        if len(parts) < 2:
            return line

        # Extract current value
        value_str = parts[0].strip()

        try:
            current_value = float(value_str)
        except ValueError:
            return line

        # Apply modification
        if method == "replace":
            new_value = value
        elif method == "multiply":
            new_value = current_value * (1 + value)
        elif method == "add":
            new_value = current_value + value
        else:
            raise ValueError(f"Unknown method: {method}")

        # Clamp to physical bounds to prevent Fortran crashes.
        # e.g., CN2 > 100 → negative retention → access violation.
        bounds = PHYSICAL_BOUNDS.get(param_name)
        if bounds is not None:
            new_value = max(bounds[0], min(bounds[1], new_value))

        # Format new value with spaces before pipe delimiter.
        # Fortran list-directed I/O fails if a number touches "|".
        # Preserve integer format only for known integer-only parameters
        # read with Fortran i4/i6 format specs.  Float parameters that
        # happen to have integer values in the file (e.g., "75 | CN2")
        # must still be written as floats.
        _INTEGER_PARAMS = {
            "ISED_DET", "IRTE", "IDEG", "IWQ", "IRTPEST", "ICN",
            "ISUBCON", "IPRINT", "NYSKIP", "NBYR", "IPET", "IEVENT",
            "ICRK", "ISUBWQ", "NMGT", "IGRO", "IURBAN", "URBLU",
            "IRRSC", "IRRNO", "NROT", "PLANT_ID",
        }
        if param_name in _INTEGER_PARAMS:
            new_value_str = f"{int(round(new_value)):16d}"
        else:
            new_value_str = f"{new_value:16.{decimal_precision}f}"

        return new_value_str + "    |" + "|".join(parts[1:])

    @staticmethod
    def _modify_tabular_line(
        line: str,
        value: float,
        method: str,
        decimal_precision: int = 4,
    ) -> str:
        """Modify all numeric values in an old-format .sol tabular line.

        Old ArcSWAT/QSWAT .sol lines have a descriptive label, a colon,
        then space-separated values for each soil layer, e.g.::

            Ave. AW Incl. Rock Frag  :        0.23        0.19        0.02

        All layer values are modified uniformly with the same method/value.
        """
        if ":" not in line:
            return line

        label_part, values_part = line.split(":", 1)
        # Parse numeric tokens, preserving their positions
        tokens = re.split(r"(\s+)", values_part)
        new_tokens = []
        for token in tokens:
            stripped = token.strip()
            if not stripped:
                new_tokens.append(token)
                continue
            try:
                current = float(stripped)
            except ValueError:
                new_tokens.append(token)
                continue

            if method == "replace":
                new_val = value
            elif method == "multiply":
                new_val = current * (1 + value)
            elif method == "add":
                new_val = current + value
            else:
                new_tokens.append(token)
                continue

            # Keep the same field width as the original token
            field_width = len(token)
            formatted = f"{new_val:.{decimal_precision}f}"
            new_tokens.append(formatted.rjust(field_width))

        return label_part + ":" + "".join(new_tokens)

    def get_parameter(
        self,
        param_name: str,
        file_type: Optional[str] = None,
        unit_id: Optional[int] = None,
    ) -> Union[float, Dict[int, float]]:
        """
        Get current value of a parameter.

        Args:
            param_name: Parameter name
            file_type: File type to read
            unit_id: Specific unit (None = return all)

        Returns:
            Single value if unit_id specified, else dict of {unit_id: value}
        """
        param_name = param_name.upper()

        if file_type is None:
            if param_name in PARAMETER_LOCATIONS:
                file_type = PARAMETER_LOCATIONS[param_name][0]
            else:
                raise ValueError(f"Unknown parameter: {param_name}")

        pattern = f"*.{file_type}"
        files = list(self.project_dir.glob(pattern))

        values = {}
        for file_path in files:
            # Extract unit ID from filename
            try:
                file_unit_id = int(file_path.stem[:5])
            except ValueError:
                file_unit_id = None

            value = self._read_parameter(file_path, param_name)
            if value is not None:
                if file_unit_id is not None:
                    values[file_unit_id] = value
                else:
                    values[file_path.stem] = value

        if unit_id is not None:
            return values.get(unit_id, None)

        return values

    def _read_parameter(
        self,
        file_path: Path,
        param_name: str,
    ) -> Optional[float]:
        """Read parameter value from a file."""
        with open(file_path, 'r', errors='surrogateescape') as f:
            for line in f:
                if f"| {param_name}" in line.upper():
                    parts = line.split("|")
                    if parts:
                        try:
                            return float(parts[0].strip())
                        except ValueError:
                            pass
        return None


# Convenience alias
ParameterParser = ParameterModifier
