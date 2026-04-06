"""
Builds SWAT 2012 fig.fig routing file from SWAT+ connectivity data.

The fig.fig file defines the watershed routing order using commands:
- subbasin: defines a subbasin
- route: routes flow through a reach
- add: adds flows at confluences
- finish: marks the end
"""

from pathlib import Path
from typing import Dict, List, Set, Tuple, Optional
from collections import defaultdict
import logging

logger = logging.getLogger(__name__)


class RoutingBuilder:
    """Builds fig.fig from SWAT+ channel connectivity."""

    def __init__(self):
        self.graph = {}  # channel_id -> downstream_channel_id
        self.channel_to_sub = {}  # channel_id -> subbasin_number
        self.sub_to_channel = {}  # subbasin_number -> channel_id

    def build_graph(self, chandeg_con: List[Dict]) -> None:
        """
        Build directed graph from chandeg.con.

        Each channel has an out_tot and routing target (obj_typ, obj_id).
        obj_typ='sdc' means it routes to another channel.
        out_tot=0 means it's the outlet.
        """
        for row in chandeg_con:
            ch_id = int(row.get("id", 0))
            out_tot = int(row.get("out_tot", 0))

            if out_tot == 0:
                # This is the outlet
                self.graph[ch_id] = None
            else:
                obj_typ = row.get("obj_typ", "")
                obj_id = int(row.get("obj_id", 0))
                if obj_typ == "sdc":
                    self.graph[ch_id] = obj_id
                else:
                    self.graph[ch_id] = None

    def select_subset(
        self,
        rtu_cons: List[Dict],
        chandeg_con: List[Dict],
        num_subbasins: int = 25,
    ) -> List[int]:
        """
        Select a connected subset of routing units (subbasins).

        Strategy: find the outlet, then traverse upstream to collect
        num_subbasins connected routing units.

        Args:
            rtu_cons: rout_unit.con rows
            chandeg_con: chandeg.con rows

        Returns:
            List of routing unit IDs to include
        """
        self.build_graph(chandeg_con)

        # Map routing units to their output channels
        # rout_unit.con has sdc_id (from multi-output parsing) for channel routing
        rtu_to_channel = {}
        for rtu in rtu_cons:
            rtu_id = int(rtu.get("id", 0))
            sdc_id = rtu.get("sdc_id", "") or rtu.get("obj_id", "0")
            if sdc_id and sdc_id.isdigit() and int(sdc_id) > 0:
                rtu_to_channel[rtu_id] = int(sdc_id)

        # Build reverse graph: channel -> list of upstream channels
        reverse = defaultdict(list)
        for ch_id, downstream in self.graph.items():
            if downstream is not None:
                reverse[downstream].append(ch_id)

        # Build channel -> list of routing units that output to it
        channel_to_rtus = defaultdict(list)
        for rtu_id, ch_id in rtu_to_channel.items():
            channel_to_rtus[ch_id].append(rtu_id)

        # Find outlet (channel with no downstream)
        outlet = None
        for ch_id, downstream in self.graph.items():
            if downstream is None:
                outlet = ch_id
                break

        if outlet is None:
            logger.warning("No outlet found, using channel 1")
            outlet = 1

        # BFS upstream from outlet to collect subbasins
        selected_rtus = []
        selected_channels = set()
        queue = [outlet]
        visited = set()

        while queue and len(selected_rtus) < num_subbasins:
            ch_id = queue.pop(0)
            if ch_id in visited:
                continue
            visited.add(ch_id)
            selected_channels.add(ch_id)

            # Add all RTUs that route to this channel
            for rtu_id in channel_to_rtus.get(ch_id, []):
                if len(selected_rtus) < num_subbasins:
                    selected_rtus.append(rtu_id)

            # Add upstream channels to queue
            for upstream_ch in reverse.get(ch_id, []):
                if upstream_ch not in visited:
                    queue.append(upstream_ch)

        logger.info(f"Selected {len(selected_rtus)} routing units, {len(selected_channels)} channels")
        return selected_rtus

    def build_fig_fig(
        self,
        selected_rtu_ids: List[int],
        rtu_cons: List[Dict],
        chandeg_con: List[Dict],
        rtu_to_new_sub: Dict[int, int],
        output_dir: Path,
    ) -> None:
        """
        Generate fig.fig for the selected subset.

        Fortran format 5000: (a1,9x,5i6,f6.3,i9,i3,3a3)
        Fields: icodes, ihouts, inum1s, inum2s, inum3s, rnum1s, inum4s, ...

        For subbasin (icode=1): inum1s=subbasin#, inum4s=GIS code
        For route (icode=2): inum1s=reach#, inum2s=inflow hyd loc
        For add (icode=5): inum1s=hyd loc 1, inum2s=hyd loc 2
        For finish (icode=0): all zeros

        File ref format 5100: (10x,2a13) - up to 2 filenames per line
        Route cmd reads: rtefile + swqfile on same line
        """
        nsub = len(rtu_to_new_sub)

        # Build channel graph for the subset
        self.build_graph(chandeg_con)

        # Map RTUs to their output channels
        rtu_to_channel = {}
        for rtu in rtu_cons:
            rtu_id = int(rtu.get("id", 0))
            sdc_id = rtu.get("sdc_id", "") or rtu.get("obj_id", "0")
            if rtu_id in rtu_to_new_sub and sdc_id.isdigit() and int(sdc_id) > 0:
                rtu_to_channel[rtu_id] = int(sdc_id)

        # Get unique channels used by selected RTUs
        used_channels = set(rtu_to_channel.values())

        # Topological sort of channels (upstream first)
        sorted_channels = self._topo_sort(used_channels)

        # Map old channel IDs to new reach numbers
        ch_to_reach = {}
        for i, ch_id in enumerate(sorted_channels):
            ch_to_reach[ch_id] = i + 1

        lines = []

        # Next hydrograph storage location counter
        ihyd = 0
        # Track accumulated flow hyd location for downstream adds
        # ch_id -> hyd storage location with accumulated upstream flow
        ch_accum_hyd = {}

        for ch_id in sorted_channels:
            reach_num = ch_to_reach[ch_id]

            # Find RTUs that output to this channel
            rtus_for_ch = [
                rtu_id for rtu_id, ch in rtu_to_channel.items()
                if ch == ch_id and rtu_id in rtu_to_new_sub
            ]

            # Subbasin commands - output each subbasin's flow
            sub_hyd_locs = []
            for rtu_id in rtus_for_ch:
                sub_num = rtu_to_new_sub[rtu_id]
                ihyd += 1
                # Subbasin: inum1s=sub_num, inum4s=sub_num (GIS code)
                lines.append(self._fig_cmd(1, ihyd, sub_num, 0, 0, inum4=sub_num))
                lines.append(f"          {sub_num:05d}0000.sub")
                sub_hyd_locs.append(ihyd)

            # If multiple subbasins feed this channel, add them together first
            if len(sub_hyd_locs) > 1:
                current_hyd = sub_hyd_locs[0]
                for extra_hyd in sub_hyd_locs[1:]:
                    ihyd += 1
                    lines.append(self._fig_cmd(5, ihyd, current_hyd, extra_hyd, 0))
                    current_hyd = ihyd
                inflow_hyd = current_hyd
            elif len(sub_hyd_locs) == 1:
                inflow_hyd = sub_hyd_locs[0]
            else:
                # No local subbasins - use upstream accumulated flow
                # Find upstream channels that feed this one
                upstream_hyds = []
                for uch_id, ds in self.graph.items():
                    if ds == ch_id and uch_id in ch_accum_hyd:
                        upstream_hyds.append(ch_accum_hyd[uch_id])
                if upstream_hyds:
                    inflow_hyd = upstream_hyds[0]
                else:
                    continue  # Skip channels with no input

            # Route command: inum1s=reach_num, inum2s=inflow hyd loc
            ihyd += 1
            lines.append(self._fig_cmd(2, ihyd, reach_num, inflow_hyd, 0))
            # Route file line: rtefile + swqfile (format 10x,2a13)
            rte_name = f"{reach_num:05d}0000.rte"
            swq_name = f"{reach_num:05d}0000.swq"
            lines.append(f"          {rte_name:<13s}{swq_name:<13s}")
            routed_hyd = ihyd

            # Add upstream accumulated flow if there are upstream channels
            downstream_ch = self.graph.get(ch_id)
            upstream_chs = [
                uch_id for uch_id, ds in self.graph.items()
                if ds == ch_id and uch_id in ch_accum_hyd and uch_id in used_channels
            ]

            current_hyd = routed_hyd
            for uch_id in upstream_chs:
                upstream_hyd = ch_accum_hyd[uch_id]
                ihyd += 1
                lines.append(self._fig_cmd(5, ihyd, current_hyd, upstream_hyd, 0))
                current_hyd = ihyd

            ch_accum_hyd[ch_id] = current_hyd

        # Finish command: icd=0
        lines.append(self._fig_cmd(0, 0, 0, 0, 0))

        filepath = output_dir / "fig.fig"
        with open(filepath, "w") as f:
            f.write("\n".join(lines) + "\n")
        logger.info(f"Wrote fig.fig with {nsub} subbasins and {len(sorted_channels)} reaches")

        # Write .swq files for each reach
        for i in range(1, len(sorted_channels) + 1):
            swq_path = output_dir / f"{i:05d}0000.swq"
            with open(swq_path, "w") as f:
                f.write(f" .swq file Reach:{i:5d}\n")
                f.write("Stream Water Quality:\n")
                f.write("\n")

    @staticmethod
    def _fig_cmd(icd: int, iht: int, inm1: int, inm2: int, inm3: int,
                 rnum1: float = 0.0, inum4: int = 0) -> str:
        """
        Format a fig.fig command line matching Fortran format:
        5000 format (a1,9x,5i6,f6.3,i9,i3,3a3)

        Fields:
        - col 1: any char (a1)
        - cols 2-10: skip (9x)
        - cols 11-16: icodes (i6) - command code
        - cols 17-22: ihouts (i6) - hydrograph storage location
        - cols 23-28: inum1s (i6)
        - cols 29-34: inum2s (i6)
        - cols 35-40: inum3s (i6)
        - cols 41-46: rnum1s (f6.3)
        - cols 47-55: inum4s (i9)
        """
        return (f" {' ' * 9}{icd:6d}{iht:6d}{inm1:6d}{inm2:6d}{inm3:6d}"
                f"{rnum1:6.3f}{inum4:9d}")

    def _topo_sort(self, channel_ids: Set[int]) -> List[int]:
        """
        Topological sort of channels (upstream first, outlet last).
        """
        # Build subgraph for selected channels
        in_degree = defaultdict(int)
        adj = defaultdict(list)

        for ch_id in channel_ids:
            downstream = self.graph.get(ch_id)
            if downstream is not None and downstream in channel_ids:
                adj[ch_id].append(downstream)
                in_degree[downstream] += 1
            if ch_id not in in_degree:
                in_degree[ch_id] = in_degree.get(ch_id, 0)

        # Find sources (no incoming edges within subset)
        queue = [ch for ch in channel_ids if in_degree.get(ch, 0) == 0]
        result = []

        while queue:
            ch = queue.pop(0)
            result.append(ch)
            for downstream in adj.get(ch, []):
                in_degree[downstream] -= 1
                if in_degree[downstream] == 0:
                    queue.append(downstream)

        # Add any channels not reached (disconnected)
        for ch_id in channel_ids:
            if ch_id not in result:
                result.append(ch_id)

        return result
