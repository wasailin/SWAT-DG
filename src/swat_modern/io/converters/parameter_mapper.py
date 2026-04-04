"""
Maps SWAT+ parameters to SWAT 2012 equivalents.

Handles the complex lookups required for CN2 resolution,
Manning's n, USLE_P, and other cross-referenced parameters.
"""

from typing import Dict, List, Any, Optional
import logging

logger = logging.getLogger(__name__)


class ParameterMapper:
    """Maps SWAT+ model data to SWAT 2012 parameter values."""

    def __init__(self, reader):
        """
        Args:
            reader: SWATplusReader instance with data loaded
        """
        self.reader = reader
        self._load_lookup_tables()

    def _load_lookup_tables(self):
        """Load all lookup tables needed for parameter mapping."""
        # Land use lookup: name -> {cn2, cons_prac, ov_mann, ...}
        self.landuse = {}
        for row in self.reader.read_landuse_lum():
            self.landuse[row["name"]] = row

        # CN table: name -> {cn_a, cn_b, cn_c, cn_d}
        self.cn_table = {}
        for row in self.reader.read_cntable():
            self.cn_table[row["name"]] = {
                "cn_a": float(row.get("cn_a", 0)),
                "cn_b": float(row.get("cn_b", 0)),
                "cn_c": float(row.get("cn_c", 0)),
                "cn_d": float(row.get("cn_d", 0)),
            }

        # OVN table: name -> ovn_mean
        self.ovn_table = {}
        for row in self.reader.read_ovn_table():
            self.ovn_table[row["name"]] = float(row.get("ovn_mean", 0.1))

        # Conservation practice: name -> usle_p
        self.cons_practice = {}
        for row in self.reader.read_cons_practice():
            self.cons_practice[row["name"]] = float(row.get("usle_p", 1.0))

        # Soils: name -> soil dict
        self.soils = self.reader.read_soils()

        # Hydrology indexed by name
        self.hydrology = {}
        for row in self.reader.read_hydrology():
            self.hydrology[row["name"]] = row

        # Topography indexed by name
        self.topography = {}
        for row in self.reader.read_topography():
            self.topography[row["name"]] = row

        # Aquifer indexed by name
        self.aquifer = {}
        for row in self.reader.read_aquifer():
            self.aquifer[row["name"]] = row

        # Snow parameters
        self.snow = self.reader.read_snow()

        # Basin parameters
        self.params_bsn = self.reader.read_parameters_bsn()

        # Basin codes
        self.codes_bsn = self.reader.read_codes_bsn()

        # Channel hydraulics indexed by name
        self.hyd_sed = {}
        for row in self.reader.read_hyd_sed_lte():
            self.hyd_sed[row["name"]] = row

        # Channel-lte indexed by name (links channel to hydrology set)
        self.channel_lte = {}
        for row in self.reader.read_channel_lte():
            self.channel_lte[row.get("name", "")] = row

    def _safe_float(self, value: str, default: float = 0.0) -> float:
        """Safely convert string to float, returning default if 'null' or invalid."""
        if value is None or value == "null" or value == "":
            return default
        try:
            return float(value)
        except (ValueError, TypeError):
            return default

    def resolve_cn2(self, lu_mgt: str, soil_name: str) -> float:
        """
        Resolve CN2 value through the SWAT+ lookup chain.

        Chain: lu_mgt -> landuse.lum cn2 field -> cntable.lum -> select by soil hyd_grp

        Args:
            lu_mgt: Land use/management name (e.g., "past_lum")
            soil_name: Soil profile name from hru-data.hru

        Returns:
            CN2 value (e.g., 69.0)
        """
        # Step 1: Get cn2 table reference from landuse.lum
        lu = self.landuse.get(lu_mgt, {})
        cn2_ref = lu.get("cn2", "null")
        if cn2_ref == "null" or cn2_ref not in self.cn_table:
            logger.warning(f"CN2 reference '{cn2_ref}' not found for {lu_mgt}, using default 75")
            return 75.0

        # Step 2: Get soil hydrologic group
        soil = self.soils.get(soil_name, {})
        hyd_grp = soil.get("hyd_grp", "B").upper()

        # Step 3: Look up CN value by hydrologic group
        cn_entry = self.cn_table[cn2_ref]
        cn_col = f"cn_{hyd_grp.lower()}"
        cn2 = cn_entry.get(cn_col, cn_entry.get("cn_b", 75.0))

        return cn2

    def resolve_ovn(self, lu_mgt: str) -> float:
        """
        Resolve Manning's n for overland flow.

        Chain: lu_mgt -> landuse.lum ov_mann -> ovn_table.lum ovn_mean
        """
        lu = self.landuse.get(lu_mgt, {})
        ovn_ref = lu.get("ov_mann", "null")
        if ovn_ref == "null" or ovn_ref not in self.ovn_table:
            return 0.15  # default
        return self.ovn_table[ovn_ref]

    def resolve_usle_p(self, lu_mgt: str) -> float:
        """
        Resolve USLE P factor.

        Chain: lu_mgt -> landuse.lum cons_prac -> cons_practice.lum usle_p
        """
        lu = self.landuse.get(lu_mgt, {})
        cp_ref = lu.get("cons_prac", "null")
        if cp_ref == "null" or cp_ref not in self.cons_practice:
            return 1.0  # default (no conservation practice)
        return self.cons_practice[cp_ref]

    def get_basin_params(self) -> Dict[str, float]:
        """
        Map SWAT+ basin parameters to SWAT 2012 basins.bsn values.

        Returns dict with SWAT 2012 parameter names as keys.
        """
        snow = self.snow
        params = self.params_bsn
        codes = self.codes_bsn

        return {
            "SFTMP": self._safe_float(snow.get("fall_tmp"), 1.0),
            "SMTMP": self._safe_float(snow.get("melt_tmp"), 0.5),
            "SMFMX": self._safe_float(snow.get("melt_max"), 4.5),
            "SMFMN": self._safe_float(snow.get("melt_min"), 4.5),
            "TIMP": self._safe_float(snow.get("tmp_lag"), 1.0),
            "SNOCOVMX": self._safe_float(snow.get("snow_h2o"), 1.0),
            "SNO50COV": self._safe_float(snow.get("cov50"), 0.5),
            "IPET": self._safe_float(codes.get("pet"), 1),
            "ESCO": 0.95,  # Will be overridden per-HRU if needed
            "EPCO": 1.0,
            "IEVENT": self._safe_float(codes.get("event"), 0),
            "ICRK": self._safe_float(codes.get("crack"), 0),
            "SURLAG": self._safe_float(params.get("surq_lag"), 4.0),
            "ADJ_PKR": self._safe_float(params.get("adj_pkrt"), 1.0),
            "PRF": self._safe_float(params.get("adj_pkrt_sed"), 1.0),
            "SPCON": self._safe_float(params.get("lin_sed"), 0.0001),
            "SPEXP": self._safe_float(params.get("exp_sed"), 1.0),
            "RCN": 1.0,
            "CMN": self._safe_float(params.get("orgn_min"), 0.0003),
            "N_UPDIS": self._safe_float(params.get("n_uptake"), 20.0),
            "P_UPDIS": self._safe_float(params.get("p_uptake"), 20.0),
            "NPERCO": self._safe_float(params.get("n_perc"), 0.2),
            "PPERCO": self._safe_float(params.get("p_perc"), 10.0),
            "PHOSKD": self._safe_float(params.get("p_soil"), 175.0),
            "PSP": self._safe_float(params.get("p_avail"), 0.4),
            "RSDCO": self._safe_float(params.get("rsd_decomp"), 0.05),
            "PERCOP": self._safe_float(params.get("pest_perc"), 0.5),
            "ISUBWQ": 0,
            "WDPQ": 1.0,
            "WGPQ": 1.0,
            "WDLPQ": 1.0,
            "WGLPQ": 1.0,
            "WDPS": 1.0,
            "WGPS": 1.0,
            "WDLPS": 1.0,
            "WGLPS": 1.0,
            "BACTKDQ": 35.0,
            "THBACT": 1.07,
            "WOF_P": 0,
            "WOF_LP": 0,
            "WDPF": 0.0,
            "WGPF": 0.0,
            "WDLPF": 0.0,
            "WGLPF": 0.0,
            "IRTEFPC": 0.01,
            "IRTEFSC": 0.01,
            "MSK_CO1": self._safe_float(params.get("msk_co1"), 0.75),
            "MSK_CO2": self._safe_float(params.get("msk_co2"), 0.25),
            "MSK_X": self._safe_float(params.get("msk_x"), 0.2),
            "EVRCH": self._safe_float(params.get("evap_adj"), 0.6),
            "SESSION_NUM": 0,
        }

    def get_hru_params(self, hru_data: Dict, hru_con: Dict) -> Dict[str, float]:
        """
        Map SWAT+ HRU data to SWAT 2012 .hru file parameters.

        Args:
            hru_data: Row from hru-data.hru
            hru_con: Row from hru.con
        """
        topo_name = hru_data.get("topo", "")
        hydro_name = hru_data.get("hydro", "")
        lu_mgt = hru_data.get("lu_mgt", "")

        topo = self.topography.get(topo_name, {})
        hydro = self.hydrology.get(hydro_name, {})

        return {
            "HRU_SLP": self._safe_float(topo.get("slp"), 0.05),
            "SLSUBBSN": self._safe_float(topo.get("slp_len"), 50.0),
            "OV_N": self.resolve_ovn(lu_mgt),
            "HRU_FR": 1.0,  # Will be recalculated per subbasin
            "LUSE": lu_mgt.replace("_lum", "").upper()[:16],
            "SOILID": hru_data.get("soil", ""),
            "RSDIN": 0.0,
            "POT_VOLXMM": 0.0,
            "POT_TILEMM": 0.0,
            "POTHOLE": 0.0,
            "CNCOEF": 1.5,
            "USLE_LS": 0.0,
            "CANMX": self._safe_float(hydro.get("can_max"), 0.0),
            "ESCO_HRU": self._safe_float(hydro.get("esco"), 0.95),
            "EPCO_HRU": self._safe_float(hydro.get("epco"), 0.5),
            "LAT_TTIME": self._safe_float(hydro.get("lat_ttime"), 0.0),
            "LAT_SED": self._safe_float(hydro.get("lat_sed"), 0.0),
            "ERORGN": self._safe_float(hydro.get("orgn_enrich"), 0.0),
            "ERORGP": self._safe_float(hydro.get("orgp_enrich"), 0.0),
            "BIOMIX": self._safe_float(hydro.get("bio_mix"), 0.2),
            "USLE_P": self.resolve_usle_p(lu_mgt),
        }

    def get_gw_params(self, hru_data: Dict, rtu_con: Dict) -> Dict[str, float]:
        """
        Map SWAT+ aquifer parameters to SWAT 2012 .gw file.

        Args:
            hru_data: Row from hru-data.hru
            rtu_con: Row from rout_unit.con (has aquifer assignment)
        """
        aqu_id = rtu_con.get("aqu", "1")
        # Find the aquifer by ID
        aqu = None
        for name, aq in self.aquifer.items():
            if aq.get("id") == aqu_id or name == f"aqu{int(aqu_id):03d}0" or aq.get("id") == str(aqu_id):
                aqu = aq
                break

        if aqu is None:
            # Try by index
            aqu_list = list(self.aquifer.values())
            idx = int(aqu_id) - 1 if aqu_id.isdigit() else 0
            if 0 <= idx < len(aqu_list):
                aqu = aqu_list[idx]
            else:
                aqu = aqu_list[0] if aqu_list else {}

        return {
            "SHALLST": self._safe_float(aqu.get("gw_flo"), 1000.0),
            "DEEPST": 1000.0,
            "GW_DELAY": 31.0,  # Not directly in SWAT+
            "ALPHA_BF": self._safe_float(aqu.get("alpha_bf"), 0.048),
            "GWQMN": self._safe_float(aqu.get("flo_min"), 1000.0),
            "GW_REVAP": self._safe_float(aqu.get("revap"), 0.02),
            "REVAPMN": self._safe_float(aqu.get("revap_min"), 500.0),
            "RCHRG_DP": self._safe_float(aqu.get("rchg_dp"), 0.05),
            "GWHT": 0.0,
            "GW_SPYLD": self._safe_float(aqu.get("spec_yld"), 0.003),
            "SHALLST_N": 0.0,
            "GWSOLP": 0.0,
            "HLIFE_NGW": self._safe_float(aqu.get("hl_no3n"), 0.0),
            "LAT_ORGN": 0.0,
            "LAT_ORGP": 0.0,
            "ALPHA_BF_D": 0.0,
        }

    def get_mgt_params(self, hru_data: Dict, hru_con: Dict) -> Dict[str, Any]:
        """
        Map SWAT+ management to SWAT 2012 .mgt file parameters.
        """
        lu_mgt = hru_data.get("lu_mgt", "")
        soil_name = hru_data.get("soil", "")
        hydro_name = hru_data.get("hydro", "")
        hydro = self.hydrology.get(hydro_name, {})

        cn2 = self.resolve_cn2(lu_mgt, soil_name)

        # Determine plant name from land use and map to plant.dat ID
        luse = lu_mgt.replace("_lum", "").upper()
        plant_name = luse[:4] if luse else "AGRL"
        plant_id_map = {
            "AGRL": 1, "FRSD": 2, "FRSE": 3, "FRST": 4, "PAST": 5,
            "RNGE": 6, "WETL": 7, "WATR": 8, "URBN": 9, "HAY": 10,
            "CORN": 11, "SOYB": 12,
        }
        ncrp = plant_id_map.get(plant_name, 1)
        # WATR and URBN should not have growing plants
        igro = 0 if plant_name in ("WATR", "URBN") else 1

        return {
            "NMGT": 0,
            "IGRO": igro,
            "NCRP": ncrp,
            "PHU_PLT": 1700.0,
            "PLANT_ID": plant_name,
            "LAIMX1": 0.0,
            "LAIMX2": 0.0,
            "BIO_MS": 1.0,
            "BIO_MIN": 0.0,
            "CNX": 0.0,
            "IURBAN": 0,
            "CFRT_ID": 0,
            "IFRT_FREQ": 0,
            "CFRT_KG": 0.0,
            "AUTO_NSTRS": 0,
            "AUTO_NAPP": 0.0,
            "AUTO_NYR": 0.0,
            "AUTO_EFF": 0.0,
            "AFRT_SURF": 0.0,
            "DDRAIN": 0,
            "TDRAIN": 0.0,
            "GDRAIN": 0.0,
            "NROT": 0,
            "CN2": cn2,
            "USLE_P": self.resolve_usle_p(lu_mgt),
            "BIOMIX": self._safe_float(hydro.get("bio_mix"), 0.2),
        }

    def get_rte_params(self, channel_name: str) -> Dict[str, float]:
        """
        Map SWAT+ channel to SWAT 2012 .rte file parameters.

        Args:
            channel_name: Name from channel-lte.cha (e.g., "cha001")
        """
        # Get the hydrology reference for this channel
        cha = self.channel_lte.get(channel_name, {})
        hyd_name = cha.get("cha_hyd", "")

        hyd = self.hyd_sed.get(hyd_name, {})

        return {
            "CH_W2": self._safe_float(hyd.get("wd"), 5.0),
            "CH_D": self._safe_float(hyd.get("dp"), 0.5),
            "CH_S2": self._safe_float(hyd.get("slp"), 0.001),
            "CH_L2": self._safe_float(hyd.get("len"), 5.0),
            "CH_N2": self._safe_float(hyd.get("mann"), 0.014),
            "CH_K2": self._safe_float(hyd.get("k"), 0.0),
            "CH_COV1": self._safe_float(hyd.get("cov_fact"), 0.0),
            "CH_COV2": self._safe_float(hyd.get("erod_fact"), 0.0),
            "CH_WDR": 4.0,
            "ALPHA_BNK": 0.0,
            "ICANAL": 0.0,
            "CH_ONCO": 0.0,
            "CH_OPCO": 0.0,
            "CH_SIDE": 0.0,
            "BANK_KFACT": 0.0,
            "BNK_D50": 0.0,
            "CH_KFACT": 0.0,
            "CH_D50": 0.0,
        }

    def get_sub_params(self, rtu_con: Dict, hru_cons: List[Dict]) -> Dict[str, Any]:
        """
        Map SWAT+ routing unit to SWAT 2012 .sub file parameters.

        Args:
            rtu_con: Row from rout_unit.con
            hru_cons: List of hru.con rows belonging to this subbasin
        """
        area = self._safe_float(rtu_con.get("area"), 100.0)
        lat = self._safe_float(rtu_con.get("lat"), 36.0)
        lon = self._safe_float(rtu_con.get("lon"), -94.0)
        elev = self._safe_float(rtu_con.get("elev"), 300.0)

        return {
            "SUB_KM": area,
            "SUB_ELEV": elev,
            "SUB_LAT": lat,
            "SUB_SLAT": lat - 0.1,
            "SUB_SHAPE": 1.0,
            "IRESSION": 1,
            "NUMBER_RECS": 0,
            "PLAPS": 0.0,
            "TLAPS": -6.0,
            "SNO_SUB": 0.0,
        }

    def get_soil_for_hru(self, soil_name: str) -> Optional[Dict]:
        """Get soil profile data for an HRU."""
        return self.soils.get(soil_name)
