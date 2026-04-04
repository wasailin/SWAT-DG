# SWAT-DG Technical Documentation

**Version 0.5.0** | Python Wrapper & Automation Framework for SWAT2012

[![CI](https://github.com/wasailin/SWAT-DG/actions/workflows/ci.yml/badge.svg)](https://github.com/wasailin/SWAT-DG/actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

---

## 1. Project Overview

SWAT-DG is a comprehensive Python framework that wraps the SWAT2012 (Soil and Water Assessment Tool) Fortran-based hydrological model, providing modern Python APIs for model execution, automated calibration, data automation, GIS-based spatial analysis, and an interactive browser-based GUI. The project bridges the gap between SWAT2012's legacy Fortran codebase and contemporary data science workflows, enabling researchers and engineers to perform end-to-end watershed modeling without leaving the Python ecosystem.

### 1.1 Design Philosophy

The framework is built around four guiding principles: (1) zero cloud dependency, ensuring all data processing stays on the user's local machine; (2) modular architecture, allowing users to install only the components they need; (3) Pythonic interfaces that integrate seamlessly with NumPy, Pandas, and Matplotlib; and (4) progressive disclosure, where the Streamlit GUI covers common workflows while the Python API exposes full control for advanced users.

### 1.2 Key Capabilities

SWAT-DG provides a Python API for running SWAT2012 simulations, parsing all major input and output file formats, and modifying model parameters programmatically. It integrates with the SPOTPY optimization library to support automated calibration using six or more algorithms, including SCE-UA, DREAM, and Latin Hypercube Sampling. Beyond standard optimization, it introduces a diagnostic calibration engine that converges in 5 to 20 model runs by analyzing hydrograph characteristics rather than performing thousands of trial-and-error evaluations. The framework also includes data automation pipelines for US-based watersheds (NOAA weather, SSURGO soils, NLCD land cover, DEM processing), a spatial module for interactive watershed mapping, and a complete SWAT+ to SWAT2012 format conversion toolkit.

---

## 2. Technology Stack

### 2.1 Core Dependencies

| Component | Technology | Version | Purpose |
|-----------|-----------|---------|---------|
| Language | Python | 3.10+ | Core runtime (supports 3.10, 3.11, 3.12, 3.13) |
| Numerical Computing | NumPy | >= 1.20 | Array operations, statistical functions |
| Data Manipulation | Pandas | >= 1.3 | DataFrame-based I/O, time series handling |
| Static Visualization | Matplotlib | >= 3.4 | Hydrographs, scatter plots, dashboards |
| Build System | Setuptools | >= 61.0 | PEP 517 build with pyproject.toml |

### 2.2 Optional Dependencies (Modular Installation)

| Feature Group | Install Command | Libraries |
|--------------|----------------|-----------|
| Calibration | `pip install swat-dg[calibration]` | SPOTPY >= 1.5 |
| GIS / Spatial | `pip install swat-dg[gis]` | GeoPandas >= 0.10, Rasterio >= 1.2, PyProj >= 3.0, Xarray >= 0.19, Folium >= 0.14 |
| Data Automation | `pip install swat-dg[data]` | Requests >= 2.25, OpenPyXL >= 3.0 |
| Web Application | `pip install swat-dg[app]` | Streamlit >= 1.28, Plotly >= 5.18, Folium >= 0.14, streamlit-folium >= 0.15 |
| All Features | `pip install swat-dg[full]` | All of the above |
| Development | `pip install swat-dg[dev]` | pytest, pytest-cov, black, ruff, mypy |

### 2.3 External Dependencies

SWAT-DG requires a compiled SWAT2012 Fortran executable to run simulations. The executable is not bundled with the package; users must provide their own compiled binary (e.g., `swat_64rel.exe` or `rev681_64rel.exe`). The application auto-discovers executables in the project directory and common parent directories.

For data automation pipelines, the framework connects to NOAA Climate Data Online (CDO) API for weather retrieval, USDA SSURGO database for soil properties, and USGS NLCD for land cover classification. These external services are US-focused and require internet connectivity only during data download; all subsequent processing is local.

---

## 3. Architecture

### 3.1 Package Structure

```
swat-dg/
├── src/swat_modern/                 # Main package (71 Python files, ~3.8 MB)
│   ├── __init__.py                  # Public API exports
│   ├── core/                        # Model wrapper and execution engine
│   │   ├── model.py                 # SWATModel - primary wrapper class
│   │   ├── runner.py                # SWATRunner - process management
│   │   ├── config.py                # SWATConfig - file.cio parser
│   │   └── result.py                # SimulationResult container
│   ├── io/                          # Input/output system
│   │   ├── parsers/                 # Output and input file parsers
│   │   │   ├── output_parser.py     # Parses output.rch, .sub, .hru, .rsv, .std
│   │   │   ├── cio_parser.py        # file.cio configuration
│   │   │   ├── bsn_parser.py        # Basin-wide parameters (.bsn)
│   │   │   ├── mgt_parser.py        # Management files (.mgt)
│   │   │   ├── sol_parser.py        # Soil properties (.sol)
│   │   │   ├── fig_parser.py        # Routing topology (fig.fig)
│   │   │   ├── parameter_reader.py  # Reads parameter values from project
│   │   │   └── result_browser.py    # Navigable output hierarchy
│   │   ├── generators/              # Parameter modification engine
│   │   │   └── parameter_modifier.py
│   │   ├── converters/              # SWAT+ to SWAT2012 conversion
│   │   │   ├── swatplus_reader.py   # Reads SWAT+ SQLite databases
│   │   │   ├── parameter_mapper.py  # Cross-version parameter mapping
│   │   │   ├── routing_builder.py   # Routing connectivity graphs
│   │   │   ├── swat2012_writer.py   # SWAT2012 file generation
│   │   │   └── weather_converter.py # Weather format conversion
│   │   ├── observation_loader.py    # Multi-format observation data loader
│   │   ├── nwis_loader.py           # USGS NWIS API integration
│   │   ├── wq_observation_loader.py # Water quality data loading
│   │   └── unit_converter.py        # Unit conversion utilities
│   ├── calibration/                 # Calibration and optimization engine
│   │   ├── calibrator.py            # High-level Calibrator API
│   │   ├── spotpy_setup.py          # SPOTPY-compatible model wrappers
│   │   ├── parameters.py            # 45+ parameter definitions with metadata
│   │   ├── objectives.py            # 8 objective functions (NSE, KGE, etc.)
│   │   ├── boundary_manager.py      # Parameter bound management
│   │   ├── diagnostic_calibrator.py # Diagnostic-guided calibration (5-20 runs)
│   │   ├── sequential.py            # Sequential upstream-to-downstream
│   │   ├── phased_calibrator.py     # Multi-phase calibration strategies
│   │   ├── simulation_optimizer.py  # Direct simulation-based optimization
│   │   ├── diagnostics.py           # Hydrograph analysis engine
│   │   └── load_calculator.py       # Sediment/nutrient load computation
│   ├── data/                        # Data automation pipelines
│   │   ├── weather.py               # NOAA CDO API, SWAT weather file generation
│   │   ├── soil.py                  # SSURGO, USDA texture classification
│   │   ├── dem.py                   # DEM processing, watershed delineation
│   │   └── landcover.py             # NLCD, curve number lookup
│   ├── spatial/                     # GIS and mapping
│   │   ├── shapefile_loader.py      # Shapefile/SQLite layer discovery and loading
│   │   └── map_builder.py           # Interactive Folium map construction
│   ├── visualization/               # Plotting and dashboards
│   │   ├── hydrograph.py            # Time series plots
│   │   ├── scatter.py               # 1:1 scatter plots with metrics
│   │   ├── duration_curve.py        # Flow duration curves
│   │   ├── metrics_table.py         # Formatted performance metrics
│   │   ├── dashboard.py             # CalibrationDashboard (4-panel unified view)
│   │   ├── diagnostics.py           # Baseflow, peak, seasonal, rating curves
│   │   ├── sensitivity.py           # Sensitivity analysis visualization
│   │   └── plotly_charts.py         # Interactive Plotly charts
│   └── app/                         # Streamlit web application
│       ├── main.py                  # Application entry point
│       ├── session_persistence.py   # Session state management
│       ├── calibration_runner.py    # Background calibration executor
│       ├── loading_utils.py         # UI styling and utilities
│       ├── _win32_dialog.py         # Windows native file dialog
│       └── pages/                   # 7-page multi-page app
│           ├── 1_Project_Setup.py   # Project loading and configuration
│           ├── 2_Watershed_Map.py   # Interactive watershed visualization
│           ├── 3_Simulation_Results.py  # Output browsing and plotting
│           ├── 4_Observation_Data.py    # Data import and management
│           ├── 5_Parameter_Editor.py    # Boundary configuration
│           ├── 6_Calibration.py         # Calibration engine interface
│           └── 7_Results.py             # Results viewer and export
├── tests/                           # Test suite (28 files, 350+ tests)
├── examples/                        # 7 Jupyter notebook tutorials
├── docs/                            # Documentation
├── pyproject.toml                   # PEP 517 build configuration
└── .github/workflows/ci.yml        # GitHub Actions CI pipeline
```

### 3.2 Data Flow Architecture

The framework follows a pipeline architecture where data flows through clearly separated stages:

```
┌─────────────────────────────────────────────────────────────────────┐
│                        SWAT Project Files                          │
│              (file.cio, *.sub, *.hru, *.sol, *.mgt, ...)          │
└───────────────────────────────┬─────────────────────────────────────┘
                                │
                    ┌───────────▼───────────┐
                    │      SWATConfig       │  Parses file.cio, extracts
                    │   (core/config.py)    │  simulation period, output
                    └───────────┬───────────┘  settings, file references
                                │
                    ┌───────────▼───────────┐
                    │      SWATModel        │  Loads project, discovers
                    │   (core/model.py)     │  executable, manages I/O
                    └───────────┬───────────┘
                                │
              ┌─────────────────┼─────────────────┐
              │                 │                  │
    ┌─────────▼─────────┐  ┌───▼────┐  ┌──────────▼──────────┐
    │  ParameterModifier │  │ Runner │  │   OutputParser       │
    │  (modify params)   │  │ (exec) │  │   (parse results)   │
    └─────────┬──────────┘  └───┬────┘  └──────────┬──────────┘
              │                 │                   │
              └─────────┬───────┘                   │
                        │                           │
              ┌─────────▼──────────┐    ┌───────────▼───────────┐
              │   Calibrator       │◄───│   ObservationLoader   │
              │  (SPOTPY engine)   │    │   (CSV/Excel/NWIS)    │
              └─────────┬──────────┘    └───────────────────────┘
                        │
              ┌─────────▼──────────┐
              │ CalibrationResult  │
              │ (metrics, params,  │
              │  visualizations)   │
              └────────────────────┘
```

### 3.3 State Management

The application uses no traditional database. All state management is file-based and in-memory: Streamlit's `SessionState` handles application-level persistence across page switches and browser refreshes; SWAT input and output files serve as the persistent data store; Pandas DataFrames provide in-memory data processing; and JSON files are used for exporting calibration results and boundary configurations. A dedicated `session_persistence.py` module serializes critical session state to disk, enabling the application to survive browser refresh events without losing project context, loaded observation data, or calibration results.

---

## 4. Core Modules

### 4.1 Core Model Wrapper (`swat_modern.core`)

The `SWATModel` class is the primary entry point. It wraps a SWAT2012 project directory, providing methods to run simulations, modify parameters, parse outputs, and manage project backups. The `SWATRunner` handles subprocess execution of the Fortran binary with timeout support, process monitoring, and cooperative cancellation via `threading.Event` and file-based signals. The `SWATConfig` class reads `file.cio` to extract simulation period, warmup years, output settings, and file references.

```python
from swat_modern import SWATModel

model = SWATModel("path/to/project", executable="swat2012.exe")
result = model.run(timeout=300)
flow = model.get_output("FLOW_OUTcms", output_type="rch", unit_id=1)
model.modify_parameter("CN2", -0.1, method="multiply")
```

### 4.2 Input/Output System (`swat_modern.io`)

The I/O module is divided into parsers, generators, and converters. The `OutputParser` reads all five SWAT output formats (`output.rch`, `output.sub`, `output.hru`, `output.rsv`, `output.std`) into Pandas DataFrames, handling the fixed-width Fortran formatting and multi-year date indexing. Input file parsers cover `.bsn` (basin parameters), `.mgt` (management practices), `.sol` (soil properties), `.hru` (HRU definitions), `.gw` (groundwater), `.rte` (routing), and `file.cio` (configuration). The `ParameterModifier` applies parameter changes using three methods: `replace` (absolute value), `multiply` (relative scaling), and `add` (additive offset), with physical bounds enforcement that prevents Fortran crashes by clamping values to valid ranges (e.g., CN2 between 0 and 98, ESCO between 0 and 1).

The `ObservationLoader` supports CSV, Excel (XLSX), USGS RDB (tab-delimited), and space-delimited formats with automatic delimiter detection, date column identification, date format parsing (including multi-column Year/Month/Day formats), and pairwise NaN removal. The NWIS loader fetches streamflow data directly from the USGS National Water Information System API.

The converters sub-package provides a complete SWAT+ to SWAT2012 conversion pipeline, reading SWAT+ v61 SQLite databases, mapping parameters through complex lookup chains (e.g., CN2 derived from land use, soil hydrologic group, and lookup tables), building routing connectivity graphs, and generating SWAT2012-compatible text files.

### 4.3 Calibration Engine (`swat_modern.calibration`)

The calibration module offers four distinct calibration approaches:

**Standard Optimization** integrates with SPOTPY to provide access to SCE-UA, DREAM, Monte Carlo, Latin Hypercube Sampling, ROPE, and DE-MCZ algorithms. The `SWATModelSetup` class implements the SPOTPY-compatible interface, translating parameter samples into SWAT model runs and returning objective function values. Supports 45+ pre-defined calibration parameters organized into six groups (Hydrology, Groundwater, Soil, Routing, Sediment, Nutrients) with recommended bounds from the literature.

**Diagnostic Calibration** (`DiagnosticCalibrator`) is the framework's signature innovation. Instead of running thousands of random parameter combinations, it analyzes the hydrograph to identify which physical processes are causing simulation errors. It performs volume balance analysis (diagnosing ESCO and CN2 issues), baseflow separation (identifying groundwater parameter needs), peak detection and comparison (for routing parameters), and flow duration curve decomposition. This approach converges in 5 to 20 model runs rather than the 5,000+ typically required by optimization algorithms.

**Sequential Calibration** implements an upstream-to-downstream phased approach: tributary gauges are calibrated first, then main-stem gauges inherit upstream parameters. This reduces parameter interaction effects and is essential for large watersheds with multiple observation points.

**Multi-Site Simultaneous Calibration** optimizes parameters against multiple observation gauges simultaneously using weighted composite objective functions. The `MultiSiteSetup` and `SubbasinGroupSetup` classes handle the mapping between parameter modifications and spatially distributed observations.

Eight objective functions are implemented: NSE (Nash-Sutcliffe Efficiency), KGE (Kling-Gupta Efficiency), PBIAS (Percent Bias), RMSE (Root Mean Square Error), MAE (Mean Absolute Error), R-squared, RSR (RMSE-Standard Deviation Ratio), and Log-NSE (for low-flow emphasis).

### 4.4 Data Automation (`swat_modern.data`)

The data module provides US-focused automation pipelines. The `WeatherDataFetcher` integrates with the NOAA Climate Data Online API to discover nearby weather stations, retrieve daily records (precipitation, temperature, wind, solar radiation, humidity), and generate SWAT-ready input files (`.pcp`, `.tmp`, `.wnd`, `.hmd`, `.slr`) along with WGEN stochastic weather generator parameters. The `SoilDataFetcher` connects to the SSURGO database for soil property lookup, applies USDA texture classification, and generates multi-layer `.sol` files. The `LandCoverProcessor` handles NLCD land cover classification, maps to SWAT land use codes, and performs curve number lookups. The `DEMProcessor` implements sink filling, D8 flow direction computation, flow accumulation analysis, watershed delineation from outlet points, and stream network extraction.

### 4.5 Spatial Module (`swat_modern.spatial`)

The `ShapefileLoader` discovers and loads vector spatial data from Shapefiles (`.shp`) and SWAT+ SQLite databases, supporting automatic detection in standard SWAT project directory structures. The `WatershedMapBuilder` constructs interactive Folium maps with subbasin polygons, stream networks, watershed boundaries, reservoir locations, and result heatmaps. Maps support layer toggling via Folium's built-in `LayerControl`, click-based feature selection, and CRS reprojection to WGS84.

### 4.6 Visualization (`swat_modern.visualization`)

The visualization module provides both static (Matplotlib) and interactive (Plotly) chart generation. The `CalibrationDashboard` produces a unified four-panel view combining hydrograph, scatter plot, flow duration curve, and metrics table. Diagnostic visualizations include baseflow separation plots, peak comparison charts, seasonal bias analysis, and rating curves. All visualizations can be exported to PNG, PDF, or self-contained HTML reports.

### 4.7 Streamlit Web Application (`swat_modern.app`)

The application is a seven-page Streamlit multi-page app providing a complete calibration workflow through a browser-based GUI. It runs entirely locally with no cloud dependencies. Key technical features include session persistence across browser refreshes, background calibration execution with real-time progress monitoring, cooperative cancellation support, native Windows file dialog integration, interactive map-based subbasin selection, and multi-format data export (JSON, CSV, HTML, PNG).

---

## 5. API Reference

### 5.1 SWATModel

```python
class SWATModel:
    def __init__(self, project_dir: str, executable: str = None)
    def run(self, timeout: int = None) -> SimulationResult
    def get_output(self, variable: str, output_type: str, unit_id: int) -> pd.DataFrame
    def modify_parameter(self, name: str, value: float, method: str = "replace",
                         file_type: str = None, unit_id: int = None)
    def backup(self, backup_dir=None, file_types: list = None) -> Path
    def restore(self, backup_dir, file_types: list = None)
```

### 5.2 Calibrator

```python
class Calibrator:
    def __init__(self, model: SWATModel, observed_data, parameters: list,
                 output_variable: str, reach_id: int = 1,
                 objective: str = "nse", warmup_years: int = 1)
    def auto_calibrate(self, n_iterations: int = 5000, algorithm: str = "sceua",
                       parallel: bool = False, n_cores: int = None) -> CalibrationResult
    def sensitivity_analysis(self, method: str = "fast", n_samples: int = 1000,
                             parallel: bool = False, n_cores: int = None) -> SensitivityResult
    def diagnostic_calibrate(self, n_iterations: int = 15,
                             algorithm: str = "sceua") -> CalibrationResult
    def ensemble_diagnostic_calibrate(self, n_ensemble: int = 4,
                                      n_iterations: int = 15) -> CalibrationResult
    def phased_calibrate(self, phases=None) -> PhasedCalibrationResult
```

### 5.3 CalibrationResult

```python
class CalibrationResult:
    def print_summary(self)
    def plot_comparison(self)
    def save_best_parameters(self, path: str)
    @property
    def metrics(self) -> dict    # {nse, kge, pbias, rmse, rsr, ...}
    @property
    def best_params(self) -> dict
```

### 5.4 Objective Functions

```python
from swat_modern.calibration.objectives import nse, kge, pbias, rmse, mae, r_squared, rsr, log_nse, evaluate_model

score = nse(observed, simulated)          # -inf to 1.0 (perfect)
score = kge(observed, simulated)          # -inf to 1.0 (perfect)
score = pbias(observed, simulated)        # % bias (0 = perfect)
metrics = evaluate_model(observed, simulated)  # dict of all metrics
```

### 5.5 Data Automation

```python
from swat_modern.data import WeatherDataFetcher, SoilDataFetcher, DEMProcessor

# Weather
weather = WeatherDataFetcher.from_csv("data.csv", station_name="Station1",
                                       latitude=30.5, longitude=-96.5)
files = weather.to_swat_files("output/")

# Soil
soil = SoilDataFetcher.create_default_profile(texture="loam", depth_cm=150)
soil.to_swat_file("000010001.sol")

# DEM Processing
dem = DEMProcessor.from_file("elevation.tif")
dem.fill_sinks()
dem.compute_flow_direction()
watershed = dem.delineate_watershed(outlet=(100, 200))
```

---

## 6. Calibration Parameters

The framework defines 45+ calibration parameters organized into six groups, each with recommended bounds derived from the SWAT calibration literature (Abbaspour 2015, Arnold et al. 2012):

### Hydrology Parameters

| Parameter | Description | Method | Default Range | File |
|-----------|------------|--------|---------------|------|
| CN2 | SCS curve number (moisture condition II) | multiply | -0.25 to 0.25 | .mgt |
| ESCO | Soil evaporation compensation factor | replace | 0.01 to 1.0 | .bsn/.hru |
| EPCO | Plant evaporation compensation factor | replace | 0.01 to 1.0 | .bsn/.hru |
| SURLAG | Surface runoff lag coefficient | replace | 0.05 to 24.0 | .bsn |
| OV_N | Manning's "n" for overland flow | replace | 0.01 to 0.50 | .hru |
| CANMX | Maximum canopy storage (mm) | replace | 0.0 to 100.0 | .hru |

### Groundwater Parameters

| Parameter | Description | Method | Default Range | File |
|-----------|------------|--------|---------------|------|
| GW_DELAY | Groundwater delay time (days) | replace | 0.0 to 500.0 | .gw |
| ALPHA_BF | Baseflow recession constant | replace | 0.0 to 1.0 | .gw |
| ALPHA_BF_D | Baseflow alpha factor for deep aquifer (1/days) | replace | 0.0 to 1.0 | .gw |
| GWQMN | Threshold depth for return flow (mm) | replace | 0.0 to 5000.0 | .gw |
| REVAPMN | Threshold depth for revap (mm) | replace | 0.0 to 500.0 | .gw |
| GW_REVAP | Groundwater revap coefficient | replace | 0.02 to 0.20 | .gw |
| RCHRG_DP | Deep aquifer percolation fraction | replace | 0.0 to 1.0 | .gw |

### Soil, Routing, Sediment, Nutrients

Soil parameters include SOL_AWC, SOL_K, and SOL_BD; routing covers CH_N2 and CH_K2; sediment includes USLE_P, USLE_K, SPCON, SPEXP, CH_COV1, and CH_COV2; and nutrient parameters include NPERCO, PPERCO, CMN, PSP, and others. Each parameter is stored with its file type, modification method, physical bounds, and descriptive metadata.

---

## 7. Testing and Quality Assurance

The test suite contains 28 test files with over 350 test cases covering unit tests (parameter definitions, objective functions, file parsers), integration tests (full calibration workflows), and fixture-based tests using real SWAT project structures. The project uses pytest as its testing framework with pytest-cov for coverage reporting. Code quality is maintained through black (formatting, line length 88), ruff (linting with E, F, W, I, N, UP rule sets), and mypy (type checking targeting Python 3.10). A GitHub Actions CI pipeline runs the full test suite across Python 3.10, 3.11, 3.12, and 3.13 on every push and pull request.

---

## 8. Build and Deployment

### 8.1 Installation

```bash
# From PyPI (basic)
pip install swat-dg

# From source (development)
git clone https://github.com/wasailin/SWAT-DG.git
cd swat-dg
pip install -e ".[full,dev]"
```

### 8.2 Running the Application

```bash
# Launch the Streamlit web app
streamlit run src/swat_modern/app/main.py

# Opens browser at http://localhost:8501
```

### 8.3 Running Tests

```bash
pytest                           # Run all tests
pytest --cov=swat_modern         # With coverage report
pytest tests/test_calibration.py # Specific module
```

---

## 9. Development Roadmap

### Completed Phases

Phase 1 (Python Wrapper Foundation) delivered the basic model wrapper, output parsing for all five SWAT output formats, input file parsing for six file types, parameter modification with physical bounds enforcement, and project backup/restore. Phase 2 (Calibration Automation) added SPOTPY integration with eight algorithms, 45+ parameter definitions, eight objective functions, sensitivity analysis via FAST and Sobol methods, and multi-site calibration support. Phase 3 (Input Data Automation) delivered weather data retrieval from NOAA, SWAT weather file generation, soil processing via SSURGO, USDA texture classification, NLCD land cover processing, and DEM processing with watershed delineation. Phase 4 (User Interface) added the visualization dashboard, interactive Plotly charts, the seven-page Streamlit web app, session persistence, and multi-format export capabilities.

### Future Development

Planned features include native SWAT+ support (beyond conversion), real-time visualization during calibration runs, parallel calibration across HRU groups, advanced ensemble methods for uncertainty quantification, and AI-assisted parameter boundary suggestion using machine learning models trained on successful calibrations from the literature.

---

## 10. References

- Arnold, J.G., Moriasi, D.N., Gassman, P.W., et al. (2012). SWAT: Model Use, Calibration, and Validation. Transactions of the ASABE, 55(4), 1491-1508.
- Abbaspour, K.C. (2015). SWAT-CUP: SWAT Calibration and Uncertainty Programs. Eawag: Swiss Federal Institute of Aquatic Science and Technology.
- Moriasi, D.N., Arnold, J.G., Van Liew, M.W., et al. (2007). Model Evaluation Guidelines for Systematic Quantification of Accuracy in Watershed Simulations. Transactions of the ASABE, 50(3), 885-900.
- Nash, J.E. & Sutcliffe, J.V. (1970). River Flow Forecasting Through Conceptual Models. Journal of Hydrology, 10(3), 282-290.
- Gupta, H.V., Kling, H., Yilmaz, K.K., & Martinez, G.F. (2009). Decomposition of the Mean Squared Error and NSE Performance Criteria. Journal of Hydrology, 377(1-2), 80-91.

---

## License

Apache 2.0 License. See LICENSE file for details.

This project builds on the SWAT model developed at Texas A&M University. See https://swat.tamu.edu/ for more information about SWAT.
