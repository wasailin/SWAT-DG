"""
Hydrograph visualization for SWAT model outputs.

Provides time series plots comparing observed and simulated values.
"""

from typing import Optional, Union, List, Tuple
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime


def plot_hydrograph(
    dates: Union[pd.DatetimeIndex, List[datetime], np.ndarray],
    observed: np.ndarray,
    simulated: np.ndarray,
    title: str = "Hydrograph Comparison",
    xlabel: str = "Date",
    ylabel: str = "Flow (m³/s)",
    obs_label: str = "Observed",
    sim_label: str = "Simulated",
    obs_color: str = "blue",
    sim_color: str = "red",
    figsize: Tuple[int, int] = (14, 6),
    show_legend: bool = True,
    show_grid: bool = True,
    alpha_sim: float = 0.7,
    linewidth: float = 1.0,
    save_path: Optional[str] = None,
    dpi: int = 150,
    ax: Optional[plt.Axes] = None,
) -> plt.Figure:
    """
    Create a hydrograph plot comparing observed and simulated time series.

    Args:
        dates: Date/time values for x-axis
        observed: Observed values
        simulated: Simulated values
        title: Plot title
        xlabel: X-axis label
        ylabel: Y-axis label
        obs_label: Legend label for observed data
        sim_label: Legend label for simulated data
        obs_color: Color for observed line
        sim_color: Color for simulated line
        figsize: Figure size (width, height)
        show_legend: Whether to show legend
        show_grid: Whether to show grid
        alpha_sim: Transparency for simulated line
        linewidth: Line width
        save_path: Path to save figure (optional)
        dpi: Resolution for saved figure
        ax: Existing axes to plot on (optional)

    Returns:
        matplotlib Figure object
    """
    # Convert inputs to arrays
    obs = np.asarray(observed).flatten()
    sim = np.asarray(simulated).flatten()

    # Create figure if no axes provided
    if ax is None:
        fig, ax = plt.subplots(figsize=figsize)
    else:
        fig = ax.get_figure()

    # Convert dates if needed
    if isinstance(dates, pd.DatetimeIndex):
        dates = dates.to_pydatetime()
    dates = np.asarray(dates)

    # Ensure same length
    min_len = min(len(dates), len(obs), len(sim))
    dates = dates[:min_len]
    obs = obs[:min_len]
    sim = sim[:min_len]

    # Plot data
    ax.plot(dates, obs, color=obs_color, label=obs_label, linewidth=linewidth)
    ax.plot(dates, sim, color=sim_color, label=sim_label,
            linewidth=linewidth, alpha=alpha_sim)

    # Formatting
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.set_title(title)

    if show_legend:
        ax.legend(loc="upper right")

    if show_grid:
        ax.grid(True, alpha=0.3)

    # Date formatting
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
    ax.xaxis.set_major_locator(mdates.AutoDateLocator())
    fig.autofmt_xdate()

    plt.tight_layout()

    # Save if path provided
    if save_path:
        fig.savefig(save_path, dpi=dpi, bbox_inches="tight")

    return fig


def plot_hydrograph_monthly(
    observed: pd.Series,
    simulated: pd.Series,
    title: str = "Monthly Hydrograph Comparison",
    ylabel: str = "Flow (m³/s)",
    figsize: Tuple[int, int] = (14, 6),
    save_path: Optional[str] = None,
) -> plt.Figure:
    """
    Create a monthly aggregated hydrograph plot.

    Args:
        observed: Observed values with datetime index
        simulated: Simulated values with datetime index
        title: Plot title
        ylabel: Y-axis label
        figsize: Figure size
        save_path: Path to save figure (optional)

    Returns:
        matplotlib Figure object
    """
    # Resample to monthly
    obs_monthly = observed.resample('M').mean()
    sim_monthly = simulated.resample('M').mean()

    # Align indices
    common_idx = obs_monthly.index.intersection(sim_monthly.index)
    obs_monthly = obs_monthly.loc[common_idx]
    sim_monthly = sim_monthly.loc[common_idx]

    return plot_hydrograph(
        dates=common_idx,
        observed=obs_monthly.values,
        simulated=sim_monthly.values,
        title=title,
        ylabel=ylabel,
        figsize=figsize,
        save_path=save_path,
    )


def plot_hydrograph_with_precipitation(
    dates: Union[pd.DatetimeIndex, List[datetime]],
    observed: np.ndarray,
    simulated: np.ndarray,
    precipitation: np.ndarray,
    title: str = "Hydrograph with Precipitation",
    flow_ylabel: str = "Flow (m³/s)",
    precip_ylabel: str = "Precipitation (mm)",
    figsize: Tuple[int, int] = (14, 8),
    save_path: Optional[str] = None,
) -> plt.Figure:
    """
    Create a hydrograph plot with precipitation bars on secondary axis.

    Args:
        dates: Date/time values
        observed: Observed flow values
        simulated: Simulated flow values
        precipitation: Precipitation values
        title: Plot title
        flow_ylabel: Y-axis label for flow
        precip_ylabel: Y-axis label for precipitation
        figsize: Figure size
        save_path: Path to save figure

    Returns:
        matplotlib Figure object
    """
    fig, ax1 = plt.subplots(figsize=figsize)

    # Flow data on primary axis
    ax1.plot(dates, observed, color='blue', label='Observed', linewidth=1)
    ax1.plot(dates, simulated, color='red', label='Simulated', linewidth=1, alpha=0.7)
    ax1.set_xlabel('Date')
    ax1.set_ylabel(flow_ylabel, color='blue')
    ax1.tick_params(axis='y', labelcolor='blue')
    ax1.legend(loc='upper left')
    ax1.grid(True, alpha=0.3)

    # Precipitation on secondary axis (inverted)
    ax2 = ax1.twinx()
    ax2.bar(dates, precipitation, color='gray', alpha=0.5, label='Precipitation', width=1)
    ax2.set_ylabel(precip_ylabel, color='gray')
    ax2.tick_params(axis='y', labelcolor='gray')
    ax2.invert_yaxis()  # Precipitation from top
    ax2.set_ylim(ax2.get_ylim()[0], 0)
    ax2.legend(loc='upper right')

    ax1.set_title(title)

    # Date formatting
    ax1.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
    fig.autofmt_xdate()

    plt.tight_layout()

    if save_path:
        fig.savefig(save_path, dpi=150, bbox_inches="tight")

    return fig
