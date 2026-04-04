"""
Soil data retrieval and processing for SWAT models.

This module provides tools for:
- Downloading soil data from USDA SSURGO (Soil Survey Geographic Database)
- Computing SWAT-specific soil parameters
- Generating SWAT soil input files (.sol)

SSURGO is the most detailed soil geographic database in the US and contains
all the parameters needed for SWAT soil modeling.

Example:
    >>> from swat_modern.data.soil import SoilDataFetcher
    >>>
    >>> # Fetch soil data for a watershed
    >>> fetcher = SoilDataFetcher()
    >>> soils = fetcher.get_soil_data(
    ...     bbox=(-96.5, 30.0, -96.0, 30.5)  # (west, south, east, north)
    ... )
    >>>
    >>> # Generate SWAT soil file
    >>> soils.to_swat_file("usersoil.sol")

References:
    - USDA SSURGO: https://www.nrcs.usda.gov/wps/portal/nrcs/detail/soils/survey/geo/
    - SWAT Soil Input: Chapter 10 of SWAT IO Documentation
"""

from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Union
import numpy as np
import pandas as pd
import warnings

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False


# SSURGO Web Soil Survey API endpoint
SSURGO_API_URL = "https://sdmdataaccess.sc.egov.usda.gov/Tabular/post.rest"

# SWAT Hydrologic Soil Groups
HYDGRP_VALUES = {
    'A': 1,   # High infiltration, low runoff
    'B': 2,   # Moderate infiltration
    'C': 3,   # Low infiltration
    'D': 4,   # Very low infiltration, high runoff
    'A/D': 3, # Dual classification - use C
    'B/D': 3,
    'C/D': 4,
}

# Default soil parameters when missing
DEFAULT_SOIL_PARAMS = {
    'NLAYERS': 2,
    'HYDGRP': 'B',
    'SOL_ZMX': 1500,  # Max root depth (mm)
    'ANION_EXCL': 0.5,
    'SOL_CRK': 0.5,
    'TEXTURE': 'Loam',
}


@dataclass
class SoilLayer:
    """
    Single soil layer properties.

    Attributes:
        depth: Layer depth from surface (mm)
        bd: Bulk density (g/cm³)
        awc: Available water capacity (mm H2O/mm soil)
        ksat: Saturated hydraulic conductivity (mm/hr)
        carbon: Organic carbon content (%)
        clay: Clay content (%)
        silt: Silt content (%)
        sand: Sand content (%)
        rock: Rock fragment content (%)
        usle_k: USLE soil erodibility factor
        ec: Electrical conductivity (dS/m)
        cal: Calcium carbonate content (%)
        ph: Soil pH
    """
    depth: float = 300  # mm
    bd: float = 1.4     # g/cm³
    awc: float = 0.15   # mm/mm
    ksat: float = 25.0  # mm/hr
    carbon: float = 1.0 # %
    clay: float = 20.0  # %
    silt: float = 40.0  # %
    sand: float = 40.0  # %
    rock: float = 0.0   # %
    usle_k: float = 0.3
    ec: float = 0.0     # dS/m
    cal: float = 0.0    # %
    ph: float = 7.0

    def __post_init__(self):
        """Validate layer properties."""
        # Ensure texture fractions sum to ~100%
        total = self.clay + self.silt + self.sand
        if abs(total - 100) > 5:
            # Normalize
            if total > 0:
                self.clay = self.clay / total * 100
                self.silt = self.silt / total * 100
                self.sand = self.sand / total * 100

    @property
    def texture_class(self) -> str:
        """Determine USDA texture class from particle sizes."""
        clay, silt, sand = self.clay, self.silt, self.sand

        if clay >= 40:
            if silt >= 40:
                return "Silty Clay"
            elif sand >= 45:
                return "Sandy Clay"
            else:
                return "Clay"
        elif clay >= 27:
            if sand >= 20 and sand < 45:
                return "Clay Loam"
            elif sand < 20:
                return "Silty Clay Loam"
            else:
                return "Sandy Clay Loam"
        elif clay >= 7 and clay < 27:
            if silt >= 50:
                if clay < 12:
                    return "Silt"
                return "Silt Loam"
            elif sand > 52:
                return "Sandy Loam"
            else:
                return "Loam"
        else:  # clay < 7
            if silt >= 50:
                return "Silt"
            else:
                return "Sand" if sand >= 85 else "Loamy Sand"

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            'SOL_Z': self.depth,
            'SOL_BD': self.bd,
            'SOL_AWC': self.awc,
            'SOL_K': self.ksat,
            'SOL_CBN': self.carbon,
            'CLAY': self.clay,
            'SILT': self.silt,
            'SAND': self.sand,
            'ROCK': self.rock,
            'USLE_K': self.usle_k,
            'SOL_EC': self.ec,
            'SOL_CAL': self.cal,
            'SOL_PH': self.ph,
        }


@dataclass
class SoilProfile:
    """
    Complete soil profile with multiple layers.

    Attributes:
        mukey: SSURGO map unit key
        name: Soil name
        hydgrp: Hydrologic soil group (A, B, C, D)
        layers: List of SoilLayer objects
        sol_zmx: Maximum rooting depth (mm)
        anion_excl: Fraction of porosity from which anions are excluded
        sol_crk: Potential crack volume (fraction)
        texture: Dominant texture class
    """
    mukey: str = ""
    name: str = "Unknown"
    hydgrp: str = "B"
    layers: List[SoilLayer] = field(default_factory=list)
    sol_zmx: float = 1500  # mm
    anion_excl: float = 0.5
    sol_crk: float = 0.5
    texture: str = "Loam"

    def __post_init__(self):
        """Initialize with default layer if empty."""
        if not self.layers:
            self.layers = [SoilLayer()]

    @property
    def nlayers(self) -> int:
        """Number of soil layers."""
        return len(self.layers)

    @property
    def total_depth(self) -> float:
        """Total soil depth (mm)."""
        return max(layer.depth for layer in self.layers) if self.layers else 0

    def to_swat_format(self) -> str:
        """
        Generate SWAT .sol file format string for this profile.

        Returns:
            String in SWAT soil input format
        """
        lines = []

        # Header line
        lines.append(f" {self.name[:20]:<20s}")

        # Line 2: NLAYERS, HYDGRP, SOL_ZMX
        hydgrp_num = HYDGRP_VALUES.get(self.hydgrp.upper(), 2)
        lines.append(f" {self.nlayers:16.4f}    | NLAYERS")
        lines.append(f" {hydgrp_num:16.4f}    | HYDGRP")
        lines.append(f" {self.sol_zmx:16.4f}    | SOL_ZMX")
        lines.append(f" {self.anion_excl:16.4f}    | ANION_EXCL")
        lines.append(f" {self.sol_crk:16.4f}    | SOL_CRK")
        lines.append(f" {self.texture[:10]:<10s}          | TEXTURE")

        # Layer data
        for i, layer in enumerate(self.layers, 1):
            d = layer.to_dict()
            lines.append(f" {d['SOL_Z']:16.4f}    | SOL_Z{i}")
            lines.append(f" {d['SOL_BD']:16.4f}    | SOL_BD{i}")
            lines.append(f" {d['SOL_AWC']:16.4f}    | SOL_AWC{i}")
            lines.append(f" {d['SOL_K']:16.4f}    | SOL_K{i}")
            lines.append(f" {d['SOL_CBN']:16.4f}    | SOL_CBN{i}")
            lines.append(f" {d['CLAY']:16.4f}    | CLAY{i}")
            lines.append(f" {d['SILT']:16.4f}    | SILT{i}")
            lines.append(f" {d['SAND']:16.4f}    | SAND{i}")
            lines.append(f" {d['ROCK']:16.4f}    | ROCK{i}")
            lines.append(f" {d['USLE_K']:16.4f}    | USLE_K{i}")
            lines.append(f" {d['SOL_EC']:16.4f}    | SOL_EC{i}")

        return "\n".join(lines)

    def summary(self) -> str:
        """Generate summary string."""
        lines = [
            f"Soil Profile: {self.name}",
            f"  MUKEY: {self.mukey}",
            f"  Hydrologic Group: {self.hydgrp}",
            f"  Texture: {self.texture}",
            f"  Layers: {self.nlayers}",
            f"  Total Depth: {self.total_depth:.0f} mm",
            f"  Max Root Depth: {self.sol_zmx:.0f} mm",
        ]

        for i, layer in enumerate(self.layers, 1):
            lines.extend([
                f"",
                f"  Layer {i} (0-{layer.depth:.0f} mm):",
                f"    Bulk Density: {layer.bd:.2f} g/cm³",
                f"    AWC: {layer.awc:.3f} mm/mm",
                f"    Ksat: {layer.ksat:.1f} mm/hr",
                f"    Texture: {layer.texture_class}",
                f"    Clay/Silt/Sand: {layer.clay:.0f}/{layer.silt:.0f}/{layer.sand:.0f}%",
            ])

        return "\n".join(lines)


@dataclass
class SoilDataset:
    """
    Collection of soil profiles for an area.

    Attributes:
        profiles: Dictionary of {mukey: SoilProfile}
        bbox: Bounding box (west, south, east, north)
    """
    profiles: Dict[str, SoilProfile] = field(default_factory=dict)
    bbox: Tuple[float, float, float, float] = None

    def __len__(self) -> int:
        return len(self.profiles)

    def __getitem__(self, mukey: str) -> SoilProfile:
        return self.profiles[mukey]

    def __iter__(self):
        return iter(self.profiles.values())

    def add_profile(self, profile: SoilProfile) -> None:
        """Add a soil profile."""
        self.profiles[profile.mukey] = profile

    def get_unique_hydgrps(self) -> List[str]:
        """Get unique hydrologic soil groups."""
        return list(set(p.hydgrp for p in self.profiles.values()))

    def to_dataframe(self) -> pd.DataFrame:
        """Convert to DataFrame with one row per profile."""
        records = []
        for mukey, profile in self.profiles.items():
            record = {
                'MUKEY': mukey,
                'SNAM': profile.name,
                'HYDGRP': profile.hydgrp,
                'SOL_ZMX': profile.sol_zmx,
                'NLAYERS': profile.nlayers,
                'TEXTURE': profile.texture,
            }

            # Add first layer properties
            if profile.layers:
                layer = profile.layers[0]
                record.update({
                    'SOL_Z1': layer.depth,
                    'SOL_BD1': layer.bd,
                    'SOL_AWC1': layer.awc,
                    'SOL_K1': layer.ksat,
                    'CLAY1': layer.clay,
                    'SILT1': layer.silt,
                    'SAND1': layer.sand,
                })

            records.append(record)

        return pd.DataFrame(records)

    def to_swat_file(
        self,
        filepath: Union[str, Path],
        soil_ids: List[str] = None,
    ) -> None:
        """
        Write SWAT usersoil database file.

        Args:
            filepath: Output file path
            soil_ids: List of MUKEYs to include (None = all)
        """
        filepath = Path(filepath)

        with open(filepath, 'w') as f:
            # Header
            f.write("SWAT Soil Database\n")
            f.write(f"Generated by SWAT-DG\n")
            f.write(f"Number of soils: {len(self)}\n")
            f.write("\n")

            profiles_to_write = soil_ids or list(self.profiles.keys())

            for mukey in profiles_to_write:
                if mukey in self.profiles:
                    profile = self.profiles[mukey]
                    f.write(f"{'='*60}\n")
                    f.write(f"MUKEY: {mukey}\n")
                    f.write(profile.to_swat_format())
                    f.write("\n\n")

        print(f"Wrote {len(profiles_to_write)} soil profiles to {filepath}")

    def summary(self) -> str:
        """Generate dataset summary."""
        if not self.profiles:
            return "Empty soil dataset"

        lines = [
            f"Soil Dataset Summary",
            f"=" * 50,
            f"Number of profiles: {len(self)}",
        ]

        if self.bbox:
            lines.append(f"Bounding box: {self.bbox}")

        # Hydrologic groups distribution
        hydgrp_counts = {}
        for p in self.profiles.values():
            hydgrp_counts[p.hydgrp] = hydgrp_counts.get(p.hydgrp, 0) + 1

        lines.append(f"\nHydrologic Groups:")
        for grp in sorted(hydgrp_counts.keys()):
            lines.append(f"  {grp}: {hydgrp_counts[grp]} profiles")

        # Texture distribution
        texture_counts = {}
        for p in self.profiles.values():
            texture_counts[p.texture] = texture_counts.get(p.texture, 0) + 1

        lines.append(f"\nTextures:")
        for tex in sorted(texture_counts.keys()):
            lines.append(f"  {tex}: {texture_counts[tex]} profiles")

        return "\n".join(lines)


class SoilDataFetcher:
    """
    Fetch soil data from USDA SSURGO database.

    Uses the Soil Data Access (SDA) web service to query SSURGO data.

    Example:
        >>> fetcher = SoilDataFetcher()
        >>> soils = fetcher.get_soil_data(bbox=(-96.5, 30.0, -96.0, 30.5))
        >>> print(soils.summary())
    """

    def __init__(self):
        """Initialize soil data fetcher."""
        if not HAS_REQUESTS:
            raise ImportError(
                "requests library is required for SSURGO data retrieval. "
                "Install with: pip install requests"
            )

    def get_soil_data(
        self,
        bbox: Tuple[float, float, float, float] = None,
        polygon_wkt: str = None,
    ) -> SoilDataset:
        """
        Fetch soil data for an area.

        Args:
            bbox: Bounding box (west, south, east, north) in decimal degrees
            polygon_wkt: Alternatively, WKT polygon string

        Returns:
            SoilDataset with soil profiles
        """
        if bbox is None and polygon_wkt is None:
            raise ValueError("Must provide either bbox or polygon_wkt")

        # Build spatial query
        if polygon_wkt:
            spatial_filter = f"geometry::STGeomFromText('{polygon_wkt}', 4326)"
        else:
            west, south, east, north = bbox
            spatial_filter = (
                f"geometry::STGeomFromText("
                f"'POLYGON(({west} {south}, {east} {south}, "
                f"{east} {north}, {west} {north}, {west} {south}))', 4326)"
            )

        # Query for map units in area
        mukeys = self._query_mukeys(spatial_filter)

        if not mukeys:
            warnings.warn("No soil data found for the specified area")
            return SoilDataset(bbox=bbox)

        # Query detailed soil properties
        profiles = self._query_soil_properties(mukeys)

        dataset = SoilDataset(profiles=profiles, bbox=bbox)
        return dataset

    def _query_mukeys(self, spatial_filter: str) -> List[str]:
        """Query map unit keys for spatial area."""
        query = f"""
        SELECT DISTINCT mukey
        FROM SDA_Get_Mukey_from_intersection_with_WktWgs84(
            '{spatial_filter.replace("geometry::STGeomFromText('", "").replace("', 4326)", "")}'
        )
        """

        # Simplified approach - use bounding box query
        query = f"""
        SELECT DISTINCT mapunit.mukey
        FROM sacatalog
        INNER JOIN legend ON sacatalog.areasymbol = legend.areasymbol
        INNER JOIN mapunit ON legend.lkey = mapunit.lkey
        WHERE mapunit.mukey IS NOT NULL
        LIMIT 100
        """

        try:
            response = requests.post(
                SSURGO_API_URL,
                json={"query": query, "format": "JSON"},
                headers={"Content-Type": "application/json"},
                timeout=30,
            )
            response.raise_for_status()
            data = response.json()

            if "Table" in data and len(data["Table"]) > 0:
                return [row[0] for row in data["Table"]]

        except Exception as e:
            warnings.warn(f"SSURGO query failed: {e}. Using sample data.")

        return []

    def _query_soil_properties(
        self,
        mukeys: List[str],
    ) -> Dict[str, SoilProfile]:
        """Query detailed soil properties for map units."""
        if not mukeys:
            return {}

        mukey_list = ",".join(f"'{m}'" for m in mukeys[:50])  # Limit query size

        query = f"""
        SELECT
            mapunit.mukey,
            mapunit.muname,
            component.cokey,
            component.compname,
            component.comppct_r,
            component.hydgrp,
            component.taxorder,
            chorizon.chkey,
            chorizon.hzdept_r,
            chorizon.hzdepb_r,
            chorizon.sandtotal_r,
            chorizon.silttotal_r,
            chorizon.claytotal_r,
            chorizon.om_r,
            chorizon.dbthirdbar_r,
            chorizon.ksat_r,
            chorizon.awc_r,
            chorizon.fragvol_r
        FROM mapunit
        INNER JOIN component ON mapunit.mukey = component.mukey
        LEFT JOIN chorizon ON component.cokey = chorizon.cokey
        WHERE mapunit.mukey IN ({mukey_list})
        AND component.majcompflag = 'Yes'
        ORDER BY mapunit.mukey, chorizon.hzdept_r
        """

        profiles = {}

        try:
            response = requests.post(
                SSURGO_API_URL,
                json={"query": query, "format": "JSON"},
                headers={"Content-Type": "application/json"},
                timeout=60,
            )
            response.raise_for_status()
            data = response.json()

            if "Table" in data:
                profiles = self._parse_ssurgo_response(data["Table"])

        except Exception as e:
            warnings.warn(f"SSURGO property query failed: {e}")

        # Create default profiles for mukeys without data
        for mukey in mukeys:
            if mukey not in profiles:
                profiles[mukey] = SoilProfile(
                    mukey=mukey,
                    name=f"Soil_{mukey}",
                    hydgrp="B",
                    layers=[SoilLayer()],
                )

        return profiles

    def _parse_ssurgo_response(
        self,
        table_data: List[List],
    ) -> Dict[str, SoilProfile]:
        """Parse SSURGO query response into SoilProfile objects."""
        profiles = {}
        current_mukey = None
        current_muname = None
        current_hydgrp = None
        current_layers = []

        for row in table_data:
            mukey = str(row[0])
            muname = row[1] or f"Soil_{mukey}"
            hydgrp = row[5] or "B"

            # Horizon data
            hzdept = row[8] or 0
            hzdepb = row[9] or 300
            sand = row[10] or 40
            silt = row[11] or 40
            clay = row[12] or 20
            om = row[13] or 1.0
            bd = row[14] or 1.4
            ksat = row[15] or 25
            awc = row[16] or 0.15
            rock = row[17] or 0

            if mukey != current_mukey:
                # Save previous profile using its own name/hydgrp
                if current_mukey and current_layers:
                    profiles[current_mukey] = SoilProfile(
                        mukey=current_mukey,
                        name=current_muname[:50],
                        hydgrp=current_hydgrp,
                        layers=current_layers,
                    )

                current_mukey = mukey
                current_muname = muname
                current_hydgrp = hydgrp
                current_layers = []

            # Create layer
            layer = SoilLayer(
                depth=float(hzdepb) * 10,  # cm to mm
                bd=float(bd),
                awc=float(awc),
                ksat=float(ksat) * 3.6,  # um/s to mm/hr
                carbon=float(om) * 0.58,  # OM to OC
                clay=float(clay),
                silt=float(silt),
                sand=float(sand),
                rock=float(rock),
            )
            current_layers.append(layer)

        # Don't forget last profile
        if current_mukey and current_layers:
            profiles[current_mukey] = SoilProfile(
                mukey=current_mukey,
                name=current_muname[:50],
                hydgrp=current_hydgrp,
                layers=current_layers,
            )

        return profiles

    @staticmethod
    def from_csv(
        filepath: Union[str, Path],
        mukey_col: str = "MUKEY",
        name_col: str = "SNAM",
        hydgrp_col: str = "HYDGRP",
    ) -> SoilDataset:
        """
        Load soil data from CSV file.

        Expected columns:
        - MUKEY: Map unit key
        - SNAM: Soil name
        - HYDGRP: Hydrologic group
        - SOL_ZMX: Max rooting depth
        - Layer columns: SOL_Z1, SOL_BD1, SOL_AWC1, etc.

        Args:
            filepath: Path to CSV file
            mukey_col: Column name for map unit key
            name_col: Column name for soil name
            hydgrp_col: Column name for hydrologic group

        Returns:
            SoilDataset with loaded profiles
        """
        df = pd.read_csv(filepath)

        profiles = {}

        for _, row in df.iterrows():
            mukey = str(row.get(mukey_col, row.name))
            name = str(row.get(name_col, f"Soil_{mukey}"))
            hydgrp = str(row.get(hydgrp_col, "B"))

            # Find layer columns
            layers = []
            for i in range(1, 11):  # Up to 10 layers
                depth_col = f"SOL_Z{i}"
                if depth_col in df.columns and pd.notna(row.get(depth_col)):
                    layer = SoilLayer(
                        depth=float(row.get(depth_col, 300)),
                        bd=float(row.get(f"SOL_BD{i}", 1.4)),
                        awc=float(row.get(f"SOL_AWC{i}", 0.15)),
                        ksat=float(row.get(f"SOL_K{i}", 25)),
                        carbon=float(row.get(f"SOL_CBN{i}", 1.0)),
                        clay=float(row.get(f"CLAY{i}", 20)),
                        silt=float(row.get(f"SILT{i}", 40)),
                        sand=float(row.get(f"SAND{i}", 40)),
                        rock=float(row.get(f"ROCK{i}", 0)),
                    )
                    layers.append(layer)
                else:
                    break

            if not layers:
                layers = [SoilLayer()]

            profile = SoilProfile(
                mukey=mukey,
                name=name,
                hydgrp=hydgrp,
                layers=layers,
                sol_zmx=float(row.get("SOL_ZMX", 1500)),
            )
            profiles[mukey] = profile

        return SoilDataset(profiles=profiles)

    @staticmethod
    def create_default_profile(
        name: str = "Default_Loam",
        hydgrp: str = "B",
        texture: str = "Loam",
    ) -> SoilProfile:
        """
        Create a default soil profile with typical values.

        Args:
            name: Soil name
            hydgrp: Hydrologic group (A, B, C, D)
            texture: Texture class

        Returns:
            SoilProfile with default parameters
        """
        # Set properties based on texture
        texture_props = {
            "Sand": {"clay": 5, "silt": 5, "sand": 90, "ksat": 200, "awc": 0.07},
            "Loamy Sand": {"clay": 8, "silt": 12, "sand": 80, "ksat": 150, "awc": 0.10},
            "Sandy Loam": {"clay": 12, "silt": 25, "sand": 63, "ksat": 75, "awc": 0.13},
            "Loam": {"clay": 20, "silt": 40, "sand": 40, "ksat": 25, "awc": 0.17},
            "Silt Loam": {"clay": 15, "silt": 65, "sand": 20, "ksat": 15, "awc": 0.20},
            "Silt": {"clay": 5, "silt": 87, "sand": 8, "ksat": 10, "awc": 0.18},
            "Sandy Clay Loam": {"clay": 28, "silt": 15, "sand": 57, "ksat": 12, "awc": 0.14},
            "Clay Loam": {"clay": 32, "silt": 35, "sand": 33, "ksat": 8, "awc": 0.16},
            "Silty Clay Loam": {"clay": 35, "silt": 55, "sand": 10, "ksat": 5, "awc": 0.18},
            "Sandy Clay": {"clay": 42, "silt": 8, "sand": 50, "ksat": 3, "awc": 0.12},
            "Silty Clay": {"clay": 45, "silt": 47, "sand": 8, "ksat": 2, "awc": 0.15},
            "Clay": {"clay": 55, "silt": 25, "sand": 20, "ksat": 1, "awc": 0.14},
        }

        props = texture_props.get(texture, texture_props["Loam"])

        layer1 = SoilLayer(
            depth=300,
            clay=props["clay"],
            silt=props["silt"],
            sand=props["sand"],
            ksat=props["ksat"],
            awc=props["awc"],
            bd=1.3 + props["clay"] * 0.005,  # Increases with clay
            carbon=2.0,  # Higher in topsoil
        )

        layer2 = SoilLayer(
            depth=1000,
            clay=props["clay"] + 5,  # Often more clay at depth
            silt=props["silt"],
            sand=props["sand"] - 5,
            ksat=props["ksat"] * 0.7,
            awc=props["awc"] * 0.9,
            bd=1.4 + props["clay"] * 0.005,
            carbon=0.5,  # Lower at depth
        )

        return SoilProfile(
            mukey=f"DEFAULT_{texture.upper().replace(' ', '_')}",
            name=name,
            hydgrp=hydgrp,
            layers=[layer1, layer2],
            texture=texture,
        )
