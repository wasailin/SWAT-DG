"""
SWAT Configuration management.

Handles reading and writing of file.cio and other configuration files.
"""

from pathlib import Path
from typing import Dict, Any, Optional, Tuple
from dataclasses import dataclass
from datetime import date, timedelta


@dataclass
class SimulationPeriod:
    """Simulation time period settings."""
    start_year: int
    start_day: int  # Julian day
    end_year: int
    end_day: int  # Julian day
    warmup_years: int = 0

    @property
    def start_date(self) -> date:
        """Convert to Python date object."""
        return date(self.start_year, 1, 1) + timedelta(days=self.start_day - 1)

    @property
    def end_date(self) -> date:
        """Convert to Python date object."""
        # IDAL=0 in SWAT means "end of last year" (Dec 31)
        if self.end_day == 0:
            return date(self.end_year, 12, 31)
        return date(self.end_year, 1, 1) + timedelta(days=self.end_day - 1)


@dataclass
class OutputSettings:
    """Output file configuration."""
    daily: bool = True
    monthly: bool = True
    yearly: bool = True
    print_code: int = 1  # SWAT IPRINT: 0=monthly, 1=daily, 2=yearly


class SWATConfig:
    """
    SWAT configuration manager.

    Reads and manages settings from file.cio and related configuration files.

    Example:
        >>> config = SWATConfig("C:/my_watershed")
        >>> print(f"Simulation period: {config.period.start_year}-{config.period.end_year}")
        >>> config.period.start_year = 2010
        >>> config.save()
    """

    def __init__(self, project_dir: Path):
        """
        Initialize configuration from project directory.

        Args:
            project_dir: Path to SWAT project directory
        """
        self.project_dir = Path(project_dir)
        self.cio_path = self.project_dir / "file.cio"

        if not self.cio_path.exists():
            raise FileNotFoundError(f"file.cio not found: {self.cio_path}")

        # Load configuration
        self._raw_cio: Dict[str, Any] = {}
        self._load_cio()

        # Parse into structured objects
        self.period = self._parse_period()
        self.output = self._parse_output()

    def _load_cio(self) -> None:
        """Load and parse file.cio."""
        with open(self.cio_path, 'r') as f:
            lines = f.readlines()

        self._cio_lines = lines
        self._raw_cio = self._parse_cio_lines(lines)

    def _find_line_by_keyword(self, lines: list, keyword: str) -> Optional[int]:
        """Find line index containing keyword (case-insensitive).

        Searches after '|' first (standard format), then anywhere in the
        line as a fallback (handles file.cio variants without pipe delimiters).
        """
        kw = keyword.upper()
        # Pass 1: look after '|' (standard SWAT2012 file.cio format)
        for i, line in enumerate(lines):
            if "|" in line and kw in line.upper().split("|", 1)[1]:
                return i
        # Pass 2: look anywhere on the line (some file.cio lack '|')
        for i, line in enumerate(lines):
            # Only match if keyword appears as a separate token (not inside
            # another word) and line starts with a number.
            parts = line.upper().split()
            if len(parts) >= 2 and kw in parts:
                # Ensure the line starts with a numeric value
                try:
                    float(parts[0])
                    return i
                except ValueError:
                    continue
        return None

    def _parse_cio_lines(self, lines: list) -> Dict[str, Any]:
        """
        Parse file.cio format.

        Uses keyword search (e.g. ``| IPRINT``) so the parser works
        regardless of the exact line positions in the user's file.cio.
        Falls back to fixed positions for the early parameters that
        rarely move (NBYR, IYR, IDAF, IDAL).
        """
        values = {}
        self._iprint_line = None
        self._nyskip_line = None

        try:
            # These four are always at fixed positions in SWAT2012
            if len(lines) > 7:
                values['nbyr'] = self._parse_value(lines[7])
            if len(lines) > 8:
                values['iyr'] = self._parse_value(lines[8])
            if len(lines) > 9:
                values['idaf'] = self._parse_value(lines[9])
            if len(lines) > 10:
                values['idal'] = self._parse_value(lines[10])

            # IPRINT: search by keyword first, fall back to index 58
            iprint_idx = self._find_line_by_keyword(lines, "IPRINT")
            if iprint_idx is not None:
                values['iprint'] = self._parse_value(lines[iprint_idx])
                self._iprint_line = iprint_idx
            elif len(lines) > 58:
                values['iprint'] = self._parse_value(lines[58])
                self._iprint_line = 58
            else:
                self._iprint_line = None

            # NYSKIP: search by keyword first, fall back to index 59
            nyskip_idx = self._find_line_by_keyword(lines, "NYSKIP")
            if nyskip_idx is not None:
                values['nyskip'] = self._parse_value(lines[nyskip_idx])
                self._nyskip_line = nyskip_idx
            elif len(lines) > 59:
                values['nyskip'] = self._parse_value(lines[59])
                self._nyskip_line = 59
            else:
                self._nyskip_line = None

        except (ValueError, IndexError) as e:
            print(f"Warning: Error parsing file.cio: {e}")

        return values

    def _parse_value(self, line: str) -> Any:
        """Extract numeric value from a file.cio line."""
        # file.cio format: first field is the value, rest is comment
        parts = line.split()
        if parts:
            try:
                # Try integer first
                return int(parts[0])
            except ValueError:
                try:
                    # Then float
                    return float(parts[0])
                except ValueError:
                    return parts[0]
        return None

    def _parse_period(self) -> SimulationPeriod:
        """Parse simulation period from loaded config."""
        nbyr = int(self._raw_cio.get('nbyr', 1))
        iyr = int(self._raw_cio.get('iyr', 2000))
        idaf = int(self._raw_cio.get('idaf', 1))
        idal = int(self._raw_cio.get('idal', 365))
        nyskip = int(self._raw_cio.get('nyskip', 0))

        return SimulationPeriod(
            start_year=iyr,
            start_day=idaf,
            end_year=iyr + nbyr - 1,
            end_day=idal,
            warmup_years=nyskip,
        )

    def _parse_output(self) -> OutputSettings:
        """Parse output settings from loaded config."""
        iprint = self._raw_cio.get('iprint', 1)

        return OutputSettings(
            daily=(iprint == 1),
            monthly=(iprint == 0),
            yearly=(iprint == 2),
            print_code=iprint,
        )

    def get_subbasin_count(self) -> int:
        """Get number of subbasins in the project."""
        # Count .sub files
        sub_files = list(self.project_dir.glob("*.sub"))
        return len(sub_files)

    def get_hru_count(self) -> int:
        """Get number of HRUs in the project."""
        # Count .hru files
        hru_files = list(self.project_dir.glob("*.hru"))
        return len(hru_files)

    def get_reach_count(self) -> int:
        """Get number of reaches in the project."""
        # Count .rte files
        rte_files = list(self.project_dir.glob("*.rte"))
        return len(rte_files)

    def get_weather_data_period(self) -> Optional[Tuple[int, int]]:
        """Detect available weather data period from .pcp files.

        Reads the first and last data lines of the first .pcp file to
        determine the year range of available precipitation data.
        SWAT2012 .pcp format: 4 header lines, then ``i4,i3,values``
        (year in cols 0-3, Julian day in cols 4-6).

        Returns
        -------
        tuple of (start_year, end_year) or None if no .pcp files found.
        """
        pcp_files = sorted(self.project_dir.glob("*.pcp"))
        if not pcp_files:
            return None

        pcp_path = pcp_files[0]
        try:
            with open(pcp_path, "r") as f:
                # Skip 4 header lines (3 titldum + 1 elevation)
                for _ in range(4):
                    f.readline()

                first_line = f.readline()
                if not first_line or len(first_line) < 7:
                    return None
                start_year = int(first_line[:4])

                # Read to the last data line
                last_line = first_line
                for line in f:
                    if line.strip():
                        last_line = line
                end_year = int(last_line[:4])

            return (start_year, end_year)
        except (ValueError, IOError, OSError):
            return None

    def save(self) -> None:
        """Save configuration changes back to file.cio."""
        # Update lines with current values
        lines = self._cio_lines.copy()

        # Update specific lines (fixed position)
        if len(lines) > 7:
            nbyr = self.period.end_year - self.period.start_year + 1
            lines[7] = f"{nbyr:16d}    | NBYR : Number of years simulated\n"

        if len(lines) > 8:
            lines[8] = f"{self.period.start_year:16d}    | IYR : Beginning year of simulation\n"

        if len(lines) > 9:
            lines[9] = f"{self.period.start_day:16d}    | IDAF : Beginning julian day\n"

        if len(lines) > 10:
            lines[10] = f"{self.period.end_day:16d}    | IDAL : Ending julian day\n"

        # IPRINT and NYSKIP: use keyword-detected positions
        iprint_idx = getattr(self, "_iprint_line", None)
        if iprint_idx is not None and len(lines) > iprint_idx:
            lines[iprint_idx] = f"{self.output.print_code:16d}    | IPRINT : Output print code\n"

        nyskip_idx = getattr(self, "_nyskip_line", None)
        if nyskip_idx is not None and len(lines) > nyskip_idx:
            lines[nyskip_idx] = f"{self.period.warmup_years:16d}    | NYSKIP : Number of years to skip\n"

        # Write back
        with open(self.cio_path, 'w') as f:
            f.writelines(lines)

        print(f"Configuration saved to {self.cio_path} (IPRINT={self.output.print_code} at line {iprint_idx})")

    def __repr__(self) -> str:
        return (
            f"SWATConfig(\n"
            f"  period: {self.period.start_year}-{self.period.end_year}\n"
            f"  subbasins: {self.get_subbasin_count()}\n"
            f"  HRUs: {self.get_hru_count()}\n"
            f")"
        )
