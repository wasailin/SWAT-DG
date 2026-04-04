"""
SWAT+ to SWAT 2012 format converter.

Converts SWAT+ TxtInOut files to SWAT 2012 format for use with
the SWAT-DG calibration tool.
"""

from .converter import SWATplusToSWAT2012Converter

__all__ = ["SWATplusToSWAT2012Converter"]
