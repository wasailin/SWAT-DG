"""
Simulation optimization for SWAT2012 calibration.

Provides tools to reduce calibration runtime by:
1. Partial-basin simulation via fig.fig truncation
2. Output I/O optimization

IMPORTANT LIMITATION - SWAT2012 Subprocess Control:
SWAT2012 is a compiled Fortran executable. Sediment, nutrient, and bacteria
calculations are hard-coded into the main simulation loop. There is NO
runtime flag to disable these processes. The only ways to avoid computing
them are:
- Use a modified/recompiled SWAT executable (streamflow-only build)
- Use partial-basin simulation (fig.fig truncation) to reduce the NUMBER
  of subbasins simulated, which proportionally reduces all computations

The primary optimization available at runtime is partial-basin simulation,
which skips entire downstream subbasins when the calibration target is
not at the watershed outlet.
"""

from pathlib import Path
from typing import Dict, Optional

from swat_modern.io.parsers.fig_parser import FigFileParser


class SimulationOptimizer:
    """
    Optimizes SWAT2012 simulation settings for calibration speed.

    Handles the optimizations possible within SWAT2012's constraints:
    - Partial-basin simulation via fig.fig truncation
    - Speedup estimation

    Example:
        >>> optimizer = SimulationOptimizer(model)
        >>> info = optimizer.analyze(target_reach=5)
        >>> print(info["estimated_speedup"])
        >>> optimizer.apply_partial_basin(target_reach=5)
    """

    def __init__(self, model):
        """
        Initialize optimizer.

        Args:
            model: SWATModel instance
        """
        self.model = model
        self._topology = None
        self._original_fig_backup = None

    def analyze(
        self,
        target_reach: Optional[int] = None,
    ) -> Dict:
        """
        Analyze potential optimizations for the current model.

        Args:
            target_reach: The reach where calibration target is located.
                If None, assumes outlet (no partial-basin possible).

        Returns:
            Dict with analysis results:
            - total_subbasins: Total subbasins in the model
            - target_subbasins: Subbasins needed for target reach
            - estimated_speedup: Estimated speedup factor
            - partial_basin_possible: Whether truncation would help
            - subprocess_info: Info about SWAT2012 limitations
        """
        topology = self._get_topology()
        total_subs = len(topology.subbasins)
        outlet = topology.get_outlet_reach()

        result = {
            "total_subbasins": total_subs,
            "total_reaches": len(topology.reaches),
            "outlet_reach": outlet,
            "partial_basin_possible": False,
            "target_subbasins": total_subs,
            "estimated_speedup": 1.0,
            "subprocess_info": self.get_subprocess_info(),
        }

        if target_reach is not None and target_reach != outlet:
            upstream_subs = topology.get_upstream_subbasins(target_reach)
            n_upstream = len(upstream_subs)

            if n_upstream < total_subs:
                result["partial_basin_possible"] = True
                result["target_subbasins"] = n_upstream
                # Speedup is roughly proportional to subbasin reduction
                result["estimated_speedup"] = (
                    total_subs / n_upstream if n_upstream > 0 else 1.0
                )
                result["upstream_subbasins"] = sorted(upstream_subs)

        return result

    def apply_partial_basin(
        self,
        target_reach: int,
        output_path: Optional[Path] = None,
    ) -> Optional[Path]:
        """
        Generate a truncated fig.fig for partial-basin simulation.

        Args:
            target_reach: Stop routing at this reach
            output_path: Where to write the truncated fig.fig.
                Defaults to project_dir/fig_partial.fig

        Returns:
            Path to the truncated fig.fig, or None if not needed
        """
        topology = self._get_topology()
        outlet = topology.get_outlet_reach()

        if target_reach == outlet:
            return None

        if output_path is None:
            output_path = self.model.project_dir / "fig_partial.fig"

        topology.build_truncated_fig(target_reach, output_path)
        return output_path

    def _get_topology(self) -> FigFileParser:
        """Parse topology (cached)."""
        if self._topology is None:
            fig_path = self.model.project_dir / "fig.fig"
            self._topology = FigFileParser(fig_path)
            self._topology.parse()
        return self._topology

    @staticmethod
    def get_subprocess_info() -> Dict:
        """
        Return information about SWAT2012 subprocess limitations.

        This is used by the UI to display an informational message
        to users about what can and cannot be optimized.
        """
        return {
            "can_disable_sediment": False,
            "can_disable_nutrients": False,
            "can_disable_bacteria": False,
            "can_disable_pesticides": False,
            "reason": (
                "SWAT2012 is a compiled Fortran executable. Sediment, nutrient, "
                "bacteria, and pesticide calculations are hard-coded into the "
                "main simulation loop and cannot be disabled at runtime."
            ),
            "recommendation": (
                "For streamflow-only calibration, the primary speedup comes from "
                "partial-basin simulation (skipping downstream subbasins). "
                "If additional speed is needed, consider using a streamflow-only "
                "SWAT build (recompiled with unnecessary process code removed)."
            ),
            "available_optimizations": [
                "Partial-basin simulation (fig.fig truncation)",
                "Reduced output writing (IPRINT settings)",
            ],
        }

    def get_topology_summary(self) -> str:
        """Get human-readable topology summary."""
        topology = self._get_topology()
        return topology.get_topology_summary()
