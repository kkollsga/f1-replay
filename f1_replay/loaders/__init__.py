"""
F1 Replay Data Loaders.

FastF1 interfaces and data processing components for loading F1 data.

Components:
- FastF1Client: Interface to FastF1 library
- SeasonsProcessor: TIER 1 - Season catalog loading
- WeekendProcessor: TIER 2 - Weekend metadata loading
- SessionProcessor: TIER 3 - Session data loading
- TelemetryBuilder: Builds telemetry DataFrames
- OrderBuilder: Builds position tracking data
- WeatherExtractor: Extracts weather events
"""

# Core FastF1 interface
from f1_replay.loaders.core.client import FastF1Client
from f1_replay.loaders.core.mapping import USER_TO_FASTF1, FASTF1_TO_USER

# Processors
from f1_replay.loaders.seasons.processor import SeasonsProcessor
from f1_replay.loaders.weekend.processor import WeekendProcessor
from f1_replay.loaders.session.processor import SessionProcessor

# Builders and extractors
from f1_replay.loaders.session.telemetry import TelemetryBuilder
from f1_replay.loaders.session.order import OrderBuilder
from f1_replay.loaders.session.weather import WeatherExtractor

__all__ = [
    # Core
    'FastF1Client',
    'USER_TO_FASTF1',
    'FASTF1_TO_USER',
    # Processors
    'SeasonsProcessor',
    'WeekendProcessor',
    'SessionProcessor',
    # Builders
    'TelemetryBuilder',
    'OrderBuilder',
    'WeatherExtractor',
]
