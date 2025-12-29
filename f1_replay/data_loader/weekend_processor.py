"""
Weekend Processor - TIER 2 Processing

Builds F1Weekend data (circuit info + metadata) from FastF1.
"""

from typing import Optional
from f1_replay.data_loader.data_models import (
    F1Weekend, WeekendMetadata, CircuitData
)
from f1_replay.data_loader.fastf1_client import FastF1Client
from f1_replay.data_loader.track_extractor import TrackExtractor


class WeekendProcessor:
    """Process and build F1Weekend data."""

    def __init__(self, fastf1_client: FastF1Client):
        """
        Initialize processor.

        Args:
            fastf1_client: FastF1Client instance
        """
        self.fastf1_client = fastf1_client
        self.track_extractor = TrackExtractor()

    def build_weekend(self, year: int, round_num: int) -> Optional[F1Weekend]:
        """
        Build complete weekend data (circuit + metadata).

        Args:
            year: Season year
            round_num: Round number

        Returns:
            F1Weekend object or None if error
        """
        print(f"→ Loading weekend {year} Round {round_num}...")

        # Get event metadata
        event = self.fastf1_client.get_event(year, round_num)
        if event is None:
            return None

        # Build circuit data
        # Need to load a session to get track geometry
        circuit = self._build_circuit(year, round_num, event)
        if circuit is None:
            return None

        # Build metadata
        metadata = self._build_metadata(year, round_num, event)

        weekend = F1Weekend(metadata=metadata, circuit=circuit)

        print(f"  ✓ Weekend complete: {metadata.event_name}")
        return weekend

    def _build_circuit(self, year: int, round_num: int, event) -> Optional[CircuitData]:
        """
        Build circuit data from track geometry extraction.

        Args:
            year: Season year
            round_num: Round number
            event: FastF1 event info

        Returns:
            CircuitData or None
        """
        print(f"  → Building circuit data...")

        # Try to load FP1 session to extract track geometry
        # (we need a session with lap data and telemetry)
        session = None
        for session_type in ['FP1', 'FP2', 'Q', 'R']:
            try:
                session = self.fastf1_client.get_session(year, round_num, session_type, load_telemetry=True)
                if session and session.laps is not None:
                    break
            except:
                continue

        if session is None:
            print(f"  ⚠ Could not load any session for track extraction")
            return None

        # Extract track geometry
        track = self.track_extractor.extract_track_geometry(session)
        if track is None:
            return None

        # Extract pit lane
        pit_lane = self.track_extractor.extract_pit_lane(session)

        # Get circuit info (for rotation and marshal sectors)
        circuit_info = None
        rotation_deg = 0.0
        try:
            circuit_info = session.get_circuit_info()
            if circuit_info and hasattr(circuit_info, 'rotation'):
                # FastF1 provides rotation directly in degrees
                rotation_deg = float(circuit_info.rotation)
                print(f"  ✓ Extracted rotation: {rotation_deg}°")
        except Exception as e:
            print(f"  ⚠ Could not extract rotation: {e}")

        # Extract track segments: try marshal sectors first, fall back to equal divisions
        segments = []
        if circuit_info:
            segments = self.track_extractor.extract_marshal_sectors(circuit_info)

        if not segments:
            # Fallback: create equal divisions if marshal sectors unavailable
            segments = self.track_extractor.create_track_segments(track.lap_distance, num_sectors=4)
            print(f"  ℹ Using equal divisions ({len(segments)} segments)")
        else:
            print(f"  ✓ Extracted marshal sectors: {len(segments)} sectors")

        # Build circuit
        circuit = CircuitData(
            track=track,
            pit_lane=pit_lane,
            track_segments=segments,
            circuit_length=track.lap_distance,
            corners=0,  # TODO: Calculate from track curvature
            rotation=rotation_deg,
            metadata={
                'track_points': len(track.x),
                'pit_lane_available': pit_lane is not None,
            }
        )

        return circuit

    def _build_metadata(self, year: int, round_num: int, event) -> WeekendMetadata:
        """
        Build weekend metadata from event info.

        Args:
            year: Season year
            round_num: Round number
            event: FastF1 event info

        Returns:
            WeekendMetadata
        """
        metadata = WeekendMetadata(
            year=year,
            round_number=round_num,
            event_name=event.get('EventName', ''),
            location=event.get('Location', ''),
            country=event.get('Country', ''),
            circuit_name=event.get('Circuit', ''),
            timezone=event.get('TimeZone', 'UTC'),
            event_date=str(event.get('EventDate', '')).split(' ')[0],  # YYYY-MM-DD
            session_schedule={},  # TODO: Extract from session dates
            available_sessions=['FP1', 'FP2', 'FP3', 'Q', 'R']  # TODO: Check actual
        )

        return metadata
