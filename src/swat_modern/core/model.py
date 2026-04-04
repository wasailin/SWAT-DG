"""
SWAT Model wrapper class for running SWAT2012 simulations from Python.

This module provides a high-level interface for:
- Running SWAT simulations
- Modifying input parameters
- Reading output files
- Managing SWAT projects
"""

import os
import shutil
from pathlib import Path
from typing import Dict, List, Optional, Union
import subprocess
import pandas as pd

from swat_modern.core.config import SWATConfig
from swat_modern.core.results import SimulationResult
from swat_modern.core.runner import SWATRunner


class SWATModel:
    """
    Main class for interacting with SWAT2012 model.

    This class provides a simple interface to:
    - Load SWAT projects
    - Run simulations
    - Modify parameters
    - Read outputs

    Example:
        >>> model = SWATModel("C:/my_watershed")
        >>> model.run()
        >>> flow = model.get_output("FLOW_OUT", output_type="rch")

    Attributes:
        project_dir: Path to the SWAT project directory
        config: SWATConfig object with project settings
        executable: Path to SWAT executable
    """

    def __init__(
        self,
        project_dir: Union[str, Path],
        executable: Optional[Union[str, Path]] = None,
    ):
        """
        Initialize SWAT model wrapper.

        Args:
            project_dir: Path to directory containing SWAT input files
            executable: Path to SWAT executable (optional, will search if not provided)

        Raises:
            FileNotFoundError: If project directory doesn't exist
            ValueError: If file.cio not found in project directory
        """
        self.project_dir = Path(project_dir).resolve()

        if not self.project_dir.exists():
            raise FileNotFoundError(f"Project directory not found: {self.project_dir}")

        # Check for file.cio (master input file)
        self.cio_path = self.project_dir / "file.cio"
        if not self.cio_path.exists():
            raise ValueError(
                f"file.cio not found in {self.project_dir}. "
                "This doesn't appear to be a valid SWAT project directory."
            )

        # Find or set executable
        self.executable = self._find_executable(executable)

        # Load configuration
        self.config = SWATConfig(self.project_dir)

        # Runner for executing simulations
        self._runner = SWATRunner(self.executable, self.project_dir)

        # Store last simulation result
        self._last_result: Optional[SimulationResult] = None

    def _find_executable(
        self, executable: Optional[Union[str, Path]] = None
    ) -> Path:
        """Find SWAT executable, searching common locations if not provided."""
        if executable is not None:
            exe_path = Path(executable)
            if exe_path.exists():
                return exe_path.resolve()
            raise FileNotFoundError(f"SWAT executable not found: {executable}")

        # Search common locations (prefer custom calibration exe first)
        search_paths = [
            self.project_dir / "swat_681_calib_ifx.exe",
            self.project_dir / "swat_692_calib_ifx.exe",
            self.project_dir / "swat_64calib_ifx.exe",
            self.project_dir / "swat_64calib.exe",
            self.project_dir / "swat2012.exe",
            self.project_dir / "swat.exe",
            self.project_dir / "swat_64rel.exe",
            self.project_dir / "SWAT_Rev681.exe",
            Path(os.environ.get("SWAT_EXE", "")) if os.environ.get("SWAT_EXE") else None,
        ]

        # Also check parent directory
        search_paths.extend([
            self.project_dir.parent / "swat_681_calib_ifx.exe",
            self.project_dir.parent / "swat_692_calib_ifx.exe",
            self.project_dir.parent / "swat_64calib_ifx.exe",
            self.project_dir.parent / "swat_64calib.exe",
            self.project_dir.parent / "swat2012.exe",
            self.project_dir.parent / "swat_64rel.exe",
            self.project_dir.parent / "SWAT_Rev681.exe",
        ])

        for path in search_paths:
            if path and path.exists():
                return path.resolve()

        # Raise helpful error if not found
        raise FileNotFoundError(
            "SWAT executable not found. Please provide the path to the executable:\n"
            "  model = SWATModel('project_dir', executable='path/to/swat.exe')\n"
            "Or set the SWAT_EXE environment variable."
        )

    def run(
        self,
        timeout: Optional[int] = None,
        capture_output: bool = True,
        cancel_event=None,
        cancel_file: Optional[str] = None,
    ) -> SimulationResult:
        """
        Run SWAT simulation.

        Args:
            timeout: Maximum time in seconds to wait for simulation (None = no limit)
            capture_output: Whether to capture stdout/stderr
            cancel_event: Optional threading.Event; when set the running
                SWAT process is terminated for cooperative cancellation.
            cancel_file: Optional file path; when the file exists the
                running SWAT process is terminated.  Used for cross-process
                cancellation (e.g. ensemble workers).

        Returns:
            SimulationResult object with simulation status and outputs

        Example:
            >>> model = SWATModel("C:/my_watershed")
            >>> result = model.run()
            >>> if result.success:
            ...     print("Simulation completed successfully!")
        """
        print(f"Running SWAT simulation in: {self.project_dir}")

        result = self._runner.run(
            timeout=timeout,
            capture_output=capture_output,
            cancel_event=cancel_event,
            cancel_file=cancel_file,
        )
        self._last_result = result

        if result.success:
            print(f"Simulation completed in {result.runtime:.1f} seconds")
        else:
            print(f"Simulation failed: {result.error_message}")

        return result

    def get_output(
        self,
        variable: str,
        output_type: str = "rch",
        unit_id: Optional[int] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> pd.DataFrame:
        """
        Get output data from simulation results.

        Args:
            variable: Variable name (e.g., "FLOW_OUT", "SED_OUT", "NO3_OUT")
            output_type: Output file type - "rch" (reach), "sub" (subbasin), or "hru"
            unit_id: Specific reach/subbasin/HRU number (None = all)
            start_date: Start date filter (YYYY-MM-DD format)
            end_date: End date filter (YYYY-MM-DD format)

        Returns:
            DataFrame with requested output data

        Example:
            >>> flow = model.get_output("FLOW_OUT", output_type="rch", unit_id=1)
            >>> print(flow.head())
        """
        from swat_modern.io.parsers.output_parser import OutputParser

        output_file = self.project_dir / f"output.{output_type}"

        if not output_file.exists():
            raise FileNotFoundError(
                f"Output file not found: {output_file}\n"
                "Make sure to run the simulation first with model.run()"
            )

        parser = OutputParser(output_file)
        df = parser.parse()

        # Filter by variable (support fuzzy match for names without unit suffix,
        # e.g. "FLOW_OUT" matches "FLOW_OUTcms")
        if variable not in df.columns:
            matches = [c for c in df.columns if c.startswith(variable)]
            if len(matches) == 1:
                variable = matches[0]
            elif len(matches) > 1:
                # Prefer exact prefix match (shortest)
                variable = min(matches, key=len)
            else:
                available = [c for c in df.columns if not c.startswith("_")]
                raise ValueError(
                    f"Variable '{variable}' not found. Available variables:\n"
                    f"  {', '.join(available[:10])}..."
                )

        # Select columns
        columns = ["RCH" if output_type == "rch" else "SUB", "YEAR", "MON", "DAY", variable]
        columns = [c for c in columns if c in df.columns]
        result = df[columns].copy()

        # Filter by unit ID
        if unit_id is not None:
            id_col = "RCH" if output_type == "rch" else "SUB"
            if id_col in result.columns:
                result = result[result[id_col] == unit_id]

        return result

    def modify_parameter(
        self,
        param_name: str,
        value: float,
        file_type: str = "bsn",
        method: str = "replace",
        unit_id: Optional[int] = None,
        decimal_precision: int = 4,
    ) -> None:
        """
        Modify a model parameter in input files.

        Args:
            param_name: Parameter name (e.g., "CN2", "ESCO", "GW_DELAY")
            value: New value for the parameter
            file_type: File type containing parameter ("bsn", "hru", "gw", etc.)
            method: Modification method - "replace", "multiply", or "add"
            unit_id: Specific unit to modify (None = all)
            decimal_precision: Number of decimal places for formatting (default 4)

        Example:
            >>> model.modify_parameter("ESCO", 0.9, file_type="hru")
            >>> model.modify_parameter("CN2", -0.1, method="multiply")  # Reduce CN2 by 10%
        """
        from swat_modern.io.generators.parameter_modifier import ParameterModifier

        modifier = ParameterModifier(self.project_dir)
        n_modified = modifier.modify(
            param_name=param_name,
            value=value,
            file_type=file_type,
            method=method,
            unit_id=unit_id,
            decimal_precision=decimal_precision,
        )
        print(f"Modified {param_name} = {value} ({method}) in {file_type} files")
        if n_modified == 0:
            import warnings
            warnings.warn(
                f"Parameter '{param_name}' was not found in any .{file_type} file. "
                f"The SWAT input files may use a format without parameter labels."
            )

    def get_parameter(
        self,
        param_name: str,
        file_type: str = "bsn",
        unit_id: Optional[int] = None,
    ) -> Union[float, Dict[int, float]]:
        """
        Get current value of a parameter.

        Args:
            param_name: Parameter name
            file_type: File type containing parameter
            unit_id: Specific unit (None = return all units)

        Returns:
            Parameter value(s) - single float if unit_id specified, dict otherwise
        """
        from swat_modern.io.generators.parameter_modifier import ParameterParser

        parser = ParameterParser(self.project_dir)
        return parser.get_parameter(param_name, file_type, unit_id)

    # All file types that contain modifiable SWAT parameters
    ALL_INPUT_EXTENSIONS = [
        ".cio", ".bsn", ".sub", ".hru", ".gw", ".rte", ".sol", ".mgt", ".fig",
    ]

    def backup(
        self,
        backup_dir: Optional[Union[str, Path]] = None,
        file_types: Optional[List[str]] = None,
    ) -> Path:
        """
        Create backup of current project state.

        Args:
            backup_dir: Directory to store backup (default: project_dir/backup_YYYYMMDD_HHMMSS)
            file_types: If specified, only back up these file extensions
                (e.g. ``["gw", "bsn"]``).  When ``None``, backs up all
                input file types.

        Returns:
            Path to backup directory
        """
        from datetime import datetime

        if backup_dir is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_dir = self.project_dir / f"backup_{timestamp}"
        else:
            backup_dir = Path(backup_dir)

        backup_dir.mkdir(parents=True, exist_ok=True)

        if file_types is not None:
            extensions = [f".{ft.lstrip('.')}" for ft in file_types]
        else:
            extensions = self.ALL_INPUT_EXTENSIONS

        for ext in extensions:
            for f in self.project_dir.glob(f"*{ext}"):
                shutil.copy2(f, backup_dir / f.name)

        print(f"Backup created: {backup_dir} ({len(extensions)} file types)")
        return backup_dir

    def restore(
        self,
        backup_dir: Union[str, Path],
        file_types: Optional[List[str]] = None,
    ) -> None:
        """
        Restore project from backup.

        Args:
            backup_dir: Path to backup directory
            file_types: If specified, only restore files with these extensions
                (e.g. ``["gw", "bsn"]``).  When ``None``, restores everything
                in the backup directory.
        """
        backup_dir = Path(backup_dir)

        if not backup_dir.exists():
            raise FileNotFoundError(f"Backup directory not found: {backup_dir}")

        if file_types is not None:
            suffixes = {f".{ft.lstrip('.')}" for ft in file_types}
            for f in backup_dir.glob("*"):
                if f.is_file() and f.suffix in suffixes:
                    shutil.copy2(f, self.project_dir / f.name)
            # Skip config reload when .cio was not restored (common fast path)
            if ".cio" in suffixes:
                self.config = SWATConfig(self.project_dir)
        else:
            for f in backup_dir.glob("*"):
                if f.is_file():
                    shutil.copy2(f, self.project_dir / f.name)
            # Reload configuration
            self.config = SWATConfig(self.project_dir)

    def __repr__(self) -> str:
        return f"SWATModel('{self.project_dir}')"
