# SWAT-DG User Manual

**Version 0.5.0** | Last Updated: 2026-03-20

A complete guide to the SWAT-DG Streamlit web application for SWAT model calibration, visualization, and analysis.

---

## Table of Contents

1. [Getting Started](#1-getting-started)
2. [Home Dashboard](#2-home-dashboard)
3. [Page 1: Project Setup](#3-page-1-project-setup)
4. [Page 2: Watershed Map](#4-page-2-watershed-map)
5. [Page 3: Simulation Results](#5-page-3-simulation-results)
6. [Page 4: Observation Data](#6-page-4-observation-data)
7. [Page 5: Parameter Editor](#7-page-5-parameter-editor)
8. [Page 6: Calibration](#8-page-6-calibration)
9. [Page 7: Results](#9-page-7-results)
10. [Supported File Formats](#10-supported-file-formats)
11. [Export & Download Options](#11-export--download-options)
12. [Troubleshooting](#12-troubleshooting)
13. [Performance Rating Guide](#13-performance-rating-guide)

---

## 1. Getting Started

### Installation

```bash
# Install with all app dependencies
pip install -e ".[app]"
```

### Launching the App

```bash
streamlit run src/swat_modern/app/main.py
```

The app opens in your default browser at `http://localhost:8501`. All data stays on your machine -- nothing is uploaded to the cloud.

### Key Features

- **Diagnostic-guided calibration**: Analyzes hydrograph deficiencies (volume bias, baseflow partition, peak timing) and converges in 5–20 model runs instead of thousands. Available as single-site or ensemble (multi-start parallel) mode.
- **Parallel calibration**: Distributes SWAT runs across multiple CPU cores for standard algorithms (SCE-UA, Monte Carlo, LHS), reducing wall-clock time proportionally.
- **Phased water quality calibration**: Automatically sequences Flow → Sediment → Nitrogen → Phosphorus calibration.
- **Partial-basin simulation**: Simulates only subbasins upstream of the calibration target, with speedups up to 15x for interior gauges.

### What You Need Before Starting

- A **SWAT2012 project folder** (the TxtInOut directory containing `file.cio` and all input files)
- A **SWAT executable** (e.g., `swat_64rel.exe`). The app will attempt to auto-detect it in your project folder.
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

## 2. Home Dashboard

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

---

## 3. Page 1: Project Setup

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
- `swat.exe`, `swat2012.exe`, `SWAT_64rel.exe`, `rev681_64rel.exe`, `SWAT_Rev681.exe`

If found, a success message appears. If not, a text field and Browse button let you specify the path manually.

### Sidebar

- **Exit Project** button -- Clears the loaded project and resets the session

---

## 4. Page 2: Watershed Map

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

## 5. Page 3: Simulation Results

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

## 6. Page 4: Observation Data

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
- Select the **format**: auto-detect, ADEQ, OBSfiles, AWRC, or generic CSV
- If the file contains multiple stations, a dropdown lets you select one
- Click **Load WQ Data** to parse the file

A success message shows the number of records and available constituents (Total Nitrogen, Total Phosphorus, TSS, NO3, NH4, Organic N, Ortho-P) with sample counts for each.

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

## 7. Page 5: Parameter Editor

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

## 8. Page 6: Calibration

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

Choose one of four modes (horizontal radio buttons):

| Mode | Description |
|------|-------------|
| **Single-site** | Calibrate against one observation gauge |
| **Simultaneous Multi-site** | Calibrate against multiple gauges with weighted objectives |
| **Sequential (Upstream-to-Downstream)** | Calibrate reaches in hydrologic order, locking parameters at each step |
| **Diagnostic Sequential** | Like Sequential, but uses 5-20 diagnostic runs per step instead of thousands |

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

**For water quality:** A full WQ upload interface appears with format selection, station detection, and constituent selection.

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

**For standard algorithms:**
- **Number of Iterations** slider -- 2 to 50,000 (default 1,000). More iterations give better results but take longer.

**For diagnostic algorithms:**
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

- **Method** -- FAST (recommended, requires minimum 65 samples per parameter) or Sobol (approximate, can use fewer samples)
- **Samples per parameter** slider -- Determines total SWAT runs (samples x number of parameters)

### Running Calibration

Two action buttons at the bottom:

- **Run Sensitivity Analysis** -- Runs sensitivity analysis only
- **Start Calibration** -- Launches the full calibration run

During calibration:
- A **progress bar** shows completion percentage
- A **status message** updates with the current iteration
- A **Cancel Calibration** button (red) lets you stop early
- Calibration runs in a **background thread** so the UI remains responsive

---

## 9. Page 7: Results

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

### Section 4: Sequential Step Details (Sequential Modes Only)

- **Step-by-Step Metrics** table -- Step number, Reach ID, Subbasin count, NSE, KGE, PBIAS, and Runtime per step
- **Per-Step Expanders** -- Each step has an expandable section showing:
  - Parameters calibrated at that step (name and optimal value)
  - Subbasins modified
  - Runtime
  - Diagnostic summary (BFI ratio, peak metrics, seasonal bias, findings, recommendations)
- **Locked Parameters Summary** -- Table showing which parameters were locked at each subbasin, with their locked values

### Section 5: Optimal Parameters

A table listing each calibrated parameter and its optimal value (formatted to 6 decimal places).

### Section 6: Export Results

Three download buttons in a row:

| Export | Format | Contents |
|--------|--------|----------|
| **Parameters (JSON)** | `calibration_parameters.json` | Best parameter values, metrics, timestamp, project path |
| **Metrics (CSV)** | `calibration_metrics.csv` | All performance metrics as a two-column table |
| **Full Report (TXT)** | `calibration_report.txt` | Formatted text report with header, date, project path, runtime, metrics, and parameters |

### Section 7: Apply Parameters to Model

Click **Apply Best Parameters to Model** to write the calibrated values directly into your SWAT input files. The app iterates through each parameter and modifies the corresponding files.

A success message confirms how many parameters were applied. You can then run a simulation to verify the results.

If an error occurs, the app suggests applying parameters manually using the exported JSON file.

---

## 10. Supported File Formats

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
| ADEQ | Arizona Department of Environmental Quality format |
| OBSfiles | Standard observation file format |
| AWRC/WQP | Narrow-result format from Water Quality Portal |
| Generic CSV | Any CSV with date, concentration, and parameter columns |

### Shapefiles (Page 2)

Standard ESRI shapefiles (`.shp` with `.shx`, `.dbf`, and `.prj` sidecar files). The app auto-discovers subbasin, stream, boundary, and reservoir layers.

### Boundary Configurations (Page 5)

JSON files containing parameter boundary definitions, saved and loaded by the Parameter Editor.

---

## 11. Export & Download Options

| Page | File | Format | Description |
|------|------|--------|-------------|
| Parameter Editor | `calibration_boundaries.json` | JSON | Custom parameter boundaries |
| Results | `calibration_parameters.json` | JSON | Best parameter values + metrics |
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

## 12. Troubleshooting

### Common Issues

**"file.cio not found in this folder"**
The path you entered does not contain a `file.cio`. Make sure you are pointing to the TxtInOut directory, not a parent folder.

**"No SWAT executable found in project folder"**
The app could not find a SWAT executable with a recognized name. Use the text field or Browse button to specify the path manually.

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

**Calibration results are poor (low NSE, high PBIAS)**
- Check observation data units and date alignment
- Start with a small set of parameters (the Recommended 4)
- Use the Diagnostics tab to identify specific model deficiencies
- Increase the number of iterations
- Ensure the warmup period is adequate (at least 1 year)

---

## 13. Performance Rating Guide

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
