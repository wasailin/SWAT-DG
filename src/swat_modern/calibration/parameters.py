"""
Calibration parameter definitions for SWAT models.

This module defines:
- CalibrationParameter: Dataclass for parameter specifications
- CALIBRATION_PARAMETERS: Default parameter definitions for SWAT2012
- Parameter groupings by process (hydrology, sediment, nutrient, etc.)

Example:
    >>> from swat_modern.calibration.parameters import get_default_parameters
    >>> params = get_default_parameters(group="hydrology")
    >>> for p in params:
    ...     print(f"{p.name}: [{p.min_value}, {p.max_value}]")
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Union, Any
import json


@dataclass
class CalibrationParameter:
    """
    Definition of a calibration parameter.

    Attributes:
        name: Parameter name (as used in SWAT files)
        file_type: File extension where parameter is stored (bsn, hru, gw, etc.)
        min_value: Minimum allowed value
        max_value: Maximum allowed value
        default_value: Default initial value
        method: Modification method - "replace", "multiply", or "add"
        description: Human-readable description
        group: Parameter group (hydrology, sediment, nutrient, etc.)
        distribution: Prior distribution for Bayesian methods ("uniform" or "normal")
        units: Parameter units (optional)
        sensitivity_rank: Typical sensitivity ranking (1=most sensitive)
        decimal_precision: Number of decimal places for physically meaningful
            formatting. Controls formatting when writing to SWAT files and
            rounding of sampled values during calibration.

    Example:
        >>> cn2 = CalibrationParameter(
        ...     name="CN2",
        ...     file_type="mgt",
        ...     min_value=-0.2,
        ...     max_value=0.2,
        ...     default_value=0.0,
        ...     method="multiply",
        ...     description="Curve number (relative change)",
        ...     group="hydrology"
        ... )
    """

    name: str
    file_type: str
    min_value: float
    max_value: float
    default_value: float = 0.0
    method: str = "replace"
    description: str = ""
    group: str = "general"
    distribution: str = "uniform"
    units: str = ""
    sensitivity_rank: Optional[int] = None
    decimal_precision: int = 4

    def __post_init__(self):
        """Validate parameter definition."""
        if self.min_value > self.max_value:
            raise ValueError(
                f"min_value ({self.min_value}) > max_value ({self.max_value}) "
                f"for parameter {self.name}"
            )

        valid_methods = ["replace", "multiply", "add"]
        if self.method not in valid_methods:
            raise ValueError(
                f"Invalid method '{self.method}'. Must be one of: {valid_methods}"
            )

        valid_distributions = ["uniform", "normal", "triangular"]
        if self.distribution not in valid_distributions:
            raise ValueError(
                f"Invalid distribution '{self.distribution}'. "
                f"Must be one of: {valid_distributions}"
            )

    def get_spotpy_parameter(self):
        """
        Convert to SPOTPY parameter format.

        Returns SPOTPY-compatible parameter definition.
        Requires spotpy to be installed.
        """
        try:
            import spotpy
        except ImportError:
            raise ImportError(
                "SPOTPY is required for calibration. "
                "Install with: pip install spotpy"
            )

        if self.distribution == "uniform":
            return spotpy.parameter.Uniform(
                name=self.name,
                low=self.min_value,
                high=self.max_value,
                optguess=self.default_value,
            )
        elif self.distribution == "normal":
            # For normal, min/max define 95% interval
            mean = (self.min_value + self.max_value) / 2
            std = (self.max_value - self.min_value) / 4  # ~95% within bounds
            return spotpy.parameter.Normal(
                name=self.name,
                mean=mean,
                stddev=std,
                optguess=self.default_value,
            )
        elif self.distribution == "triangular":
            return spotpy.parameter.Triangular(
                name=self.name,
                left=self.min_value,
                mode=self.default_value,
                right=self.max_value,
            )

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "name": self.name,
            "file_type": self.file_type,
            "min_value": self.min_value,
            "max_value": self.max_value,
            "default_value": self.default_value,
            "method": self.method,
            "description": self.description,
            "group": self.group,
            "distribution": self.distribution,
            "units": self.units,
            "sensitivity_rank": self.sensitivity_rank,
            "decimal_precision": self.decimal_precision,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "CalibrationParameter":
        """Create from dictionary."""
        # Handle older serialized data that may not include decimal_precision
        d = dict(data)
        d.setdefault("decimal_precision", 4)
        return cls(**d)


# =============================================================================
# Default SWAT2012 Calibration Parameters
# =============================================================================
# Based on commonly calibrated parameters in SWAT literature
# References:
# - Abbaspour, K.C. (2015). SWAT-CUP: SWAT Calibration and Uncertainty Programs
# - Arnold, J.G., et al. (2012). SWAT: Model Use, Calibration, and Validation
# - Neitsch, S.L., et al. (2011). SWAT Theoretical Documentation

CALIBRATION_PARAMETERS: Dict[str, CalibrationParameter] = {
    # =========================================================================
    # HYDROLOGY PARAMETERS
    # =========================================================================

    # Surface Runoff
    "CN2": CalibrationParameter(
        name="CN2",
        file_type="mgt",
        min_value=-0.25,
        max_value=0.25,
        default_value=0.0,
        method="multiply",
        description="SCS curve number for moisture condition II (relative change)",
        group="hydrology",
        sensitivity_rank=1,
        decimal_precision=2,
    ),
    "SURLAG": CalibrationParameter(
        name="SURLAG",
        file_type="bsn",
        min_value=0.5,
        max_value=24.0,
        default_value=4.0,
        method="replace",
        description="Surface runoff lag coefficient (days)",
        group="hydrology",
        units="days",
        sensitivity_rank=8,
        decimal_precision=2,
    ),
    "OV_N": CalibrationParameter(
        name="OV_N",
        file_type="hru",
        min_value=0.01,
        max_value=0.5,
        default_value=0.15,
        method="replace",
        description="Manning's n for overland flow",
        group="hydrology",
        sensitivity_rank=12,
        decimal_precision=3,
    ),

    # Evapotranspiration
    "ESCO": CalibrationParameter(
        name="ESCO",
        file_type="bsn",
        min_value=0.01,
        max_value=1.0,
        default_value=0.95,
        method="replace",
        description="Soil evaporation compensation factor",
        group="hydrology",
        sensitivity_rank=2,
        decimal_precision=2,
    ),
    "EPCO": CalibrationParameter(
        name="EPCO",
        file_type="bsn",
        min_value=0.01,
        max_value=1.0,
        default_value=1.0,
        method="replace",
        description="Plant uptake compensation factor",
        group="hydrology",
        sensitivity_rank=9,
        decimal_precision=2,
    ),
    "CANMX": CalibrationParameter(
        name="CANMX",
        file_type="hru",
        min_value=0.0,
        max_value=100.0,
        default_value=0.0,
        method="replace",
        description="Maximum canopy storage (mm)",
        group="hydrology",
        units="mm",
        sensitivity_rank=15,
        decimal_precision=1,
    ),

    # Groundwater
    "GW_DELAY": CalibrationParameter(
        name="GW_DELAY",
        file_type="gw",
        min_value=0.0,
        max_value=500.0,
        default_value=31.0,
        method="replace",
        description="Groundwater delay time (days)",
        group="groundwater",
        units="days",
        sensitivity_rank=3,
        decimal_precision=1,
    ),
    "ALPHA_BF": CalibrationParameter(
        name="ALPHA_BF",
        file_type="gw",
        min_value=0.0,
        max_value=1.0,
        default_value=0.048,
        method="replace",
        description="Baseflow alpha factor (1/days)",
        group="groundwater",
        units="1/days",
        sensitivity_rank=4,
        decimal_precision=3,
    ),
    "ALPHA_BF_D": CalibrationParameter(
        name="ALPHA_BF_D",
        file_type="gw",
        min_value=0.0,
        max_value=1.0,
        default_value=0.0,
        method="replace",
        description="Baseflow alpha factor for deep aquifer (1/days)",
        group="groundwater",
        units="1/days",
        sensitivity_rank=15,
        decimal_precision=4,
    ),
    "GWQMN": CalibrationParameter(
        name="GWQMN",
        file_type="gw",
        min_value=0.0,
        max_value=5000.0,
        default_value=1000.0,
        method="replace",
        description="Threshold water depth in shallow aquifer for return flow (mm)",
        group="groundwater",
        units="mm",
        sensitivity_rank=5,
        decimal_precision=0,
    ),
    "REVAPMN": CalibrationParameter(
        name="REVAPMN",
        file_type="gw",
        min_value=0.0,
        max_value=500.0,
        default_value=250.0,
        method="replace",
        description="Threshold water depth for revap to occur (mm)",
        group="groundwater",
        units="mm",
        sensitivity_rank=10,
        decimal_precision=0,
    ),
    "GW_REVAP": CalibrationParameter(
        name="GW_REVAP",
        file_type="gw",
        min_value=0.02,
        max_value=0.2,
        default_value=0.02,
        method="replace",
        description="Groundwater revap coefficient",
        group="groundwater",
        sensitivity_rank=11,
        decimal_precision=3,
    ),
    "RCHRG_DP": CalibrationParameter(
        name="RCHRG_DP",
        file_type="gw",
        min_value=0.0,
        max_value=1.0,
        default_value=0.05,
        method="replace",
        description="Deep aquifer percolation fraction",
        group="groundwater",
        sensitivity_rank=6,
        decimal_precision=3,
    ),
    "SHALLST": CalibrationParameter(
        name="SHALLST",
        file_type="gw",
        min_value=0.0,
        max_value=5000.0,
        default_value=1000.0,
        method="replace",
        description="Initial shallow aquifer storage (mm)",
        group="groundwater",
        units="mm",
        decimal_precision=0,
    ),
    "DEEPST": CalibrationParameter(
        name="DEEPST",
        file_type="gw",
        min_value=0.0,
        max_value=5000.0,
        default_value=1000.0,
        method="replace",
        description="Initial deep aquifer storage (mm)",
        group="groundwater",
        units="mm",
        decimal_precision=0,
    ),

    # Soil
    "SOL_AWC": CalibrationParameter(
        name="SOL_AWC",
        file_type="sol",
        min_value=-0.5,
        max_value=0.5,
        default_value=0.0,
        method="multiply",
        description="Available water capacity (relative change)",
        group="soil",
        sensitivity_rank=7,
        decimal_precision=3,
    ),
    "SOL_K": CalibrationParameter(
        name="SOL_K",
        file_type="sol",
        min_value=-0.5,
        max_value=0.5,
        default_value=0.0,
        method="multiply",
        description="Saturated hydraulic conductivity (relative change)",
        group="soil",
        units="mm/hr",
        sensitivity_rank=13,
        decimal_precision=2,
    ),
    "SOL_BD": CalibrationParameter(
        name="SOL_BD",
        file_type="sol",
        min_value=-0.5,
        max_value=0.5,
        default_value=0.0,
        method="multiply",
        description="Soil bulk density (relative change)",
        group="soil",
        units="g/cm3",
        decimal_precision=2,
    ),

    # Snow
    "SFTMP": CalibrationParameter(
        name="SFTMP",
        file_type="bsn",
        min_value=-5.0,
        max_value=5.0,
        default_value=1.0,
        method="replace",
        description="Snowfall temperature (C)",
        group="snow",
        units="C",
        decimal_precision=1,
    ),
    "SMTMP": CalibrationParameter(
        name="SMTMP",
        file_type="bsn",
        min_value=-5.0,
        max_value=5.0,
        default_value=0.5,
        method="replace",
        description="Snow melt base temperature (C)",
        group="snow",
        units="C",
        decimal_precision=1,
    ),
    "SMFMX": CalibrationParameter(
        name="SMFMX",
        file_type="bsn",
        min_value=0.0,
        max_value=10.0,
        default_value=4.5,
        method="replace",
        description="Maximum melt rate for snow on June 21 (mm H2O/C/day)",
        group="snow",
        units="mm/C/day",
        decimal_precision=1,
    ),
    "SMFMN": CalibrationParameter(
        name="SMFMN",
        file_type="bsn",
        min_value=0.0,
        max_value=10.0,
        default_value=4.5,
        method="replace",
        description="Minimum melt rate for snow on December 21 (mm H2O/C/day)",
        group="snow",
        units="mm/C/day",
        decimal_precision=1,
    ),
    "TIMP": CalibrationParameter(
        name="TIMP",
        file_type="bsn",
        min_value=0.0,
        max_value=1.0,
        default_value=1.0,
        method="replace",
        description="Snow pack temperature lag factor",
        group="snow",
        decimal_precision=2,
    ),

    # Channel Routing
    "CH_N2": CalibrationParameter(
        name="CH_N2",
        file_type="rte",
        min_value=0.01,
        max_value=0.3,
        default_value=0.05,
        method="replace",
        description="Manning's n for main channel",
        group="routing",
        sensitivity_rank=14,
        decimal_precision=3,
    ),
    "CH_K2": CalibrationParameter(
        name="CH_K2",
        file_type="rte",
        min_value=0.0,
        max_value=500.0,
        default_value=0.0,
        method="replace",
        description="Effective hydraulic conductivity of main channel (mm/hr)",
        group="routing",
        units="mm/hr",
        decimal_precision=2,
    ),

    # =========================================================================
    # SEDIMENT PARAMETERS
    # =========================================================================

    "USLE_P": CalibrationParameter(
        name="USLE_P",
        file_type="mgt",
        min_value=0.1,
        max_value=1.0,
        default_value=1.0,
        method="replace",
        description="USLE support practice factor",
        group="sediment",
        decimal_precision=2,
    ),
    "USLE_K": CalibrationParameter(
        name="USLE_K",
        file_type="sol",
        min_value=-0.5,
        max_value=0.5,
        default_value=0.0,
        method="multiply",
        description="USLE soil erodibility factor (relative change)",
        group="sediment",
        decimal_precision=3,
    ),
    "SPCON": CalibrationParameter(
        name="SPCON",
        file_type="bsn",
        min_value=0.0001,
        max_value=0.01,
        default_value=0.001,
        method="replace",
        description="Linear re-entrainment parameter for channel sediment",
        group="sediment",
        decimal_precision=4,
    ),
    "SPEXP": CalibrationParameter(
        name="SPEXP",
        file_type="bsn",
        min_value=1.0,
        max_value=2.0,
        default_value=1.0,
        method="replace",
        description="Exponent re-entrainment parameter for channel sediment",
        group="sediment",
        decimal_precision=2,
    ),
    "CH_COV1": CalibrationParameter(
        name="CH_COV1",
        file_type="rte",
        min_value=0.0,
        max_value=0.6,
        default_value=0.0,
        method="replace",
        description="Channel erodibility factor",
        group="sediment",
        decimal_precision=2,
    ),
    "CH_COV2": CalibrationParameter(
        name="CH_COV2",
        file_type="rte",
        min_value=0.0,
        max_value=1.0,
        default_value=0.0,
        method="replace",
        description="Channel cover factor",
        group="sediment",
        decimal_precision=2,
    ),
    "LAT_SED": CalibrationParameter(
        name="LAT_SED",
        file_type="hru",
        min_value=0.0,
        max_value=5000.0,
        default_value=0.0,
        method="replace",
        description="Lateral sediment concentration (mg/L)",
        group="sediment",
        units="mg/L",
        decimal_precision=1,
    ),
    "PRF": CalibrationParameter(
        name="PRF",
        file_type="bsn",
        min_value=0.0,
        max_value=2.0,
        default_value=1.0,
        method="replace",
        description="Peak rate adjustment factor for sediment routing in main channel",
        group="sediment",
        decimal_precision=2,
    ),
    "ADJ_PKR": CalibrationParameter(
        name="ADJ_PKR",
        file_type="bsn",
        min_value=0.5,
        max_value=2.0,
        default_value=1.0,
        method="replace",
        description="Peak rate adjustment for sediment routing in subbasin",
        group="sediment",
        decimal_precision=2,
    ),
    "SLSUBBSN": CalibrationParameter(
        name="SLSUBBSN",
        file_type="hru",
        min_value=-0.5,
        max_value=0.5,
        default_value=0.0,
        method="multiply",
        description="Average slope length (relative change)",
        group="sediment",
        units="m",
        decimal_precision=2,
    ),
    "FILTERW": CalibrationParameter(
        name="FILTERW",
        file_type="mgt",
        min_value=0.0,
        max_value=100.0,
        default_value=0.0,
        method="replace",
        description="Width of edge-of-field filter strip",
        group="sediment",
        units="m",
        decimal_precision=1,
    ),

    # =========================================================================
    # NUTRIENT PARAMETERS
    # =========================================================================

    # Nitrogen
    "CMN": CalibrationParameter(
        name="CMN",
        file_type="bsn",
        min_value=0.0001,
        max_value=0.003,
        default_value=0.0003,
        method="replace",
        description="Rate factor for humus mineralization of active organic N",
        group="nutrient",
        decimal_precision=4,
    ),
    "NPERCO": CalibrationParameter(
        name="NPERCO",
        file_type="bsn",
        min_value=0.0,
        max_value=1.0,
        default_value=0.2,
        method="replace",
        description="Nitrate percolation coefficient",
        group="nutrient",
        decimal_precision=2,
    ),
    "N_UPDIS": CalibrationParameter(
        name="N_UPDIS",
        file_type="bsn",
        min_value=0.0,
        max_value=100.0,
        default_value=20.0,
        method="replace",
        description="Nitrogen uptake distribution parameter",
        group="nutrient",
        decimal_precision=1,
    ),
    "CDN": CalibrationParameter(
        name="CDN",
        file_type="bsn",
        min_value=0.0,
        max_value=3.0,
        default_value=1.4,
        method="replace",
        description="Denitrification exponential rate coefficient",
        group="nutrient",
        decimal_precision=2,
    ),
    "SDNCO": CalibrationParameter(
        name="SDNCO",
        file_type="bsn",
        min_value=0.0,
        max_value=1.1,
        default_value=1.0,
        method="replace",
        description="Denitrification threshold water content",
        group="nutrient",
        decimal_precision=2,
    ),
    "ERORGN": CalibrationParameter(
        name="ERORGN",
        file_type="hru",
        min_value=0.0,
        max_value=5.0,
        default_value=0.0,
        method="replace",
        description="Organic N enrichment ratio",
        group="nutrient",
        decimal_precision=2,
    ),

    # Phosphorus
    "PPERCO": CalibrationParameter(
        name="PPERCO",
        file_type="bsn",
        min_value=10.0,
        max_value=17.5,
        default_value=10.0,
        method="replace",
        description="Phosphorus percolation coefficient",
        group="nutrient",
        decimal_precision=2,
    ),
    "PHOSKD": CalibrationParameter(
        name="PHOSKD",
        file_type="bsn",
        min_value=100.0,
        max_value=200.0,
        default_value=175.0,
        method="replace",
        description="Phosphorus soil partitioning coefficient",
        group="nutrient",
        decimal_precision=1,
    ),
    "PSP": CalibrationParameter(
        name="PSP",
        file_type="bsn",
        min_value=0.01,
        max_value=0.7,
        default_value=0.4,
        method="replace",
        description="Phosphorus availability index",
        group="nutrient",
        decimal_precision=2,
    ),
    "P_UPDIS": CalibrationParameter(
        name="P_UPDIS",
        file_type="bsn",
        min_value=0.0,
        max_value=100.0,
        default_value=20.0,
        method="replace",
        description="Phosphorus uptake distribution parameter",
        group="nutrient",
        decimal_precision=1,
    ),
    "ERORGP": CalibrationParameter(
        name="ERORGP",
        file_type="hru",
        min_value=0.0,
        max_value=5.0,
        default_value=0.0,
        method="replace",
        description="Organic P enrichment ratio",
        group="nutrient",
        decimal_precision=2,
    ),
    "GWSOLP": CalibrationParameter(
        name="GWSOLP",
        file_type="gw",
        min_value=0.0,
        max_value=0.5,
        default_value=0.0,
        method="replace",
        description="Soluble phosphorus concentration in groundwater loading",
        group="nutrient",
        units="mg/L",
        decimal_precision=3,
    ),

    # =========================================================================
    # PLANT GROWTH PARAMETERS
    # =========================================================================

    "BIOMIX": CalibrationParameter(
        name="BIOMIX",
        file_type="mgt",
        min_value=0.0,
        max_value=1.0,
        default_value=0.2,
        method="replace",
        description="Biological mixing efficiency",
        group="plant",
        decimal_precision=2,
    ),
}


class ParameterSet:
    """
    Collection of calibration parameters for a specific calibration setup.

    Manages a set of parameters, their values, and provides methods for
    serialization and application to SWAT models.

    Example:
        >>> params = ParameterSet()
        >>> params.add("CN2")  # Add with default settings
        >>> params.add("ESCO", min_value=0.5, max_value=1.0)  # Override bounds
        >>> params.set_values({"CN2": -0.1, "ESCO": 0.8})
        >>> params.apply_to_model(model)
    """

    def __init__(self, parameters: List[CalibrationParameter] = None):
        """
        Initialize parameter set.

        Args:
            parameters: Initial list of parameters (optional)
        """
        self._parameters: Dict[str, CalibrationParameter] = {}
        self._values: Dict[str, float] = {}

        if parameters:
            for p in parameters:
                self.add_parameter(p)

    def add(
        self,
        name: str,
        min_value: float = None,
        max_value: float = None,
        default_value: float = None,
        method: str = None,
    ) -> None:
        """
        Add a parameter by name from defaults, optionally overriding bounds.

        Args:
            name: Parameter name (must exist in CALIBRATION_PARAMETERS)
            min_value: Override minimum value
            max_value: Override maximum value
            default_value: Override default value
            method: Override modification method
        """
        name = name.upper()

        if name not in CALIBRATION_PARAMETERS:
            available = list(CALIBRATION_PARAMETERS.keys())[:10]
            raise ValueError(
                f"Unknown parameter '{name}'. "
                f"Available: {available}... ({len(CALIBRATION_PARAMETERS)} total)"
            )

        # Get default definition
        default = CALIBRATION_PARAMETERS[name]

        # Create new parameter with overrides
        param = CalibrationParameter(
            name=name,
            file_type=default.file_type,
            min_value=min_value if min_value is not None else default.min_value,
            max_value=max_value if max_value is not None else default.max_value,
            default_value=default_value if default_value is not None else default.default_value,
            method=method if method is not None else default.method,
            description=default.description,
            group=default.group,
            distribution=default.distribution,
            units=default.units,
            sensitivity_rank=default.sensitivity_rank,
            decimal_precision=default.decimal_precision,
        )

        self.add_parameter(param)

    def add_parameter(self, parameter: CalibrationParameter) -> None:
        """Add a CalibrationParameter object."""
        self._parameters[parameter.name] = parameter
        self._values[parameter.name] = parameter.default_value

    def remove(self, name: str) -> None:
        """Remove a parameter."""
        name = name.upper()
        if name in self._parameters:
            del self._parameters[name]
            del self._values[name]

    def get_parameter(self, name: str) -> CalibrationParameter:
        """Get parameter definition."""
        name = name.upper()
        if name not in self._parameters:
            raise KeyError(f"Parameter '{name}' not in set")
        return self._parameters[name]

    @property
    def names(self) -> List[str]:
        """Get list of parameter names."""
        return list(self._parameters.keys())

    @property
    def values(self) -> Dict[str, float]:
        """Get current parameter values."""
        return self._values.copy()

    def set_values(self, values: Dict[str, float]) -> None:
        """
        Set parameter values.

        Args:
            values: Dictionary of {parameter_name: value}
        """
        for name, value in values.items():
            name = name.upper()
            if name not in self._parameters:
                raise KeyError(f"Unknown parameter: {name}")

            param = self._parameters[name]

            # Validate bounds (with small tolerance for floating point)
            if value < param.min_value - 1e-10 or value > param.max_value + 1e-10:
                raise ValueError(
                    f"Value {value} for {name} out of bounds "
                    f"[{param.min_value}, {param.max_value}]"
                )

            self._values[name] = value

    def set_value(self, name: str, value: float) -> None:
        """Set a single parameter value."""
        self.set_values({name: value})

    # Basin-wide file types that have a single file (not per-subbasin)
    BASIN_WIDE_TYPES: Set[str] = {"bsn"}

    # Parameters that have per-HRU equivalents in .hru files.
    # When subbasin_ids is specified, these are automatically redirected
    # to the .hru version so they can vary spatially.
    BSN_TO_HRU_MAP: Dict[str, str] = {
        "ESCO": "ESCO_HRU",
        "EPCO": "EPCO_HRU",
    }

    def apply_to_model(
        self,
        model,
        subbasin_ids: Optional[List[int]] = None,
    ) -> None:
        """
        Apply current parameter values to a SWAT model.

        Args:
            model: SWATModel instance
            subbasin_ids: If specified, only modify files for these subbasins.
                For basin-wide parameters (.bsn), the single file is always
                modified UNLESS a per-HRU equivalent exists (e.g., ESCO ->
                ESCO_HRU), in which case the per-HRU version is used to
                allow spatial variation.
        """
        for name, value in self._values.items():
            param = self._parameters[name]
            precision = param.decimal_precision

            if subbasin_ids is not None:
                # Check if this basin-wide param has a per-HRU equivalent
                if (
                    param.file_type in self.BASIN_WIDE_TYPES
                    and name in self.BSN_TO_HRU_MAP
                ):
                    # Use original name because .hru file label is "ESCO",
                    # not "ESCO_HRU". The _modify_file() searches for the
                    # label string in each line.
                    for sub_id in subbasin_ids:
                        model.modify_parameter(
                            param_name=name,
                            value=value,
                            file_type="hru",
                            method=param.method,
                            unit_id=sub_id,
                            decimal_precision=precision,
                        )
                elif param.file_type not in self.BASIN_WIDE_TYPES:
                    # Per-unit param: apply only to specified subbasins
                    for sub_id in subbasin_ids:
                        model.modify_parameter(
                            param_name=name,
                            value=value,
                            file_type=param.file_type,
                            method=param.method,
                            unit_id=sub_id,
                            decimal_precision=precision,
                        )
                else:
                    # Basin-wide param with no per-HRU equivalent:
                    # apply globally (no spatial variation possible)
                    model.modify_parameter(
                        param_name=name,
                        value=value,
                        file_type=param.file_type,
                        method=param.method,
                        decimal_precision=precision,
                    )
            else:
                # Original behavior: modify all files
                model.modify_parameter(
                    param_name=name,
                    value=value,
                    file_type=param.file_type,
                    method=param.method,
                    decimal_precision=precision,
                )
                # Also modify HRU-level override if this is a basin-wide
                # param that can also exist per-HRU (e.g. ESCO → ESCO_HRU).
                # Many QSWAT/ArcSWAT models read from .hru, ignoring .bsn.
                if (
                    param.file_type in self.BASIN_WIDE_TYPES
                    and name in self.BSN_TO_HRU_MAP
                ):
                    # Use original name because .hru file label is "ESCO",
                    # not "ESCO_HRU". The _modify_file() searches for the
                    # label string in each line.
                    model.modify_parameter(
                        param_name=name,
                        value=value,
                        file_type="hru",
                        method=param.method,
                        decimal_precision=precision,
                    )

    def get_spotpy_parameters(self) -> list:
        """Get list of SPOTPY parameter objects."""
        return [p.get_spotpy_parameter() for p in self._parameters.values()]

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "parameters": {
                name: param.to_dict()
                for name, param in self._parameters.items()
            },
            "values": self._values.copy(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ParameterSet":
        """Create from dictionary."""
        params = [
            CalibrationParameter.from_dict(p)
            for p in data["parameters"].values()
        ]
        pset = cls(params)
        pset.set_values(data.get("values", {}))
        return pset

    def to_json(self, filepath: str = None) -> str:
        """Save to JSON file or return JSON string."""
        json_str = json.dumps(self.to_dict(), indent=2)
        if filepath:
            with open(filepath, 'w') as f:
                f.write(json_str)
        return json_str

    @classmethod
    def from_json(cls, filepath_or_string: str) -> "ParameterSet":
        """Load from JSON file or string."""
        try:
            # Try as file first
            with open(filepath_or_string, 'r') as f:
                data = json.load(f)
        except (FileNotFoundError, OSError):
            # Try as JSON string
            data = json.loads(filepath_or_string)
        return cls.from_dict(data)

    def __len__(self) -> int:
        return len(self._parameters)

    def __contains__(self, name: str) -> bool:
        return name.upper() in self._parameters

    def __iter__(self):
        return iter(self._parameters.values())

    def __repr__(self) -> str:
        return f"ParameterSet({len(self)} parameters: {', '.join(self.names)})"


def get_default_parameters(
    group: str = None,
    top_n: int = None,
) -> List[CalibrationParameter]:
    """
    Get default calibration parameters.

    Args:
        group: Filter by group (hydrology, groundwater, sediment, nutrient, etc.)
        top_n: Return only top N most sensitive parameters

    Returns:
        List of CalibrationParameter objects

    Example:
        >>> # Get all hydrology parameters
        >>> params = get_default_parameters(group="hydrology")

        >>> # Get top 10 most sensitive parameters
        >>> params = get_default_parameters(top_n=10)
    """
    params = list(CALIBRATION_PARAMETERS.values())

    # Filter by group
    if group is not None:
        group = group.lower()
        params = [p for p in params if p.group == group]

    # Sort by sensitivity and take top N
    if top_n is not None:
        # Sort by sensitivity_rank (None values at end)
        params = sorted(
            params,
            key=lambda p: p.sensitivity_rank if p.sensitivity_rank else 999
        )
        params = params[:top_n]

    return params


def get_streamflow_parameters() -> List[CalibrationParameter]:
    """
    Get recommended parameters for streamflow calibration.

    Returns the most sensitive parameters for streamflow simulation.
    """
    names = [
        "CN2", "ESCO", "GW_DELAY", "ALPHA_BF", "GWQMN",
        "RCHRG_DP", "SOL_AWC", "SURLAG", "EPCO", "REVAPMN"
    ]
    return [CALIBRATION_PARAMETERS[n] for n in names]


def get_sediment_parameters() -> List[CalibrationParameter]:
    """
    Get recommended parameters for sediment calibration.

    Returns parameters for sediment yield simulation.
    """
    names = [
        "USLE_P", "USLE_K", "SPCON", "SPEXP",
        "CH_COV1", "CH_COV2", "LAT_SED", "PRF", "ADJ_PKR", "SLSUBBSN"
    ]
    return [CALIBRATION_PARAMETERS[n] for n in names]


def get_nutrient_parameters() -> List[CalibrationParameter]:
    """
    Get recommended parameters for nutrient calibration.

    Returns parameters for nitrogen and phosphorus simulation.
    """
    names = [
        "CMN", "NPERCO", "N_UPDIS", "CDN", "SDNCO",
        "PPERCO", "PHOSKD", "PSP", "P_UPDIS",
        "ERORGN", "ERORGP"
    ]
    return [CALIBRATION_PARAMETERS[n] for n in names]


# Parameter groups for reference
PARAMETER_GROUPS = {
    "hydrology": ["CN2", "ESCO", "EPCO", "SURLAG", "OV_N", "CANMX"],
    "groundwater": ["GW_DELAY", "ALPHA_BF", "ALPHA_BF_D", "GWQMN", "REVAPMN",
                    "GW_REVAP", "RCHRG_DP", "SHALLST", "DEEPST"],
    "soil": ["SOL_AWC", "SOL_K", "SOL_BD"],
    "snow": ["SFTMP", "SMTMP", "SMFMX", "SMFMN", "TIMP"],
    "routing": ["CH_N2", "CH_K2"],
    "sediment": ["USLE_P", "USLE_K", "SPCON", "SPEXP", "CH_COV1", "CH_COV2", "LAT_SED",
                 "PRF", "ADJ_PKR", "SLSUBBSN", "FILTERW"],
    "nutrient": ["CMN", "NPERCO", "N_UPDIS", "CDN", "SDNCO",
                 "PPERCO", "PHOSKD", "PSP", "P_UPDIS", "ERORGN", "ERORGP", "GWSOLP"],
    "plant": ["BIOMIX"],
}


def get_nitrogen_parameters() -> List[CalibrationParameter]:
    """Get recommended parameters for nitrogen calibration.

    Returns parameters specifically for nitrogen simulation.
    Subset of nutrient parameters focusing on N processes.
    """
    names = ["CMN", "NPERCO", "N_UPDIS", "CDN", "SDNCO", "ERORGN"]
    return [CALIBRATION_PARAMETERS[n] for n in names]


def get_phosphorus_parameters() -> List[CalibrationParameter]:
    """Get recommended parameters for phosphorus calibration.

    Returns parameters specifically for phosphorus simulation.
    Subset of nutrient parameters focusing on P processes.
    """
    names = ["PPERCO", "PHOSKD", "PSP", "P_UPDIS", "ERORGP", "GWSOLP"]
    return [CALIBRATION_PARAMETERS[n] for n in names]


CONSTITUENT_PHASES = {
    "streamflow": {
        "parameters_func": get_streamflow_parameters,
        "output_variable": "FLOW_OUT",
        "description": "Streamflow calibration (hydrology)",
        "default_iterations": 5000,
        "default_objective": "kge",
    },
    "sediment": {
        "parameters_func": get_sediment_parameters,
        "output_variable": "SED_OUT",
        "description": "Sediment yield calibration",
        "default_iterations": 2000,
        "default_objective": "nse",
    },
    "nitrogen": {
        "parameters_func": get_nitrogen_parameters,
        "output_variable": "TOT_N",
        "description": "Total nitrogen calibration",
        "default_iterations": 2000,
        "default_objective": "nse",
    },
    "phosphorus": {
        "parameters_func": get_phosphorus_parameters,
        "output_variable": "TOT_P",
        "description": "Total phosphorus calibration",
        "default_iterations": 2000,
        "default_objective": "nse",
    },
}
