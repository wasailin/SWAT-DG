"""
SWAT-DG Visualization Module.

Provides unified visualization tools for SWAT model calibration and analysis:
- Hydrographs (time series plots)
- Scatter plots with 1:1 line
- Performance metrics tables
- Flow duration curves
- Dashboard for combined visualizations

Example:
    from swat_modern.visualization import plot_hydrograph, plot_scatter, MetricsTable

    # Plot time series comparison
    fig = plot_hydrograph(dates, observed, simulated, title="Streamflow Calibration")

    # Scatter plot with metrics
    fig = plot_scatter(observed, simulated, show_metrics=True)

    # Create metrics table
    table = MetricsTable(observed, simulated)
    table.display()
"""

from swat_modern.visualization.hydrograph import plot_hydrograph, plot_hydrograph_monthly
from swat_modern.visualization.scatter import plot_scatter, plot_residuals
from swat_modern.visualization.metrics_table import MetricsTable, create_metrics_dataframe
from swat_modern.visualization.duration_curve import plot_duration_curve, plot_duration_comparison
from swat_modern.visualization.dashboard import CalibrationDashboard
from swat_modern.visualization.sensitivity import (
    plot_sensitivity_tornado,
    sensitivity_ranking_table,
    get_suggested_parameters,
)
from swat_modern.visualization.diagnostics import (
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

try:
    from swat_modern.visualization.plotly_charts import (
        plotly_time_series,
        plotly_multi_variable,
        plotly_bar_summary,
        plotly_scatter_comparison,
    )
    _HAS_PLOTLY = True
except ImportError:
    _HAS_PLOTLY = False

__all__ = [
    # Hydrograph plots
    "plot_hydrograph",
    "plot_hydrograph_monthly",
    # Scatter plots
    "plot_scatter",
    "plot_residuals",
    # Metrics
    "MetricsTable",
    "create_metrics_dataframe",
    # Duration curves
    "plot_duration_curve",
    "plot_duration_comparison",
    # Dashboard
    "CalibrationDashboard",
    # Sensitivity analysis
    "plot_sensitivity_tornado",
    "sensitivity_ranking_table",
    "get_suggested_parameters",
    # Diagnostics
    "plot_baseflow_separation",
    "plot_peak_comparison",
    "plot_seasonal_bias",
    "plot_recommendations_table",
    "plot_diagnostic_dashboard",
    "plot_rating_curve",
    "plot_flow_partition",
    "plot_event_partition",
    "plot_wq_diagnostic_dashboard",
]

# Conditionally export plotly symbols only when plotly is available
if _HAS_PLOTLY:
    __all__ += [
        "plotly_time_series",
        "plotly_multi_variable",
        "plotly_bar_summary",
        "plotly_scatter_comparison",
    ]
