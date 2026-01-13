"""
F1 Replay Data Models.

Pure immutable dataclasses representing F1 data at different levels:
- TIER 1: EventInfo (lightweight event metadata)
- TIER 2: F1Weekend (EventInfo + CircuitData)
- TIER 3: SessionData (complete session data)
"""

# Base mixin
from f1_replay.models.base import F1DataMixin

# TIER 1: Event metadata (canonical source)
from f1_replay.models.event import (
    SessionInfo,
    EventInfo,
    format_date_range,
    get_location_dir,
)


# TIER 2: Weekend and circuit
from f1_replay.models.weekend import (
    MarshalSector,
    Corner,
    TrackGeometry,
    DirectionArrow,
    PitLane,
    CircuitData,
    F1Weekend,
)

# TIER 3: Session data
from f1_replay.models.session import (
    T0Info,
    SessionMetadata,
    TrackStatusEvent,
    RaceControlMessage,
    WeatherSample,
    EventsData,
    FastestLapEvent,
    PositionEntry,
    PositionSnapshot,
    ResultsData,
    SessionData,
)

# Results
from f1_replay.models.results import (
    LoadResult,
    F1DataResult,
    RaceResults,
)

__all__ = [
    # Base
    'F1DataMixin',
    # TIER 1 (EventInfo)
    'SessionInfo',
    'EventInfo',
    'format_date_range',
    'get_location_dir',
    # TIER 2
    'MarshalSector',
    'Corner',
    'TrackGeometry',
    'DirectionArrow',
    'PitLane',
    'CircuitData',
    'F1Weekend',
    # TIER 3
    'T0Info',
    'SessionMetadata',
    'TrackStatusEvent',
    'RaceControlMessage',
    'WeatherSample',
    'EventsData',
    'FastestLapEvent',
    'PositionEntry',
    'PositionSnapshot',
    'ResultsData',
    'SessionData',
    # Results
    'LoadResult',
    'F1DataResult',
    'RaceResults',
]
