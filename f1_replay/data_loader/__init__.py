"""
Data Loader Module - F1 Data Access and Caching

Provides hierarchical 3-tier data loading:
- TIER 1: F1Seasons (seasons catalog)
- TIER 2: F1Weekend (race weekend data)
- TIER 3: SessionData (session telemetry and events)
"""

from f1_replay.data_loader.dataloader import DataLoader
from f1_replay.data_loader.data_models import (
    F1Seasons, F1Year, RoundInfo,
    F1Weekend, WeekendMetadata, CircuitData, TrackGeometry, TrackSegment,
    SessionData, SessionMetadata, EventsData, ResultsData,
)
from f1_replay.data_loader.session_mapping import to_fastf1_code, to_user_friendly
from f1_replay.data_loader.telemetry_consolidator import TelemetryConsolidator
from f1_replay.data_loader.time_normalizer import TimeNormalizer, align_to_session_start
from f1_replay.data_loader import visualization_utils

__all__ = [
    # Main loader
    'DataLoader',
    # Session mapping
    'to_fastf1_code',
    'to_user_friendly',
    # Telemetry utilities
    'TelemetryConsolidator',
    # Time utilities
    'TimeNormalizer',
    'align_to_session_start',
    # Visualization
    'visualization_utils',
    # TIER 1
    'F1Seasons',
    'F1Year',
    'RoundInfo',
    # TIER 2
    'F1Weekend',
    'WeekendMetadata',
    'CircuitData',
    'TrackGeometry',
    'TrackSegment',
    # TIER 3
    'SessionData',
    'SessionMetadata',
    'EventsData',
    'ResultsData',
]
