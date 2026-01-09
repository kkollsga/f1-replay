"""
Session data models.

TIER 3: SessionData with telemetry, events, and results.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
import polars as pl

from f1_replay.models.base import F1DataMixin


class TrackStatusWithReport:
    """
    Wrapper around Polars DataFrame that also stores a consolidation report.

    Behaves like a DataFrame when accessed normally, but has a .report property
    showing which events were merged during interval consolidation.
    """

    def __init__(self, df: pl.DataFrame, report: Optional[dict] = None):
        """
        Initialize wrapper.

        Args:
            df: Track status DataFrame
            report: Consolidation report with merge details
        """
        self._df = df
        self._report = report or {}

    @property
    def report(self) -> dict:
        """Get consolidation report showing which events were merged."""
        return self._report

    # Make it behave like a DataFrame
    def __getattr__(self, name):
        """Delegate attribute access to underlying DataFrame."""
        return getattr(self._df, name)

    def __getitem__(self, key):
        """Delegate indexing to underlying DataFrame."""
        return self._df[key]

    def __repr__(self):
        """Show DataFrame representation."""
        return repr(self._df)

    def __str__(self):
        """Show DataFrame string representation."""
        return str(self._df)

    def __len__(self):
        """Get number of rows."""
        return len(self._df)

    def __iter__(self):
        """Iterate over DataFrame."""
        return iter(self._df)

    @property
    def df(self) -> pl.DataFrame:
        """Get underlying DataFrame directly."""
        return self._df


@dataclass(frozen=True)
class T0Info(F1DataMixin):
    """
    Time reference for session normalization.

    t0.utc is FastF1's timing zero (t0_date) - the point where session_time=0.
    This matches FastF1's SessionTime column directly (converted to seconds).

    Example:
        t0.utc = '2025-04-13T14:08:14'  # Timing zero (session_time=0)
        t0.warmup_start_offset = 3200.0 # Formation lap starts at session_time=3200s
        t0.lights_out_offset = 3335.0   # Lights out at session_time=3335s
        t0.session_duration = 7200.0    # 2 hours of telemetry

        # Convert session_time to race_time (relative to lights out):
        race_time = session_time - lights_out_offset
        # At session_time=0: race_time = -3335 (55min before lights out)
        # At session_time=3335: race_time = 0 (lights out!)
    """
    # Timing zero (t0_date) - when session_time=0 in FastF1's SessionTime
    utc: str  # ISO format UTC timestamp

    # Race timezone for local time display
    timezone: str = ""  # IANA timezone (e.g., "Asia/Shanghai", "Europe/Monaco")
    utc_offset_hours: float = 0.0  # Numeric offset (e.g., +8.0, -5.0)

    # Session timing offsets (seconds from t0)
    warmup_start_offset: Optional[float] = None  # When formation lap starts
    lights_out_offset: float = 0.0  # When lights go out (race starts)

    # Total telemetry duration in seconds (from first to last data point)
    session_duration: float = 0.0


@dataclass(frozen=True)
class SessionMetadata(F1DataMixin):
    """Session-specific metadata."""
    session_type: str  # "R", "Q", "FP1", "FP2", "FP3", "S"
    year: int
    round_number: int
    event_name: str
    drivers: List[str]  # ["VER", "HAM", "LEC", ...]
    driver_numbers: Dict[str, int]  # {"VER": 1, "HAM": 44, ...}
    driver_names: Dict[str, str]  # {"VER": "Max Verstappen", "HAM": "Lewis Hamilton", ...}
    driver_teams: Dict[str, str]  # {"VER": "Red Bull Racing", ...}
    driver_colors: Dict[str, str]  # {"VER": "#0600EF", "HAM": "#00D2BE", ...}
    team_colors: Dict[str, str]  # {"Red Bull Racing": "#0600EF", ...}
    track_length: float  # From circuit
    total_laps: int  # Laps in this session
    dnf_drivers: List[str] = field(default_factory=list)  # Drivers who DNF'd (status="Retired")
    t0: Optional[T0Info] = None  # Time reference for normalization (single source of truth)
    start_time_local: Optional[str] = None  # "17:00:00"


@dataclass(frozen=True)
class TrackStatusEvent(F1DataMixin):
    """
    Track status/flag event (unified from track_status + race_control_messages).

    Represents both global track states (SC, VSC, Red) and specific flags (Yellow sector, Blue for driver).
    Can represent either a discrete event (end_time=None) or an interval (end_time set).
    """
    session_time: float  # Seconds since session start (t0) - interval start time
    status: str  # "AllClear", "Yellow", "SafetyCar", "VSC", "VSCEnding", "Red"
    message: str = ""
    scope: str = "Track"  # "Track", "Sector", "Driver"
    sector: Optional[int] = None  # Sector number for sector flags (None if not sector-specific)
    driver_num: str = ""  # Driver number for blue flags
    end_time: Optional[float] = None  # Interval end time (None = discrete event or ongoing)


@dataclass(frozen=True)
class RaceControlMessage(F1DataMixin):
    """Race control message."""
    message: str
    time: float = 0.0  # Original time value from FastF1
    session_time: float = 0.0  # Normalized: seconds since session start (t0)


@dataclass(frozen=True)
class WeatherSample(F1DataMixin):
    """Weather sample at a point in time."""
    temperature: float  # °C
    humidity: float  # 0-100
    wind_speed: float  # m/s
    wind_direction: Optional[str] = None  # "N", "NE", etc.
    track_temperature: float = 0.0  # °C
    rainfall: bool = False
    time: float = 0.0  # Original time value from FastF1
    session_time: float = 0.0  # Normalized: seconds since session start (t0)


@dataclass(frozen=True)
class EventsData(F1DataMixin):
    """All events during session (stored as Polars DataFrames for efficiency)."""
    # Unified track status: merges session.track_status + race_control_messages[Category='Flag']
    # Columns: session_time, status, message, flag_type, scope, sector, driver_num, lap, raw_time, end_time
    # Includes synthetic events (SessionStart→WarmUp, LightsOut) and rain events (consolidated)
    # Can access .report property for consolidation details
    track_status: TrackStatusWithReport = field(default_factory=lambda: TrackStatusWithReport(pl.DataFrame()))
    race_control: pl.DataFrame = field(default_factory=lambda: pl.DataFrame())  # Columns: message, time, session_time


@dataclass(frozen=True)
class FastestLapEvent(F1DataMixin):
    """Fastest lap record."""
    lap: int
    driver: str
    time: float  # seconds (lap duration)
    lap_time_ms: int
    session_time: float = 0.0  # Session time when this lap was completed (seconds since t0)


@dataclass(frozen=True)
class PositionEntry(F1DataMixin):
    """Driver position in standings."""
    position: int
    driver: str
    gap: float  # seconds to leader


@dataclass(frozen=True)
class PositionSnapshot(F1DataMixin):
    """Standings at a moment in time."""
    time: float  # Session seconds
    lap: Optional[int] = None
    standings: List[PositionEntry] = field(default_factory=list)


@dataclass(frozen=True)
class ResultsData(F1DataMixin):
    """Race results and standings."""
    fastest_laps: List[FastestLapEvent] = field(default_factory=list)
    position_history: List[PositionSnapshot] = field(default_factory=list)


@dataclass(frozen=True)
class SessionData(F1DataMixin):
    """Complete immutable data for one session."""
    metadata: SessionMetadata
    telemetry: Dict[str, pl.DataFrame] = field(default_factory=dict)  # driver_code -> telemetry (includes position column)
    events: EventsData = field(default_factory=EventsData)
    results: ResultsData = field(default_factory=ResultsData)

    # Convenience properties for easier access to results
    @property
    def fastest_laps(self) -> List[FastestLapEvent]:
        """Get fastest lap progression (chronological record of fastest lap changes)."""
        return self.results.fastest_laps

    @property
    def position_history(self) -> List[PositionSnapshot]:
        """Get position snapshots (standings at moments in time)."""
        return self.results.position_history

    @property
    def t0(self) -> Optional[T0Info]:
        """Get time reference info for session normalization."""
        return self.metadata.t0
