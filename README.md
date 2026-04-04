# SWAT-DG

[![CI](https://github.com/wasailin/SWAT-DG/actions/workflows/ci.yml/badge.svg)](https://github.com/wasailin/SWAT-DG/actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

Python wrapper and automate calibration tools for the SWAT2012 hydrological model, with diagnostic-guided calibration.
Developed by [Lynxce](https://www.lynxce-env.com/)
Direct download from [Releases](https://github.com/wasailin/SWAT-DG/releases)

## Features

### Core Functionality
- **Run SWAT from Python** - Simple API to execute SWAT simulations
- **Read/Write Input Files** - Parse and modify SWAT input parameters (.bsn, .sol, .mgt, .gw, .cio)
- **Parse Outputs** - Convert SWAT outputs to pandas DataFrames (output.rch, output.sub, output.hru, output.std, output.rsv)
- **Backup/Restore** - Safely backup and restore project files (selective backup for 99.9% size reduction)
- **fig.fig Routing Parser** - Parse watershed routing, upstream/downstream traversal, partial-basin simulation via active subbasins


### Calibration (SPOTPY Integration)
- **8+ Optimization Algorithms** - SCE-UA, DREAM, Monte Carlo, LHS, ROPE, DE-MCZ, and more
- **45+ Calibration Parameters** - Pre-defined parameters with recommended bounds
- **Parameter Boundary Manager** - Customize search bounds per parameter
- **Objective Functions** - NSE, KGE, PBIAS, RMSE, MAE, R-squared, RSR, Log-NSE
- **Sensitivity Analysis** - FAST and Sobol methods (parallel-capable)
- **Multi-site Calibration** - Calibrate using multiple observation points simultaneously
- **Sequential Multi-site Calibration** - Upstream-to-downstream step-by-step calibration
- **Parallel Calibration** - Multi-core calibration via pathos

### Diagnostic-Guided Calibration
- **Diagnostic Calibration** - Physics-based parameter guidance from observed vs. simulated signatures (baseflow separation, peak analysis, volume balance, seasonal bias, FDC metrics)
- **Ensemble Diagnostic Calibration** - Multiple diagnostic runs for robust parameter estimation with uncertainty
- **Phased Calibration** - Sequential hydrology → sediment → nitrogen → phosphorus workflow
- **Multi-constituent WQ Calibration** - Calibrate sediment, nitrogen, and phosphorus loads
- **Load Calculator** - Convert SWAT output concentrations to constituent loads
- **WQ Diagnostics** - Specialized diagnostic engines for sediment, nitrogen, and phosphorus

### Streamlit Web App (7 Pages)
- **Project Setup** - Load SWAT project, auto-detect executable, display project info
- **Watershed Map** - Interactive Folium map of subbasins and reaches with simulation output overlay
- **Simulation Results** - View/export raw SWAT outputs, compare multiple simulations, filter by reach/subbasin
- **Observation Data** - Import observed data (NWIS API, CSV, Excel), manage multiple sites
- **Parameter Editor** - Edit parameters with live preview, batch editing, constraint validation, boundary editor
- **Calibration** - Select mode (single-site, multi-site, sequential), choose algorithm and parameters, run calibration
- **Results** - Performance metrics, hydrographs, scatter plots, export to JSON/CSV/HTML/PNG
- **Session Persistence** - Full app state saving (survives browser refresh)

### Visualization Dashboard
- **Hydrograph Plots** - Time series comparison of observed vs simulated (daily and monthly)
- **Scatter Plots** - 1:1 plots with performance metrics, residual plots
- **Flow Duration Curves** - Exceedance probability analysis
- **Metrics Tables** - Formatted performance metrics with rating (Poor/Fair/Good/Excellent)
- **Sensitivity Plots** - Parameter sensitivity tornado charts and ranking tables
- **Diagnostic Plots** - Baseflow separation, peak comparison, seasonal bias, rating curves, flow partition
- **Interactive Plotly Charts** - Interactive time series, multi-variable, bar summaries, scatter comparisons
- **Export** - Save to PNG, PDF, or HTML reports

### Observation Data Import
- **USGS NWIS** - Fetch streamflow and water quality data from USGS API
- **Multi-format Loader** - CSV, Excel, TXT, TSV, USGS RDB format with auto-detection
- **WQ Observation Loader** - ADEQ, OBS files, AWRC/WQP STORET, generic CSV; standardizes to mg/L

### Data Automation Pipeline (US-Focused)
- **Weather Data** - NOAA CDO API integration, auto-generate .pcp, .tmp, WGEN parameters
- **Soil Data** - SSURGO integration, soil texture classification, .sol file generation
- **Land Cover** - NLCD classification, SWAT code mapping, curve number lookup
- **DEM Processing** - Sink filling, D8 flow direction, flow accumulation, watershed delineation

### GIS / Spatial
- **Watershed Map Builder** - Interactive Folium/Leaflet maps with subbasins and reaches
- **Shapefile Loader** - Load GIS shapefiles, extract subbasin/reach topology

### Portable Distribution
- **SWAT-DG Portable** - Self-contained Windows ZIP with embedded Python; no installation needed
- Download from [Releases](https://github.com/wasailin/SWAT-DG/releases)

## Installation

```bash
pip install swat-dg
```

Or install from source:

```bash
git clone https://github.com/wasailin/SWAT-DG.git
cd swat-dg
pip install -e .
```

For calibration features:
```bash
pip install swat-dg[calibration]  # Installs spotpy, pathos
```

For GIS/spatial features:
```bash
pip install swat-dg[gis]  # Installs geopandas, rasterio, pyproj, xarray, folium
```

For data automation:
```bash
pip install swat-dg[data]  # Installs requests, openpyxl
```

For the Streamlit web app:
```bash
pip install swat-dg[app]  # Installs streamlit, plotly, folium
```

For all features:
```bash
pip install swat-dg[full]
```

## Quick Start

### Launch the Calibration App (Easiest!)

```bash
# Install with app dependencies
pip install -e ".[app]"

# Launch the calibration app
streamlit run src/swat_modern/app/main.py

# Opens browser at http://localhost:8501
# Browse to your SWAT project folder
# Load observation data, select parameters, run calibration!
```

The app runs **100% locally** - all data stays on your computer.

### Basic Usage

```python
from swat_modern import SWATModel

# Load a SWAT project
model = SWATModel("C:/my_watershed", executable="C:/swat2012.exe")

# Run simulation
result = model.run()

# Get streamflow output
flow = model.get_output("FLOW_OUTcms", output_type="rch", unit_id=1)
print(flow.head())

# Modify parameters
model.modify_parameter("CN2", -0.1, method="multiply")  # Reduce CN2 by 10%

# Run again
result2 = model.run()
```

### Calibration

```python
from swat_modern import SWATModel
from swat_modern.calibration import Calibrator

# Load model
model = SWATModel("C:/my_watershed")

# Create calibrator with observed data
calibrator = Calibrator(
    model=model,
    observed_data="streamflow.csv",
    parameters=["CN2", "ESCO", "GW_DELAY", "ALPHA_BF", "GWQMN"],
    output_variable="FLOW_OUT",
    reach_id=1,
    objective="nse"
)

# Run automatic calibration (parallel across cores)
results = calibrator.auto_calibrate(
    n_iterations=5000,
    algorithm="sceua",
    parallel=True,
    n_cores=4
)

# View results
results.print_summary()
results.plot_comparison()

# Save best parameters
results.save_best_parameters("best_params.json")
```

### Diagnostic-Guided Calibration

```python
from swat_modern.calibration import Calibrator

calibrator = Calibrator(model=model, observed_data="streamflow.csv", reach_id=1)

# Single diagnostic run (uses flow signatures to guide parameter selection)
result = calibrator.diagnostic_calibrate(n_iterations=2000)

# Ensemble diagnostic (multiple runs for uncertainty)
result = calibrator.ensemble_diagnostic_calibrate(n_ensemble=5, n_iterations=1000)

# Phased: hydrology first, then sediment, then nitrogen, then phosphorus
result = calibrator.phased_calibrate(phases=["hydrology", "sediment", "nitrogen", "phosphorus"])
```

### Sensitivity Analysis

```python
from swat_modern.calibration import Calibrator

calibrator = Calibrator(model=model, observed_data="streamflow.csv", reach_id=1)

# Parallel sensitivity analysis
sa_result = calibrator.sensitivity_analysis(
    method="fast",
    n_samples=500,
    parallel=True,
    n_cores=4
)

sa_result.plot_rankings()
print(sa_result.top_parameters(n=10))
```

### Using Objective Functions

```python
from swat_modern.calibration.objectives import nse, kge, pbias, rsr, evaluate_model

# Calculate single metric
score = nse(observed, simulated)
print(f"NSE = {score:.3f}")

# Calculate multiple metrics
metrics = evaluate_model(observed, simulated)
print(metrics)  # {'nse': 0.85, 'kge': 0.78, 'pbias': 5.2, 'rsr': 0.45, ...}
```

### Visualization Dashboard

```python
from swat_modern.visualization import CalibrationDashboard

dashboard = CalibrationDashboard(
    dates=dates,
    observed=observed,
    simulated=simulated,
    site_name="Big Creek Watershed",
    variable_name="Streamflow",
    units="m³/s"
)

dashboard.create_dashboard()
dashboard.save("calibration_report.png")
dashboard.to_html("calibration_report.html")
```

## Requirements

- Python 3.10+
- numpy, pandas, matplotlib
- SWAT2012 executable (compiled Fortran)

## Calibration Parameters

The package includes 45+ pre-defined calibration parameters organized by group:

| Group | Parameters |
|-------|------------|
| Hydrology | CN2, ESCO, EPCO, SURLAG, OV_N, CANMX |
| Groundwater | GW_DELAY, ALPHA_BF, ALPHA_BF_D, GWQMN, REVAPMN, GW_REVAP, RCHRG_DP |
| Soil | SOL_AWC, SOL_K, SOL_BD |
| Routing | CH_N2, CH_K2 |
| Sediment | USLE_P, USLE_K, SPCON, SPEXP, CH_COV1, CH_COV2, PRF, ADJ_PKR |
| Nutrients | NPERCO, PPERCO, CMN, PSP, N_UPDIS, PHOSKD, ERORGP, and more |

## Calibration Algorithms

Via SPOTPY integration:

- **SCE-UA** - Shuffled Complex Evolution (recommended for hydrology)
- **DREAM** - Differential Evolution Adaptive Metropolis (with uncertainty)
- **MC** - Monte Carlo sampling (fully parallelizable)
- **LHS** - Latin Hypercube Sampling (fully parallelizable)
- **ROPE** - Robust Parameter Estimation
- **DE-MCZ** - Differential Evolution MCMC

Diagnostic-guided (built-in):

- **diagnostic** - Physics-based single diagnostic run
- **diagnostic_ensemble** - Multiple diagnostic runs with uncertainty
- **phased** - Sequential hydrology → sediment → nitrogen → phosphorus

## Documentation

See the `docs/` folder:
- [Quick Start](docs/quickstart.md)
- [Installation](docs/installation.md)
- [API Reference](docs/api_reference.md)
- [User Manual](docs/user_manual.md)

## Project Status

Current version: **v0.5.0**

### Phase 1: Python Wrapper Foundation ✅
- [x] Basic SWAT model wrapper (`SWATModel`)
- [x] Output file parsing (output.rch, output.sub, output.hru, output.std, output.rsv)
- [x] Input file parsing (.bsn, .sol, .mgt, .gw, .cio, fig.fig)
- [x] Parameter modification (replace, multiply, add methods)
- [x] Project backup/restore (selective file types for 99.9% size reduction)

### Phase 2: Calibration Automation ✅
- [x] SPOTPY calibration integration (8+ algorithms)
- [x] Objective functions (NSE, KGE, PBIAS, RMSE, MAE, R², Log-NSE, RSR)
- [x] 45+ calibration parameter definitions with recommended bounds
- [x] Sensitivity analysis (FAST, Sobol) with parallel support
- [x] Multi-site calibration (simultaneous and sequential upstream-to-downstream)
- [x] Parameter boundary manager for custom search bounds

### Phase 3: Input Data Automation ✅
- [x] Weather data retrieval (NOAA API)
- [x] SWAT weather file generation (.pcp, .tmp, WGEN)
- [x] Soil data processing (SSURGO integration)
- [x] Land cover (NLCD classification)
- [x] DEM processing and watershed delineation
- [x] USGS NWIS observation data import (streamflow and water quality)
- [x] Multi-format observation loader (CSV, Excel, USGS RDB, ADEQ, STORET)

### Phase 4: User Interface ✅
- [x] Visualization dashboard (hydrograph, scatter, duration curves, metrics table)
- [x] Diagnostic visualization (baseflow separation, peak comparison, seasonal bias, rating curves)
- [x] Interactive Plotly charts (time series, multi-variable, scatter)
- [x] Streamlit web app (7 pages) with session persistence
- [x] Interactive parameter selection and boundary editing
- [x] Export to JSON, CSV, HTML, PNG, PDF

### Phase 5: Advanced Calibration ✅
- [x] Diagnostic-guided calibration (baseflow separation, peak analysis, volume balance, FDC metrics)
- [x] Ensemble diagnostic calibration with uncertainty
- [x] Phased calibration (hydrology → sediment → nitrogen → phosphorus)
- [x] Parallel multi-core calibration via pathos
- [x] Multi-constituent WQ calibration (sediment, nitrogen, phosphorus)
- [x] Load calculator for constituent loads
- [x] WQ-specific diagnostic engines

### Phase 6: Distribution & Performance ✅
- [x] SWAT+ to SWAT2012 converter (CLI and API)
- [x] fig.fig routing parser with upstream/downstream traversal
- [x] Partial-basin active subbasin optimization (active_subs.dat)
- [x] Portable SWAT-DG Windows package (embedded Python 3.11, no install needed)
- [x] Intel ifx compiler build (2.4x faster than gfortran)
- [x] GIS integration (Folium maps, shapefile loading)

## Contributing

Contributions are welcome! Please see our contributing guidelines.

## License

Apache 2.0 License - see LICENSE file for details.

## Acknowledgments

This project builds on the SWAT model developed at Texas A&M University.
See https://swat.tamu.edu/ for more information about SWAT.

## References

- Arnold, J.G., et al. (2012). SWAT: Model Use, Calibration, and Validation. ASABE.
- Abbaspour, K.C. (2015). SWAT-CUP: SWAT Calibration and Uncertainty Programs.
- Moriasi, D.N., et al. (2007). Model evaluation guidelines. ASABE, 50(3), 885-900.
