"""
F1 Replay Wrappers.

High-level wrapper classes providing convenient access to F1 data models.

Session Hierarchy:
    Session (base)
    ├── RaceSession (position tracking during race)
    ├── SprintSession
    ├── QualiSession
    ├── SprintQualiSession
    └── PracticeSession (FP1, FP2, FP3)
"""

from f1_replay.wrappers.race_weekend import RaceWeekend
from f1_replay.wrappers.session import (
    Session,
    RaceSession,
    SprintSession,
    QualiSession,
    SprintQualiSession,
    PracticeSession,
    create_session,
)

__all__ = [
    # Weekend
    'RaceWeekend',
    # Session classes
    'Session',
    'RaceSession',
    'SprintSession',
    'QualiSession',
    'SprintQualiSession',
    'PracticeSession',
    # Factory
    'create_session',
]
