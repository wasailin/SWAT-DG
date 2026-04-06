# Installation Guide

## Requirements

- **Python 3.10 or higher**
- **SWAT2012 executable** - Compiled Fortran binary (see below)

## Basic Installation

Install from PyPI:

```bash
pip install swat-dg
```

## Installation Options

### Calibration Support (SPOTPY)

For automated calibration with 8+ optimization algorithms:

```bash
pip install swat-dg[calibration]
```

This installs:
- `spotpy>=1.5` - Calibration algorithms (SCE-UA, DREAM, Monte Carlo, etc.)

### GIS Support

For raster processing and watershed delineation:

```bash
pip install swat-dg[gis]
```

This installs:
- `geopandas>=0.10` - Geospatial data handling
- `rasterio>=1.2` - Raster I/O (GeoTIFF)
- `pyproj>=3.0` - Coordinate transformations
- `xarray>=0.19` - N-dimensional arrays

### Data Automation

For automated weather and soil data retrieval:

```bash
pip install swat-dg[data]
```

This installs:
- `requests>=2.25` - HTTP requests for API access

### Full Installation

Install all optional dependencies:

```bash
pip install swat-dg[full]
```

## Development Installation

For contributing or development:

```bash
# Clone the repository
git clone https://github.com/wasailin/SWAT-DG.git
cd swat-dg

# Install in development mode with dev dependencies
pip install -e ".[dev,full]"
```

Development dependencies include:
- `pytest>=7.0` - Testing framework
- `pytest-cov>=3.0` - Coverage reporting
- `black>=22.0` - Code formatting
- `mypy>=0.990` - Type checking

## SWAT Executable Setup

SWAT-DG requires the SWAT2012 executable to run simulations. You can either:
1. Compile from source (recommended)
2. Use a pre-compiled binary

### Option 1: Compile from Source (Recommended)

The project includes build scripts for compiling SWAT2012:

```bash
cd fortran
# Windows
build_windows.bat

# Linux/Mac
chmod +x build_unix.sh
./build_unix.sh
```

#### Prerequisites for Compilation

**Windows:**
1. Install [CMake](https://cmake.org/download/)
2. Install [MSYS2](https://www.msys2.org/) and GFortran:
   ```bash
   pacman -S mingw-w64-x86_64-gcc-fortran
   ```

**Linux (Ubuntu/Debian):**
```bash
sudo apt update
sudo apt install cmake gfortran
```

**Mac:**
```bash
brew install cmake gcc
```

### Option 2: Pre-compiled Binary

Download SWAT2012 Rev. 681 or above from [Texas A&M](https://swat.tamu.edu/software/swat-executables/), or get the custom-compiled executable from the [Releases](https://github.com/wasailin/SWAT-DG/releases) page.

### Configuring the Executable Path

Once you have the executable, configure it in your code:

```python
from swat_modern import SWATModel

# Option 1: Pass explicitly
model = SWATModel(
    "path/to/project",
    executable="C:/path/to/swat2012.exe"
)

# Option 2: Set environment variable
import os
os.environ["SWAT_EXE"] = "C:/path/to/swat2012.exe"
model = SWATModel("path/to/project")  # Uses SWAT_EXE
```

## Verifying Installation

Test that SWAT-DG is installed correctly:

```python
from swat_modern import SWATModel
from swat_modern.calibration import Calibrator
from swat_modern.calibration.objectives import nse, kge

print("SWAT-DG installed successfully!")
print(f"SWATModel: {SWATModel}")
print(f"Calibrator: {Calibrator}")
print(f"NSE function: {nse}")
```

Test with optional dependencies:

```python
# Test calibration
try:
    import spotpy
    print(f"SPOTPY {spotpy.__version__} available")
except ImportError:
    print("SPOTPY not installed - install with pip install swat-dg[calibration]")

# Test GIS
try:
    import rasterio
    import geopandas
    print(f"rasterio {rasterio.__version__} available")
    print(f"geopandas {geopandas.__version__} available")
except ImportError:
    print("GIS dependencies not installed - install with pip install swat-dg[gis]")
```

## Troubleshooting

### "ModuleNotFoundError: No module named 'swat_modern'"

Make sure you installed the package:
```bash
pip install swat-dg
```

> Note: The Python import name is `swat_modern` even though the package is installed as `swat-dg`.

### "No SWAT executable found"

Set the executable path explicitly or via environment variable:
```python
model = SWATModel("project", executable="path/to/swat2012.exe")
```

### "CMake not found" (when compiling)

Install CMake and ensure it's in your PATH:
- Windows: Download from https://cmake.org/download/
- Linux: `sudo apt install cmake`
- Mac: `brew install cmake`

### "No Fortran compiler found"

Install GFortran:
- Windows: Use MSYS2 or MinGW-w64
- Linux: `sudo apt install gfortran`
- Mac: `brew install gcc`

### Windows: "DLL load failed"

Ensure the Fortran runtime libraries are available. If using MinGW-compiled executables, you may need to add MinGW's `bin` directory to your PATH.

### Import errors with optional dependencies

Install the appropriate extra:
```bash
pip install swat-dg[calibration]  # For SPOTPY
pip install swat-dg[gis]          # For rasterio/geopandas
pip install swat-dg[full]         # For everything
```

## Platform-Specific Notes

### Windows

- Use forward slashes or raw strings for paths: `r"C:\path\to\project"` or `"C:/path/to/project"`
- Compiled executables from MinGW may require runtime DLLs

### Linux

- SWAT must be compiled from source
- Install gfortran: `sudo apt install gfortran`

### macOS

- Use Homebrew to install GCC: `brew install gcc`
- The Fortran compiler will be `gfortran-XX` (e.g., `gfortran-13`)

## Getting Help

- GitHub Issues: https://github.com/wasailin/SWAT-DG/issues
- SWAT Documentation: https://swat.tamu.edu/docs/
