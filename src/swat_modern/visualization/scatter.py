"""
Scatter plot visualization for SWAT model calibration.

Provides scatter plots with 1:1 line and performance metrics.
"""

from typing import Optional, Tuple, Dict
import numpy as np
import matplotlib.pyplot as plt
from swat_modern.calibration.objectives import evaluate_model, nse, kge, pbias, rsr


def plot_scatter(
    observed: np.ndarray,
    simulated: np.ndarray,
    title: str = "Observed vs Simulated",
    xlabel: str = "Observed",
    ylabel: str = "Simulated",
    show_metrics: bool = True,
    show_1to1: bool = True,
    show_regression: bool = False,
    figsize: Tuple[int, int] = (8, 8),
    point_color: str = "blue",
    point_alpha: float = 0.5,
    point_size: int = 20,
    save_path: Optional[str] = None,
    dpi: int = 150,
    ax: Optional[plt.Axes] = None,
) -> plt.Figure:
    """
    Create a scatter plot of observed vs simulated values.

    Args:
        observed: Observed values
        simulated: Simulated values
        title: Plot title
        xlabel: X-axis label
        ylabel: Y-axis label
        show_metrics: Display performance metrics on plot
        show_1to1: Show 1:1 reference line
        show_regression: Show regression line
        figsize: Figure size
        point_color: Scatter point color
        point_alpha: Point transparency
        point_size: Point size
        save_path: Path to save figure
        dpi: Resolution for saved figure
        ax: Existing axes to plot on

    Returns:
        matplotlib Figure object
    """
    # Convert and clean data
    obs = np.asarray(observed).flatten()
    sim = np.asarray(simulated).flatten()

    # Remove NaN values
    mask = ~(np.isnan(obs) | np.isnan(sim))
    obs = obs[mask]
    sim = sim[mask]

    # Create figure if needed
    if ax is None:
        fig, ax = plt.subplots(figsize=figsize)
    else:
        fig = ax.get_figure()

    # Scatter plot
    ax.scatter(obs, sim, c=point_color, alpha=point_alpha, s=point_size, edgecolors='none')

    # Determine axis limits
    all_vals = np.concatenate([obs, sim])
    min_val = np.min(all_vals)
    max_val = np.max(all_vals)
    padding = (max_val - min_val) * 0.05
    axis_min = max(0, min_val - padding)
    axis_max = max_val + padding

    ax.set_xlim(axis_min, axis_max)
    ax.set_ylim(axis_min, axis_max)

    # 1:1 line
    if show_1to1:
        ax.plot([axis_min, axis_max], [axis_min, axis_max], 'k--',
                linewidth=1.5, label='1:1 Line', zorder=1)

    # Regression line
    if show_regression and len(obs) > 2:
        z = np.polyfit(obs, sim, 1)
        p = np.poly1d(z)
        x_line = np.linspace(axis_min, axis_max, 100)
        ax.plot(x_line, p(x_line), 'r-', linewidth=1.5,
                label=f'Regression (y={z[0]:.2f}x+{z[1]:.2f})', alpha=0.7)

    # Performance metrics
    if show_metrics and len(obs) > 2:
        metrics = evaluate_model(obs, sim)
        metrics_text = (
            f"NSE = {metrics['nse']:.3f}\n"
            f"KGE = {metrics['kge']:.3f}\n"
            f"PBIAS = {metrics['pbias']:.1f}%\n"
            f"RSR = {metrics['rsr']:.3f}\n"
            f"R² = {metrics['r_squared']:.3f}\n"
            f"n = {len(obs)}"
        )
        ax.text(0.05, 0.95, metrics_text, transform=ax.transAxes,
                fontsize=10, verticalalignment='top',
                bbox=dict(boxstyle='round', facecolor='white', alpha=0.8))

    # Labels and formatting
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    ax.grid(True, alpha=0.3)
    ax.set_aspect('equal', adjustable='box')

    if show_1to1 or show_regression:
        ax.legend(loc='lower right')

    plt.tight_layout()

    if save_path:
        fig.savefig(save_path, dpi=dpi, bbox_inches="tight")

    return fig


def plot_residuals(
    observed: np.ndarray,
    simulated: np.ndarray,
    dates: Optional[np.ndarray] = None,
    title: str = "Residuals Analysis",
    figsize: Tuple[int, int] = (14, 8),
    save_path: Optional[str] = None,
) -> plt.Figure:
    """
    Create residual analysis plots.

    Includes:
    - Residuals over time (or index)
    - Residuals distribution histogram
    - Residuals vs observed (heteroscedasticity check)

    Args:
        observed: Observed values
        simulated: Simulated values
        dates: Optional date values for x-axis
        title: Plot title
        figsize: Figure size
        save_path: Path to save figure

    Returns:
        matplotlib Figure object
    """
    # Clean data
    obs = np.asarray(observed).flatten()
    sim = np.asarray(simulated).flatten()
    mask = ~(np.isnan(obs) | np.isnan(sim))
    obs = obs[mask]
    sim = sim[mask]

    # Calculate residuals
    residuals = sim - obs

    # Create subplots
    fig, axes = plt.subplots(2, 2, figsize=figsize)

    # 1. Residuals over time/index
    ax1 = axes[0, 0]
    x_vals = dates[mask] if dates is not None else np.arange(len(residuals))
    ax1.scatter(x_vals, residuals, alpha=0.5, s=10)
    ax1.axhline(y=0, color='red', linestyle='--', linewidth=1)
    ax1.set_xlabel('Time' if dates is not None else 'Index')
    ax1.set_ylabel('Residual (Sim - Obs)')
    ax1.set_title('Residuals Over Time')
    ax1.grid(True, alpha=0.3)

    # 2. Histogram of residuals
    ax2 = axes[0, 1]
    ax2.hist(residuals, bins=30, edgecolor='black', alpha=0.7)
    ax2.axvline(x=0, color='red', linestyle='--', linewidth=1)
    ax2.axvline(x=np.mean(residuals), color='green', linestyle='-', linewidth=1,
                label=f'Mean: {np.mean(residuals):.3f}')
    ax2.set_xlabel('Residual')
    ax2.set_ylabel('Frequency')
    ax2.set_title('Residuals Distribution')
    ax2.legend()
    ax2.grid(True, alpha=0.3)

    # 3. Residuals vs Observed
    ax3 = axes[1, 0]
    ax3.scatter(obs, residuals, alpha=0.5, s=10)
    ax3.axhline(y=0, color='red', linestyle='--', linewidth=1)
    ax3.set_xlabel('Observed')
    ax3.set_ylabel('Residual')
    ax3.set_title('Residuals vs Observed')
    ax3.grid(True, alpha=0.3)

    # 4. Q-Q plot
    ax4 = axes[1, 1]
    from scipy import stats
    stats.probplot(residuals, dist="norm", plot=ax4)
    ax4.set_title('Normal Q-Q Plot')
    ax4.grid(True, alpha=0.3)

    fig.suptitle(title, fontsize=14, y=1.02)
    plt.tight_layout()

    if save_path:
        fig.savefig(save_path, dpi=150, bbox_inches="tight")

    return fig


def plot_scatter_by_season(
    observed: np.ndarray,
    simulated: np.ndarray,
    dates: np.ndarray,
    title: str = "Seasonal Scatter Plots",
    figsize: Tuple[int, int] = (12, 10),
    save_path: Optional[str] = None,
) -> plt.Figure:
    """
    Create scatter plots for each season.

    Args:
        observed: Observed values
        simulated: Simulated values
        dates: Date values
        title: Plot title
        figsize: Figure size
        save_path: Path to save figure

    Returns:
        matplotlib Figure object
    """
    # Convert dates to months
    months = np.array([d.month for d in dates])

    # Define seasons
    seasons = {
        'Winter (DJF)': [12, 1, 2],
        'Spring (MAM)': [3, 4, 5],
        'Summer (JJA)': [6, 7, 8],
        'Fall (SON)': [9, 10, 11],
    }

    fig, axes = plt.subplots(2, 2, figsize=figsize)
    axes = axes.flatten()

    for idx, (season_name, season_months) in enumerate(seasons.items()):
        ax = axes[idx]
        mask = np.isin(months, season_months) & ~np.isnan(observed) & ~np.isnan(simulated)

        if np.sum(mask) > 0:
            obs_season = observed[mask]
            sim_season = simulated[mask]

            ax.scatter(obs_season, sim_season, alpha=0.5, s=20)

            # 1:1 line
            all_vals = np.concatenate([obs_season, sim_season])
            min_val, max_val = np.min(all_vals), np.max(all_vals)
            ax.plot([min_val, max_val], [min_val, max_val], 'k--', linewidth=1)

            # Metrics
            if len(obs_season) > 2:
                nse_val = nse(obs_season, sim_season)
                ax.text(0.05, 0.95, f'NSE = {nse_val:.3f}\nn = {len(obs_season)}',
                       transform=ax.transAxes, fontsize=9, verticalalignment='top',
                       bbox=dict(boxstyle='round', facecolor='white', alpha=0.8))

        ax.set_xlabel('Observed')
        ax.set_ylabel('Simulated')
        ax.set_title(season_name)
        ax.grid(True, alpha=0.3)
        ax.set_aspect('equal', adjustable='box')

    fig.suptitle(title, fontsize=14)
    plt.tight_layout()

    if save_path:
        fig.savefig(save_path, dpi=150, bbox_inches="tight")

    return fig
