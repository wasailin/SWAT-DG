"""
Shared loading indication utilities for SWAT-DG Streamlit app.

Provides reusable components for consistent loading feedback across all pages:
- Shimmer/skeleton CSS animations
- Skeleton placeholder functions for metrics, dataframes, charts, and text
- Multi-step status wrapper
- Animated progress bar CSS override
- Standardized page guards
"""

import streamlit as st


# ---------------------------------------------------------------------------
# CSS Injection
# ---------------------------------------------------------------------------

_SHIMMER_CSS = """
<style>
@keyframes shimmer {
    0% { background-position: -200% 0; }
    100% { background-position: 200% 0; }
}
.shimmer-placeholder {
    background: linear-gradient(90deg, #f0f0f0 25%, #e0e0e0 50%, #f0f0f0 75%);
    background-size: 200% 100%;
    animation: shimmer 1.5s infinite;
    border-radius: 4px;
}
.shimmer-metric-box {
    background: linear-gradient(90deg, #f0f0f0 25%, #e0e0e0 50%, #f0f0f0 75%);
    background-size: 200% 100%;
    animation: shimmer 1.5s infinite;
    border-radius: 8px;
    padding: 1rem;
    height: 80px;
}
.shimmer-chart-box {
    background: linear-gradient(90deg, #f0f0f0 25%, #e0e0e0 50%, #f0f0f0 75%);
    background-size: 200% 100%;
    animation: shimmer 1.5s infinite;
    border-radius: 8px;
    width: 100%;
}
.shimmer-text-line {
    background: linear-gradient(90deg, #f0f0f0 25%, #e0e0e0 50%, #f0f0f0 75%);
    background-size: 200% 100%;
    animation: shimmer 1.5s infinite;
    border-radius: 4px;
    height: 14px;
    margin-bottom: 8px;
}
.shimmer-table-row {
    display: flex;
    gap: 8px;
    margin-bottom: 6px;
}
.shimmer-table-cell {
    background: linear-gradient(90deg, #f0f0f0 25%, #e0e0e0 50%, #f0f0f0 75%);
    background-size: 200% 100%;
    animation: shimmer 1.5s infinite;
    border-radius: 4px;
    height: 16px;
    flex: 1;
}
</style>
"""

_PROGRESS_CSS = """
<style>
/* Animated gradient sweep on Streamlit progress bars */
.stProgress > div > div > div {
    background: linear-gradient(
        90deg,
        #2e7d32 0%,
        #43a047 25%,
        #2e7d32 50%,
        #43a047 75%,
        #2e7d32 100%
    ) !important;
    background-size: 200% 100% !important;
    animation: progress-sweep 2s linear infinite !important;
    border-radius: 4px;
}
@keyframes progress-sweep {
    0% { background-position: 200% 0; }
    100% { background-position: -200% 0; }
}
@keyframes pulse {
    0%, 100% { opacity: 1; transform: scale(1); }
    50% { opacity: 0.7; transform: scale(1.1); }
}
</style>
"""


_HIDE_DEPLOY_CSS = '<style>[data-testid="stAppDeployButton"] { display: none; }</style>'


def hide_deploy_button():
    """Hide the Streamlit 'Deploy' button in the toolbar. Call once per page."""
    st.markdown(_HIDE_DEPLOY_CSS, unsafe_allow_html=True)


def inject_shimmer_css():
    """Inject shimmer/skeleton animation CSS into the page. Call once per page."""
    st.markdown(_SHIMMER_CSS, unsafe_allow_html=True)


def inject_progress_css():
    """Inject animated gradient CSS for st.progress bars. Call once per page."""
    st.markdown(_PROGRESS_CSS, unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Skeleton Placeholders
# ---------------------------------------------------------------------------

def skeleton_metrics(n_cols: int = 3):
    """Render N shimmer placeholder metric boxes in columns."""
    cols = st.columns(n_cols)
    for col in cols:
        with col:
            st.markdown(
                '<div class="shimmer-metric-box"></div>',
                unsafe_allow_html=True,
            )


def skeleton_dataframe(n_rows: int = 5, n_cols: int = 4):
    """Render a shimmer placeholder table."""
    # Header row
    header_cells = "".join(
        '<div class="shimmer-table-cell" style="height:18px;"></div>'
        for _ in range(n_cols)
    )
    rows_html = f'<div class="shimmer-table-row">{header_cells}</div>'

    # Data rows
    for _ in range(n_rows):
        cells = "".join(
            '<div class="shimmer-table-cell"></div>' for _ in range(n_cols)
        )
        rows_html += f'<div class="shimmer-table-row">{cells}</div>'

    st.markdown(
        f'<div style="padding: 0.5rem 0;">{rows_html}</div>',
        unsafe_allow_html=True,
    )


def skeleton_chart(height: int = 200):
    """Render a shimmer placeholder chart area."""
    st.markdown(
        f'<div class="shimmer-chart-box" style="height:{height}px;"></div>',
        unsafe_allow_html=True,
    )


def skeleton_text(n_lines: int = 3):
    """Render shimmer placeholder text lines with varying widths."""
    widths = [100, 85, 70, 90, 60]
    lines_html = ""
    for i in range(n_lines):
        w = widths[i % len(widths)]
        lines_html += f'<div class="shimmer-text-line" style="width:{w}%;"></div>'
    st.markdown(lines_html, unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Multi-step Loading Status
# ---------------------------------------------------------------------------

class LoadingStatus:
    """Context manager wrapping st.status with step tracking.

    Usage::

        with loading_status("Loading project...", ["Reading config", "Scanning files"]) as status:
            status.step(0)
            ...
            status.step(1)
            ...
            status.complete("Project loaded successfully")
    """

    def __init__(self, label: str, steps: list):
        self._status = st.status(label, expanded=True)
        self._steps = steps

    def __enter__(self):
        self._status.__enter__()
        return self

    def step(self, index: int):
        """Activate a step by index, showing its label."""
        if 0 <= index < len(self._steps):
            st.write(f"⏳ {self._steps[index]}...")

    def complete(self, label: str = None):
        """Mark the status as complete with an optional summary label."""
        self._status.update(
            label=label or "Done",
            state="complete",
            expanded=False,
        )

    def error(self, label: str = None):
        """Mark the status as error with an optional summary label."""
        self._status.update(
            label=label or "Error",
            state="error",
        )

    def __exit__(self, *args):
        return self._status.__exit__(*args)


def loading_status(label: str, steps: list) -> LoadingStatus:
    """Create a multi-step loading status indicator.

    Parameters
    ----------
    label : str
        Initial label shown in the status header.
    steps : list of str
        Step descriptions to show as progress advances.

    Returns
    -------
    LoadingStatus
        Context manager with .step(i), .complete(), and .error() methods.
    """
    return LoadingStatus(label, steps)


# ---------------------------------------------------------------------------
# Page Guards
# ---------------------------------------------------------------------------

def page_requires_project() -> bool:
    """Check if a SWAT project is loaded; show standardized message and stop if not.

    Returns True if the project exists in session state.
    """
    if "project_path" not in st.session_state:
        st.warning("Please load a SWAT project first in **Project Setup**.")
        st.info(
            "Navigate to **Project Setup** in the sidebar to load your "
            "SWAT project folder."
        )
        st.stop()
    return True
