"""
Flow Duration Curve visualization for SWAT model analysis.

Flow duration curves show the percentage of time that flow is equal to or exceeds
a given value, useful for understanding flow regime characteristics.
"""

from typing import Optional, Tuple, List
import numpy as np
import matplotlib.pyplot as plt


def calculate_exceedance_probability(values: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """
    Calculate exceedance probabilities for a dataset.

    Args:
        values: Flow or other values to analyze

    Returns:
        Tuple of (sorted_values, exceedance_probabilities)
    """
    # Remove NaN values
    values = np.asarray(values).flatten()
    values = values[~np.isnan(values)]

    # Sort in descending order
    sorted_values = np.sort(values)[::-1]

    # Calculate exceedance probability using Weibull plotting position
    n = len(sorted_values)
    exceedance_prob = (np.arange(1, n + 1)) / (n + 1) * 100

    return sorted_values, exceedance_prob


def plot_duration_curve(
    values: np.ndarray,
    title: str = "Flow Duration Curve",
    xlabel: str = "Exceedance Probability (%)",
    ylabel: str = "Flow (m³/s)",
    label: str = None,
    color: str = "blue",
    log_scale: bool = True,
    figsize: Tuple[int, int] = (10, 6),
    show_percentiles: bool = True,
    save_path: Optional[str] = None,
    ax: Optional[plt.Axes] = None,
) -> plt.Figure:
    """
    Create a flow duration curve plot.

    Args:
        values: Flow values
        title: Plot title
        xlabel: X-axis label
        ylabel: Y-axis label
        label: Legend label
        color: Line color
        log_scale: Use log scale for y-axis
        figsize: Figure size
        show_percentiles: Show key percentile annotations
        save_path: Path to save figure
        ax: Existing axes to plot on

    Returns:
        matplotlib Figure object
    """
    # Calculate exceedance probabilities
    sorted_values, exceedance_prob = calculate_exceedance_probability(values)

    # Create figure if needed
    if ax is None:
        fig, ax = plt.subplots(figsize=figsize)
    else:
        fig = ax.get_figure()

    # Plot duration curve
    ax.plot(exceedance_prob, sorted_values, color=color, linewidth=1.5, label=label)

    # Log scale
    if log_scale and np.min(sorted_values[sorted_values > 0]) > 0:
        ax.set_yscale('log')

    # Percentile annotations
    if show_percentiles:
        percentiles = [10, 50, 90]
        for p in percentiles:
            idx = np.argmin(np.abs(exceedance_prob - p))
            value = sorted_values[idx]
            ax.axhline(y=value, color='gray', linestyle=':', alpha=0.5)
            ax.axvline(x=p, color='gray', linestyle=':', alpha=0.5)
            ax.annotate(
                f'Q{p}={value:.1f}',
                xy=(p, value),
                xytext=(p + 5, value),
                fontsize=8,
                alpha=0.7,
            )

    # Formatting
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    ax.set_xlim(0, 100)
    ax.grid(True, alpha=0.3)

    if label:
        ax.legend()

    plt.tight_layout()

    if save_path:
        fig.savefig(save_path, dpi=150, bbox_inches="tight")

    return fig


def plot_duration_comparison(
    observed: np.ndarray,
    simulated: np.ndarray,
    title: str = "Flow Duration Curve Comparison",
    xlabel: str = "Exceedance Probability (%)",
    ylabel: str = "Flow (m³/s)",
    obs_label: str = "Observed",
    sim_label: str = "Simulated",
    obs_color: str = "blue",
    sim_color: str = "red",
    log_scale: bool = True,
    figsize: Tuple[int, int] = (10, 6),
    show_difference: bool = True,
    save_path: Optional[str] = None,
) -> plt.Figure:
    """
    Create a comparison of observed and simulated flow duration curves.

    Args:
        observed: Observed flow values
        simulated: Simulated flow values
        title: Plot title
        xlabel: X-axis label
        ylabel: Y-axis label
        obs_label: Label for observed data
        sim_label: Label for simulated data
        obs_color: Color for observed line
        sim_color: Color for simulated line
        log_scale: Use log scale for y-axis
        figsize: Figure size
        show_difference: Show difference plot below
        save_path: Path to save figure

    Returns:
        matplotlib Figure object
    """
    # Calculate exceedance probabilities
    obs_sorted, obs_prob = calculate_exceedance_probability(observed)
    sim_sorted, sim_prob = calculate_exceedance_probability(simulated)

    if show_difference:
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(figsize[0], figsize[1] * 1.5),
                                        gridspec_kw={'height_ratios': [3, 1]})
    else:
        fig, ax1 = plt.subplots(figsize=figsize)

    # Main duration curves
    ax1.plot(obs_prob, obs_sorted, color=obs_color, linewidth=1.5, label=obs_label)
    ax1.plot(sim_prob, sim_sorted, color=sim_color, linewidth=1.5,
             label=sim_label, alpha=0.8)

    if log_scale:
        min_val = min(
            np.min(obs_sorted[obs_sorted > 0]) if np.any(obs_sorted > 0) else 1,
            np.min(sim_sorted[sim_sorted > 0]) if np.any(sim_sorted > 0) else 1
        )
        if min_val > 0:
            ax1.set_yscale('log')

    ax1.set_xlabel(xlabel)
    ax1.set_ylabel(ylabel)
    ax1.set_title(title)
    ax1.set_xlim(0, 100)
    ax1.grid(True, alpha=0.3)
    ax1.legend()

    # Difference plot
    if show_difference:
        # Interpolate to common probabilities for difference calculation
        common_prob = np.linspace(1, 99, 100)
        obs_interp = np.interp(common_prob, obs_prob, obs_sorted)
        sim_interp = np.interp(common_prob, sim_prob, sim_sorted)
        diff_pct = np.where(
            obs_interp > 0,
            (sim_interp - obs_interp) / obs_interp * 100,
            0.0,
        )

        ax2.fill_between(common_prob, diff_pct, 0,
                         where=diff_pct >= 0, color='red', alpha=0.3, label='Overestimate')
        ax2.fill_between(common_prob, diff_pct, 0,
                         where=diff_pct < 0, color='blue', alpha=0.3, label='Underestimate')
        ax2.axhline(y=0, color='black', linewidth=0.5)
        ax2.set_xlabel(xlabel)
        ax2.set_ylabel('Difference (%)')
        ax2.set_xlim(0, 100)
        ax2.set_ylim(-100, 100)
        ax2.grid(True, alpha=0.3)
        ax2.legend(loc='upper right', fontsize=8)

    plt.tight_layout()

    if save_path:
        fig.savefig(save_path, dpi=150, bbox_inches="tight")

    return fig


def calculate_fdc_metrics(
    observed: np.ndarray,
    simulated: np.ndarray,
) -> dict:
    """
    Calculate flow duration curve comparison metrics.

    Args:
        observed: Observed flow values
        simulated: Simulated flow values

    Returns:
        Dictionary of FDC metrics
    """
    obs_sorted, obs_prob = calculate_exceedance_probability(observed)
    sim_sorted, sim_prob = calculate_exceedance_probability(simulated)

    # Interpolate to common probabilities
    common_prob = np.linspace(1, 99, 99)
    obs_interp = np.interp(common_prob, obs_prob, obs_sorted)
    sim_interp = np.interp(common_prob, sim_prob, sim_sorted)

    # Key percentile flows
    percentiles = [5, 10, 25, 50, 75, 90, 95]
    metrics = {}

    for p in percentiles:
        idx = np.argmin(np.abs(common_prob - p))
        metrics[f'Q{p}_obs'] = obs_interp[idx]
        metrics[f'Q{p}_sim'] = sim_interp[idx]
        metrics[f'Q{p}_diff_pct'] = (
            (sim_interp[idx] - obs_interp[idx]) / obs_interp[idx] * 100
            if obs_interp[idx] != 0 else 0.0
        )

    # Overall bias (guard against zero observed)
    safe_obs = np.where(obs_interp != 0, obs_interp, np.nan)
    metrics['mean_diff_pct'] = float(np.nanmean((sim_interp - obs_interp) / safe_obs * 100))

    # High flow bias (Q5-Q25)
    high_mask = common_prob <= 25
    obs_high = obs_interp[high_mask]
    safe_high = np.where(obs_high != 0, obs_high, np.nan)
    metrics['high_flow_bias'] = float(np.nanmean(
        (sim_interp[high_mask] - obs_high) / safe_high * 100
    ))

    # Low flow bias (Q75-Q95)
    low_mask = common_prob >= 75
    obs_low = obs_interp[low_mask]
    safe_low = np.where(obs_low != 0, obs_low, np.nan)
    metrics['low_flow_bias'] = float(np.nanmean(
        (sim_interp[low_mask] - obs_low) / safe_low * 100
    ))

    return metrics
