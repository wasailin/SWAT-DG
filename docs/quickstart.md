# Quick Start Guide

Get started with SWAT-DG in 5 minutes.

## Prerequisites

1. Python 3.10+ installed
2. A SWAT2012 project directory with input files
3. SWAT2012 executable (see [Installation Guide](installation.md))

## Step 1: Install SWAT-DG

```bash
pip install swat-dg[calibration]
```

## Step 2: Load a SWAT Project

```python
from swat_modern import SWATModel

# Load your SWAT project
model = SWATModel(
    project_dir="C:/my_watershed",
    executable="C:/swat2012.exe"
)

print(f"Project: {model.project_dir}")
```

## Step 3: Run a Simulation

```python
# Run SWAT
result = model.run()

if result.success:
    print(f"Simulation completed in {result.runtime:.1f} seconds")
else:
    print(f"Simulation failed: {result.error}")
```

## Step 4: Read Results

```python
# Get streamflow from reach 1
flow = model.get_output(
    variable="FLOW_OUTcms",
    output_type="rch",
    unit_id=1
)

print(flow.head())
#              date  FLOW_OUTcms
# 0      2010-01-01        5.234
# 1      2010-01-02        4.891
# ...
```

### Available Output Types

| Output Type | File | Description |
|-------------|------|-------------|
| `"rch"` | output.rch | Reach/channel outputs (46 variables) |
| `"sub"` | output.sub | Subbasin outputs (24 variables) |
| `"hru"` | output.hru | HRU outputs (79 variables) |
| `"rsv"` | output.rsv | Reservoir outputs |
| `"std"` | output.std | Standard summary |

### Common Variables

- `FLOW_OUTcms` - Streamflow (m³/s)
- `SED_OUTtons` - Sediment load (tons)
- `NO3_OUTkg` - Nitrate load (kg)
- `ORGN_OUTkg` - Organic nitrogen (kg)
- `SOLP_OUTkg` - Soluble phosphorus (kg)

## Step 5: Modify Parameters

```python
# Reduce curve number by 10%
model.modify_parameter("CN2", -0.1, method="multiply")

# Set ESCO to a specific value
model.modify_parameter("ESCO", 0.85, method="replace")

# Increase groundwater delay by 5 days
model.modify_parameter("GW_DELAY", 5, method="add")

# Run again with new parameters
result2 = model.run()
```

### Parameter Modification Methods

| Method | Effect | Example |
|--------|--------|---------|
| `"replace"` | Set to exact value | `CN2 = 75` |
| `"multiply"` | Scale by factor | `CN2 = CN2 * (1 + value)` |
| `"add"` | Add to current | `CN2 = CN2 + value` |

## Step 6: Basic Calibration

```python
from swat_modern.calibration import Calibrator

# Create calibrator with observed data
calibrator = Calibrator(
    model=model,
    observed_data="observed_flow.csv",
    parameters=["CN2", "ESCO", "GW_DELAY", "ALPHA_BF"],
    output_variable="FLOW_OUTcms",
    reach_id=1,
    objective="nse"
)

# Run automatic calibration (1000 iterations)
results = calibrator.auto_calibrate(n_iterations=1000, algorithm="sceua")

# View results
results.print_summary()
# Best NSE: 0.78
# Best parameters:
#   CN2: -0.08
#   ESCO: 0.72
#   GW_DELAY: 45.3
#   ALPHA_BF: 0.12
```

### Available Algorithms

| Algorithm | Description | Use Case |
|-----------|-------------|----------|
| `"sceua"` | Shuffled Complex Evolution | General calibration (recommended) |
| `"dream"` | Differential Evolution Adaptive Metropolis | Uncertainty analysis |
| `"mc"` | Monte Carlo | Sensitivity exploration |
| `"lhs"` | Latin Hypercube Sampling | Parameter space sampling |

### Available Objective Functions

| Function | Description | Ideal Value |
|----------|-------------|-------------|
| `"nse"` | Nash-Sutcliffe Efficiency | 1.0 |
| `"kge"` | Kling-Gupta Efficiency | 1.0 |
| `"pbias"` | Percent Bias | 0.0 |
| `"rmse"` | Root Mean Square Error | 0.0 |

## Step 7: Visualize Results

```python
# Plot observed vs simulated
results.plot_comparison()

# Save calibrated parameters
results.save_best_parameters("best_params.json")
```

## Step 8: Backup and Restore

```python
# Create backup before modifications
backup_dir = model.backup()
print(f"Backup saved to: {backup_dir}")

# Make changes...
model.modify_parameter("CN2", -0.2, method="multiply")
model.run()

# Restore original state
model.restore(backup_dir)
print("Project restored to original state")
```

## Next Steps

- See `examples/01_getting_started.ipynb` for more detailed examples
- See `examples/02_calibration.ipynb` for advanced calibration
- See `examples/03_weather_data.ipynb` for weather data automation
- See [API Reference](api_reference.md) for complete documentation

## Quick Reference

```python
from swat_modern import SWATModel
from swat_modern.calibration import Calibrator
from swat_modern.calibration.objectives import nse, kge, pbias, evaluate_model
from swat_modern.data import WeatherDataFetcher, SoilDataFetcher, DEMProcessor

# Load model
model = SWATModel("project_dir", executable="swat.exe")

# Run simulation
result = model.run(timeout=300)

# Get output
flow = model.get_output("FLOW_OUTcms", "rch", 1)

# Modify parameter
model.modify_parameter("CN2", -0.1, method="multiply")

# Calibrate
calibrator = Calibrator(model, "observed.csv", ["CN2", "ESCO"])
results = calibrator.auto_calibrate(n_iterations=5000)

# Calculate metrics
metrics = evaluate_model(observed, simulated)
print(f"NSE={metrics['nse']:.3f}, KGE={metrics['kge']:.3f}")
```
