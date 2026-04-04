"""
Basin parameter file (.bsn) parser.

Parses and modifies SWAT basin-wide parameters from basins.bsn file.

The .bsn file contains parameters that apply to the entire watershed,
including weather generator settings, water quality options, and
general simulation controls.

Example:
    >>> parser = BSNParser("basins.bsn")
    >>> params = parser.parse()
    >>> print(params['SFTMP'])  # Snowfall temperature
    >>> parser.set_parameter('SFTMP', 1.5)
    >>> parser.write("basins_modified.bsn")
"""

from pathlib import Path
from typing import Dict, List, Optional, Union
from dataclasses import dataclass, field


# Basin parameter definitions with line numbers (0-indexed) and descriptions
# Based on SWAT Input/Output Documentation
# Line 0 is typically a title/comment line, so parameters start at line 1
BSN_PARAMETERS = {
    # Line 0: Title/Comment (skip)
    # Parameters start at line 1
    'SFTMP': {'line': 1, 'col': 0, 'type': float, 'desc': 'Snowfall temperature (°C)'},
    'SMTMP': {'line': 2, 'col': 0, 'type': float, 'desc': 'Snow melt base temperature (°C)'},
    'SMFMX': {'line': 3, 'col': 0, 'type': float, 'desc': 'Max melt rate for snow on Jun 21 (mm/°C/day)'},
    'SMFMN': {'line': 4, 'col': 0, 'type': float, 'desc': 'Min melt rate for snow on Dec 21 (mm/°C/day)'},
    'TIMP': {'line': 5, 'col': 0, 'type': float, 'desc': 'Snow pack temperature lag factor'},
    'SNOCOVMX': {'line': 6, 'col': 0, 'type': float, 'desc': 'Min snow water content for 100% coverage (mm)'},
    'SNO50COV': {'line': 7, 'col': 0, 'type': float, 'desc': 'Fraction of SNOCOVMX for 50% coverage'},
    'IPET': {'line': 8, 'col': 0, 'type': int, 'desc': 'PET method (0=P-M, 1=Penman, 2=Priestley-Taylor, 3=Hargreaves)'},
    'ESCO': {'line': 9, 'col': 0, 'type': float, 'desc': 'Soil evaporation compensation factor'},
    'EPCO': {'line': 10, 'col': 0, 'type': float, 'desc': 'Plant uptake compensation factor'},
    'EVLAI': {'line': 11, 'col': 0, 'type': float, 'desc': 'LAI at which max evap occurs'},
    'FFCB': {'line': 12, 'col': 0, 'type': float, 'desc': 'Initial soil water as fraction of field capacity'},
    # Runoff parameters
    'IEVENT': {'line': 13, 'col': 0, 'type': int, 'desc': 'Rainfall/runoff code'},
    'ICRK': {'line': 14, 'col': 0, 'type': int, 'desc': 'Crack flow code (0=no, 1=yes)'},
    'SURLAG': {'line': 15, 'col': 0, 'type': float, 'desc': 'Surface runoff lag coefficient'},
    'ADJ_PKR': {'line': 16, 'col': 0, 'type': float, 'desc': 'Peak rate adjustment for sediment routing'},
    'PRF': {'line': 17, 'col': 0, 'type': float, 'desc': 'Peak rate factor for sediment routing'},
    'SPCON': {'line': 18, 'col': 0, 'type': float, 'desc': 'Linear sediment reentrain parameter'},
    'SPEXP': {'line': 19, 'col': 0, 'type': float, 'desc': 'Exponent sediment reentrain parameter'},
    # Channel parameters
    'RCN': {'line': 20, 'col': 0, 'type': float, 'desc': 'Concentration of N in rainfall (mg/L)'},
    'CMN': {'line': 21, 'col': 0, 'type': float, 'desc': 'Rate factor for humus mineralization'},
    'N_UPDIS': {'line': 22, 'col': 0, 'type': float, 'desc': 'N uptake distribution parameter'},
    'P_UPDIS': {'line': 23, 'col': 0, 'type': float, 'desc': 'P uptake distribution parameter'},
    'NPERCO': {'line': 24, 'col': 0, 'type': float, 'desc': 'N percolation coefficient'},
    'PPERCO': {'line': 25, 'col': 0, 'type': float, 'desc': 'P percolation coefficient'},
    'PHOSKD': {'line': 26, 'col': 0, 'type': float, 'desc': 'P soil partitioning coefficient'},
    'PSP': {'line': 27, 'col': 0, 'type': float, 'desc': 'P availability index'},
    'RSDCO': {'line': 28, 'col': 0, 'type': float, 'desc': 'Residue decomposition coefficient'},
    # Pesticide/bacteria
    'PERCOP': {'line': 29, 'col': 0, 'type': float, 'desc': 'Pesticide percolation coefficient'},
    # Water quality
    'ISUBWQ': {'line': 30, 'col': 0, 'type': int, 'desc': 'Subbasin water quality code'},
    # Additional parameters...
    'WDPQ': {'line': 31, 'col': 0, 'type': float, 'desc': 'Die-off factor for persistent bacteria in soil'},
    'WGPQ': {'line': 32, 'col': 0, 'type': float, 'desc': 'Growth factor for persistent bacteria in soil'},
    'WDLPQ': {'line': 33, 'col': 0, 'type': float, 'desc': 'Die-off factor for less persistent bacteria in soil'},
    'WGLPQ': {'line': 34, 'col': 0, 'type': float, 'desc': 'Growth factor for less persistent bacteria in soil'},
    'WDPS': {'line': 35, 'col': 0, 'type': float, 'desc': 'Die-off factor for persistent bacteria on foliage'},
    'WGPS': {'line': 36, 'col': 0, 'type': float, 'desc': 'Growth factor for persistent bacteria on foliage'},
    'WDLPS': {'line': 37, 'col': 0, 'type': float, 'desc': 'Die-off factor for less persistent bacteria on foliage'},
    'WGLPS': {'line': 38, 'col': 0, 'type': float, 'desc': 'Growth factor for less persistent bacteria on foliage'},
    # Groundwater
    'GWSOLP': {'line': 39, 'col': 0, 'type': float, 'desc': 'Soluble P concentration in groundwater (mg/L)'},
    # Routing
    'MSK_CO1': {'line': 40, 'col': 0, 'type': float, 'desc': 'Muskingum calibration coefficient 1'},
    'MSK_CO2': {'line': 41, 'col': 0, 'type': float, 'desc': 'Muskingum calibration coefficient 2'},
    'MSK_X': {'line': 42, 'col': 0, 'type': float, 'desc': 'Muskingum weighting factor'},
    'TRNSRCH': {'line': 43, 'col': 0, 'type': float, 'desc': 'Fraction of transmission losses to deep aquifer'},
    'EVRCH': {'line': 44, 'col': 0, 'type': float, 'desc': 'Reach evaporation adjustment factor'},
    'IRTPEST': {'line': 45, 'col': 0, 'type': int, 'desc': 'Pest routing (0=daily, 1=hourly)'},
    'ICN': {'line': 46, 'col': 0, 'type': int, 'desc': 'CN method (0=daily, 1=plant ET)'},
    'CNCOEF': {'line': 47, 'col': 0, 'type': float, 'desc': 'Plant ET curve number coefficient'},
    'CDN': {'line': 48, 'col': 0, 'type': float, 'desc': 'Denitrification exponential rate coefficient'},
    'SDNCO': {'line': 49, 'col': 0, 'type': float, 'desc': 'Denitrification threshold water content'},
    # Land use
    'BTEFR': {'line': 50, 'col': 0, 'type': float, 'desc': 'Bacteria partition coefficient for soil'},
    'BTEFP': {'line': 51, 'col': 0, 'type': float, 'desc': 'Bacteria partition coefficient for stream'},
    'BTEFPL': {'line': 52, 'col': 0, 'type': float, 'desc': 'Bacteria partition coefficient for lake'},
}


@dataclass
class BasinParameters:
    """
    Container for basin-wide parameters.

    Attributes:
        params: Dictionary of parameter name -> value
        file_path: Path to the original .bsn file
        raw_lines: Original file lines for modification
    """
    params: Dict[str, Union[int, float]] = field(default_factory=dict)
    file_path: Optional[Path] = None
    raw_lines: List[str] = field(default_factory=list)

    def __getitem__(self, key: str) -> Union[int, float]:
        return self.params[key]

    def __setitem__(self, key: str, value: Union[int, float]) -> None:
        self.params[key] = value

    def get(self, key: str, default=None) -> Union[int, float, None]:
        return self.params.get(key, default)

    def keys(self):
        return self.params.keys()

    def values(self):
        return self.params.values()

    def items(self):
        return self.params.items()

    def summary(self) -> str:
        """Generate a summary of key parameters."""
        lines = [
            "Basin Parameters Summary",
            "=" * 50,
        ]

        # Group parameters by category
        categories = {
            'Snow': ['SFTMP', 'SMTMP', 'SMFMX', 'SMFMN', 'TIMP', 'SNOCOVMX', 'SNO50COV'],
            'ET': ['IPET', 'ESCO', 'EPCO', 'EVLAI'],
            'Runoff': ['SURLAG', 'ICN', 'CNCOEF'],
            'Sediment': ['ADJ_PKR', 'PRF', 'SPCON', 'SPEXP'],
            'Nutrients': ['CMN', 'NPERCO', 'PPERCO', 'PHOSKD', 'PSP'],
            'Routing': ['MSK_CO1', 'MSK_CO2', 'MSK_X', 'TRNSRCH', 'EVRCH'],
        }

        for category, param_names in categories.items():
            lines.append(f"\n{category}:")
            for name in param_names:
                if name in self.params:
                    desc = BSN_PARAMETERS.get(name, {}).get('desc', '')
                    lines.append(f"  {name}: {self.params[name]} - {desc}")

        return "\n".join(lines)


class BSNParser:
    """
    Parser for SWAT basin parameter files (.bsn).

    Example:
        >>> parser = BSNParser("basins.bsn")
        >>> params = parser.parse()
        >>> print(params['ESCO'])
        >>> params['ESCO'] = 0.95
        >>> parser.write("basins_modified.bsn", params)
    """

    def __init__(self, file_path: Union[str, Path]):
        """
        Initialize parser.

        Args:
            file_path: Path to .bsn file
        """
        self.file_path = Path(file_path)
        self._raw_lines = []

    def parse(self) -> BasinParameters:
        """
        Parse the .bsn file.

        Returns:
            BasinParameters object with all parameters
        """
        if not self.file_path.exists():
            raise FileNotFoundError(f"BSN file not found: {self.file_path}")

        with open(self.file_path, 'r', errors='surrogateescape') as f:
            self._raw_lines = f.readlines()

        params = {}

        # Use pipe-delimited matching (standard SWAT format: "value | PARAM")
        # instead of fragile line-number indexing.  basins.bsn has 3 header
        # lines plus section headers interspersed — line numbers don't work.
        param_lookup = {name.upper(): (name, info) for name, info in BSN_PARAMETERS.items()}

        for line in self._raw_lines:
            if "|" not in line:
                continue
            parts = line.split("|", 1)
            if len(parts) < 2:
                continue
            # The parameter name is the first word after the pipe.
            # Strip trailing colon — some files use "| SFTMP: description".
            label = parts[1].strip().split()[0].rstrip(":").upper() if parts[1].strip() else ""
            if label in param_lookup:
                name, info = param_lookup[label]
                try:
                    value_str = parts[0].strip()
                    if info['type'] == int:
                        params[name] = int(float(value_str))
                    else:
                        params[name] = float(value_str)
                except (ValueError, IndexError):
                    pass

        return BasinParameters(
            params=params,
            file_path=self.file_path,
            raw_lines=self._raw_lines.copy(),
        )

    def write(
        self,
        output_path: Union[str, Path],
        params: BasinParameters,
    ) -> None:
        """
        Write modified parameters to a new .bsn file.

        Args:
            output_path: Path to output file
            params: BasinParameters with modified values
        """
        output_path = Path(output_path)
        lines = params.raw_lines.copy()

        for name, value in params.params.items():
            if name in BSN_PARAMETERS:
                info = BSN_PARAMETERS[name]
                line_idx = info['line']

                if line_idx < len(lines):
                    # Preserve the comment/label portion of the line
                    old_line = lines[line_idx]
                    parts = old_line.split()

                    if len(parts) >= 1:
                        # Format the new value
                        if info['type'] == int:
                            new_value = f"{int(value):16d}"
                        else:
                            new_value = f"{float(value):16.4f}"

                        # Reconstruct line with comment if present
                        if '|' in old_line:
                            comment_idx = old_line.index('|')
                            comment = old_line[comment_idx:]
                            lines[line_idx] = f"{new_value}    {comment}"
                        else:
                            # Keep any trailing text as comment
                            if len(parts) > 1:
                                comment = " ".join(parts[1:])
                                lines[line_idx] = f"{new_value}    | {comment}\n"
                            else:
                                lines[line_idx] = f"{new_value}\n"

        with open(output_path, 'w') as f:
            f.writelines(lines)

    @staticmethod
    def get_parameter_info(name: str) -> Optional[Dict]:
        """
        Get information about a basin parameter.

        Args:
            name: Parameter name (e.g., 'ESCO')

        Returns:
            Dictionary with parameter info or None if not found
        """
        return BSN_PARAMETERS.get(name.upper())

    @staticmethod
    def list_parameters() -> List[str]:
        """
        List all available basin parameters.

        Returns:
            List of parameter names
        """
        return list(BSN_PARAMETERS.keys())

    @staticmethod
    def create_default() -> BasinParameters:
        """
        Create a BasinParameters object with default SWAT values.

        Returns:
            BasinParameters with default values
        """
        defaults = {
            'SFTMP': 1.0,
            'SMTMP': 0.5,
            'SMFMX': 4.5,
            'SMFMN': 4.5,
            'TIMP': 1.0,
            'SNOCOVMX': 1.0,
            'SNO50COV': 0.5,
            'IPET': 0,
            'ESCO': 0.95,
            'EPCO': 1.0,
            'EVLAI': 3.0,
            'FFCB': 0.0,
            'IEVENT': 0,
            'ICRK': 0,
            'SURLAG': 4.0,
            'ADJ_PKR': 1.0,
            'PRF': 1.0,
            'SPCON': 0.0001,
            'SPEXP': 1.0,
            'RCN': 1.0,
            'CMN': 0.0003,
            'N_UPDIS': 20.0,
            'P_UPDIS': 20.0,
            'NPERCO': 0.2,
            'PPERCO': 10.0,
            'PHOSKD': 175.0,
            'PSP': 0.4,
            'RSDCO': 0.05,
            'PERCOP': 0.5,
            'ISUBWQ': 0,
            'MSK_CO1': 0.75,
            'MSK_CO2': 0.25,
            'MSK_X': 0.2,
            'TRNSRCH': 0.0,
            'EVRCH': 1.0,
            'ICN': 0,
            'CNCOEF': 1.0,
            'CDN': 1.4,
            'SDNCO': 1.1,
        }

        return BasinParameters(params=defaults)
