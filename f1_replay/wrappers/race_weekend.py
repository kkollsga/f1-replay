"""
RaceWeekend - Race weekend data with circuit geometry.

Wraps F1Weekend dataclass for user-friendly access.
Manages session loading/unloading for memory efficiency.
"""

from typing import TYPE_CHECKING, Dict, List, Optional, Callable
import numpy as np

from f1_replay.models import F1Weekend, EventInfo, CircuitData, TrackGeometry, TrackSegment, PitLane, DirectionArrow

if TYPE_CHECKING:
    from f1_replay.wrappers.session import Session


class SessionNotLoaded:
    """Placeholder that raises helpful error when accessed."""

    def __init__(self, session_name: str, weekend: "RaceWeekend"):
        self._session_name = session_name
        self._weekend = weekend

    def __getattr__(self, name: str):
        raise AttributeError(
            f"{self._session_name} session not loaded. "
            f"Use manager.load_session(session_type='{self._session_name[0].upper()}') or "
            f"weekend.load_session('{self._session_name}')"
        )

    def __repr__(self) -> str:
        return f"<{self._session_name} not loaded>"

    def __bool__(self) -> bool:
        return False


class RaceWeekend:
    """
    Race weekend with circuit geometry and loaded sessions.

    Wraps F1Weekend (EventInfo + CircuitData) internally.
    Manages session loading/unloading for memory efficiency.

    Attributes:
        year: Season year
        round_number: Race round number
        event_name: e.g., 'Monaco Grand Prix'
        location: e.g., 'Monte Carlo'
        country: e.g., 'Monaco'
        circuit_name: e.g., 'Circuit de Monaco'
        timezone: e.g., 'Europe/Monaco'
        event_date: ISO date string
        event_start: First session date
        available_sessions: ['FP1', 'FP2', 'FP3', 'Q', 'R']
        circuit: CircuitData (track, pit_lane, length, corners, etc.)
    """

    def __init__(
        self,
        data: F1Weekend,
        display_timezone: Optional[str] = None,
        session_loader: Optional[Callable[[str], Optional["Session"]]] = None
    ):
        """
        Initialize from F1Weekend dataclass.

        Args:
            data: F1Weekend dataclass (EventInfo + CircuitData)
            display_timezone: Timezone for display
            session_loader: Optional callback to load sessions (year, round, type) -> Session
        """
        self._data = data
        self._sessions: Dict[str, "Session"] = {}
        self._display_timezone = display_timezone
        self._session_loader = session_loader

    # =========================================================================
    # Event Properties (from EventInfo)
    # =========================================================================

    @property
    def event(self) -> EventInfo:
        """Access underlying EventInfo."""
        return self._data.event

    @property
    def year(self) -> int:
        return self._data.event.year

    @property
    def round_number(self) -> int:
        return self._data.event.round_number

    @property
    def event_name(self) -> str:
        return self._data.event.name

    @property
    def location(self) -> str:
        return self._data.event.location

    @property
    def country(self) -> str:
        return self._data.event.country

    @property
    def circuit_name(self) -> str:
        return self._data.event.circuit_name

    @property
    def timezone(self) -> str:
        return self._data.event.timezone

    @property
    def event_date(self) -> str:
        return self._data.event.end_date

    @property
    def event_start(self) -> str:
        return self._data.event.start_date

    @property
    def available_sessions(self) -> List[str]:
        return self._data.event.available_sessions

    @property
    def session_schedule(self) -> Dict[str, str]:
        return self._data.event.session_schedule

    # =========================================================================
    # Circuit Properties (from CircuitData)
    # =========================================================================

    @property
    def circuit(self) -> CircuitData:
        """Access circuit data (track, pit_lane, corners, rotation, etc.)."""
        return self._data.circuit

    @property
    def track(self) -> TrackGeometry:
        """Direct access to track geometry."""
        return self._data.circuit.track

    @property
    def pit_lane(self) -> Optional[PitLane]:
        """Direct access to pit lane."""
        return self._data.circuit.pit_lane

    @property
    def circuit_length(self) -> float:
        """Circuit length in meters."""
        return self._data.circuit.circuit_length

    @property
    def corners(self) -> int:
        """Number of corners."""
        return self._data.circuit.corners

    @property
    def rotation(self) -> float:
        """Track rotation in degrees."""
        return self._data.circuit.rotation

    @property
    def track_segments(self) -> List[TrackSegment]:
        """Track segments (sectors, DRS zones)."""
        return self._data.circuit.track_segments

    @property
    def direction_arrow(self) -> Optional[DirectionArrow]:
        """Direction arrow at start/finish (opposite pitlane)."""
        return self._data.circuit.direction_arrow

    # =========================================================================
    # Query Methods
    # =========================================================================

    def get_track_coords(self) -> Dict[str, list]:
        """Get track coordinates as JSON-friendly lists."""
        track = self._data.circuit.track
        result = {
            'x': track.x.tolist() if isinstance(track.x, np.ndarray) else track.x,
            'y': track.y.tolist() if isinstance(track.y, np.ndarray) else track.y,
            'lap_distance': float(track.lap_distance)
        }
        if track.distance is not None:
            result['distance'] = (
                track.distance.tolist()
                if isinstance(track.distance, np.ndarray)
                else track.distance
            )
        return result

    def get_pit_lane_coords(self) -> Optional[Dict[str, list]]:
        """Get pit lane coordinates as JSON-friendly lists."""
        pit = self._data.circuit.pit_lane
        if pit is None:
            return None
        return {
            'x': pit.x.tolist() if isinstance(pit.x, np.ndarray) else pit.x,
            'y': pit.y.tolist() if isinstance(pit.y, np.ndarray) else pit.y,
            'lap_distance': float(pit.length)
        }

    def get_sectors(self) -> List[TrackSegment]:
        """Get marshal sectors."""
        return [seg for seg in self._data.circuit.track_segments if seg.segment_type == 'sector']

    def get_drs_zones(self) -> List[TrackSegment]:
        """Get DRS zones."""
        return [seg for seg in self._data.circuit.track_segments if seg.segment_type == 'drs_zone']

    # =========================================================================
    # Session Management (load/unload for memory efficiency)
    # =========================================================================

    def set_session(self, session_type: str, session: "Session") -> None:
        """Store a loaded session."""
        self._sessions[session_type] = session

    def unload_session(self, session_type: str) -> bool:
        """
        Unload a session to free memory.

        Args:
            session_type: Session type ('R', 'Q', 'FP1', etc.)

        Returns:
            True if session was unloaded, False if not loaded
        """
        if session_type in self._sessions:
            del self._sessions[session_type]
            return True
        return False

    def unload_all_sessions(self) -> int:
        """
        Unload all sessions to free memory.

        Returns:
            Number of sessions unloaded
        """
        count = len(self._sessions)
        self._sessions.clear()
        return count

    def clear_sessions(self) -> None:
        """Clear all loaded sessions. Alias for unload_all_sessions()."""
        self._sessions.clear()

    def is_session_loaded(self, session_type: str) -> bool:
        """Check if a session is currently loaded."""
        return session_type in self._sessions

    @property
    def loaded_sessions(self) -> List[str]:
        """List of loaded session types."""
        return list(self._sessions.keys())

    # Session type mapping (accepts acronyms, shortnames, full names)
    SESSION_ALIASES = {
        # Race
        'race': 'R', 'r': 'R',
        # Qualifying
        'qualifying': 'Q', 'quali': 'Q', 'q': 'Q',
        # Sprint
        'sprint': 'S', 's': 'S',
        # Sprint Qualifying
        'sq': 'SQ', 'sprint qualifying': 'SQ', 'sprint_qualifying': 'SQ',
        'sprintquali': 'SQ', 'sprint shootout': 'SQ',
        # Practice
        'fp1': 'FP1', 'practice 1': 'FP1', 'practice1': 'FP1',
        'fp2': 'FP2', 'practice 2': 'FP2', 'practice2': 'FP2',
        'fp3': 'FP3', 'practice 3': 'FP3', 'practice3': 'FP3',
    }

    # Convert full names to shortnames for display
    SESSION_SHORTNAMES = {
        'Practice 1': 'FP1', 'Practice 2': 'FP2', 'Practice 3': 'FP3',
        'Qualifying': 'Q', 'Race': 'R',
        'Sprint': 'S', 'Sprint Qualifying': 'SQ', 'Sprint Shootout': 'SQ',
    }

    def _normalize_session_type(self, session_type: str) -> str:
        """Normalize session type to standard code."""
        return self.SESSION_ALIASES.get(session_type.lower(), session_type.upper())

    def load_session(self, session_type: str, force_update: bool = False) -> Optional["Session"]:
        """
        Load a session into this weekend.

        Args:
            session_type: Session type ('race', 'R', 'qualifying', 'Q', 'FP1', etc.)
            force_update: Force reload from FastF1

        Returns:
            Loaded Session or None if loader not available
        """
        code = self._normalize_session_type(session_type)

        # Return cached if already loaded and not forcing update
        if code in self._sessions and not force_update:
            return self._sessions[code]

        if self._session_loader is None:
            raise RuntimeError(
                "Session loader not configured. Use manager.load_session() instead, "
                "or initialize RaceWeekend with a session_loader callback."
            )

        session = self._session_loader(code, force_update)
        if session:
            self._sessions[code] = session
        return session

    @property
    def race(self) -> "Session":
        """Race session (raises helpful error if not loaded)."""
        return self._sessions.get("R") or SessionNotLoaded("Race", self)

    @property
    def qualifying(self) -> "Session":
        """Qualifying session (raises helpful error if not loaded)."""
        return self._sessions.get("Q") or SessionNotLoaded("Qualifying", self)

    @property
    def sprint(self) -> "Session":
        """Sprint session (raises helpful error if not loaded)."""
        return self._sessions.get("S") or SessionNotLoaded("Sprint", self)

    @property
    def fp1(self) -> "Session":
        """FP1 session (raises helpful error if not loaded)."""
        return self._sessions.get("FP1") or SessionNotLoaded("FP1", self)

    @property
    def fp2(self) -> "Session":
        """FP2 session (raises helpful error if not loaded)."""
        return self._sessions.get("FP2") or SessionNotLoaded("FP2", self)

    @property
    def fp3(self) -> "Session":
        """FP3 session (raises helpful error if not loaded)."""
        return self._sessions.get("FP3") or SessionNotLoaded("FP3", self)

    def keys(self) -> List[str]:
        """List available data fields."""
        return [
            'year', 'round_number', 'event_name', 'location', 'country',
            'circuit_name', 'timezone', 'event_date', 'available_sessions',
            'circuit', 'track', 'pit_lane', 'circuit_length', 'corners', 'rotation',
            'race', 'qualifying', 'sprint', 'fp1', 'fp2', 'fp3'
        ]

    def _format_date_range(self) -> str:
        """Format event date range like '11-13 Apr'."""
        from datetime import datetime
        try:
            end = datetime.strptime(self.event_date, "%Y-%m-%d")
            start = datetime.strptime(self.event_start, "%Y-%m-%d") if self.event_start else None

            if start and start.month == end.month:
                return f"{start.day}-{end.day} {end.strftime('%b')}"
            elif start:
                return f"{start.day} {start.strftime('%b')} - {end.day} {end.strftime('%b')}"
            else:
                return f"{end.day} {end.strftime('%b')}"
        except (ValueError, TypeError):
            return self.event_date[:10] if self.event_date else ""

    def plot(
        self,
        figsize: tuple = (12, 10),
        color_mode: str = 'white',
        save_path: str = None,
        dpi: int = 150,
        track_width: float = 4,
    ):
        """
        Generate poster-style circuit map.

        Args:
            figsize: Figure size (width, height)
            color_mode: Track coloring - 'white', 'sectors', 'speed', 'throttle', 'height'
            save_path: Save to file instead of displaying
            dpi: Resolution for saved file
            track_width: Line width for track (default 4)

        Returns:
            matplotlib Figure
        """
        from f1_replay.tools.weekend_plot import plot_weekend

        return plot_weekend(
            circuit=self.circuit,
            event=self.event,
            figsize=figsize,
            color_mode=color_mode,
            save_path=save_path,
            dpi=dpi,
            track_width=track_width,
        )

    def __repr__(self) -> str:
        parts = [f"RaceWeekend({self.year} R{self.round_number}: {self.event_name}"]

        date_range = self._format_date_range()
        if date_range:
            parts.append(f', date="{date_range}"')

        # Convert to shortnames
        short_sessions = [
            self.SESSION_SHORTNAMES.get(s, s)
            for s in self.available_sessions
        ] if self.available_sessions else []
        sessions_str = ", ".join(short_sessions) if short_sessions else "none"
        parts.append(f", sessions=[{sessions_str}]")

        # Show loaded sessions
        for name, key in [("race", "R"), ("quali", "Q"), ("sprint", "S")]:
            if key in self._sessions:
                parts.append(f", {name}=loaded")

        parts.append(")")
        return "".join(parts)
