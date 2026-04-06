"""
SWAT 2012 file writers.

Generates fixed-format SWAT 2012 input files with the
'value | PARAM_NAME : description' format expected by
SWAT-DG's ParameterModifier.
"""

from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


def _fmt(value, width=14, decimals=4) -> str:
    """Format a numeric value for SWAT 2012 fixed-width fields."""
    if isinstance(value, int) or (isinstance(value, float) and value == int(value) and abs(value) < 1e6):
        return f"{int(value):>{width}}"
    return f"{value:>{width}.{decimals}f}"


def _fmtf(value, width=14, decimals=2) -> str:
    """Format a float value."""
    return f"{float(value):>{width}.{decimals}f}"


def _fmts(value, width=16) -> str:
    """Format a string value (left-aligned)."""
    return f"{str(value):<{width}}"


class SWAT2012Writer:
    """Writes SWAT 2012 format input files."""

    def __init__(self, output_dir: str):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._timestamp = datetime.now().strftime("%m/%d/%Y  %I:%M:%S %p")

    def write_file_cio(
        self,
        nbyr: int,
        iyr: int,
        idaf: int = 1,
        idal: int = 365,
        nsub: int = 1,
        nhru: int = 1,
        nrch: int = 1,
        nyskip: int = 5,
        iprint: int = 1,
        nrgage: int = 1,
        nrtot: int = 9,
        ntgage: int = 1,
        nttot: int = 9,
    ):
        """
        Write file.cio master control file matching SWAT Fortran readfile.f read sequence.

        The SWAT exe reads file.cio line-by-line in a strict order defined by
        readfile.f (unit 101) and getallo.f (unit 23). Every line position matters.
        """
        lines = []
        # L1: titldum (a80) - project description line 1
        lines.append("Master Watershed File: SWAT+ to SWAT2012 Conversion")
        # L2: titldum (a80) - project description line 2
        lines.append("Project Description:")
        # L3: title (20a4) - simulation title
        lines.append("General Input/Output section (file.cio):")
        # L4: titldum (a80) - date/generator line
        lines.append(f"SWAT-DG converter {self._timestamp}")
        # L5: titldum (a80) - blank separator
        lines.append("")
        # L6: titldum (a80) - section header "General Information"
        lines.append("General Information/Watershed Configuration:")
        # L7: figfile (6a) - watershed configuration filename
        lines.append("fig.fig")
        # L8: nbyr (*) - number of calendar years
        lines.append(f"{nbyr:16}    | NBYR : Number of years simulated")
        # L7: iyr (*) - beginning year
        lines.append(f"{iyr:16}    | IYR : Beginning year of simulation")
        # L8: idaf (*) - beginning julian day
        lines.append(f"{idaf:16}    | IDAF : Beginning Julian day")
        # L9: idal (*) - ending julian day
        lines.append(f"{idal:16}    | IDAL : Ending Julian day")
        # L10: titldum (a80) - section header "Climate"
        lines.append("Climate:")
        # L11: igen (*) - random number seed code
        lines.append(f"{0:16}    | IGEN : Random number seed code")
        # L12: pcpsim (*) - rainfall input code (1=measured)
        lines.append(f"{1:16}    | PCPSIM : Rainfall input code (1=measured)")
        # L13: idt (*) - time step length in minutes (0=daily)
        lines.append(f"{0:16}    | IDT : Rainfall time step (min, 0=daily)")
        # L14: idist (*) - rainfall distribution code
        lines.append(f"{0:16}    | IDIST : Rainfall distribution code")
        # L15: rexp (*) - exponential distribution exponent
        lines.append(f"{1.3:16.1f}    | REXP : Exponent for exponential rainfall dist")
        # L16: nrgage (*) - number of raingage files
        lines.append(f"{nrgage:16}    | NRGAGE : Number of raingage files")
        # L17: nrtot (*) - total number of rain gages
        lines.append(f"{nrtot:16}    | NRTOT : Total number of rain gages")
        # L18: nrgfil (*) - number of rain gages per file
        lines.append(f"{nrtot:16}    | NRGFIL : Number of rain gages per file")
        # L19: tmpsim (*) - temperature input code (1=measured)
        lines.append(f"{1:16}    | TMPSIM : Temperature input code (1=measured)")
        # L20: ntgage (*) - number of temperature gage files
        lines.append(f"{ntgage:16}    | NTGAGE : Number of temp gage files")
        # L21: nttot (*) - total number of temperature gages
        lines.append(f"{nttot:16}    | NTTOT : Total number of temp gages")
        # L22: ntgfil (*) - number of temp gages per file
        lines.append(f"{nttot:16}    | NTGFIL : Number of temp gages per file")
        # L23: slrsim (*) - solar radiation input code (2=simulated)
        lines.append(f"{2:16}    | SLRSIM : Solar radiation input code (2=generated)")
        # L24: nstot (*) - number of solar radiation records
        lines.append(f"{0:16}    | NSTOT : Number of solar radiation records")
        # L25: rhsim (*) - relative humidity input code (2=simulated)
        lines.append(f"{2:16}    | RHSIM : Relative humidity input code (2=generated)")
        # L26: nhtot (*) - number of RH records
        lines.append(f"{0:16}    | NHTOT : Number of relative humidity records")
        # L27: wndsim (*) - wind speed input code (2=simulated)
        lines.append(f"{2:16}    | WNDSIM : Wind speed input code (2=generated)")
        # L28: nwtot (*) - number of wind speed records
        lines.append(f"{0:16}    | NWTOT : Number of wind speed records")
        # L29: fcstyr (*) - forecast beginning year
        lines.append(f"{0:16}    | FCSTYR : Beginning year of forecast period")
        # L30: fcstday (*) - forecast beginning day
        lines.append(f"{0:16}    | FCSTDAY : Beginning date of forecast period")
        # L31: fcstcycles (*) - number of forecast cycles
        lines.append(f"{0:16}    | FCSTCYCLES : Number of forecast cycles")
        # L32: titldum (a80) - section header "Precipitation Files"
        lines.append("Precipitation Files:")
        # L33-35: rfile(1:18) (6a) - reads 3 lines of 6 filenames each
        lines.append("pcp1.pcp")
        lines.append("")  # rfile line 2 (unused stations)
        lines.append("")  # rfile line 3 (unused stations)
        # L36: titldum (a80) - section header "Temperature Files"
        lines.append("Temperature Files:")
        # L37-39: tfile(1:18) (6a) - reads 3 lines of 6 filenames each
        lines.append("tmp1.tmp")
        lines.append("")  # tfile line 2
        lines.append("")  # tfile line 3
        # L40: slrfile (6a) - solar radiation filename
        lines.append("slr.slr")
        # L41: rhfile (6a) - relative humidity filename
        lines.append("hmd.hmd")
        # L42: wndfile (6a) - wind speed filename
        lines.append("wnd.wnd")
        # L43: fcstfile (6a) - forecast data filename
        lines.append("")
        # L40: titldum (a80) - section header "Watershed Modeling"
        lines.append("Watershed Modeling Options:")
        # L41: bsnfile (6a) - basin input filename
        lines.append("basins.bsn")
        # L42: titldum (a80) - section header "Database Files"
        lines.append("Database Files:")
        # L43: plantdb (6a) - plant/crop database
        lines.append("plant.dat")
        # L44: tilldb (6a) - tillage database
        lines.append("till.dat")
        # L45: pestdb (6a) - pesticide database
        lines.append("pest.dat")
        # L46: fertdb (6a) - fertilizer database
        lines.append("fert.dat")
        # L47: urbandb (6a) - urban database
        lines.append("urban.dat")
        # L48: titldum (a80) - section header "Special Projects"
        lines.append("Special Projects:")
        # L49: isproj (*) - special project code
        lines.append(f"{0:16}    | ISPROJ : Special project code")
        # L50: iclb (*) - auto-calibration flag
        lines.append(f"{0:16}    | ICLB : Auto-calibration flag")
        # L51: calfile (6a) - calibration parameters filename
        lines.append("")
        # L52: titldum (a80) - section header "Output Information"
        lines.append("Output Information:")
        # L53: iprint (*) - print code
        lines.append(f"{iprint:16}    | IPRINT : Print code (0=monthly,1=daily,2=annual)")
        # L54: nyskip (*) - years to skip output
        lines.append(f"{nyskip:16}    | NYSKIP : Number of years to skip output")
        # L55: ilog (*) - streamflow print code
        lines.append(f"{0:16}    | ILOG : Streamflow print code")
        # L56: iprp (*) - pesticide output print code
        lines.append(f"{0:16}    | IPRP : Pesticide output print code")
        # L57: titldum (a80)
        lines.append("Output variables:")
        # L58: titldum (a80) - section header "REACH output"
        lines.append("Reach output variables (output.rch):")
        # L59: ipdvar(1:20) (*) - reach output variable codes (0=all)
        lines.append("    0    0    0    0    0    0    0    0    0    0    0    0    0    0    0    0    0    0    0    0")
        # L60: titldum (a80) - section header "SUBBASIN output"
        lines.append("Subbasin output variables (output.sub):")
        # L61: ipdvab(1:15) (*) - subbasin output codes
        lines.append("    0    0    0    0    0    0    0    0    0    0    0    0    0    0    0")
        # L62: titldum (a80) - section header "HRU output"
        lines.append("HRU output variables (output.hru):")
        # L63: ipdvas(1:20) (*) - HRU output variable codes
        lines.append("    0    0    0    0    0    0    0    0    0    0    0    0    0    0    0    0    0    0    0    0")
        # L64: titldum (a80) - section header "HRUs printed"
        lines.append("HRUs printed in output.hru/output.wtr:")
        # L65: ipdhru(1:20) (*) - HRU numbers for output
        lines.append("    0    0    0    0    0    0    0    0    0    0    0    0    0    0    0    0    0    0    0    0")
        # L66: titldum (a80) - section header "Atmospheric deposition"
        lines.append("Atmospheric Deposition:")
        # L67: atmofile (6a) - atmospheric deposition filename
        lines.append("")
        # L68: iphr (*) - hourly output (optional, iostat)
        lines.append(f"{0:16}    | IPHR : Hourly output flag")
        # L69: isto (*) - soil storage output (optional, iostat)
        lines.append(f"{0:16}    | ISTO : Soil storage output flag")
        # L70: isol (*) - soil nutrients output (optional, iostat)
        lines.append(f"{0:16}    | ISOL : Soil nutrient output flag")
        # L71: i_subhw (*) - headwater routing code (optional, iostat)
        lines.append(f"{0:16}    | I_SUBHW : Headwater routing code")
        # L72: septdb (6a) - septic database (optional, iostat)
        lines.append("")
        # L73: ia_b (*) - ASCII/binary (optional, iostat)
        lines.append(f"{0:16}    | IA_B : ASCII/binary output (0=ascii)")
        # L74: ihumus (*) - water quality output (optional, iostat)
        lines.append(f"{0:16}    | IHUMUS : Water quality output flag")
        # L75: itemp (*) - temperature/velocity output (optional, iostat)
        lines.append(f"{0:16}    | ITEMP : Temp/velocity output flag")
        # L76: isnow (*) - elevation band output (optional, iostat)
        lines.append(f"{0:16}    | ISNOW : Elevation band snow output flag")
        # L77: imgt (*) - management output (optional, iostat)
        lines.append(f"{0:16}    | IMGT : Management output flag")
        # L78: iwtr (*) - water table output (optional, iostat)
        lines.append(f"{0:16}    | IWTR : Water table/pothole output flag")
        # L79: icalen (*) - calendar day flag (optional, iostat)
        lines.append(f"{0:16}    | ICALEN : Calendar day output (0=julian)")

        filepath = self.output_dir / "file.cio"
        with open(filepath, "w") as f:
            f.write("\n".join(lines) + "\n")
        logger.info(f"Wrote {filepath}")

    def write_basins_bsn(self, params: Dict[str, float]):
        """
        Write basins.bsn matching readbsn.f read sequence exactly.

        readbsn.f reads (unit 103) with free-format reads and
        titldum section headers interleaved at specific positions.
        """
        def _f(name, default=0.0):
            return float(params.get(name, default))
        def _i(name, default=0):
            return int(params.get(name, default))

        lines = []
        # L1-3: 3 titldum (title lines read by readbsn.f Rev 681)
        # readbsn.f reads exactly 3 header lines with format(a).
        lines.append("Basin Parameters - SWAT+ to SWAT2012 Conversion")
        lines.append(f"Generated by SWAT-DG converter {self._timestamp}")
        lines.append("Basin-wide model parameters:")
        # L4-10: snow + PET parameters
        lines.append(f"{_f('SFTMP', 1.0):16.4f}    | SFTMP : Snowfall temperature (deg C)")
        lines.append(f"{_f('SMTMP', 0.5):16.4f}    | SMTMP : Snow melt base temperature (deg C)")
        lines.append(f"{_f('SMFMX', 4.5):16.4f}    | SMFMX : Melt factor for Jun 21 (mm/deg C-day)")
        lines.append(f"{_f('SMFMN', 4.5):16.4f}    | SMFMN : Melt factor for Dec 21 (mm/deg C-day)")
        lines.append(f"{_f('TIMP', 1.0):16.4f}    | TIMP : Snow pack temperature lag factor")
        lines.append(f"{_f('SNOCOVMX', 1.0):16.4f}    | SNOCOVMX : Min snow water content (mm H2O)")
        lines.append(f"{_f('SNO50COV', 0.5):16.4f}    | SNO50COV : Fraction of snow coverage at 50% cover")
        # L11: IPET
        lines.append(f"{_i('IPET', 1):16}    | IPET : PET method (0=PT, 1=PM, 2=Harg, 3=Read)")
        # L12: petfile (format 1000 = a string line)
        lines.append(f"               ")  # blank = no PET file
        # L13-14: ESCO, EPCO
        lines.append(f"{_f('ESCO', 0.95):16.4f}    | ESCO : Soil evaporation compensation factor")
        lines.append(f"{_f('EPCO', 1.0):16.4f}    | EPCO : Plant uptake compensation factor")
        # L15-16: EVLAI, FFCB
        lines.append(f"{_f('EVLAI', 3.0):16.4f}    | EVLAI : Leaf area index at which no evap from soil")
        lines.append(f"{_f('FFCB', 0.0):16.4f}    | FFCB : Initial soil water storage fraction of FC")
        # L17: titldum (section header)
        lines.append("Runoff/Erosion:")
        # L18-24: runoff/erosion params
        lines.append(f"{_i('IEVENT', 0):16}    | IEVENT : Rainfall/runoff code")
        lines.append(f"{_i('ICRK', 0):16}    | ICRK : Crack flow code")
        lines.append(f"{_f('SURLAG', 4.0):16.4f}    | SURLAG : Surface runoff lag coefficient")
        lines.append(f"{_f('ADJ_PKR', 1.0):16.4f}    | ADJ_PKR : Peak rate adjustment factor")
        lines.append(f"{_f('PRF', 1.0):16.4f}    | PRF : Peak rate adjustment for sediment routing")
        lines.append(f"{_f('SPCON', 0.0001):16.4f}    | SPCON : Linear param for sediment routing")
        lines.append(f"{_f('SPEXP', 1.0):16.4f}    | SPEXP : Exponent param for sediment routing")
        # L25: titldum
        lines.append("Nutrients:")
        # L26-34: nutrient params
        lines.append(f"{_f('RCN', 1.0):16.4f}    | RCN : Concentration of N in rainfall (mg/L)")
        lines.append(f"{_f('CMN', 0.0003):16.4f}    | CMN : Rate factor for humus mineralization")
        lines.append(f"{_f('N_UPDIS', 20.0):16.4f}    | N_UPDIS : Nitrogen uptake distribution param")
        lines.append(f"{_f('P_UPDIS', 20.0):16.4f}    | P_UPDIS : Phosphorus uptake distribution param")
        lines.append(f"{_f('NPERCO', 0.1):16.4f}    | NPERCO : Nitrogen percolation coefficient")
        lines.append(f"{_f('PPERCO', 10.0):16.4f}    | PPERCO : Phosphorus percolation coefficient")
        lines.append(f"{_f('PHOSKD', 175.0):16.4f}    | PHOSKD : Phosphorus soil partitioning coeff")
        lines.append(f"{_f('PSP', 0.4):16.4f}    | PSP : Phosphorus sorption coefficient")
        lines.append(f"{_f('RSDCO', 0.05):16.4f}    | RSDCO : Residue decomposition coefficient")
        # L35: titldum
        lines.append("Pesticides:")
        # L36: PERCOP
        lines.append(f"{_f('PERCOP', 0.5):16.4f}    | PERCOP : Pesticide percolation coefficient")
        # L37: titldum
        lines.append("Water Quality:")
        # L38: ISUBWQ
        lines.append(f"{_i('ISUBWQ', 0):16}    | ISUBWQ : Subbasin water quality code")
        # L39: titldum
        lines.append("Bacteria:")
        # L40-55: bacteria params
        lines.append(f"{_f('WDPQ', 1.0):16.4f}    | WDPQ : Die-off persistent bacteria in soil (1/d)")
        lines.append(f"{_f('WGPQ', 1.0):16.4f}    | WGPQ : Growth persistent bacteria in soil (1/d)")
        lines.append(f"{_f('WDLPQ', 1.0):16.4f}    | WDLPQ : Die-off less persist bact in soil (1/d)")
        lines.append(f"{_f('WGLPQ', 1.0):16.4f}    | WGLPQ : Growth less persist bact in soil (1/d)")
        lines.append(f"{_f('WDPS', 1.0):16.4f}    | WDPS : Die-off persist bact on foliage (1/d)")
        lines.append(f"{_f('WGPS', 1.0):16.4f}    | WGPS : Growth persist bact on foliage (1/d)")
        lines.append(f"{_f('WDLPS', 1.0):16.4f}    | WDLPS : Die-off less persist bact foliage (1/d)")
        lines.append(f"{_f('WGLPS', 1.0):16.4f}    | WGLPS : Growth less persist bact foliage (1/d)")
        lines.append(f"{_f('BACTKDQ', 35.0):16.4f}    | BACTKDQ : Bact soil partition coefficient")
        lines.append(f"{_f('THBACT', 1.07):16.4f}    | THBACT : Temp adj factor for bacteria")
        lines.append(f"{_i('WOF_P', 0):16}    | WOF_P : Wash off fraction persistent")
        lines.append(f"{_i('WOF_LP', 0):16}    | WOF_LP : Wash off fraction less persistent")
        lines.append(f"{_f('WDPF', 0.0):16.4f}    | WDPF : Persist bact die-off in water (1/d)")
        lines.append(f"{_f('WGPF', 0.0):16.4f}    | WGPF : Persist bact growth in water (1/d)")
        lines.append(f"{_f('WDLPF', 0.0):16.4f}    | WDLPF : Less persist bact die-off water (1/d)")
        lines.append(f"{_f('WGLPF', 0.0):16.4f}    | WGLPF : Less persist bact growth water (1/d)")
        # L56: ISED_DET (format 1001 = (i4))
        lines.append(f"{_i('ISED_DET', 0):4}    | ISED_DET : Sediment routing method")
        # L57: titldum
        lines.append("Channel Routing:")
        # L58-63: routing params
        lines.append(f"{_i('IRTE', 0):16}    | IRTE : Channel routing method (0=VarStor, 1=Musk)")
        lines.append(f"{_f('MSK_CO1', 0.75):16.4f}    | MSK_CO1 : Muskingum calibration coeff 1")
        lines.append(f"{_f('MSK_CO2', 0.25):16.4f}    | MSK_CO2 : Muskingum calibration coeff 2")
        lines.append(f"{_f('MSK_X', 0.2):16.4f}    | MSK_X : Muskingum weighting factor")
        lines.append(f"{_i('IDEG', 0):16}    | IDEG : Channel degradation code")
        lines.append(f"{_i('IWQ', 0):16}    | IWQ : In-stream water quality code")
        # L64: wwqfile (format 1000 = string) - must exist, readbsn.f opens unconditionally
        lines.append(f"basins.wwq")
        # L65-72: more routing/WQ params
        lines.append(f"{_f('TRNSRCH', 0.0):16.4f}    | TRNSRCH : Reach transmission loss fraction")
        lines.append(f"{_f('EVRCH', 0.6):16.4f}    | EVRCH : Reach evaporation adj factor")
        lines.append(f"{_i('IRTPEST', 0):16}    | IRTPEST : Pesticide in-stream routing")
        lines.append(f"{_i('ICN', 0):16}    | ICN : Daily CN calculation method")
        lines.append(f"{_f('CNCOEF', 1.0):16.4f}    | CNCOEF : Plant ET curve number coefficient")
        lines.append(f"{_f('CDN', 1.4):16.4f}    | CDN : Denitrification exponential rate coeff")
        lines.append(f"{_f('SDNCO', 1.1):16.4f}    | SDNCO : Denitrification threshold water content")
        lines.append(f"{_f('BACT_SWF', 0.15):16.4f}    | BACT_SWF : Fraction of manure with active bact")
        # After L72: optional params with iostat (graceful EOF handling)
        lines.append(f"{_f('BACTMX', 10.0):16.4f}    | BACTMX : Bact percolation coefficient")
        lines.append(f"{_f('BACTMINLP', 0.0):16.4f}    | BACTMINLP : Min less persist bact threshold")
        lines.append(f"{_f('BACTMINP', 0.0):16.4f}    | BACTMINP : Min persist bact threshold")
        lines.append(f"{_f('WDLPRCH', 0.0):16.4f}    | WDLPRCH : Die-off LP bact in reach (1/d)")
        lines.append(f"{_f('WDPRCH', 0.0):16.4f}    | WDPRCH : Die-off P bact in reach (1/d)")
        lines.append(f"{_f('WDLPRES', 0.0):16.4f}    | WDLPRES : Die-off LP bact in reservoir (1/d)")
        lines.append(f"{_f('WDPRES', 0.0):16.4f}    | WDPRES : Die-off P bact in reservoir (1/d)")
        lines.append(f"{_f('TB_ADJ', 0.0):16.4f}    | TB_ADJ : Temp adj for basin")
        lines.append(f"{_f('DEPIMP_BSN', 6000):16.4f}    | DEPIMP_BSN : Depth to impervious layer (mm)")
        lines.append(f"{_f('DDRAIN_BSN', 0.0):16.4f}    | DDRAIN_BSN : Depth to drain (mm)")
        lines.append(f"{_f('TDRAIN_BSN', 0.0):16.4f}    | TDRAIN_BSN : Time to drain (hr)")
        lines.append(f"{_f('GDRAIN_BSN', 0.0):16.4f}    | GDRAIN_BSN : Tile drain lag time (hr)")
        lines.append(f"{_f('CN_FROZ', 0.000862):16.6f}    | CN_FROZ : Frozen soil adj on infiltration")
        lines.append(f"{_f('DORM_HR', 0.0):16.4f}    | DORM_HR : Dormancy threshold hours")
        lines.append(f"{_f('SMXCO', 1.0):16.4f}    | SMXCO : Max soil water content adjustment")
        lines.append(f"{_f('FIXCO', 0.5):16.4f}    | FIXCO : N fixation coefficient")
        lines.append(f"{_f('NFIXMX', 20.0):16.4f}    | NFIXMX : Max daily N fixation (kg/ha)")
        lines.append(f"{_f('ANION_EXCL_BSN', 0.5):16.4f}    | ANION_EXCL_BSN : Anion exclusion fraction")
        lines.append(f"{_f('CH_ONCO_BSN', 0.0):16.4f}    | CH_ONCO_BSN : Channel organic N conc (ppm)")
        lines.append(f"{_f('CH_OPCO_BSN', 0.0):16.4f}    | CH_OPCO_BSN : Channel organic P conc (ppm)")
        lines.append(f"{_f('HLIFE_NGW_BSN', 0.0):16.4f}    | HLIFE_NGW_BSN : Half-life nitrate in GW (d)")
        # titldum before reach WQ parameters
        lines.append("Reach Water Quality:")
        lines.append(f"{_f('BC1_BSN', 0.1):16.4f}    | BC1 : Rate constant for oxidation NH3->NO2")
        lines.append(f"{_f('BC2_BSN', 0.1):16.4f}    | BC2 : Rate constant for oxidation NO2->NO3")
        lines.append(f"{_f('BC3_BSN', 0.02):16.4f}    | BC3 : Rate constant for hydrolysis orgN->NH3")
        lines.append(f"{_f('BC4_BSN', 0.01):16.4f}    | BC4 : Rate constant for decay orgP->dissP")
        lines.append(f"{_f('DECR_MIN', 0.01):16.4f}    | DECR_MIN : Min dissolved oxygen change rate")
        lines.append(f"{_i('ICFAC', 0):16}    | ICFAC : C-factor calculation method")
        lines.append(f"{_f('RSD_COVCO', 0.3):16.4f}    | RSD_COVCO : Residue cover factor for erosion")
        lines.append(f"{_f('VCRIT', 0.0):16.4f}    | VCRIT : Critical velocity for erosion")
        lines.append(f"{_i('CSWAT', 0):16}    | CSWAT : Carbon model (0=orig, 1=C-FARM, 2=Century)")
        lines.append(f"{_f('RES_STLR_CO', 0.184):16.4f}    | RES_STLR_CO : Reservoir settling coeff")
        lines.append(f"{_i('BF_FLG', 0):16}    | BF_FLG : Baseflow recession method")
        lines.append(f"{_i('IUH', 1):16}    | IUH : Unit hydrograph method")
        lines.append(f"{_f('UHALPHA', 1.0):16.4f}    | UHALPHA : Unit hydro alpha factor")
        # L532-533 in readbsn.f: titldum then tlu (land use list)
        lines.append("Land Use Change:")
        lines.append("   ")  # empty tlu = no land use filtering (len_trim <= 3)

        filepath = self.output_dir / "basins.bsn"
        with open(filepath, "w") as f:
            f.write("\n".join(lines) + "\n")
        logger.info(f"Wrote {filepath}")

    def write_sub_file(
        self,
        sub_id: int,
        params: Dict[str, Any],
        hru_files: List[str],
        pcp_file: str = "pcp1.pcp",
        tmp_file: str = "tmp1.tmp",
        rte_file: str = None,
    ):
        """
        Write SSSSS0000.sub subbasin file matching SWAT Fortran readsub.f format.

        The .sub file has exactly 52 lines of parameters before the HRU count
        on line 53 (getallo.f skips 52 lines then reads numhru).
        Then 7 header lines, then HRU file references.
        """
        sub_str = f"{sub_id:05d}"
        if rte_file is None:
            rte_file = f"{sub_str}0000.rte"

        sub_km = params.get("SUB_KM", 10.0)
        sub_lat = params.get("SUB_LAT", 36.0)
        sub_elev = params.get("SUB_ELEV", 300.0)
        nhru = len(hru_files)

        lines = []
        # L1: title (5100 format - 20a4)
        lines.append(f" .sub file Subbasin:{sub_id}  {self._timestamp}  ArcSWAT 2012/SWAT-DG")
        # L2: sub_km (free format)
        lines.append(f"{sub_km:16.4f}    | SUB_KM : Subbasin area (km2)")
        # L3: title or conditional (isproj==3 has special format, otherwise title)
        lines.append(f"Subbasin climate parameters")
        # L4: title
        lines.append(f"Elevation Bands:")
        # L5: sub_lat
        lines.append(f"{sub_lat:16.4f}    | SUB_LAT : Latitude of subbasin (deg)")
        # L6: sub_elev
        lines.append(f"{sub_elev:16.4f}    | SUB_ELEV : Elevation of subbasin (m)")
        # L7: irgage - rain gage data code (1=gage 1)
        lines.append(f"{1:16}    | IRGAGE : Raingage data code")
        # L8: itgage - temp gage data code
        lines.append(f"{1:16}    | ITGAGE : Tempgage data code")
        # L9: isgage - solar rad gage code (0=simulated)
        lines.append(f"{0:16}    | ISGAGE : Solar rad gage code")
        # L10: ihgage - humidity gage code (0=simulated)
        lines.append(f"{0:16}    | IHGAGE : Relative humidity gage code")
        # L11: iwgage - wind speed gage code (0=simulated)
        lines.append(f"{0:16}    | IWGAGE : Wind speed gage code")
        # L12: wgnfile (5300 format = 8a13) - weather generator filename
        wgn_name = params.get("WGNFILE", f"{sub_str}0000.wgn")
        lines.append(f"{wgn_name:<13s}")
        # L13: fcst_reg
        lines.append(f"{0:16}    | FCST_REG : Forecast region")
        # L14-L15: 2 title lines
        lines.append(f"Elevation band data:")
        lines.append(f"   Elevation (m)")
        # L16: elevb(1:10) - elevation band elevations (5200 format = 10f8.1)
        lines.append(f"{0.0:8.1f}" * 10)
        # L17: title
        lines.append(f"   Fraction of area")
        # L18: elevb_fr(1:10) - elevation band fractions
        lines.append(f"{0.0:8.1f}" * 10)
        # L19: title
        lines.append(f"   Initial snow (mm)")
        # L20: ssnoeb(1:10) - initial snow
        lines.append(f"{0.0:8.1f}" * 10)
        # L21: plaps
        lines.append(f"{0.0:16.4f}    | PLAPS : Precipitation lapse rate (mm/km)")
        # L22: tlaps
        lines.append(f"{-6.0:16.4f}    | TLAPS : Temperature lapse rate (deg C/km)")
        # L23: sno_sub
        lines.append(f"{0.0:16.4f}    | SNO_SUB : Initial snow water content (mm)")
        # L24: title
        lines.append(f"Tributary channel parameters:")
        # L25: ch_ls
        lines.append(f"{5.0:16.4f}    | CH_L1 : Longest tributary channel length (km)")
        # L26: ch_s(1)
        lines.append(f"{0.01:16.4f}    | CH_S1 : Average slope of tributary channel (m/m)")
        # L27: ch_w(1)
        lines.append(f"{5.0:16.4f}    | CH_W1 : Average width of tributary channel (m)")
        # L28: ch_k(1)
        lines.append(f"{0.01:16.4f}    | CH_K1 : Effective hydraulic conductivity (mm/hr)")
        # L29: ch_n(1)
        lines.append(f"{0.05:16.4f}    | CH_N1 : Manning's n for tributary channel")
        # L30: title
        lines.append(f"Pond/wetland data:")
        # L31: pndfile (5300 = 8a13)
        pnd_name = params.get("PNDFILE", f"{sub_str}0000.pnd")
        lines.append(f"{pnd_name:<13s}")
        # L32: title
        lines.append(f"Water use data:")
        # L33: wusfile (5300 = 8a13)
        wus_name = params.get("WUSFILE", f"{sub_str}0000.wus")
        lines.append(f"{wus_name:<13s}")
        # L34: snofile (5100 - read as title/string)
        lines.append(f"             ")  # blank
        # L35: co2
        lines.append(f"{400.0:16.4f}    | CO2 : CO2 concentration (ppmv)")
        # L36: title
        lines.append(f"Monthly rainfall adjustment (Jan-Jun):")
        # L37: rfinc(1:6) - 6 monthly rainfall adjustments (5200 = 10f8.1 but only 6)
        lines.append(f"{0.0:8.1f}" * 6)
        # L38: title
        lines.append(f"Monthly rainfall adjustment (Jul-Dec):")
        # L39: rfinc(7:12)
        lines.append(f"{0.0:8.1f}" * 6)
        # L40: title
        lines.append(f"Monthly temperature adjustment (Jan-Jun):")
        # L41: tmpinc(1:6)
        lines.append(f"{0.0:8.1f}" * 6)
        # L42: title
        lines.append(f"Monthly temperature adjustment (Jul-Dec):")
        # L43: tmpinc(7:12)
        lines.append(f"{0.0:8.1f}" * 6)
        # L44: title
        lines.append(f"Monthly radiation adjustment (Jan-Jun):")
        # L45: radinc(1:6)
        lines.append(f"{0.0:8.1f}" * 6)
        # L46: title
        lines.append(f"Monthly radiation adjustment (Jul-Dec):")
        # L47: radinc(7:12)
        lines.append(f"{0.0:8.1f}" * 6)
        # L48: title
        lines.append(f"Monthly humidity adjustment (Jan-Jun):")
        # L49: huminc(1:6)
        lines.append(f"{0.0:8.1f}" * 6)
        # L50: title
        lines.append(f"Monthly humidity adjustment (Jul-Dec):")
        # L51: huminc(7:12)
        lines.append(f"{0.0:8.1f}" * 6)
        # L52: title -- THIS IS LINE 52 (getallo skips to here)
        lines.append(f"HRU data:")
        # L53: hrutot -- NUMBER OF HRUs (getallo reads this on line 53)
        lines.append(f"{nhru:16}    | HRUTOT : Total number of HRUs in subbasin")

        # Verify we have exactly 53 lines so far
        assert len(lines) == 53, f"Expected 53 lines, got {len(lines)}"

        # L54-L61: 8 title lines (readsub reads 8 titldum after hrutot)
        lines.append(f"HRU: Luse Soil Slp_len Slp OV_N Lat Lon Elev")
        lines.append(f"          HRU file   MGT file   SOL file   CHM file   GW file    OPS file   SEP file   SDR file   ILS2")
        for _ in range(5):
            lines.append(f"")
        lines.append(f"General HRUs:")

        # HRU file references: readsub reads format(8a13,i6)
        for hru_file in hru_files:
            base = hru_file.replace(".hru", "")
            # 8 filenames (a13 each) + ils2 (i6)
            hru_f = f"{base}.hru"
            mgt_f = f"{base}.mgt"
            sol_f = f"{base}.sol"
            chm_f = f"{base}.chm"
            gw_f = f"{base}.gw"
            ops_f = f""  # optional
            sep_f = f""  # optional
            sdr_f = f""  # optional
            lines.append(
                f"{hru_f:13s}{mgt_f:13s}{sol_f:13s}{chm_f:13s}"
                f"{gw_f:13s}{ops_f:13s}{sep_f:13s}{sdr_f:13s}{0:6d}"
            )

        filepath = self.output_dir / f"{sub_str}0000.sub"
        with open(filepath, "w") as f:
            f.write("\n".join(lines) + "\n")

    def write_rte_file(self, sub_id: int, params: Dict[str, float]):
        """Write SSSSS0000.rte reach routing file."""
        sub_str = f"{sub_id:05d}"
        lines = []
        # L1: titldum (ONE title line only - readrte.f reads one)
        lines.append(f" .rte file Reach:{sub_id:5d} {self._timestamp}")

        rte_params = [
            ("CH_W2", "Average width of main channel (m)", 2),
            ("CH_D", "Average depth of main channel (m)", 2),
            ("CH_S2", "Average slope of main channel (m/m)", 4),
            ("CH_L2", "Length of main channel (km)", 2),
            ("CH_N2", "Manning's n for main channel", 4),
            ("CH_K2", "Effective hydraulic conductivity (mm/hr)", 2),
            ("CH_COV1", "Channel cover factor", 2),
            ("CH_COV2", "Channel erodibility factor", 2),
            ("CH_WDR", "Channel width/depth ratio", 2),
            ("ALPHA_BNK", "Baseflow alpha factor for bank storage", 2),
            ("ICANAL", "Canal flag", 2),
            ("CH_ONCO", "Organic N concentration (mg/L)", 2),
            ("CH_OPCO", "Organic P concentration (mg/L)", 2),
            ("CH_SIDE", "Change in channel width / unit change in depth", 2),
            ("BANK_KFACT", "Bank USLE K factor", 2),
            ("BNK_D50", "D50 particle size of bank sediment (um)", 2),
            ("CH_KFACT", "Channel USLE K factor", 2),
            ("CH_D50", "D50 particle size of channel bed (um)", 2),
        ]

        for name, desc, dec in rte_params:
            val = params.get(name, 0.0)
            lines.append(f"{val:>14.{dec}f}    | {name} : {desc}")

        filepath = self.output_dir / f"{sub_str}0000.rte"
        with open(filepath, "w") as f:
            f.write("\n".join(lines) + "\n")

    def write_wgn_file(self, sub_id: int, wgn_data: Dict):
        """
        Write SSSSS0000.wgn weather generator file matching readwgn.f format.

        readwgn.f reads from unit 114:
        L1: titldum (format a)
        L2: wlat (format 12x,f7.2)
        L3: welev (format 12x,f7.2)
        L4: rain_yrs (format 12x,f7.2)
        L5-L18: 14 rows of monthly data (12 values each)
            tmpmx(12), tmpmn(12), tmpstdmx(12), tmpstdmn(12) → format 12f6.2
            pcpmm(12) → format 12f6.1
            pcpsd(12), pcpskw(12), pr_w1(12), pr_w2(12), pcpd(12),
            rainhhmx(12), solarav(12), dewpt(12), wndav(12) → format 12f6.2
        """
        sub_str = f"{sub_id:05d}"
        monthly = wgn_data.get("monthly", [])
        if len(monthly) != 12:
            return

        lines = []
        # L1: title
        lines.append(f" Station: sub{sub_id}  Lati:  {wgn_data.get('lat', 36.0):.2f}  Long: {wgn_data.get('lon', -94.0):.2f}  Elev: {wgn_data.get('elev', 300.0):.0f}")
        # L2: wlat (12x,f7.2)
        lines.append(f"{'LATI/LONG':12s}{wgn_data.get('lat', 36.0):7.2f}")
        # L3: welev (12x,f7.2)
        lines.append(f"{'ELEVATION':12s}{wgn_data.get('elev', 300.0):7.2f}")
        # L4: rain_yrs (12x,f7.2)
        lines.append(f"{'RAIN_YRS':12s}{float(wgn_data.get('rain_yrs', 32)):7.2f}")

        # Helper to extract monthly values
        def monthly_vals(key):
            return [m.get(key, 0.0) for m in monthly]

        # L5: tmpmx (12f6.2)
        vals = monthly_vals("tmpmx")
        lines.append("".join(f"{v:6.2f}" for v in vals))
        # L6: tmpmn (12f6.2)
        vals = monthly_vals("tmpmn")
        lines.append("".join(f"{v:6.2f}" for v in vals))
        # L7: tmpstdmx (12f6.2)
        vals = monthly_vals("tmpstdmx")
        lines.append("".join(f"{v:6.2f}" for v in vals))
        # L8: tmpstdmn (12f6.2)
        vals = monthly_vals("tmpstdmn")
        lines.append("".join(f"{v:6.2f}" for v in vals))
        # L9: pcpmm (12f6.1)
        vals = monthly_vals("pcpmm")
        lines.append("".join(f"{v:6.1f}" for v in vals))
        # L10: pcpsd (12f6.2)
        vals = monthly_vals("pcpsd")
        lines.append("".join(f"{v:6.2f}" for v in vals))
        # L11: pcpskw (12f6.2)
        vals = monthly_vals("pcpskw")
        lines.append("".join(f"{v:6.2f}" for v in vals))
        # L12: pr_w1 = wet_dry (12f6.2)
        vals = monthly_vals("wetdry")
        lines.append("".join(f"{v:6.2f}" for v in vals))
        # L13: pr_w2 = wet_wet (12f6.2)
        vals = monthly_vals("wetwet")
        lines.append("".join(f"{v:6.2f}" for v in vals))
        # L14: pcpd (12f6.2)
        vals = monthly_vals("pcpd")
        lines.append("".join(f"{v:6.2f}" for v in vals))
        # L15: rainhhmx = pcp_hhr (12f6.2)
        vals = monthly_vals("pcphhr")
        lines.append("".join(f"{v:6.2f}" for v in vals))
        # L16: solarav (12f6.2)
        vals = monthly_vals("slrav")
        lines.append("".join(f"{v:6.2f}" for v in vals))
        # L17: dewpt (12f6.2)
        vals = monthly_vals("dewpt")
        lines.append("".join(f"{v:6.2f}" for v in vals))
        # L18: wndav (12f6.2)
        vals = monthly_vals("wndav")
        lines.append("".join(f"{v:6.2f}" for v in vals))

        filepath = self.output_dir / f"{sub_str}0000.wgn"
        with open(filepath, "w") as f:
            f.write("\n".join(lines) + "\n")

    def write_pnd_file(self, sub_id: int):
        """Write minimal SSSSS0000.pnd pond file. readpnd.f uses iostat on all reads."""
        sub_str = f"{sub_id:05d}"
        lines = []
        lines.append(f" .pnd file Subbasin:{sub_id:5d}")
        lines.append("Pond/Wetland Parameters:")
        # Write all zeros for the ~26 pond params so readpnd doesn't get garbage
        for _ in range(26):
            lines.append(f"{0.0:16.4f}")
        # Wetland section title
        lines.append("Wetland Parameters:")
        for _ in range(26):
            lines.append(f"{0.0:16.4f}")
        filepath = self.output_dir / f"{sub_str}0000.pnd"
        with open(filepath, "w") as f:
            f.write("\n".join(lines) + "\n")

    def write_wus_file(self, sub_id: int):
        """
        Write minimal SSSSS0000.wus water use file.
        readwus.f reads 3 titldum then monthly water use values with iostat.
        """
        sub_str = f"{sub_id:05d}"
        lines = []
        lines.append(f" .wus file Subbasin:{sub_id:5d}")
        lines.append("Water Use Data:")
        lines.append("Monthly water removals:")
        # 10 lines of monthly data (6 values per line, 2 lines per category)
        for _ in range(10):
            lines.append(f"{0.0:12.1f}" * 6)
        filepath = self.output_dir / f"{sub_str}0000.wus"
        with open(filepath, "w") as f:
            f.write("\n".join(lines) + "\n")

    def write_hru_file(self, sub_id: int, hru_idx: int, params: Dict[str, Any]):
        """
        Write SSSSSHHHHH.hru file matching readhru.f read sequence.

        readhru.f reads (unit 108):
        L1:  titldum (title)
        L2:  hru_fr (fraction of subbasin area)
        L3:  slsubbsn (average slope length, m)
        L4:  hru_slp (average slope steepness, m/m)
        L5:  ov_n (Manning's n for overland flow)
        L6:  lat_ttime (lateral flow travel time, days)
        L7:  lat_sed (sediment conc in lateral flow, mg/L)
        L8:  slsoil (slope length for lateral subsurface flow, m)
        L9:  canmx (max canopy storage, mm) [iostat]
        L10: esco (soil evaporation compensation factor) [iostat]
        L11: epco (plant water uptake compensation factor) [iostat]
        L12: rsdin (initial residue cover, kg/ha) [iostat]
        L13: erorgn (organic N enrichment ratio) [iostat]
        L14: erorgp (organic P enrichment ratio) [iostat]
        L15: pot_fr (pothole fraction) [iostat]
        L16: fld_fr (floodplain fraction) [iostat]
        L17: rip_fr (riparian zone fraction) [iostat]
        L18: titldum (section header) [iostat]
        L19: pot_tilemm [iostat]
        L20: pot_volxmm [iostat]
        L21: pot_volmm [iostat]
        L22: pot_nsed [iostat]
        L23: pot_no3l [iostat]
        L24: dep_imp [iostat]
        L25-27: 3x titldum [iostat]
        L28: evpot [iostat]
        L29: dis_stream [iostat]
        ... (more optional params with iostat)
        """
        filename = f"{sub_id:05d}{hru_idx:04d}.hru"
        lines = []
        # L1: titldum
        lines.append(f" .hru file Subbasin:{sub_id:5d} HRU:{hru_idx:4d} {self._timestamp}")
        # L2: hru_fr
        lines.append(f"{float(params.get('HRU_FR', 0.0001)):>16.6f}    | HRU_FR : Fraction of subbasin area")
        # L3: slsubbsn
        lines.append(f"{float(params.get('SLSUBBSN', 50)):>16.2f}    | SLSUBBSN : Avg slope length (m)")
        # L4: hru_slp
        lines.append(f"{float(params.get('HRU_SLP', 0.05)):>16.4f}    | HRU_SLP : Avg slope steepness (m/m)")
        # L5: ov_n
        lines.append(f"{float(params.get('OV_N', 0.1)):>16.4f}    | OV_N : Manning's n for overland flow")
        # L6: lat_ttime
        lines.append(f"{float(params.get('LAT_TTIME', 0)):>16.2f}    | LAT_TTIME : Lateral flow travel time (days)")
        # L7: lat_sed
        lines.append(f"{float(params.get('LAT_SED', 0)):>16.2f}    | LAT_SED : Sediment conc in lateral flow (mg/L)")
        # L8: slsoil
        lines.append(f"{float(params.get('SLSOIL', 0)):>16.2f}    | SLSOIL : Slope length for lat subsurface flow (m)")
        # L9: canmx (iostat)
        lines.append(f"{float(params.get('CANMX', 0)):>16.2f}    | CANMX : Max canopy storage (mm)")
        # L10: esco (iostat)
        lines.append(f"{float(params.get('ESCO_HRU', 0)):>16.4f}    | ESCO : Soil evap compensation factor")
        # L11: epco (iostat)
        lines.append(f"{float(params.get('EPCO_HRU', 0)):>16.4f}    | EPCO : Plant uptake compensation factor")
        # L12: rsdin (iostat)
        lines.append(f"{float(params.get('RSDIN', 0)):>16.2f}    | RSDIN : Initial residue cover (kg/ha)")
        # L13: erorgn (iostat)
        lines.append(f"{float(params.get('ERORGN', 0)):>16.2f}    | ERORGN : Organic N enrichment ratio")
        # L14: erorgp (iostat)
        lines.append(f"{float(params.get('ERORGP', 0)):>16.2f}    | ERORGP : Organic P enrichment ratio")
        # L15: pot_fr (iostat)
        lines.append(f"{float(params.get('POT_FR', 0)):>16.4f}    | POT_FR : Pothole fraction of HRU")
        # L16: fld_fr (iostat)
        lines.append(f"{float(params.get('FLD_FR', 0)):>16.4f}    | FLD_FR : Floodplain fraction")
        # L17: rip_fr (iostat)
        lines.append(f"{float(params.get('RIP_FR', 0)):>16.4f}    | RIP_FR : Riparian zone fraction")
        # L18: titldum (section header)
        lines.append("Pothole/Impounded Area:")
        # L19: pot_tilemm
        lines.append(f"{float(params.get('POT_TILEMM', 0)):>16.2f}    | POT_TILE : Tile drain flow (mm)")
        # L20: pot_volxmm
        lines.append(f"{float(params.get('POT_VOLXMM', 0)):>16.2f}    | POT_VOLX : Max volume (mm)")
        # L21: pot_volmm
        lines.append(f"{float(params.get('POT_VOLMM', 0)):>16.2f}    | POT_VOL : Initial volume (mm)")
        # L22: pot_nsed
        lines.append(f"{float(params.get('POT_NSED', 0)):>16.2f}    | POT_NSED : Normal sediment conc (mg/L)")
        # L23: pot_no3l
        lines.append(f"{float(params.get('POT_NO3L', 0)):>16.4f}    | POT_NO3L : Nitrate decay rate (1/day)")
        # L24: dep_imp
        lines.append(f"{float(params.get('DEP_IMP', 6000)):>16.2f}    | DEP_IMP : Depth to impervious layer (mm)")

        filepath = self.output_dir / filename
        with open(filepath, "w") as f:
            f.write("\n".join(lines) + "\n")

    def write_mgt_file(self, sub_id: int, hru_idx: int, params: Dict[str, Any]):
        """
        Write SSSSSHHHHH.mgt management file.

        readmgt.f reads exactly 30 lines before management operations:
        Line 1:  titldum (title)
        Line 2:  nmgt (management schedule code)
        Line 3:  titldum (section header)
        Line 4:  igro (land cover status)
        Line 5:  ncrp (crop/plant ID number)
        Line 6:  laiday (initial LAI)
        Line 7:  bio_ms (initial biomass)
        Line 8:  phu_plt (total heat units)
        Line 9:  titldum (section header)
        Line 10: biomix (biological mixing)
        Line 11: cn2 (curve number)
        Line 12: usle_p (USLE P factor)
        Line 13: bio_min (min biomass for grazing)
        Line 14: filterw (filter strip width)
        Line 15: titldum (section header)
        Line 16: iurban (urban simulation code)
        Line 17: urblu (urban land type ID)
        Line 18: titldum (section header)
        Line 19: irrsc (irrigation source code)
        Line 20: irrno (irrigation source number)
        Line 21: flowmin (minimum instream flow)
        Line 22: divmax (max daily irrigation diversion)
        Line 23: flowfr (fraction of available flow)
        Line 24: titldum (section header)
        Line 25: ddrain (depth to subsurface drain)
        Line 26: tdrain (time to drain)
        Line 27: gdrain (drain tile lag time)
        Line 28: titldum (section header)
        Line 29: titldum (was nrot, now skipped)
        Line 30: titldum (end header)
        Then: management operations in format 5200
        """
        filename = f"{sub_id:05d}{hru_idx:04d}.mgt"
        lines = []
        # L1: titldum
        lines.append(f" .mgt file Subbasin:{sub_id:5d} HRU:{hru_idx:4d} {self._timestamp}")
        # L2: nmgt
        lines.append(f"{int(params.get('NMGT', 0)):>16}    | NMGT : Management code")
        # L3: titldum
        lines.append("General Operation/Plant Growth:")
        # L4: igro
        lines.append(f"{int(params.get('IGRO', 1)):>16}    | IGRO : Land cover status")
        # L5: ncrp (plant ID number from plant.dat)
        lines.append(f"{int(params.get('NCRP', 0)):>16}    | NCRP : Land cover/plant ID")
        # L6: laiday
        lines.append(f"{float(params.get('LAIDAY', 0)):>16.2f}    | LAIDAY : Initial LAI")
        # L7: bio_ms
        lines.append(f"{float(params.get('BIO_MS', 1)):>16.2f}    | BIO_MS : Initial biomass (kg/ha)")
        # L8: phu_plt
        lines.append(f"{float(params.get('PHU_PLT', 1700)):>16.2f}    | PHU_PLT : Heat units to maturity")
        # L9: titldum
        lines.append("Hydrology/Erosion/Nutrient:")
        # L10: biomix
        lines.append(f"{float(params.get('BIOMIX', 0.2)):>16.2f}    | BIOMIX : Biological mixing efficiency")
        # L11: cn2
        lines.append(f"{float(params.get('CN2', 75)):>16.2f}    | CN2 : Initial SCS CN for moisture cond. II")
        # L12: usle_p
        lines.append(f"{float(params.get('USLE_P', 1.0)):>16.2f}    | USLE_P : USLE support practice factor")
        # L13: bio_min
        lines.append(f"{float(params.get('BIO_MIN', 0)):>16.2f}    | BIO_MIN : Min biomass for grazing (kg/ha)")
        # L14: filterw
        lines.append(f"{float(params.get('FILTERW', 0)):>16.2f}    | FILTERW : Filter strip width (m)")
        # L15: titldum
        lines.append("Urban:")
        # L16: iurban
        lines.append(f"{int(params.get('IURBAN', 0)):>16}    | IURBAN : Urban simulation code")
        # L17: urblu
        lines.append(f"{int(params.get('URBLU', 0)):>16}    | URBLU : Urban land type ID")
        # L18: titldum
        lines.append("Irrigation:")
        # L19: irrsc
        lines.append(f"{int(params.get('IRRSC', 5)):>16}    | IRRSC : Irrigation source code")
        # L20: irrno
        lines.append(f"{int(params.get('IRRNO', 0)):>16}    | IRRNO : Irrigation source number")
        # L21: flowmin
        lines.append(f"{float(params.get('FLOWMIN', 0)):>16.2f}    | FLOWMIN : Min instream flow (m3/s)")
        # L22: divmax
        lines.append(f"{float(params.get('DIVMAX', 0)):>16.2f}    | DIVMAX : Max daily irrig diversion (mm)")
        # L23: flowfr
        lines.append(f"{float(params.get('FLOWFR', 1.0)):>16.2f}    | FLOWFR : Fraction of flow available")
        # L24: titldum
        lines.append("Tile Drain:")
        # L25: ddrain
        lines.append(f"{float(params.get('DDRAIN', 0)):>16.2f}    | DDRAIN : Depth to drain (mm)")
        # L26: tdrain
        lines.append(f"{float(params.get('TDRAIN', 0)):>16.2f}    | TDRAIN : Time to drain (hr)")
        # L27: gdrain
        lines.append(f"{float(params.get('GDRAIN', 0)):>16.2f}    | GDRAIN : Drain tile lag time (hr)")
        # L28: titldum
        lines.append("Rotation:")
        # L29: titldum (was nrot, now commented out in readmgt.f)
        lines.append(f"{int(params.get('NROT', 1)):>16}    | NROT : Number of years of rotation")
        # L30: titldum
        lines.append("Scheduled Management Operations:")

        filepath = self.output_dir / filename
        with open(filepath, "w") as f:
            f.write("\n".join(lines) + "\n")

    def write_sol_file(self, sub_id: int, hru_idx: int, soil: Dict):
        """
        Write SSSSSHHHHH.sol soil file in SWAT 2012 column-based format.

        Matches readsol.f read sequence:
        - Line 1: title (a80)
        - Line 2: 12x + SNAM (a16)
        - Line 3: 24x + HYDGRP (a1)
        - Line 4: 28x + SOL_ZMX (f12.2)
        - Line 5: 51x + ANION_EXCL (f5.3)
        - Line 6: 33x + SOL_CRK (f5.3)
        - Line 7: texture title (a80)
        - Lines 8+: 27-char label + layer values (27x,25f12.2)
        """
        if soil is None:
            soil = {
                "name": "DefaultSoil", "nly": 1, "hyd_grp": "B",
                "dp_tot": 1000.0, "anion_excl": 0.5, "perc_crk": 0.5,
                "layers": [{"dp": 1000, "bd": 1.4, "awc": 0.15, "soil_k": 20.0,
                           "carbon": 1.0, "clay": 20, "silt": 40, "sand": 40,
                           "rock": 0, "alb": 0.3, "usle_k": 0.3, "ec": 0}],
            }

        filename = f"{sub_id:05d}{hru_idx:04d}.sol"
        nly = soil["nly"]
        layers = soil["layers"]

        def _sol_row(label: str, values) -> str:
            """Format a .sol row: 27-char label + f12.2 values."""
            lbl = f" {label:<26}"[:27]
            if isinstance(values, (int, float)):
                return lbl + f"{float(values):12.2f}"
            return lbl + "".join(f"{float(v):12.2f}" for v in values)

        lines = []
        # Line 1: title (a80) - read by 5500 format
        lines.append(f" .Sol file Subbasin:{sub_id:5d} HRU:{hru_idx:4d} Luse:XXXX Soil: {soil['name'][:16]}")
        # Line 2: SNAM - format (12x,a16) - 12 skip + 16 char name
        lines.append(f" Soil Name: {soil['name'][:16]:<16}")
        # Line 3: HYDGRP - format (24x,a1) - 24 skip + 1 char group
        lines.append(f" Soil Hydrologic Group: {soil['hyd_grp'].upper():>1}")
        # Line 4: SOL_ZMX - format (28x,f12.2) - 28 skip + 12 col float
        lines.append(f" Maximum rooting depth(mm) :{soil['dp_tot']:12.2f}")
        # Line 5: ANION_EXCL - format (51x,f5.3) - 51 skip + 5 col float
        #   Need exactly 51 chars before the float value
        lines.append(f" Porosity fraction from which anions are excluded: {soil['anion_excl']:5.3f}")
        # Line 6: SOL_CRK - format (33x,f5.3) - 33 skip + 5 col float
        #   Need exactly 33 chars before the float value
        lines.append(f" Crack volume potential of soil: {soil['perc_crk']:5.3f}")
        # Line 7: texture line (a80, titldum) - just a header/label
        lines.append(f" Texture : {''.join(f'{self._soil_texture(l):>12s}' for l in layers)}")

        # Lines 8+: layer property rows - format (27x,25f12.2)
        lines.append(_sol_row("SOL_Z(mm)            :", [l.get("dp", 300) for l in layers]))
        lines.append(_sol_row("SOL_BD(Mg/m**3)      :", [l.get("bd", 1.4) for l in layers]))
        lines.append(_sol_row("SOL_AWC(mm/mm)       :", [l.get("awc", 0.15) for l in layers]))
        lines.append(_sol_row("SOL_K(mm/hr)         :", [l.get("soil_k", 20) for l in layers]))
        lines.append(_sol_row("SOL_CBN(%)           :", [l.get("carbon", 1.0) for l in layers]))
        lines.append(_sol_row("CLAY(%)              :", [l.get("clay", 20) for l in layers]))
        lines.append(_sol_row("SILT(%)              :", [l.get("silt", 40) for l in layers]))
        lines.append(_sol_row("SAND(%)              :", [l.get("sand", 40) for l in layers]))
        lines.append(_sol_row("ROCK(%)              :", [l.get("rock", 0) for l in layers]))
        lines.append(_sol_row("SOL_ALB              :", layers[0].get("alb", 0.3)))
        lines.append(_sol_row("USLE_K               :", layers[0].get("usle_k", 0.3)))
        lines.append(_sol_row("SOL_EC(dS/m)         :", [l.get("ec", 0) for l in layers]))

        filepath = self.output_dir / filename
        with open(filepath, "w") as f:
            f.write("\n".join(lines) + "\n")

    @staticmethod
    def _soil_texture(layer: Dict) -> str:
        """Determine soil texture class from clay/silt/sand percentages."""
        clay = layer.get("clay", 20)
        silt = layer.get("silt", 40)
        sand = layer.get("sand", 40)
        if clay > 40:
            return "Clay"
        elif silt > 50:
            return "Silt"
        elif sand > 70:
            return "Sand"
        elif clay > 25:
            return "ClayLoam"
        elif silt > 40:
            return "SiltLoam"
        return "Loam"

    def write_gw_file(self, sub_id: int, hru_idx: int, params: Dict[str, float]):
        """
        Write SSSSSHHHHH.gw groundwater file matching readgw.f.

        readgw.f reads (unit 110):
        L1:  titldum (ONE title line)
        L2:  shallst (initial shallow aquifer storage, mm)
        L3:  deepst (initial deep aquifer storage, mm)
        L4:  delay (groundwater delay time, days)
        L5:  alpha_bf (baseflow alpha factor, 1/days)
        L6:  gwqmn (threshold depth for return flow, mm)
        L7:  gw_revap (revap coefficient)
        L8:  revapmn (threshold depth for revap, mm)
        L9:  rchrg_dp (deep aquifer percolation fraction) [iostat]
        L10: gwht (initial GW height, m) [iostat]
        L11: gw_spyld (specific yield) [iostat]
        L12: shallst_n (nitrate in shallow aquifer, mg/L) [iostat]
        L13: gwsolp (soluble P in GW, mg/L) [iostat]
        L14: hlife_ngw (half-life of nitrate in GW, days) [iostat]
        ... more optional
        """
        filename = f"{sub_id:05d}{hru_idx:04d}.gw"
        lines = []
        # L1: titldum (ONE title line only)
        lines.append(f" .gw file Subbasin:{sub_id:5d} HRU:{hru_idx:4d} {self._timestamp}")

        gw_params = [
            ("SHALLST", "Initial shallow aquifer storage (mm)", 2),
            ("DEEPST", "Initial deep aquifer storage (mm)", 2),
            ("GW_DELAY", "Groundwater delay time (days)", 2),
            ("ALPHA_BF", "Baseflow alpha factor (1/days)", 4),
            ("GWQMN", "Threshold depth for return flow (mm)", 2),
            ("GW_REVAP", "Groundwater revap coefficient", 4),
            ("REVAPMN", "Threshold depth for revap (mm)", 2),
            ("RCHRG_DP", "Deep aquifer percolation fraction", 4),
            ("GWHT", "Initial groundwater height (m)", 2),
            ("GW_SPYLD", "Specific yield of aquifer", 4),
            ("SHALLST_N", "Nitrate in shallow aquifer (mg/L)", 2),
            ("GWSOLP", "Soluble P in groundwater (mg/L)", 2),
            ("HLIFE_NGW", "Half-life of nitrate in GW (days)", 2),
            ("LAT_ORGN", "Organic N in lateral flow (mg/L)", 2),
            ("LAT_ORGP", "Organic P in lateral flow (mg/L)", 2),
            ("ALPHA_BF_D", "Alpha factor for deep aquifer (1/days)", 4),
        ]

        for name, desc, dec in gw_params:
            val = params.get(name, 0.0)
            lines.append(f"{float(val):>14.{dec}f}    | {name} : {desc}")

        filepath = self.output_dir / filename
        with open(filepath, "w") as f:
            f.write("\n".join(lines) + "\n")

    def write_chm_file(self, sub_id: int, hru_idx: int, nlayers: int = 1):
        """
        Write SSSSSHHHHH.chm soil chemistry file.

        readchm.f reads: 3 titldum, then layer data rows (27x,10f12.2)
        for sol_no3, sol_orgn, sol_solp, sol_orgp, pperco_sub.
        All reads use iostat=eof so minimal content is fine.
        """
        filename = f"{sub_id:05d}{hru_idx:04d}.chm"

        def _chm_row(label: str, values) -> str:
            lbl = f" {label:<26}"[:27]
            return lbl + "".join(f"{float(v):12.2f}" for v in values)

        zeros = [0.0] * nlayers
        lines = []
        # 3 titldum lines
        lines.append(f" .chm file Subbasin:{sub_id:5d} HRU:{hru_idx:4d}")
        lines.append(" Soil Nutrient Data")
        lines.append(" Initial concentrations: NO3, OrgN, SolP, OrgP")
        # Layer data rows (format 27x,10f12.2)
        lines.append(_chm_row("SOL_NO3(mg/kg)       :", zeros))
        lines.append(_chm_row("SOL_ORGN(mg/kg)      :", zeros))
        lines.append(_chm_row("SOL_SOLP(mg/kg)      :", zeros))
        lines.append(_chm_row("SOL_ORGP(mg/kg)      :", zeros))
        lines.append(_chm_row("PPERCO_SUB           :", zeros))
        # 3 more titldum before pesticide section
        lines.append(" Pesticide Data")
        lines.append(" Pesticide concentrations")
        lines.append(" ")

        filepath = self.output_dir / filename
        with open(filepath, "w") as f:
            f.write("\n".join(lines) + "\n")

    def write_empty_support_files(self):
        """Write minimal placeholder files that SWAT 2012 expects."""
        # slr.slr - solar radiation (empty placeholder)
        with open(self.output_dir / "slr.slr", "w") as f:
            f.write("Solar Radiation Input - Simulated\n")

        # wnd.wnd - wind (empty placeholder)
        with open(self.output_dir / "wnd.wnd", "w") as f:
            f.write("Wind Speed Input - Simulated\n")

        # hmd.hmd - humidity (empty placeholder)
        with open(self.output_dir / "hmd.hmd", "w") as f:
            f.write("Relative Humidity Input - Simulated\n")

        # lup.dat - land use update (SWAT opens this unconditionally)
        with open(self.output_dir / "lup.dat", "w") as f:
            f.write("")

        # basins.wwq - watershed water quality (readbsn.f opens unconditionally)
        # readwwq.f uses iostat=eof for all reads, so minimal file is fine
        with open(self.output_dir / "basins.wwq", "w") as f:
            f.write("Watershed Water Quality - Default\n")

        # Database files required by SWAT (opened in readfile.f/getallo.f)
        self._write_plant_dat()
        self._write_till_dat()
        self._write_pest_dat()
        self._write_fert_dat()
        self._write_urban_dat()

    def _write_plant_dat(self):
        """
        Write minimal plant.dat (crop/land use database).

        readplant.f reads 5 lines per crop entry:
        L1: ic, cname, idtype (free format: int, char*4, int)
        L2: bioe, hvstc, blaic, frgrw1, laimx1, frgrw2, laimx2, dlaic, chtmxc, rdmxc
        L3: topt, tbase, cnyldc, cpyldc, bn1, bn2, bn3, bp1c, bp2c, bp3c
        L4: wsyfc, usle_c, gsic, vpdfr, frgmax, wavpc, co2hi, bioehi, rsdcopl, alaimin
        L5: bioleaf, yrsmat, biomxtrees, extcoef, bmdieoff, rsr1c, rsr2c (format 777)

        getallo.f counts crop records by reading line 1 format.
        """
        plants = [
            # (id, name, idc, bio_e, hvsti, blai, frgrw1, laimx1, frgrw2, laimx2,
            #  dlai, chtmx, rdmx, t_opt, t_base, cnyld, cpyld,
            #  bn1, bn2, bn3, bp1, bp2, bp3,
            #  wsyf, usle_c, gsi, vpdfr, frgmax, wavp, co2hi, bioehi, rsdco_pl, alai_min)
            (1, "AGRL", 4, 20.0, 0.50, 3.0, 0.15, 0.01, 0.50, 0.95, 0.70, 0.5, 2000, 25, 10, 0.014, 0.0018, 0.044, 0.016, 0.010, 0.006, 0.003, 0.002, 0.01, 0.003, 0.005, 4.0, 0.75, 8.0, 660.0, 16.0, 0.05, 0.0),
            (2, "FRSD", 7, 15.0, 0.76, 5.0, 0.05, 0.01, 0.40, 0.95, 0.99, 10.0, 3500, 30, 0, 0.015, 0.0020, 0.040, 0.015, 0.010, 0.005, 0.003, 0.002, 0.01, 0.001, 0.002, 4.0, 0.75, 8.0, 660.0, 16.0, 0.05, 0.75),
            (3, "FRSE", 7, 15.0, 0.76, 5.0, 0.05, 0.01, 0.40, 0.95, 0.99, 10.0, 3500, 30, 0, 0.015, 0.0020, 0.040, 0.015, 0.010, 0.005, 0.003, 0.002, 0.01, 0.001, 0.002, 4.0, 0.75, 8.0, 660.0, 16.0, 0.05, 0.75),
            (4, "FRST", 7, 15.0, 0.76, 4.0, 0.05, 0.01, 0.40, 0.95, 0.99, 6.0, 3500, 25, 0, 0.015, 0.0020, 0.040, 0.015, 0.010, 0.005, 0.003, 0.002, 0.01, 0.001, 0.003, 4.0, 0.75, 8.0, 660.0, 16.0, 0.05, 0.75),
            (5, "PAST", 6, 20.0, 0.90, 4.0, 0.15, 0.01, 0.50, 0.95, 0.70, 0.5, 2000, 25, 10, 0.020, 0.0030, 0.044, 0.016, 0.010, 0.006, 0.003, 0.002, 0.01, 0.003, 0.005, 4.0, 0.75, 8.0, 660.0, 16.0, 0.05, 0.0),
            (6, "RNGE", 6, 20.0, 0.90, 2.5, 0.15, 0.01, 0.50, 0.95, 0.70, 0.5, 2000, 25, 10, 0.020, 0.0030, 0.044, 0.016, 0.010, 0.006, 0.003, 0.002, 0.01, 0.003, 0.005, 4.0, 0.75, 8.0, 660.0, 16.0, 0.05, 0.0),
            (7, "WETL", 6, 20.0, 0.90, 5.0, 0.15, 0.01, 0.50, 0.95, 0.80, 2.0, 2000, 25, 0, 0.020, 0.0030, 0.044, 0.016, 0.010, 0.006, 0.003, 0.002, 0.01, 0.001, 0.005, 4.0, 0.75, 8.0, 660.0, 16.0, 0.05, 0.0),
            (8, "WATR", 0, 0.0, 0.00, 0.0, 0.00, 0.00, 0.00, 0.00, 0.00, 0.0, 0, 0, 0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 660.0, 0.0, 0.0, 0.0),
            (9, "URBN", 0, 0.0, 0.00, 0.0, 0.00, 0.00, 0.00, 0.00, 0.00, 0.0, 0, 0, 0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 660.0, 0.0, 0.0, 0.0),
            (10, "HAY ", 6, 20.0, 0.90, 4.0, 0.15, 0.01, 0.50, 0.95, 0.70, 0.5, 2000, 25, 10, 0.020, 0.0030, 0.044, 0.016, 0.010, 0.006, 0.003, 0.002, 0.01, 0.003, 0.005, 4.0, 0.75, 8.0, 660.0, 16.0, 0.05, 0.0),
            (11, "CORN", 4, 39.0, 0.50, 6.0, 0.15, 0.05, 0.50, 0.95, 0.70, 2.5, 2500, 30, 8, 0.014, 0.0018, 0.060, 0.020, 0.010, 0.008, 0.004, 0.002, 0.01, 0.003, 0.006, 4.0, 0.75, 8.0, 660.0, 33.0, 0.05, 0.0),
            (12, "SOYB", 4, 25.0, 0.31, 3.0, 0.15, 0.01, 0.50, 0.95, 0.70, 0.9, 2000, 25, 10, 0.067, 0.0091, 0.060, 0.028, 0.015, 0.008, 0.004, 0.002, 0.01, 0.003, 0.005, 4.0, 0.75, 8.0, 660.0, 20.0, 0.05, 0.0),
        ]

        lines = []
        for p in plants:
            pid, name, idc = p[0], p[1], p[2]
            bioe, hvstc, blaic = p[3], p[4], p[5]
            frgrw1, laimx1, frgrw2, laimx2 = p[6], p[7], p[8], p[9]
            dlaic, chtmxc, rdmxc = p[10], p[11], p[12]
            topt, tbase = p[13], p[14]
            cnyldc, cpyldc = p[15], p[16]
            bn1, bn2, bn3, bp1, bp2, bp3 = p[17], p[18], p[19], p[20], p[21], p[22]
            wsyfc, usle_c, gsic = p[23], p[24], p[25]
            vpdfr, frgmax, wavpc = p[26], p[27], p[28]
            co2hi, bioehi, rsdcopl, alaimin = p[29], p[30], p[31], p[32]

            # L1: ic, cname, idtype (free format)
            lines.append(f" {pid:4d} {name:<4s} {idc:4d}")
            # L2: bioe hvstc blaic frgrw1 laimx1 frgrw2 laimx2 dlaic chtmxc rdmxc
            lines.append(
                f" {bioe:8.2f}{hvstc:8.3f}{blaic:8.2f}{frgrw1:8.3f}{laimx1:8.3f}"
                f"{frgrw2:8.3f}{laimx2:8.3f}{dlaic:8.3f}{chtmxc:8.2f}{rdmxc:8.1f}"
            )
            # L3: topt tbase cnyldc cpyldc bn1 bn2 bn3 bp1c bp2c bp3c
            lines.append(
                f" {topt:8.1f}{tbase:8.1f}{cnyldc:8.4f}{cpyldc:8.4f}"
                f"{bn1:8.4f}{bn2:8.4f}{bn3:8.4f}{bp1:8.4f}{bp2:8.4f}{bp3:8.4f}"
            )
            # L4: wsyfc usle_c gsic vpdfr frgmax wavpc co2hi bioehi rsdcopl alaimin
            lines.append(
                f" {wsyfc:8.3f}{usle_c:8.4f}{gsic:8.4f}{vpdfr:8.2f}{frgmax:8.3f}"
                f"{wavpc:8.2f}{co2hi:8.1f}{bioehi:8.2f}{rsdcopl:8.3f}{alaimin:8.3f}"
            )
            # L5: bioleaf yrsmat biomxtrees extcoef bmdieoff rsr1c rsr2c (format 777: f8.3,i5,5f8.3)
            bioleaf = 0.0
            yrsmat = 0 if idc not in (7,) else 30
            biomxtrees = 0.0 if idc not in (7,) else 1000.0
            extcoef = 0.65
            bmdieoff = 1.0 if idc in (7,) else 0.1
            rsr1c = 0.4
            rsr2c = 0.2
            lines.append(
                f"{bioleaf:8.3f}{yrsmat:5d}{biomxtrees:8.3f}{extcoef:8.3f}"
                f"{bmdieoff:8.3f}{rsr1c:8.3f}{rsr2c:8.3f}"
            )

        filepath = self.output_dir / "plant.dat"
        with open(filepath, "w") as f:
            f.write("\n".join(lines) + "\n")
        logger.info(f"Wrote {filepath} with {len(plants)} crop types")

    def _write_till_dat(self):
        """
        Write minimal till.dat (tillage database).

        getallo.f reads till.dat as:
          read(30,6300,iostat=eof) itnum  -- format i4 (tillage number)
        Loop until EOF to count records.
        """
        filepath = self.output_dir / "till.dat"
        lines = []
        # Record 1: generic tillage (ID=1, name, mixing efficiency, mixing depth)
        lines.append("   1Generic Till      0.30   200.00")
        with open(filepath, "w") as f:
            f.write("\n".join(lines) + "\n")
        logger.info(f"Wrote {filepath}")

    def _write_pest_dat(self):
        """
        Write minimal pest.dat (pesticide database).

        getallo.f reads pest.dat as:
          read(31,6200,iostat=eof) ipnum  -- format i3 (pesticide number)
        Loop until EOF to count records.
        """
        filepath = self.output_dir / "pest.dat"
        lines = []
        # Record 1: generic pesticide (ID=1)
        lines.append("  1Generic Pest         0.0    0.0    0.0    0.0    0.0    0.0")
        with open(filepath, "w") as f:
            f.write("\n".join(lines) + "\n")
        logger.info(f"Wrote {filepath}")

    def _write_fert_dat(self):
        """
        Write minimal fert.dat (fertilizer database).

        getallo.f reads fert.dat as:
          read(7,6300,iostat=eof) ifnum  -- format i4 (fertilizer number)
        Loop until EOF to count records.
        """
        filepath = self.output_dir / "fert.dat"
        lines = []
        # Record 1: generic fertilizer (ID=1)
        lines.append("   1Elem Nitrogen      0.460  0.000  0.000  0.000  0.000  0")
        with open(filepath, "w") as f:
            f.write("\n".join(lines) + "\n")
        logger.info(f"Wrote {filepath}")

    def _write_urban_dat(self):
        """
        Write minimal urban.dat (urban land type database).

        getallo.f reads urban.dat as:
          read(8,6200,iostat=eof) iunum  -- format i3 (urban type number)
          read(8,6000,iostat=eof) titldum  -- 1 line of parameters
        Loop until EOF.
        """
        filepath = self.output_dir / "urban.dat"
        lines = []
        # Record 1: generic urban (ID=1)
        lines.append("  1")
        lines.append("  0.50  0.50  0.10  0.10  0.30   50.0  0.05  0.90   15.0    0.0    0.0    0.0")
        with open(filepath, "w") as f:
            f.write("\n".join(lines) + "\n")
        logger.info(f"Wrote {filepath}")
