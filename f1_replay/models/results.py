"""
Result data models.

Load results and race results for data loading operations.
"""

from dataclasses import dataclass
from typing import Any, NamedTuple

from f1_replay.models.base import F1DataMixin
from f1_replay.models.session import SessionData


class LoadResult(NamedTuple):
    """
    Result of loading a session, includes both processed data and optional raw FastF1 session.

    raw_session is only populated when data is freshly processed (force_update=True or cache miss).
    When loaded from cache, raw_session is None. raw_session is NOT persisted to disk.

    Usage:
        result = loader.load_session(2025, 4, "Race", force_update=True)
        session_data = result.data  # SessionData (always present)
        raw = result.raw_session    # FastF1 session (only when freshly processed)
    """
    data: SessionData
    raw_session: Any = None  # FastF1 session object (temporary, not stored)


@dataclass
class F1DataResult(F1DataMixin):
    """Base class for mutable F1 data result objects."""
    pass


@dataclass
class RaceResults(F1DataResult):
    """
    Lightweight race results for incremental loading.

    Used by Manager.load_weekend() to efficiently get race winner
    without loading full session telemetry.

    Extensible: add more fields as needed (podium, dnfs, etc.)
    """
    winner: str  # Winner abbreviation (e.g., "VER")
    raw_session: Any = None  # FastF1 session (temporary, for further loading)

    # Placeholder for future extensions:
    # podium: List[str] = field(default_factory=list)  # Top 3
    # dnf_drivers: List[str] = field(default_factory=list)
    # pole_position: Optional[str] = None
