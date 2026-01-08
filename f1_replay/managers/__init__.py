"""
F1 Replay Managers.

Orchestration layer for loading and managing F1 data.

Components:
- DataLoader: Low-level data loading with caching
- Manager: High-level interface for browsing and loading F1 data
"""

from f1_replay.managers.dataloader import DataLoader
from f1_replay.managers.race_manager import Manager
from f1_replay.models import LoadResult

__all__ = [
    'DataLoader',
    'LoadResult',
    'Manager',
]
