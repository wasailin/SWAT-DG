"""
Diagnostic visualization for expert-guided SWAT model calibration.

Provides plots for baseflow separation, peak comparison, seasonal bias,
parameter recommendations, and water quality (sediment, phosphorus, nitrogen)
diagnostic dashboards.
"""

from typing import Dict, List, Optional, Tuple
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec


def plot_baseflow_separation(
    dates: np.ndarray,
    total_flow: np.ndarray,
    baseflow: np.ndarray,
    title: str = "Baseflow Separation (Eckhardt Filter)",
    ylabel: str = "Flow",
    figsize: Tuple[int, int] = (14, 5),
    ax: Optional[plt.Axes] = None,
    save_path: Optional[str] = None,
) -> plt.Figure:
    """
    Plot total flow with baseflow shaded underneath.

    Quickflow is the white area between baseflow and total flow.

    Args:
        dates: Date array or index.
        total_flow: Total streamflow array.
        baseflow: Baseflow array (from Eckhardt or Lyne-Hollick filter).
        title: Plot title.
        ylabel: Y-axis label.
        figsize: Figure size.
        ax: Existing axes to plot on.
        save_path: Path to save figure.

    Returns:
        matplotlib Figure object.
    """
    if ax is None:
        fig, ax = plt.subplots(figsize=figsize)
    else:
        fig = ax.get_figure()

    ax.plot(dates, total_flow, color="#1565C0", linewidth=0.8, label="Total Flow", alpha=0.9)
    ax.fill_between(dates, 0, baseflow, color="#90CAF9", alpha=0.6, label="Baseflow")
    ax.fill_between(dates, baseflow, total_flow, color="#E3F2FD", alpha=0.3, label="Quickflow")

    # BFI annotation
    bfi = np.nansum(baseflow) / np.nansum(total_flow) if np.nansum(total_flow) > 0 else 0
    ax.text(0.02, 0.95, f"BFI = {bfi:.3f}", transform=ax.transAxes,
            fontsize=10, verticalalignment="top",
            bbox=dict(boxstyle="round,pad=0.3", facecolor="white", alpha=0.8))

    ax.set_xlabel("Date")
    ax.set_ylabel(ylabel)
    ax.set_title(title, fontsize=12, fontweight="bold")
    ax.legend(loc="upper right", fontsize=9)
    ax.grid(True, alpha=0.2)
    ax.set_xlim(dates[0], dates[-1])

    plt.tight_layout()
    if save_path:
        fig.savefig(save_path, dpi=150, bbox_inches="tight")
    return fig


def plot_peak_comparison(
    dates: np.ndarray,
    observed: np.ndarray,
    simulated: np.ndarray,
    peak_pairs: List[Dict],
    title: str = "Peak Flow Comparison",
    ylabel: str = "Flow",
    figsize: Tuple[int, int] = (14, 5),
    save_path: Optional[str] = None,
) -> plt.Figure:
    """
    Plot hydrograph with matched peaks highlighted and timing offsets annotated.

    Args:
        dates: Date array.
        observed: Observed flow.
        simulated: Simulated flow.
        peak_pairs: List of matched peak dicts from compare_peaks().
        title: Plot title.
        ylabel: Y-axis label.
        figsize: Figure size.
        save_path: Path to save figure.

    Returns:
        matplotlib Figure object.
    """
    fig, ax = plt.subplots(figsize=figsize)

    ax.plot(dates, observed, color="#1565C0", linewidth=1.0, label="Observed", alpha=0.9)
    ax.plot(dates, simulated, color="#E53935", linewidth=1.0, label="Simulated", alpha=0.8)

    # Mark matched peaks
    for pair in peak_pairs:
        obs_idx = pair["obs_index"]
        sim_idx = pair["sim_index"]
        if obs_idx < len(dates) and sim_idx < len(dates):
            ax.plot(dates[obs_idx], pair["obs_value"], "v", color="#1565C0",
                    markersize=8, zorder=5)
            ax.plot(dates[sim_idx], pair["sim_value"], "^", color="#E53935",
                    markersize=8, zorder=5)

            # Connect with a line to show timing offset
            ax.plot([dates[obs_idx], dates[sim_idx]],
                    [pair["obs_value"], pair["sim_value"]],
                    "--", color="gray", alpha=0.5, linewidth=0.8)

    # Summary annotation
    if peak_pairs:
        ratios = [p["magnitude_ratio"] for p in peak_pairs if not np.isnan(p.get("magnitude_ratio", np.nan))]
        offsets = [p["timing_error"] for p in peak_pairs]
        med_ratio = np.median(ratios) if ratios else np.nan
        med_offset = np.median(offsets) if offsets else np.nan
        txt = f"Peaks: {len(peak_pairs)} matched\nMag ratio: {med_ratio:.2f}\nTiming: {med_offset:+.1f} days"
        ax.text(0.02, 0.95, txt, transform=ax.transAxes, fontsize=9,
                verticalalignment="top",
                bbox=dict(boxstyle="round,pad=0.3", facecolor="white", alpha=0.8))

    ax.set_xlabel("Date")
    ax.set_ylabel(ylabel)
    ax.set_title(title, fontsize=12, fontweight="bold")
    ax.legend(loc="upper right", fontsize=9)
    ax.grid(True, alpha=0.2)
    ax.set_xlim(dates[0], dates[-1])

    plt.tight_layout()
    if save_path:
        fig.savefig(save_path, dpi=150, bbox_inches="tight")
    return fig


def plot_seasonal_bias(
    seasonal_bias: Dict[str, float],
    title: str = "Seasonal Volume Bias (PBIAS %)",
    figsize: Tuple[int, int] = (6, 4),
    ax: Optional[plt.Axes] = None,
    save_path: Optional[str] = None,
) -> plt.Figure:
    """
    Bar chart of seasonal volume bias.

    Args:
        seasonal_bias: Dict of {season: pbias} from volume_balance().
        title: Plot title.
        figsize: Figure size.
        ax: Existing axes.
        save_path: Path to save figure.

    Returns:
        matplotlib Figure.
    """
    if ax is None:
        fig, ax = plt.subplots(figsize=figsize)
    else:
        fig = ax.get_figure()

    seasons = ["DJF", "MAM", "JJA", "SON"]
    values = [seasonal_bias.get(s, 0) for s in seasons]
    colors = ["#E53935" if v < 0 else "#1565C0" for v in values]

    bars = ax.bar(seasons, values, color=colors, edgecolor="white", width=0.6)

    # Value labels
    for bar, val in zip(bars, values):
        y_offset = 1 if val >= 0 else -1
        ax.text(bar.get_x() + bar.get_width() / 2, val + y_offset,
                f"{val:+.1f}%", ha="center", va="bottom" if val >= 0 else "top", fontsize=9)

    ax.axhline(y=0, color="black", linewidth=0.5)
    ax.axhline(y=10, color="gray", linestyle="--", alpha=0.3)
    ax.axhline(y=-10, color="gray", linestyle="--", alpha=0.3)
    ax.set_ylabel("PBIAS (%)")
    ax.set_title(title, fontsize=11, fontweight="bold")
    ax.grid(axis="y", alpha=0.2)

    # Annotation: positive = underestimation, negative = overestimation
    ax.text(0.98, 0.02, "+PBIAS = underestimate\n-PBIAS = overestimate",
            transform=ax.transAxes, fontsize=7, ha="right", va="bottom",
            alpha=0.5, style="italic")

    plt.tight_layout()
    if save_path:
        fig.savefig(save_path, dpi=150, bbox_inches="tight")
    return fig


def plot_recommendations_table(
    recommendations: list,
    title: str = "Parameter Recommendations",
    figsize: Tuple[int, int] = (10, None),
    save_path: Optional[str] = None,
) -> plt.Figure:
    """
    Create a parameter recommendation table rendered as a matplotlib figure.

    Args:
        recommendations: List of ParameterRecommendation objects.
        title: Table title.
        figsize: Figure size (height auto-calculated if None).
        save_path: Path to save figure.

    Returns:
        matplotlib Figure.
    """
    if not recommendations:
        fig, ax = plt.subplots(figsize=(6, 1))
        ax.text(0.5, 0.5, "No significant issues found", ha="center", va="center",
                fontsize=12, transform=ax.transAxes, alpha=0.5)
        ax.axis("off")
        return fig

    n_rows = len(recommendations)
    height = max(2, 0.5 * n_rows + 1.2)
    fig_w = figsize[0] if figsize[0] else 10
    fig, ax = plt.subplots(figsize=(fig_w, height))
    ax.axis("off")

    # Table data
    cell_text = []
    cell_colors = []
    conf_colors = {"high": "#FFCDD2", "medium": "#FFF9C4", "low": "#E0E0E0"}

    for r in recommendations:
        arrow = "\u2191" if r.direction == "increase" else "\u2193"
        cell_text.append([r.parameter, f"{arrow} {r.direction}", r.reason, r.confidence])
        bg = conf_colors.get(r.confidence, "#FFFFFF")
        cell_colors.append([bg, bg, bg, bg])

    table = ax.table(
        cellText=cell_text,
        colLabels=["Parameter", "Direction", "Reason", "Confidence"],
        cellColours=cell_colors,
        colWidths=[0.15, 0.12, 0.55, 0.12],
        loc="center",
        cellLoc="left",
    )
    table.auto_set_font_size(False)
    table.set_fontsize(9)
    table.scale(1, 1.4)

    # Style header
    for j in range(4):
        table[0, j].set_facecolor("#37474F")
        table[0, j].set_text_props(color="white", fontweight="bold")

    ax.set_title(title, fontsize=12, fontweight="bold", pad=10)

    plt.tight_layout()
    if save_path:
        fig.savefig(save_path, dpi=150, bbox_inches="tight")
    return fig


def plot_diagnostic_dashboard(
    report,
    dates: np.ndarray,
    observed: np.ndarray,
    simulated: np.ndarray,
    title: str = "Hydrograph Diagnostic Dashboard",
    figsize: Tuple[int, int] = (16, 14),
    save_path: Optional[str] = None,
) -> plt.Figure:
    """
    Create a 4-panel diagnostic dashboard.

    Panels:
        Top:         Hydrograph with baseflow separation overlay
        Middle-left: Peak magnitude scatter (obs vs sim peaks, 1:1 line)
        Middle-right: Seasonal volume bias bar chart
        Bottom:      Parameter recommendations table

    Args:
        report: DiagnosticReport object from diagnostics.diagnose().
        dates: Date array.
        observed: Observed flow array.
        simulated: Simulated flow array.
        title: Dashboard title.
        figsize: Figure size.
        save_path: Path to save figure.

    Returns:
        matplotlib Figure.
    """
    fig = plt.figure(figsize=figsize)
    fig.suptitle(title, fontsize=14, fontweight="bold", y=0.98)

    gs = gridspec.GridSpec(3, 2, height_ratios=[1.2, 1, 1], hspace=0.35, wspace=0.3)

    # --- Panel 1: Hydrograph with baseflow (spans full width) ---
    ax1 = fig.add_subplot(gs[0, :])
    ax1.plot(dates, observed, color="#1565C0", linewidth=0.8, label="Observed", alpha=0.9)
    ax1.plot(dates, simulated, color="#E53935", linewidth=0.8, label="Simulated", alpha=0.8)
    ax1.fill_between(dates, 0, report.obs_baseflow, color="#90CAF9", alpha=0.3, label="Obs Baseflow")
    ax1.fill_between(dates, 0, report.sim_baseflow, color="#EF9A9A", alpha=0.3, label="Sim Baseflow")
    ax1.set_xlabel("Date")
    ax1.set_ylabel("Flow")
    ax1.set_title("Hydrograph with Baseflow Separation", fontsize=11)
    ax1.legend(loc="upper right", fontsize=8, ncol=2)
    ax1.grid(True, alpha=0.2)
    ax1.set_xlim(dates[0], dates[-1])

    # Metrics annotation
    m = report.overall_metrics
    metrics_txt = (
        f"NSE={m.get('nse', np.nan):.3f}  KGE={m.get('kge', np.nan):.3f}  "
        f"PBIAS={m.get('pbias', np.nan):.1f}%\n"
        f"BFI obs={report.bfi_observed:.3f}  sim={report.bfi_simulated:.3f}  "
        f"ratio={report.bfi_ratio:.2f}"
    )
    ax1.text(0.01, 0.97, metrics_txt, transform=ax1.transAxes, fontsize=8,
             verticalalignment="top",
             bbox=dict(boxstyle="round,pad=0.3", facecolor="white", alpha=0.85))

    # --- Panel 2: Peak magnitude scatter ---
    ax2 = fig.add_subplot(gs[1, 0])
    peak_pairs = report.peak_comparison.get("peak_pairs", [])
    if peak_pairs:
        obs_peaks = [p["obs_value"] for p in peak_pairs]
        sim_peaks = [p["sim_value"] for p in peak_pairs]
        ax2.scatter(obs_peaks, sim_peaks, c="#E53935", edgecolors="white",
                    s=60, zorder=5, alpha=0.8)
        # 1:1 line
        max_val = max(max(obs_peaks), max(sim_peaks)) * 1.1
        ax2.plot([0, max_val], [0, max_val], "--", color="gray", alpha=0.5, label="1:1 line")
        ax2.set_xlim(0, max_val)
        ax2.set_ylim(0, max_val)

        # Timing annotations for top peaks
        top_n = min(5, len(peak_pairs))
        sorted_pairs = sorted(peak_pairs, key=lambda p: p["obs_value"], reverse=True)[:top_n]
        for p in sorted_pairs:
            ax2.annotate(f"{p['timing_error']:+d}d",
                         xy=(p["obs_value"], p["sim_value"]),
                         fontsize=7, alpha=0.7, textcoords="offset points",
                         xytext=(5, 5))
    else:
        ax2.text(0.5, 0.5, "No peaks detected", ha="center", va="center",
                 transform=ax2.transAxes, alpha=0.5)

    ax2.set_xlabel("Observed Peak Flow")
    ax2.set_ylabel("Simulated Peak Flow")
    ax2.set_title("Peak Magnitude Comparison", fontsize=11)
    ax2.legend(fontsize=8)
    ax2.grid(True, alpha=0.2)
    ax2.set_aspect("equal", adjustable="box")

    # --- Panel 3: Seasonal volume bias ---
    ax3 = fig.add_subplot(gs[1, 1])
    seasonal = report.volume_metrics.get("seasonal_bias", {})
    if seasonal:
        plot_seasonal_bias(seasonal, title="Seasonal Volume Bias", ax=ax3)
    else:
        ax3.text(0.5, 0.5, "No seasonal data\n(dates not provided)",
                 ha="center", va="center", transform=ax3.transAxes, alpha=0.5)
        ax3.set_title("Seasonal Volume Bias", fontsize=11)
        ax3.axis("off")

    # --- Panel 4: Findings & recommendations table (spans full width) ---
    ax4 = fig.add_subplot(gs[2, :])
    ax4.axis("off")

    if report.findings:
        # Build table data from findings + recommendations
        cell_text = []
        cell_colors = []
        conf_colors = {"high": "#FFCDD2", "medium": "#FFF9C4", "low": "#E0E0E0"}

        for r in report.recommendations[:10]:
            arrow = "\u2191" if r.direction == "increase" else "\u2193"
            cell_text.append([r.parameter, f"{arrow} {r.direction}", r.reason, r.confidence])
            bg = conf_colors.get(r.confidence, "#FFFFFF")
            cell_colors.append([bg, bg, bg, bg])

        if cell_text:
            table = ax4.table(
                cellText=cell_text,
                colLabels=["Parameter", "Direction", "Reason", "Confidence"],
                cellColours=cell_colors,
                colWidths=[0.13, 0.10, 0.60, 0.10],
                loc="upper center",
                cellLoc="left",
            )
            table.auto_set_font_size(False)
            table.set_fontsize(8)
            table.scale(1, 1.3)
            for j in range(4):
                table[0, j].set_facecolor("#37474F")
                table[0, j].set_text_props(color="white", fontweight="bold")
        ax4.set_title("Parameter Recommendations", fontsize=11, fontweight="bold")
    else:
        ax4.text(0.5, 0.5, "No significant diagnostic issues found",
                 ha="center", va="center", transform=ax4.transAxes,
                 fontsize=12, alpha=0.5, style="italic")
        ax4.set_title("Parameter Recommendations", fontsize=11, fontweight="bold")

    if save_path:
        fig.savefig(save_path, dpi=150, bbox_inches="tight")

    return fig


# ---------------------------------------------------------------------------
# Water Quality Diagnostic Visualizations
# ---------------------------------------------------------------------------


def plot_rating_curve(
    obs_flow: np.ndarray,
    obs_sed: np.ndarray,
    sim_flow: np.ndarray,
    sim_sed: np.ndarray,
    rating_analysis: Dict,
    title: str = "Sediment Rating Curve (Log-Log)",
    figsize: Tuple[int, int] = (7, 6),
    ax: Optional[plt.Axes] = None,
    save_path: Optional[str] = None,
) -> plt.Figure:
    """
    Log-log scatter plot comparing observed and simulated sediment-discharge
    rating curves with power-law regression lines overlaid.

    Args:
        obs_flow: Observed flow array.
        obs_sed: Observed sediment array.
        sim_flow: Simulated flow array.
        sim_sed: Simulated sediment array.
        rating_analysis: Dict from sediment_rating_curve_analysis() with keys
            obs_slope, sim_slope, slope_ratio.
        title: Plot title.
        figsize: Figure size.
        ax: Existing axes to plot on.
        save_path: Path to save figure.

    Returns:
        matplotlib Figure object.
    """
    if ax is None:
        fig, ax = plt.subplots(figsize=figsize)
    else:
        fig = ax.get_figure()

    # Filter to positive values for log-log plotting
    obs_valid = (obs_flow > 0) & (obs_sed > 0)
    sim_valid = (sim_flow > 0) & (sim_sed > 0)

    # Scatter plots
    if np.any(obs_valid):
        ax.scatter(obs_flow[obs_valid], obs_sed[obs_valid],
                   c="#1565C0", edgecolors="white", s=30, alpha=0.5,
                   label="Observed", zorder=3)
    if np.any(sim_valid):
        ax.scatter(sim_flow[sim_valid], sim_sed[sim_valid],
                   c="#E53935", edgecolors="white", s=30, alpha=0.5,
                   label="Simulated", zorder=3)

    # Power-law regression lines
    obs_slope = rating_analysis.get("obs_slope", np.nan)
    sim_slope = rating_analysis.get("sim_slope", np.nan)

    # Compute regression lines from the raw data (need intercept too)
    if np.any(obs_valid) and not np.isnan(obs_slope):
        log_q_obs = np.log10(obs_flow[obs_valid])
        log_s_obs = np.log10(obs_sed[obs_valid])
        coeffs_obs = np.polyfit(log_q_obs, log_s_obs, 1)
        q_line = np.logspace(np.log10(obs_flow[obs_valid].min()),
                             np.log10(obs_flow[obs_valid].max()), 100)
        s_line = 10 ** np.polyval(coeffs_obs, np.log10(q_line))
        ax.plot(q_line, s_line, color="#1565C0", linewidth=2, linestyle="--",
                alpha=0.9, label=f"Obs fit (slope={obs_slope:.2f})")

    if np.any(sim_valid) and not np.isnan(sim_slope):
        log_q_sim = np.log10(sim_flow[sim_valid])
        log_s_sim = np.log10(sim_sed[sim_valid])
        coeffs_sim = np.polyfit(log_q_sim, log_s_sim, 1)
        q_line = np.logspace(np.log10(sim_flow[sim_valid].min()),
                             np.log10(sim_flow[sim_valid].max()), 100)
        s_line = 10 ** np.polyval(coeffs_sim, np.log10(q_line))
        ax.plot(q_line, s_line, color="#E53935", linewidth=2, linestyle="--",
                alpha=0.9, label=f"Sim fit (slope={sim_slope:.2f})")

    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel("Flow (log scale)")
    ax.set_ylabel("Sediment (log scale)")
    ax.set_title(title, fontsize=12, fontweight="bold")
    ax.legend(loc="upper left", fontsize=8)
    ax.grid(True, alpha=0.2, which="both")

    # Slope ratio annotation
    slope_ratio = rating_analysis.get("slope_ratio", np.nan)
    if not np.isnan(slope_ratio):
        ax.text(0.98, 0.05, f"Slope ratio (sim/obs) = {slope_ratio:.2f}",
                transform=ax.transAxes, fontsize=9, ha="right", va="bottom",
                bbox=dict(boxstyle="round,pad=0.3", facecolor="white", alpha=0.8))

    plt.tight_layout()
    if save_path:
        fig.savefig(save_path, dpi=150, bbox_inches="tight")
    return fig


def plot_flow_partition(
    flow_partition: Dict,
    title: str = "Phosphorus Flow Partition PBIAS",
    figsize: Tuple[int, int] = (7, 5),
    ax: Optional[plt.Axes] = None,
    save_path: Optional[str] = None,
) -> plt.Figure:
    """
    Grouped bar chart showing high-flow vs low-flow PBIAS for phosphorus.

    Bars are color-coded: red for overestimation (negative PBIAS), blue for
    underestimation (positive PBIAS). Fraction values are annotated below
    the x-axis labels.

    Args:
        flow_partition: Dict from phosphorus_flow_partition() with keys
            highflow_pbias, lowflow_pbias, obs_highflow_frac, sim_highflow_frac.
        title: Plot title.
        figsize: Figure size.
        ax: Existing axes to plot on.
        save_path: Path to save figure.

    Returns:
        matplotlib Figure object.
    """
    if ax is None:
        fig, ax = plt.subplots(figsize=figsize)
    else:
        fig = ax.get_figure()

    highflow_pbias = flow_partition.get("highflow_pbias", 0)
    lowflow_pbias = flow_partition.get("lowflow_pbias", 0)
    obs_hf_frac = flow_partition.get("obs_highflow_frac", np.nan)
    sim_hf_frac = flow_partition.get("sim_highflow_frac", np.nan)

    labels = ["High Flow\n(particulate P)", "Low Flow\n(dissolved P)"]
    values = [highflow_pbias, lowflow_pbias]
    colors = ["#E53935" if v < 0 else "#1565C0" for v in values]

    bars = ax.bar(labels, values, color=colors, edgecolor="white", width=0.5)

    # Value labels on bars
    for bar, val in zip(bars, values):
        y_offset = 1.5 if val >= 0 else -1.5
        ax.text(bar.get_x() + bar.get_width() / 2, val + y_offset,
                f"{val:+.1f}%", ha="center",
                va="bottom" if val >= 0 else "top", fontsize=10, fontweight="bold")

    ax.axhline(y=0, color="black", linewidth=0.5)
    ax.axhline(y=25, color="gray", linestyle="--", alpha=0.3)
    ax.axhline(y=-25, color="gray", linestyle="--", alpha=0.3)
    ax.set_ylabel("PBIAS (%)")
    ax.set_title(title, fontsize=12, fontweight="bold")
    ax.grid(axis="y", alpha=0.2)

    # Fraction annotation
    frac_txt = (
        f"Obs high-flow frac: {obs_hf_frac:.2f}    "
        f"Sim high-flow frac: {sim_hf_frac:.2f}"
    )
    ax.text(0.5, -0.12, frac_txt, transform=ax.transAxes, fontsize=8,
            ha="center", va="top", alpha=0.6, style="italic")

    # PBIAS convention annotation
    ax.text(0.98, 0.02, "+PBIAS = underestimate\n-PBIAS = overestimate",
            transform=ax.transAxes, fontsize=7, ha="right", va="bottom",
            alpha=0.5, style="italic")

    plt.tight_layout()
    if save_path:
        fig.savefig(save_path, dpi=150, bbox_inches="tight")
    return fig


def plot_event_partition(
    event_partition: Dict,
    title: str = "Event vs Baseflow Sediment Fraction",
    figsize: Tuple[int, int] = (6, 5),
    ax: Optional[plt.Axes] = None,
    save_path: Optional[str] = None,
) -> plt.Figure:
    """
    Bar chart comparing observed vs simulated event sediment fraction.

    Two bars show the fraction of total sediment load transported during
    high-flow (event) periods for observed and simulated data.

    Args:
        event_partition: Dict from sediment_event_partition() with keys
            obs_event_frac, sim_event_frac, event_ratio.
        title: Plot title.
        figsize: Figure size.
        ax: Existing axes to plot on.
        save_path: Path to save figure.

    Returns:
        matplotlib Figure object.
    """
    if ax is None:
        fig, ax = plt.subplots(figsize=figsize)
    else:
        fig = ax.get_figure()

    obs_frac = event_partition.get("obs_event_frac", 0)
    sim_frac = event_partition.get("sim_event_frac", 0)
    event_ratio = event_partition.get("event_ratio", np.nan)

    labels = ["Observed", "Simulated"]
    values = [obs_frac, sim_frac]
    colors = ["#1565C0", "#E53935"]

    bars = ax.bar(labels, values, color=colors, edgecolor="white", width=0.5)

    # Value labels on bars
    for bar, val in zip(bars, values):
        ax.text(bar.get_x() + bar.get_width() / 2, val + 0.01,
                f"{val:.2f}", ha="center", va="bottom", fontsize=10, fontweight="bold")

    ax.set_ylabel("Event Sediment Fraction")
    ax.set_title(title, fontsize=12, fontweight="bold")
    ax.set_ylim(0, min(1.15, max(obs_frac, sim_frac) * 1.3 + 0.05))
    ax.grid(axis="y", alpha=0.2)

    # Event ratio annotation
    if not np.isnan(event_ratio):
        ax.text(0.98, 0.95, f"Event ratio (sim/obs) = {event_ratio:.2f}",
                transform=ax.transAxes, fontsize=9, ha="right", va="top",
                bbox=dict(boxstyle="round,pad=0.3", facecolor="white", alpha=0.8))

    plt.tight_layout()
    if save_path:
        fig.savefig(save_path, dpi=150, bbox_inches="tight")
    return fig


def _build_recommendations_panel(ax, recommendations):
    """
    Render a parameter recommendations table on the given axes.

    Internal helper used by plot_wq_diagnostic_dashboard to avoid duplication.

    Args:
        ax: Matplotlib axes (will be turned off).
        recommendations: List of ParameterRecommendation objects.
    """
    ax.axis("off")

    if not recommendations:
        ax.text(0.5, 0.5, "No significant diagnostic issues found",
                ha="center", va="center", transform=ax.transAxes,
                fontsize=12, alpha=0.5, style="italic")
        ax.set_title("Parameter Recommendations", fontsize=11, fontweight="bold")
        return

    cell_text = []
    cell_colors = []
    conf_colors = {"high": "#FFCDD2", "medium": "#FFF9C4", "low": "#E0E0E0"}

    for r in recommendations[:10]:
        arrow = "\u2191" if r.direction == "increase" else "\u2193"
        cell_text.append([r.parameter, f"{arrow} {r.direction}", r.reason, r.confidence])
        bg = conf_colors.get(r.confidence, "#FFFFFF")
        cell_colors.append([bg, bg, bg, bg])

    if cell_text:
        table = ax.table(
            cellText=cell_text,
            colLabels=["Parameter", "Direction", "Reason", "Confidence"],
            cellColours=cell_colors,
            colWidths=[0.13, 0.10, 0.60, 0.10],
            loc="upper center",
            cellLoc="left",
        )
        table.auto_set_font_size(False)
        table.set_fontsize(8)
        table.scale(1, 1.3)
        for j in range(4):
            table[0, j].set_facecolor("#37474F")
            table[0, j].set_text_props(color="white", fontweight="bold")

    ax.set_title("Parameter Recommendations", fontsize=11, fontweight="bold")


def plot_wq_diagnostic_dashboard(
    report,
    report_type: str,
    dates: np.ndarray,
    observed: np.ndarray,
    simulated: np.ndarray,
    obs_flow: Optional[np.ndarray] = None,
    sim_flow: Optional[np.ndarray] = None,
    title: Optional[str] = None,
    figsize: Tuple[int, int] = (16, 14),
    save_path: Optional[str] = None,
) -> plt.Figure:
    """
    Multi-panel water quality diagnostic dashboard.

    Layout varies by report_type:
      - sediment: time series, rating curve, event partition, seasonal bias,
        recommendations (5 panels)
      - phosphorus: time series, flow partition, seasonal bias,
        recommendations (4 panels)
      - nitrogen: time series, seasonal bias, recommendations (3 panels)

    Args:
        report: SedimentDiagnosticReport, PhosphorusDiagnosticReport, or
            NitrogenDiagnosticReport object.
        report_type: One of "sediment", "phosphorus", "nitrogen".
        dates: Date array.
        observed: Observed WQ time series.
        simulated: Simulated WQ time series.
        obs_flow: Observed flow array (needed for sediment rating curve and
            phosphorus flow partition plots). Optional for nitrogen.
        sim_flow: Simulated flow array (needed for sediment rating curve).
            Optional for phosphorus and nitrogen.
        title: Dashboard title. Auto-generated if None.
        figsize: Figure size.
        save_path: Path to save figure.

    Returns:
        matplotlib Figure object.
    """
    if title is None:
        label = report_type.capitalize()
        title = f"{label} Diagnostic Dashboard"

    report_type = report_type.lower()

    if report_type == "sediment":
        return _dashboard_sediment(report, dates, observed, simulated,
                                   obs_flow, sim_flow, title, figsize, save_path)
    elif report_type == "phosphorus":
        return _dashboard_phosphorus(report, dates, observed, simulated,
                                     obs_flow, title, figsize, save_path)
    elif report_type == "nitrogen":
        return _dashboard_nitrogen(report, dates, observed, simulated,
                                   title, figsize, save_path)
    else:
        raise ValueError(
            f"Unknown report_type '{report_type}'. "
            "Expected 'sediment', 'phosphorus', or 'nitrogen'."
        )


def _dashboard_sediment(report, dates, observed, simulated,
                        obs_flow, sim_flow, title, figsize, save_path):
    """Build sediment diagnostic dashboard (5 panels)."""
    fig = plt.figure(figsize=figsize)
    fig.suptitle(title, fontsize=14, fontweight="bold", y=0.98)

    gs = gridspec.GridSpec(3, 2, height_ratios=[1.0, 1.0, 1.0],
                           hspace=0.40, wspace=0.30)

    # --- Panel 1: Time series (full width) ---
    ax1 = fig.add_subplot(gs[0, :])
    ax1.plot(dates, observed, color="#1565C0", linewidth=0.8,
             label="Observed", alpha=0.9)
    ax1.plot(dates, simulated, color="#E53935", linewidth=0.8,
             label="Simulated", alpha=0.8)
    ax1.set_xlabel("Date")
    ax1.set_ylabel("Sediment")
    ax1.set_title("Sediment Time Series", fontsize=11)
    ax1.legend(loc="upper right", fontsize=8)
    ax1.grid(True, alpha=0.2)
    ax1.set_xlim(dates[0], dates[-1])

    # Metrics annotation
    m = report.overall_metrics
    metrics_txt = (
        f"NSE={m.get('nse', np.nan):.3f}  "
        f"PBIAS={m.get('pbias', np.nan):.1f}%  "
        f"R\u00b2={m.get('r_squared', np.nan):.3f}"
    )
    ax1.text(0.01, 0.97, metrics_txt, transform=ax1.transAxes, fontsize=8,
             verticalalignment="top",
             bbox=dict(boxstyle="round,pad=0.3", facecolor="white", alpha=0.85))

    # --- Panel 2: Rating curve (left) ---
    ax2 = fig.add_subplot(gs[1, 0])
    if (obs_flow is not None and sim_flow is not None
            and report.rating_curve):
        plot_rating_curve(obs_flow, observed, sim_flow, simulated,
                          report.rating_curve, title="Rating Curve",
                          ax=ax2)
    else:
        ax2.text(0.5, 0.5, "Rating curve data\nnot available",
                 ha="center", va="center", transform=ax2.transAxes, alpha=0.5)
        ax2.set_title("Rating Curve", fontsize=11)
        ax2.axis("off")

    # --- Panel 3: Event partition (right) ---
    ax3 = fig.add_subplot(gs[1, 1])
    if report.event_partition:
        plot_event_partition(report.event_partition,
                             title="Event Sediment Partition", ax=ax3)
    else:
        ax3.text(0.5, 0.5, "Event partition data\nnot available",
                 ha="center", va="center", transform=ax3.transAxes, alpha=0.5)
        ax3.set_title("Event Sediment Partition", fontsize=11)
        ax3.axis("off")

    # --- Panel 4: Seasonal bias (left bottom) ---
    ax4 = fig.add_subplot(gs[2, 0])
    seasonal = report.seasonal_bias
    if seasonal:
        plot_seasonal_bias(seasonal, title="Seasonal Sediment Bias", ax=ax4)
    else:
        ax4.text(0.5, 0.5, "No seasonal data",
                 ha="center", va="center", transform=ax4.transAxes, alpha=0.5)
        ax4.set_title("Seasonal Sediment Bias", fontsize=11)
        ax4.axis("off")

    # --- Panel 5: Recommendations (right bottom) ---
    ax5 = fig.add_subplot(gs[2, 1])
    _build_recommendations_panel(ax5, report.recommendations)

    if save_path:
        fig.savefig(save_path, dpi=150, bbox_inches="tight")

    return fig


def _dashboard_phosphorus(report, dates, observed, simulated,
                          obs_flow, title, figsize, save_path):  # noqa: ARG001 (obs_flow)
    """Build phosphorus diagnostic dashboard (4 panels).

    obs_flow is accepted for interface consistency with the dispatcher but is
    not used directly -- the flow partition dict is pre-computed in the report.
    """
    fig = plt.figure(figsize=figsize)
    fig.suptitle(title, fontsize=14, fontweight="bold", y=0.98)

    gs = gridspec.GridSpec(3, 2, height_ratios=[1.0, 1.0, 0.9],
                           hspace=0.40, wspace=0.30)

    # --- Panel 1: Time series (full width) ---
    ax1 = fig.add_subplot(gs[0, :])
    ax1.plot(dates, observed, color="#1565C0", linewidth=0.8,
             label="Observed", alpha=0.9)
    ax1.plot(dates, simulated, color="#E53935", linewidth=0.8,
             label="Simulated", alpha=0.8)
    ax1.set_xlabel("Date")
    ax1.set_ylabel("Phosphorus")
    ax1.set_title("Phosphorus Time Series", fontsize=11)
    ax1.legend(loc="upper right", fontsize=8)
    ax1.grid(True, alpha=0.2)
    ax1.set_xlim(dates[0], dates[-1])

    # Metrics annotation
    m = report.overall_metrics
    metrics_txt = (
        f"NSE={m.get('nse', np.nan):.3f}  "
        f"PBIAS={m.get('pbias', np.nan):.1f}%  "
        f"R\u00b2={m.get('r_squared', np.nan):.3f}"
    )
    ax1.text(0.01, 0.97, metrics_txt, transform=ax1.transAxes, fontsize=8,
             verticalalignment="top",
             bbox=dict(boxstyle="round,pad=0.3", facecolor="white", alpha=0.85))

    # --- Panel 2: Flow partition (left) ---
    ax2 = fig.add_subplot(gs[1, 0])
    if report.flow_partition:
        plot_flow_partition(report.flow_partition,
                            title="P Flow Partition PBIAS", ax=ax2)
    else:
        ax2.text(0.5, 0.5, "Flow partition data\nnot available",
                 ha="center", va="center", transform=ax2.transAxes, alpha=0.5)
        ax2.set_title("P Flow Partition PBIAS", fontsize=11)
        ax2.axis("off")

    # --- Panel 3: Seasonal bias (right) ---
    ax3 = fig.add_subplot(gs[1, 1])
    seasonal = report.seasonal_bias
    if seasonal:
        plot_seasonal_bias(seasonal, title="Seasonal P Bias", ax=ax3)
    else:
        ax3.text(0.5, 0.5, "No seasonal data",
                 ha="center", va="center", transform=ax3.transAxes, alpha=0.5)
        ax3.set_title("Seasonal P Bias", fontsize=11)
        ax3.axis("off")

    # --- Panel 4: Recommendations (full width) ---
    ax4 = fig.add_subplot(gs[2, :])
    _build_recommendations_panel(ax4, report.recommendations)

    if save_path:
        fig.savefig(save_path, dpi=150, bbox_inches="tight")

    return fig


def _dashboard_nitrogen(report, dates, observed, simulated,
                        title, figsize, save_path):
    """Build nitrogen diagnostic dashboard (3 panels)."""
    fig = plt.figure(figsize=figsize)
    fig.suptitle(title, fontsize=14, fontweight="bold", y=0.98)

    gs = gridspec.GridSpec(3, 1, height_ratios=[1.2, 1.0, 0.9],
                           hspace=0.40)

    # --- Panel 1: Time series (full width) ---
    ax1 = fig.add_subplot(gs[0])
    ax1.plot(dates, observed, color="#1565C0", linewidth=0.8,
             label="Observed", alpha=0.9)
    ax1.plot(dates, simulated, color="#E53935", linewidth=0.8,
             label="Simulated", alpha=0.8)
    ax1.set_xlabel("Date")
    ax1.set_ylabel("Nitrogen")
    ax1.set_title("Nitrogen Time Series", fontsize=11)
    ax1.legend(loc="upper right", fontsize=8)
    ax1.grid(True, alpha=0.2)
    ax1.set_xlim(dates[0], dates[-1])

    # Metrics annotation
    m = report.overall_metrics
    metrics_txt = (
        f"NSE={m.get('nse', np.nan):.3f}  "
        f"PBIAS={m.get('pbias', np.nan):.1f}%  "
        f"R\u00b2={m.get('r_squared', np.nan):.3f}"
    )
    ax1.text(0.01, 0.97, metrics_txt, transform=ax1.transAxes, fontsize=8,
             verticalalignment="top",
             bbox=dict(boxstyle="round,pad=0.3", facecolor="white", alpha=0.85))

    # --- Panel 2: Seasonal bias ---
    ax2 = fig.add_subplot(gs[1])
    seasonal = report.seasonal_bias
    if seasonal:
        plot_seasonal_bias(seasonal, title="Seasonal N Bias", ax=ax2)
    else:
        ax2.text(0.5, 0.5, "No seasonal data",
                 ha="center", va="center", transform=ax2.transAxes, alpha=0.5)
        ax2.set_title("Seasonal N Bias", fontsize=11)
        ax2.axis("off")

    # --- Panel 3: Recommendations ---
    ax3 = fig.add_subplot(gs[2])
    _build_recommendations_panel(ax3, report.recommendations)

    if save_path:
        fig.savefig(save_path, dpi=150, bbox_inches="tight")

    return fig
