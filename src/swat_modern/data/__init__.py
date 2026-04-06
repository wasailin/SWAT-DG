"""
SWAT Data Automation Module.

This module provides tools for automated retrieval and processing of
input data for SWAT models:

- Weather data from NOAA and other sources
- DEM processing and watershed delineation
- Soil data from SSURGO
- Land cover data from NLCD

Example usage:
    from swat_modern.data import WeatherDataFetcher

    # Fetch weather data for a location
    weather = WeatherDataFetcher.from_csv("weather.csv")

    # Generate SWAT weather files
    weather.to_swat_files("weather_files/")

DEM processing example:
    from swat_modern.data import DEMProcessor

    # Load and process DEM
    dem = DEMProcessor.from_file("elevation.tif")
    dem.fill_sinks()
    dem.compute_flow_direction()
    dem.compute_flow_accumulation()

    # Delineate watershed
    watershed = dem.delineate_watershed(outlet=(500, 350))

Soil data example:
    from swat_modern.data import SoilDataFetcher

    # Create default soil profile
    soil = SoilDataFetcher.create_default_profile("loam", depth_cm=150)
    soil.to_swat_file("output/000010001.sol")

Land cover example:
    from swat_modern.data import LandCoverFetcher, NLCDClass

    # Get SWAT land use code for NLCD class
    nlcd = NLCDClass.DECIDUOUS_FOREST
    swat_code = nlcd.swat_code  # Returns "FRSD"
"""

from swat_modern.data.weather import (
    WeatherDataFetcher,
    WeatherStation,
    WeatherData,
    NOAAClient,
)

from swat_modern.data.soil import (
    SoilDataFetcher,
    SoilLayer,
    SoilProfile,
    SoilDataset,
)

from swat_modern.data.landcover import (
    LandCoverFetcher,
    NLCDClass,
    NLCD_TO_SWAT,
)


# Lazy import for DEM (requires GIS dependencies)
def __getattr__(name):
    if name in ("DEMProcessor", "DEMMetadata", "WatershedResult", "StreamNetwork"):
        from swat_modern.data import dem as dem_module
        return getattr(dem_module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    # Weather
    "WeatherDataFetcher",
    "WeatherStation",
    "WeatherData",
    "NOAAClient",
    # Soil
    "SoilDataFetcher",
    "SoilLayer",
    "SoilProfile",
    "SoilDataset",
    # Land Cover
    "LandCoverFetcher",
    "NLCDClass",
    "NLCD_TO_SWAT",
    # DEM (lazy loaded)
    "DEMProcessor",
    "DEMMetadata",
    "WatershedResult",
    "StreamNetwork",
]
