"""
Weekend Processor - TIER 2 Processing

Builds F1Weekend metadata from FastF1.
Track/pit geometry is extracted during session processing (TelemetryBuilder).
"""

from typing import Optional, Union
from f1_replay.models import (
    F1Weekend, CircuitData, TrackGeometry, EventInfo, SessionInfo
)
from f1_replay.loaders.core.client import FastF1Client

# Manual rotation overrides (location name -> degrees)
# Keys must be lowercase with underscores (normalized format)
# Only one entry per circuit - aliases are handled via LOCATION_ALIASES
MANUAL_ROTATIONS = {
    "melbourne": 38,
    "suzuka": 0,
    "spielberg": 30,
    "silverstone": 275,
    "spa_francorchamps": 97,
    "budapest": 310,
    "zandvoort": 175,
    "monza": 95,
    "baku": 310,
    "marina_bay": 360,
    "austin": 0,
    "mexico_city": 8,
    "sao_paulo": 270,
    "las_vegas": 90,
    "lusail": 61,
    "yas_marina": 265,
}

# Location aliases - tracks with different names across years (bidirectional)
# When looking up rotation, all aliases in a group are checked
LOCATION_ALIASES = [
    {"yas_marina", "yas_island"},  # Abu Dhabi
    {"imola", "emilia_romagna"},   # Imola
    {"portimao", "algarve"},       # Portugal
]


def get_manual_rotation(location: str) -> Optional[float]:
    """Get manual rotation override for a location, checking aliases."""
    # Normalize: lowercase, replace spaces with underscores
    key = location.lower().replace(" ", "_").replace("-", "_")

    # Direct lookup
    if key in MANUAL_ROTATIONS:
        return MANUAL_ROTATIONS[key]

    # Check if key matches any alias group, then look up all aliases
    for alias_group in LOCATION_ALIASES:
        if any(alias in key or key in alias for alias in alias_group):
            # Found matching alias group - check all aliases for rotation
            for alias in alias_group:
                if alias in MANUAL_ROTATIONS:
                    return MANUAL_ROTATIONS[alias]

    return None


class WeekendProcessor:
    """Process and build F1Weekend data."""

    def __init__(self, fastf1_client: FastF1Client):
        self.fastf1_client = fastf1_client

    def build_weekend(self, year: int, round_num_or_name: Union[int, str],
                      test_number: Optional[int] = None) -> Optional[F1Weekend]:
        """
        Build weekend data (metadata + basic circuit info).

        Track geometry is extracted later during session processing.

        Args:
            year: Season year
            round_num_or_name: Round number (int) or event name (str) for testing events
            test_number: For testing events, the test number (1, 2, etc.)
        """
        # Handle testing events with dedicated FastF1 API
        if test_number is not None:
            print(f"→ Loading weekend {year} T{test_number:02d}...")
            event = self.fastf1_client.get_testing_event(year, test_number)
        else:
            identifier = f"'{round_num_or_name}'" if isinstance(round_num_or_name, str) else f"Round {round_num_or_name}"
            print(f"→ Loading weekend {year} {identifier}...")
            event = self.fastf1_client.get_event(year, round_num_or_name)

        if event is None:
            return None

        # Get round number from event (may be 0 for testing)
        round_num = event.get('RoundNumber', 0)
        circuit_name = event.get('Location', '') or event.get('OfficialEventName', '')

        # Build basic circuit data (track geometry comes from session)
        circuit = self._build_circuit(year, round_num_or_name, test_number, circuit_name)

        # Build event info
        event_info = self._build_event_info(year, round_num, event)

        weekend = F1Weekend(event=event_info, circuit=circuit)
        print(f"  ✓ Weekend complete: {event_info.name}")
        return weekend

    def _build_circuit(self, year: int, round_num_or_name: Union[int, str],
                       test_number: Optional[int] = None, circuit_name: str = "") -> Optional[CircuitData]:
        """Build basic circuit data. Full track geometry comes from session."""
        print(f"  → Building circuit data...")

        # Try to get circuit info (rotation, etc.) from any session
        session = None
        rotation_deg = 0.0
        circuit_length = 5000.0  # Default, will be updated from session

        if test_number is not None:
            # For testing events, use testing session API
            for session_num in [1, 2, 3]:
                try:
                    session = self.fastf1_client.get_testing_session(year, test_number, session_num, load_telemetry=False)
                    if session:
                        break
                except:
                    continue
        else:
            for session_type in ['FP1', 'Q', 'R']:
                try:
                    session = self.fastf1_client.get_session(year, round_num_or_name, session_type, load_telemetry=False)
                    if session:
                        break
                except:
                    continue

        if session:
            try:
                circuit_info = session.get_circuit_info()
                if circuit_info and hasattr(circuit_info, 'rotation'):
                    rotation_deg = float(circuit_info.rotation)
            except:
                pass

        # Check for manual rotation override (takes priority over FastF1)
        manual_rot = get_manual_rotation(circuit_name)
        if manual_rot is not None:
            rotation_deg = manual_rot
            print(f"  ✓ Rotation: {rotation_deg}° (manual override)")
        elif rotation_deg != 0:
            print(f"  ✓ Rotation: {rotation_deg}° (FastF1)")

        # Create placeholder track geometry (will be replaced by session data)
        placeholder_track = TrackGeometry(
            x=None, y=None, distance=None, lap_distance=circuit_length
        )

        circuit = CircuitData(
            track=placeholder_track,
            pit_lane=None,
            track_segments=[],
            circuit_length=circuit_length,
            corners=0,
            rotation=rotation_deg,
            name=circuit_name,
            metadata={'source': 'weekend_placeholder'}
        )

        return circuit

    def _build_event_info(self, year: int, round_num: int, event) -> EventInfo:
        """Build EventInfo from FastF1 event data."""
        # Build sessions with full datetime
        sessions = []

        for i in range(1, 6):  # Session1 through Session5
            session_name = event.get(f'Session{i}')
            session_date = event.get(f'Session{i}Date')

            if session_name and str(session_name) not in ('nan', 'None', ''):
                date_str = ""
                if session_date is not None:
                    try:
                        date_str = str(session_date)
                        # Clean up pandas timestamp format
                        if 'T' not in date_str and ' ' in date_str:
                            date_str = date_str.replace(' ', 'T')
                    except (ValueError, TypeError, AttributeError):
                        pass
                sessions.append(SessionInfo(name=str(session_name), date=date_str))

        # Get event start from first session
        event_start = ""
        if sessions:
            first_date = sessions[0].date
            if first_date:
                event_start = first_date.split('T')[0][:10]

        return EventInfo(
            name=event.get('EventName', ''),
            location=event.get('Location', ''),
            country=event.get('Country', ''),
            circuit_name=event.get('Circuit', ''),
            year=year,
            round_number=round_num,
            start_date=event_start,
            end_date=str(event.get('EventDate', '')).split(' ')[0],
            sessions=sessions,
            timezone=event.get('TimeZone', 'UTC'),
            event_format=str(event.get('EventFormat', 'conventional')),
        )
