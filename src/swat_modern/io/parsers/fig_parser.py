"""
Parser for SWAT2012 fig.fig routing file.

Extracts watershed routing topology from an existing fig.fig file,
enabling upstream/downstream analysis, partial-basin simulation,
and sequential calibration.

The fig.fig file defines the watershed routing order using commands:
- icode=1 (subbasin): defines a subbasin contribution
- icode=2 (route): routes flow through a reach/channel
- icode=5 (add): adds flows at confluences
- icode=0 (finish): marks the end of routing

Fortran format 5000: (a1,9x,5i6,f6.3,i9,i3,3a3)
  col  1:    any char (a1)
  col  2-10: skip (9x)
  col 11-16: icodes  (i6) - command code
  col 17-22: ihouts  (i6) - hydrograph storage location
  col 23-28: inum1s  (i6) - subbasin# or reach#
  col 29-34: inum2s  (i6) - inflow hyd location
  col 35-40: inum3s  (i6)
  col 41-46: rnum1s  (f6.3)
  col 47-55: inum4s  (i9) - GIS code
"""

from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
from collections import defaultdict
import logging

logger = logging.getLogger(__name__)


class FigFileParser:
    """
    Parses fig.fig to extract routing topology.

    Provides methods for upstream/downstream traversal and
    generation of truncated fig.fig for partial-basin simulation.

    Example:
        >>> parser = FigFileParser("C:/project/fig.fig")
        >>> parser.parse()
        >>> upstream = parser.get_upstream_subbasins(reach_id=5)
        >>> parser.build_truncated_fig(terminal_reach=5, output_path="fig_partial.fig")
    """

    def __init__(self, fig_path):
        self.fig_path = Path(fig_path)
        self.commands: List[dict] = []
        self.subbasins: List[int] = []
        self.reaches: List[int] = []
        # reach -> downstream reach (None = outlet)
        self.reach_graph: Dict[int, Optional[int]] = {}
        # subbasin -> reach it feeds into
        self.subbasin_to_reach: Dict[int, int] = {}
        # reach -> list of subbasins that directly feed it
        self.reach_to_subbasins: Dict[int, List[int]] = defaultdict(list)
        self._parsed = False

    def parse(self) -> dict:
        """
        Parse fig.fig and extract topology.

        Returns:
            dict with keys: subbasins, reaches, reach_graph,
            subbasin_to_reach, outlet_reach
        """
        if not self.fig_path.exists():
            raise FileNotFoundError(f"fig.fig not found: {self.fig_path}")

        with open(self.fig_path, "r") as f:
            lines = f.readlines()

        self.commands = []
        self.subbasins = []
        self.reaches = []
        self.reach_graph = {}
        self.subbasin_to_reach = {}
        self.reach_to_subbasins = defaultdict(list)

        # Track hydrograph storage locations
        # hyd_loc -> what produced it (type, id)
        hyd_source: Dict[int, Tuple[str, int]] = {}
        # hyd_loc -> which reach's routing produced it
        hyd_from_route: Dict[int, int] = {}
        # hyd_loc -> combined hyd (for add commands)
        hyd_combined: Dict[int, List[int]] = {}

        i = 0
        while i < len(lines):
            line = lines[i]
            cmd = self._parse_command_line(line)

            if cmd is None:
                i += 1
                continue

            # Read associated file reference line if applicable.
            # SWAT's readfig.f reads a second line (filename) after
            # these icodes: 1 (subbasin), 2 (route), 14 (saveconc),
            # 3 (routres), 13 (recday), 17 (recmon), 6 (rechour).
            # If the parser misses a file line, build_truncated_fig
            # drops it and SWAT hits EOF trying to read fig.fig.
            _ICODES_WITH_FILE_LINE = {1, 2, 3, 6, 13, 14, 17}
            file_line = None
            if cmd["icode"] in _ICODES_WITH_FILE_LINE and i + 1 < len(lines):
                file_line = lines[i + 1]
                cmd["file_line"] = file_line.rstrip("\n")
                i += 2
            else:
                cmd["file_line"] = None
                i += 1

            cmd["raw_line"] = line.rstrip("\n")
            self.commands.append(cmd)

            if cmd["icode"] == 0:
                # Finish
                break
            elif cmd["icode"] == 1:
                # Subbasin command
                sub_id = cmd["inum1"]
                ihout = cmd["ihout"]
                if sub_id > 0:
                    self.subbasins.append(sub_id)
                    hyd_source[ihout] = ("subbasin", sub_id)
            elif cmd["icode"] == 2:
                # Route command
                reach_id = cmd["inum1"]
                inflow_hyd = cmd["inum2"]
                ihout = cmd["ihout"]
                if reach_id > 0:
                    self.reaches.append(reach_id)
                    hyd_from_route[ihout] = reach_id
                    # Map subbasin(s) feeding this route via inflow_hyd
                    self._trace_subbasins_to_reach(
                        inflow_hyd, reach_id, hyd_source, hyd_combined
                    )
            elif cmd["icode"] == 5:
                # Add command - combines two hyd locations
                ihout = cmd["ihout"]
                hyd1 = cmd["inum1"]
                hyd2 = cmd["inum2"]
                combined = []
                combined.extend(hyd_combined.get(hyd1, [hyd1]))
                combined.extend(hyd_combined.get(hyd2, [hyd2]))
                hyd_combined[ihout] = combined

                # Track reach connectivity from add commands
                # If hyd1 or hyd2 comes from a route, the downstream
                # reach is the one that uses this combined hyd
                for h in [hyd1, hyd2]:
                    if h in hyd_from_route:
                        # This routed output is being added - the reach
                        # it came from is upstream of whatever uses ihout
                        pass  # Will be resolved when next route uses ihout

        # Build reach connectivity graph
        self._build_reach_graph()

        self._parsed = True

        return {
            "subbasins": self.subbasins,
            "reaches": self.reaches,
            "reach_graph": dict(self.reach_graph),
            "subbasin_to_reach": dict(self.subbasin_to_reach),
            "outlet_reach": self.get_outlet_reach(),
        }

    def _parse_command_line(self, line: str) -> Optional[dict]:
        """Parse a fig.fig command line using fixed-width format."""
        if len(line.strip()) < 16:
            return None

        try:
            # Pad line to at least 55 chars for safe slicing
            padded = line.ljust(56)

            icode = int(padded[10:16].strip() or "0")
            ihout = int(padded[16:22].strip() or "0")
            inum1 = int(padded[22:28].strip() or "0")
            inum2 = int(padded[28:34].strip() or "0")
            inum3 = int(padded[34:40].strip() or "0")

            try:
                rnum1 = float(padded[40:46].strip() or "0")
            except ValueError:
                rnum1 = 0.0

            try:
                inum4 = int(padded[46:55].strip() or "0")
            except ValueError:
                inum4 = 0

            return {
                "icode": icode,
                "ihout": ihout,
                "inum1": inum1,
                "inum2": inum2,
                "inum3": inum3,
                "rnum1": rnum1,
                "inum4": inum4,
            }
        except (ValueError, IndexError):
            return None

    def _trace_subbasins_to_reach(
        self,
        inflow_hyd: int,
        reach_id: int,
        hyd_source: Dict[int, Tuple[str, int]],
        hyd_combined: Dict[int, List[int]],
    ) -> None:
        """Trace which subbasins feed into a reach via hydrograph locations."""
        # The inflow_hyd may be:
        # 1. Directly from a subbasin command
        # 2. From an add command combining multiple sources
        hyds_to_check = hyd_combined.get(inflow_hyd, [inflow_hyd])

        for hyd in hyds_to_check:
            if hyd in hyd_source:
                source_type, source_id = hyd_source[hyd]
                if source_type == "subbasin":
                    self.subbasin_to_reach[source_id] = reach_id
                    self.reach_to_subbasins[reach_id].append(source_id)

    def _build_reach_graph(self) -> None:
        """
        Build directed graph: reach -> downstream reach.

        In SWAT fig.fig, each route command receives flow from a single
        local subbasin.  Accumulated upstream flow is merged via add
        commands *after* the route.  So reach connectivity cannot be
        derived from route-command inputs alone; instead we track which
        subbasins (and therefore reaches) contribute to each hydrograph
        through the add chain.
        """
        # --- Step 1: track subbasins contributing to each hyd location ---
        subs_in_hyd: Dict[int, Set[int]] = {}
        reaches_in_hyd: Dict[int, Set[int]] = {}

        for cmd in self.commands:
            ihout = cmd["ihout"]
            if cmd["icode"] == 1:  # subbasin
                subs_in_hyd[ihout] = {cmd["inum1"]}
                reaches_in_hyd[ihout] = set()
            elif cmd["icode"] == 2:  # route
                inflow = cmd["inum2"]
                subs_in_hyd[ihout] = subs_in_hyd.get(inflow, set()).copy()
                reaches_in_hyd[ihout] = {cmd["inum1"]}
            elif cmd["icode"] == 5:  # add
                hyd1, hyd2 = cmd["inum1"], cmd["inum2"]
                subs_in_hyd[ihout] = (
                    subs_in_hyd.get(hyd1, set())
                    | subs_in_hyd.get(hyd2, set())
                )
                reaches_in_hyd[ihout] = (
                    reaches_in_hyd.get(hyd1, set())
                    | reaches_in_hyd.get(hyd2, set())
                )

        # --- Step 2: for each reach, find its accumulated hyd ---------
        # Two sub-sets are tracked:
        #
        #  _reach_upstream_subs:  subbasins in the route's OUTPUT hydrograph
        #     (= route input subs, which already include upstream for
        #     accumulated routing).  Correct for upstream detection in
        #     accumulated-routing models.
        #
        #  _reach_accumulated_subs:  subbasins after following the ADD chain
        #     past the route.  Correct for local-only routing models where
        #     you need to sum FLOW_OUT across all contributing reaches.
        reach_upstream_subs: Dict[int, Set[int]] = {}
        reach_accumulated_subs: Dict[int, Set[int]] = {}

        for i, cmd in enumerate(self.commands):
            if cmd["icode"] != 2:
                continue
            reach_id = cmd["inum1"]

            # Subs at route output (before downstream ADD merges)
            reach_upstream_subs[reach_id] = subs_in_hyd.get(
                cmd["ihout"], set()
            ).copy()

            # Follow the ADD chain after the route
            acc_hyd = cmd["ihout"]
            for j in range(i + 1, len(self.commands)):
                nxt = self.commands[j]
                if nxt["icode"] == 5:
                    if nxt["inum1"] == acc_hyd or nxt["inum2"] == acc_hyd:
                        acc_hyd = nxt["ihout"]
                elif nxt["icode"] in (1, 2, 0):
                    break

            reach_accumulated_subs[reach_id] = subs_in_hyd.get(
                acc_hyd, set()
            )

        # Store for use by get_upstream_subbasins
        self._reach_upstream_subs = reach_upstream_subs
        self._reach_accumulated_subs = reach_accumulated_subs

        # --- Step 3: derive reach_graph from accumulated sub sets ------
        # Reach R's immediate downstream D is the reach with the smallest
        # accumulated-sub set that strictly contains R's set.
        self.reach_graph = {}
        for r in self.reaches:
            r_subs = reach_accumulated_subs.get(r, set())
            best_down = None
            best_size = float("inf")
            for d in self.reaches:
                if d == r:
                    continue
                d_subs = reach_accumulated_subs.get(d, set())
                if r_subs < d_subs and len(d_subs) < best_size:
                    best_down = d
                    best_size = len(d_subs)
            self.reach_graph[r] = best_down

    def get_outlet_reach(self) -> Optional[int]:
        """Find the most downstream reach (outlet)."""
        if not self._parsed:
            raise RuntimeError("Call parse() first")

        if not self.reaches:
            return None

        # Outlet = reach that is not upstream of any other reach
        all_upstream = set(self.reach_graph.keys())
        downstream_targets = {
            v for v in self.reach_graph.values() if v is not None
        }

        # Reaches that appear as downstream targets but are not upstream
        # of anything else
        candidates = downstream_targets - {
            k for k, v in self.reach_graph.items() if v is not None
        }

        # If no clear candidate, find reach with no downstream
        if not candidates:
            candidates = {
                r for r in self.reaches
                if self.reach_graph.get(r) is None
            }

        if len(candidates) == 1:
            return candidates.pop()

        # Multiple outlets possible; pick the one with most upstream reaches
        if candidates:
            return max(
                candidates,
                key=lambda r: len(self.get_upstream_reaches(r)),
            )

        # Fallback: last reach in the list (routing order)
        return self.reaches[-1] if self.reaches else None

    def get_upstream_reaches(self, reach_id: int) -> Set[int]:
        """Get all reaches upstream of a given reach (exclusive)."""
        if not self._parsed:
            raise RuntimeError("Call parse() first")

        # Build reverse graph: downstream -> set of upstream
        reverse = defaultdict(set)
        for up, down in self.reach_graph.items():
            if down is not None:
                reverse[down].add(up)

        # BFS upstream
        upstream = set()
        queue = list(reverse.get(reach_id, set()))

        while queue:
            current = queue.pop(0)
            if current in upstream:
                continue
            upstream.add(current)
            queue.extend(reverse.get(current, set()))

        return upstream

    def get_upstream_subbasins(self, reach_id: int) -> Set[int]:
        """
        Get all subbasins upstream of a given reach (inclusive of
        subbasins that directly feed into the reach).

        For **accumulated routing** models (standard QSWAT/ArcSWAT), uses
        the route's input hydrograph subs — these already include all
        upstream contributions and do NOT include downstream or sister
        branches that merge after the route.

        For **local-only routing** models (SWAT+-converted), uses the
        ADD-chain accumulated subs — the full set of reaches whose
        FLOW_OUT must be summed to get total flow at this reach.
        """
        if not self._parsed:
            raise RuntimeError("Call parse() first")

        if hasattr(self, "_reach_accumulated_subs"):
            # For accumulated routing, use the route-input subs (correct
            # upstream set without downstream/sister contamination).
            if self.has_accumulated_routing() and hasattr(
                self, "_reach_upstream_subs"
            ):
                return self._reach_upstream_subs.get(
                    reach_id, set()
                ).copy()
            return self._reach_accumulated_subs.get(reach_id, set()).copy()

        # Fallback: traverse reach_graph + reach_to_subbasins
        upstream_reaches = self.get_upstream_reaches(reach_id)
        upstream_reaches.add(reach_id)
        subbasins = set()
        for r in upstream_reaches:
            subbasins.update(self.reach_to_subbasins.get(r, []))
        return subbasins

    def get_reach_for_subbasin(self, subbasin_id: int) -> Optional[int]:
        """
        Get the reach that a subbasin feeds into.

        In many SWAT models, subbasin N does NOT correspond to reach N.
        For example, in the UIRW model subbasin 10 feeds reach 15, while
        reach 10 receives water from subbasin 22.

        Returns:
            Reach ID, or None if the subbasin is not found.
        """
        if not self._parsed:
            raise RuntimeError("Call parse() first")
        return self.subbasin_to_reach.get(subbasin_id)

    def get_upstream_subbasins_by_subbasin(self, subbasin_id: int) -> Set[int]:
        """
        Get all subbasins upstream of a given subbasin (inclusive).

        This is a convenience wrapper that translates a subbasin ID to its
        corresponding reach ID, then calls get_upstream_subbasins().

        In many SWAT models, subbasin numbers differ from reach numbers.
        For example, in UIRW:
            - get_upstream_subbasins(10) returns {22} (reach 10 routes sub 22)
            - get_upstream_subbasins_by_subbasin(10) returns {10, 12, 13, 16, 17}
              (all subs draining through subbasin 10's outlet)

        Args:
            subbasin_id: The subbasin number (NOT reach number).

        Returns:
            Set of upstream subbasin IDs (inclusive of subbasin_id itself).

        Raises:
            ValueError: If the subbasin_id is not found in the fig.fig topology.
        """
        if not self._parsed:
            raise RuntimeError("Call parse() first")

        reach_id = self.subbasin_to_reach.get(subbasin_id)
        if reach_id is None:
            raise ValueError(
                f"Subbasin {subbasin_id} not found in fig.fig. "
                f"Available subbasins: {sorted(self.subbasins)}"
            )

        return self.get_upstream_subbasins(reach_id)

    def has_accumulated_routing(self) -> bool:
        """
        Check if any route command receives accumulated (ADD) flow as input.

        In some SWAT models (e.g. UIRW), every route command takes only
        local subbasin output as input.  ADD commands combine flows AFTER
        routing, so output.rch FLOW_OUT contains only local subbasin flow,
        NOT accumulated upstream flow.

        In other models (typical ArcSWAT), downstream routes receive ADD
        results, so output.rch FLOW_OUT IS accumulated.

        Returns:
            True if at least one route command receives accumulated flow
            (i.e., its input hydrograph comes from an ADD command).
        """
        if not self._parsed:
            raise RuntimeError("Call parse() first")

        add_outputs: set = set()
        for cmd in self.commands:
            if cmd["icode"] == 5:
                add_outputs.add(cmd["ihout"])
            elif cmd["icode"] == 2:
                if cmd["inum2"] in add_outputs:
                    return True
        return False

    def get_subbasins_between(
        self,
        upstream_reach: int,
        downstream_reach: int,
    ) -> Set[int]:
        """
        Get subbasins between two reaches.

        Returns subbasins upstream of downstream_reach but NOT upstream
        of (or at) upstream_reach. Useful for identifying the calibration
        group between two observation sites.
        """
        downstream_subs = self.get_upstream_subbasins(downstream_reach)
        upstream_subs = self.get_upstream_subbasins(upstream_reach)
        return downstream_subs - upstream_subs

    def build_truncated_fig(
        self,
        terminal_reach: int,
        output_path,
        active_subbasins: Optional[Set[int]] = None,
    ) -> int:
        """
        Generate a truncated fig.fig that routes only through reaches
        upstream of *terminal_reach*.

        **Important SWAT2012 limitation**: ``getallo.f`` counts icode=1
        (subbasin) commands to dimension arrays (``msub``), but
        ``readfig.f`` indexes those arrays by the **subbasin number**
        (e.g., ``subgis(22)``).  If subbasin commands are removed, the
        count drops below the highest subbasin number and SWAT crashes
        with an array-bounds error.  Therefore this method keeps **all**
        subbasin commands and only removes downstream route/add commands.
        All subbasins are still simulated; only downstream routing is
        skipped, so the performance benefit is modest.

        Args:
            terminal_reach: Stop routing at this reach
            output_path: Path to write the truncated fig.fig

        Returns:
            Number of *upstream* subbasins (for informational purposes;
            the file still contains all subbasin commands).
        """
        if not self._parsed:
            raise RuntimeError("Call parse() first")

        output_path = Path(output_path)
        if active_subbasins is not None:
            upstream_subs = active_subbasins
            upstream_reaches = {
                self.subbasin_to_reach[s]
                for s in active_subbasins
                if s in self.subbasin_to_reach
            }
        else:
            upstream_subs = self.get_upstream_subbasins(terminal_reach)
            upstream_reaches = self.get_upstream_reaches(terminal_reach)
            upstream_reaches.add(terminal_reach)

        # Collect hydrograph storage locations produced by included
        # commands so we can filter add commands properly.
        # Only upstream subbasin hydrographs are tracked — all subbasin
        # commands are kept (SWAT2012 array-bounds requirement), but
        # downstream subbasin hydrographs must NOT propagate through
        # the ADD filter or downstream ADDs referencing excluded routes
        # would be kept, causing access violations in SWAT.
        included_hyds: set = set()

        lines = []

        for cmd in self.commands:
            if cmd["icode"] == 0:
                # Finish - always include
                lines.append(cmd["raw_line"])
                break
            elif cmd["icode"] == 1:
                # Subbasin - ALWAYS include (see docstring for why).
                lines.append(cmd["raw_line"])
                if cmd["file_line"] is not None:
                    lines.append(cmd["file_line"])
                # Only track upstream subbasins for ADD filtering
                if cmd["inum1"] in upstream_subs:
                    included_hyds.add(cmd["ihout"])
            elif cmd["icode"] == 2:
                # Route - include only if reach is in the upstream set
                if cmd["inum1"] in upstream_reaches:
                    lines.append(cmd["raw_line"])
                    if cmd["file_line"] is not None:
                        lines.append(cmd["file_line"])
                    # Don't track the terminal reach's output — it is
                    # the endpoint of upstream routing.  Tracking it
                    # would cause downstream ADDs (which combine the
                    # terminal output with downstream subbasins) to
                    # pass the ADD filter, causing SWAT access violations.
                    if cmd["inum1"] != terminal_reach:
                        included_hyds.add(cmd["ihout"])
            elif cmd["icode"] == 5:
                # Add - include only if at least one input was produced
                # by an included command (avoids dangling references to
                # hydrographs from excluded downstream routes).
                if cmd["inum1"] in included_hyds or cmd["inum2"] in included_hyds:
                    lines.append(cmd["raw_line"])
                    included_hyds.add(cmd["ihout"])
            elif cmd["icode"] == 14:
                # Saveconc - only include if its reference hydrograph
                # was actually produced.  In a truncated fig, the
                # original saveconc often references the outlet's
                # hydrograph which no longer exists.
                if cmd.get("inum1") in included_hyds or cmd.get("ihout") in included_hyds:
                    lines.append(cmd["raw_line"])
                    if cmd.get("file_line") is not None:
                        lines.append(cmd["file_line"])
            else:
                lines.append(cmd["raw_line"])
                if cmd.get("file_line") is not None:
                    lines.append(cmd["file_line"])

        # Ensure finish command is present
        if not lines or not any(
            self._parse_command_line(l) and
            self._parse_command_line(l).get("icode") == 0
            for l in lines[-3:]
        ):
            lines.append(
                f" {'':9s}{0:6d}{0:6d}{0:6d}{0:6d}{0:6d}{0.0:6.3f}{0:9d}"
            )

        with open(output_path, "w") as f:
            f.write("\n".join(lines) + "\n")

        logger.info(
            f"Wrote truncated fig.fig: {len(upstream_subs)} upstream subbasins, "
            f"{len(upstream_reaches)} upstream reaches, "
            f"{len(self.subbasins)} total subbasins kept -> {output_path}"
        )
        return len(upstream_subs)

    def write_active_subs(
        self,
        terminal_reach: int,
        output_path,
        subbasin_list: Optional[List[int]] = None,
    ) -> List[int]:
        """Write active_subs.dat listing subbasins upstream of terminal_reach.

        This file is read by the custom SWAT executable to skip simulation
        of non-active subbasins (the ``call subbasin`` in command.f is
        guarded by ``active_sub(inum1) == 1``).

        Args:
            terminal_reach: Only subbasins upstream of this reach are active.
            output_path: Path to write active_subs.dat.
            subbasin_list: If provided, write this list instead of
                auto-detecting from fig.fig routing.

        Returns:
            Sorted list of active subbasin numbers.
        """
        if not self._parsed:
            raise RuntimeError("Call parse() first")

        if subbasin_list is not None:
            upstream_subs = sorted(subbasin_list)
        else:
            upstream_subs = sorted(self.get_upstream_subbasins(terminal_reach))
        output_path = Path(output_path)
        # First line must be the count — readcalib.f reads it as n_active_subs.
        # Without the count header the first subbasin number is consumed as
        # the count, silently deactivating that subbasin.
        lines = [str(len(upstream_subs))] + [str(s) for s in upstream_subs]
        output_path.write_text("\n".join(lines) + "\n")

        logger.info(
            f"Wrote active_subs.dat: {len(upstream_subs)} active subbasins "
            f"for terminal reach {terminal_reach} -> {output_path}"
        )
        return upstream_subs

    def get_topology_summary(self) -> str:
        """Return a human-readable summary of the routing topology."""
        if not self._parsed:
            raise RuntimeError("Call parse() first")

        lines = [
            f"Subbasins: {len(self.subbasins)}",
            f"Reaches: {len(self.reaches)}",
            f"Outlet reach: {self.get_outlet_reach()}",
            "",
            "Reach connectivity (upstream -> downstream):",
        ]
        for up, down in sorted(self.reach_graph.items()):
            if down is not None:
                lines.append(f"  Reach {up} -> Reach {down}")
            else:
                lines.append(f"  Reach {up} -> OUTLET")

        lines.append("")
        lines.append("Subbasin -> Reach mapping:")
        for sub, reach in sorted(self.subbasin_to_reach.items()):
            lines.append(f"  Sub {sub} -> Reach {reach}")

        return "\n".join(lines)

    def __repr__(self) -> str:
        status = "parsed" if self._parsed else "not parsed"
        return (
            f"FigFileParser('{self.fig_path}', {status}, "
            f"{len(self.subbasins)} subs, {len(self.reaches)} reaches)"
        )


# ---------------------------------------------------------------------------
# Multi-reach partial-basin utilities
# ---------------------------------------------------------------------------


def get_multi_reach_active_subs(
    fig_path: Path,
    target_reach_ids: List[int],
) -> Tuple[Set[int], int]:
    """Compute the union of upstream subbasins for multiple target reaches.

    Uses fig.fig routing topology (priority) to determine which subbasins
    must be active to simulate all target reaches correctly.

    Also identifies the most-downstream reach among the targets (the one
    whose upstream set is the largest superset), which is used as the
    ``terminal_reach`` for ``write_active_subs()``.

    Args:
        fig_path: Path to fig.fig.
        target_reach_ids: List of target reach (or subbasin) IDs.

    Returns:
        Tuple of (union_of_upstream_subs, most_downstream_reach_id).
        If fig.fig doesn't exist or can't be parsed, returns (empty set, 0).
    """
    if not Path(fig_path).exists():
        return set(), 0

    parser = FigFileParser(fig_path)
    topo = parser.parse()
    sub_to_rch = topo["subbasin_to_reach"]

    # Translate subbasin IDs to reach IDs where necessary
    translated: List[int] = []
    for rid in target_reach_ids:
        if rid in topo["reaches"]:
            translated.append(rid)
        elif rid in topo["subbasins"]:
            mapped = sub_to_rch.get(rid, rid)
            translated.append(mapped)
        else:
            translated.append(rid)

    if not translated:
        return set(), 0

    # Compute upstream subs for each target (fig.fig priority)
    per_reach_subs: Dict[int, Set[int]] = {}
    for reach_id in translated:
        per_reach_subs[reach_id] = parser.get_upstream_subbasins(reach_id)

    # Union of all upstream subbasin sets
    union_subs: Set[int] = set()
    for subs in per_reach_subs.values():
        union_subs |= subs

    # Most-downstream reach = the one with the largest upstream set
    most_downstream = max(translated, key=lambda r: len(per_reach_subs.get(r, set())))

    return union_subs, most_downstream


# ---------------------------------------------------------------------------
# GIS-based topology utilities (standalone, not part of FigFileParser)
# ---------------------------------------------------------------------------


def _has_river_shapefile(shapes_dir: Path) -> bool:
    """Check if a Shapes directory contains a river network shapefile.

    Supports both ``rivs1.shp`` (SWAT+ / older QSWAT) and ``riv1.shp``
    (standard QSWAT).
    """
    return (shapes_dir / "rivs1.shp").exists() or (
        shapes_dir / "riv1.shp"
    ).exists()


def _find_river_shapefile(shapes_dir: Path) -> Optional[Path]:
    """Return the path to whichever river shapefile exists, or None."""
    for name in ("rivs1.shp", "riv1.shp"):
        p = shapes_dir / name
        if p.exists():
            return p
    return None


def find_qswat_shapes_dir(model_project_dir) -> Optional[Path]:
    """Try to find QSWAT Watershed/Shapes directory with a river shapefile.

    Searches in the model project dir itself and then walks up the directory
    tree looking for ``Watershed/Shapes/`` containing ``rivs1.shp`` (SWAT+)
    or ``riv1.shp`` (standard QSWAT).

    Args:
        model_project_dir: Path to the SWAT model project (TxtInOut) directory.

    Returns:
        Path to the Shapes directory, or None if not found.
    """
    model_dir = Path(model_project_dir)

    # Check within the model directory itself
    candidate = model_dir / "Watershed" / "Shapes"
    if _has_river_shapefile(candidate):
        return candidate

    # Walk up the directory tree (handles TxtInOut inside Scenarios/Default/)
    for ancestor in model_dir.parents:
        candidate = ancestor / "Watershed" / "Shapes"
        if _has_river_shapefile(candidate):
            return candidate
        # Stop at the drive root
        if ancestor == ancestor.parent:
            break

    # Check sibling directories of the model project.
    # Two-pass approach: prefer rivs1.shp first (SWAT+ project shapes),
    # then fall back to riv1.shp (standard QSWAT).  This avoids picking
    # up an unrelated QSWAT project's riv1.shp when the correct sibling
    # has rivs1.shp.
    parent = model_dir.parent
    if parent.exists():
        for shp_name in ("rivs1.shp", "riv1.shp"):
            for sibling in parent.iterdir():
                if not sibling.is_dir() or sibling == model_dir:
                    continue
                candidate = sibling / "Watershed" / "Shapes"
                if (candidate / shp_name).exists():
                    return candidate

    return None


def get_gis_drainage_topology(
    shapes_dir,
) -> Dict[int, Optional[int]]:
    """Parse the river shapefile to derive subbasin->downstream_subbasin mapping.

    Supports two shapefile formats:

    * **rivs1.shp** (SWAT+ / older QSWAT): Contains multiple channel segments
      per subbasin with ``Channel``, ``ChannelR``, and ``Subbasin`` columns.
      Drainage connectivity is inferred by finding boundary-crossing channels.

    * **riv1.shp** (standard QSWAT): One row per subbasin with ``Subbasin``
      and ``SubbasinR`` (downstream subbasin) columns — a direct mapping.

    Args:
        shapes_dir: Path to the QSWAT Watershed/Shapes directory.

    Returns:
        Dict mapping each subbasin ID to its downstream subbasin ID.
        Outlet subbasins map to ``None``.

    Raises:
        ImportError: If geopandas is not installed.
        FileNotFoundError: If no supported river shapefile is found.
    """
    import geopandas as gpd  # optional dependency

    shapes_dir = Path(shapes_dir)
    rivs_path = _find_river_shapefile(shapes_dir)
    if rivs_path is None:
        raise FileNotFoundError(
            f"No river shapefile (rivs1.shp or riv1.shp) found in {shapes_dir}"
        )

    gdf = gpd.read_file(rivs_path)

    # ── riv1.shp: direct Subbasin → SubbasinR mapping ──────────────
    if {"Subbasin", "SubbasinR"}.issubset(gdf.columns):
        topology: Dict[int, Optional[int]] = {}
        for _, row in gdf.iterrows():
            sub = int(row["Subbasin"])
            down = int(row["SubbasinR"])
            topology[sub] = down if down != 0 else None
        return topology

    # ── rivs1.shp: channel-level routing ────────────────────────────
    required = {"Channel", "ChannelR", "Subbasin"}
    if not required.issubset(gdf.columns):
        raise ValueError(
            f"{rivs_path.name} missing required columns: "
            f"{required - set(gdf.columns)}"
        )

    # Build channel → subbasin lookup
    ch_to_sub: Dict[int, int] = dict(
        zip(gdf["Channel"].astype(int), gdf["Subbasin"].astype(int))
    )

    # For each channel, find its downstream channel's subbasin
    gdf = gdf.copy()
    gdf["DownSubbasin"] = gdf["ChannelR"].astype(int).map(ch_to_sub)

    # Boundary channels: downstream channel is in a different subbasin
    boundary = gdf[gdf["Subbasin"] != gdf["DownSubbasin"]]

    # Derive subbasin → downstream subbasin
    all_subs = sorted(gdf["Subbasin"].astype(int).unique())
    topology = {}

    for sub in all_subs:
        sub_boundary = boundary[boundary["Subbasin"] == sub]
        if len(sub_boundary) > 0:
            down_subs = sub_boundary["DownSubbasin"].dropna().astype(int).unique()
            if len(down_subs) > 0:
                # Pick the most downstream outlet (largest stream order at boundary)
                if "strmOrder" in sub_boundary.columns:
                    idx = sub_boundary["strmOrder"].idxmax()
                    topology[sub] = int(sub_boundary.loc[idx, "DownSubbasin"])
                else:
                    topology[sub] = int(down_subs[0])
            else:
                topology[sub] = None  # outlet
        else:
            topology[sub] = None  # no boundary crossing → outlet

    return topology


def get_gis_upstream_subbasins(
    shapes_dir,
    subbasin_id: int,
) -> Set[int]:
    """Get all subbasins upstream of a given subbasin using GIS topology.

    Parses the river shapefile (``rivs1.shp`` or ``riv1.shp``) from the
    QSWAT Watershed/Shapes directory to build the physical drainage network,
    then performs a BFS upstream traversal.

    Args:
        shapes_dir: Path to the QSWAT Watershed/Shapes directory.
        subbasin_id: The target subbasin (inclusive in the result).

    Returns:
        Set of subbasin IDs that drain to the target (including itself).
    """
    topology = get_gis_drainage_topology(shapes_dir)

    # Build reverse graph: downstream → set of upstream subs
    reverse: Dict[int, Set[int]] = defaultdict(set)
    for sub, down in topology.items():
        if down is not None:
            reverse[down].add(sub)

    # BFS upstream from target
    result: Set[int] = {subbasin_id}
    queue = list(reverse.get(subbasin_id, set()))
    while queue:
        current = queue.pop(0)
        if current not in result:
            result.add(current)
            queue.extend(reverse.get(current, set()))

    return result


def get_section_subbasins(
    start_sub: int,
    end_sub: int,
    shapes_dir=None,
    fig_path=None,
) -> Tuple[Set[int], Set[int]]:
    """Compute the subbasins in a watershed section between two points.

    The "section" is defined as: all subbasins that are upstream of
    ``end_sub`` but NOT strictly upstream of ``start_sub``. In other words,
    ``start_sub`` itself is included in the section, but everything above
    it is excluded (locked).

    Formula:
        section = upstream_of(end) - upstream_of(start) + {start}
        locked  = upstream_of(start) - {start}

    Priority: fig.fig routing > GIS topology (rivs1.shp) fallback.

    Args:
        start_sub: Upper boundary subbasin (included in section).
        end_sub: Lower boundary / observation point subbasin (included in section).
        shapes_dir: Path to QSWAT Watershed/Shapes directory. Used as
            fallback if fig.fig is not available or returns empty results.
        fig_path: Path to fig.fig file. Preferred source of topology.

    Returns:
        Tuple of (section_subs, locked_subs) where:
            section_subs: Set of subbasin IDs to calibrate (start to end inclusive).
            locked_subs: Set of subbasin IDs upstream of start (excluded from calibration).

    Raises:
        ValueError: If neither fig_path nor shapes_dir can resolve topology,
            or if start_sub is not upstream of end_sub.
    """
    upstream_end: Set[int] = set()
    upstream_start: Set[int] = set()

    # Try fig.fig first
    _used_fig = False
    if fig_path is not None:
        fig_path = Path(fig_path)
        if fig_path.exists():
            try:
                parser = FigFileParser(fig_path)
                parser.parse()
                upstream_end = parser.get_upstream_subbasins_by_subbasin(end_sub)
                upstream_start = parser.get_upstream_subbasins_by_subbasin(start_sub)
                if upstream_end:
                    _used_fig = True
            except Exception:
                pass

    # Fall back to GIS topology
    if not _used_fig:
        if shapes_dir is None:
            raise ValueError(
                "Cannot compute section subbasins: no fig.fig found "
                "and no GIS shapefile path provided."
            )
        if not _has_river_shapefile(Path(shapes_dir)):
            raise ValueError(
                f"No river shapefile found in {shapes_dir} "
                "and fig.fig is not available."
            )
        upstream_end = get_gis_upstream_subbasins(shapes_dir, end_sub)
        upstream_start = get_gis_upstream_subbasins(shapes_dir, start_sub)

    # Validate: start must be upstream of (or equal to) end
    if start_sub not in upstream_end:
        raise ValueError(
            f"Subbasin {start_sub} is not upstream of subbasin {end_sub}. "
            f"Upstream of {end_sub}: {sorted(upstream_end)}"
        )

    # Compute section and locked sets
    section_subs = (upstream_end - upstream_start) | {start_sub}
    locked_subs = upstream_start - {start_sub}

    return section_subs, locked_subs
