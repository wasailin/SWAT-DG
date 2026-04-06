# API Reference

Complete reference for SWAT-DG Python API.

## Core Module

### swat_modern.SWATModel

Main class for interacting with SWAT2012 model.

```python
from swat_modern import SWATModel
```

#### Constructor

```python
SWATModel(project_dir, executable=None)
```

**Parameters:**
- `project_dir` (str | Path): Path to directory containing SWAT input files
- `executable` (str | Path, optional): Path to SWAT executable. If not provided, searches:
  - `{project_dir}/swat2012.exe`
  - `SWAT_EXE` environment variable

**Raises:**
- `FileNotFoundError`: If project directory or executable not found
- `ValueError`: If `file.cio` not found in project directory

**Example:**
```python
model = SWATModel("C:/my_watershed", executable="C:/swat2012.exe")
```

#### Attributes

| Attribute | Type | Description |
|-----------|------|-------------|
| `project_dir` | Path | Resolved path to project directory |
| `config` | SWATConfig | Project configuration from file.cio |
| `executable` | Path | Path to SWAT executable |

#### Methods

##### run()

Execute SWAT simulation.

```python
run(timeout=None, capture_output=True) -> SimulationResult
```

**Parameters:**
- `timeout` (int, optional): Maximum seconds to wait for simulation
- `capture_output` (bool): Whether to capture stdout/stderr

**Returns:** `SimulationResult` object

**Example:**
```python
result = model.run(timeout=300)
if result.success:
    print(f"Completed in {result.runtime:.1f}s")
```

##### get_output()

Read SWAT output file and return specified variable.

```python
get_output(variable, output_type="rch", unit_id=None) -> pd.DataFrame
```

**Parameters:**
- `variable` (str): Variable name to extract (e.g., "FLOW_OUTcms")
- `output_type` (str): One of "rch", "sub", "hru", "rsv", "std"
- `unit_id` (int, optional): Filter by reach/subbasin/HRU number

**Returns:** pandas DataFrame with date index

**Example:**
```python
# Get streamflow for reach 1
flow = model.get_output("FLOW_OUTcms", output_type="rch", unit_id=1)
```

##### modify_parameter()

Modify a SWAT input parameter.

```python
modify_parameter(param_name, value, method="replace", file_type=None)
```

**Parameters:**
- `param_name` (str): Parameter name (e.g., "CN2", "ESCO")
- `value` (float): Value to apply
- `method` (str): "replace", "multiply", or "add"
- `file_type` (str, optional): File type to modify ("bsn", "mgt", "sol", etc.)

**Methods:**
- `"replace"`: Set parameter to value
- `"multiply"`: Multiply current value by (1 + value)
- `"add"`: Add value to current

**Example:**
```python
model.modify_parameter("CN2", -0.1, method="multiply")  # -10%
model.modify_parameter("ESCO", 0.85, method="replace")
```

##### backup()

Create backup of project files.

```python
backup(backup_dir=None, file_types=None) -> Path
```

**Parameters:**
- `backup_dir` (str | Path, optional): Backup location (default: auto-generated timestamp directory)
- `file_types` (List[str], optional): File extensions to back up (e.g., `["gw", "bsn", "mgt"]`). When `None`, backs up all input file types. Selective backup can reduce I/O by over 99% for large projects.

**Returns:** Path to backup directory

##### restore()

Restore project from backup.

```python
restore(backup_dir, file_types=None)
```

**Parameters:**
- `backup_dir` (str | Path): Path to backup directory
- `file_types` (List[str], optional): File extensions to restore (e.g., `["gw", "bsn"]`). When `None`, restores all files in the backup directory.

---

### swat_modern.core.SimulationResult

Container for simulation results.

```python
from swat_modern.core import SimulationResult
```

#### Attributes

| Attribute | Type | Description |
|-----------|------|-------------|
| `success` | bool | Whether simulation completed successfully |
| `runtime` | float | Execution time in seconds |
| `return_code` | int | Process return code |
| `stdout` | str | Standard output text |
| `stderr` | str | Standard error text |
| `output_files` | List[Path] | Paths to output files created |
| `error` | str | Error message if failed |

---

### swat_modern.core.SWATConfig

Configuration parser for file.cio.

```python
from swat_modern.core import SWATConfig
```

#### Attributes

| Attribute | Type | Description |
|-----------|------|-------------|
| `period` | SimulationPeriod | Simulation period settings |
| `period.start_year` | int | Start year of simulation |
| `period.end_year` | int | End year of simulation |
| `period.warmup_years` | int | Number of warmup (skip) years (NYSKIP) |
| `period.start_date` | date | Simulation start date (derived from start_year + IDAF) |
| `period.end_date` | date | Simulation end date (derived from end_year + IDAL) |
| `output` | OutputSettings | Output file configuration |
| `output.daily` | bool | Daily output enabled |
| `output.monthly` | bool | Monthly output enabled |
| `output.yearly` | bool | Yearly output enabled |

---

## Calibration Module

### swat_modern.calibration.Calibrator

High-level calibration interface.

```python
from swat_modern.calibration import Calibrator
```

#### Constructor

```python
Calibrator(
    model,
    observed_data,
    parameters=None,
    output_variable="FLOW_OUT",
    output_type="rch",
    reach_id=1,
    objective="nse",
    warmup_years=1
)
```

**Parameters:**
- `model` (SWATModel): SWAT model instance
- `observed_data` (str | DataFrame | Series): Observed data (CSV path or DataFrame)
- `parameters` (List[str], optional): Parameter names to calibrate (default: streamflow parameters)
- `output_variable` (str): SWAT output variable name
- `output_type` (str): Output file type ("rch", "sub", "hru")
- `reach_id` (int): Reach/subbasin/HRU ID to extract output from
- `objective` (str): Objective function ("nse", "kge", "pbias", "log_nse")
- `warmup_years` (int): Number of initial simulation years to exclude from calibration (default: 1)

#### Methods

##### auto_calibrate()

Run automatic calibration.

```python
auto_calibrate(n_iterations=5000, algorithm="sceua", parallel=False, n_cores=None, **kwargs) -> CalibrationResult
```

**Parameters:**
- `n_iterations` (int): Number of model evaluations
- `algorithm` (str): Optimization algorithm
- `parallel` (bool): Enable parallel processing across CPU cores (default: False)
- `n_cores` (int, optional): Number of CPU cores for parallel mode (default: all available)
- `**kwargs`: Additional algorithm-specific options

**Algorithms:**
| Algorithm | Description |
|-----------|-------------|
| `"sceua"` | Shuffled Complex Evolution (recommended) |
| `"dream"` | Differential Evolution Adaptive Metropolis |
| `"mc"` | Monte Carlo sampling |
| `"lhs"` | Latin Hypercube Sampling |
| `"rope"` | Robust Parameter Estimation |
| `"demcz"` | DE-MCZ algorithm |
| `"fast"` | FAST sensitivity sampler |
| `"abc"` | Approximate Bayesian Computation |

**Returns:** `CalibrationResult` object

##### sensitivity_analysis()

Perform sensitivity analysis.

```python
sensitivity_analysis(n_samples=1000, method="fast", parallel=False, n_cores=None) -> SensitivityResult
```

**Parameters:**
- `n_samples` (int): Number of samples per parameter
- `method` (str): "fast" (recommended) or "sobol"
- `parallel` (bool): Enable parallel SWAT runs across CPU cores (default: False)
- `n_cores` (int, optional): Number of CPU cores for parallel mode (default: all available)

**Returns:** `SensitivityResult` object with sensitivity indices and best parameter set found

##### diagnostic_calibrate()

Run diagnostic-guided calibration in 5–20 SWAT runs.

```python
diagnostic_calibrate(n_iterations=15, algorithm="sceua") -> CalibrationResult
```

Analyzes hydrograph deficiencies (volume bias, baseflow partition, peak magnitude) and adjusts parameters intelligently rather than sampling parameter space blindly. Converges in 5–20 runs vs. 5,000+ for standard algorithms.

**Parameters:**
- `n_iterations` (int): Maximum number of SWAT runs (default: 15)
- `algorithm` (str): Reserved for future use; always uses the diagnostic engine

**Returns:** `CalibrationResult` with best parameters and performance metrics

##### ensemble_diagnostic_calibrate()

Run ensemble parallel diagnostic calibration (multi-start).

```python
ensemble_diagnostic_calibrate(n_ensemble=4, n_iterations=15) -> CalibrationResult
```

Launches `n_ensemble` independent DiagnosticCalibrators with diverse configurations in parallel, then returns the best result. Achieves better solution quality than a single diagnostic run in the same wall-clock time.

**Parameters:**
- `n_ensemble` (int): Number of parallel workers (default: 4)
- `n_iterations` (int): Maximum SWAT runs per worker (default: 15)

**Returns:** `CalibrationResult` with best parameters across all ensemble members

##### phased_calibrate()

Run phased multi-constituent calibration (Flow → Sediment → Nutrients).

```python
phased_calibrate(phases=["hydrology", "sediment", "nutrients"]) -> PhasedCalibrationResult
```

Calibrates constituents in sequence: streamflow first, then sediment, then nitrogen and phosphorus. Each phase locks in the previous phase's optimal parameters before proceeding.

**Parameters:**
- `phases` (List[str] | List[PhaseConfig], optional): Phase sequence. Default: Flow → Sediment → Nitrogen → Phosphorus (auto-enabled based on available observation data)

**Returns:** `PhasedCalibrationResult` with per-phase results and merged best parameter set

##### manual_run()

Run single simulation with specified parameters.

```python
manual_run(parameters) -> pd.DataFrame
```

**Parameters:**
- `parameters` (dict): Parameter name-value pairs

**Returns:** DataFrame of simulation results

---

### swat_modern.calibration.CalibrationResult

Container for calibration results.

```python
from swat_modern.calibration import CalibrationResult
```

#### Attributes

| Attribute | Type | Description |
|-----------|------|-------------|
| `best_parameters` | dict | Optimal parameter values |
| `best_objective` | float | Best objective function value |
| `all_parameters` | DataFrame | All parameter sets tried |
| `all_objectives` | ndarray | All objective values |
| `observed` | ndarray | Observed data used |
| `simulated` | ndarray | Best simulation results |
| `runtime` | float | Total calibration time (seconds) |
| `n_iterations` | int | Number of evaluations |
| `algorithm` | str | Algorithm used |
| `metrics` | dict | Performance metrics |

#### Methods

##### print_summary()

Print formatted summary of results.

```python
print_summary()
```

##### plot_comparison()

Plot observed vs simulated time series.

```python
plot_comparison(figsize=(12, 6), title=None)
```

##### save_best_parameters()

Save optimal parameters to JSON file.

```python
save_best_parameters(filepath)
```

---

### swat_modern.calibration.SensitivityResult

Container for sensitivity analysis results.

```python
from swat_modern.calibration import SensitivityResult
```

#### Attributes

| Attribute | Type | Description |
|-----------|------|-------------|
| `sensitivity` | dict | Sensitivity indices `{param: S1}` for FAST, or DataFrame with 'Parameter' and 'S1' columns for Sobol |
| `best_parameters` | dict | Best-performing parameter set found during SA |
| `best_objective` | float | Best objective function value found |
| `n_evaluations` | int | Total number of model evaluations |
| `runtime` | float | Total runtime in seconds |
| `method` | str | SA method used ("fast" or "sobol") |

---

### swat_modern.calibration.CalibrationParameter

Parameter definition for calibration.

```python
from swat_modern.calibration import CalibrationParameter
```

#### Constructor

```python
CalibrationParameter(
    name,
    min_value,
    max_value,
    file_type="mgt",
    description="",
    method="multiply",
    default=0.0
)
```

**Parameters:**
- `name` (str): Parameter name
- `min_value` (float): Minimum bound
- `max_value` (float): Maximum bound
- `file_type` (str): SWAT file type
- `description` (str): Parameter description
- `method` (str): Modification method
- `default` (float): Default value

---

### Objective Functions

```python
from swat_modern.calibration.objectives import nse, kge, pbias, rmse, mae, r_squared, log_nse
```

All functions have signature: `func(observed, simulated) -> float`

#### nse()

Nash-Sutcliffe Efficiency.

```python
nse(observed, simulated) -> float
```

Range: -inf to 1 (1 = perfect)

#### kge()

Kling-Gupta Efficiency.

```python
kge(observed, simulated) -> float
```

Range: -inf to 1 (1 = perfect)

#### pbias()

Percent Bias.

```python
pbias(observed, simulated) -> float
```

Range: -inf to +inf (0 = perfect)

#### rmse()

Root Mean Square Error.

```python
rmse(observed, simulated) -> float
```

Range: 0 to +inf (0 = perfect)

#### mae()

Mean Absolute Error.

```python
mae(observed, simulated) -> float
```

Range: 0 to +inf (0 = perfect)

#### r_squared()

Coefficient of Determination (R²).

```python
r_squared(observed, simulated) -> float
```

Range: 0 to 1 (1 = perfect)

#### log_nse()

NSE of log-transformed values.

```python
log_nse(observed, simulated, epsilon=0.01) -> float
```

Useful for low-flow evaluation.

#### evaluate_model()

Calculate multiple metrics at once.

```python
evaluate_model(observed, simulated) -> dict
```

**Returns:** Dictionary with all metrics

```python
metrics = evaluate_model(obs, sim)
# {'nse': 0.85, 'kge': 0.78, 'pbias': 5.2, 'rmse': 10.5, ...}
```

---

## Data Module

### swat_modern.data.WeatherDataFetcher

Weather data retrieval and SWAT file generation.

```python
from swat_modern.data import WeatherDataFetcher
```

#### Class Methods

##### from_csv()

Load weather data from CSV file.

```python
WeatherDataFetcher.from_csv(
    filepath,
    station_name,
    latitude,
    longitude,
    date_col="date",
    precip_col="precip",
    tmax_col="tmax",
    tmin_col="tmin"
) -> WeatherDataFetcher
```

#### Instance Methods

##### to_swat_files()

Generate SWAT weather input files.

```python
to_swat_files(output_dir) -> dict
```

**Returns:** Dictionary of file paths created

---

### swat_modern.data.SoilDataFetcher

Soil data processing.

```python
from swat_modern.data import SoilDataFetcher
```

#### Class Methods

##### create_default_profile()

Create default soil profile by texture.

```python
SoilDataFetcher.create_default_profile(
    texture="loam",
    depth_cm=150,
    n_layers=3
) -> SoilDataFetcher
```

#### Instance Methods

##### to_swat_file()

Generate SWAT .sol file.

```python
to_swat_file(filepath)
```

---

### swat_modern.data.DEMProcessor

DEM processing and watershed delineation.

```python
from swat_modern.data import DEMProcessor
```

#### Class Methods

##### from_file()

Load DEM from GeoTIFF file.

```python
DEMProcessor.from_file(filepath) -> DEMProcessor
```

##### from_array()

Create from numpy array.

```python
DEMProcessor.from_array(data, transform, crs=None) -> DEMProcessor
```

#### Instance Methods

##### fill_sinks()

Fill depressions in DEM.

```python
fill_sinks() -> np.ndarray
```

##### compute_flow_direction()

Calculate D8 flow direction.

```python
compute_flow_direction() -> np.ndarray
```

##### compute_flow_accumulation()

Calculate flow accumulation.

```python
compute_flow_accumulation() -> np.ndarray
```

##### delineate_watershed()

Delineate watershed from outlet point.

```python
delineate_watershed(outlet) -> np.ndarray
```

**Parameters:**
- `outlet` (tuple): (x, y) coordinates or (row, col) indices

##### extract_streams()

Extract stream network.

```python
extract_streams(threshold=1000) -> np.ndarray
```

**Parameters:**
- `threshold` (int): Flow accumulation threshold

---

### swat_modern.data.LandCoverProcessor

Land cover processing for SWAT.

```python
from swat_modern.data import LandCoverProcessor
```

#### Class Methods

##### from_file()

Load land cover raster.

```python
LandCoverProcessor.from_file(filepath) -> LandCoverProcessor
```

#### Instance Methods

##### to_swat_codes()

Convert NLCD codes to SWAT land use codes.

```python
to_swat_codes() -> np.ndarray
```

##### get_curve_numbers()

Get curve numbers by soil hydrologic group.

```python
get_curve_numbers(soil_group) -> np.ndarray
```

**Parameters:**
- `soil_group` (str): "A", "B", "C", or "D"

---

## Calibration Parameters Reference

### Pre-defined Parameter Groups

```python
from swat_modern.calibration.parameters import (
    get_streamflow_parameters,
    get_sediment_parameters,
    get_nutrient_parameters,
    get_all_parameters,
)
```

### Streamflow Parameters

| Name | Description | Range | Method |
|------|-------------|-------|--------|
| CN2 | Curve Number | -0.25 to 0.25 | multiply |
| ESCO | Soil evaporation compensation | 0.01 to 1.0 | replace |
| EPCO | Plant uptake compensation | 0.01 to 1.0 | replace |
| GW_DELAY | Groundwater delay (days) | 0 to 500 | replace |
| ALPHA_BF | Baseflow alpha factor | 0 to 1.0 | replace |
| ALPHA_BF_D | Baseflow alpha factor for deep aquifer | 0 to 1.0 | replace |
| GWQMN | Threshold for return flow (mm) | 0 to 5000 | replace |
| GW_REVAP | Groundwater "revap" coefficient | 0.02 to 0.2 | replace |
| REVAPMN | Threshold for "revap" (mm) | 0 to 1000 | replace |
| RCHRG_DP | Deep aquifer percolation fraction | 0 to 1.0 | replace |
| SURLAG | Surface runoff lag coefficient | 0.05 to 24 | replace |
| SOL_AWC | Soil available water capacity | -0.5 to 0.5 | multiply |
| SOL_K | Soil hydraulic conductivity | -0.8 to 0.8 | multiply |
| SOL_BD | Soil bulk density | -0.5 to 0.6 | multiply |
| CH_N2 | Manning's n for channel | 0 to 0.3 | replace |
| CH_K2 | Channel hydraulic conductivity | 0 to 500 | replace |
| OV_N | Manning's n for overland flow | 0.01 to 0.5 | replace |
| CANMX | Maximum canopy storage (mm) | 0 to 100 | replace |

### Sediment Parameters

| Name | Description | Range | Method |
|------|-------------|-------|--------|
| USLE_P | USLE support practice factor | 0 to 1.0 | replace |
| USLE_K | USLE soil erodibility factor | -0.5 to 0.5 | multiply |
| SPCON | Sediment transport coefficient | 0.0001 to 0.01 | replace |
| SPEXP | Sediment transport exponent | 1.0 to 2.0 | replace |
| CH_COV1 | Channel cover factor | 0 to 1.0 | replace |
| CH_COV2 | Channel erodibility factor | 0 to 1.0 | replace |

### Nutrient Parameters

| Name | Description | Range | Method |
|------|-------------|-------|--------|
| NPERCO | Nitrogen percolation coefficient | 0 to 1.0 | replace |
| PPERCO | Phosphorus percolation coefficient | 10 to 17.5 | replace |
| CMN | Humus mineralization rate | 0.001 to 0.003 | replace |
| PSP | Phosphorus sorption coefficient | 0.01 to 0.7 | replace |
| N_UPDIS | Nitrogen uptake distribution | 0 to 100 | replace |
| P_UPDIS | Phosphorus uptake distribution | 0 to 100 | replace |
| ERORGN | Organic N enrichment ratio | 0 to 5 | replace |
| ERORGP | Organic P enrichment ratio | 0 to 5 | replace |

---

## Output File Reference

### output.rch Variables

| Variable | Description | Units |
|----------|-------------|-------|
| FLOW_INcms | Inflow | m³/s |
| FLOW_OUTcms | Outflow | m³/s |
| EVAPcms | Evaporation | m³/s |
| SED_INtons | Sediment in | tons |
| SED_OUTtons | Sediment out | tons |
| NO3_INkg | Nitrate in | kg |
| NO3_OUTkg | Nitrate out | kg |
| ORGN_INkg | Organic N in | kg |
| ORGN_OUTkg | Organic N out | kg |
| SOLP_INkg | Soluble P in | kg |
| SOLP_OUTkg | Soluble P out | kg |

### output.sub Variables

| Variable | Description | Units |
|----------|-------------|-------|
| PRECIPmm | Precipitation | mm |
| SNOMELTmm | Snowmelt | mm |
| PETmm | Potential ET | mm |
| ETmm | Actual ET | mm |
| SWmm | Soil water | mm |
| PERCmm | Percolation | mm |
| SURQmm | Surface runoff | mm |
| GW_Qmm | Groundwater flow | mm |
| WYLDmm | Water yield | mm |
| SYLDt/ha | Sediment yield | t/ha |

### output.hru Variables

Similar to output.sub but at HRU level.

---

## See Also

- [Installation Guide](installation.md)
- [Quick Start Guide](quickstart.md)
- Example notebooks in `examples/` folder
