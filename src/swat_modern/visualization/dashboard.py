"""
Unified dashboard for SWAT model calibration visualization.

Combines multiple visualization components into a single dashboard view.
"""

from typing import Optional, Tuple, Dict, List
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.gridspec import GridSpec

from swat_modern.visualization.hydrograph import plot_hydrograph
from swat_modern.visualization.scatter import plot_scatter
from swat_modern.visualization.metrics_table import MetricsTable
from swat_modern.visualization.duration_curve import plot_duration_comparison
from swat_modern.calibration.objectives import evaluate_model, model_performance_rating


class CalibrationDashboard:
    """
    Comprehensive dashboard for SWAT model calibration results.

    Provides a unified view combining:
    - Time series comparison (hydrograph)
    - Scatter plot with 1:1 line
    - Performance metrics table
    - Flow duration curve comparison

    Example:
        >>> from swat_modern.visualization import CalibrationDashboard
        >>> dashboard = CalibrationDashboard(
        ...     dates=dates,
        ...     observed=observed,
        ...     simulated=simulated,
        ...     site_name="Big Creek Watershed"
        ... )
        >>> dashboard.create_dashboard()
        >>> dashboard.save("calibration_report.png")
    """

    def __init__(
        self,
        dates: np.ndarray,
        observed: np.ndarray,
        simulated: np.ndarray,
        site_name: str = "Calibration Results",
        variable_name: str = "Streamflow",
        units: str = "m³/s",
    ):
        """
        Initialize CalibrationDashboard.

        Args:
            dates: Date/time values
            observed: Observed values
            simulated: Simulated values
            site_name: Name of the site/watershed
            variable_name: Name of the variable (e.g., "Streamflow", "Sediment")
            units: Units for the variable
        """
        self.dates = np.asarray(dates)
        self.observed = np.asarray(observed).flatten()
        self.simulated = np.asarray(simulated).flatten()
        self.site_name = site_name
        self.variable_name = variable_name
        self.units = units

        # Clean data
        self._clean_mask = ~(np.isnan(self.observed) | np.isnan(self.simulated))
        self._obs_clean = self.observed[self._clean_mask]
        self._sim_clean = self.simulated[self._clean_mask]
        self._dates_clean = self.dates[self._clean_mask] if len(self.dates) == len(self.observed) else None

        # Calculate metrics
        self.metrics = evaluate_model(self._obs_clean, self._sim_clean)
        self.rating = model_performance_rating(self.metrics['nse'])

        self._fig = None

    def create_dashboard(
        self,
        figsize: Tuple[int, int] = (16, 12),
        show: bool = True,
    ) -> plt.Figure:
        """
        Create the complete calibration dashboard.

        Args:
            figsize: Figure size (width, height)
            show: Whether to display the figure

        Returns:
            matplotlib Figure object
        """
        fig = plt.figure(figsize=figsize)
        gs = GridSpec(3, 2, figure=fig, height_ratios=[1.5, 1, 1])

        # 1. Hydrograph (top, spanning full width)
        ax_hydro = fig.add_subplot(gs[0, :])
        self._plot_hydrograph(ax_hydro)

        # 2. Scatter plot (middle left)
        ax_scatter = fig.add_subplot(gs[1, 0])
        self._plot_scatter(ax_scatter)

        # 3. Metrics table (middle right)
        ax_metrics = fig.add_subplot(gs[1, 1])
        self._plot_metrics_table(ax_metrics)

        # 4. Duration curve (bottom left)
        ax_fdc = fig.add_subplot(gs[2, 0])
        self._plot_duration_curve(ax_fdc)

        # 5. Monthly comparison (bottom right)
        ax_monthly = fig.add_subplot(gs[2, 1])
        self._plot_monthly_comparison(ax_monthly)

        # Overall title
        fig.suptitle(
            f"{self.site_name} - {self.variable_name} Calibration\n"
            f"NSE = {self.metrics['nse']:.3f} | KGE = {self.metrics['kge']:.3f} | "
            f"PBIAS = {self.metrics['pbias']:.1f}% | Rating: {self.rating}",
            fontsize=14,
            fontweight='bold',
            y=1.02
        )

        plt.tight_layout()

        self._fig = fig

        if show:
            plt.show()

        return fig

    def _plot_hydrograph(self, ax: plt.Axes):
        """Plot time series comparison."""
        if self._dates_clean is not None:
            ax.plot(self._dates_clean, self._obs_clean, color='blue',
                    linewidth=1, label='Observed')
            ax.plot(self._dates_clean, self._sim_clean, color='red',
                    linewidth=1, alpha=0.7, label='Simulated')
        else:
            ax.plot(self._obs_clean, color='blue', linewidth=1, label='Observed')
            ax.plot(self._sim_clean, color='red', linewidth=1, alpha=0.7, label='Simulated')

        ax.set_xlabel('Date')
        ax.set_ylabel(f'{self.variable_name} ({self.units})')
        ax.set_title('Time Series Comparison')
        ax.legend(loc='upper right')
        ax.grid(True, alpha=0.3)

    def _plot_scatter(self, ax: plt.Axes):
        """Plot scatter comparison."""
        ax.scatter(self._obs_clean, self._sim_clean, alpha=0.5, s=15, c='blue')

        # 1:1 line
        all_vals = np.concatenate([self._obs_clean, self._sim_clean])
        min_val, max_val = np.min(all_vals), np.max(all_vals)
        ax.plot([min_val, max_val], [min_val, max_val], 'k--', linewidth=1)

        ax.set_xlabel(f'Observed ({self.units})')
        ax.set_ylabel(f'Simulated ({self.units})')
        ax.set_title('Observed vs Simulated')
        ax.grid(True, alpha=0.3)
        ax.set_aspect('equal', adjustable='box')

    def _plot_metrics_table(self, ax: plt.Axes):
        """Plot metrics as a table."""
        ax.axis('off')

        # Create table data
        metrics_data = [
            ['Metric', 'Value', 'Rating'],
            ['NSE', f"{self.metrics['nse']:.4f}", self._get_nse_rating()],
            ['KGE', f"{self.metrics['kge']:.4f}", self._get_kge_rating()],
            ['PBIAS', f"{self.metrics['pbias']:.2f}%", self._get_pbias_rating()],
            ['RSR', f"{self.metrics['rsr']:.4f}", self._get_rsr_rating()],
            ['R²', f"{self.metrics['r_squared']:.4f}", '-'],
            ['RMSE', f"{self.metrics['rmse']:.4f}", '-'],
            ['n', f"{len(self._obs_clean)}", '-'],
        ]

        # Create table
        table = ax.table(
            cellText=metrics_data[1:],
            colLabels=metrics_data[0],
            cellLoc='center',
            loc='center',
            colWidths=[0.3, 0.35, 0.35],
        )

        table.auto_set_font_size(False)
        table.set_fontsize(10)
        table.scale(1.2, 1.5)

        # Style header
        for j in range(3):
            table[(0, j)].set_facecolor('#4CAF50')
            table[(0, j)].set_text_props(color='white', fontweight='bold')

        ax.set_title('Performance Metrics', fontsize=12, pad=20)

    def _plot_duration_curve(self, ax: plt.Axes):
        """Plot flow duration curves."""
        # Calculate exceedance probabilities
        obs_sorted = np.sort(self._obs_clean)[::-1]
        sim_sorted = np.sort(self._sim_clean)[::-1]
        n = len(obs_sorted)
        prob = (np.arange(1, n + 1)) / (n + 1) * 100

        ax.plot(prob, obs_sorted, color='blue', linewidth=1.5, label='Observed')
        ax.plot(prob, sim_sorted, color='red', linewidth=1.5, alpha=0.8, label='Simulated')

        if np.min(obs_sorted[obs_sorted > 0]) > 0:
            ax.set_yscale('log')

        ax.set_xlabel('Exceedance Probability (%)')
        ax.set_ylabel(f'{self.variable_name} ({self.units})')
        ax.set_title('Flow Duration Curves')
        ax.set_xlim(0, 100)
        ax.legend()
        ax.grid(True, alpha=0.3)

    def _plot_monthly_comparison(self, ax: plt.Axes):
        """Plot monthly average comparison."""
        if self._dates_clean is None:
            ax.text(0.5, 0.5, 'No date information available',
                    ha='center', va='center', transform=ax.transAxes)
            ax.set_title('Monthly Comparison')
            return

        # Create DataFrame for monthly aggregation
        df = pd.DataFrame({
            'date': self._dates_clean,
            'observed': self._obs_clean,
            'simulated': self._sim_clean,
        })
        df['month'] = pd.to_datetime(df['date']).dt.month

        monthly_obs = df.groupby('month')['observed'].mean()
        monthly_sim = df.groupby('month')['simulated'].mean()

        months = monthly_obs.index
        x = np.arange(len(months))
        width = 0.35

        ax.bar(x - width/2, monthly_obs.values, width, label='Observed', color='blue', alpha=0.7)
        ax.bar(x + width/2, monthly_sim.values, width, label='Simulated', color='red', alpha=0.7)

        ax.set_xlabel('Month')
        ax.set_ylabel(f'Mean {self.variable_name} ({self.units})')
        ax.set_title('Monthly Average Comparison')
        ax.set_xticks(x)
        ax.set_xticklabels(['J', 'F', 'M', 'A', 'M', 'J', 'J', 'A', 'S', 'O', 'N', 'D'][:len(months)])
        ax.legend()
        ax.grid(True, alpha=0.3, axis='y')

    def _get_nse_rating(self) -> str:
        """Get NSE rating text."""
        nse_val = self.metrics['nse']
        if nse_val > 0.75:
            return 'Very Good'
        elif nse_val > 0.65:
            return 'Good'
        elif nse_val > 0.50:
            return 'Satisfactory'
        return 'Unsatisfactory'

    def _get_kge_rating(self) -> str:
        """Get KGE rating text."""
        kge_val = self.metrics['kge']
        if kge_val > 0.75:
            return 'Very Good'
        elif kge_val > 0.50:
            return 'Good'
        elif kge_val > 0.0:
            return 'Satisfactory'
        return 'Unsatisfactory'

    def _get_pbias_rating(self) -> str:
        """Get PBIAS rating text."""
        pbias_val = abs(self.metrics['pbias'])
        if pbias_val < 10:
            return 'Very Good'
        elif pbias_val < 15:
            return 'Good'
        elif pbias_val < 25:
            return 'Satisfactory'
        return 'Unsatisfactory'

    def _get_rsr_rating(self) -> str:
        """Get RSR rating text."""
        rsr_val = self.metrics['rsr']
        if rsr_val <= 0.50:
            return 'Very Good'
        elif rsr_val <= 0.60:
            return 'Good'
        elif rsr_val <= 0.70:
            return 'Satisfactory'
        return 'Unsatisfactory'

    def save(
        self,
        filepath: str,
        dpi: int = 150,
        format: str = None,
    ):
        """
        Save dashboard to file.

        Args:
            filepath: Output file path
            dpi: Resolution
            format: File format (auto-detected from extension if None)
        """
        if self._fig is None:
            self.create_dashboard(show=False)

        self._fig.savefig(filepath, dpi=dpi, format=format, bbox_inches='tight')
        print(f"Dashboard saved to: {filepath}")

    def to_html(self, filepath: str):
        """
        Export dashboard as HTML report.

        Args:
            filepath: Output HTML file path
        """
        import base64
        from io import BytesIO

        if self._fig is None:
            self.create_dashboard(show=False)

        # Convert figure to base64
        buf = BytesIO()
        self._fig.savefig(buf, format='png', dpi=150, bbox_inches='tight')
        buf.seek(0)
        img_base64 = base64.b64encode(buf.read()).decode('utf-8')

        # Create HTML
        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>{self.site_name} - Calibration Report</title>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 20px; }}
                h1 {{ color: #2c3e50; }}
                .metrics {{ margin: 20px 0; }}
                img {{ max-width: 100%; }}
            </style>
        </head>
        <body>
            <h1>{self.site_name} - {self.variable_name} Calibration Report</h1>
            <div class="metrics">
                <h2>Performance Summary</h2>
                <ul>
                    <li><strong>NSE:</strong> {self.metrics['nse']:.4f} ({self._get_nse_rating()})</li>
                    <li><strong>KGE:</strong> {self.metrics['kge']:.4f}</li>
                    <li><strong>PBIAS:</strong> {self.metrics['pbias']:.2f}%</li>
                    <li><strong>RSR:</strong> {self.metrics['rsr']:.4f}</li>
                    <li><strong>R²:</strong> {self.metrics['r_squared']:.4f}</li>
                    <li><strong>Samples:</strong> {len(self._obs_clean)}</li>
                </ul>
            </div>
            <h2>Visualization</h2>
            <img src="data:image/png;base64,{img_base64}" alt="Calibration Dashboard">
        </body>
        </html>
        """

        with open(filepath, 'w') as f:
            f.write(html)

        print(f"HTML report saved to: {filepath}")
