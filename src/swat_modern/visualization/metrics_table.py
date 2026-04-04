"""
Metrics table visualization for SWAT model performance.

Provides formatted tables of calibration metrics.
"""

from typing import Optional, List, Dict
import numpy as np
import pandas as pd
from swat_modern.calibration.objectives import (
    nse, kge, pbias, rmse, r_squared, mae, rsr, log_nse,
    model_performance_rating
)


def create_metrics_dataframe(
    observed: np.ndarray,
    simulated: np.ndarray,
    site_name: str = "Site 1",
    include_all: bool = True,
) -> pd.DataFrame:
    """
    Create a DataFrame with all calibration metrics.

    Args:
        observed: Observed values
        simulated: Simulated values
        site_name: Name for the site/location
        include_all: Include all available metrics

    Returns:
        DataFrame with metrics
    """
    # Clean data
    obs = np.asarray(observed).flatten()
    sim = np.asarray(simulated).flatten()
    mask = ~(np.isnan(obs) | np.isnan(sim))
    obs = obs[mask]
    sim = sim[mask]

    if len(obs) < 2:
        raise ValueError("Need at least 2 valid data points")

    # Calculate metrics
    metrics = {
        'NSE': nse(obs, sim),
        'KGE': kge(obs, sim),
        'PBIAS (%)': pbias(obs, sim),
        'R²': r_squared(obs, sim),
        'RMSE': rmse(obs, sim),
        'RSR': rsr(obs, sim),
    }

    if include_all:
        metrics['MAE'] = mae(obs, sim)
        metrics['Log-NSE'] = log_nse(obs, sim)
        metrics['n'] = len(obs)

    # Create DataFrame
    df = pd.DataFrame({
        'Metric': list(metrics.keys()),
        site_name: list(metrics.values()),
    })

    return df


def create_multi_site_metrics(
    sites_data: Dict[str, tuple],
    include_all: bool = True,
) -> pd.DataFrame:
    """
    Create metrics table for multiple sites.

    Args:
        sites_data: Dictionary of {site_name: (observed, simulated)}
        include_all: Include all metrics

    Returns:
        DataFrame with metrics for all sites
    """
    dfs = []
    for site_name, (obs, sim) in sites_data.items():
        df = create_metrics_dataframe(obs, sim, site_name, include_all)
        dfs.append(df.set_index('Metric'))

    result = pd.concat(dfs, axis=1)
    return result.reset_index()


class MetricsTable:
    """
    Class for displaying and formatting calibration metrics.

    Example:
        >>> table = MetricsTable(observed, simulated)
        >>> print(table.to_string())
        >>> table.to_html("metrics.html")
    """

    def __init__(
        self,
        observed: np.ndarray,
        simulated: np.ndarray,
        site_name: str = "Calibration Results",
    ):
        """
        Initialize MetricsTable.

        Args:
            observed: Observed values
            simulated: Simulated values
            site_name: Name for the site/analysis
        """
        self.observed = np.asarray(observed).flatten()
        self.simulated = np.asarray(simulated).flatten()
        self.site_name = site_name

        # Clean data
        mask = ~(np.isnan(self.observed) | np.isnan(self.simulated))
        self._obs_clean = self.observed[mask]
        self._sim_clean = self.simulated[mask]

        # Calculate all metrics
        self._calculate_metrics()

    def _calculate_metrics(self):
        """Calculate all performance metrics."""
        obs, sim = self._obs_clean, self._sim_clean

        if len(obs) < 2:
            self.metrics = {}
            return

        self.metrics = {
            'NSE': nse(obs, sim),
            'KGE': kge(obs, sim),
            'PBIAS': pbias(obs, sim),
            'R²': r_squared(obs, sim),
            'RMSE': rmse(obs, sim),
            'RSR': rsr(obs, sim),
            'MAE': mae(obs, sim),
            'Log-NSE': log_nse(obs, sim),
        }

        self.n_samples = len(obs)
        self.rating = model_performance_rating(self.metrics['NSE'])

    def to_dataframe(self) -> pd.DataFrame:
        """Convert metrics to DataFrame."""
        data = []
        for metric, value in self.metrics.items():
            if metric == 'PBIAS':
                formatted = f"{value:.2f}%"
            else:
                formatted = f"{value:.4f}"
            data.append({
                'Metric': metric,
                'Value': value,
                'Formatted': formatted,
            })

        data.append({
            'Metric': 'n (samples)',
            'Value': self.n_samples,
            'Formatted': str(self.n_samples),
        })
        data.append({
            'Metric': 'Performance Rating',
            'Value': np.nan,
            'Formatted': self.rating,
        })

        return pd.DataFrame(data)

    def to_string(self) -> str:
        """Get formatted string representation."""
        lines = [
            "=" * 50,
            f"  {self.site_name}",
            "=" * 50,
            "",
        ]

        for metric, value in self.metrics.items():
            if metric == 'PBIAS':
                lines.append(f"  {metric:12s}: {value:>10.2f}%")
            else:
                lines.append(f"  {metric:12s}: {value:>10.4f}")

        lines.extend([
            "",
            f"  {'Samples':12s}: {self.n_samples:>10d}",
            f"  {'Rating':12s}: {self.rating:>10s}",
            "",
            "=" * 50,
        ])

        return "\n".join(lines)

    def display(self):
        """Print formatted metrics table."""
        print(self.to_string())

    def to_html(self, filepath: str = None) -> str:
        """
        Generate HTML table.

        Args:
            filepath: Optional path to save HTML file

        Returns:
            HTML string
        """
        df = self.to_dataframe()
        html = df[['Metric', 'Formatted']].to_html(index=False)

        # Add styling
        styled_html = f"""
        <style>
            .metrics-table {{
                font-family: Arial, sans-serif;
                border-collapse: collapse;
                width: 300px;
            }}
            .metrics-table th, .metrics-table td {{
                border: 1px solid #ddd;
                padding: 8px;
                text-align: left;
            }}
            .metrics-table th {{
                background-color: #4CAF50;
                color: white;
            }}
            .metrics-table tr:nth-child(even) {{
                background-color: #f2f2f2;
            }}
        </style>
        <h3>{self.site_name}</h3>
        {html}
        """

        if filepath:
            with open(filepath, 'w') as f:
                f.write(styled_html)

        return styled_html

    def get_rating_color(self) -> str:
        """Get color code based on performance rating."""
        colors = {
            'Very Good': '#2ecc71',
            'Good': '#27ae60',
            'Satisfactory': '#f39c12',
            'Unsatisfactory': '#e74c3c',
        }
        return colors.get(self.rating, '#95a5a6')

    def passes_threshold(
        self,
        nse_min: float = 0.5,
        pbias_max: float = 25.0,
        rsr_max: float = 0.7,
    ) -> bool:
        """
        Check if metrics pass minimum thresholds.

        Based on Moriasi et al. (2007) satisfactory thresholds.

        Args:
            nse_min: Minimum NSE (default: 0.5)
            pbias_max: Maximum absolute PBIAS (default: 25%)
            rsr_max: Maximum RSR (default: 0.7)

        Returns:
            True if all thresholds are met
        """
        return (
            self.metrics['NSE'] >= nse_min and
            abs(self.metrics['PBIAS']) <= pbias_max and
            self.metrics['RSR'] <= rsr_max
        )
