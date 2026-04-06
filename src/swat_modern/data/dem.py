"""
DEM processing utilities for SWAT watershed delineation.

This module provides tools for:
- Loading and processing Digital Elevation Models (DEMs)
- Filling sinks/depressions
- Computing flow direction and flow accumulation
- Delineating watersheds and subbasins
- Extracting stream networks

Requires optional GIS dependencies:
    pip install swat-dg[gis]
    # or: pip install rasterio numpy scipy

Example:
    >>> from swat_modern.data.dem import DEMProcessor
    >>>
    >>> # Load DEM
    >>> dem = DEMProcessor("elevation.tif")
    >>>
    >>> # Process for watershed delineation
    >>> dem.fill_sinks()
    >>> dem.compute_flow_direction()
    >>> dem.compute_flow_accumulation()
    >>>
    >>> # Delineate watershed from outlet
    >>> watershed = dem.delineate_watershed(outlet_x=500000, outlet_y=3500000)
    >>> watershed.save("watershed.tif")

References:
    - Jenson, S.K. and Domingue, J.O. (1988). Extracting Topographic Structure
      from Digital Elevation Data for Geographic Information System Analysis.
    - O'Callaghan, J.F. and Mark, D.M. (1984). The extraction of drainage
      networks from digital elevation data.
"""

from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union
from dataclasses import dataclass, field
import numpy as np
import warnings

# Check for optional dependencies
try:
    import rasterio
    from rasterio.transform import Affine
    from rasterio.crs import CRS
    HAS_RASTERIO = True
except ImportError:
    HAS_RASTERIO = False

try:
    from scipy import ndimage
    HAS_SCIPY = True
except ImportError:
    HAS_SCIPY = False


def _check_dependencies():
    """Check if required dependencies are available."""
    missing = []
    if not HAS_RASTERIO:
        missing.append("rasterio")
    if not HAS_SCIPY:
        missing.append("scipy")

    if missing:
        raise ImportError(
            f"DEM processing requires: {', '.join(missing)}. "
            f"Install with: pip install swat-dg[gis]"
        )


# D8 flow direction encoding
# Values represent direction to neighbor (power of 2)
# 32 64 128
# 16  X   1
#  8  4   2
D8_DIRECTIONS = {
    'E': 1,
    'SE': 2,
    'S': 4,
    'SW': 8,
    'W': 16,
    'NW': 32,
    'N': 64,
    'NE': 128,
}

# Row, column offsets for each direction
D8_OFFSETS = {
    1: (0, 1),    # E
    2: (1, 1),    # SE
    4: (1, 0),    # S
    8: (1, -1),   # SW
    16: (0, -1),  # W
    32: (-1, -1), # NW
    64: (-1, 0),  # N
    128: (-1, 1), # NE
}


@dataclass
class DEMMetadata:
    """
    Metadata for a DEM raster.

    Attributes:
        width: Number of columns
        height: Number of rows
        crs: Coordinate reference system
        transform: Affine transformation matrix
        bounds: (left, bottom, right, top) bounds
        resolution: (x_res, y_res) cell size
        nodata: NoData value
    """
    width: int
    height: int
    crs: str = None
    transform: tuple = None
    bounds: tuple = None
    resolution: tuple = None
    nodata: float = None

    @property
    def cell_area(self) -> float:
        """Cell area in square units of CRS."""
        if self.resolution:
            return abs(self.resolution[0] * self.resolution[1])
        return 1.0


@dataclass
class WatershedResult:
    """
    Result of watershed delineation.

    Attributes:
        mask: Boolean array of watershed cells
        area_cells: Number of cells in watershed
        area_km2: Area in square kilometers (if CRS is projected)
        outlet: (row, col) of outlet cell
        bounds: (min_row, min_col, max_row, max_col)
        metadata: DEM metadata
    """
    mask: np.ndarray
    area_cells: int
    area_km2: float = None
    outlet: tuple = None
    bounds: tuple = None
    metadata: DEMMetadata = None

    def save(self, filepath: Union[str, Path], **kwargs) -> None:
        """
        Save watershed mask to GeoTIFF.

        Args:
            filepath: Output file path
            **kwargs: Additional arguments for rasterio
        """
        _check_dependencies()

        filepath = Path(filepath)

        profile = {
            'driver': 'GTiff',
            'dtype': 'uint8',
            'width': self.mask.shape[1],
            'height': self.mask.shape[0],
            'count': 1,
            'crs': self.metadata.crs if self.metadata else None,
            'transform': self.metadata.transform if self.metadata else None,
            'nodata': 0,
        }
        profile.update(kwargs)

        with rasterio.open(filepath, 'w', **profile) as dst:
            dst.write(self.mask.astype('uint8'), 1)


@dataclass
class StreamNetwork:
    """
    Extracted stream network.

    Attributes:
        segments: List of stream segments (each is array of (row, col) points)
        orders: Stream orders for each segment
        lengths: Length of each segment
        total_length: Total stream length
    """
    segments: List[np.ndarray]
    orders: List[int] = None
    lengths: List[float] = None
    total_length: float = None

    def to_geodataframe(self):
        """Convert to GeoDataFrame (requires geopandas)."""
        try:
            import geopandas as gpd
            from shapely.geometry import LineString
        except ImportError:
            raise ImportError("geopandas is required: pip install geopandas")

        geometries = []
        for segment in self.segments:
            if len(segment) >= 2:
                geometries.append(LineString(segment))

        data = {'geometry': geometries}
        if self.orders:
            data['order'] = self.orders[:len(geometries)]
        if self.lengths:
            data['length'] = self.lengths[:len(geometries)]

        return gpd.GeoDataFrame(data)


class DEMProcessor:
    """
    Digital Elevation Model processor for watershed analysis.

    Provides methods for:
    - Loading DEMs from various formats
    - Sink filling (depression removal)
    - D8 flow direction computation
    - Flow accumulation
    - Watershed delineation
    - Stream network extraction

    Example:
        >>> dem = DEMProcessor("dem.tif")
        >>> dem.fill_sinks()
        >>> dem.compute_flow_direction()
        >>> dem.compute_flow_accumulation()
        >>>
        >>> # Delineate watershed
        >>> ws = dem.delineate_watershed(outlet_x=500000, outlet_y=3500000)
        >>> print(f"Watershed area: {ws.area_km2:.2f} km²")
        >>>
        >>> # Extract streams
        >>> streams = dem.extract_streams(threshold=1000)
    """

    def __init__(
        self,
        dem_path: Union[str, Path] = None,
        dem_array: np.ndarray = None,
        resolution: float = None,
        nodata: float = -9999,
    ):
        """
        Initialize DEM processor.

        Args:
            dem_path: Path to DEM raster file (GeoTIFF, etc.)
            dem_array: Alternatively, provide DEM as numpy array
            resolution: Cell size (required if using dem_array)
            nodata: NoData value (default: -9999)
        """
        _check_dependencies()

        self.dem_path = Path(dem_path) if dem_path else None
        self.nodata = nodata

        # Initialize arrays
        self.elevation: np.ndarray = None
        self.filled: np.ndarray = None
        self.flow_direction: np.ndarray = None
        self.flow_accumulation: np.ndarray = None
        self.metadata: DEMMetadata = None

        # Load DEM
        if dem_path:
            self._load_from_file(dem_path)
        elif dem_array is not None:
            self._load_from_array(dem_array, resolution, nodata)
        else:
            raise ValueError("Must provide either dem_path or dem_array")

    def _load_from_file(self, filepath: Union[str, Path]) -> None:
        """Load DEM from raster file."""
        filepath = Path(filepath)

        if not filepath.exists():
            raise FileNotFoundError(f"DEM file not found: {filepath}")

        with rasterio.open(filepath) as src:
            self.elevation = src.read(1).astype(np.float64)

            # Handle nodata
            if src.nodata is not None:
                self.nodata = src.nodata
                self.elevation[self.elevation == self.nodata] = np.nan

            # Extract metadata
            self.metadata = DEMMetadata(
                width=src.width,
                height=src.height,
                crs=str(src.crs) if src.crs else None,
                transform=src.transform.to_gdal() if src.transform else None,
                bounds=src.bounds,
                resolution=(src.res[0], src.res[1]) if src.res else None,
                nodata=self.nodata,
            )

    def _load_from_array(
        self,
        array: np.ndarray,
        resolution: float,
        nodata: float,
    ) -> None:
        """Load DEM from numpy array."""
        self.elevation = array.astype(np.float64)
        self.nodata = nodata

        # Handle nodata
        if nodata is not None:
            self.elevation[self.elevation == nodata] = np.nan

        self.metadata = DEMMetadata(
            width=array.shape[1],
            height=array.shape[0],
            resolution=(resolution, resolution) if resolution else None,
            nodata=nodata,
        )

    def fill_sinks(self, method: str = "planchon") -> np.ndarray:
        """
        Fill sinks (depressions) in DEM.

        Sinks are cells or groups of cells surrounded by higher terrain
        that would trap water. These must be filled for proper flow routing.

        Args:
            method: Fill method - "planchon" (default) or "simple"
                - "planchon": Planchon & Darboux (2001) algorithm
                - "simple": Simple iterative filling

        Returns:
            Filled DEM array
        """
        if method == "planchon":
            self.filled = self._fill_sinks_planchon()
        elif method == "simple":
            self.filled = self._fill_sinks_simple()
        else:
            raise ValueError(f"Unknown fill method: {method}")

        return self.filled

    def _fill_sinks_planchon(self) -> np.ndarray:
        """
        Fill sinks using Planchon & Darboux (2001) algorithm.

        This is an efficient algorithm that fills depressions by
        iteratively raising cells until water can drain.
        """
        dem = self.elevation.copy()
        rows, cols = dem.shape

        # Initialize with infinity except edges
        filled = np.full_like(dem, np.inf)

        # Set edge cells to DEM values
        filled[0, :] = dem[0, :]
        filled[-1, :] = dem[-1, :]
        filled[:, 0] = dem[:, 0]
        filled[:, -1] = dem[:, -1]

        # Also set NaN cells
        filled[np.isnan(dem)] = np.nan

        # Small increment for flat areas
        epsilon = 1e-5

        # Iteratively fill
        changed = True
        iterations = 0
        max_iterations = rows * cols  # Safety limit

        while changed and iterations < max_iterations:
            changed = False
            iterations += 1

            for i in range(1, rows - 1):
                for j in range(1, cols - 1):
                    if np.isnan(dem[i, j]):
                        continue

                    if filled[i, j] > dem[i, j]:
                        # Check neighbors
                        for di, dj in [(-1,-1), (-1,0), (-1,1), (0,-1),
                                       (0,1), (1,-1), (1,0), (1,1)]:
                            ni, nj = i + di, j + dj

                            if np.isnan(filled[ni, nj]):
                                continue

                            # Can drain to this neighbor
                            if dem[i, j] >= filled[ni, nj] + epsilon:
                                filled[i, j] = dem[i, j]
                                changed = True
                                break

                            # Need to raise to drain
                            if filled[i, j] > filled[ni, nj] + epsilon:
                                filled[i, j] = filled[ni, nj] + epsilon
                                changed = True

        return filled

    def _fill_sinks_simple(self) -> np.ndarray:
        """
        Simple iterative sink filling.

        Less efficient but more straightforward implementation.
        """
        filled = self.elevation.copy()
        rows, cols = filled.shape

        changed = True
        while changed:
            changed = False

            for i in range(1, rows - 1):
                for j in range(1, cols - 1):
                    if np.isnan(filled[i, j]):
                        continue

                    # Get minimum neighbor
                    neighbors = []
                    for di, dj in [(-1,0), (1,0), (0,-1), (0,1)]:
                        ni, nj = i + di, j + dj
                        if not np.isnan(filled[ni, nj]):
                            neighbors.append(filled[ni, nj])

                    if neighbors:
                        min_neighbor = min(neighbors)
                        if filled[i, j] < min_neighbor:
                            filled[i, j] = min_neighbor + 1e-5
                            changed = True

        return filled

    def compute_flow_direction(self) -> np.ndarray:
        """
        Compute D8 flow direction.

        The D8 algorithm assigns flow to one of 8 neighbors based on
        steepest descent. Direction is encoded as powers of 2:

            32  64  128
            16   X    1
             8   4    2

        Returns:
            Flow direction array (uint8)
        """
        if self.filled is None:
            warnings.warn("DEM not filled. Using original elevations.")
            dem = self.elevation
        else:
            dem = self.filled

        rows, cols = dem.shape
        flow_dir = np.zeros((rows, cols), dtype=np.uint8)

        # Direction offsets and values
        offsets = [
            (0, 1, 1),    # E
            (1, 1, 2),    # SE
            (1, 0, 4),    # S
            (1, -1, 8),   # SW
            (0, -1, 16),  # W
            (-1, -1, 32), # NW
            (-1, 0, 64),  # N
            (-1, 1, 128), # NE
        ]

        # Distance factors for diagonal vs cardinal
        dist_factors = [1, np.sqrt(2), 1, np.sqrt(2), 1, np.sqrt(2), 1, np.sqrt(2)]

        for i in range(1, rows - 1):
            for j in range(1, cols - 1):
                if np.isnan(dem[i, j]):
                    continue

                max_slope = 0
                max_dir = 0

                for k, (di, dj, direction) in enumerate(offsets):
                    ni, nj = i + di, j + dj

                    if np.isnan(dem[ni, nj]):
                        continue

                    # Calculate slope
                    drop = dem[i, j] - dem[ni, nj]
                    slope = drop / dist_factors[k]

                    if slope > max_slope:
                        max_slope = slope
                        max_dir = direction

                flow_dir[i, j] = max_dir

        self.flow_direction = flow_dir
        return flow_dir

    def compute_flow_accumulation(self) -> np.ndarray:
        """
        Compute flow accumulation.

        Flow accumulation counts the number of cells that flow into
        each cell. High values indicate stream channels.

        Returns:
            Flow accumulation array
        """
        if self.flow_direction is None:
            raise RuntimeError("Must compute flow direction first")

        rows, cols = self.flow_direction.shape
        accumulation = np.ones((rows, cols), dtype=np.float64)

        # Mark NaN cells
        if self.elevation is not None:
            accumulation[np.isnan(self.elevation)] = 0

        # Create dependency count
        dependency = np.zeros((rows, cols), dtype=np.int32)

        for i in range(rows):
            for j in range(cols):
                direction = self.flow_direction[i, j]
                if direction in D8_OFFSETS:
                    di, dj = D8_OFFSETS[direction]
                    ni, nj = i + di, j + dj
                    if 0 <= ni < rows and 0 <= nj < cols:
                        dependency[ni, nj] += 1

        # Process cells with no dependencies first (topological sort)
        queue = []
        for i in range(rows):
            for j in range(cols):
                if dependency[i, j] == 0 and self.flow_direction[i, j] > 0:
                    queue.append((i, j))

        while queue:
            i, j = queue.pop(0)
            direction = self.flow_direction[i, j]

            if direction in D8_OFFSETS:
                di, dj = D8_OFFSETS[direction]
                ni, nj = i + di, j + dj

                if 0 <= ni < rows and 0 <= nj < cols:
                    accumulation[ni, nj] += accumulation[i, j]
                    dependency[ni, nj] -= 1

                    if dependency[ni, nj] == 0:
                        queue.append((ni, nj))

        self.flow_accumulation = accumulation
        return accumulation

    def delineate_watershed(
        self,
        outlet_x: float = None,
        outlet_y: float = None,
        outlet_row: int = None,
        outlet_col: int = None,
        snap_threshold: int = 100,
    ) -> WatershedResult:
        """
        Delineate watershed from outlet point.

        Args:
            outlet_x: Outlet X coordinate (in CRS units)
            outlet_y: Outlet Y coordinate (in CRS units)
            outlet_row: Outlet row index (alternative to coordinates)
            outlet_col: Outlet column index
            snap_threshold: Snap outlet to high flow accumulation within
                           this many cells (default: 100)

        Returns:
            WatershedResult with watershed mask and statistics
        """
        if self.flow_direction is None:
            raise RuntimeError("Must compute flow direction first")

        rows, cols = self.flow_direction.shape

        # Convert coordinates to row/col
        if outlet_row is None or outlet_col is None:
            if outlet_x is None or outlet_y is None:
                raise ValueError("Must provide outlet coordinates or row/col")
            outlet_row, outlet_col = self._coords_to_rowcol(outlet_x, outlet_y)

        # Snap to high flow accumulation
        if self.flow_accumulation is not None and snap_threshold > 0:
            outlet_row, outlet_col = self._snap_to_stream(
                outlet_row, outlet_col, snap_threshold
            )

        # Trace upstream
        watershed = np.zeros((rows, cols), dtype=bool)
        self._trace_upstream(outlet_row, outlet_col, watershed)

        # Calculate statistics
        area_cells = np.sum(watershed)

        area_km2 = None
        if self.metadata and self.metadata.resolution:
            cell_area_m2 = abs(
                self.metadata.resolution[0] * self.metadata.resolution[1]
            )
            area_km2 = (area_cells * cell_area_m2) / 1e6

        # Find bounds
        rows_ws, cols_ws = np.where(watershed)
        if len(rows_ws) > 0:
            bounds = (
                rows_ws.min(), cols_ws.min(),
                rows_ws.max(), cols_ws.max()
            )
        else:
            bounds = None

        return WatershedResult(
            mask=watershed,
            area_cells=area_cells,
            area_km2=area_km2,
            outlet=(outlet_row, outlet_col),
            bounds=bounds,
            metadata=self.metadata,
        )

    def _coords_to_rowcol(self, x: float, y: float) -> Tuple[int, int]:
        """Convert coordinates to row/column indices."""
        if self.metadata and self.metadata.transform:
            # Use affine transform
            transform = Affine.from_gdal(*self.metadata.transform)
            col, row = ~transform * (x, y)
            return int(row), int(col)
        else:
            raise ValueError(
                "No transform available. Use outlet_row/outlet_col instead."
            )

    def _snap_to_stream(
        self,
        row: int,
        col: int,
        threshold: int,
    ) -> Tuple[int, int]:
        """Snap point to nearest high flow accumulation cell."""
        if self.flow_accumulation is None:
            return row, col

        rows, cols = self.flow_accumulation.shape

        # Search window
        r_min = max(0, row - threshold)
        r_max = min(rows, row + threshold + 1)
        c_min = max(0, col - threshold)
        c_max = min(cols, col + threshold + 1)

        window = self.flow_accumulation[r_min:r_max, c_min:c_max]

        # Find max accumulation in window
        max_idx = np.unravel_index(np.argmax(window), window.shape)

        return r_min + max_idx[0], c_min + max_idx[1]

    def _trace_upstream(
        self,
        row: int,
        col: int,
        watershed: np.ndarray,
    ) -> None:
        """Recursively trace upstream cells."""
        rows, cols = self.flow_direction.shape

        # Use iterative approach to avoid recursion limit
        stack = [(row, col)]

        while stack:
            r, c = stack.pop()

            if watershed[r, c]:
                continue

            watershed[r, c] = True

            # Find cells that flow into this one
            for direction, (dr, dc) in D8_OFFSETS.items():
                nr, nc = r - dr, c - dc  # Opposite direction

                if 0 <= nr < rows and 0 <= nc < cols:
                    if self.flow_direction[nr, nc] == direction:
                        if not watershed[nr, nc]:
                            stack.append((nr, nc))

    def extract_streams(
        self,
        threshold: int = 1000,
        compute_order: bool = True,
    ) -> StreamNetwork:
        """
        Extract stream network based on flow accumulation threshold.

        Args:
            threshold: Minimum flow accumulation to define a stream cell
            compute_order: Calculate Strahler stream order

        Returns:
            StreamNetwork with stream segments
        """
        if self.flow_accumulation is None:
            raise RuntimeError("Must compute flow accumulation first")

        # Identify stream cells
        stream_cells = self.flow_accumulation >= threshold

        # Extract connected segments
        labeled, n_features = ndimage.label(stream_cells)

        segments = []
        for i in range(1, n_features + 1):
            segment_mask = labeled == i
            rows, cols = np.where(segment_mask)

            if len(rows) > 0:
                # Order points by flow direction
                points = self._order_stream_points(rows, cols)
                segments.append(points)

        # Calculate stream orders if requested
        orders = None
        if compute_order:
            orders = self._compute_stream_orders(segments)

        # Calculate lengths
        lengths = []
        cell_size = 1.0
        if self.metadata and self.metadata.resolution:
            cell_size = self.metadata.resolution[0]

        for segment in segments:
            if len(segment) >= 2:
                # Sum distances between consecutive points
                diffs = np.diff(segment, axis=0)
                distances = np.sqrt(np.sum(diffs**2, axis=1)) * cell_size
                lengths.append(np.sum(distances))
            else:
                lengths.append(0)

        return StreamNetwork(
            segments=segments,
            orders=orders,
            lengths=lengths,
            total_length=sum(lengths),
        )

    def _order_stream_points(
        self,
        rows: np.ndarray,
        cols: np.ndarray,
    ) -> np.ndarray:
        """Order stream segment points by flow direction."""
        # Simple approach: sort by flow accumulation (descending)
        if self.flow_accumulation is not None:
            accum = self.flow_accumulation[rows, cols]
            order = np.argsort(-accum)
            return np.column_stack([cols[order], rows[order]])
        else:
            return np.column_stack([cols, rows])

    def _compute_stream_orders(
        self,
        segments: List[np.ndarray],
    ) -> List[int]:
        """Compute Strahler stream orders (simplified)."""
        # Simplified: assign order based on segment length
        lengths = [len(seg) for seg in segments]
        max_length = max(lengths) if lengths else 1

        orders = []
        for seg in segments:
            # Rough order estimate
            order = max(1, int(np.log2(len(seg) / max_length * 8) + 1))
            orders.append(min(order, 7))  # Cap at 7

        return orders

    def get_slope(self) -> np.ndarray:
        """
        Calculate slope from DEM.

        Returns:
            Slope in degrees
        """
        dem = self.filled if self.filled is not None else self.elevation

        cell_size = 1.0
        if self.metadata and self.metadata.resolution:
            cell_size = self.metadata.resolution[0]

        # Calculate gradients
        gy, gx = np.gradient(dem, cell_size)

        # Calculate slope magnitude
        slope_rad = np.arctan(np.sqrt(gx**2 + gy**2))
        slope_deg = np.degrees(slope_rad)

        return slope_deg

    def get_aspect(self) -> np.ndarray:
        """
        Calculate aspect from DEM.

        Returns:
            Aspect in degrees (0-360, 0=North, 90=East)
        """
        dem = self.filled if self.filled is not None else self.elevation

        cell_size = 1.0
        if self.metadata and self.metadata.resolution:
            cell_size = self.metadata.resolution[0]

        gy, gx = np.gradient(dem, cell_size)

        # Calculate aspect
        aspect = np.degrees(np.arctan2(-gx, gy))
        aspect = (aspect + 360) % 360

        return aspect

    def save(
        self,
        filepath: Union[str, Path],
        data: str = "elevation",
        **kwargs,
    ) -> None:
        """
        Save raster data to file.

        Args:
            filepath: Output file path
            data: Which data to save - "elevation", "filled",
                  "flow_direction", "flow_accumulation", "slope", "aspect"
            **kwargs: Additional arguments for rasterio
        """
        filepath = Path(filepath)

        # Get data array and set nodata handling flag
        nodata_value = self.nodata
        if data == "elevation":
            array = self.elevation
            dtype = 'float32'
        elif data == "filled":
            array = self.filled
            dtype = 'float32'
        elif data == "flow_direction":
            array = self.flow_direction
            dtype = 'uint8'
            nodata_value = None  # Flow direction doesn't need nodata
        elif data == "flow_accumulation":
            array = self.flow_accumulation
            dtype = 'float32'
        elif data == "slope":
            array = self.get_slope()
            dtype = 'float32'
        elif data == "aspect":
            array = self.get_aspect()
            dtype = 'float32'
        else:
            raise ValueError(f"Unknown data type: {data}")

        if array is None:
            raise ValueError(f"Data '{data}' not available. Compute it first.")

        profile = {
            'driver': 'GTiff',
            'dtype': dtype,
            'width': array.shape[1],
            'height': array.shape[0],
            'count': 1,
            'crs': self.metadata.crs if self.metadata else None,
            'transform': Affine.from_gdal(*self.metadata.transform) if self.metadata and self.metadata.transform else None,
            'nodata': nodata_value,
        }
        profile.update(kwargs)

        # Handle NaN values
        output = array.copy()
        if dtype.startswith('float'):
            output = np.where(np.isnan(output), self.nodata, output)

        with rasterio.open(filepath, 'w', **profile) as dst:
            dst.write(output.astype(dtype), 1)

    def summary(self) -> str:
        """Generate summary of DEM and derived data."""
        lines = [
            "DEM Summary",
            "=" * 50,
        ]

        if self.metadata:
            lines.extend([
                f"Size: {self.metadata.width} x {self.metadata.height} cells",
                f"CRS: {self.metadata.crs or 'Unknown'}",
            ])
            if self.metadata.resolution:
                lines.append(
                    f"Resolution: {self.metadata.resolution[0]:.2f} x "
                    f"{self.metadata.resolution[1]:.2f}"
                )
            if self.metadata.bounds:
                lines.append(f"Bounds: {self.metadata.bounds}")

        if self.elevation is not None:
            valid = ~np.isnan(self.elevation)
            lines.extend([
                f"",
                f"Elevation:",
                f"  Min: {np.nanmin(self.elevation):.2f}",
                f"  Max: {np.nanmax(self.elevation):.2f}",
                f"  Mean: {np.nanmean(self.elevation):.2f}",
                f"  Valid cells: {np.sum(valid):,}",
            ])

        if self.flow_accumulation is not None:
            lines.extend([
                f"",
                f"Flow Accumulation:",
                f"  Max: {np.max(self.flow_accumulation):.0f}",
            ])

        lines.extend([
            f"",
            f"Computed:",
            f"  Filled: {'Yes' if self.filled is not None else 'No'}",
            f"  Flow Direction: {'Yes' if self.flow_direction is not None else 'No'}",
            f"  Flow Accumulation: {'Yes' if self.flow_accumulation is not None else 'No'}",
        ])

        return "\n".join(lines)
