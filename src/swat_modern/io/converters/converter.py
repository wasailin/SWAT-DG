"""
Main orchestrator for SWAT+ to SWAT 2012 conversion.

Usage:
    from swat_modern.io.converters import SWATplusToSWAT2012Converter

    converter = SWATplusToSWAT2012Converter(
        source_dir="C:/my_swatplus_project/Scenarios/Default/TxtInOut",
        output_dir="C:/my_swat2012_project",
        num_subbasins=25,
    )
    converter.convert()

CLI:
    python -m swat_modern.io.converters.converter --source <path> --output <path> --num-subbasins 25
"""

from pathlib import Path
from typing import Dict, List, Optional, Set
from collections import defaultdict
import logging
import sys

from .swatplus_reader import SWATplusReader
from .parameter_mapper import ParameterMapper
from .swat2012_writer import SWAT2012Writer
from .routing_builder import RoutingBuilder
from .weather_converter import WeatherConverter

logger = logging.getLogger(__name__)


class SWATplusToSWAT2012Converter:
    """
    Converts a SWAT+ TxtInOut directory to SWAT 2012 format.

    Creates a subset of the model (configurable number of subbasins)
    with all files needed by the SWAT-DG calibration tool.
    """

    def __init__(
        self,
        source_dir: str,
        output_dir: str,
        num_subbasins: int = 25,
    ):
        """
        Args:
            source_dir: Path to SWAT+ TxtInOut directory
            output_dir: Path for SWAT 2012 output
            num_subbasins: Number of subbasins to include in subset
        """
        self.source_dir = Path(source_dir)
        self.output_dir = Path(output_dir)
        self.num_subbasins = num_subbasins

        self.reader = SWATplusReader(str(self.source_dir))
        self.mapper = ParameterMapper(self.reader)
        self.writer = SWAT2012Writer(str(self.output_dir))
        self.routing = RoutingBuilder()
        self.weather = WeatherConverter(self.reader)

        # Mapping tables built during conversion
        self.selected_rtu_ids: List[int] = []
        self.rtu_to_new_sub: Dict[int, int] = {}
        self.hru_assignments: Dict[int, List[Dict]] = {}  # new_sub -> list of HRU info

    def convert(self) -> None:
        """Run the full conversion pipeline."""
        logger.info(f"Starting SWAT+ to SWAT 2012 conversion")
        logger.info(f"Source: {self.source_dir}")
        logger.info(f"Output: {self.output_dir}")
        logger.info(f"Target subbasins: {self.num_subbasins}")

        self._step1_select_subset()
        self._step2_assign_hrus()
        self._step3_write_basin_files()
        self._step4_write_subbasin_files()
        self._step5_write_hru_files()
        self._step6_write_routing()
        self._step7_write_weather()
        self._step8_write_support_files()

        logger.info("Conversion complete!")
        self._print_summary()

    def _step1_select_subset(self):
        """Select connected subset of routing units."""
        logger.info("Step 1: Selecting subbasin subset...")
        rtu_cons = self.reader.read_rout_unit_con()
        chandeg_con = self.reader.read_chandeg_con()

        self.selected_rtu_ids = self.routing.select_subset(
            rtu_cons, chandeg_con, self.num_subbasins
        )

        # Assign new sequential subbasin numbers
        for i, rtu_id in enumerate(self.selected_rtu_ids):
            self.rtu_to_new_sub[rtu_id] = i + 1

        logger.info(f"  Selected {len(self.selected_rtu_ids)} routing units")

    def _step2_assign_hrus(self):
        """Assign HRUs to subbasins."""
        logger.info("Step 2: Assigning HRUs to subbasins...")

        # Read all data needed
        rtu_defs = self.reader.read_rout_unit_def()
        rtu_eles = self.reader.read_rout_unit_ele()
        hru_data_list = self.reader.read_hru_data()
        hru_con_list = self.reader.read_hru_con()

        # Index HRU data by name
        hru_data_by_name = {}
        for hru in hru_data_list:
            hru_data_by_name[hru.get("name", "")] = hru

        # Index HRU con by id
        hru_con_by_id = {}
        for hru in hru_con_list:
            hru_con_by_id[int(hru.get("id", 0))] = hru

        # Index RTU elements by ID
        rtu_ele_by_id = {}
        for ele in rtu_eles:
            rtu_ele_by_id[int(ele.get("id", 0))] = ele

        # Build RTU -> HRU element list
        rtu_to_hru_ids = {}
        for rtu_def in rtu_defs:
            rtu_id = rtu_def["id"]
            if rtu_id not in self.rtu_to_new_sub:
                continue
            # The elements list contains element IDs that reference rout_unit.ele
            elem_ids = rtu_def.get("elements", [])
            hru_ids = []
            for eid in elem_ids:
                ele = rtu_ele_by_id.get(eid, {})
                obj_typ = ele.get("obj_typ", "")
                obj_id = ele.get("obj_id", "0")
                if obj_typ == "hru" and obj_id.isdigit():
                    hru_ids.append(int(obj_id))
            rtu_to_hru_ids[rtu_id] = hru_ids

        # Get RTU con data indexed by id
        rtu_cons = self.reader.read_rout_unit_con()
        rtu_con_by_id = {}
        for rtu in rtu_cons:
            rtu_con_by_id[int(rtu.get("id", 0))] = rtu

        # Build the assignment: new_sub -> list of HRU info
        total_hrus = 0
        for rtu_id, new_sub in self.rtu_to_new_sub.items():
            hru_ids = rtu_to_hru_ids.get(rtu_id, [])
            rtu_con = rtu_con_by_id.get(rtu_id, {})

            hrus = []
            for hru_id in hru_ids:
                hru_con = hru_con_by_id.get(hru_id, {})
                hru_name = hru_con.get("name", f"hru{hru_id:04d}")
                hru_data = hru_data_by_name.get(hru_name, {})

                if hru_data:
                    hrus.append({
                        "hru_id": hru_id,
                        "hru_name": hru_name,
                        "hru_data": hru_data,
                        "hru_con": hru_con,
                        "rtu_con": rtu_con,
                    })

            self.hru_assignments[new_sub] = hrus
            total_hrus += len(hrus)

        logger.info(f"  Assigned {total_hrus} HRUs across {len(self.rtu_to_new_sub)} subbasins")

    def _step3_write_basin_files(self):
        """Write global basin files."""
        logger.info("Step 3: Writing basin-level files...")

        # Get simulation period
        time_sim = self.reader.read_time_sim()
        nbyr = time_sim["yrc_end"] - time_sim["yrc_start"]
        if nbyr <= 0:
            nbyr = 1

        # Count totals
        total_hrus = sum(len(hrus) for hrus in self.hru_assignments.values())
        nsub = len(self.rtu_to_new_sub)

        # Pre-compute weather station count for file.cio
        all_hru_cons = []
        for new_sub, hrus in self.hru_assignments.items():
            for hru_info in hrus:
                all_hru_cons.append(hru_info["hru_con"])
        stations = self.weather.get_stations_for_hrus(all_hru_cons)
        nstations = len(stations)

        # file.cio
        self.writer.write_file_cio(
            nbyr=nbyr,
            iyr=time_sim["yrc_start"],
            idaf=1 if time_sim["day_start"] == 0 else time_sim["day_start"],
            idal=365 if time_sim["day_end"] == 0 else time_sim["day_end"],
            nsub=nsub,
            nhru=total_hrus,
            nrch=nsub,
            nyskip=5,
            iprint=1,
            nrgage=1,
            nrtot=nstations,
            ntgage=1,
            nttot=nstations,
        )

        # basins.bsn
        basin_params = self.mapper.get_basin_params()
        self.writer.write_basins_bsn(basin_params)

        logger.info(f"  Wrote file.cio and basins.bsn ({nsub} subs, {total_hrus} HRUs)")

    def _step4_write_subbasin_files(self):
        """Write per-subbasin .sub, .rte, .wgn, .pnd, .wus files."""
        logger.info("Step 4: Writing subbasin files...")

        rtu_cons = self.reader.read_rout_unit_con()
        rtu_con_by_id = {int(r.get("id", 0)): r for r in rtu_cons}

        # Map RTU to its output channel name (use sdc_id from multi-output parsing)
        rtu_to_channel_name = {}
        for rtu in rtu_cons:
            rtu_id = int(rtu.get("id", 0))
            sdc_id = rtu.get("sdc_id", "") or rtu.get("obj_id", "0")
            if sdc_id and sdc_id.isdigit() and int(sdc_id) > 0:
                rtu_to_channel_name[rtu_id] = f"cha{int(sdc_id):03d}"

        # Read weather generator data for .wgn files
        wgn_stations = self.reader.read_weather_wgn()
        # Get first available wgn station as default
        default_wgn = next(iter(wgn_stations.values()), None) if wgn_stations else None

        # Map weather station names (from RTU wst field) to wgn station data
        weather_stas = self.reader.read_weather_sta()
        wst_to_wgn_name = {}
        for sta in weather_stas:
            sta_name = sta.get("name", "")
            wgn_name = sta.get("wgn", "")
            if sta_name and wgn_name:
                wst_to_wgn_name[sta_name] = wgn_name

        for rtu_id, new_sub in self.rtu_to_new_sub.items():
            rtu_con = rtu_con_by_id.get(rtu_id, {})
            hrus = self.hru_assignments.get(new_sub, [])

            # Sub params
            sub_params = self.mapper.get_sub_params(
                rtu_con, [h["hru_con"] for h in hrus]
            )

            # HRU file names
            hru_files = [f"{new_sub:05d}{i+1:04d}.hru" for i in range(len(hrus))]

            self.writer.write_sub_file(new_sub, sub_params, hru_files)

            # Rte params (from channel associated with this RTU)
            ch_name = rtu_to_channel_name.get(rtu_id, "")
            rte_params = self.mapper.get_rte_params(ch_name)
            self.writer.write_rte_file(new_sub, rte_params)

            # .wgn file - weather generator from nearest station
            wst_name = rtu_con.get("wst", "")
            wgn_name = wst_to_wgn_name.get(wst_name, "")
            wgn_data = wgn_stations.get(wgn_name, default_wgn)
            if wgn_data:
                self.writer.write_wgn_file(new_sub, wgn_data)

            # .pnd and .wus files (minimal/default)
            self.writer.write_pnd_file(new_sub)
            self.writer.write_wus_file(new_sub)

        logger.info(f"  Wrote {len(self.rtu_to_new_sub)} .sub, .rte, .wgn, .pnd, .wus files")

    def _step5_write_hru_files(self):
        """Write per-HRU .hru, .mgt, .sol, .gw files."""
        logger.info("Step 5: Writing HRU files...")

        total_written = 0
        for new_sub, hrus in self.hru_assignments.items():
            for hru_idx_0, hru_info in enumerate(hrus):
                hru_idx = hru_idx_0 + 1  # 1-based
                hru_data = hru_info["hru_data"]
                hru_con = hru_info["hru_con"]
                rtu_con = hru_info["rtu_con"]

                # .hru file
                hru_params = self.mapper.get_hru_params(hru_data, hru_con)
                # Calculate HRU fraction within subbasin
                total_sub_area = sum(
                    self.mapper._safe_float(h["hru_con"].get("area"), 1.0)
                    for h in hrus
                )
                hru_area = self.mapper._safe_float(hru_con.get("area"), 1.0)
                hru_params["HRU_FR"] = hru_area / total_sub_area if total_sub_area > 0 else 1.0
                self.writer.write_hru_file(new_sub, hru_idx, hru_params)

                # .mgt file
                mgt_params = self.mapper.get_mgt_params(hru_data, hru_con)
                self.writer.write_mgt_file(new_sub, hru_idx, mgt_params)

                # .sol file
                soil_name = hru_data.get("soil", "")
                soil = self.mapper.get_soil_for_hru(soil_name)
                self.writer.write_sol_file(new_sub, hru_idx, soil)

                # .gw file
                gw_params = self.mapper.get_gw_params(hru_data, rtu_con)
                self.writer.write_gw_file(new_sub, hru_idx, gw_params)

                # .chm file (placeholder)
                nlayers = len(soil.get("layers", [{}]))
                self.writer.write_chm_file(new_sub, hru_idx, nlayers)

                total_written += 1
                if total_written % 200 == 0:
                    logger.info(f"  ... wrote {total_written} HRU file sets")

        logger.info(f"  Wrote {total_written} HRU file sets (.hru, .mgt, .sol, .gw)")

    def _step6_write_routing(self):
        """Write fig.fig routing file."""
        logger.info("Step 6: Writing routing network...")
        rtu_cons = self.reader.read_rout_unit_con()
        chandeg_con = self.reader.read_chandeg_con()

        self.routing.build_fig_fig(
            self.selected_rtu_ids,
            rtu_cons,
            chandeg_con,
            self.rtu_to_new_sub,
            self.output_dir,
        )

    def _step7_write_weather(self):
        """Write weather files."""
        logger.info("Step 7: Writing weather files...")

        # Collect all HRU connectivity for selected subbasins
        all_hru_cons = []
        for new_sub, hrus in self.hru_assignments.items():
            for hru_info in hrus:
                all_hru_cons.append(hru_info["hru_con"])

        # Get unique stations
        stations = self.weather.get_stations_for_hrus(all_hru_cons)
        logger.info(f"  Found {len(stations)} unique weather stations")

        # Convert precipitation
        self.weather.convert_precipitation(stations, self.output_dir)

        # Convert temperature
        self.weather.convert_temperature(stations, self.output_dir)

    def _step8_write_support_files(self):
        """Write support/placeholder files."""
        logger.info("Step 8: Writing support files...")
        self.writer.write_empty_support_files()

    def _print_summary(self):
        """Print conversion summary."""
        total_hrus = sum(len(hrus) for hrus in self.hru_assignments.values())
        nsub = len(self.rtu_to_new_sub)

        # Count files
        output_files = list(self.output_dir.glob("*"))
        file_counts = defaultdict(int)
        for f in output_files:
            file_counts[f.suffix] += 1

        logger.info("=" * 60)
        logger.info("CONVERSION SUMMARY")
        logger.info("=" * 60)
        logger.info(f"Subbasins: {nsub}")
        logger.info(f"HRUs: {total_hrus}")
        logger.info(f"Output directory: {self.output_dir}")
        logger.info(f"Total files: {len(output_files)}")
        for ext, count in sorted(file_counts.items()):
            logger.info(f"  {ext}: {count}")


def main():
    """CLI entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Convert SWAT+ TxtInOut to SWAT 2012 format"
    )
    parser.add_argument(
        "--source", required=True,
        help="Path to SWAT+ TxtInOut directory"
    )
    parser.add_argument(
        "--output", required=True,
        help="Path for SWAT 2012 output directory"
    )
    parser.add_argument(
        "--num-subbasins", type=int, default=25,
        help="Number of subbasins to include (default: 25)"
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Enable verbose logging"
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    converter = SWATplusToSWAT2012Converter(
        source_dir=args.source,
        output_dir=args.output,
        num_subbasins=args.num_subbasins,
    )
    converter.convert()


if __name__ == "__main__":
    main()
