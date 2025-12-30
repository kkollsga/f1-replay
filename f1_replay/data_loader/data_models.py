"""
f1-replay Data Models

Immutable dataclasses for representing F1 data at different levels:
- TIER 1: F1Seasons (season catalog)
- TIER 2: F1Weekend (race weekend with circuit info)
- TIER 3: SessionData (complete session data)
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
import numpy as np
import polars as pl

# ============================================================================
# TIER 1: Season Catalog (F1Seasons)
# ============================================================================

@dataclass(frozen=True)
class RoundInfo:
    """Basic info about a single race weekend."""
    round_number: int
    event_name: str  # "Bahrain Grand Prix"
    location: str    # "Sakhir"
    country: str     # "Bahrain"
    circuit_name: str  # "Bahrain International Circuit"
    date: str        # "2024-03-02"
    available_sessions: List[str]  # ["FP1", "FP2", "FP3", "Q", "R"]


@dataclass(frozen=True)
class F1Year:
    """Data for a single F1 season."""
    year: int
    total_rounds: int
    rounds: List[RoundInfo]


@dataclass(frozen=True)
class F1Seasons:
    """Complete immutable catalog of all F1 seasons."""
    years: Dict[int, F1Year]
    last_updated: str  # ISO timestamp


# ============================================================================
# TIER 2: Race Weekend (F1Weekend)
# ============================================================================

@dataclass(frozen=True)
class TrackSegment:
    """A segment of track (marshal sector, DRS zone, etc.)."""
    name: str  # "Sector 1", "DRS Zone 1"
    start_distance: float  # meters
    end_distance: float    # meters
    segment_type: str  # "sector", "drs_zone"
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TrackGeometry:
    """Track or pit lane coordinates."""
    x: np.ndarray  # float32 array of X coordinates
    y: np.ndarray  # float32 array of Y coordinates
    distance: Optional[np.ndarray] = None  # float32 cumulative distance
    lap_distance: float = 0.0  # Total distance (meters)


@dataclass(frozen=True)
class CircuitData:
    """Complete circuit information."""
    track: TrackGeometry  # Track outline
    pit_lane: Optional[TrackGeometry] = None  # Pit lane outline
    track_segments: List[TrackSegment] = field(default_factory=list)  # Marshal sectors
    circuit_length: float = 0.0  # Total track length (meters)
    corners: int = 0  # Number of corners
    rotation: float = 0.0  # Track rotation in degrees (from FastF1)
    metadata: Dict[str, Any] = field(default_factory=dict)  # DRS zones, etc.


@dataclass(frozen=True)
class WeekendMetadata:
    """Race weekend metadata."""
    year: int
    round_number: int
    event_name: str  # "Abu Dhabi Grand Prix"
    location: str    # "Yas Island"
    country: str     # "United Arab Emirates"
    circuit_name: str  # "Yas Marina Circuit"
    timezone: str    # "UTC+4"
    event_date: str  # ISO date "2024-12-08"
    session_schedule: Dict[str, str] = field(default_factory=dict)  # Session times
    available_sessions: List[str] = field(default_factory=list)  # ["FP1", ..., "R"]


@dataclass(frozen=True)
class F1Weekend:
    """Complete immutable race weekend: metadata + circuit geometry."""
    metadata: WeekendMetadata
    circuit: CircuitData


# ============================================================================
# TIER 3: Session Data (SessionData)
# ============================================================================

@dataclass(frozen=True)
class SessionMetadata:
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
    t0_date_utc: Optional[str] = None  # Session start time UTC
    start_time_local: Optional[str] = None  # "17:00:00"


@dataclass(frozen=True)
class TrackStatusEvent:
    """Track status change event."""
    status: str  # "AllClear", "Yellow", "SafetyCar", "VirtualSafetyCar", "Red"
    message: str
    time: float = 0.0  # Original time value from FastF1
    session_time: float = 0.0  # Normalized: seconds since session start (t0)


@dataclass(frozen=True)
class RaceControlMessage:
    """Race control message."""
    message: str
    time: float = 0.0  # Original time value from FastF1
    session_time: float = 0.0  # Normalized: seconds since session start (t0)


@dataclass(frozen=True)
class WeatherSample:
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
class EventsData:
    """All events during session (stored as Polars DataFrames for efficiency)."""
    track_status: pl.DataFrame = field(default_factory=lambda: pl.DataFrame())  # Columns: status, message, time, session_time
    race_control: pl.DataFrame = field(default_factory=lambda: pl.DataFrame())  # Columns: message, time, session_time
    weather: pl.DataFrame = field(default_factory=lambda: pl.DataFrame())  # Columns: temperature, humidity, wind_speed, wind_direction, track_temperature, rainfall, time, session_time


@dataclass(frozen=True)
class FastestLapEvent:
    """Fastest lap record."""
    lap: int
    driver: str
    time: float  # seconds (lap duration)
    lap_time_ms: int
    session_time: float = 0.0  # Session time when this lap was completed (seconds since t0)


@dataclass(frozen=True)
class PositionEntry:
    """Driver position in standings."""
    position: int
    driver: str
    gap: float  # seconds to leader


@dataclass(frozen=True)
class PositionSnapshot:
    """Standings at a moment in time."""
    time: float  # Session seconds
    lap: Optional[int] = None
    standings: List[PositionEntry] = field(default_factory=list)


@dataclass(frozen=True)
class ResultsData:
    """Race results and standings."""
    fastest_laps: List[FastestLapEvent] = field(default_factory=list)
    position_history: List[PositionSnapshot] = field(default_factory=list)


@dataclass(frozen=True)
class SessionData:
    """Complete immutable data for one session."""
    metadata: SessionMetadata
    telemetry: Dict[str, pl.DataFrame] = field(default_factory=dict)  # driver_code -> telemetry
    events: EventsData = field(default_factory=EventsData)
    results: ResultsData = field(default_factory=ResultsData)
    order: pl.DataFrame = field(default_factory=lambda: pl.DataFrame())  # Columns: session_time, position, driver (only rows where order changed)
    rain_events: pl.DataFrame = field(default_factory=lambda: pl.DataFrame())  # Columns: start_time, end_time, duration

    # Convenience properties for easier access to results
    @property
    def fastest_laps(self) -> List[FastestLapEvent]:
        """Get fastest lap progression (chronological record of fastest lap changes)."""
        return self.results.fastest_laps

    @property
    def position_history(self) -> List[PositionSnapshot]:
        """Get position snapshots (standings at moments in time)."""
        return self.results.position_history
