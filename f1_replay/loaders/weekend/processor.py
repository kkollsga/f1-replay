"""
Weekend Processor - TIER 2 Processing

Builds F1Weekend with complete track geometry using LightTelemetryBuilder.
Track/pit geometry is extracted during weekend build (not deferred to session).
"""

from typing import Optional, Union
import numpy as np
from f1_replay.models import (
    F1Weekend, CircuitData, TrackGeometry, EventInfo, SessionInfo, PitLane, DirectionArrow, MarshalSector, Corner
)
from f1_replay.loaders.core.client import FastF1Client
from f1_replay.loaders.weekend.light_telemetry import LightTelemetryBuilder
from f1_replay.loaders.session.telemetry import TrackData

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


def extract_timezone_offset(date_str: str) -> str:
    """Extract timezone offset from ISO datetime string (e.g., '+02:00' from '2025-09-05T13:30:00+02:00')."""
    import re
    if date_str:
        match = re.search(r'([+-]\d{2}:\d{2})$', date_str)
        if match:
            return match.group(1)
    return ""


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
        Build weekend data with complete track geometry.

        Track geometry is extracted during weekend build using LightTelemetryBuilder.

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

        # Build event info first (needed for testing event detection)
        event_info = self._build_event_info(year, round_num, event)

        # Build circuit with REAL track geometry (not placeholder)
        circuit = self._build_circuit_with_track(year, round_num_or_name, test_number, circuit_name, event_info)

        weekend = F1Weekend(event=event_info, circuit=circuit)
        print(f"  ✓ Weekend complete: {event_info.name}")
        return weekend

    def _build_circuit_with_track(self, year: int, round_num_or_name: Union[int, str],
                                   test_number: Optional[int] = None, circuit_name: str = "",
                                   event_info: Optional[EventInfo] = None) -> Optional[CircuitData]:
        """
        Build circuit data with real track geometry extracted from telemetry.

        Steps:
        1. Get rotation (manual override or FastF1)
        2. Load race session with telemetry
        3. Extract track using LightTelemetryBuilder
        4. If extraction fails, create placeholder (future races, new circuits)
        5. Build CircuitData with TrackGeometry

        Args:
            year: Season year
            round_num_or_name: Round number or event name
            test_number: Testing event number (if applicable)
            circuit_name: Circuit location name
            event_info: Event information (for testing event detection)

        Returns:
            CircuitData with real track or placeholder
        """
        print(f"  → Building circuit with track geometry...")

        # Get rotation (manual override takes priority)
        rotation_deg = self._get_rotation(year, round_num_or_name, test_number, circuit_name)

        # Skip extraction for testing events (use historical data instead)
        if event_info and event_info.format == 'testing':
            print(f"  ⚠ Testing event - creating placeholder (will use historical track)")
            return self._build_placeholder_circuit(circuit_name, rotation_deg)

        # Try to extract track from race session
        track_data = self._extract_track_from_race(year, round_num_or_name, test_number)

        if track_data is None:
            # Fallback: create placeholder (for future races, new circuits)
            print(f"  ⚠ Could not extract track - using placeholder")
            return self._build_placeholder_circuit(circuit_name, rotation_deg)

        # Build complete CircuitData with real track
        return self._build_complete_circuit(track_data, circuit_name, rotation_deg)

    def _get_rotation(self, year: int, round_num_or_name: Union[int, str],
                      test_number: Optional[int], circuit_name: str) -> float:
        """Get circuit rotation from manual override or FastF1."""
        rotation_deg = 0.0

        # Try to get rotation from FastF1 circuit_info
        session = None
        if test_number is not None:
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

        # Check for manual rotation override (takes priority)
        manual_rot = get_manual_rotation(circuit_name)
        if manual_rot is not None:
            rotation_deg = manual_rot
            print(f"  ✓ Rotation: {rotation_deg}° (manual override)")
        elif rotation_deg != 0:
            print(f"  ✓ Rotation: {rotation_deg}° (FastF1)")

        return rotation_deg

    def _extract_track_from_race(self, year: int, round_num_or_name: Union[int, str],
                                 test_number: Optional[int]) -> Optional[TrackData]:
        """
        Extract track geometry from race session only.

        Uses race winner's telemetry for track extraction.

        Args:
            year: Season year
            round_num_or_name: Round number or event name
            test_number: Testing event number (if applicable)

        Returns:
            TrackData or None if extraction fails
        """
        try:
            # Load race session with telemetry
            if test_number is not None:
                # Testing events don't extract track (handled by historical search in Manager)
                return None

            print(f"  → Loading race session for track extraction...")
            session = self.fastf1_client.get_session_with_all_data(year, round_num_or_name, 'R')

            if session is None:
                return None

            # Get race winner
            winner = self._get_race_winner(session)
            if winner is None:
                print(f"  ⚠ Could not determine race winner")
                return None

            print(f"  → Extracting track from race winner: {winner}")

            # Extract track using light telemetry
            track_data = LightTelemetryBuilder.extract_track_geometry(session, winner)

            # Extract marshal sectors by projecting X,Y onto track
            if track_data is not None:
                track_data = self._add_circuit_info(session, track_data)

            return track_data

        except Exception as e:
            print(f"  ⚠ Track extraction failed: {e}")
            return None

    def _get_race_winner(self, f1_session) -> Optional[str]:
        """Get race winner abbreviation from results."""
        try:
            results = f1_session.results
            if results is not None and len(results) > 0:
                p1 = results[results['Position'] == 1]
                if len(p1) > 0:
                    return p1.iloc[0]['Abbreviation']
        except Exception:
            pass
        return None

    def _add_circuit_info(self, f1_session, track_data: TrackData) -> TrackData:
        """
        Extract marshal sectors and corners from circuit_info.

        Projects X,Y coordinates onto track using our internal track distance.
        """
        try:
            circuit_info = f1_session.get_circuit_info()
            if circuit_info is None:
                return track_data

            track_x = track_data.track_x
            track_y = track_data.track_y
            track_dist = track_data.track_distance  # decimeters
            lap_distance_dm = track_data.lap_distance
            lap_distance_m = lap_distance_dm / 10.0

            marshal_sectors = None
            corners = None

            # Extract marshal sectors
            if hasattr(circuit_info, 'marshal_sectors') and circuit_info.marshal_sectors is not None:
                marshal_df = circuit_info.marshal_sectors
                if len(marshal_df) > 0:
                    sector_nums = marshal_df['Number'].values.astype(np.int32)
                    sector_x = marshal_df['X'].values.astype(np.float32)
                    sector_y = marshal_df['Y'].values.astype(np.float32)

                    # Project onto track
                    dist_sq = (sector_x[:, None] - track_x[None, :])**2 + (sector_y[:, None] - track_y[None, :])**2
                    closest_indices = np.argmin(dist_sq, axis=1)
                    dist_meters = track_dist[closest_indices] / 10.0

                    sector_distances = sorted(zip(sector_nums, dist_meters), key=lambda x: x[1])

                    marshal_sectors = []
                    for i, (sector_num, from_dist) in enumerate(sector_distances):
                        to_dist = sector_distances[i + 1][1] if i + 1 < len(sector_distances) else lap_distance_m + sector_distances[0][1]
                        marshal_sectors.append((sector_num, from_dist, to_dist))

                    print(f"    ✓ Marshal sectors: {len(marshal_sectors)}")

            # Extract corners
            if hasattr(circuit_info, 'corners') and circuit_info.corners is not None:
                corners_df = circuit_info.corners
                if len(corners_df) > 0:
                    corner_nums = corners_df['Number'].values.astype(np.int32)
                    corner_x = corners_df['X'].values.astype(np.float32)
                    corner_y = corners_df['Y'].values.astype(np.float32)
                    corner_angles = corners_df['Angle'].values.astype(np.float32)
                    corner_letters = corners_df['Letter'].values if 'Letter' in corners_df.columns else [''] * len(corner_nums)

                    # Project onto track
                    dist_sq = (corner_x[:, None] - track_x[None, :])**2 + (corner_y[:, None] - track_y[None, :])**2
                    closest_indices = np.argmin(dist_sq, axis=1)
                    dist_meters = track_dist[closest_indices] / 10.0

                    corners = []
                    for i, num in enumerate(corner_nums):
                        letter = str(corner_letters[i]) if corner_letters[i] and str(corner_letters[i]) != 'nan' else ''
                        corners.append((int(num), float(dist_meters[i]), float(corner_angles[i]), letter))

                    print(f"    ✓ Corners: {len(corners)}")

            return TrackData(
                track_x=track_data.track_x,
                track_y=track_data.track_y,
                track_distance=track_data.track_distance,
                lap_distance=track_data.lap_distance,
                pit_x=track_data.pit_x,
                pit_y=track_data.pit_y,
                pit_distance=track_data.pit_distance,
                pit_length=track_data.pit_length,
                pit_entry_distance=track_data.pit_entry_distance,
                pit_exit_distance=track_data.pit_exit_distance,
                marshal_sectors=marshal_sectors,
                corners=corners,
                speed=track_data.speed,
                throttle=track_data.throttle,
                brake=track_data.brake,
                track_z=track_data.track_z
            )

        except Exception as e:
            print(f"    ⚠ Could not extract circuit info: {e}")
            return track_data

    def _build_complete_circuit(self, track_data: TrackData, circuit_name: str,
                                rotation_deg: float) -> CircuitData:
        """Build CircuitData from extracted TrackData."""
        # Convert distances from decimeters to meters
        circuit_length_meters = track_data.lap_distance / 10.0
        distance_meters = track_data.track_distance / 10.0 if track_data.track_distance is not None else None

        # Convert marshal sector tuples to MarshalSector objects
        marshal_sectors = []
        if track_data.marshal_sectors:
            for sector_num, from_dist, to_dist in track_data.marshal_sectors:
                marshal_sectors.append(MarshalSector(
                    number=int(sector_num),
                    start_distance=float(from_dist),
                    end_distance=float(to_dist)
                ))

        # Convert corner tuples to Corner objects
        corners = []
        if track_data.corners:
            for number, distance, angle, letter in track_data.corners:
                corners.append(Corner(
                    number=number,
                    distance=distance,
                    angle=angle,
                    letter=letter
                ))

        # Build TrackGeometry
        track = TrackGeometry(
            x=track_data.track_x,
            y=track_data.track_y,
            distance=distance_meters,
            lap_distance=circuit_length_meters,
            marshal_sectors=marshal_sectors,
            speed=track_data.speed,
            throttle=track_data.throttle,
            brake=track_data.brake,
            z=track_data.track_z
        )

        # Build pit lane
        pit_lane = None
        if track_data.pit_x is not None and len(track_data.pit_x) > 0:
            pit_lane = PitLane(
                x=track_data.pit_x,
                y=track_data.pit_y,
                distance=track_data.pit_distance,
                length=track_data.pit_length,
                entry_track_dist=track_data.pit_entry_distance or 0.0,
                exit_track_dist=track_data.pit_exit_distance or 0.0
            )

        # Calculate direction arrow (opposite side of pit lane)
        direction_arrow = None
        if track_data.track_x is not None and len(track_data.track_x) > 1:
            # Track direction at start/finish
            dx = track_data.track_x[1] - track_data.track_x[0]
            dy = track_data.track_y[1] - track_data.track_y[0]
            length = np.sqrt(dx*dx + dy*dy)
            if length > 0:
                # Unit vector in racing direction
                dir_x, dir_y = dx / length, dy / length
                # Perpendicular (both sides)
                perp_x, perp_y = -dir_y, dir_x  # Left side

                # Place arrow opposite pit lane
                arrow_offset = 200  # Distance from centerline (decimeters)
                left_x = track_data.track_x[0] + perp_x * arrow_offset
                left_y = track_data.track_y[0] + perp_y * arrow_offset
                right_x = track_data.track_x[0] - perp_x * arrow_offset
                right_y = track_data.track_y[0] - perp_y * arrow_offset

                # Pick side farther from pit
                if pit_lane is not None and track_data.pit_x is not None and len(track_data.pit_x) > 0:
                    start_x, start_y = track_data.track_x[0], track_data.track_y[0]
                    pit_dists = (track_data.pit_x - start_x)**2 + (track_data.pit_y - start_y)**2
                    nearest_idx = np.argmin(pit_dists)
                    pit_near_x = track_data.pit_x[nearest_idx]
                    pit_near_y = track_data.pit_y[nearest_idx]

                    dist_left = (left_x - pit_near_x)**2 + (left_y - pit_near_y)**2
                    dist_right = (right_x - pit_near_x)**2 + (right_y - pit_near_y)**2
                    arrow_x, arrow_y = (left_x, left_y) if dist_left > dist_right else (right_x, right_y)
                else:
                    arrow_x, arrow_y = left_x, left_y

                direction_arrow = DirectionArrow(
                    x=float(arrow_x), y=float(arrow_y),
                    dx=float(dir_x), dy=float(dir_y)
                )

        return CircuitData(
            track=track,
            pit_lane=pit_lane,
            circuit_length=circuit_length_meters,
            corners=corners,
            rotation=rotation_deg,
            name=circuit_name,
            direction_arrow=direction_arrow,
            metadata={'source': 'light_telemetry_weekend'}
        )

    def _build_placeholder_circuit(self, circuit_name: str, rotation_deg: float) -> CircuitData:
        """
        Build placeholder circuit data (for future races or extraction failures).

        Track geometry will be extracted later (legacy fallback in Manager).
        """
        circuit_length = 5000.0  # Default, will be updated from actual session

        # Create placeholder track geometry
        placeholder_track = TrackGeometry(
            x=None, y=None, distance=None, lap_distance=circuit_length
        )

        circuit = CircuitData(
            track=placeholder_track,
            pit_lane=None,
            circuit_length=circuit_length,
            corners=[],
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

        # Extract timezone offset from first session's datetime string
        timezone = ""
        for s in sessions:
            if s.date:
                timezone = extract_timezone_offset(s.date)
                if timezone:
                    break

        return EventInfo(
            name=event.get('EventName', ''),
            official_name=event.get('OfficialEventName', ''),
            circuit_name=event.get('Location', ''),
            country=event.get('Country', ''),
            year=year,
            round_number=round_num,
            start_date=event_start,
            end_date=str(event.get('EventDate', '')).split(' ')[0],
            sessions=sessions,
            timezone_offset=timezone,
            format=str(event.get('EventFormat', 'conventional')),
        )
