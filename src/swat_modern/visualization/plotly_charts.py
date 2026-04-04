"""
Interactive Plotly charts for SWAT model visualization.

Provides interactive charts for the Streamlit web application,
complementing the existing matplotlib-based visualization modules.
"""

from typing import List, Optional, Tuple, Union

import numpy as np
import pandas as pd

try:
    import plotly.graph_objects as go
    import plotly.express as px
    HAS_PLOTLY = True
except ImportError:
    HAS_PLOTLY = False


def _require_plotly():
    if not HAS_PLOTLY:
        raise ImportError(
            "plotly is required for interactive charts. "
            "Install with: pip install swat-dg[app]"
        )


def plotly_time_series(
    df: pd.DataFrame,
    date_col: Optional[str] = None,
    value_cols: Union[str, List[str]] = None,
    title: str = "Time Series",
    ylabel: str = "Value",
    colors: Optional[List[str]] = None,
    show_rangeslider: bool = True,
    height: int = 450,
) -> "go.Figure":
    """
    Create an interactive Plotly time series plot.

    Args:
        df: DataFrame with date index or date column and value columns.
        date_col: Column name for dates. If None, uses the DataFrame index.
        value_cols: Column name(s) to plot. If None, plots all numeric columns.
        title: Plot title.
        ylabel: Y-axis label.
        colors: Optional list of colors for each trace.
        show_rangeslider: Show date range slider below chart.
        height: Chart height in pixels.

    Returns:
        Plotly Figure object.
    """
    _require_plotly()

    # Determine date axis
    if date_col is not None:
        x = df[date_col]
    elif isinstance(df.index, pd.DatetimeIndex):
        x = df.index
    else:
        x = df.index

    # Determine value columns
    if value_cols is None:
        value_cols = [c for c in df.select_dtypes(include=[np.number]).columns
                      if c != date_col]
    elif isinstance(value_cols, str):
        value_cols = [value_cols]

    # Default colors
    if colors is None:
        colors = px.colors.qualitative.Set2

    fig = go.Figure()

    for i, col in enumerate(value_cols):
        color = colors[i % len(colors)]
        fig.add_trace(go.Scatter(
            x=x,
            y=df[col],
            mode="lines",
            name=col,
            line=dict(color=color, width=1.5),
            hovertemplate=f"{col}: %{{y:.3f}}<extra></extra>",
        ))

    fig.update_layout(
        title=title,
        yaxis_title=ylabel,
        xaxis_title="Date",
        height=height,
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        template="plotly_white",
    )

    if show_rangeslider:
        fig.update_xaxes(rangeslider_visible=True)

    return fig


def plotly_multi_variable(
    df: pd.DataFrame,
    date_col: Optional[str] = None,
    variables: List[str] = None,
    title: str = "Multi-Variable Comparison",
    secondary_y_vars: Optional[List[str]] = None,
    ylabel_primary: str = "Primary",
    ylabel_secondary: str = "Secondary",
    height: int = 500,
) -> "go.Figure":
    """
    Plot multiple variables with optional dual y-axes.

    Args:
        df: DataFrame with date index or column and variable columns.
        date_col: Date column name. If None, uses index.
        variables: List of variable column names to plot.
        title: Plot title.
        secondary_y_vars: Variables to plot on secondary y-axis.
        ylabel_primary: Primary y-axis label.
        ylabel_secondary: Secondary y-axis label.
        height: Chart height in pixels.

    Returns:
        Plotly Figure object.
    """
    _require_plotly()
    from plotly.subplots import make_subplots

    if variables is None:
        variables = [c for c in df.select_dtypes(include=[np.number]).columns
                      if c != date_col]

    if secondary_y_vars is None:
        secondary_y_vars = []

    has_secondary = len(secondary_y_vars) > 0

    fig = make_subplots(specs=[[{"secondary_y": has_secondary}]])

    if date_col is not None:
        x = df[date_col]
    elif isinstance(df.index, pd.DatetimeIndex):
        x = df.index
    else:
        x = df.index

    colors = px.colors.qualitative.Set2

    for i, var in enumerate(variables):
        if var not in df.columns:
            continue
        is_secondary = var in secondary_y_vars
        fig.add_trace(
            go.Scatter(
                x=x,
                y=df[var],
                name=var,
                line=dict(color=colors[i % len(colors)], width=1.5),
            ),
            secondary_y=is_secondary,
        )

    fig.update_layout(
        title=title,
        height=height,
        hovermode="x unified",
        template="plotly_white",
    )
    fig.update_yaxes(title_text=ylabel_primary, secondary_y=False)
    if has_secondary:
        fig.update_yaxes(title_text=ylabel_secondary, secondary_y=True)

    return fig


def plotly_bar_summary(
    df: pd.DataFrame,
    category_col: str,
    value_col: str,
    title: str = "Summary",
    color: str = "#3388ff",
    orientation: str = "v",
    height: int = 400,
) -> "go.Figure":
    """
    Create a bar chart for summary statistics.

    Args:
        df: DataFrame with category and value columns.
        category_col: Column for categories (x-axis or y-axis).
        value_col: Column for values.
        title: Plot title.
        color: Bar color.
        orientation: 'v' for vertical, 'h' for horizontal.
        height: Chart height in pixels.

    Returns:
        Plotly Figure object.
    """
    _require_plotly()

    if orientation == "h":
        fig = go.Figure(go.Bar(
            x=df[value_col],
            y=df[category_col],
            orientation="h",
            marker_color=color,
        ))
        fig.update_layout(yaxis_title=category_col, xaxis_title=value_col)
    else:
        fig = go.Figure(go.Bar(
            x=df[category_col],
            y=df[value_col],
            marker_color=color,
        ))
        fig.update_layout(xaxis_title=category_col, yaxis_title=value_col)

    fig.update_layout(
        title=title,
        height=height,
        template="plotly_white",
    )

    return fig


def plotly_scatter_comparison(
    observed: pd.Series,
    simulated: pd.Series,
    title: str = "Observed vs Simulated",
    xlabel: str = "Observed",
    ylabel: str = "Simulated",
    height: int = 450,
) -> "go.Figure":
    """
    Scatter plot comparing observed and simulated values with 1:1 line.

    Args:
        observed: Observed values.
        simulated: Simulated values.
        title: Plot title.
        xlabel: X-axis label.
        ylabel: Y-axis label.
        height: Chart height.

    Returns:
        Plotly Figure object.
    """
    _require_plotly()

    obs = np.asarray(observed).flatten()
    sim = np.asarray(simulated).flatten()

    # Remove NaN
    mask = ~(np.isnan(obs) | np.isnan(sim))
    obs = obs[mask]
    sim = sim[mask]

    min_val = min(obs.min(), sim.min())
    max_val = max(obs.max(), sim.max())

    fig = go.Figure()

    fig.add_trace(go.Scatter(
        x=obs, y=sim,
        mode="markers",
        marker=dict(size=5, opacity=0.5, color="#3388ff"),
        name="Data",
    ))

    # 1:1 line
    fig.add_trace(go.Scatter(
        x=[min_val, max_val],
        y=[min_val, max_val],
        mode="lines",
        line=dict(color="black", dash="dash", width=1.5),
        name="1:1 Line",
    ))

    fig.update_layout(
        title=title,
        xaxis_title=xlabel,
        yaxis_title=ylabel,
        height=height,
        template="plotly_white",
        xaxis=dict(scaleanchor="y", scaleratio=1),
    )

    return fig
