"""
Sensitivity analysis visualization for SWAT model calibration.

Provides tornado plots, ranking tables, and parameter auto-selection
based on sensitivity analysis results from SPOTPY's FAST or Sobol methods.
"""

from typing import Dict, List, Optional, Tuple, Union
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

# Parameter group colors for tornado plot
GROUP_COLORS = {
    "hydrology": "#2196F3",      # blue
    "groundwater": "#4CAF50",    # green
    "soil": "#795548",           # brown
    "routing": "#FF9800",        # orange
    "snow": "#00BCD4",           # cyan
    "sediment": "#9C27B0",       # purple
    "nutrient": "#F44336",       # red
    "plant": "#8BC34A",          # light green
    "general": "#607D8B",        # gray
}


def _normalize_sensitivity_results(
    results: Union[Dict, pd.DataFrame],
    parameter_names: List[str] = None,
) -> pd.DataFrame:
    """Normalize SPOTPY sensitivity results to a standard DataFrame.

    SPOTPY FAST returns either a dict {param: S1} or a DataFrame with 'S1' column.
    This normalizes both to a DataFrame with 'Parameter' and 'S1' columns.
    """
    if isinstance(results, dict):
        df = pd.DataFrame([
            {"Parameter": k, "S1": v}
            for k, v in results.items()
        ])
    elif isinstance(results, pd.DataFrame):
        df = results.copy()
        if "Parameter" not in df.columns:
            if "parameter" in df.columns:
                df = df.rename(columns={"parameter": "Parameter"})
            elif df.index.name:
                df = df.reset_index()
                df = df.rename(columns={df.columns[0]: "Parameter"})
        if "S1" not in df.columns:
            # Look for common column names
            for col in ["s1", "sensitivity", "Si", "si"]:
                if col in df.columns:
                    df = df.rename(columns={col: "S1"})
                    break
    else:
        raise TypeError(f"Expected dict or DataFrame, got {type(results)}")

    if parameter_names and len(parameter_names) == len(df):
        df["Parameter"] = parameter_names

    return df.sort_values("S1", ascending=False).reset_index(drop=True)


def _get_param_group(param_name: str) -> str:
    """Look up parameter group from the CALIBRATION_PARAMETERS registry."""
    try:
        from swat_modern.calibration.parameters import CALIBRATION_PARAMETERS
        p = CALIBRATION_PARAMETERS.get(param_name)
        return p.group if p else "general"
    except ImportError:
        return "general"


def plot_sensitivity_tornado(
    results: Union[Dict, pd.DataFrame],
    parameter_names: List[str] = None,
    title: str = "Parameter Sensitivity Analysis (FAST)",
    top_n: int = 15,
    figsize: Tuple[int, int] = (10, 8),
    ax: Optional[plt.Axes] = None,
    save_path: Optional[str] = None,
) -> plt.Figure:
    """
    Create a horizontal bar chart (tornado plot) of parameter sensitivity indices.

    Bars are sorted by S1 index (most sensitive at top) and colored by
    parameter group (hydrology, groundwater, soil, etc.).

    Args:
        results: Sensitivity results from SPOTPY FAST (dict or DataFrame).
        parameter_names: Override parameter names (if results uses generic names).
        title: Plot title.
        top_n: Show only top N most sensitive parameters.
        figsize: Figure size.
        ax: Existing axes to plot on.
        save_path: Path to save figure.

    Returns:
        matplotlib Figure object.
    """
    df = _normalize_sensitivity_results(results, parameter_names)

    # Limit to top N
    df = df.head(top_n)

    # Reverse order for tornado (most sensitive at top)
    df = df.iloc[::-1].reset_index(drop=True)

    if ax is None:
        fig, ax = plt.subplots(figsize=figsize)
    else:
        fig = ax.get_figure()

    # Color by group
    colors = [GROUP_COLORS.get(_get_param_group(p), GROUP_COLORS["general"])
              for p in df["Parameter"]]

    bars = ax.barh(
        range(len(df)),
        df["S1"],
        color=colors,
        edgecolor="white",
        linewidth=0.5,
        height=0.7,
    )

    ax.set_yticks(range(len(df)))
    ax.set_yticklabels(df["Parameter"], fontsize=10)
    ax.set_xlabel("First-Order Sensitivity Index (S1)", fontsize=11)
    ax.set_title(title, fontsize=13, fontweight="bold")
    ax.axvline(x=0.01, color="gray", linestyle="--", alpha=0.5, label="Threshold (0.01)")

    # Value labels on bars
    for i, (val, bar) in enumerate(zip(df["S1"], bars)):
        ax.text(val + 0.005, i, f"{val:.3f}", va="center", fontsize=9, alpha=0.8)

    # Legend for groups
    unique_groups = []
    seen = set()
    for p in df["Parameter"]:
        g = _get_param_group(p)
        if g not in seen:
            seen.add(g)
            unique_groups.append(g)

    if len(unique_groups) > 1:
        from matplotlib.patches import Patch
        legend_handles = [
            Patch(facecolor=GROUP_COLORS.get(g, GROUP_COLORS["general"]), label=g.capitalize())
            for g in unique_groups
        ]
        ax.legend(handles=legend_handles, loc="lower right", fontsize=8, framealpha=0.8)

    ax.grid(axis="x", alpha=0.3)
    plt.tight_layout()

    if save_path:
        fig.savefig(save_path, dpi=150, bbox_inches="tight")

    return fig


def sensitivity_ranking_table(
    results: Union[Dict, pd.DataFrame],
    parameter_names: List[str] = None,
) -> pd.DataFrame:
    """
    Create a formatted sensitivity ranking table.

    Returns DataFrame with: Rank, Parameter, S1, Group, Description, Suggested.

    Args:
        results: Sensitivity results from SPOTPY FAST.
        parameter_names: Override parameter names.

    Returns:
        Formatted DataFrame suitable for display.
    """
    df = _normalize_sensitivity_results(results, parameter_names)

    # Add metadata from parameter definitions
    try:
        from swat_modern.calibration.parameters import CALIBRATION_PARAMETERS
        has_params = True
    except ImportError:
        has_params = False

    rows = []
    for i, row in df.iterrows():
        rec = {
            "Rank": i + 1,
            "Parameter": row["Parameter"],
            "S1": round(row["S1"], 4),
        }
        if has_params:
            p = CALIBRATION_PARAMETERS.get(row["Parameter"])
            rec["Group"] = p.group.capitalize() if p else "—"
            rec["Description"] = p.description if p else "—"
        rec["Suggested"] = "Yes" if row["S1"] >= 0.01 else "No"
        rows.append(rec)

    return pd.DataFrame(rows)


def get_suggested_parameters(
    results: Union[Dict, pd.DataFrame],
    parameter_names: List[str] = None,
    top_n: int = 10,
    min_threshold: float = 0.01,
) -> List[str]:
    """
    Return the top N most sensitive parameters above the threshold.

    This is the bridge between sensitivity analysis and parameter selection:
    the user can run SA, then auto-populate the calibration parameter list.

    Args:
        results: Sensitivity results from SPOTPY.
        parameter_names: Override parameter names.
        top_n: Maximum number of parameters to suggest.
        min_threshold: Minimum S1 value to include.

    Returns:
        List of parameter names, ordered by sensitivity (most sensitive first).
    """
    df = _normalize_sensitivity_results(results, parameter_names)
    filtered = df[df["S1"] >= min_threshold].head(top_n)
    return filtered["Parameter"].tolist()
