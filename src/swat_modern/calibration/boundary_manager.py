"""
Calibration boundary manager.

Manages custom parameter boundaries for calibration, allowing users
to override default min/max ranges, enable/disable parameters,
and save/load configurations.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

from swat_modern.calibration.parameters import (
    CALIBRATION_PARAMETERS,
    PARAMETER_GROUPS,
    CalibrationParameter,
    ParameterSet,
)


@dataclass
class ParameterBoundary:
    """Custom boundary for a single calibration parameter."""
    name: str
    custom_min: Optional[float] = None
    custom_max: Optional[float] = None
    enabled: bool = True
    notes: str = ""

    @property
    def effective_min(self) -> float:
        """Get the effective minimum (custom or default)."""
        if self.custom_min is not None:
            return self.custom_min
        if self.name in CALIBRATION_PARAMETERS:
            return CALIBRATION_PARAMETERS[self.name].min_value
        return 0.0

    @property
    def effective_max(self) -> float:
        """Get the effective maximum (custom or default)."""
        if self.custom_max is not None:
            return self.custom_max
        if self.name in CALIBRATION_PARAMETERS:
            return CALIBRATION_PARAMETERS[self.name].max_value
        return 1.0

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "custom_min": self.custom_min,
            "custom_max": self.custom_max,
            "enabled": self.enabled,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ParameterBoundary":
        return cls(**data)


class BoundaryManager:
    """
    Manage custom calibration boundaries.

    Allows users to override default parameter ranges, enable/disable
    parameters, and perform batch operations by group.

    Example:
        >>> manager = BoundaryManager()
        >>> manager.set_boundary("CN2", min_value=-0.15, max_value=0.15)
        >>> manager.enable_parameter("ESCO", True)
        >>> manager.batch_set_group("snow", enabled=False)
        >>> param_set = manager.to_parameter_set()
    """

    def __init__(self):
        """Initialize with all default parameters disabled."""
        self._boundaries: Dict[str, ParameterBoundary] = {}

        # Initialize boundaries for all known parameters
        for name in CALIBRATION_PARAMETERS:
            self._boundaries[name] = ParameterBoundary(
                name=name,
                enabled=False,
            )

    def set_boundary(
        self,
        param_name: str,
        min_value: Optional[float] = None,
        max_value: Optional[float] = None,
    ) -> None:
        """
        Set custom min/max for a parameter.

        Args:
            param_name: Parameter name.
            min_value: Custom minimum value. None keeps default.
            max_value: Custom maximum value. None keeps default.
        """
        param_name = param_name.upper()
        if param_name not in self._boundaries:
            self._boundaries[param_name] = ParameterBoundary(name=param_name)

        boundary = self._boundaries[param_name]
        if min_value is not None:
            boundary.custom_min = min_value
        if max_value is not None:
            boundary.custom_max = max_value

    def reset_boundary(self, param_name: str) -> None:
        """Reset a parameter to default boundaries."""
        param_name = param_name.upper()
        if param_name in self._boundaries:
            self._boundaries[param_name].custom_min = None
            self._boundaries[param_name].custom_max = None

    def enable_parameter(self, param_name: str, enabled: bool = True) -> None:
        """Enable or disable a parameter for calibration."""
        param_name = param_name.upper()
        if param_name not in self._boundaries:
            self._boundaries[param_name] = ParameterBoundary(name=param_name)
        self._boundaries[param_name].enabled = enabled

    def batch_set_group(
        self,
        group: str,
        enabled: Optional[bool] = None,
        min_scale: float = 1.0,
        max_scale: float = 1.0,
    ) -> None:
        """
        Apply settings to all parameters in a group.

        Args:
            group: Parameter group name (hydrology, groundwater, etc.).
            enabled: Set all to enabled/disabled. None leaves unchanged.
            min_scale: Scale factor for min bounds (1.0 = no change).
            max_scale: Scale factor for max bounds (1.0 = no change).
        """
        group = group.lower()
        param_names = PARAMETER_GROUPS.get(group, [])

        for name in param_names:
            if name not in self._boundaries:
                continue

            boundary = self._boundaries[name]

            if enabled is not None:
                boundary.enabled = enabled

            if min_scale != 1.0:
                default_min = CALIBRATION_PARAMETERS[name].min_value
                boundary.custom_min = default_min * min_scale

            if max_scale != 1.0:
                default_max = CALIBRATION_PARAMETERS[name].max_value
                boundary.custom_max = default_max * max_scale

    def get_boundary(self, param_name: str) -> ParameterBoundary:
        """Get boundary for a parameter."""
        param_name = param_name.upper()
        if param_name not in self._boundaries:
            raise KeyError(f"Unknown parameter: {param_name}")
        return self._boundaries[param_name]

    @property
    def enabled_parameters(self) -> List[str]:
        """Get list of enabled parameter names."""
        return [name for name, b in self._boundaries.items() if b.enabled]

    @property
    def all_boundaries(self) -> Dict[str, ParameterBoundary]:
        """Get all boundaries."""
        return self._boundaries.copy()

    def to_parameter_set(self) -> ParameterSet:
        """
        Convert enabled boundaries to a ParameterSet for calibration.

        Returns:
            ParameterSet with only enabled parameters and custom bounds.
        """
        param_set = ParameterSet()

        for name, boundary in self._boundaries.items():
            if not boundary.enabled:
                continue
            if name not in CALIBRATION_PARAMETERS:
                continue

            param_set.add(
                name,
                min_value=boundary.effective_min,
                max_value=boundary.effective_max,
            )

        return param_set

    def get_summary_dataframe(self) -> "pd.DataFrame":
        """
        Return a DataFrame for display in the UI.

        Returns:
            DataFrame with columns: enabled, name, group, description,
            default_min, default_max, custom_min, custom_max, method, units
        """
        import pandas as pd

        rows = []
        for name, boundary in self._boundaries.items():
            if name not in CALIBRATION_PARAMETERS:
                continue

            param = CALIBRATION_PARAMETERS[name]
            rows.append({
                "enabled": boundary.enabled,
                "name": name,
                "group": param.group,
                "description": param.description,
                "default_min": param.min_value,
                "default_max": param.max_value,
                "custom_min": boundary.custom_min,
                "custom_max": boundary.custom_max,
                "method": param.method,
                "units": param.units,
                "sensitivity_rank": param.sensitivity_rank,
            })

        df = pd.DataFrame(rows)
        # Sort by sensitivity rank
        df["_sort"] = df["sensitivity_rank"].fillna(999).astype(int)
        df = df.sort_values("_sort").drop(columns=["_sort"]).reset_index(drop=True)
        return df

    def to_json(self, filepath: Optional[str] = None) -> str:
        """
        Save boundaries to JSON.

        Args:
            filepath: Path to save. If None, returns JSON string only.

        Returns:
            JSON string.
        """
        data = {
            "boundaries": {
                name: b.to_dict()
                for name, b in self._boundaries.items()
            }
        }

        json_str = json.dumps(data, indent=2)

        if filepath:
            with open(filepath, "w") as f:
                f.write(json_str)

        return json_str

    @classmethod
    def from_json(cls, filepath_or_string: str) -> "BoundaryManager":
        """
        Load boundaries from JSON file or string.

        Args:
            filepath_or_string: Path to JSON file or JSON string.

        Returns:
            BoundaryManager with loaded boundaries.
        """
        try:
            with open(filepath_or_string, "r") as f:
                data = json.load(f)
        except (FileNotFoundError, OSError):
            data = json.loads(filepath_or_string)

        manager = cls()

        for name, boundary_data in data.get("boundaries", {}).items():
            boundary = ParameterBoundary.from_dict(boundary_data)
            manager._boundaries[name.upper()] = boundary

        return manager

    def suggest_boundaries(
        self,
        watershed_characteristics: Optional[Dict] = None,
    ) -> Dict[str, Tuple[float, float]]:
        """
        AI-assisted boundary suggestion (placeholder).

        This method will use watershed area, dominant land use, soil type,
        and climate characteristics to narrow parameter ranges based on
        literature values and machine learning models.

        Currently returns default boundaries for all parameters.

        Args:
            watershed_characteristics: Dict with keys like:
                - area_km2: Watershed area
                - dominant_landuse: e.g., "forest", "agriculture", "urban"
                - dominant_soil_group: e.g., "A", "B", "C", "D"
                - climate: e.g., "humid", "semi-arid", "arid"
                - slope_mean: Average slope in degrees

        Returns:
            Dict mapping parameter name to (suggested_min, suggested_max).
        """
        # Placeholder: return default boundaries
        suggestions = {}
        for name, param in CALIBRATION_PARAMETERS.items():
            suggestions[name] = (param.min_value, param.max_value)

        return suggestions

    def __len__(self) -> int:
        return len(self.enabled_parameters)

    def __repr__(self) -> str:
        n_enabled = len(self.enabled_parameters)
        n_custom = sum(
            1 for b in self._boundaries.values()
            if b.custom_min is not None or b.custom_max is not None
        )
        return f"BoundaryManager({n_enabled} enabled, {n_custom} custom bounds)"
