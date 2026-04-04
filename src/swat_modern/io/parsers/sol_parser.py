"""
Soil input file (.sol) parser.

Parses SWAT soil input files that define soil layer properties for each HRU.

The .sol file contains multi-layer soil properties including:
- Layer depths and bulk density
- Available water capacity
- Saturated hydraulic conductivity
- Organic carbon content
- Clay/silt/sand fractions

Example:
    >>> parser = SOLParser("000010001.sol")
    >>> soil = parser.parse()
    >>> print(soil.nlayers)  # Number of soil layers
    >>> print(soil.total_depth())  # Total soil depth in mm
"""

from pathlib import Path
from typing import Dict, List, Optional, Union
from dataclasses import dataclass, field


# Soil property definitions (parameter name, description, units)
SOL_PROPERTIES = {
    'SNAM': {'desc': 'Soil name', 'type': str},
    'HYDGRP': {'desc': 'Hydrologic soil group (A, B, C, D)', 'type': str},
    'SOL_ZMX': {'desc': 'Maximum rooting depth (mm)', 'type': float},
    'ANION_EXCL': {'desc': 'Fraction of porosity from which anions are excluded', 'type': float},
    'SOL_CRK': {'desc': 'Crack volume potential of soil', 'type': float},
    'TEXTURE': {'desc': 'Texture of soil layer', 'type': str},
    # Layer properties (arrays)
    'SOL_Z': {'desc': 'Depth from soil surface to bottom of layer (mm)', 'type': float},
    'SOL_BD': {'desc': 'Moist bulk density (g/cm³)', 'type': float},
    'SOL_AWC': {'desc': 'Available water capacity (mm H2O/mm soil)', 'type': float},
    'SOL_K': {'desc': 'Saturated hydraulic conductivity (mm/hr)', 'type': float},
    'SOL_CBN': {'desc': 'Organic carbon content (%)', 'type': float},
    'CLAY': {'desc': 'Clay content (%)', 'type': float},
    'SILT': {'desc': 'Silt content (%)', 'type': float},
    'SAND': {'desc': 'Sand content (%)', 'type': float},
    'ROCK': {'desc': 'Rock fragment content (%)', 'type': float},
    'SOL_ALB': {'desc': 'Moist soil albedo', 'type': float},
    'USLE_K': {'desc': 'USLE equation soil erodibility factor', 'type': float},
    'SOL_EC': {'desc': 'Electrical conductivity (dS/m)', 'type': float},
}


@dataclass
class SoilInputData:
    """
    Container for soil input data.

    Attributes:
        snam: Soil name
        hydgrp: Hydrologic soil group
        sol_zmx: Maximum rooting depth (mm)
        anion_excl: Anion exclusion fraction
        sol_crk: Crack volume potential
        nlayers: Number of soil layers
        layers: List of dictionaries containing layer properties
        file_path: Path to the original .sol file
        raw_lines: Original file lines
    """
    snam: str = ""
    hydgrp: str = ""
    sol_zmx: float = 0.0
    anion_excl: float = 0.5
    sol_crk: float = 0.0
    nlayers: int = 0
    layers: List[Dict[str, float]] = field(default_factory=list)
    file_path: Optional[Path] = None
    raw_lines: List[str] = field(default_factory=list)

    def total_depth(self) -> float:
        """Calculate total soil depth from layer data."""
        if not self.layers:
            return 0.0
        return max(layer.get('SOL_Z', 0.0) for layer in self.layers)

    def total_awc(self) -> float:
        """Calculate total available water capacity across all layers."""
        if not self.layers:
            return 0.0

        total = 0.0
        prev_depth = 0.0
        for layer in self.layers:
            depth = layer.get('SOL_Z', 0.0)
            awc = layer.get('SOL_AWC', 0.0)
            thickness = depth - prev_depth
            total += awc * thickness
            prev_depth = depth
        return total

    def get_layer(self, layer_idx: int) -> Optional[Dict[str, float]]:
        """Get properties of a specific layer (0-indexed)."""
        if 0 <= layer_idx < len(self.layers):
            return self.layers[layer_idx]
        return None

    def summary(self) -> str:
        """Generate a summary of soil properties."""
        lines = [
            f"Soil: {self.snam}",
            "=" * 50,
            f"Hydrologic Group: {self.hydgrp}",
            f"Max Rooting Depth: {self.sol_zmx:.0f} mm",
            f"Number of Layers: {self.nlayers}",
            f"Total Depth: {self.total_depth():.0f} mm",
            f"Total AWC: {self.total_awc():.1f} mm",
            "",
            "Layer Properties:",
            "-" * 50,
        ]

        header = f"{'Layer':>5} {'Depth':>8} {'BD':>6} {'AWC':>6} {'K':>8} {'Clay':>6} {'Silt':>6} {'Sand':>6}"
        lines.append(header)

        for i, layer in enumerate(self.layers):
            line = f"{i+1:>5} {layer.get('SOL_Z', 0):>8.0f} {layer.get('SOL_BD', 0):>6.2f} " \
                   f"{layer.get('SOL_AWC', 0):>6.3f} {layer.get('SOL_K', 0):>8.2f} " \
                   f"{layer.get('CLAY', 0):>6.1f} {layer.get('SILT', 0):>6.1f} {layer.get('SAND', 0):>6.1f}"
            lines.append(line)

        return "\n".join(lines)


class SOLParser:
    """
    Parser for SWAT soil input files (.sol).

    The .sol file format has:
    - Header lines with soil name, hydrologic group, etc.
    - Multiple rows for layer properties (one column per layer)

    Example:
        >>> parser = SOLParser("000010001.sol")
        >>> soil = parser.parse()
        >>> print(f"Soil has {soil.nlayers} layers")
        >>> print(f"Total AWC: {soil.total_awc():.1f} mm")
    """

    def __init__(self, file_path: Union[str, Path]):
        """
        Initialize parser.

        Args:
            file_path: Path to .sol file
        """
        self.file_path = Path(file_path)
        self._raw_lines = []

    def parse(self) -> SoilInputData:
        """
        Parse the .sol file.

        Returns:
            SoilInputData object with soil properties
        """
        if not self.file_path.exists():
            raise FileNotFoundError(f"SOL file not found: {self.file_path}")

        with open(self.file_path, 'r', errors='surrogateescape') as f:
            self._raw_lines = f.readlines()

        soil = SoilInputData(
            file_path=self.file_path,
            raw_lines=self._raw_lines.copy(),
        )

        # Parse the file line by line.
        # Supports both pipe-delimited ("value | PARAM") and colon-delimited
        # ("PARAM: value") formats for header fields.
        _header_keys = {'SNAM', 'HYDGRP', 'SOL_ZMX', 'ANION_EXCL', 'SOL_CRK'}
        for i, line in enumerate(self._raw_lines):
            line = line.strip()
            if not line:
                continue

            # Try pipe-delimited format first (SWAT2012 standard)
            if '|' in line:
                parts = line.split('|', 1)
                label = parts[1].strip().split()[0].upper() if len(parts) > 1 and parts[1].strip() else ""
                value_str = parts[0].strip()
                if label in _header_keys:
                    if label == 'SNAM':
                        soil.snam = value_str
                    elif label == 'HYDGRP':
                        soil.hydgrp = value_str
                    elif label == 'SOL_ZMX':
                        soil.sol_zmx = self._parse_float(value_str)
                    elif label == 'ANION_EXCL':
                        soil.anion_excl = self._parse_float(value_str)
                    elif label == 'SOL_CRK':
                        soil.sol_crk = self._parse_float(value_str)
                    continue

            # Fallback: colon-delimited format ("SNAM: SoilName")
            if ':' in line:
                parts = line.split(':', 1)
                if len(parts) == 2:
                    key = parts[0].strip().upper()
                    value = parts[1].strip()

                    if key == 'SNAM':
                        soil.snam = value
                    elif key == 'HYDGRP':
                        soil.hydgrp = value
                    elif key == 'SOL_ZMX':
                        soil.sol_zmx = self._parse_float(value)
                    elif key == 'ANION_EXCL':
                        soil.anion_excl = self._parse_float(value)
                    elif key == 'SOL_CRK':
                        soil.sol_crk = self._parse_float(value)
                    continue

            if line.startswith('SOL_Z') or any(line.startswith(prop) for prop in
                    ['SOL_BD', 'SOL_AWC', 'SOL_K', 'SOL_CBN', 'CLAY', 'SILT', 'SAND', 'ROCK', 'SOL_ALB', 'USLE_K', 'SOL_EC']):
                # Layer property line
                parts = line.split()
                if len(parts) >= 2:
                    prop_name = parts[0].upper()
                    values = []
                    for val in parts[1:]:
                        try:
                            values.append(float(val))
                        except ValueError:
                            break

                    # Initialize layers if needed
                    if len(values) > len(soil.layers):
                        for _ in range(len(values) - len(soil.layers)):
                            soil.layers.append({})

                    # Store values in layers
                    for j, val in enumerate(values):
                        soil.layers[j][prop_name] = val

        # Determine number of layers
        soil.nlayers = len(soil.layers)

        return soil

    def _parse_float(self, value: str) -> float:
        """Parse a float value, handling common formats."""
        try:
            # Remove any trailing comments
            if '|' in value:
                value = value.split('|')[0].strip()
            return float(value.split()[0])
        except (ValueError, IndexError):
            return 0.0

    def write(
        self,
        output_path: Union[str, Path],
        soil: SoilInputData,
    ) -> None:
        """
        Write soil data to a .sol file.

        Args:
            output_path: Path to output file
            soil: SoilInputData with properties to write
        """
        output_path = Path(output_path)

        lines = [
            f" {soil.snam}\n",
            f" {soil.hydgrp}\n",
            f" {soil.sol_zmx:.2f}\n",
            f" {soil.anion_excl:.4f}\n",
            f" {soil.sol_crk:.4f}\n",
        ]

        # Write layer properties
        layer_props = ['SOL_Z', 'SOL_BD', 'SOL_AWC', 'SOL_K', 'SOL_CBN',
                       'CLAY', 'SILT', 'SAND', 'ROCK', 'SOL_ALB', 'USLE_K', 'SOL_EC']

        for prop in layer_props:
            values = []
            for layer in soil.layers:
                values.append(layer.get(prop, 0.0))

            # Format based on property
            if prop in ['SOL_Z']:
                value_str = ' '.join(f'{v:12.2f}' for v in values)
            elif prop in ['SOL_BD', 'SOL_AWC', 'SOL_ALB', 'USLE_K']:
                value_str = ' '.join(f'{v:12.4f}' for v in values)
            else:
                value_str = ' '.join(f'{v:12.2f}' for v in values)

            lines.append(f" {prop:12s}{value_str}\n")

        with open(output_path, 'w') as f:
            f.writelines(lines)

    @staticmethod
    def get_property_info(name: str) -> Optional[Dict]:
        """
        Get information about a soil property.

        Args:
            name: Property name (e.g., 'SOL_AWC')

        Returns:
            Dictionary with property info or None if not found
        """
        return SOL_PROPERTIES.get(name.upper())

    @staticmethod
    def list_properties() -> List[str]:
        """
        List all available soil properties.

        Returns:
            List of property names
        """
        return list(SOL_PROPERTIES.keys())
