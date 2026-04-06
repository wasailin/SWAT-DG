"""
SWAT-DG - Python wrapper and automation tools for SWAT2012 hydrological model.

This package provides:
- Python wrapper to run SWAT2012 simulations
- Input/output file parsers and generators (output.rch, output.sub, output.hru, .bsn, .sol, .mgt)
- Calibration tools using SPOTPY (8+ algorithms, 45 parameters)
- Data automation pipelines for US watersheds (weather, soil, land cover, DEM)
- Visualization dashboard for calibration results
- Streamlit web app for user-friendly calibration

Example usage:
    from swat_modern import SWATModel

    # Load a SWAT project
    model = SWATModel("path/to/project")

    # Run simulation
    result = model.run()

    # Get output data
    streamflow = model.get_output("FLOW_OUT", output_type="rch")

Calibration example:
    from swat_modern import SWATModel
    from swat_modern.calibration import Calibrator

    model = SWATModel("path/to/project")
    calibrator = Calibrator(model, observed_data="streamflow.csv")
    results = calibrator.auto_calibrate()
    results.print_summary()

Visualization example:
    from swat_modern.visualization import CalibrationDashboard

    dashboard = CalibrationDashboard(dates, observed, simulated)
    dashboard.create_dashboard()
    dashboard.save("calibration_report.png")

Launch Streamlit app:
    streamlit run src/swat_modern/app/main.py
    # Or from Python:
    from swat_modern.app import run_app
    run_app()
"""

__version__ = "0.5.0"

from swat_modern.core.model import SWATModel
from swat_modern.core.config import SWATConfig
from swat_modern.core.results import SimulationResult

# Lazy import for calibration (requires spotpy) and visualization
def __getattr__(name):
    if name == "Calibrator":
        from swat_modern.calibration.calibrator import Calibrator
        return Calibrator
    if name == "visualization":
        from swat_modern import visualization
        return visualization
    if name == "spatial":
        from swat_modern import spatial
        return spatial
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    "SWATModel",
    "SWATConfig",
    "SimulationResult",
    "Calibrator",
    "visualization",
    "spatial",
    "__version__",
]
