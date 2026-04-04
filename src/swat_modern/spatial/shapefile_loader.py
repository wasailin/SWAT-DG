"""
Shapefile and spatial data loader for SWAT projects.

Discovers and loads shapefiles from SWAT project directories and
spatial layers from SWAT+ SQLite databases.
"""

import sqlite3
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

try:
    import geopandas as gpd
    HAS_GEOPANDAS = True
except ImportError:
    HAS_GEOPANDAS = False


def _require_geopandas():
    """Raise ImportError if geopandas is not installed."""
    if not HAS_GEOPANDAS:
        raise ImportError(
            "geopandas is required for spatial operations. "
            "Install with: pip install swat-dg[gis]"
        )


class ShapefileLoader:
    """
    Discover and load shapefiles from SWAT project directories.

    Searches common directory structures used by SWAT2012 and SWAT+:
    - project_dir/Watershed/Shapes/
    - project_dir/Shapes/
    - project_dir/../Watershed/Shapes/
    - SWAT+ SQLite databases (*.sqlite)

    Example:
        >>> loader = ShapefileLoader("C:/SWAT_project")
        >>> found = loader.find_shapefiles()
        >>> subbasins = loader.load_subbasins()
    """

    # Heuristic patterns for identifying layer types
    _SUBBASIN_PATTERNS = ["sub", "subbasin", "subbasins", "basin"]
    _STREAM_PATTERNS = ["riv", "river", "stream", "reach", "channel"]
    _BOUNDARY_PATTERNS = ["wshed", "watershed", "boundary", "outline"]
    _HRU_PATTERNS = ["hru", "lsu", "lsus", "landscape"]
    _RESERVOIR_PATTERNS = ["res", "reservoir", "reservoirs", "lake"]

    def __init__(self, project_dir: Union[str, Path]):
        """
        Initialize loader with project directory.

        Args:
            project_dir: Path to SWAT project directory.
        """
        self.project_dir = Path(project_dir)
        self._shapes_dir: Optional[Path] = None
        self._discovered: Optional[Dict[str, Path]] = None

    def find_shapefiles(self) -> Dict[str, Path]:
        """
        Discover shapefiles in common SWAT directory locations.

        Returns:
            Dict mapping layer type to shapefile path.
            Keys: 'subbasins', 'streams', 'boundary', 'hrus', 'reservoirs'
            Only includes layers that were found.
        """
        _require_geopandas()

        if self._discovered is not None:
            return self._discovered

        shapes_dir = self._find_shapes_dir()
        result: Dict[str, Path] = {}

        if shapes_dir is None:
            self._discovered = result
            return result

        self._shapes_dir = shapes_dir
        result = self._scan_directory_for_shapefiles(shapes_dir)
        self._discovered = result
        return result

    def scan_custom_directory(self, shapes_dir: Union[str, Path]) -> Dict[str, Path]:
        """
        Scan a custom directory for shapefiles.

        Args:
            shapes_dir: Path to directory containing shapefiles.

        Returns:
            Dict mapping layer type to shapefile path.
            Keys: 'subbasins', 'streams', 'boundary', 'hrus', 'reservoirs'
            Only includes layers that were found.
        """
        _require_geopandas()
        shapes_dir = Path(shapes_dir)

        if not shapes_dir.exists() or not shapes_dir.is_dir():
            return {}

        return self._scan_directory_for_shapefiles(shapes_dir)

    def _scan_directory_for_shapefiles(self, shapes_dir: Path) -> Dict[str, Path]:
        """
        Internal method to scan a directory for shapefiles and classify them.

        Args:
            shapes_dir: Path to directory to scan.

        Returns:
            Dict mapping layer type to shapefile path.
        """
        result: Dict[str, Path] = {}

        # Collect all .shp files
        shp_files = list(shapes_dir.glob("*.shp"))

        # Also check subdirectories one level deep
        for subdir in shapes_dir.iterdir():
            if subdir.is_dir():
                shp_files.extend(subdir.glob("*.shp"))

        # Classify each shapefile by name heuristic
        for shp in shp_files:
            stem = shp.stem.lower()
            if self._matches(stem, self._SUBBASIN_PATTERNS) and "subbasins" not in result:
                result["subbasins"] = shp
            elif self._matches(stem, self._STREAM_PATTERNS) and "streams" not in result:
                result["streams"] = shp
            elif self._matches(stem, self._BOUNDARY_PATTERNS) and "boundary" not in result:
                result["boundary"] = shp
            elif self._matches(stem, self._HRU_PATTERNS) and "hrus" not in result:
                result["hrus"] = shp
            elif self._matches(stem, self._RESERVOIR_PATTERNS) and "reservoirs" not in result:
                result["reservoirs"] = shp

        return result

    def find_sqlite_layers(self) -> Dict[str, Tuple[Path, str]]:
        """
        Discover spatial layers in SWAT+ SQLite databases.

        Searches for .sqlite files in the project directory and its
        gis.data/ subdirectory, then lists tables that contain geometry.

        Returns:
            Dict mapping layer name to (sqlite_path, table_name) tuple.
        """
        _require_geopandas()

        result: Dict[str, Tuple[Path, str]] = {}
        search_dirs = [
            self.project_dir,
            self.project_dir / "gis.data",
        ]

        # Also check SWAT+ subdirectory patterns
        for d in self.project_dir.iterdir():
            if d.is_dir() and d.suffix == "-spt":
                search_dirs.append(d / "gis.data")

        for search_dir in search_dirs:
            if not search_dir.exists():
                continue
            for sqlite_file in search_dir.glob("*.sqlite"):
                try:
                    layers = self._list_sqlite_spatial_tables(sqlite_file)
                    for layer_name in layers:
                        key = f"{sqlite_file.stem}/{layer_name}"
                        result[key] = (sqlite_file, layer_name)
                except Exception:
                    continue

        return result

    def load_subbasins(self, path: Optional[Union[str, Path]] = None) -> "gpd.GeoDataFrame":
        """
        Load subbasin polygons and reproject to WGS84.

        Args:
            path: Explicit path to shapefile. If None, uses auto-discovered path.

        Returns:
            GeoDataFrame with subbasin polygons in EPSG:4326.
        """
        _require_geopandas()
        if path is None:
            found = self.find_shapefiles()
            path = found.get("subbasins")
            if path is None:
                raise FileNotFoundError(
                    "No subbasin shapefile found. "
                    "Provide path explicitly or ensure shapefiles are in Watershed/Shapes/"
                )
        return self._load_and_reproject(path)

    def load_streams(self, path: Optional[Union[str, Path]] = None) -> "gpd.GeoDataFrame":
        """
        Load stream network lines and reproject to WGS84.

        Args:
            path: Explicit path to shapefile. If None, uses auto-discovered path.

        Returns:
            GeoDataFrame with stream lines in EPSG:4326.
        """
        _require_geopandas()
        if path is None:
            found = self.find_shapefiles()
            path = found.get("streams")
            if path is None:
                raise FileNotFoundError("No stream shapefile found.")
        return self._load_and_reproject(path)

    def load_boundary(self, path: Optional[Union[str, Path]] = None) -> "gpd.GeoDataFrame":
        """
        Load watershed boundary polygon and reproject to WGS84.

        Args:
            path: Explicit path to shapefile. If None, uses auto-discovered path.

        Returns:
            GeoDataFrame with boundary polygon in EPSG:4326.
        """
        _require_geopandas()
        if path is None:
            found = self.find_shapefiles()
            path = found.get("boundary")
            if path is None:
                raise FileNotFoundError("No boundary shapefile found.")
        return self._load_and_reproject(path)

    def load_hrus(self, path: Optional[Union[str, Path]] = None) -> "gpd.GeoDataFrame":
        """Load HRU/landscape unit polygons and reproject to WGS84."""
        _require_geopandas()
        if path is None:
            found = self.find_shapefiles()
            path = found.get("hrus")
            if path is None:
                raise FileNotFoundError("No HRU shapefile found.")
        return self._load_and_reproject(path)

    def load_reservoirs(self, path: Optional[Union[str, Path]] = None) -> "gpd.GeoDataFrame":
        """Load reservoir points/polygons and reproject to WGS84."""
        _require_geopandas()
        if path is None:
            found = self.find_shapefiles()
            path = found.get("reservoirs")
            if path is None:
                raise FileNotFoundError("No reservoir shapefile found.")
        return self._load_and_reproject(path)

    def load_from_sqlite(
        self,
        sqlite_path: Union[str, Path],
        table_name: str,
    ) -> "gpd.GeoDataFrame":
        """
        Load a spatial layer from a SWAT+ SQLite database.

        Args:
            sqlite_path: Path to the .sqlite file.
            table_name: Name of the spatial table to load.

        Returns:
            GeoDataFrame reprojected to EPSG:4326.
        """
        _require_geopandas()
        gdf = gpd.read_file(str(sqlite_path), layer=table_name)
        return self.reproject_to_wgs84(gdf)

    def load_shapefile(self, path: Union[str, Path]) -> "gpd.GeoDataFrame":
        """
        Load any shapefile and reproject to WGS84.

        Args:
            path: Path to the .shp file.

        Returns:
            GeoDataFrame reprojected to EPSG:4326.
        """
        _require_geopandas()
        return self._load_and_reproject(path)

    @staticmethod
    def reproject_to_wgs84(gdf: "gpd.GeoDataFrame") -> "gpd.GeoDataFrame":
        """
        Reproject a GeoDataFrame to EPSG:4326 (WGS84).

        Args:
            gdf: Input GeoDataFrame with any CRS.

        Returns:
            GeoDataFrame in EPSG:4326.
        """
        if gdf.crs is None:
            # Assume WGS84 if no CRS defined
            gdf = gdf.set_crs("EPSG:4326")
        elif gdf.crs.to_epsg() != 4326:
            gdf = gdf.to_crs("EPSG:4326")
        return gdf

    # -------------------------------------------------------------------------
    # Private helpers
    # -------------------------------------------------------------------------

    def _find_shapes_dir(self) -> Optional[Path]:
        """Search for a Shapes directory in common locations."""
        candidates = [
            self.project_dir / "Watershed" / "Shapes",
            self.project_dir / "Shapes",
            self.project_dir.parent / "Watershed" / "Shapes",
            # Standard ArcSWAT/QSWAT: ~\Scenarios\Default\TxtInOut -> ~\Watershed\Shapes
            self.project_dir.parent.parent.parent / "Watershed" / "Shapes",
            # SWAT+ structure
            self.project_dir / "gis.data" / "Watershed" / "Shapes",
        ]

        # Also check SWAT+ project subdirs (name-spt pattern)
        for d in self.project_dir.parent.iterdir():
            if d.is_dir() and d.name.endswith("-spt"):
                candidates.append(d / "gis.data" / "Watershed" / "Shapes")

        for candidate in candidates:
            if candidate.exists() and candidate.is_dir():
                return candidate

        return None

    @staticmethod
    def _matches(stem: str, patterns: List[str]) -> bool:
        """Check if a filename stem matches any of the given patterns."""
        for pattern in patterns:
            if pattern in stem:
                return True
        return False

    def _load_and_reproject(self, path: Union[str, Path]) -> "gpd.GeoDataFrame":
        """Load a shapefile and reproject to WGS84."""
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Shapefile not found: {path}")
        gdf = gpd.read_file(str(path))
        return self.reproject_to_wgs84(gdf)

    @staticmethod
    def _list_sqlite_spatial_tables(sqlite_path: Path) -> List[str]:
        """List tables in a SQLite database that contain geometry columns."""
        tables = []
        conn = sqlite3.connect(str(sqlite_path))
        try:
            cursor = conn.cursor()
            # Check for SpatiaLite geometry_columns table
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name='geometry_columns'"
            )
            if cursor.fetchone():
                cursor.execute("SELECT f_table_name FROM geometry_columns")
                tables = [row[0] for row in cursor.fetchall()]
            else:
                # Check for gpkg_geometry_columns (GeoPackage format)
                cursor.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' "
                    "AND name='gpkg_geometry_columns'"
                )
                if cursor.fetchone():
                    cursor.execute("SELECT table_name FROM gpkg_geometry_columns")
                    tables = [row[0] for row in cursor.fetchall()]
        finally:
            conn.close()
        return tables
