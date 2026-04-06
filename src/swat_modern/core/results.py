"""
SWAT Simulation results container.

Stores simulation outputs and provides convenience methods for analysis.
"""

from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime
import pandas as pd


@dataclass
class SimulationResult:
    """
    Container for SWAT simulation results.

    Stores simulation status, runtime, and provides access to output data.

    Attributes:
        success: Whether simulation completed successfully
        runtime: Simulation runtime in seconds
        return_code: Process return code
        stdout: Standard output from simulation
        stderr: Standard error from simulation
        error_message: Human-readable error message if failed
        project_dir: Path to project directory
        timestamp: When simulation was run
    """

    success: bool
    runtime: float
    return_code: int
    stdout: str = ""
    stderr: str = ""
    error_message: str = ""
    project_dir: Optional[Path] = None
    timestamp: datetime = field(default_factory=datetime.now)

    # Cached data
    _reach_data: Optional[pd.DataFrame] = field(default=None, repr=False)
    _subbasin_data: Optional[pd.DataFrame] = field(default=None, repr=False)
    _hru_data: Optional[pd.DataFrame] = field(default=None, repr=False)

    @property
    def output_files(self) -> Dict[str, Path]:
        """Get paths to output files."""
        if self.project_dir is None:
            return {}

        outputs = {}
        for name in ["output.rch", "output.sub", "output.hru", "output.std"]:
            path = self.project_dir / name
            if path.exists():
                outputs[name] = path

        return outputs

    @property
    def has_outputs(self) -> bool:
        """Check if output files exist."""
        return len(self.output_files) > 0

    def get_reach_output(self) -> pd.DataFrame:
        """
        Get reach (channel) output data.

        Returns:
            DataFrame with reach output variables
        """
        if self._reach_data is not None:
            return self._reach_data

        if self.project_dir is None:
            raise ValueError("Project directory not set")

        from swat_modern.io.parsers.output_parser import OutputParser

        rch_path = self.project_dir / "output.rch"
        if not rch_path.exists():
            raise FileNotFoundError(f"Reach output not found: {rch_path}")

        parser = OutputParser(rch_path)
        self._reach_data = parser.parse()
        return self._reach_data

    def get_subbasin_output(self) -> pd.DataFrame:
        """
        Get subbasin output data.

        Returns:
            DataFrame with subbasin output variables
        """
        if self._subbasin_data is not None:
            return self._subbasin_data

        if self.project_dir is None:
            raise ValueError("Project directory not set")

        from swat_modern.io.parsers.output_parser import OutputParser

        sub_path = self.project_dir / "output.sub"
        if not sub_path.exists():
            raise FileNotFoundError(f"Subbasin output not found: {sub_path}")

        parser = OutputParser(sub_path)
        self._subbasin_data = parser.parse()
        return self._subbasin_data

    def get_water_balance(self) -> Dict[str, float]:
        """
        Extract water balance summary from output.std.

        Returns:
            Dictionary with water balance components
        """
        if self.project_dir is None:
            raise ValueError("Project directory not set")

        std_path = self.project_dir / "output.std"
        if not std_path.exists():
            raise FileNotFoundError(f"Standard output not found: {std_path}")

        # Parse output.std for water balance
        balance = {}
        with open(std_path, 'r') as f:
            in_balance_section = False
            for line in f:
                if "WATER BALANCE" in line.upper():
                    in_balance_section = True
                    continue

                if in_balance_section:
                    # Parse water balance lines
                    parts = line.split()
                    if len(parts) >= 2:
                        try:
                            # Try to extract numeric value
                            key = parts[0].replace("=", "").strip()
                            value = float(parts[-1])
                            balance[key] = value
                        except (ValueError, IndexError):
                            continue

        return balance

    def summary(self) -> str:
        """
        Generate summary of simulation results.

        Returns:
            Formatted string with simulation summary
        """
        lines = [
            "=" * 50,
            "SWAT Simulation Results",
            "=" * 50,
            f"Status: {'SUCCESS' if self.success else 'FAILED'}",
            f"Runtime: {self.runtime:.2f} seconds",
            f"Timestamp: {self.timestamp.strftime('%Y-%m-%d %H:%M:%S')}",
        ]

        if not self.success:
            lines.append(f"Error: {self.error_message}")

        if self.has_outputs:
            lines.append("\nOutput files:")
            for name, path in self.output_files.items():
                size_kb = path.stat().st_size / 1024
                lines.append(f"  - {name}: {size_kb:.1f} KB")

        lines.append("=" * 50)

        return "\n".join(lines)

    def __str__(self) -> str:
        status = "SUCCESS" if self.success else "FAILED"
        return f"SimulationResult({status}, runtime={self.runtime:.1f}s)"
