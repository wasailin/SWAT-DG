"""
Read current calibration parameter values from SWAT project files.

Uses batched file reading for efficiency — groups parameters by file type
and reads each file only once, extracting all relevant parameters per pass.

This reduces I/O from O(parameters × files) to O(files).
"""

from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import pandas as pd

from swat_modern.calibration.parameters import (
    CALIBRATION_PARAMETERS,
    PARAMETER_GROUPS,
    CalibrationParameter,
)
from swat_modern.io.generators.parameter_modifier import (
    PARAMETER_LOCATIONS,
    ParameterModifier,
)


class ProjectParameterReader:
    """
    Read all calibration-relevant parameter values from a SWAT project.

    For per-unit parameters (HRU, subbasin), returns the mean, min,
    and max across all units.

    Uses batched I/O: files of the same type are opened once and all
    relevant parameters are extracted in a single pass.

    Example:
        >>> reader = ProjectParameterReader("C:/swat_project")
        >>> df = reader.read_all_parameters()
        >>> print(df[['name', 'current_mean', 'current_min', 'current_max']])
    """

    def __init__(self, project_dir: Union[str, Path]):
        self.project_dir = Path(project_dir)
        if not self.project_dir.exists():
            raise FileNotFoundError(f"Project directory not found: {self.project_dir}")

        self._cache: Optional[pd.DataFrame] = None

    def read_all_parameters(self) -> pd.DataFrame:
        """
        Read current values of all 45 calibration parameters.

        Groups parameters by file type, globs each type once, and reads
        each file in a single pass to extract all matching parameters.

        Returns:
            DataFrame with columns:
                name, file_type, group, description, method,
                default_min, default_max, default_value,
                current_mean, current_min, current_max, current_count,
                sensitivity_rank, units
        """
        if self._cache is not None:
            return self._cache

        # Group parameters by file type for batched reading
        params_by_type: Dict[str, List[str]] = {}
        param_file_types: Dict[str, str] = {}

        for name, param in CALIBRATION_PARAMETERS.items():
            if name in PARAMETER_LOCATIONS:
                file_type = PARAMETER_LOCATIONS[name][0]
            else:
                file_type = param.file_type

            param_file_types[name] = file_type
            params_by_type.setdefault(file_type, []).append(name)

        # Batch-read: {param_name: {unit_id: value}}
        all_values: Dict[str, Dict] = {name: {} for name in CALIBRATION_PARAMETERS}

        for file_type, param_names in params_by_type.items():
            files = list(self.project_dir.glob(f"*.{file_type}"))
            param_names_upper = {n.upper() for n in param_names}

            for file_path in files:
                # Extract unit ID from filename (e.g. "000010001" -> 10001)
                try:
                    file_unit_id = int(file_path.stem[:5])
                except (ValueError, IndexError):
                    file_unit_id = file_path.stem

                try:
                    extracted = self._read_multiple_parameters(
                        file_path, param_names_upper
                    )
                except Exception:
                    continue

                for pname, value in extracted.items():
                    if value is not None:
                        all_values[pname][file_unit_id] = value

        # Build result rows
        rows = []
        for name, param in CALIBRATION_PARAMETERS.items():
            values_dict = all_values[name]
            numeric_values = [
                v for v in values_dict.values() if isinstance(v, (int, float))
            ]

            if numeric_values:
                current_mean = sum(numeric_values) / len(numeric_values)
                current_min = min(numeric_values)
                current_max = max(numeric_values)
                current_count = len(numeric_values)
            else:
                current_mean = None
                current_min = None
                current_max = None
                current_count = 0

            rows.append({
                "name": name,
                "file_type": param_file_types[name],
                "group": param.group,
                "description": param.description,
                "method": param.method,
                "default_min": param.min_value,
                "default_max": param.max_value,
                "default_value": param.default_value,
                "current_mean": current_mean,
                "current_min": current_min,
                "current_max": current_max,
                "current_count": current_count,
                "sensitivity_rank": param.sensitivity_rank,
                "units": param.units,
            })

        df = pd.DataFrame(rows)
        df["_sort_key"] = df["sensitivity_rank"].fillna(999).astype(int)
        df = df.sort_values("_sort_key").drop(columns=["_sort_key"]).reset_index(drop=True)

        self._cache = df
        return df

    def read_parameter(
        self,
        param_name: str,
    ) -> Dict[str, Any]:
        """
        Read a single parameter with per-unit values.

        Args:
            param_name: Parameter name (e.g., "CN2").

        Returns:
            Dict with keys: name, values (dict of unit_id->value),
            mean, min, max, file_type.
        """
        param_name = param_name.upper()

        if param_name not in CALIBRATION_PARAMETERS:
            raise ValueError(f"Unknown parameter: {param_name}")

        param = CALIBRATION_PARAMETERS[param_name]

        # Determine file type
        if param_name in PARAMETER_LOCATIONS:
            file_type = PARAMETER_LOCATIONS[param_name][0]
        else:
            file_type = param.file_type

        try:
            modifier = ParameterModifier(self.project_dir)
            values = modifier.get_parameter(param_name, file_type=file_type)
        except Exception:
            values = {}

        if isinstance(values, dict):
            numeric_values = [v for v in values.values() if isinstance(v, (int, float))]
        elif isinstance(values, (int, float)):
            numeric_values = [values]
            values = {"basin": values}
        else:
            numeric_values = []
            values = {}

        result = {
            "name": param_name,
            "values": values,
            "file_type": file_type,
        }

        if numeric_values:
            result["mean"] = sum(numeric_values) / len(numeric_values)
            result["min"] = min(numeric_values)
            result["max"] = max(numeric_values)
            result["count"] = len(numeric_values)
        else:
            result["mean"] = None
            result["min"] = None
            result["max"] = None
            result["count"] = 0

        return result

    def get_parameter_groups(self) -> Dict[str, List[str]]:
        """Return parameter group definitions."""
        return PARAMETER_GROUPS.copy()

    # -------------------------------------------------------------------------
    # Private
    # -------------------------------------------------------------------------

    @staticmethod
    def _read_multiple_parameters(
        file_path: Path,
        param_names: set,
    ) -> Dict[str, Optional[float]]:
        """
        Read multiple parameters from a single file in one pass.

        Scans each line for the ``value | NAME`` SWAT format and extracts
        the numeric value for any parameter whose name matches the set.

        Args:
            file_path: Path to a SWAT input file.
            param_names: Set of uppercase parameter names to look for.

        Returns:
            Dict mapping parameter name to its numeric value.
        """
        results: Dict[str, Optional[float]] = {}
        remaining = set(param_names)

        with open(file_path, "r") as f:
            for line in f:
                if not remaining:
                    break  # found all params, stop early

                if "|" not in line:
                    continue

                parts = line.split("|")
                if len(parts) < 2:
                    continue

                # Extract parameter name from the comment part after |
                comment = parts[1].strip().upper()
                comment_words = comment.split()
                if not comment_words:
                    continue

                first_word = comment_words[0].rstrip(":")

                if first_word in remaining:
                    try:
                        value = float(parts[0].strip())
                        results[first_word] = value
                        remaining.discard(first_word)
                    except ValueError:
                        pass

        return results
