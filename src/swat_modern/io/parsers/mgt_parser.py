"""
Management file (.mgt) parser.

Parses SWAT management input files that define agricultural operations
for each HRU.

The .mgt file contains:
- General management parameters (rotation, CN adjustments, etc.)
- Scheduled operations (planting, harvest, tillage, fertilizer, etc.)

Example:
    >>> parser = MGTParser("000010001.mgt")
    >>> mgt = parser.parse()
    >>> print(mgt.cn2)  # Curve number
    >>> for op in mgt.get_planting_operations():
    ...     print(f"Plant {op.plant_id} on day {op.month}/{op.day}")
"""

from pathlib import Path
from typing import Dict, List, Optional, Union
from dataclasses import dataclass, field
from enum import IntEnum


class MGTOperation(IntEnum):
    """SWAT management operation codes."""
    PLANTING = 1
    IRRIGATION = 2
    FERTILIZER = 3
    PESTICIDE = 4
    HARVEST_KILL = 5
    TILLAGE = 6
    HARVEST_ONLY = 7
    KILL = 8
    GRAZING = 9
    AUTO_IRRIGATION = 10
    AUTO_FERTILIZER = 11
    STREET_SWEEPING = 12
    RELEASE_IMPOUND = 13
    CONTINUOUS_FERTILIZER = 14
    CONTINUOUS_PESTICIDE = 15
    BURNING = 16
    SKIP = 17


# Management parameter definitions
MGT_PARAMETERS = {
    'NMGT': {'line': 0, 'desc': 'Management code', 'type': int},
    'IGRO': {'line': 1, 'desc': 'Land cover status (0=bare, 1=growing)', 'type': int},
    'PLANT_ID': {'line': 2, 'desc': 'Land cover ID from crop.dat', 'type': int},
    'LAI_INIT': {'line': 3, 'desc': 'Initial leaf area index', 'type': float},
    'BIO_INIT': {'line': 4, 'desc': 'Initial dry weight biomass (kg/ha)', 'type': float},
    'PHU_PLT': {'line': 5, 'desc': 'Number of heat units to maturity', 'type': float},
    'BIOMIX': {'line': 6, 'desc': 'Biological mixing efficiency', 'type': float},
    'CN2': {'line': 7, 'desc': 'Initial SCS CN II value', 'type': float},
    'USLE_P': {'line': 8, 'desc': 'USLE support practice factor', 'type': float},
    'BIO_MIN': {'line': 9, 'desc': 'Minimum biomass for grazing (kg/ha)', 'type': float},
    'FILTERW': {'line': 10, 'desc': 'Width of edge-of-field filter strip (m)', 'type': float},
    'IURBAN': {'line': 11, 'desc': 'Urban simulation code', 'type': int},
    'URBLU': {'line': 12, 'desc': 'Urban land type', 'type': int},
    'IRRSC': {'line': 13, 'desc': 'Irrigation source code', 'type': int},
    'IRRNO': {'line': 14, 'desc': 'Irrigation source location', 'type': int},
    'FLOWMIN': {'line': 15, 'desc': 'Min in-stream flow for irrigation (m³/s)', 'type': float},
    'DIVMAX': {'line': 16, 'desc': 'Max irrigation diversion (m³/s)', 'type': float},
    'FLOWFR': {'line': 17, 'desc': 'Fraction of flow allowed for diversion', 'type': float},
    'DDRAIN': {'line': 18, 'desc': 'Depth to subsurface drain (mm)', 'type': float},
    'TDRAIN': {'line': 19, 'desc': 'Time to drain soil to field capacity (hr)', 'type': float},
    'GDRAIN': {'line': 20, 'desc': 'Drain tile lag time (hr)', 'type': float},
    'NROT': {'line': 21, 'desc': 'Number of years of rotation', 'type': int},
}


@dataclass
class ManagementOperation:
    """
    A single management operation.

    Attributes:
        op_code: Operation code (see MGTOperation enum)
        year: Year of operation in rotation
        month: Month of operation (1-12)
        day: Day of operation (1-31)
        husc: Heat unit scheduling factor
        params: Additional operation-specific parameters
    """
    op_code: int = 0
    year: int = 1
    month: int = 1
    day: int = 1
    husc: float = 0.0
    params: Dict[str, Union[int, float, str]] = field(default_factory=dict)

    @property
    def operation_name(self) -> str:
        """Get the name of this operation."""
        try:
            return MGTOperation(self.op_code).name
        except ValueError:
            return f"UNKNOWN_{self.op_code}"

    def __repr__(self) -> str:
        return f"ManagementOperation({self.operation_name}, year={self.year}, month={self.month}, day={self.day})"


@dataclass
class ManagementData:
    """
    Container for management input data.

    Attributes:
        params: Dictionary of general management parameters
        operations: List of scheduled management operations
        file_path: Path to the original .mgt file
        raw_lines: Original file lines
    """
    params: Dict[str, Union[int, float]] = field(default_factory=dict)
    operations: List[ManagementOperation] = field(default_factory=list)
    file_path: Optional[Path] = None
    raw_lines: List[str] = field(default_factory=list)

    # Convenience properties for common parameters
    @property
    def cn2(self) -> float:
        """Get curve number II value."""
        return self.params.get('CN2', 0.0)

    @property
    def usle_p(self) -> float:
        """Get USLE P factor."""
        return self.params.get('USLE_P', 1.0)

    @property
    def biomix(self) -> float:
        """Get biological mixing efficiency."""
        return self.params.get('BIOMIX', 0.2)

    def get_planting_operations(self) -> List[ManagementOperation]:
        """Get all planting operations."""
        return [op for op in self.operations if op.op_code == MGTOperation.PLANTING]

    def get_harvest_operations(self) -> List[ManagementOperation]:
        """Get all harvest operations (harvest only and harvest/kill)."""
        return [op for op in self.operations
                if op.op_code in (MGTOperation.HARVEST_ONLY, MGTOperation.HARVEST_KILL)]

    def get_fertilizer_operations(self) -> List[ManagementOperation]:
        """Get all fertilizer applications."""
        return [op for op in self.operations
                if op.op_code in (MGTOperation.FERTILIZER, MGTOperation.AUTO_FERTILIZER,
                                  MGTOperation.CONTINUOUS_FERTILIZER)]

    def get_tillage_operations(self) -> List[ManagementOperation]:
        """Get all tillage operations."""
        return [op for op in self.operations if op.op_code == MGTOperation.TILLAGE]

    def get_irrigation_operations(self) -> List[ManagementOperation]:
        """Get all irrigation operations."""
        return [op for op in self.operations
                if op.op_code in (MGTOperation.IRRIGATION, MGTOperation.AUTO_IRRIGATION)]

    def summary(self) -> str:
        """Generate a summary of management data."""
        lines = [
            "Management Summary",
            "=" * 50,
            f"CN2: {self.cn2:.1f}",
            f"USLE_P: {self.usle_p:.3f}",
            f"BIOMIX: {self.biomix:.2f}",
            "",
            f"Total Operations: {len(self.operations)}",
        ]

        # Count by type
        op_counts = {}
        for op in self.operations:
            name = op.operation_name
            op_counts[name] = op_counts.get(name, 0) + 1

        if op_counts:
            lines.append("")
            lines.append("Operations by Type:")
            for name, count in sorted(op_counts.items()):
                lines.append(f"  {name}: {count}")

        return "\n".join(lines)


class MGTParser:
    """
    Parser for SWAT management input files (.mgt).

    Example:
        >>> parser = MGTParser("000010001.mgt")
        >>> mgt = parser.parse()
        >>> print(f"CN2: {mgt.cn2}")
        >>> for op in mgt.operations:
        ...     print(f"{op.operation_name} on {op.month}/{op.day}")
    """

    def __init__(self, file_path: Union[str, Path]):
        """
        Initialize parser.

        Args:
            file_path: Path to .mgt file
        """
        self.file_path = Path(file_path)
        self._raw_lines = []

    def parse(self) -> ManagementData:
        """
        Parse the .mgt file.

        Returns:
            ManagementData object with management parameters and operations
        """
        if not self.file_path.exists():
            raise FileNotFoundError(f"MGT file not found: {self.file_path}")

        with open(self.file_path, 'r', errors='surrogateescape') as f:
            self._raw_lines = f.readlines()

        mgt = ManagementData(
            file_path=self.file_path,
            raw_lines=self._raw_lines.copy(),
        )

        # Use pipe-delimited matching (standard SWAT format: "value | PARAM")
        # instead of fragile line-number indexing.  .mgt has 1 header line
        # and line positions vary across SWAT versions.
        param_lookup = {name.upper(): (name, info) for name, info in MGT_PARAMETERS.items()}
        operation_start = len(self._raw_lines)  # default: no operations

        for idx, line in enumerate(self._raw_lines):
            if "|" not in line:
                continue
            parts = line.split("|", 1)
            if len(parts) < 2:
                continue
            label = parts[1].strip().split()[0].rstrip(":").upper() if parts[1].strip() else ""
            if label in param_lookup:
                name, info = param_lookup[label]
                try:
                    value_str = parts[0].strip()
                    if info['type'] == int:
                        mgt.params[name] = int(float(value_str))
                    else:
                        mgt.params[name] = float(value_str)
                except (ValueError, IndexError):
                    pass
                # Operations start after the last parameter line
                if name == 'NROT':
                    operation_start = idx + 1

        i = operation_start
        while i < len(self._raw_lines):
            line = self._raw_lines[i].strip()
            if not line or line.startswith('#'):
                i += 1
                continue

            # Try to parse as operation line
            parts = line.split()
            if len(parts) >= 5:
                try:
                    year = int(float(parts[0]))
                    month = int(float(parts[1]))
                    day = int(float(parts[2]))
                    husc = float(parts[3])
                    op_code = int(float(parts[4]))

                    op = ManagementOperation(
                        op_code=op_code,
                        year=year,
                        month=month,
                        day=day,
                        husc=husc,
                    )

                    # Parse operation-specific parameters
                    if len(parts) > 5:
                        op.params = self._parse_op_params(op_code, parts[5:])

                    mgt.operations.append(op)
                except (ValueError, IndexError):
                    pass

            i += 1

        return mgt

    def _parse_op_params(
        self,
        op_code: int,
        params: List[str]
    ) -> Dict[str, Union[int, float, str]]:
        """
        Parse operation-specific parameters.

        Args:
            op_code: Operation code
            params: List of parameter value strings

        Returns:
            Dictionary of parameter name -> value
        """
        result = {}

        try:
            if op_code == MGTOperation.PLANTING:
                if len(params) >= 1:
                    result['PLANT_ID'] = int(float(params[0]))
                if len(params) >= 2:
                    result['CURYR_MAT'] = int(float(params[1]))
                if len(params) >= 3:
                    result['HEAT_UNITS'] = float(params[2])
                if len(params) >= 4:
                    result['LAI_INIT'] = float(params[3])

            elif op_code == MGTOperation.FERTILIZER:
                if len(params) >= 1:
                    result['FERT_ID'] = int(float(params[0]))
                if len(params) >= 2:
                    result['FRT_KG'] = float(params[1])
                if len(params) >= 3:
                    result['FRT_SURFACE'] = float(params[2])

            elif op_code == MGTOperation.TILLAGE:
                if len(params) >= 1:
                    result['TILL_ID'] = int(float(params[0]))
                if len(params) >= 2:
                    result['CNOP'] = float(params[1])

            elif op_code == MGTOperation.HARVEST_KILL:
                if len(params) >= 1:
                    result['CNOP'] = float(params[0])
                if len(params) >= 2:
                    result['HI_OVR'] = float(params[1])
                if len(params) >= 3:
                    result['FRAC_HARVK'] = float(params[2])

            elif op_code == MGTOperation.HARVEST_ONLY:
                if len(params) >= 1:
                    result['HI_OVR'] = float(params[0])
                if len(params) >= 2:
                    result['FRAC_HARV'] = float(params[1])

            elif op_code == MGTOperation.IRRIGATION:
                if len(params) >= 1:
                    result['IRR_AMT'] = float(params[0])
                if len(params) >= 2:
                    result['IRR_SALT'] = float(params[1])
                if len(params) >= 3:
                    result['IRR_EFM'] = float(params[2])
                if len(params) >= 4:
                    result['IRR_SQ'] = float(params[3])

            elif op_code == MGTOperation.GRAZING:
                if len(params) >= 1:
                    result['GRZ_DAYS'] = int(float(params[0]))
                if len(params) >= 2:
                    result['MANURE_ID'] = int(float(params[1]))
                if len(params) >= 3:
                    result['BIO_EAT'] = float(params[2])
                if len(params) >= 4:
                    result['BIO_TRMP'] = float(params[3])
                if len(params) >= 5:
                    result['MANURE_KG'] = float(params[4])

        except (ValueError, IndexError):
            pass

        return result

    def write(
        self,
        output_path: Union[str, Path],
        mgt: ManagementData,
    ) -> None:
        """
        Write management data to a .mgt file.

        Args:
            output_path: Path to output file
            mgt: ManagementData with parameters and operations
        """
        output_path = Path(output_path)

        lines = []

        # Write general parameters
        param_order = ['NMGT', 'IGRO', 'PLANT_ID', 'LAI_INIT', 'BIO_INIT', 'PHU_PLT',
                       'BIOMIX', 'CN2', 'USLE_P', 'BIO_MIN', 'FILTERW', 'IURBAN',
                       'URBLU', 'IRRSC', 'IRRNO', 'FLOWMIN', 'DIVMAX', 'FLOWFR',
                       'DDRAIN', 'TDRAIN', 'GDRAIN', 'NROT']

        for param in param_order:
            info = MGT_PARAMETERS.get(param, {})
            value = mgt.params.get(param, 0)

            if info.get('type') == int:
                lines.append(f"{int(value):16d}    | {param}\n")
            else:
                lines.append(f"{float(value):16.4f}    | {param}\n")

        # Write operations
        for op in mgt.operations:
            op_line = f"{op.year:4d} {op.month:4d} {op.day:4d} {op.husc:12.5f} {op.op_code:4d}"

            # Add operation-specific parameters
            if op.op_code == MGTOperation.PLANTING:
                plant_id = op.params.get('PLANT_ID', 0)
                curyr_mat = op.params.get('CURYR_MAT', 0)
                heat_units = op.params.get('HEAT_UNITS', 0.0)
                lai_init = op.params.get('LAI_INIT', 0.0)
                op_line += f" {plant_id:4d} {curyr_mat:4d} {heat_units:12.5f} {lai_init:12.5f}"

            elif op.op_code == MGTOperation.FERTILIZER:
                fert_id = op.params.get('FERT_ID', 0)
                frt_kg = op.params.get('FRT_KG', 0.0)
                frt_surface = op.params.get('FRT_SURFACE', 0.0)
                op_line += f" {fert_id:4d} {frt_kg:12.4f} {frt_surface:12.4f}"

            elif op.op_code == MGTOperation.TILLAGE:
                till_id = op.params.get('TILL_ID', 0)
                cnop = op.params.get('CNOP', 0.0)
                op_line += f" {till_id:4d} {cnop:12.4f}"

            lines.append(op_line + "\n")

        with open(output_path, 'w') as f:
            f.writelines(lines)

    @staticmethod
    def get_operation_name(code: int) -> str:
        """
        Get the name of an operation code.

        Args:
            code: Operation code

        Returns:
            Operation name or 'UNKNOWN'
        """
        try:
            return MGTOperation(code).name
        except ValueError:
            return f"UNKNOWN_{code}"

    @staticmethod
    def list_operations() -> List[str]:
        """
        List all available operation types.

        Returns:
            List of operation names
        """
        return [op.name for op in MGTOperation]

    @staticmethod
    def get_parameter_info(name: str) -> Optional[Dict]:
        """
        Get information about a management parameter.

        Args:
            name: Parameter name (e.g., 'CN2')

        Returns:
            Dictionary with parameter info or None if not found
        """
        return MGT_PARAMETERS.get(name.upper())
