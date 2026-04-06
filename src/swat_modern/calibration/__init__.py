"""
SWAT Calibration Module.

This module provides tools for automated calibration of SWAT models using SPOTPY.

Main components:
- Calibrator: High-level calibration interface
- ObjectiveFunctions: NSE, KGE, PBIAS, R-squared metrics
- CalibrationParameter: Parameter definition for calibration
- SWATModelSetup: SPOTPY-compatible model setup class

Example usage:
    from swat_modern import SWATModel
    from swat_modern.calibration import Calibrator

    model = SWATModel("C:/my_watershed")
    calibrator = Calibrator(model, observed_data="streamflow.csv")
    results = calibrator.auto_calibrate()
"""

from swat_modern.calibration.objectives import (
    nse,
    kge,
    pbias,
    rmse,
    r_squared,
    log_nse,
    rsr,
    evaluate_model,
    ObjectiveFunction,
)
from swat_modern.calibration.parameters import (
    CalibrationParameter,
    CALIBRATION_PARAMETERS,
    get_default_parameters,
    ParameterSet,
    get_streamflow_parameters,
    get_sediment_parameters,
    get_nitrogen_parameters,
    get_phosphorus_parameters,
    CONSTITUENT_PHASES,
)
from swat_modern.calibration.spotpy_setup import (
    SWATModelSetup,
    MultiSiteSetup,
    SubbasinGroupSetup,
    run_baseline_simulation,
    MultiConstituentSetup,
)
from swat_modern.calibration.calibrator import Calibrator, SensitivityResult
from swat_modern.calibration.sequential import (
    SequentialCalibrator,
    SequentialCalibrationResult,
    SequentialDiagnosticCalibrator,
    SequentialDiagnosticResult,
    CalibrationStep,
)
from swat_modern.calibration.simulation_optimizer import SimulationOptimizer
from swat_modern.calibration.diagnostics import (
    diagnose,
    diagnose_sediment,
    diagnose_phosphorus,
    diagnose_nitrogen,
    DiagnosticReport,
    SedimentDiagnosticReport,
    PhosphorusDiagnosticReport,
    NitrogenDiagnosticReport,
    DiagnosticRule,
    ParameterRecommendation,
    eckhardt_baseflow_filter,
    lyne_hollick_filter,
    calculate_bfi,
    detect_peaks,
    compare_peaks,
    volume_balance,
    flow_duration_curve_metrics,
    kge_components,
    estimate_adjustment,
    DIAGNOSTIC_RULES,
    DIAGNOSTIC_THRESHOLDS,
)
from swat_modern.calibration.diagnostic_calibrator import (
    DiagnosticCalibrator,
    DiagnosticCalibrationResult,
    DiagnosticStep,
    EnsembleDiagnosticCalibrator,
    EnsembleRecipe,
)
from swat_modern.calibration.phased_calibrator import (
    PhasedCalibrator,
    PhasedCalibrationResult,
    PhaseConfig,
)
from swat_modern.calibration.load_calculator import (
    LoadCalculator,
    CONSTITUENT_TO_SWAT_VARIABLE,
)

__all__ = [
    # Objective functions
    "nse",
    "kge",
    "pbias",
    "rmse",
    "r_squared",
    "log_nse",
    "rsr",
    "evaluate_model",
    "ObjectiveFunction",
    # Parameters
    "CalibrationParameter",
    "CALIBRATION_PARAMETERS",
    "get_default_parameters",
    "ParameterSet",
    # SPOTPY integration
    "SWATModelSetup",
    "MultiSiteSetup",
    "SubbasinGroupSetup",
    "run_baseline_simulation",
    # High-level interface
    "Calibrator",
    "SensitivityResult",
    # Sequential calibration
    "SequentialCalibrator",
    "SequentialCalibrationResult",
    "SequentialDiagnosticCalibrator",
    "SequentialDiagnosticResult",
    "CalibrationStep",
    # Optimization
    "SimulationOptimizer",
    # Diagnostics
    "diagnose",
    "diagnose_sediment",
    "diagnose_phosphorus",
    "diagnose_nitrogen",
    "DiagnosticReport",
    "NitrogenDiagnosticReport",
    "SedimentDiagnosticReport",
    "PhosphorusDiagnosticReport",
    "DiagnosticRule",
    "ParameterRecommendation",
    "eckhardt_baseflow_filter",
    "lyne_hollick_filter",
    "calculate_bfi",
    "detect_peaks",
    "compare_peaks",
    "volume_balance",
    "DIAGNOSTIC_RULES",
    "DIAGNOSTIC_THRESHOLDS",
    "flow_duration_curve_metrics",
    "kge_components",
    "estimate_adjustment",
    # Diagnostic calibration
    "DiagnosticCalibrator",
    "DiagnosticCalibrationResult",
    "DiagnosticStep",
    "EnsembleDiagnosticCalibrator",
    "EnsembleRecipe",
    # Phased calibration
    "PhasedCalibrator",
    "PhasedCalibrationResult",
    "PhaseConfig",
    # Load calculation
    "LoadCalculator",
    "CONSTITUENT_TO_SWAT_VARIABLE",
    # Multi-constituent SPOTPY
    "MultiConstituentSetup",
    # Parameter functions
    "get_streamflow_parameters",
    "get_sediment_parameters",
    "get_nitrogen_parameters",
    "get_phosphorus_parameters",
    "CONSTITUENT_PHASES",
]
