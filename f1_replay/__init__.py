"""
f1-replay - Formula 1 Data Analysis and Visualization Library

A Python library for accessing, processing, and analyzing Formula 1 race data.
Provides hierarchical data loading (seasons → weekends → sessions) with efficient
caching and memory management.
"""

__version__ = "0.1.0"
__author__ = "F1 Replay Development"

from f1_replay.data_loader import DataLoader
from f1_replay.manager import Manager
from f1_replay.race_weekend import RaceWeekend
from f1_replay.session import Session
from f1_replay.config import get_cache_dir, set_cache_dir, get_config

__all__ = [
    'DataLoader',
    'Manager',
    'RaceWeekend',
    'Session',
    'get_cache_dir',
    'set_cache_dir',
    'get_config',
]
