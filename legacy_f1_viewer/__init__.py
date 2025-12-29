"""
F1 Viewer - F1 Race Telemetry and Visualization Library

A Python library for fetching, processing, and visualizing Formula 1 race telemetry data.

Architecture:
- DataLoader: Main facade for loading race data
- RaceManager: High-level API for the Flask app
- Race: Clean API for accessing race data (wraps SessionDataset)
- SessionDataset: Immutable, cached session data (telemetry, track, weather, etc.)
- F1Catalog: Complete catalog of all F1 seasons

Note: Only data_loader.py imports fastf1. All other modules are framework-agnostic.
"""

from .race import Race
from .manager import RaceManager
from .data_loader import (
    DataLoader,
    F1Catalog,
    SeasonInfo,
    RaceInfo,
    RaceWeekendData,
    SessionDataset,
    RaceDataLoader,
)

__version__ = "0.2.0"
__all__ = [
    # Main API
    "Race",
    "RaceManager",
    "DataLoader",
    # Data classes
    "SessionDataset",
    "RaceWeekendData",
    "F1Catalog",
    "SeasonInfo",
    "RaceInfo",
    # Advanced
    "RaceDataLoader",
]
