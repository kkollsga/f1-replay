"""
Event models - Lightweight race weekend metadata.

EventInfo is the canonical source of race weekend metadata,
used from seasons catalog through weekend loading.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional


@dataclass(frozen=True)
class SessionInfo:
    """Individual session information."""
    name: str  # "FP1", "Q", "R", etc.
    date: str  # ISO datetime "2024-05-23T13:30:00+02:00"

    def __repr__(self) -> str:
        return f"Session({self.name}: {self.date})"


@dataclass(frozen=True)
class EventInfo:
    """
    Race weekend event metadata.

    Lightweight immutable struct used across all tiers:
    - Tier 1: Built during seasons catalog fetch
    - Tier 2: Passed to RaceWeekend with circuit data
    - Tools: Used by plot_weekend for poster generation

    Attributes:
        name: Event name, e.g., "Monaco Grand Prix"
        official_name: Full sponsor name, e.g., "FORMULA 1 CRYPTO.COM MONACO GRAND PRIX 2025"
        circuit_name: Circuit location, e.g., "Monte Carlo"
        country: Country, e.g., "Monaco"
        year: Season year
        round_number: Round number in season
        start_date: First session date (ISO format)
        end_date: Race date (ISO format)
        sessions: List of SessionInfo with names and datetimes
        timezone_offset: UTC offset, e.g., "+02:00"
        format: "conventional" or "sprint_qualifying"
    """
    name: str
    official_name: str
    circuit_name: str
    country: str
    year: int
    round_number: int
    start_date: str  # ISO date "2024-05-23"
    end_date: str    # ISO date "2024-05-26"
    sessions: List[SessionInfo] = field(default_factory=list)
    timezone_offset: str = ""
    format: str = "conventional"

    @property
    def session_schedule(self) -> Dict[str, str]:
        """Dict mapping session name to datetime string."""
        return {s.name: s.date for s in self.sessions}

    def get_session_date(self, session_name: str) -> Optional[str]:
        """Get date for a specific session."""
        for s in self.sessions:
            if s.name == session_name:
                return s.date
        return None

    def __repr__(self) -> str:
        sessions = ", ".join(self.session_schedule.keys())
        return f"EventInfo({self.year} R{self.round_number}: {self.name}, sessions=[{sessions}])"


def format_date_range(event: EventInfo) -> str:
    """Format event date range like '23-26 May'."""
    from datetime import datetime
    try:
        end = datetime.strptime(event.end_date[:10], "%Y-%m-%d")
        start = datetime.strptime(event.start_date[:10], "%Y-%m-%d") if event.start_date else None

        if start and start.month == end.month:
            return f"{start.day}-{end.day} {end.strftime('%b')}"
        elif start:
            return f"{start.day} {start.strftime('%b')} - {end.day} {end.strftime('%b')}"
        else:
            return f"{end.day} {end.strftime('%b')}"
    except (ValueError, TypeError):
        return event.end_date[:10] if event.end_date else ""


def get_location_dir(event: EventInfo) -> str:
    """
    Get location directory name for an event.

    Format: "{round:02d}_{circuit_name}"
    Example: "01_Bahrain", "21_Abu_Dhabi"
    """
    location_safe = event.circuit_name.replace(' ', '_').replace('-', '_')
    return f"{event.round_number:02d}_{location_safe}"
