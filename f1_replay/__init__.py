"""
f1-replay - Formula 1 Data Analysis and Visualization Library

A Python library for accessing, processing, and analyzing Formula 1 race data.
Provides hierarchical data loading (seasons -> weekends -> sessions) with efficient
caching and memory management.

Package Structure:
    f1_replay.models/     - Pure data types (dataclasses)
    f1_replay.wrappers/   - High-level wrapper classes (Session, RaceWeekend)
    f1_replay.loaders/    - FastF1 interfaces and data processors
    f1_replay.managers/   - Orchestration layer (DataLoader, Manager)

Quick Start:
    from f1_replay import Manager

    mgr = Manager()
    mgr.load_weekend(2025, 4)  # Load Chinese GP
    mgr.load_race()            # Load race session

    race = mgr.weekend.race
    print(race.drivers)
"""

__version__ = "0.1.0"
__author__ = "F1 Replay Development"

# High-level API (most common imports)
from f1_replay.managers import DataLoader, LoadResult, Manager
from f1_replay.wrappers import (
    RaceWeekend,
    Session,
    RaceSession, SprintSession, QualiSession, SprintQualiSession, PracticeSession,
    create_session,
)

# Config
from f1_replay.config import get_cache_dir, set_cache_dir, get_config

__all__ = [
    # Managers
    'DataLoader',
    'LoadResult',
    'Manager',
    # Wrappers
    'RaceWeekend',
    # Session classes
    'Session',
    'RaceSession',
    'SprintSession',
    'QualiSession',
    'SprintQualiSession',
    'PracticeSession',
    'create_session',
    # Config
    'get_cache_dir',
    'set_cache_dir',
    'get_config',
]
