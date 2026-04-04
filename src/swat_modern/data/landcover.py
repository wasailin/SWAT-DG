"""
Land cover data retrieval and processing for SWAT models.

This module provides tools for:
- Downloading land cover data from USGS NLCD (National Land Cover Database)
- Mapping NLCD classes to SWAT land use codes
- Generating SWAT land use input files

NLCD is the primary land cover dataset for the conterminous US and contains
16 land cover classes that can be mapped to SWAT land use types.

Example:
    >>> from swat_modern.data.landcover import LandCoverFetcher, NLCDClass
    >>>
    >>> # Map NLCD to SWAT codes
    >>> swat_code = NLCDClass.to_swat_code(41)  # Deciduous Forest
    >>> print(swat_code)  # "FRSD"
    >>>
    >>> # Create land cover dataset from raster
    >>> fetcher = LandCoverFetcher()
    >>> landcover = fetcher.from_raster("nlcd_2019.tif")
    >>> landcover.to_swat_file("landuse.csv")

References:
    - USGS NLCD: https://www.mrlc.gov/
    - SWAT Land Use: Chapter 13 of SWAT IO Documentation
"""

from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Union
from enum import IntEnum
import numpy as np
import pandas as pd
import warnings


# NLCD Class Definitions (2019 version)
class NLCDClass(IntEnum):
    """NLCD Land Cover Classification codes."""

    # Water
    OPEN_WATER = 11
    PERENNIAL_ICE_SNOW = 12

    # Developed
    DEVELOPED_OPEN = 21
    DEVELOPED_LOW = 22
    DEVELOPED_MEDIUM = 23
    DEVELOPED_HIGH = 24

    # Barren
    BARREN_LAND = 31

    # Forest
    DECIDUOUS_FOREST = 41
    EVERGREEN_FOREST = 42
    MIXED_FOREST = 43

    # Shrubland
    DWARF_SCRUB = 51  # Alaska only
    SHRUB_SCRUB = 52

    # Herbaceous
    GRASSLAND = 71
    SEDGE_HERBACEOUS = 72  # Alaska only
    LICHENS = 73  # Alaska only
    MOSS = 74  # Alaska only

    # Planted/Cultivated
    PASTURE_HAY = 81
    CULTIVATED_CROPS = 82

    # Wetlands
    WOODY_WETLANDS = 90
    EMERGENT_WETLANDS = 95


# NLCD to SWAT land use mapping
# SWAT land use codes from SWAT documentation
NLCD_TO_SWAT = {
    # Water
    11: {"code": "WATR", "name": "Water", "cn_a": 100, "cn_b": 100, "cn_c": 100, "cn_d": 100},
    12: {"code": "WATR", "name": "Perennial Ice/Snow", "cn_a": 100, "cn_b": 100, "cn_c": 100, "cn_d": 100},

    # Developed
    21: {"code": "URLD", "name": "Residential-Low Density", "cn_a": 54, "cn_b": 70, "cn_c": 80, "cn_d": 85},
    22: {"code": "URML", "name": "Residential-Med/Low Density", "cn_a": 61, "cn_b": 75, "cn_c": 83, "cn_d": 87},
    23: {"code": "URMD", "name": "Residential-Medium Density", "cn_a": 77, "cn_b": 85, "cn_c": 90, "cn_d": 92},
    24: {"code": "URHD", "name": "Residential-High Density", "cn_a": 89, "cn_b": 92, "cn_c": 94, "cn_d": 95},

    # Barren
    31: {"code": "BARR", "name": "Barren", "cn_a": 77, "cn_b": 86, "cn_c": 91, "cn_d": 94},

    # Forest
    41: {"code": "FRSD", "name": "Forest-Deciduous", "cn_a": 36, "cn_b": 60, "cn_c": 73, "cn_d": 79},
    42: {"code": "FRSE", "name": "Forest-Evergreen", "cn_a": 36, "cn_b": 60, "cn_c": 73, "cn_d": 79},
    43: {"code": "FRST", "name": "Forest-Mixed", "cn_a": 36, "cn_b": 60, "cn_c": 73, "cn_d": 79},

    # Shrubland
    51: {"code": "RNGB", "name": "Range-Brush", "cn_a": 35, "cn_b": 56, "cn_c": 70, "cn_d": 77},
    52: {"code": "RNGB", "name": "Range-Brush", "cn_a": 35, "cn_b": 56, "cn_c": 70, "cn_d": 77},

    # Herbaceous/Grassland
    71: {"code": "RNGE", "name": "Range-Grasses", "cn_a": 49, "cn_b": 69, "cn_c": 79, "cn_d": 84},
    72: {"code": "RNGE", "name": "Range-Grasses", "cn_a": 49, "cn_b": 69, "cn_c": 79, "cn_d": 84},
    73: {"code": "RNGE", "name": "Range-Grasses", "cn_a": 49, "cn_b": 69, "cn_c": 79, "cn_d": 84},
    74: {"code": "RNGE", "name": "Range-Grasses", "cn_a": 49, "cn_b": 69, "cn_c": 79, "cn_d": 84},

    # Agriculture
    81: {"code": "HAY", "name": "Hay", "cn_a": 49, "cn_b": 69, "cn_c": 79, "cn_d": 84},
    82: {"code": "AGRR", "name": "Agricultural Land-Row Crops", "cn_a": 67, "cn_b": 78, "cn_c": 85, "cn_d": 89},

    # Wetlands
    90: {"code": "WETF", "name": "Wetlands-Forested", "cn_a": 72, "cn_b": 80, "cn_c": 86, "cn_d": 90},
    95: {"code": "WETN", "name": "Wetlands-Non-Forested", "cn_a": 78, "cn_b": 83, "cn_c": 88, "cn_d": 91},
}


# SWAT land use descriptions
SWAT_LANDUSE = {
    "WATR": {"description": "Water", "cover_type": "water"},
    "URLD": {"description": "Residential-Low Density", "cover_type": "urban"},
    "URML": {"description": "Residential-Med/Low Density", "cover_type": "urban"},
    "URMD": {"description": "Residential-Medium Density", "cover_type": "urban"},
    "URHD": {"description": "Residential-High Density", "cover_type": "urban"},
    "UCOM": {"description": "Commercial", "cover_type": "urban"},
    "UIDU": {"description": "Industrial", "cover_type": "urban"},
    "UTRN": {"description": "Transportation", "cover_type": "urban"},
    "BARR": {"description": "Barren", "cover_type": "barren"},
    "FRSD": {"description": "Forest-Deciduous", "cover_type": "forest"},
    "FRSE": {"description": "Forest-Evergreen", "cover_type": "forest"},
    "FRST": {"description": "Forest-Mixed", "cover_type": "forest"},
    "RNGB": {"description": "Range-Brush", "cover_type": "shrub"},
    "RNGE": {"description": "Range-Grasses", "cover_type": "grass"},
    "HAY": {"description": "Hay", "cover_type": "agriculture"},
    "AGRR": {"description": "Agricultural Land-Row Crops", "cover_type": "agriculture"},
    "AGRL": {"description": "Agricultural Land-Generic", "cover_type": "agriculture"},
    "AGRC": {"description": "Agricultural Land-Close-grown", "cover_type": "agriculture"},
    "WETF": {"description": "Wetlands-Forested", "cover_type": "wetland"},
    "WETN": {"description": "Wetlands-Non-Forested", "cover_type": "wetland"},
    "PAST": {"description": "Pasture", "cover_type": "grass"},
    "ORCD": {"description": "Orchard", "cover_type": "agriculture"},
}


def nlcd_to_swat_code(nlcd_class: int) -> str:
    """
    Convert NLCD class to SWAT land use code.

    Args:
        nlcd_class: NLCD classification code (11-95)

    Returns:
        SWAT 4-character land use code
    """
    if nlcd_class in NLCD_TO_SWAT:
        return NLCD_TO_SWAT[nlcd_class]["code"]
    return "AGRL"  # Default to generic agriculture


def get_curve_number(nlcd_class: int, hydgrp: str) -> int:
    """
    Get curve number for NLCD class and hydrologic soil group.

    Args:
        nlcd_class: NLCD classification code
        hydgrp: Hydrologic soil group (A, B, C, D)

    Returns:
        Curve number (0-100)
    """
    if nlcd_class not in NLCD_TO_SWAT:
        return 75  # Default

    hydgrp = hydgrp.upper()
    if '/' in hydgrp:
        hydgrp = hydgrp.split('/')[1]  # Use worst case for dual class

    cn_key = f"cn_{hydgrp.lower()}"
    return NLCD_TO_SWAT[nlcd_class].get(cn_key, 75)


@dataclass
class LandCoverClass:
    """
    Land cover class information.

    Attributes:
        code: NLCD or SWAT code
        name: Class name
        swat_code: SWAT land use code
        area_km2: Area in square kilometers
        area_pct: Percentage of total area
        pixel_count: Number of pixels
    """
    code: int
    name: str
    swat_code: str = ""
    area_km2: float = 0.0
    area_pct: float = 0.0
    pixel_count: int = 0

    def __post_init__(self):
        """Set SWAT code if not provided."""
        if not self.swat_code:
            self.swat_code = nlcd_to_swat_code(self.code)


@dataclass
class LandCoverDataset:
    """
    Land cover dataset with statistics.

    Attributes:
        classes: Dictionary of {code: LandCoverClass}
        total_area_km2: Total area in km²
        resolution: Pixel resolution in meters
        crs: Coordinate reference system
        bounds: Bounding box (west, south, east, north)
    """
    classes: Dict[int, LandCoverClass] = field(default_factory=dict)
    total_area_km2: float = 0.0
    resolution: float = 30.0  # NLCD default
    crs: str = ""
    bounds: Tuple[float, float, float, float] = None

    def __len__(self) -> int:
        return len(self.classes)

    def __getitem__(self, code: int) -> LandCoverClass:
        return self.classes[code]

    def __iter__(self):
        return iter(self.classes.values())

    def add_class(self, lc_class: LandCoverClass) -> None:
        """Add a land cover class."""
        self.classes[lc_class.code] = lc_class

    def get_swat_distribution(self) -> Dict[str, float]:
        """
        Get distribution by SWAT land use codes.

        Returns:
            Dictionary of {swat_code: percentage}
        """
        swat_dist = {}
        for lc in self.classes.values():
            code = lc.swat_code
            if code in swat_dist:
                swat_dist[code] += lc.area_pct
            else:
                swat_dist[code] = lc.area_pct
        return swat_dist

    def get_dominant_class(self) -> LandCoverClass:
        """Get the dominant land cover class by area."""
        return max(self.classes.values(), key=lambda x: x.area_pct)

    def to_dataframe(self) -> pd.DataFrame:
        """Convert to DataFrame."""
        records = []
        for code, lc in self.classes.items():
            records.append({
                "NLCD_Code": code,
                "Name": lc.name,
                "SWAT_Code": lc.swat_code,
                "Area_km2": lc.area_km2,
                "Area_pct": lc.area_pct,
                "Pixel_Count": lc.pixel_count,
            })
        return pd.DataFrame(records).sort_values("Area_pct", ascending=False)

    def to_swat_file(
        self,
        filepath: Union[str, Path],
        include_cn: bool = True,
    ) -> None:
        """
        Write SWAT land use lookup table.

        Args:
            filepath: Output file path
            include_cn: Include curve numbers for soil groups
        """
        filepath = Path(filepath)

        with open(filepath, 'w') as f:
            f.write("SWAT Land Use Distribution\n")
            f.write(f"Total Area: {self.total_area_km2:.2f} km2\n")
            f.write("\n")

            # Header
            if include_cn:
                f.write(f"{'SWAT_Code':<8} {'NLCD':<6} {'Name':<30} {'Area_pct':>10} "
                       f"{'CN_A':>6} {'CN_B':>6} {'CN_C':>6} {'CN_D':>6}\n")
                f.write("-" * 90 + "\n")
            else:
                f.write(f"{'SWAT_Code':<8} {'NLCD':<6} {'Name':<30} {'Area_pct':>10}\n")
                f.write("-" * 60 + "\n")

            # Data rows
            for code, lc in sorted(self.classes.items(), key=lambda x: -x[1].area_pct):
                if include_cn and code in NLCD_TO_SWAT:
                    cn = NLCD_TO_SWAT[code]
                    f.write(f"{lc.swat_code:<8} {code:<6} {lc.name:<30} {lc.area_pct:>10.2f} "
                           f"{cn['cn_a']:>6} {cn['cn_b']:>6} {cn['cn_c']:>6} {cn['cn_d']:>6}\n")
                else:
                    f.write(f"{lc.swat_code:<8} {code:<6} {lc.name:<30} {lc.area_pct:>10.2f}\n")

        print(f"Wrote land use table to {filepath}")

    def summary(self) -> str:
        """Generate summary string."""
        lines = [
            "Land Cover Dataset Summary",
            "=" * 50,
            f"Total Area: {self.total_area_km2:.2f} km²",
            f"Resolution: {self.resolution} m",
            f"Number of classes: {len(self)}",
            "",
            "Land Cover Distribution:",
        ]

        for lc in sorted(self.classes.values(), key=lambda x: -x.area_pct):
            lines.append(f"  {lc.swat_code} ({lc.code}): {lc.area_pct:.1f}% - {lc.name}")

        # SWAT distribution
        lines.append("")
        lines.append("SWAT Land Use Distribution:")
        for code, pct in sorted(self.get_swat_distribution().items(), key=lambda x: -x[1]):
            desc = SWAT_LANDUSE.get(code, {}).get("description", code)
            lines.append(f"  {code}: {pct:.1f}% - {desc}")

        return "\n".join(lines)


class LandCoverFetcher:
    """
    Fetch and process land cover data.

    Supports:
    - Loading from GeoTIFF rasters
    - Computing statistics
    - NLCD to SWAT conversion

    Example:
        >>> fetcher = LandCoverFetcher()
        >>> lc = fetcher.from_raster("nlcd_2019.tif")
        >>> print(lc.summary())
    """

    def __init__(self):
        """Initialize land cover fetcher."""
        pass

    def from_raster(
        self,
        filepath: Union[str, Path],
        mask: np.ndarray = None,
    ) -> LandCoverDataset:
        """
        Load land cover from GeoTIFF raster.

        Args:
            filepath: Path to NLCD GeoTIFF
            mask: Optional mask array (True = include)

        Returns:
            LandCoverDataset with statistics
        """
        filepath = Path(filepath)

        try:
            import rasterio
        except ImportError:
            raise ImportError(
                "rasterio is required for raster processing. "
                "Install with: pip install rasterio"
            )

        with rasterio.open(filepath) as src:
            data = src.read(1)
            transform = src.transform
            crs = str(src.crs)
            bounds = src.bounds

            # Get resolution
            res = abs(transform.a)  # Pixel size in CRS units

        # Apply mask if provided
        if mask is not None:
            data = np.where(mask, data, 0)

        # Compute statistics
        dataset = self._compute_statistics(data, res, crs, bounds)

        return dataset

    def from_array(
        self,
        data: np.ndarray,
        resolution: float = 30.0,
        crs: str = "EPSG:5070",
    ) -> LandCoverDataset:
        """
        Create land cover dataset from numpy array.

        Args:
            data: 2D numpy array with NLCD class values
            resolution: Pixel resolution in meters
            crs: Coordinate reference system

        Returns:
            LandCoverDataset with statistics
        """
        return self._compute_statistics(data, resolution, crs, None)

    def _compute_statistics(
        self,
        data: np.ndarray,
        resolution: float,
        crs: str,
        bounds: tuple,
    ) -> LandCoverDataset:
        """Compute land cover statistics from array."""
        # Get unique classes and counts
        unique, counts = np.unique(data, return_counts=True)

        # Remove nodata (0)
        mask = unique != 0
        unique = unique[mask]
        counts = counts[mask]

        # Calculate areas
        pixel_area_km2 = (resolution ** 2) / 1e6  # m² to km²
        total_pixels = counts.sum()
        total_area = total_pixels * pixel_area_km2

        # Create dataset
        dataset = LandCoverDataset(
            total_area_km2=total_area,
            resolution=resolution,
            crs=crs,
            bounds=bounds,
        )

        # Add classes
        for code, count in zip(unique, counts):
            code = int(code)
            area_km2 = count * pixel_area_km2
            area_pct = (count / total_pixels) * 100 if total_pixels > 0 else 0

            # Get name from NLCD mapping
            name = NLCD_TO_SWAT.get(code, {}).get("name", f"Class_{code}")
            swat_code = nlcd_to_swat_code(code)

            lc_class = LandCoverClass(
                code=code,
                name=name,
                swat_code=swat_code,
                area_km2=area_km2,
                area_pct=area_pct,
                pixel_count=int(count),
            )
            dataset.add_class(lc_class)

        return dataset

    @staticmethod
    def create_sample_dataset() -> LandCoverDataset:
        """
        Create a sample land cover dataset for testing.

        Returns:
            LandCoverDataset with typical land use distribution
        """
        # Typical distribution for a mixed-use watershed
        sample_data = [
            (41, "Deciduous Forest", 25.0),
            (42, "Evergreen Forest", 15.0),
            (82, "Cultivated Crops", 20.0),
            (81, "Pasture/Hay", 15.0),
            (71, "Grassland/Herbaceous", 10.0),
            (21, "Developed, Open Space", 5.0),
            (22, "Developed, Low Intensity", 3.0),
            (11, "Open Water", 2.0),
            (90, "Woody Wetlands", 3.0),
            (52, "Shrub/Scrub", 2.0),
        ]

        dataset = LandCoverDataset(
            total_area_km2=500.0,
            resolution=30.0,
            crs="EPSG:5070",
        )

        for code, name, pct in sample_data:
            area_km2 = 500.0 * pct / 100
            pixel_count = int(area_km2 * 1e6 / (30 ** 2))

            lc_class = LandCoverClass(
                code=code,
                name=name,
                area_km2=area_km2,
                area_pct=pct,
                pixel_count=pixel_count,
            )
            dataset.add_class(lc_class)

        return dataset

    @staticmethod
    def reclassify_to_swat(
        data: np.ndarray,
    ) -> Tuple[np.ndarray, Dict[int, str]]:
        """
        Reclassify NLCD array to SWAT land use codes.

        Args:
            data: 2D array with NLCD values

        Returns:
            Tuple of (reclassified array, code mapping)
        """
        # Create mapping from NLCD to integer codes for SWAT
        swat_codes = list(set(v["code"] for v in NLCD_TO_SWAT.values()))
        swat_to_int = {code: i + 1 for i, code in enumerate(sorted(swat_codes))}

        # Reclassify
        result = np.zeros_like(data)
        for nlcd_code, info in NLCD_TO_SWAT.items():
            swat_code = info["code"]
            result[data == nlcd_code] = swat_to_int[swat_code]

        # Create reverse mapping
        int_to_swat = {v: k for k, v in swat_to_int.items()}

        return result, int_to_swat


def get_nlcd_class_name(code: int) -> str:
    """Get NLCD class name from code."""
    return NLCD_TO_SWAT.get(code, {}).get("name", f"Unknown ({code})")


def get_swat_land_use_info(swat_code: str) -> dict:
    """Get SWAT land use information."""
    return SWAT_LANDUSE.get(swat_code, {"description": swat_code, "cover_type": "unknown"})
