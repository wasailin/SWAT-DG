"""
SWAT-DG Streamlit Application.

A user-friendly web interface for SWAT model calibration and visualization.
Runs 100% locally on your computer.

Launch with:
    streamlit run src/swat_modern/app/main.py

Or from Python:
    from swat_modern.app import run_app
    run_app()
"""

import subprocess
import sys
from pathlib import Path


def run_app():
    """Launch the Streamlit calibration app."""
    app_path = Path(__file__).parent / "main.py"
    subprocess.run([sys.executable, "-m", "streamlit", "run", str(app_path)])


__all__ = ["run_app"]
