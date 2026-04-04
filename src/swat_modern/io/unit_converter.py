"""
Unit conversion utilities for hydrological data.

Handles conversion between common units used in USGS observations
and SWAT model outputs.
"""

from typing import Optional, Union

import numpy as np
import pandas as pd


# Direct conversion factors: (from_unit, to_unit) -> factor
# Multiply source value by factor to get target value
CONVERSION_FACTORS = {
    # Flow
    ("cfs", "m3/s"): 0.0283168,
    ("m3/s", "cfs"): 35.3147,
    ("cfs", "cms"): 0.0283168,
    ("cms", "cfs"): 35.3147,
    ("l/s", "m3/s"): 0.001,
    ("m3/s", "l/s"): 1000.0,
    ("cfs", "l/s"): 28.3168,

    # Length
    ("ft", "m"): 0.3048,
    ("m", "ft"): 3.28084,
    ("in", "mm"): 25.4,
    ("mm", "in"): 0.0393701,
    ("in", "cm"): 2.54,
    ("cm", "in"): 0.393701,

    # Temperature (handled specially)
    # ("F", "C"): special,
    # ("C", "F"): special,

    # Mass
    ("lb", "kg"): 0.453592,
    ("kg", "lb"): 2.20462,
    ("ton", "kg"): 907.185,  # US short ton
    ("kg", "ton"): 0.00110231,
    ("ton", "t"): 0.907185,  # US short ton to metric tonne
    ("t", "ton"): 1.10231,
}


def convert_flow(
    value: Union[float, np.ndarray, pd.Series],
    from_unit: str,
    to_unit: str,
) -> Union[float, np.ndarray, pd.Series]:
    """
    Convert between flow units.

    Supported units: cfs, m3/s, cms, l/s

    Args:
        value: Flow value(s) to convert.
        from_unit: Source unit.
        to_unit: Target unit.

    Returns:
        Converted value(s).
    """
    from_unit = _normalize_unit(from_unit)
    to_unit = _normalize_unit(to_unit)

    if from_unit == to_unit:
        return value

    key = (from_unit, to_unit)
    if key in CONVERSION_FACTORS:
        return value * CONVERSION_FACTORS[key]

    raise ValueError(f"No conversion available from '{from_unit}' to '{to_unit}'")


def convert_length(
    value: Union[float, np.ndarray, pd.Series],
    from_unit: str,
    to_unit: str,
) -> Union[float, np.ndarray, pd.Series]:
    """
    Convert between length units.

    Supported units: ft, m, in, mm, cm

    Args:
        value: Length value(s) to convert.
        from_unit: Source unit.
        to_unit: Target unit.

    Returns:
        Converted value(s).
    """
    from_unit = _normalize_unit(from_unit)
    to_unit = _normalize_unit(to_unit)

    if from_unit == to_unit:
        return value

    key = (from_unit, to_unit)
    if key in CONVERSION_FACTORS:
        return value * CONVERSION_FACTORS[key]

    raise ValueError(f"No conversion available from '{from_unit}' to '{to_unit}'")


def convert_temperature(
    value: Union[float, np.ndarray, pd.Series],
    from_unit: str,
    to_unit: str,
) -> Union[float, np.ndarray, pd.Series]:
    """
    Convert between temperature units.

    Supported units: C, F, K

    Args:
        value: Temperature value(s) to convert.
        from_unit: Source unit.
        to_unit: Target unit.

    Returns:
        Converted value(s).
    """
    from_unit = _normalize_unit(from_unit)
    to_unit = _normalize_unit(to_unit)

    if from_unit == to_unit:
        return value

    # Convert to Celsius first
    if from_unit == "f":
        celsius = (value - 32) * 5.0 / 9.0
    elif from_unit == "k":
        celsius = value - 273.15
    elif from_unit == "c":
        celsius = value
    else:
        raise ValueError(f"Unknown temperature unit: {from_unit}")

    # Convert from Celsius to target
    if to_unit == "c":
        return celsius
    elif to_unit == "f":
        return celsius * 9.0 / 5.0 + 32
    elif to_unit == "k":
        return celsius + 273.15
    else:
        raise ValueError(f"Unknown temperature unit: {to_unit}")


def convert_concentration_to_load(
    concentration: Union[float, np.ndarray, pd.Series],
    flow_m3s: Union[float, np.ndarray, pd.Series],
    conc_unit: str = "mg/L",
    load_unit: str = "kg/day",
) -> Union[float, np.ndarray, pd.Series]:
    """
    Convert concentration to load using flow data.

    Load = Concentration * Flow * conversion_factor

    Args:
        concentration: Concentration values (e.g., mg/L).
        flow_m3s: Flow values in m3/s.
        conc_unit: Concentration unit ("mg/L" or "ug/L").
        load_unit: Target load unit ("kg/day" or "g/day").

    Returns:
        Load values in the target unit.
    """
    # Convert concentration to mg/L
    if conc_unit == "ug/L":
        conc_mg_l = concentration / 1000.0
    elif conc_unit == "mg/L":
        conc_mg_l = concentration
    else:
        raise ValueError(f"Unsupported concentration unit: {conc_unit}")

    # Load (kg/day) = conc (mg/L) * flow (m3/s) * 86400 (s/day) / 1e6 (mg/kg) * 1000 (L/m3)
    # = conc * flow * 86.4
    load_kg_day = conc_mg_l * flow_m3s * 86.4

    if load_unit == "kg/day":
        return load_kg_day
    elif load_unit == "g/day":
        return load_kg_day * 1000.0
    elif load_unit == "t/day":
        return load_kg_day / 1000.0
    else:
        raise ValueError(f"Unsupported load unit: {load_unit}")


def convert_load_to_concentration(
    load: Union[float, np.ndarray, pd.Series],
    flow_m3s: Union[float, np.ndarray, pd.Series],
    load_unit: str = "kg/day",
    conc_unit: str = "mg/L",
) -> Union[float, np.ndarray, pd.Series]:
    """
    Convert load to concentration using flow data.

    Concentration = Load / (Flow * conversion_factor)

    Args:
        load: Load values.
        flow_m3s: Flow values in m3/s.
        load_unit: Load unit ("kg/day", "g/day").
        conc_unit: Target concentration unit ("mg/L").

    Returns:
        Concentration values.
    """
    # Convert load to kg/day
    if load_unit == "g/day":
        load_kg_day = load / 1000.0
    elif load_unit == "kg/day":
        load_kg_day = load
    elif load_unit == "t/day":
        load_kg_day = load * 1000.0
    else:
        raise ValueError(f"Unsupported load unit: {load_unit}")

    # Concentration (mg/L) = load (kg/day) / (flow (m3/s) * 86.4)
    conc_mg_l = load_kg_day / (flow_m3s * 86.4)

    if conc_unit == "mg/L":
        return conc_mg_l
    elif conc_unit == "ug/L":
        return conc_mg_l * 1000.0
    else:
        raise ValueError(f"Unsupported concentration unit: {conc_unit}")


def _normalize_unit(unit: str) -> str:
    """Normalize unit string for comparison."""
    unit = unit.strip().lower()
    # Common aliases
    aliases = {
        "m3/s": "m3/s",
        "m³/s": "m3/s",
        "cms": "m3/s",
        "cumecs": "m3/s",
        "cubic feet per second": "cfs",
        "ft3/s": "cfs",
        "ft³/s": "cfs",
        "celsius": "c",
        "deg c": "c",
        "degc": "c",
        "fahrenheit": "f",
        "deg f": "f",
        "kelvin": "k",
        "meters": "m",
        "feet": "ft",
        "inches": "in",
        "millimeters": "mm",
        "centimeters": "cm",
    }
    return aliases.get(unit, unit)


# Constituent unit definitions for water quality calibration
# Maps constituent names to their observation units, SWAT output units, and load units
CONSTITUENT_UNITS = {
    "TN":      {"obs_unit": "mg/L", "swat_unit": "kg",   "load_unit": "kg/day",   "swat_column": "TOT_Nkg"},
    "TP":      {"obs_unit": "mg/L", "swat_unit": "kg",   "load_unit": "kg/day",   "swat_column": "TOT_Pkg"},
    "TSS":     {"obs_unit": "mg/L", "swat_unit": "tons", "load_unit": "tons/day", "swat_column": "SED_OUTtons"},
    "NO3":     {"obs_unit": "mg/L", "swat_unit": "kg",   "load_unit": "kg/day",   "swat_column": "NO3_OUTkg"},
    "NH4":     {"obs_unit": "mg/L", "swat_unit": "kg",   "load_unit": "kg/day",   "swat_column": "NH4_OUTkg"},
    "NO2":     {"obs_unit": "mg/L", "swat_unit": "kg",   "load_unit": "kg/day",   "swat_column": "NO2_OUTkg"},
    "ORGN":    {"obs_unit": "mg/L", "swat_unit": "kg",   "load_unit": "kg/day",   "swat_column": "ORGN_OUTkg"},
    "ORGP":    {"obs_unit": "mg/L", "swat_unit": "kg",   "load_unit": "kg/day",   "swat_column": "ORGP_OUTkg"},
    "MINP":    {"obs_unit": "mg/L", "swat_unit": "kg",   "load_unit": "kg/day",   "swat_column": "MINP_OUTkg"},
    "SEDCONC": {"obs_unit": "mg/L", "swat_unit": "mg/L", "load_unit": "mg/L",     "swat_column": "SEDCONCmg_L"},
    "NO3CONC": {"obs_unit": "mg/L", "swat_unit": "mg/L", "load_unit": "mg/L",     "swat_column": "NO3ConcMg_l"},
}


def convert_concentration_to_sediment_load(
    concentration: Union[float, np.ndarray, pd.Series],
    flow_m3s: Union[float, np.ndarray, pd.Series],
    conc_unit: str = "mg/L",
    load_unit: str = "tons/day",
) -> Union[float, np.ndarray, pd.Series]:
    """Convert sediment concentration to sediment load using flow data.

    Load (tons/day) = conc (mg/L) * flow (m3/s) * 1000 (L/m3) * 86400 (s/day) / 1e9 (mg/ton)
                    = conc * flow * 0.0864

    This is different from N/P load conversion because SWAT outputs
    sediment in tons, not kg.

    Args:
        concentration: Sediment concentration values (e.g., TSS in mg/L).
        flow_m3s: Flow values in m3/s.
        conc_unit: Concentration unit ("mg/L" or "ug/L").
        load_unit: Target load unit ("tons/day" or "kg/day").

    Returns:
        Sediment load values in the target unit.
    """
    # Convert concentration to mg/L
    if conc_unit == "ug/L":
        conc_mg_l = concentration / 1000.0
    elif conc_unit == "mg/L":
        conc_mg_l = concentration
    else:
        raise ValueError(f"Unsupported concentration unit: {conc_unit}")

    # Load (tons/day) = conc (mg/L) * flow (m3/s) * 1000 (L/m3) * 86400 (s/day) / 1e9 (mg/ton)
    # 1 m3 = 1000 L, 1 metric ton = 1e6 g = 1e9 mg
    # = conc * flow * 86400000 / 1e9 = conc * flow * 0.0864
    load_tons_day = conc_mg_l * flow_m3s * 0.0864

    if load_unit == "tons/day":
        return load_tons_day
    elif load_unit == "kg/day":
        return load_tons_day * 1000.0  # 1 ton = 1000 kg (metric)
    elif load_unit == "t/day":
        return load_tons_day  # tons = t (metric tonnes)
    else:
        raise ValueError(f"Unsupported load unit: {load_unit}")


def convert_obs_to_load(
    constituent: str,
    concentration: Union[float, np.ndarray, pd.Series],
    flow_m3s: Union[float, np.ndarray, pd.Series],
    conc_unit: str = "mg/L",
) -> Union[float, np.ndarray, pd.Series]:
    """Convert observed concentration to load for any constituent.

    Dispatches to the appropriate conversion function based on the
    constituent type. Sediment (TSS) uses tons/day, all others use kg/day.

    Args:
        constituent: Constituent name (e.g., "TN", "TP", "TSS", "NO3").
        concentration: Concentration values in conc_unit.
        flow_m3s: Flow values in m3/s.
        conc_unit: Concentration unit (default "mg/L").

    Returns:
        Load values in SWAT-compatible units (kg/day for N/P, tons/day for sediment).
    """
    constituent = constituent.upper()

    if constituent not in CONSTITUENT_UNITS:
        raise ValueError(
            f"Unknown constituent '{constituent}'. "
            f"Available: {list(CONSTITUENT_UNITS.keys())}"
        )

    load_unit = CONSTITUENT_UNITS[constituent]["load_unit"]

    # Concentration-type constituents (no load conversion needed)
    if load_unit == "mg/L":
        return concentration

    # Sediment: tons/day
    if constituent == "TSS":
        return convert_concentration_to_sediment_load(
            concentration, flow_m3s, conc_unit=conc_unit, load_unit="tons/day"
        )

    # N/P constituents: kg/day
    return convert_concentration_to_load(
        concentration, flow_m3s, conc_unit=conc_unit, load_unit="kg/day"
    )
