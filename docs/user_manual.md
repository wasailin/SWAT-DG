# SWAT-DG User Manual

**Version 0.5.0** | Last Updated: 2026-04-06

A complete guide to the SWAT-DG application for SWAT model calibration, visualization, and analysis. Covers both the Streamlit web application and the Python API.

---

## Table of Contents

1. [Getting Started](#1-getting-started)
2. [Installation](#2-installation)
3. [Home Dashboard](#3-home-dashboard)
4. [Page 1: Project Setup](#4-page-1-project-setup)
5. [Page 2: Watershed Map](#5-page-2-watershed-map)
6. [Page 3: Simulation Results](#6-page-3-simulation-results)
7. [Page 4: Observation Data](#7-page-4-observation-data)
8. [Page 5: Parameter Editor](#8-page-5-parameter-editor)
9. [Page 6: Calibration](#9-page-6-calibration)
10. [Page 7: Results](#10-page-7-results)
11. [Python API Reference](#11-python-api-reference)
12. [Data Automation Pipeline](#12-data-automation-pipeline)
13. [GIS / Spatial Tools](#13-gis--spatial-tools)
14. [SWAT+ to SWAT2012 Converter](#14-swat-to-swat2012-converter)
15. [Session Persistence](#15-session-persistence)
16. [Calibration Parameters Reference](#16-calibration-parameters-reference)
17. [Supported File Formats](#17-supported-file-formats)
18. [Export & Download Options](#18-export--download-options)
19. [Troubleshooting](#19-troubleshooting)
20. [Performance Rating Guide](#20-performance-rating-guide)

---

## 1. Getting Started

### Key Features

- **Diagnostic-guided calibration**: Analyzes hydrograph deficiencies (volume bias, baseflow partition, peak timing) and converges in 5-20 model runs instead of thousands. Available as single-site or ensemble (multi-start parallel) mode.
- **Parallel calibration**: Distributes SWAT runs across multiple CPU cores for standard algorithms (SCE-UA, Monte Carlo, LHS), reducing wall-clock time proportionally.
- **Phased water quality calibration**: Automatically sequences Flow, Sediment, Nitrogen, and Phosphorus calibration phases.
- **Partial-basin simulation**: Simulates only subbasins upstream of the calibration target, with speedups up to 15x for interior gauges.
- **Python API**: Full programmatic access to all functionality -- run simulations, modify parameters, calibrate, and visualize from scripts and notebooks.

### What You Need Before Starting

- A **SWAT2012 project folder** (the TxtInOut directory containing `file.cio` and all input files)
- A **SWAT executable** -- SWAT2012 Rev. 681 or above (e.g., `swat_64rel.exe`). A custom-compiled executable optimized for calibration is available on the [Releases](https://github.com/wasailin/SWAT-DG/releases) page, but any SWAT2012 executable downloaded from the [official SWAT website](https://swat.tamu.edu/) also works. The app will attempt to auto-detect it in your project folder.
- **Observation data** (streamflow or water quality measurements in CSV or Excel format) for calibration

### Recommended Workflow

Follow the pages in order for the best experience:

1. **Project Setup** -- Load your SWAT project folder
2. **Watershed Map** -- View your watershed spatially
3. **Simulation Results** -- Browse existing model outputs
4. **Observation Data** -- Import observed streamflow or water quality data
5. **Parameter Editor** -- Review and customize calibration parameter boundaries
6. **Calibration** -- Select parameters, choose an algorithm, and run calibration
7. **Results** -- View performance metrics, plots, and export calibrated parameters

---

## 2. Installation

### System Requirements

- **Python**: 3.10 or later (3.11 recommended)
- **Operating Systems**: Windows, Linux, macOS
- **SWAT Executable**: A compiled SWAT2012 Rev. 681+ executable (e.g., `swat_64rel.exe` on Windows). Available from the [Releases](https://github.com/wasailin/SWAT-DG/releases) page or the [official SWAT website](https://swat.tamu.edu/).
- **Disk Space**: Varies by project size; SWAT TxtInOut directories can range from a few MB to several GB

### Core Install

Install the base package with minimal dependencies (numpy, pandas, matplotlib):

```bash
pip install swat-dg
```

### Optional Dependency Groups

SWAT-DG uses optional dependency groups to keep the base install lightweight. Install only what you need:

```bash
# Calibration support (SPOTPY + pathos for parallel)
pip install "swat-dg[calibration]"

# GIS / spatial tools (geopandas, rasterio, pyproj, folium)
pip install "swat-dg[gis]"

# Data fetching (requests, openpyxl for Excel files)
pip install "swat-dg[data]"

# Streamlit web app (streamlit, plotly, folium)
pip install "swat-dg[app]"

# Everything (all optional dependencies)
pip install "swat-dg[full]"

# Development tools (pytest, black, ruff, mypy)
pip install "swat-dg[dev]"
```

| Group | Packages | Purpose |
|-------|----------|---------|
| `calibration` | spotpy, pathos | SPOTPY optimization algorithms, parallel calibration |
| `gis` | geopandas, rasterio, pyproj, xarray, folium | Shapefile loading, DEM processing, interactive maps |
| `data` | requests, openpyxl | NOAA/USGS data fetching, Excel file support |
| `app` | streamlit, plotly, folium, streamlit-folium | Streamlit web application |
| `full` | All of the above plus scipy, shapely | Complete installation |
| `dev` | pytest, pytest-cov, black, ruff, mypy | Testing and code quality |

### Installing from Source

```bash
git clone https://github.com/wasailin/SWAT-DG.git
cd SWAT-DG
pip install -e ".[full]"
```

The `-e` flag installs in editable mode so changes to the source are immediately reflected.

### Portable Distribution (Windows)

A self-contained Windows ZIP distribution is available from [GitHub Releases](https://github.com/wasailin/SWAT-DG/releases). It includes an embedded Python 3.11 environment with all dependencies pre-installed. No separate Python installation is needed.

1. Download the ZIP file from the latest release
2. Extract to any folder
3. Run `start_app.bat` to launch the Streamlit web app

### Launching the Streamlit App

```bash
streamlit run src/swat_modern/app/main.py
```

The app opens in your default browser at `http://localhost:8501`. All data stays on your machine -- nothing is uploaded to the cloud.

---

## 3. Home Dashboard

The home page provides an overview of your current session and quick navigation to all pages.

### Sidebar

The sidebar appears on every page and shows:

- **Project Status** -- Green badges for each completed step:
  - Project loaded
  - Shapefiles detected
  - Observation data loaded
  - Boundaries configured
  - Calibration results available (with NSE value)
- **Quick Links** -- SWAT documentation and GitHub repository
- **Footer** -- Confirms that all processing runs locally

### Main Area

- **Getting Started** -- Six numbered steps linking to each page
- **Session Status** -- Seven metric tiles showing the state of your workflow (Project, Map, Results, Observations, Boundaries, Calibration, Parameters)
- **Tips for Better Calibration** -- Expandable section with guidance on parameter selection, algorithm choice, iteration counts, and performance targets based on Moriasi et al. (2007)

### Session Auto-Restore

When you refresh the browser or navigate away and return, the app automatically restores your session state. This includes:

- The loaded project path and SWAT executable
- Observation data and calibration targets
- Calibration results and sensitivity analysis results
- Parameter boundaries

The `SWATModel` object is reconstructed automatically from the persisted project path and executable path. See [Session Persistence](#15-session-persistence) for technical details.

---

## 4. Page 1: Project Setup

This page loads your SWAT project and detects the executable.

### Loading a Project

1. **Enter the project path** in the text field, or click **Browse...** to open a folder picker
   - The path should point to the TxtInOut folder containing `file.cio`
2. Click **Load Project**

The app validates the folder and runs through four steps:
- Validating project folder (checks for `file.cio`)
- Finding SWAT executable (searches common names and locations)
- Reading project configuration (simulation period, output settings)
- Scanning for shapefiles (looks for spatial data nearby)

### Project Information

Once loaded, the page displays:

**Left column -- Project Details:**
- Full path
- Project folder name
- File counts by type (`.sub`, `.hru`, `.sol`, `.mgt`)

**Right column -- Configuration:**
- Simulation start and end year
- Warmup years
- Whether shapefiles were found

### Viewing Project Files

Expand **View Project Files** to see all files grouped by extension. Each file has an **Open** button that launches it in your default text editor.

Below the file list, a **file preview** dropdown lets you select any file and view its contents (first 200 lines) directly in the browser.

### SWAT Executable

The app searches for common executable names in the project folder and its parent directory:
- `swat_681_calib_ifx.exe`, `swat_692_calib_ifx.exe`, `swat_64calib_ifx.exe`, `swat_64calib.exe`
- `swat2012.exe`, `swat.exe`, `swat_64rel.exe`, `SWAT_Rev681.exe`

It also checks the `SWAT_EXE` environment variable.

If found, a success message appears. If not, a text field and Browse button let you specify the path manually.

### Sidebar

- **Exit Project** button -- Clears the loaded project and resets the session

---

## 5. Page 2: Watershed Map

Displays your watershed on an interactive map using shapefiles.

### Spatial Data Sources

The app auto-discovers shapefiles for subbasins, streams, boundary, and reservoirs. Status badges show which layers were found.

If auto-discovery fails, expand **Manual Shapefile Paths** to specify:
- A **Shapes directory** containing all shapefiles
- Individual paths for **Subbasins**, **Streams**, **Boundary**, and **Reservoirs** shapefiles

Each field has a Browse button for file selection.

### Interactive Map

The map is rendered using Folium with the following features:
- **Pan and zoom** with mouse or scroll wheel
- **Layer Control** (top-right corner) -- Toggle individual layers on/off
- **Auto-fit** -- The map automatically zooms to show all loaded data
- Supported layers: Boundary (outline), Subbasins (filled polygons), Streams (blue lines), Reservoirs (markers)

### Feature Details

Below the map:
- **Subbasin Summary** (expandable) -- Total subbasins, total area (km2), coordinate reference system, and a full attribute table
- **Stream Network Summary** (expandable) -- Stream segment count and attribute table (first 20 rows)

---

## 6. Page 3: Simulation Results

Browse and visualize SWAT model output files.

### Available Output Files

Five status badges show which output files exist:
- `output.rch` (Reach)
- `output.sub` (Subbasin)
- `output.hru` (HRU)
- `output.rsv` (Reservoir)
- `output.std` (Summary)

If no outputs exist, a warning prompts you to run a SWAT simulation first.

### Selecting Data to View

Three dropdown menus in a row:

1. **Output Type** -- Reach, Subbasin, HRU, or Reservoir
2. **Variable** -- Categorized list (Hydrology, Nutrients, Sediment, Other) with priority variables shown first
3. **Unit ID** -- The specific reach, subbasin, or HRU number to display

### Time Series Plot

An interactive Plotly chart shows the selected variable over time with a range slider for zooming. Below the chart, five summary statistics are displayed: Mean, Std Dev, Min, Max, and Count.

### Compare Across Units

Expand this section to view multiple units side-by-side:

- **If shapefiles are loaded** -- An interactive map appears where you can right-click subbasins to select/deselect them for comparison. Selected subbasins turn green. A multi-select widget below the map syncs with your map selections.
- **If no shapefiles** -- A standard multi-select dropdown lets you choose units to compare.

A Plotly chart shows one line per selected unit.

### Spatial Summary

- **Aggregation dropdown** -- Choose mean, sum, max, min, or std
- **Bar chart** -- Shows the aggregated value for each unit
- **Spatial heatmap** (if shapefiles loaded) -- A Folium map with subbasins colored by the aggregated value, with a colorbar legend
- **Data table** (expandable) -- Full spatial summary data

### Detailed Statistics

An expandable section with comprehensive statistics: Mean, Median, Std Dev, Min, Max, Quantiles, Count, and NaN percentage.

---

## 7. Page 4: Observation Data

Load observed measurements (streamflow or water quality) for comparison and calibration.

### Loading Data

Four tabs provide different data sources:

#### Tab 1: Upload File
Drag and drop or browse for a file. Supported formats: CSV, Excel (`.xlsx`, `.xls`), tab/space-delimited (`.txt`, `.tsv`), USGS RDB (`.rdb`), and generic data files (`.dat`).

#### Tab 2: File Path
Type or browse to a file on your local disk. The app auto-detects the delimiter (comma, tab, space, or semicolon) and shows it before loading.

#### Tab 3: USGS NWIS
Fetch data directly from the USGS National Water Information System:
- Enter a **USGS Site Number** (e.g., `07196500`)
- Select a **Parameter** from the dropdown (default: Discharge in cubic feet per second)
- Set **Start Date** and **End Date**
- Click **Fetch USGS Data**

The app connects to the NWIS API and downloads the data automatically.

#### Tab 4: WQ File (Concentration)
Load water quality concentration data (mg/L) from specialized formats:
- Upload or specify a file path
- Select the **format**: Auto-detect, Water Quality Portal (WQP), or Generic CSV
- If the file contains multiple stations, a dropdown lets you select one
- Click **Load WQ Data** to parse the file

A success message shows the number of records and available constituents (Total Nitrogen, Total Phosphorus, TSS, NO3, NH4, Organic N, Ortho-P, TKN, Suspended Sediment Discharge) with sample counts for each.

### Configuring Columns

After loading, configure how the data maps to your model:

**Left column:**
- **Date column** -- Select which column contains dates (auto-detected)
- **Date format** -- Auto-detect or specify manually (`%Y-%m-%d`, `%m/%d/%Y`, etc.)

**Right column:**
- **Observed value column** -- Select the numeric column with measurements (auto-detected)
- **Units** -- Select from: m3/s, cfs, mm/day, mg/L, kg/day, ug/L, tons/day, ft3/s, deg C

**CFS to CMS Conversion:** If units are set to `cfs`, a warning appears explaining that SWAT outputs flow in cubic meters per second. A checkbox (checked by default) converts by multiplying by 0.0283168.

### Calibration Target

- **Output type** -- Choose rch (Reach), sub (Subbasin), or hru (HRU)
- **Subbasin/HRU ID** -- The unit number where the gauge is located
- **SWAT output variable** -- The variable to calibrate against. Options vary by output type:
  - Reach: FLOW_OUTcms, SED_OUTtons, ORGN_OUTkg, ORGP_OUTkg, NO3_OUTkg, MINP_OUTkg, NH4_OUTkg, SEDCONCmg_L, TOT_Nkg, TOT_Pkg
  - Subbasin: WYLDmm, SYLDt_ha, ORGNkg_ha, ORGPkg_ha, NSURQkg_ha, SOLPkg_ha, SEDPkg_ha
  - HRU: WYLDmm, SYLDt_ha, ORGNkg_ha, ORGPkg_ha, NSURQkg_ha, SOLPkg_ha

### Upstream Subbasins (Reach Output Only)

For reach output, an expandable section lets you specify upstream subbasins for accumulated flow computation. The app auto-detects upstream subbasins from GIS shapefiles or `fig.fig`. You can also enter them manually as a comma-separated list.

A reference table (expandable) shows all subbasin areas read from `.sub` files.

### WQ Flow Pairing (Water Quality Only)

When calibrating water quality variables, concentrations (mg/L) must be paired with flow to compute loads. Choose either:
- **Use current simulated streamflow** from `output.rch`
- **Upload observed streamflow** from a separate file

The app uses a load calculator to convert concentrations to loads (kg/day or tons/day) and displays the number of paired observations.

### Process & Validate

Click **Process and Validate Data** to finalize. The app:
- Parses dates and values
- Applies unit conversions
- Detects potential data quality issues (monotonic row indices, scale mismatches)
- Filters to the calibration period
- Stores the processed data for calibration

Warnings appear if fewer than 10 observations fall within the selected period, or if the observed data scale differs significantly from simulated values.

---

## 8. Page 5: Parameter Editor

Review current model parameter values and customize calibration boundaries.

### Current Project Parameters

Click **Refresh Parameters from Project** to read current values from your SWAT input files. Three metrics show the total parameters available, how many have current values, and how many were not found in the project files.

Expand **View Current Parameter Values** to see a table with each parameter's name, group, description, current value (or range for spatially-varying parameters), default min/max bounds, modification method, and units.

### Calibration Boundaries

An editable table lets you customize which parameters to calibrate and their bounds:

| Column | Editable | Description |
|--------|----------|-------------|
| Enable | Yes (checkbox) | Toggle parameter on/off for calibration |
| Parameter | No | Parameter name |
| Group | No | Category (Hydrology, Groundwater, etc.) |
| Description | No | What the parameter controls |
| Current Value | No | Value read from project files |
| Default Min/Max | No | Standard recommended bounds |
| Custom Min | Yes | Override the minimum bound |
| Custom Max | Yes | Override the maximum bound |

### Sidebar: Quick Selection

The sidebar provides shortcuts:

- **Filter by group** -- Multi-select to show only specific parameter categories
- **Batch operations** -- Select a group and click Enable Group or Disable Group
- **Quick selection presets:**
  - **Recommended (4)** -- The four most commonly calibrated parameters
  - **Hydrology Focus (6)** -- Six key hydrology parameters
  - **Select All** / **Clear All**

### Save & Load Boundaries

**Save:**
- **Download Boundaries (JSON)** -- Downloads `calibration_boundaries.json` to your computer
- **Save to Project Folder** -- Saves the JSON file directly into your SWAT project folder

**Load:**
- **Upload boundaries JSON** -- Upload a previously saved configuration
- **Load from Project Folder** -- Loads from the project folder (button only appears if the file exists)

### Apply to Calibration

Click **Apply Boundaries to Calibration** to lock in your selections. The app confirms how many parameters are enabled and directs you to the Calibration page.

An expandable **View Effective Bounds** section shows the final min/max for each enabled parameter, indicating where custom overrides differ from defaults.

---

## 9. Page 6: Calibration

Configure and run automatic model calibration.

### Step 1: Parameter Selection

If you have not set boundaries on the Parameter Editor page, this section lets you select parameters directly.

**Quick selection buttons** (toggle-style, multiple can be active):
- Recommended (4)
- Hydrology Focus
- Include Snow
- Sediment Focus
- Nitrogen Focus
- Phosphorus Focus
- Clear All

Below the buttons, parameters are organized into category expanders (Hydrology, Groundwater, Soil, Routing, Snow, Sediment, Nitrogen, Phosphorus). Each parameter row shows:
- A **checkbox** to enable/disable it
- Its **description**
- Its calibration **range** (min to max)
- Its modification **method** (multiply or replace)

An info bar at the top shows the total count and names of enabled parameters.

**Water quality mode:** When calibrating a water quality variable, streamflow parameters are locked by default. An advanced checkbox allows unlocking them if needed.

### Step 2: Calibration Mode

Choose one of five modes (horizontal radio buttons):

| Mode | Description |
|------|-------------|
| **Single-site** | Calibrate against one observation gauge |
| **Simultaneous Multi-site** | Calibrate against multiple gauges with weighted objectives |
| **Sequential (Upstream-to-Downstream)** | Calibrate reaches in hydrologic order, locking parameters at each step |
| **Diagnostic Sequential** | Like Sequential, but uses 5-20 diagnostic runs per step instead of thousands |
| **Multi-Constituent Phased** | Sequential phase calibration: Flow, then Sediment, then Nitrogen, then Phosphorus. Each phase locks its best parameters before the next phase begins. |

The **Multi-Constituent Phased** mode requires both streamflow and water quality observation data. After the streamflow phase completes and locks its parameters, the sediment phase calibrates sediment parameters on top of the locked hydrology, and so on for nitrogen and phosphorus. Phases without corresponding observation data are automatically skipped.

### Step 3: Output Variable

Select the SWAT output variable to calibrate against:
- Streamflow: FLOW_OUTcms
- Sediment: SED_OUTtons
- Nutrients: TOT_Nkg, TOT_Pkg, ORGN_OUTkg, NO3_OUTkg, NH4_OUTkg, ORGP_OUTkg, MINP_OUTkg

For water quality variables, an info box recommends calibrating in order: Flow first, then Sediment, then Nitrogen, then Phosphorus.

### Step 4: Observation Data

#### Single-Site Mode
- Enter the **Subbasin ID** where the gauge is located
- **Upload** a streamflow or WQ observation file (CSV, Excel, or text)
- The app auto-detects date and value columns
- If multiple numeric columns exist, a dropdown lets you choose the calibration column
- Data quality checks warn about potential issues (row indices, unit mismatches)

**For water quality:** A full WQ upload interface appears with format selection, station detection, and constituent selection. Available WQ constituents include Total Nitrogen (TN), Total Phosphorus (TP), Total Suspended Solids (TSS), NO3, NH4, Organic N, Ortho-P, TKN, and Suspended Sediment Discharge (tons/day). For concentration-based constituents, you can choose the flow source for load calculation -- either SWAT simulated flow from `output.rch` or an uploaded observed streamflow file. WQ processing is deferred until calibration starts, and the app automatically calculates loads from concentrations and flow using `load = concentration * flow * 0.0864`. For Suspended Sediment Discharge, a "Direct Load" path is available that requires no flow pairing -- observations in tons/day are compared directly against SWAT `SED_OUTtons`.

**Fallback:** If no file is uploaded here, the app uses observation data loaded on the Observation Data page.

**Custom calibration period:** Check the box to restrict calibration to a date range within your observation data. Date pickers constrain to valid dates. A warning appears if fewer than 10 observations fall within the range.

#### Multi-Site Modes
- Set the **number of observation sites** (2 to 10)
- For each site, configure:
  - **Subbasin ID** -- Where the gauge is located
  - **Weight** -- Slider from 0.1 to 2.0 (default 1.0) for the objective function
  - **Observation file** -- Upload per-site streamflow or WQ data
  - **Calibration column** -- Select if multiple numeric columns exist

### Step 5: SWAT Executable

Enter or browse for the SWAT executable path. If one was already detected during Project Setup, it appears as the default. If left blank, the app searches the project folder automatically.

### Step 6: Calibration Settings

Three columns of settings:

#### Algorithm Selection
| Algorithm | Description |
|-----------|-------------|
| **SCE-UA** (Recommended) | Shuffled Complex Evolution -- robust global optimization |
| **DREAM** (Bayesian) | Differential Evolution Adaptive Metropolis -- includes uncertainty |
| **Monte Carlo** | Random sampling across parameter space |
| **Latin Hypercube** | Stratified random sampling for better coverage |
| **Diagnostic-Guided** | Analyzes hydrograph patterns, converges in 5-20 runs |
| **Diagnostic Ensemble** | Parallel multi-start diagnostic across CPU cores |

**For standard algorithms (SCE-UA, DREAM, MC, LHS):**
- **Number of Iterations** slider -- 2 to 50,000 (default 1,000). More iterations give better results but take longer.

**For diagnostic algorithms (Diagnostic-Guided, Diagnostic Ensemble):**
- **Max SWAT Runs** slider -- 5 to 50 (default 15)
- **KGE Target** slider -- 0.30 to 0.95 (default 0.70). Calibration stops when reached.
- **PBIAS Target** slider -- 5% to 25% (default 10%). Calibration stops when absolute PBIAS drops below this.
- **Ensemble workers** slider (ensemble only) -- Number of CPU cores to use

#### Objective Function
| Function | Best For |
|----------|----------|
| **NSE** (Nash-Sutcliffe) | General streamflow calibration (most common) |
| **KGE** (Kling-Gupta) | Newer metric, decomposes into correlation, variability, and bias |
| **Log-NSE** | Emphasizes low flows |

#### Calibration Timestep
- **Daily** or **Monthly** -- Must match observation data frequency
- Auto-detected from uploaded observation data (shown as a caption)

**Warmup years** -- Number of initial simulation years to exclude from statistics (0 to 5, default 1)

### Step 7: Simulation Period

Expandable section showing the current simulation period from `file.cio` and available weather data range.

Check **Use custom simulation period** to override:
- **Start year** and **End year** number inputs
- Constrained by available weather data
- An info message confirms the adjusted period

### Step 8: Optimization Settings (Speed)

Expandable section with performance options:

- **Enable partial-basin simulation** (default: on) -- Only simulates subbasins upstream of the calibration target. Can significantly reduce runtime for interior gauges.
- **Enable parallel processing** (default: off) -- Distributes SWAT runs across CPU cores. A number input lets you choose how many cores to use (leaving some free keeps your machine responsive).

### Step 9: Upstream Subbasin Detection

Expandable advanced section:

- **QSWAT Shapes directory** -- Path to the folder containing river shapefiles (`rivs1.shp` or `riv1.shp`). The app validates whether the shapefile exists.
- **Override upstream subbasins** -- Manually enter a comma-separated list of subbasin IDs
- **Detect upstream subbasins** button -- Runs auto-detection using GIS topology (preferred) or `fig.fig` as a fallback

### Step 10: Runtime Estimate

A caption shows the estimated runtime based on algorithm, iterations, and number of steps (for sequential modes). Formatted as seconds, minutes, or hours.

### Step 11: Sensitivity Analysis (Optional)

Expandable section for parameter sensitivity analysis:

- **Method** -- FAST (recommended) or Sobol (approximate, can use fewer samples)
  - **FAST**: Fourier Amplitude Sensitivity Test. Requires a minimum of 65 samples per parameter for valid Fourier decomposition. Total evaluations = samples per parameter x number of parameters.
  - **Sobol**: Uses LHS sampling with binned variance-based first-order index estimation. Approximate but flexible.
- **Samples per parameter** slider -- Determines total SWAT runs

### Step 12: Baseline Diagnostic Analysis

Before calibration begins, the app runs a baseline diagnostic analysis on the current (uncalibrated) model output compared to observations. This pre-calibration check produces:

- **BFI Deficiency**: Compares observed and simulated Baseflow Index (BFI) using Eckhardt baseflow separation
- **Peak Flow Bias**: Compares magnitude and timing of peak flow events
- **Flow Duration Curve Metrics**: Yilmaz FDC decomposition for high-flow, mid-flow, and low-flow segments
- **KGE Decomposition**: Breaks KGE into correlation, variability ratio, and bias ratio components
- **Diagnostic Findings**: Bulleted list with confidence levels (High, Medium, Low) indicating specific model deficiencies
- **Targeted Parameter Recommendations**: Table suggesting which parameters to adjust, in which direction, with reasoning and confidence

This baseline analysis serves as a "before" snapshot and informs the diagnostic calibration algorithm about which parameters need adjustment.

### Running Calibration

Two action buttons at the bottom:

- **Run Sensitivity Analysis** -- Runs sensitivity analysis only
- **Start Calibration** -- Launches the full calibration run

#### Background Calibration Runner

Calibration runs in a **background daemon thread** with the following architecture:

- The calibration thread survives tab switching and browser refresh. Even if you navigate away from the Calibration page and come back, the running calibration is still active.
- A shared `CalibrationState` object communicates progress from the background thread to the Streamlit UI thread. CPython's GIL ensures thread-safe reads/writes without explicit locks.
- A module-level registry keeps references to active calibration and sensitivity analysis states, so a browser refresh can reconnect to a running (or just-completed) background task.
- **Progress snapshots** include: simulation count, total iterations, elapsed time, average time per simulation, and best score so far.
- **Cancellation** is cooperative: clicking the Cancel button sets a flag in `CalibrationState`, which the calibration loop checks periodically. For ensemble workers running in separate processes, a file-based cancellation flag is used.

During calibration:
- A **progress bar** shows completion percentage
- A **status message** updates with the current iteration
- A **Cancel Calibration** button (red) lets you stop early
- Calibration runs in a **background thread** so the UI remains responsive

---

## 10. Page 7: Results

View calibration performance, visualizations, and export results.

### Pre-Load Check

If no calibration has been run, a warning appears with a button linking to the Calibration page.

### Section 1: Performance Metrics

**Runtime display** -- Total calibration time formatted as hours/minutes/seconds.

**Metric tiles** (five columns):

| Metric | Format | Rating Guide |
|--------|--------|-------------|
| NSE (Nash-Sutcliffe) | 4 decimals | > 0.75 Very Good, > 0.65 Good, > 0.50 Satisfactory |
| KGE (Kling-Gupta) | 4 decimals | Higher is better |
| PBIAS | 2 decimals + % | < 10% Very Good, < 15% Good, < 25% Satisfactory |
| RSR | 4 decimals | < 0.50 Very Good, < 0.60 Good, < 0.70 Satisfactory |
| R-squared | 4 decimals | Higher is better |

For sequential calibration, metrics are shown per step with headers indicating the reach ID, step number, subbasin count, and step runtime.

An expandable **Performance Rating Guide** table shows the Moriasi et al. (2007) classification thresholds.

### Section 2: Before vs After Calibration

Shown when the app has baseline (pre-calibration) results for comparison.

For each reach:
- A **comparison table** with Before, After, and Change columns for all five metrics
- A **time series plot** showing Observed (black), Before (red dashed), and After (blue solid) lines
- A **Download** button for the plot (PNG, 200 DPI)

If the before and after values are on very different scales, a dual-axis plot is used automatically.

### Section 3: Visualization

Six tabs provide different views of calibration results:

#### Tab 1: Time Series
- Overlaid observed (blue) vs simulated (red) time series
- Title shows the reach ID and objective function value
- Download button (PNG)

If a large scale difference is detected between observed and simulated, a warning appears about potential unit mismatch, and a dual-axis plot is generated.

#### Tab 2: Scatter Plot
- Observed (x-axis) vs Simulated (y-axis) scatter with 1:1 reference line (black dashed)
- Equal aspect ratio
- Title shows reach ID and objective function value
- Download button (PNG)

#### Tab 3: Flow Duration Curves
- Exceedance probability (%) on x-axis, value on y-axis
- Observed (blue) and Simulated (red) lines
- Log-scale y-axis when all values are positive
- Download button (PNG)

#### Tab 4: Residual Analysis
Two side-by-side plots:
- **Left:** Histogram of residuals (simulated minus observed) with a vertical line at zero and at the mean
- **Right:** Scatter of residuals vs observed values with a horizontal reference line at zero
- Download button (PNG)

#### Tab 5: Diagnostics (Hydrograph Analysis)
Detailed diagnostic analysis of model performance:

- **Baseflow Separation** -- Side-by-side observed and simulated baseflow plots with Baseflow Index (BFI) values
- **Four diagnostic metrics:**
  - BFI Ratio (simulated/observed)
  - Peak Magnitude Ratio
  - Peak Timing offset (days)
  - Volume PBIAS (%)
- **Seasonal Bias Chart** -- Bar chart showing volume bias by season
- **Peak Comparison Plot** -- Observed vs simulated peak events
- **Diagnostic Findings** -- Bulleted list with confidence levels (High, Medium, Low)
- **Parameter Recommendations** -- Table suggesting which parameters to adjust, in which direction, with reasoning and confidence

If no significant issues are found, a success message confirms good model performance.

#### Tab 6: Sensitivity (Conditional)
Only appears if sensitivity analysis was run.

- **Tornado chart** -- Horizontal bar chart ranking parameters by sensitivity
- **Ranking table** -- Parameter name, Main Effect (S1), Total Effect (ST), and Ranking
- Download button (PNG)

### Section 4: Multi-Constituent (Phased) Results Display

When phased calibration (Flow, Sediment, Nitrogen, Phosphorus) is used, the Results page shows:

- **Per-Phase Summary Table**: A table listing each phase (Streamflow, Sediment, Nitrogen, Phosphorus), its status (completed, skipped, or error), and key metrics (NSE, KGE, PBIAS)
- **Per-Phase Expandable Details**: Each completed phase has an expandable section containing:
  - Time series comparison (observed vs simulated) for that constituent
  - Scatter plot
  - Seasonal PBIAS analysis
  - List of parameters calibrated in that phase with their optimal values
- **Merged Parameter Summary**: The final merged parameter set from all completed phases

### Section 5: Sequential Step Details (Sequential Modes Only)

- **Step-by-Step Metrics** table -- Step number, Reach ID, Subbasin count, NSE, KGE, PBIAS, and Runtime per step
- **Per-Step Expanders** -- Each step has an expandable section showing:
  - Parameters calibrated at that step (name and optimal value)
  - Subbasins modified
  - Runtime
  - Diagnostic summary (BFI ratio, peak metrics, seasonal bias, findings, recommendations)
- **Locked Parameters Summary** -- Table showing which parameters were locked at each subbasin, with their locked values

### Section 6: Optimal Parameters

A table listing each calibrated parameter and its optimal value (formatted to 6 decimal places).

### Section 7: Export Results

**Download buttons:**

| Export | Format | Contents |
|--------|--------|----------|
| **Parameters (JSON)** | `calibration_parameters.json` | Best parameter values, metrics, timestamp, project path |
| **Parameters (CSV)** | `calibration_parameters.csv` | Parameter names and values in two-column format |
| **Metrics (CSV)** | `calibration_metrics.csv` | All performance metrics as a two-column table |
| **Full Report (TXT)** | `calibration_report.txt` | Formatted text report with header, date, project path, runtime, metrics, and parameters |

### Section 8: Apply Parameters to Model

Click **Apply Best Parameters to Model** to write the calibrated values directly into your SWAT input files. Three application options are available:

| Option | Description |
|--------|-------------|
| **Full Basin** | Applies all calibrated parameters to every subbasin in the project (default for single-site calibration) |
| **Partial Section (Scoped)** | Applies parameters only to the subbasins that were calibrated (relevant for sequential calibration steps) |
| **Sequential Multi-Step** | Applies locked parameters from all sequential calibration steps, each to its respective subbasin group |

Before applying, the app creates a timestamped backup copy of the project directory (e.g., `TxtInOut_backup_20260406_143021/`) so you can revert if needed.

A success message confirms how many parameters were applied. You can then run a simulation to verify the results.

If an error occurs, the app suggests applying parameters manually using the exported JSON file.

---

## 11. Python API Reference

SWAT-DG provides a full Python API for scripting and automation. All classes and functions described below can be used independently of the Streamlit web application.

### 11.1 SWATModel

The primary entry point for interacting with a SWAT2012 project.

```python
from swat_modern import SWATModel

model = SWATModel("C:/my_watershed/TxtInOut")
# Or specify the executable explicitly:
model = SWATModel("C:/my_watershed/TxtInOut", executable="C:/swat/swat_64rel.exe")
```

**Constructor parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `project_dir` | str or Path | Path to directory containing SWAT input files (must contain `file.cio`) |
| `executable` | str or Path (optional) | Path to SWAT executable. If omitted, auto-searches project and parent directories. Also checks `SWAT_EXE` environment variable. |

**Methods:**

#### `run(timeout=None, capture_output=True, cancel_event=None, cancel_file=None)`

Run a SWAT simulation.

```python
result = model.run()
if result.success:
    print(f"Completed in {result.runtime:.1f}s")
else:
    print(f"Failed: {result.error_message}")
```

| Parameter | Type | Description |
|-----------|------|-------------|
| `timeout` | int (optional) | Maximum seconds to wait (None = no limit) |
| `capture_output` | bool | Capture stdout/stderr (default True) |
| `cancel_event` | threading.Event (optional) | Set this event to terminate a running simulation |
| `cancel_file` | str (optional) | File path; when the file exists, the simulation is terminated. Used for cross-process cancellation. |

Returns: `SimulationResult`

#### `get_output(variable, output_type="rch", unit_id=None, start_date=None, end_date=None)`

Read output data from simulation results.

```python
# Get streamflow for reach 14
flow = model.get_output("FLOW_OUT", output_type="rch", unit_id=14)

# Get sediment for all reaches
sediment = model.get_output("SED_OUT", output_type="rch")

# Get subbasin water yield
wyld = model.get_output("WYLD", output_type="sub", unit_id=5)
```

| Parameter | Type | Description |
|-----------|------|-------------|
| `variable` | str | Variable name (e.g., "FLOW_OUT", "SED_OUT", "NO3_OUT"). Supports fuzzy matching -- "FLOW_OUT" matches "FLOW_OUTcms". |
| `output_type` | str | "rch" (reach), "sub" (subbasin), or "hru" |
| `unit_id` | int (optional) | Specific unit number (None = all units) |
| `start_date` | str (optional) | Start date filter (YYYY-MM-DD) |
| `end_date` | str (optional) | End date filter (YYYY-MM-DD) |

Returns: `pandas.DataFrame`

#### `modify_parameter(param_name, value, file_type="bsn", method="replace", unit_id=None, decimal_precision=4)`

Modify a model parameter in SWAT input files.

```python
# Set ESCO to 0.9 in all .bsn files
model.modify_parameter("ESCO", 0.9, file_type="bsn")

# Reduce CN2 by 10% in all .mgt files
model.modify_parameter("CN2", -0.1, file_type="mgt", method="multiply")

# Set GW_DELAY to 50 in subbasin 3 only
model.modify_parameter("GW_DELAY", 50.0, file_type="gw", unit_id=3)
```

| Parameter | Type | Description |
|-----------|------|-------------|
| `param_name` | str | Parameter name (e.g., "CN2", "ESCO") |
| `value` | float | New value |
| `file_type` | str | File extension ("bsn", "hru", "gw", "mgt", "rte", "sol") |
| `method` | str | "replace" (set to value), "multiply" (multiply existing by 1+value), or "add" (add value to existing) |
| `unit_id` | int (optional) | Specific unit to modify (None = all) |
| `decimal_precision` | int | Decimal places for formatting (default 4) |

#### `get_parameter(param_name, file_type="bsn", unit_id=None)`

Read the current value of a parameter from SWAT input files.

```python
# Get ESCO value (single basin-level parameter)
esco = model.get_parameter("ESCO", file_type="bsn")

# Get CN2 for all subbasins (returns dict: {unit_id: value})
cn2_values = model.get_parameter("CN2", file_type="mgt")

# Get GW_DELAY for subbasin 3
gw_delay = model.get_parameter("GW_DELAY", file_type="gw", unit_id=3)
```

Returns: `float` if `unit_id` specified, `Dict[int, float]` otherwise.

#### `backup(backup_dir=None, file_types=None)`

Create a backup of the current project state.

```python
# Full backup (all input file types)
backup_path = model.backup()

# Selective backup (only groundwater and basin files)
backup_path = model.backup(file_types=["gw", "bsn"])

# Backup to a specific directory
backup_path = model.backup(backup_dir="C:/backups/before_calibration")
```

| Parameter | Type | Description |
|-----------|------|-------------|
| `backup_dir` | str or Path (optional) | Destination directory. Default: `project_dir/backup_YYYYMMDD_HHMMSS` |
| `file_types` | list of str (optional) | Only backup these extensions (e.g., `["gw", "bsn"]`). None = all input types. |

Returns: `Path` to the backup directory.

Selective backup can dramatically reduce backup/restore time. For example, backing up only `gw`, `bsn`, and `mgt` files copies 1.4 MB instead of 1.4 GB for a large project.

#### `restore(backup_dir, file_types=None)`

Restore the project from a backup.

```python
model.restore(backup_path)

# Selective restore (only groundwater files)
model.restore(backup_path, file_types=["gw"])
```

When `.cio` is not in the restored file types, the `SWATConfig` reload is skipped for additional speed.

### 11.2 SWATConfig

Configuration manager for SWAT project settings. Automatically created when you instantiate `SWATModel`.

```python
from swat_modern import SWATConfig

config = SWATConfig("C:/my_watershed/TxtInOut")
```

**Key attributes:**

| Attribute | Type | Description |
|-----------|------|-------------|
| `period` | `SimulationPeriod` | Contains `start_year`, `end_year`, `start_day`, `end_day`, `warmup_years`. Also provides `start_date` and `end_date` properties as Python `date` objects. |
| `output` | `OutputSettings` | Contains `daily`, `monthly`, `yearly` booleans and `print_code` (1=daily, 0=monthly, 2=yearly) |

**Methods:**

```python
# Query project dimensions
n_subs = config.get_subbasin_count()   # counts .sub files
n_hrus = config.get_hru_count()        # counts .hru files
n_reaches = config.get_reach_count()   # counts .rte files

# Get weather data period
start_yr, end_yr = config.get_weather_data_period()  # from .pcp files

# Modify and save
config.period.start_year = 2005
config.period.end_year = 2020
config.period.warmup_years = 2
config.output.print_code = 1  # daily output
config.save()  # writes changes back to file.cio
```

### 11.3 SWATRunner

Low-level simulation runner with timeout and cancellation support. Used internally by `SWATModel.run()`.

```python
from swat_modern.core.runner import SWATRunner
import threading

runner = SWATRunner(executable="C:/swat/swat.exe", project_dir="C:/project")

# Run with timeout
result = runner.run(timeout=300)  # 5-minute timeout

# Run with cancellation support
cancel = threading.Event()
result = runner.run(cancel_event=cancel)
# In another thread: cancel.set() to stop the simulation
```

### 11.4 SimulationResult

Container returned by `SWATModel.run()`.

```python
result = model.run()

# Check status
print(result.success)       # True/False
print(result.runtime)       # seconds
print(result.return_code)   # process exit code
print(result.error_message) # human-readable error if failed
print(result.timestamp)     # datetime when simulation was run

# Access output files
for name, path in result.output_files.items():
    print(f"{name}: {path}")

# Read parsed output data
rch_data = result.get_reach_output()      # DataFrame from output.rch
sub_data = result.get_subbasin_output()    # DataFrame from output.sub

# Get water balance from output.std
balance = result.get_water_balance()       # dict of water balance components

# Print formatted summary
print(result.summary())
```

### 11.5 Calibrator

High-level interface for automated SWAT model calibration.

```python
from swat_modern import SWATModel
from swat_modern.calibration import Calibrator

model = SWATModel("C:/my_watershed")
calibrator = Calibrator(
    model=model,
    observed_data="streamflow.csv",            # CSV, DataFrame, or Series
    parameters=["CN2", "ESCO", "GW_DELAY", "ALPHA_BF"],  # or None for defaults
    output_variable="FLOW_OUT",
    output_type="rch",
    reach_id=14,
    objective="nse",                           # "nse", "kge", "pbias", "log_nse"
    warmup_years=1,
)
```

**Constructor parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `model` | SWATModel | Model instance |
| `observed_data` | DataFrame, Series, str, or Path | Observation data with date and value columns |
| `parameters` | list of str, list of CalibrationParameter, or ParameterSet (optional) | Parameters to calibrate. None = default top 10 streamflow parameters. |
| `output_variable` | str | SWAT output variable (default: "FLOW_OUT") |
| `output_type` | str | "rch", "sub", or "hru" (default: "rch") |
| `reach_id` | int | Unit ID for output extraction (default: 1) |
| `objective` | str | Objective function name (default: "nse") |
| `warmup_years` | int | Years to exclude from evaluation (default: 1) |

#### `auto_calibrate(n_iterations=5000, algorithm="sceua", parallel=False, ...)`

The main calibration entry point. Supports all algorithms including diagnostic.

```python
# Standard calibration with SCE-UA
results = calibrator.auto_calibrate(n_iterations=5000, algorithm="sceua")

# Quick diagnostic calibration (5-20 runs)
results = calibrator.auto_calibrate(
    n_iterations=15,
    algorithm="diagnostic",
    kge_target=0.70,
    pbias_target=10.0,
)

# Parallel ensemble diagnostic
results = calibrator.auto_calibrate(
    n_iterations=15,
    algorithm="diagnostic_ensemble",
    n_ensemble_workers=4,
)

# Monte Carlo with parallel processing
results = calibrator.auto_calibrate(
    n_iterations=10000,
    algorithm="mc",
    parallel=True,
    n_cores=4,
)
```

| Parameter | Type | Description |
|-----------|------|-------------|
| `n_iterations` | int | Number of model evaluations (default: 5000) |
| `algorithm` | str | "sceua", "dream", "mc", "lhs", "rope", "demcz", "abc", "fscabc", "diagnostic", "diagnostic_ensemble" |
| `parallel` | bool | Enable parallel processing (default: False) |
| `n_cores` | int (optional) | CPU cores for parallel mode |
| `dbname` | str (optional) | Database name for saving results |
| `dbformat` | str | "csv" or "sql" (default: "csv") |
| `verbose` | bool | Print progress (default: True) |
| `progress_callback` | callable (optional) | Callback receiving progress dict |
| `kge_target` | float | KGE target for diagnostic algorithms (default: 0.70) |
| `pbias_target` | float | PBIAS target for diagnostic algorithms (default: 10.0) |
| `n_ensemble_workers` | int | Workers for diagnostic ensemble (default: 4) |

Returns: `CalibrationResult`

#### `diagnostic_calibrate(max_iterations=15, kge_target=0.70, pbias_target=10.0, ...)`

Run diagnostic-guided calibration directly (without going through `auto_calibrate`).

```python
results = calibrator.diagnostic_calibrate(
    max_iterations=15,
    kge_target=0.70,
    pbias_target=10.0,
    damping=0.5,          # secant method damping
    constituent="flow",   # "flow", "sediment", "nitrogen", "phosphorus"
)
```

The diagnostic calibrator works in four phases:
1. **Baseline**: Run current parameters, diagnose, early-exit if already good
2. **Volume correction**: Adjusts ESCO, CN2 to fix total volume bias
3. **Baseflow partition**: Adjusts GWQMN, RCHRG_DP, ALPHA_BF, GW_DELAY
4. **Peak correction**: Adjusts CN2, SURLAG

Returns: `CalibrationResult`

#### `ensemble_diagnostic_calibrate(n_workers=4, max_iterations=15, ...)`

Launches N independent diagnostic calibrators with diverse configurations in parallel. Same wall-clock time as a single diagnostic, but better solution quality.

```python
results = calibrator.ensemble_diagnostic_calibrate(
    n_workers=4,
    max_iterations=15,
    kge_target=0.70,
    pbias_target=10.0,
)
```

Returns: `CalibrationResult` (best result from all workers)

#### `phased_calibrate(wq_observations, phases=None, ...)`

Run phased multi-constituent calibration (Flow, Sediment, Nitrogen, Phosphorus).

```python
from swat_modern.calibration.phased_calibrator import PhasedCalibrationResult

# Load WQ observations (DataFrame with date + concentration columns)
# Columns: date, TN_mg_L, TP_mg_L, TSS_mg_L
wq_df = pd.read_csv("wq_data.csv", parse_dates=["date"])

result = calibrator.phased_calibrate(wq_df)
result.print_summary()
```

Phases are automatically enabled based on available observation columns. If `wq_observations` has a `TN_mg_L` column, nitrogen calibration is enabled; if it has `TP_mg_L`, phosphorus is enabled; etc.

Returns: `PhasedCalibrationResult`

#### `multi_site_calibrate(sites, mode="simultaneous", n_iterations=5000, ...)`

Multi-site calibration with simultaneous or sequential strategies.

```python
# Simultaneous: single optimization with weighted objectives
results = calibrator.multi_site_calibrate(
    sites=[
        {"reach_id": 3, "observed": upstream_df, "weight": 1.0},
        {"reach_id": 7, "observed": outlet_df, "weight": 1.5},
    ],
    mode="simultaneous",
    n_iterations=5000,
)

# Sequential: upstream-to-downstream with parameter locking
results = calibrator.multi_site_calibrate(
    sites=[
        {"reach_id": 3, "observed": upstream_df},
        {"reach_id": 7, "observed": outlet_df},
    ],
    mode="sequential",
    n_iterations=5000,
    use_partial_basin=True,
)

# Diagnostic sequential
results = calibrator.multi_site_calibrate(
    sites=[...],
    mode="diagnostic_sequential",
    n_iterations=15,
)
```

| Mode | Description |
|------|-------------|
| `"simultaneous"` | Single optimization against all sites with weighted objective |
| `"sequential"` | Upstream-to-downstream calibration with parameter locking |
| `"diagnostic_sequential"` | Like sequential but uses diagnostic calibration per step |

Returns: `CalibrationResult` (simultaneous) or `SequentialCalibrationResult` (sequential)

#### `sensitivity_analysis(n_samples=1000, method="fast", parallel=False, ...)`

Run parameter sensitivity analysis.

```python
sa_result = calibrator.sensitivity_analysis(
    n_samples=100,     # per parameter (FAST minimum: 65)
    method="fast",     # "fast" or "sobol"
    parallel=True,
    n_cores=4,
)
print(sa_result.sensitivity)       # dict or DataFrame of S1 indices
print(sa_result.best_parameters)   # best param set found during SA
print(sa_result.best_objective)    # best objective value
```

Returns: `SensitivityResult`

### 11.6 CalibrationResult

Container returned by calibration methods.

```python
results = calibrator.auto_calibrate()

# Access results
print(results.best_parameters)    # {"CN2": -0.12, "ESCO": 0.85, ...}
print(results.best_objective)     # 0.78
print(results.metrics)            # {"nse": 0.78, "kge": 0.72, "pbias": -5.2, ...}
print(results.runtime)            # 342.5 (seconds)
print(results.n_iterations)       # 5000
print(results.algorithm)          # "sceua"
print(results.objective_name)     # "nse"
print(results.reach_id)           # 14

# Data arrays
print(results.observed)           # numpy array
print(results.simulated)          # numpy array
print(results.dates)              # numpy array of dates (optional)
print(results.all_parameters)     # DataFrame of all tried parameter sets
print(results.all_objectives)     # numpy array of all objective values
print(results.site_results)       # list of per-site dicts (multi-site only)

# Visualization
results.plot_comparison(title="My Calibration", save_path="comparison.png")
results.plot_parameter_evolution(parameters=["CN2", "ESCO"])

# Summary
results.print_summary()
print(results.summary())

# Save
results.save_best_parameters("best_params.json")  # JSON with params + metrics
results.save_full_results("all_iterations.csv")    # CSV of all tried param sets
```

### 11.7 Objective Functions

All objective functions accept `(observed, simulated)` arrays and return a float.

```python
from swat_modern.calibration.objectives import (
    nse, kge, pbias, rmse, mae, r_squared, rsr, log_nse, mse,
    evaluate_model, ObjectiveFunction, model_performance_rating,
)

# Individual functions
print(nse(obs, sim))          # Nash-Sutcliffe: -inf to 1 (1 = perfect)
print(kge(obs, sim))          # Kling-Gupta: -inf to 1 (1 = perfect)
print(pbias(obs, sim))        # Percent Bias: 0% optimal, positive = underestimate
print(rmse(obs, sim))         # Root Mean Square Error: 0 = perfect
print(mae(obs, sim))          # Mean Absolute Error: 0 = perfect
print(r_squared(obs, sim))    # Coefficient of Determination: 0 to 1
print(rsr(obs, sim))          # RMSE-std ratio: 0 = perfect
print(log_nse(obs, sim))      # NSE of log values: emphasizes low flows
print(mse(obs, sim))          # Mean Square Error

# KGE with decomposition
kge_val, r, alpha, beta = kge(obs, sim, return_components=True)
# r = correlation, alpha = variability ratio, beta = bias ratio

# Evaluate with multiple metrics at once
metrics = evaluate_model(obs, sim, metrics=["nse", "kge", "pbias", "rmse", "r_squared", "rsr"])
# Returns {"nse": 0.78, "kge": 0.72, ...}

# Get performance rating string
rating = model_performance_rating(0.78)  # "Very Good"

# ObjectiveFunction wrapper
obj = ObjectiveFunction("nse", weight=1.0)
value = obj.evaluate(obs, sim)
score = obj.score(obs, sim)  # weighted, sign-adjusted for optimization
```

### 11.8 CalibrationDashboard

Create a combined visualization dashboard with hydrograph, scatter plot, metrics table, flow duration curve, and monthly comparison.

```python
from swat_modern.visualization import CalibrationDashboard

dashboard = CalibrationDashboard(
    dates=dates_array,
    observed=obs_array,
    simulated=sim_array,
    site_name="Big Creek Watershed",
    variable_name="Streamflow",
    units="m3/s",
)

# Create and display the dashboard (matplotlib figure with 5 panels)
fig = dashboard.create_dashboard(figsize=(16, 12), show=True)

# Save to file
dashboard.save("calibration_report.png", dpi=150)

# Export as HTML report
dashboard.to_html("calibration_report.html")

# Access computed metrics
print(dashboard.metrics)  # {"nse": ..., "kge": ..., ...}
print(dashboard.rating)   # "Very Good", "Good", etc.
```

### 11.9 Visualization Functions

Individual visualization functions for custom plots.

```python
from swat_modern.visualization import (
    plot_hydrograph,
    plot_hydrograph_monthly,
    plot_scatter,
    plot_residuals,
    plot_duration_curve,
    plot_duration_comparison,
    plot_sensitivity_tornado,
    sensitivity_ranking_table,
    MetricsTable,
    create_metrics_dataframe,
)

# Time series comparison
fig = plot_hydrograph(dates, observed, simulated, title="Streamflow")

# Monthly aggregated hydrograph
fig = plot_hydrograph_monthly(dates, observed, simulated)

# Scatter plot with 1:1 line
fig = plot_scatter(observed, simulated, show_metrics=True)

# Residual analysis (histogram + residuals vs observed)
fig = plot_residuals(observed, simulated)

# Flow duration curve
fig = plot_duration_curve(data, label="Observed")

# FDC comparison (observed vs simulated)
fig = plot_duration_comparison(observed, simulated)

# Sensitivity tornado chart
fig = plot_sensitivity_tornado(sensitivity_dict, title="Parameter Sensitivity")

# Sensitivity ranking table
df = sensitivity_ranking_table(sensitivity_dict)

# Metrics table
table = MetricsTable(observed, simulated)
table.display()
metrics_df = create_metrics_dataframe(observed, simulated)
```

**Diagnostic visualization functions:**

```python
from swat_modern.visualization import (
    plot_baseflow_separation,
    plot_peak_comparison,
    plot_seasonal_bias,
    plot_recommendations_table,
    plot_diagnostic_dashboard,
    plot_rating_curve,
    plot_flow_partition,
    plot_event_partition,
    plot_wq_diagnostic_dashboard,
)
```

**Plotly interactive charts** (requires plotly):

```python
from swat_modern.visualization import (
    plotly_time_series,
    plotly_multi_variable,
    plotly_bar_summary,
    plotly_scatter_comparison,
)
```

---

## 12. Data Automation Pipeline

The `swat_modern.data` module provides tools for automated retrieval and processing of SWAT input data, primarily for US watersheds.

### 12.1 WeatherDataFetcher

Fetch and process weather data for SWAT input files.

```python
from swat_modern.data import WeatherDataFetcher

# From a local CSV file
weather = WeatherDataFetcher.from_csv("weather_data.csv")

# From NOAA API (requires data token)
from swat_modern.data import NOAAClient
client = NOAAClient(token="your_noaa_api_token")
weather = WeatherDataFetcher.from_noaa_api(
    client=client,
    station_id="USW00013968",
    start_date="2000-01-01",
    end_date="2020-12-31",
)

# Generate SWAT weather input files
weather.to_swat_files("output_dir/")

# Generate WGEN parameters for weather generator
wgen_params = weather.generate_wgen_parameters()
```

**Exported classes:**

| Class | Description |
|-------|-------------|
| `WeatherDataFetcher` | Main class for fetching and converting weather data |
| `WeatherStation` | Metadata for a weather station (ID, name, coordinates) |
| `WeatherData` | Container for daily weather records |
| `NOAAClient` | NOAA Climate Data Online API client |

### 12.2 SoilDataFetcher

Retrieve and process soil data for SWAT `.sol` files.

```python
from swat_modern.data import SoilDataFetcher

# From SSURGO database (US soils)
soil = SoilDataFetcher.from_ssurgo(mukey=123456)

# Create a default soil profile manually
soil = SoilDataFetcher.create_default_profile("loam", depth_cm=150)

# Write to SWAT .sol file format
soil.to_swat_file("output/000010001.sol")
```

**Exported classes:**

| Class | Description |
|-------|-------------|
| `SoilDataFetcher` | Retrieves soil data from SSURGO or creates default profiles |
| `SoilLayer` | Individual soil layer properties (depth, bulk density, AWC, K, etc.) |
| `SoilProfile` | Complete soil profile with multiple layers |
| `SoilDataset` | Collection of soil profiles for a watershed |

### 12.3 LandCoverFetcher

Map NLCD (National Land Cover Database) classes to SWAT land use codes.

```python
from swat_modern.data import LandCoverFetcher, NLCDClass, NLCD_TO_SWAT

# Get SWAT code for an NLCD class
nlcd = NLCDClass.DECIDUOUS_FOREST
swat_code = nlcd.swat_code  # Returns "FRSD"

# Look up mapping
print(NLCD_TO_SWAT[41])  # "FRSD" (Deciduous Forest)

# Fetch land cover data from NLCD
landcover = LandCoverFetcher.from_nlcd(bbox=(-95.5, 35.0, -94.5, 36.0))
```

### 12.4 DEMProcessor

Process digital elevation models for watershed delineation (requires GIS dependencies).

```python
from swat_modern.data import DEMProcessor

# Load DEM
dem = DEMProcessor.from_file("elevation.tif")

# Pre-process
dem.fill_sinks()
dem.compute_flow_direction()
dem.compute_flow_accumulation()

# Delineate watershed from an outlet point
watershed = dem.delineate_watershed(outlet=(500, 350))
```

**Exported classes:**

| Class | Description |
|-------|-------------|
| `DEMProcessor` | DEM loading, sink filling, flow routing, and watershed delineation |
| `DEMMetadata` | DEM spatial metadata (CRS, resolution, bounds) |
| `WatershedResult` | Delineated watershed boundary and properties |
| `StreamNetwork` | Extracted stream network from flow accumulation |

---

## 13. GIS / Spatial Tools

The `swat_modern.spatial` module provides GIS functionality for loading and visualizing watershed spatial data.

### 13.1 ShapefileLoader

Discover and load shapefiles from SWAT project directories. Searches standard locations used by SWAT2012 and SWAT+.

```python
from swat_modern.spatial import ShapefileLoader

loader = ShapefileLoader("C:/SWAT_project")

# Auto-discover shapefiles
found = loader.find_shapefiles()
# Returns: {"subbasins": Path(...), "streams": Path(...), "boundary": Path(...), ...}

# Load individual layers as GeoDataFrames
subbasins = loader.load_subbasins()
streams = loader.load_streams()
boundary = loader.load_boundary()
reservoirs = loader.load_reservoirs()

# Extract routing topology from stream attributes
topology = loader.extract_topology()
```

**Search locations:**
- `project_dir/Watershed/Shapes/`
- `project_dir/Shapes/`
- `project_dir/../Watershed/Shapes/`
- SWAT+ SQLite databases (`*.sqlite`)

**Layer identification** uses heuristic pattern matching on filenames:
- Subbasins: `sub`, `subbasin`, `subbasins`, `basin`
- Streams: `riv`, `river`, `stream`, `reach`, `channel`
- Boundary: `wshed`, `watershed`, `boundary`, `outline`
- Reservoirs: `res`, `reservoir`, `reservoirs`, `lake`
- HRUs: `hru`, `lsu`, `lsus`, `landscape`

### 13.2 WatershedMapBuilder

Build interactive Folium maps for watershed visualization.

```python
from swat_modern.spatial import WatershedMapBuilder

builder = WatershedMapBuilder()

# Create a base map centered on the watershed
builder.create_base_map(subbasins_gdf, zoom_start=10, tiles="OpenStreetMap")

# Add layers
builder.add_subbasins(subbasins_gdf)
builder.add_streams(streams_gdf)

# Add a heatmap layer (e.g., CN2 values by subbasin)
builder.add_heatmap(subbasins_gdf, column="CN2", colormap="YlOrRd", legend_name="CN2 Value")

# Get the folium Map object
m = builder.get_map()

# Save to HTML
builder.save("watershed_map.html")
```

---

## 14. SWAT+ to SWAT2012 Converter

The `swat_modern.io.converters` module converts SWAT+ TxtInOut files to SWAT 2012 format for use with the SWAT-DG calibration tool.

### Overview

SWAT+ uses a fundamentally different file format and naming convention from SWAT2012. This converter translates the key input files so that existing SWAT2012 executables and calibration tools can work with projects originally created in SWAT+.

### Usage

```python
from swat_modern.io.converters import SWATplusToSWAT2012Converter

converter = SWATplusToSWAT2012Converter(
    source_dir="C:/UIRW/Scenarios/Default/TxtInOut",  # SWAT+ TxtInOut
    output_dir="C:/UIRW_2012",                         # Output SWAT2012 directory
    num_subbasins=25,                                   # Number of subbasins to include
)
converter.convert()
```

**Command-line interface:**

```bash
python -m swat_modern.io.converters.converter \
    --source "C:/UIRW/Scenarios/Default/TxtInOut" \
    --output "C:/UIRW_2012" \
    --num-subbasins 25
```

### Key Components

| Class | File | Purpose |
|-------|------|---------|
| `SWATplusToSWAT2012Converter` | `converter.py` | Main orchestrator |
| `SWATplusReader` | `swatplus_reader.py` | Reads SWAT+ input files (connect, routing_unit, channel, aquifer, hru, soils, landuse, management, weather, etc.) |
| `SWAT2012Writer` | `swat2012_writer.py` | Writes SWAT 2012 format files (`.sub`, `.hru`, `.gw`, `.sol`, `.mgt`, `.rte`, `.bsn`, `file.cio`, `fig.fig`, etc.) |
| `ParameterMapper` | `parameter_mapper.py` | Maps SWAT+ parameter names and units to SWAT2012 equivalents |
| `RoutingBuilder` | `routing_builder.py` | Builds `fig.fig` routing file from SWAT+ connectivity |
| `WeatherConverter` | `weather_converter.py` | Converts SWAT+ weather files to SWAT2012 `.pcp`, `.tmp`, `.slr`, `.wnd`, `.hmd` format |

---

## 15. Session Persistence

The Streamlit app persists session state to disk so that browser refreshes, tab switches, and session timeouts do not lose your work.

### Persistence Architecture

The persistence system uses a **multi-tier approach**:

| Tier | Format | Keys | Purpose |
|------|--------|------|---------|
| **JSON** | `.json` | project_path, swat_exe, reach_id, output_variable, calibration_objective, sensitivity_results, etc. | Simple scalar and dictionary values that are JSON-serializable |
| **Pickle** | `.pkl` | observed_data, wq_load_data, calibration_results_full, baseline_results, etc. | Complex objects (pandas DataFrames, numpy arrays, custom classes) |

### Per-Project Session Files

Session files are keyed by the **MD5 hash** of the project path to avoid cross-tab/cross-project conflicts:

- JSON session: `~/.swat_modern/session_{hash8}.json`
- Observation data: `~/.swat_modern/obs_data_{hash8}.pkl`
- Calibration results: `~/.swat_modern/cal_results_{hash8}.pkl`

Default location: `~/.swat_modern/` (user home directory).

### What Persists

| Category | Keys | Persistence Tier |
|----------|------|-----------------|
| Project setup | project_path, swat_exe, swat_executable | JSON |
| Observation config | obs_units, output_type, reach_id, output_variable | JSON |
| Calibration config | calibration_objective, best_parameters | JSON |
| Observation data | observed_data, observed_data_multi, wq_load_data | Pickle |
| Calibration results | calibration_results_full, calibration_runtime, baseline_results | Pickle |
| Sensitivity results | sensitivity_results, sa_best_params, sa_best_objective, sa_runtime, sa_method_used | JSON |

### Auto-Restore Behavior

1. On page load, the app calls `load_session()` which reads the JSON file and restores simple keys into `st.session_state`
2. `load_observation_data()` restores pandas objects from the pickle file
3. `load_calibration_results()` restores calibration result objects from their pickle file
4. If `project_path` is found in restored state, the `SWATModel` object is automatically reconstructed
5. Only keys that are **not already present** in session state are restored (fresher in-memory data takes priority)

### Background Calibration Survival

The background calibration runner uses module-level registries (`_active_cal_state`, `_active_sa_state`) that survive Streamlit session resets (since Streamlit reloads the page but the Python process and daemon threads continue). After a browser refresh, the app reconnects to the running or just-completed calibration state.

---

## 16. Calibration Parameters Reference

SWAT-DG includes 45+ predefined calibration parameters organized by process group. All parameters are defined in `src/swat_modern/calibration/parameters.py`.

### Hydrology Parameters

| Name | File | Min | Max | Default | Method | Description | Units |
|------|------|-----|-----|---------|--------|-------------|-------|
| CN2 | .mgt | -0.25 | 0.25 | 0.0 | multiply | SCS curve number for moisture condition II (relative change) | -- |
| SURLAG | .bsn | 0.5 | 24.0 | 4.0 | replace | Surface runoff lag coefficient | days |
| OV_N | .hru | 0.01 | 0.5 | 0.15 | replace | Manning's n for overland flow | -- |
| ESCO | .bsn | 0.01 | 1.0 | 0.95 | replace | Soil evaporation compensation factor | -- |
| EPCO | .bsn | 0.01 | 1.0 | 1.0 | replace | Plant uptake compensation factor | -- |
| CANMX | .hru | 0.0 | 100.0 | 0.0 | replace | Maximum canopy storage | mm |

### Groundwater Parameters

| Name | File | Min | Max | Default | Method | Description | Units |
|------|------|-----|-----|---------|--------|-------------|-------|
| GW_DELAY | .gw | 0.0 | 500.0 | 31.0 | replace | Groundwater delay time | days |
| ALPHA_BF | .gw | 0.0 | 1.0 | 0.048 | replace | Baseflow alpha factor | 1/days |
| ALPHA_BF_D | .gw | 0.0 | 1.0 | 0.0 | replace | Baseflow alpha factor for deep aquifer | 1/days |
| GWQMN | .gw | 0.0 | 5000.0 | 1000.0 | replace | Threshold water depth in shallow aquifer for return flow | mm |
| REVAPMN | .gw | 0.0 | 500.0 | 250.0 | replace | Threshold water depth for revap to occur | mm |
| GW_REVAP | .gw | 0.02 | 0.2 | 0.02 | replace | Groundwater revap coefficient | -- |
| RCHRG_DP | .gw | 0.0 | 1.0 | 0.05 | replace | Deep aquifer percolation fraction | -- |
| SHALLST | .gw | 0.0 | 5000.0 | 1000.0 | replace | Initial shallow aquifer storage | mm |
| DEEPST | .gw | 0.0 | 5000.0 | 1000.0 | replace | Initial deep aquifer storage | mm |

### Soil Parameters

| Name | File | Min | Max | Default | Method | Description | Units |
|------|------|-----|-----|---------|--------|-------------|-------|
| SOL_AWC | .sol | -0.5 | 0.5 | 0.0 | multiply | Available water capacity (relative change) | -- |
| SOL_K | .sol | -0.5 | 0.5 | 0.0 | multiply | Saturated hydraulic conductivity (relative change) | mm/hr |
| SOL_BD | .sol | -0.5 | 0.5 | 0.0 | multiply | Soil bulk density (relative change) | g/cm3 |

### Snow Parameters

| Name | File | Min | Max | Default | Method | Description | Units |
|------|------|-----|-----|---------|--------|-------------|-------|
| SFTMP | .bsn | -5.0 | 5.0 | 1.0 | replace | Snowfall temperature | C |
| SMTMP | .bsn | -5.0 | 5.0 | 0.5 | replace | Snow melt base temperature | C |
| SMFMX | .bsn | 0.0 | 10.0 | 4.5 | replace | Maximum melt rate (June 21) | mm/C/day |
| SMFMN | .bsn | 0.0 | 10.0 | 4.5 | replace | Minimum melt rate (December 21) | mm/C/day |
| TIMP | .bsn | 0.0 | 1.0 | 1.0 | replace | Snow pack temperature lag factor | -- |

### Routing Parameters

| Name | File | Min | Max | Default | Method | Description | Units |
|------|------|-----|-----|---------|--------|-------------|-------|
| CH_N2 | .rte | 0.01 | 0.3 | 0.05 | replace | Manning's n for main channel | -- |
| CH_K2 | .rte | 0.0 | 500.0 | 0.0 | replace | Effective hydraulic conductivity of main channel | mm/hr |

### Sediment Parameters

| Name | File | Min | Max | Default | Method | Description | Units |
|------|------|-----|-----|---------|--------|-------------|-------|
| USLE_P | .mgt | 0.1 | 1.0 | 1.0 | replace | USLE support practice factor | -- |
| USLE_K | .sol | -0.5 | 0.5 | 0.0 | multiply | USLE soil erodibility factor (relative change) | -- |
| SPCON | .bsn | 0.0001 | 0.01 | 0.001 | replace | Linear re-entrainment parameter for channel sediment | -- |
| SPEXP | .bsn | 1.0 | 2.0 | 1.0 | replace | Exponent re-entrainment parameter for channel sediment | -- |
| CH_COV1 | .rte | 0.0 | 0.6 | 0.0 | replace | Channel erodibility factor | -- |
| CH_COV2 | .rte | 0.0 | 1.0 | 0.0 | replace | Channel cover factor | -- |
| LAT_SED | .hru | 0.0 | 5000.0 | 0.0 | replace | Lateral sediment concentration | mg/L |
| PRF | .bsn | 0.0 | 2.0 | 1.0 | replace | Peak rate adjustment factor for sediment routing in main channel | -- |
| ADJ_PKR | .bsn | 0.5 | 2.0 | 1.0 | replace | Peak rate adjustment for sediment routing in subbasin | -- |
| SLSUBBSN | .hru | -0.5 | 0.5 | 0.0 | multiply | Average slope length (relative change) | m |
| FILTERW | .mgt | 0.0 | 100.0 | 0.0 | replace | Width of edge-of-field filter strip | m |

### Nutrient Parameters -- Nitrogen

| Name | File | Min | Max | Default | Method | Description | Units |
|------|------|-----|-----|---------|--------|-------------|-------|
| CMN | .bsn | 0.0001 | 0.003 | 0.0003 | replace | Rate factor for humus mineralization of active organic N | -- |
| NPERCO | .bsn | 0.0 | 1.0 | 0.2 | replace | Nitrate percolation coefficient | -- |
| N_UPDIS | .bsn | 0.0 | 100.0 | 20.0 | replace | Nitrogen uptake distribution parameter | -- |
| CDN | .bsn | 0.0 | 3.0 | 1.4 | replace | Denitrification exponential rate coefficient | -- |
| SDNCO | .bsn | 0.0 | 1.1 | 1.0 | replace | Denitrification threshold water content | -- |
| ERORGN | .hru | 0.0 | 5.0 | 0.0 | replace | Organic N enrichment ratio | -- |

### Nutrient Parameters -- Phosphorus

| Name | File | Min | Max | Default | Method | Description | Units |
|------|------|-----|-----|---------|--------|-------------|-------|
| PPERCO | .bsn | 10.0 | 17.5 | 10.0 | replace | Phosphorus percolation coefficient | -- |
| PHOSKD | .bsn | 100.0 | 200.0 | 175.0 | replace | Phosphorus soil partitioning coefficient | -- |
| PSP | .bsn | 0.01 | 0.7 | 0.4 | replace | Phosphorus availability index | -- |
| P_UPDIS | .bsn | 0.0 | 100.0 | 20.0 | replace | Phosphorus uptake distribution parameter | -- |
| ERORGP | .hru | 0.0 | 5.0 | 0.0 | replace | Organic P enrichment ratio | -- |
| GWSOLP | .gw | 0.0 | 0.5 | 0.0 | replace | Soluble phosphorus concentration in groundwater loading | mg/L |

### Plant Growth Parameters

| Name | File | Min | Max | Default | Method | Description | Units |
|------|------|-----|-----|---------|--------|-------------|-------|
| BIOMIX | .mgt | 0.0 | 1.0 | 0.2 | replace | Biological mixing efficiency | -- |

### Modification Methods

| Method | Formula | Use Case |
|--------|---------|----------|
| `replace` | `new_value = calibration_value` | Parameters with absolute physical meaning (e.g., ESCO, GW_DELAY) |
| `multiply` | `new_value = original_value * (1 + calibration_value)` | Parameters that vary spatially and should preserve relative differences (e.g., CN2, SOL_AWC) |
| `add` | `new_value = original_value + calibration_value` | Less commonly used; adds a constant offset |

### Predefined Parameter Groups

The following helper functions return recommended parameter sets:

| Function | Parameters | Purpose |
|----------|-----------|---------|
| `get_streamflow_parameters()` | CN2, ESCO, GW_DELAY, ALPHA_BF, GWQMN, RCHRG_DP, SOL_AWC, SURLAG, EPCO, CH_N2 | Streamflow/hydrology calibration |
| `get_sediment_parameters()` | USLE_P, USLE_K, SPCON, SPEXP, CH_COV1, CH_COV2, LAT_SED, PRF, ADJ_PKR | Sediment yield calibration |
| `get_nitrogen_parameters()` | CMN, NPERCO, N_UPDIS, CDN, SDNCO, ERORGN | Total nitrogen calibration |
| `get_phosphorus_parameters()` | PPERCO, PHOSKD, PSP, P_UPDIS, ERORGP, GWSOLP | Total phosphorus calibration |
| `get_nutrient_parameters()` | All nitrogen + phosphorus parameters | Combined nutrient calibration |
| `get_default_parameters(group=None, top_n=None)` | Configurable | Filtered/sorted by group or sensitivity rank |

---

## 17. Supported File Formats

### Observation Data (Page 4)

| Format | Extensions | Notes |
|--------|-----------|-------|
| CSV | `.csv` | Comma-separated, auto-detected |
| Excel | `.xlsx`, `.xls` | First sheet used |
| Tab-delimited | `.txt`, `.tsv` | Auto-detected delimiter |
| USGS RDB | `.rdb` | Standard USGS format with `#` comment headers |
| Generic data | `.dat` | Space or tab delimited |

Date formats auto-detected: `%Y-%m-%d`, `%m/%d/%Y`, `%d/%m/%Y`, `%Y/%m/%d`, `%Y-%m-%d %H:%M:%S`, `%Y%m%d`

### Water Quality Data (Pages 4 and 6)

| Format | Description |
|--------|-------------|
| Auto-detect | Tries all supported formats automatically |
| Water Quality Portal (WQP) | Narrow-result format from Water Quality Portal (STORET/WQX) with automatic compound-to-elemental unit conversion |
| Generic CSV | Any CSV with date, concentration, and parameter columns |

The WQ loader automatically converts compound-form units (e.g., mg/L as NO3, mg/L NH4, mg/L as PO4) to elemental basis (as N, as P) to match SWAT's nutrient output convention.

### Shapefiles (Page 2)

Standard ESRI shapefiles (`.shp` with `.shx`, `.dbf`, and `.prj` sidecar files). The app auto-discovers subbasin, stream, boundary, and reservoir layers.

### Boundary Configurations (Page 5)

JSON files containing parameter boundary definitions, saved and loaded by the Parameter Editor.

---

## 18. Export & Download Options

| Page | File | Format | Description |
|------|------|--------|-------------|
| Parameter Editor | `calibration_boundaries.json` | JSON | Custom parameter boundaries |
| Results | `calibration_parameters.json` | JSON | Best parameter values + metrics |
| Results | `calibration_parameters.csv` | CSV | Parameter names and values |
| Results | `calibration_metrics.csv` | CSV | Performance metrics table |
| Results | `calibration_report.txt` | TXT | Full formatted calibration report |
| Results | `time_series_reach_{id}.png` | PNG | Time series comparison plot |
| Results | `scatter_reach_{id}.png` | PNG | Observed vs simulated scatter |
| Results | `flow_duration_reach_{id}.png` | PNG | Flow duration curve |
| Results | `residuals_reach_{id}.png` | PNG | Residual analysis plot |
| Results | `sensitivity_tornado.png` | PNG | Parameter sensitivity rankings |
| Results | `before_vs_after_reach_{id}.png` | PNG | Pre/post calibration comparison |

All plot downloads are 200 DPI PNG images.

---

## 19. Troubleshooting

### Common Issues

**"file.cio not found in this folder"**
The path you entered does not contain a `file.cio`. Make sure you are pointing to the TxtInOut directory, not a parent folder.

**"No SWAT executable found in project folder"**
The app could not find a SWAT executable with a recognized name. Use the text field or Browse button to specify the path manually. You can also set the `SWAT_EXE` environment variable.

**"No output files found. Run a SWAT simulation first"**
The project folder does not contain `output.rch`, `output.sub`, or other output files. Run a SWAT simulation first (either from the command line or through the app).

**"No data found for the selected combination"**
The selected variable and unit ID combination does not exist in the output file. Try a different unit ID or variable.

**"The selected column appears to contain row indices"**
The app detected that your selected observation column contains sequential integers (1, 2, 3, ...) instead of measurement values. Choose a different column from the dropdown.

**"Observed data appears to be in cubic feet per second (CFS)"**
SWAT outputs streamflow in cubic meters per second. The app offers automatic conversion (multiply by 0.0283168). Leave the checkbox checked unless your model is configured differently.

**"Only N observations in the selected period"**
Fewer than 10 observations overlap with the simulation period. Consider widening the calibration period or checking date formats.

**Large scale difference warning on Results page**
The observed and simulated values differ by more than 10x. This usually indicates a unit mismatch (e.g., CFS vs CMS, or concentrations vs loads). Check your observation data units and the selected SWAT output variable.

**"Multi-site calibration requires at least 2 sites with data"**
In multi-site mode, upload observation files for at least two sites before starting calibration.

**Calibration takes too long**
- Reduce the number of iterations
- Enable partial-basin simulation (only simulates upstream subbasins)
- Use the Diagnostic-Guided algorithm (converges in 5-20 runs)
- Enable parallel processing to use multiple CPU cores
- Reduce the number of calibration parameters
- Use selective backup/restore (automatic when only a few file types are modified)

**Calibration results are poor (low NSE, high PBIAS)**
- Check observation data units and date alignment
- Start with a small set of parameters (the Recommended 4)
- Use the Diagnostics tab to identify specific model deficiencies
- Increase the number of iterations
- Ensure the warmup period is adequate (at least 1 year)
- Try the diagnostic-guided algorithm, which targets specific hydrograph deficiencies

**FAST sensitivity analysis produces NaN or unreliable results**
FAST requires a minimum of 65 samples per parameter for valid Fourier decomposition. If you specify fewer, the app automatically increases to 65. If results still look unreliable, increase samples to 100+ per parameter.

**Parallel calibration fails or hangs**
- Ensure `pathos` is installed: `pip install pathos`
- Reduce the number of cores (leave at least 1-2 cores free for the OS)
- Check that the SWAT project directory is accessible from all worker processes
- For diagnostic ensemble, each worker creates its own project copy; ensure sufficient disk space

**Browser refresh loses calibration state**
The background calibration thread survives browser refresh. Return to the Calibration page, and the app will reconnect to the running calibration. If results were already completed, they are persisted to `~/.swat_modern/` and restored automatically.

**"SPOTPY is required for calibration"**
Install calibration dependencies: `pip install "swat-dg[calibration]"`

**"geopandas is required for spatial operations"**
Install GIS dependencies: `pip install "swat-dg[gis]"`

---

## 20. Performance Rating Guide

Based on Moriasi et al. (2007) guidelines for model evaluation:

| Rating | NSE | PBIAS (Streamflow) | RSR |
|--------|-----|---------------------|-----|
| Very Good | > 0.75 | < 10% | < 0.50 |
| Good | 0.65 -- 0.75 | 10% -- 15% | 0.50 -- 0.60 |
| Satisfactory | 0.50 -- 0.65 | 15% -- 25% | 0.60 -- 0.70 |
| Unsatisfactory | < 0.50 | > 25% | > 0.70 |

**KGE:** Values above 0.50 are generally considered acceptable. Values above 0.75 indicate very good performance.

**R-squared:** Values above 0.50 indicate that the model explains more than half the variance in observations.

---

*SWAT-DG is open-source software under the Apache 2.0 License. All processing runs locally on your machine. Your data is never uploaded to external servers.*
