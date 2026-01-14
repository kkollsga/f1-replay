"""
Session Processor - TIER 3 Processing

Builds SessionData (telemetry, events, results) from FastF1.
Event times are normalized to session start (t0) automatically.
"""

from typing import Optional, Dict, Any
import datetime
import numpy as np
import polars as pl
import pandas as pd
from f1_replay.models import (
    SessionData, SessionMetadata, EventsData, ResultsData,
    FastestLapEvent, PositionSnapshot, PositionEntry,
    TrackStatusEvent, RaceControlMessage, WeatherSample, T0Info
)
from f1_replay.loaders.core.client import FastF1Client
from f1_replay.loaders.session.weather import WeatherExtractor
from f1_replay.loaders.session.telemetry import TelemetryBuilder
from f1_replay.loaders.session.order import OrderBuilder


class SessionProcessor:
    """Process and build SessionData."""

    # Message patterns from "Other" category that are routed to track_status/subtitle
    # These are excluded from race_control to avoid duplicates
    TRACK_STATUS_MESSAGE_PATTERNS = ['ABORTED START']
    # Regex pattern for messages with timestamps (e.g., "RACE WILL START AT 12:47")
    # These become status subtitles, not race control messages
    TIMESTAMP_MESSAGE_PATTERN = r'AT\s+\d{1,2}:\d{2}'

    def __init__(self, fastf1_client: FastF1Client, circuit_length: float, weekend_track=None):
        """
        Initialize processor.

        Args:
            fastf1_client: FastF1Client instance
            circuit_length: Track length for metadata
            weekend_track: Optional TrackGeometry from Weekend (for adding track_distance to telemetry)
        """
        self.fastf1_client = fastf1_client
        self.circuit_length = circuit_length
        self.weekend_track = weekend_track

    def _get_session_start_seconds_of_day(self, t0_date_utc: Optional[str]) -> Optional[float]:
        """Get session start time in seconds of day."""
        if not t0_date_utc:
            return None

        try:
            if 'T' in t0_date_utc:
                dt = datetime.datetime.fromisoformat(t0_date_utc.replace('Z', '+00:00'))
            else:
                dt = datetime.datetime.fromisoformat(t0_date_utc)

            seconds_of_day = dt.hour * 3600 + dt.minute * 60 + dt.second + dt.microsecond / 1e6
            return seconds_of_day
        except Exception:
            return None

    def _get_true_session_start_from_telemetry(self, telemetry: Dict[str, pl.DataFrame]) -> Optional[str]:
        """Get true session start time from telemetry data (RawTime column)."""
        if not telemetry:
            return None

        try:
            earliest_date = None

            for driver_tel in telemetry.values():
                # Use RawTime (renamed from Date in complete telemetry)
                col_name = 'RawTime' if 'RawTime' in driver_tel.columns else 'Date'

                if col_name in driver_tel.columns and len(driver_tel) > 0:
                    first_date = driver_tel[col_name][0]

                    if first_date is not None:
                        if not isinstance(first_date, pd.Timestamp):
                            first_date = pd.Timestamp(first_date)

                        if earliest_date is None:
                            earliest_date = first_date
                        elif first_date < earliest_date:
                            earliest_date = first_date

            if earliest_date is not None:
                if isinstance(earliest_date, pd.Timestamp):
                    return earliest_date.isoformat()
                else:
                    return str(earliest_date)

        except Exception:
            pass

        return None

    def _normalize_event_time(self, raw_time: float, t0_seconds_of_day: Optional[float],
                             time_obj=None, t0_datetime=None) -> float:
        """Normalize event time to session-relative (seconds since t0)."""
        # Preferred: use datetime objects for precision
        if time_obj is not None and t0_datetime is not None:
            try:
                if not isinstance(time_obj, pd.Timestamp):
                    time_obj = pd.Timestamp(time_obj)
                if not isinstance(t0_datetime, pd.Timestamp):
                    t0_datetime = pd.Timestamp(t0_datetime)

                diff = (time_obj - t0_datetime).total_seconds()
                return diff
            except Exception:
                pass

        # Secondary: use seconds of day if available
        if t0_seconds_of_day is not None and raw_time > 86400:
            return raw_time - t0_seconds_of_day

        # Fallback: return raw time as-is
        return raw_time

    def _find_race_start_time(self, events: EventsData, session_type: str) -> Optional[float]:
        """
        Find the actual race start time (lights out / formation lap start) from events.

        For race sessions (R), this is when the formation lap actually starts,
        which corresponds to the second GREEN LIGHT event in race_control messages.

        Args:
            events: EventsData with track status and race control events
            session_type: Type of session ("R", "Q", "FP1", etc.)

        Returns:
            session_time offset in seconds, or None if not found
        """
        if session_type != "R":
            return None

        try:
            # Look for GREEN LIGHT events in race_control messages
            if len(events.race_control) > 0:
                race_control_list = events.race_control.to_dicts()

                # GREEN LIGHT messages indicate pit exit open / race start
                # The first GREEN LIGHT (around -2400s) is pre-race pit exit open
                # The second GREEN LIGHT (around 0s) is formation lap start
                green_lights = [e for e in race_control_list
                               if 'GREEN LIGHT' in e.get('message', '').upper()]

                if len(green_lights) >= 2:
                    # Use the second GREEN LIGHT as race start
                    race_start_time = green_lights[1].get('session_time')
                    if race_start_time is not None:
                        return float(race_start_time)

            # Fallback: use first AllClear from track_status that's near session start
            if len(events.track_status) > 0:
                track_status_list = events.track_status.to_dicts()
                for e in track_status_list:
                    if e.get('status') == 'AllClear':
                        session_time = e.get('session_time', 0)
                        # First AllClear should be right after lights out (< 60 seconds)
                        if 0 <= session_time < 60:
                            return float(session_time)

        except Exception:
            pass

        return None

    def _renormalize_to_race_start(self, session_data: SessionData, race_start_time: float) -> SessionData:
        """
        Re-normalize all times to be relative to race start (lights out) instead of t0.

        Args:
            session_data: SessionData with times normalized to t0
            race_start_time: session_time offset of race start (lights out)

        Returns:
            SessionData with times re-normalized to race start
        """
        from dataclasses import replace

        # Re-normalize telemetry
        renormalized_telemetry = {}
        for driver, tel in session_data.telemetry.items():
            if "session_time" in tel.columns:
                # Subtract race_start_time from all session_time values
                new_session_time = tel["session_time"] - race_start_time
                tel_renormalized = tel.with_columns(
                    pl.Series("session_time", new_session_time, dtype=pl.Float64)
                )
                renormalized_telemetry[driver] = tel_renormalized
            else:
                renormalized_telemetry[driver] = tel

        # Re-normalize events
        def renormalize_df(df: pl.DataFrame) -> pl.DataFrame:
            if len(df) == 0 or "session_time" not in df.columns:
                return df
            new_session_time = df["session_time"] - race_start_time
            return df.with_columns(
                pl.Series("session_time", new_session_time, dtype=pl.Float64)
            )

        renormalized_events = EventsData(
            track_status=renormalize_df(session_data.events.track_status),
            race_control=renormalize_df(session_data.events.race_control)
        )

        # Re-normalize results if they have session_time
        renormalized_results = session_data.results
        if session_data.results and hasattr(session_data.results, 'position_history'):
            if session_data.results.position_history:
                renormalized_positions = []
                for snapshot in session_data.results.position_history:
                    # Update snapshot time
                    new_time = snapshot.time - race_start_time if snapshot.time is not None else snapshot.time
                    new_snapshot = snapshot.__class__(
                        time=new_time,                        standings=snapshot.standings
                    )
                    renormalized_positions.append(new_snapshot)

                renormalized_results = replace(
                    session_data.results,
                    position_history=renormalized_positions
                )

        # Create new SessionData with renormalized times
        return replace(
            session_data,
            telemetry=renormalized_telemetry,
            events=renormalized_events,
            results=renormalized_results
        )

    def build_session(self, year: int, round_num: int,
                     session_type: str, event_name: str) -> Optional[tuple]:
        """
        Build complete session data with logical dependency order.

        Processing order (NEW):
        1. Load FastF1 session
        2. Extract DNF drivers
        3. Build SessionMetadata FIRST (uses f1_session.date for warmup start)
        4. Build EventsData SECOND (uses metadata.t0 for synthetic events)
        5. Build Telemetry LAST (all dependencies available)
        6. Add track distance, positions, intervals
        7. Build results

        Args:
            year: Season year
            round_num: Round number
            session_type: "FP1", "FP2", "FP3", "Q", "S", "R"
            event_name: Event name for metadata

        Returns:
            Tuple of (SessionData, raw_f1_session, track_data) or None if error
        """
        print(f"→ Loading session {year} R{round_num} {session_type}...")

        # STEP 1: Load FastF1 session
        f1_session = self.fastf1_client.get_session_with_all_data(year, round_num, session_type)
        if f1_session is None:
            return None

        # STEP 2: Extract DNF drivers
        dnf_drivers_set = self._extract_dnf_drivers(f1_session)

        # STEP 3: Build SessionMetadata FIRST ★
        print(f"  → Building metadata...")
        metadata = self._build_metadata(
            year, round_num, session_type, event_name,
            f1_session,
            laps_df=f1_session.laps  # For lights_out_offset extraction
        )
        print(f"  ✓ Metadata built with {len(metadata.drivers)} drivers")

        # STEP 4: Build EventsData SECOND ★
        print(f"  → Building events...")
        events = self._build_events(f1_session, t0_info=metadata.t0)
        print(f"  ✓ Events built")

        # STEP 5: Build Telemetry LAST ★
        print(f"  → Building telemetry from pos_data + car_data...")
        telemetry, track_data, session_timing, status_data_all = TelemetryBuilder.build_telemetry(
            f1_session,
            dnf_drivers=dnf_drivers_set,
            extract_track=False  # Track extracted during weekend build, not session
        )

        if not telemetry:
            print(f"  ⚠ No telemetry data available")
            return None

        # STEP 6: Add track distance using weekend's track geometry
        if self.weekend_track is not None and self.weekend_track.x is not None:
            print(f"  → Adding track_distance from weekend track geometry...")
            # Create a temporary TrackData-like structure for TelemetryBuilder
            from f1_replay.loaders.session.telemetry import TrackData
            temp_track_data = TrackData(
                track_x=self.weekend_track.x,
                track_y=self.weekend_track.y,
                track_z=self.weekend_track.z,
                track_distance=(self.weekend_track.distance * 10.0).astype(np.float32) if self.weekend_track.distance is not None else None,  # meters -> decimeters
                lap_distance=self.weekend_track.lap_distance * 10.0,  # meters -> decimeters
                pit_x=None, pit_y=None, pit_distance=None, pit_length=0.0,
                pit_entry_distance=None, pit_exit_distance=None,
                marshal_sectors=[], speed=None, throttle=None, brake=None
            )
            # Use metadata.t0 for session_timing (compatibility with existing code)
            session_timing_compat = None
            if metadata.t0 and metadata.t0.warmup_start_offset is not None:
                session_timing_compat = {'warmup_start_time': metadata.t0.warmup_start_offset}

            # Add track_distance, race_distance, and update lap_number
            telemetry = TelemetryBuilder._add_track_distance_all(telemetry, temp_track_data, session_timing_compat)
            print(f"  ✓ Track distance added from weekend track")
        else:
            # No track geometry available - add placeholder columns for status update
            print(f"  ⚠ No weekend track geometry, adding placeholder distance columns")
            for driver, tel in telemetry.items():
                n_rows = len(tel)
                telemetry[driver] = tel.with_columns([
                    pl.lit(0.0).cast(pl.Float32).alias('track_distance'),
                    pl.lit(0.0).cast(pl.Float32).alias('race_distance'),
                ])

        # STEP 6.5: Update status column (ALWAYS, regardless of track geometry)
        # Extract warmup intervals from track_status
        warmup_intervals = []
        if events and events.track_status is not None:
            warmup_events = events.track_status.filter(events.track_status['status'] == 'WarmUp')
            for row in warmup_events.iter_rows(named=True):
                start = row['session_time']
                end = row.get('end_time', None)
                if start is not None and end is not None:
                    warmup_intervals.append((start, end))

        # Get lights_out_offset from metadata
        lights_out_offset = metadata.t0.lights_out_offset if metadata.t0 else None

        # Update status column using warmup intervals and lights_out
        telemetry = TelemetryBuilder._add_status_all(
            telemetry,
            status_data_all,
            warmup_intervals=warmup_intervals,
            lights_out_offset=lights_out_offset
        )
        print(f"  ✓ Status updated from track events")

        # STEP 7: Add positions and intervals
        print(f"  → Adding positions to telemetry...")
        telemetry = OrderBuilder.add_positions_to_telemetry(telemetry)
        print(f"  ✓ Positions added to {len(telemetry)} drivers")

        print(f"  → Adding intervals to telemetry...")
        telemetry = OrderBuilder.add_intervals_to_telemetry(telemetry)
        print(f"  ✓ Intervals added")

        # STEP 8: Build results
        t0_utc = metadata.t0.utc if metadata.t0 else None
        results = self._build_results(f1_session, telemetry, t0_utc)

        # STEP 9: Update metadata with telemetry session_duration
        if metadata.t0 and telemetry:
            # Recalculate session_duration now that we have telemetry
            max_time = 0.0
            min_time = float('inf')
            for df in telemetry.values():
                if 'session_time' in df.columns and len(df) > 0:
                    max_time = max(max_time, df['session_time'].max())
                    min_time = min(min_time, df['session_time'].min())
            if min_time != float('inf'):
                session_duration = max_time - min_time
                # Update T0Info with calculated session_duration
                from f1_replay.models.session import T0Info
                metadata = SessionMetadata(
                    session_type=metadata.session_type,
                    year=metadata.year,
                    round_number=metadata.round_number,
                    event_name=metadata.event_name,
                    drivers=metadata.drivers,
                    driver_numbers=metadata.driver_numbers,
                    driver_names=metadata.driver_names,
                    driver_teams=metadata.driver_teams,
                    driver_colors=metadata.driver_colors,
                    team_colors=metadata.team_colors,
                    track_length=metadata.track_length,
                    total_laps=metadata.total_laps,
                    dnf_drivers=metadata.dnf_drivers,
                    t0=T0Info(
                        utc=metadata.t0.utc,
                        timezone=metadata.t0.timezone,
                        utc_offset_hours=metadata.t0.utc_offset_hours,
                        warmup_start_offset=metadata.t0.warmup_start_offset,
                        lights_out_offset=metadata.t0.lights_out_offset,
                        session_duration=session_duration
                    ),
                    start_time_local=metadata.start_time_local
                )

        # Create final SessionData
        session_data = SessionData(
            metadata=metadata,
            telemetry=telemetry,
            events=events,
            results=results
        )

        print(f"  ✓ Session complete: {len(metadata.drivers)} drivers, {len(telemetry)} with telemetry")
        return session_data, f1_session, track_data

    def _extract_dnf_drivers(self, f1_session) -> set:
        """
        Extract DNF driver codes from session results.

        Uses FastF1 results.Status to identify drivers who retired.
        Finished statuses: "Finished", "Lapped", "+1 Lap", "+2 Laps", etc.
        DNF statuses: "Retired", "Accident", "Engine", "Collision", etc.

        Returns:
            Set of driver abbreviations who did not finish
        """
        dnf_drivers = set()
        results = self.fastf1_client.get_driver_results(f1_session)

        if results is not None:
            for _, row in results.iterrows():
                abbr = row.get('Abbreviation')
                status = row.get('Status', '')
                if abbr and status:
                    is_finished = status in ('Finished', 'Lapped') or status.startswith('+')
                    if not is_finished:
                        dnf_drivers.add(abbr)

        if dnf_drivers:
            print(f"  → DNF drivers from results: {', '.join(sorted(dnf_drivers))}")

        return dnf_drivers

    def _build_metadata(self, year: int, round_num: int, session_type: str,
                       event_name: str, f1_session, laps_df,
                       telemetry: Optional[Dict[str, pl.DataFrame]] = None) -> SessionMetadata:
        """
        Build SessionMetadata using FastF1 data directly.

        Args:
            year: Season year
            round_num: Round number
            session_type: Session type ("R", "Q", etc.)
            event_name: Event name
            f1_session: FastF1 session object
            laps_df: Lap data for lights_out_offset extraction
            telemetry: Optional telemetry for session_duration calculation

        Returns:
            Complete SessionMetadata with T0Info
        """
        drivers = self.fastf1_client.get_drivers_in_session(f1_session)
        results = self.fastf1_client.get_driver_results(f1_session)

        # Extract driver info from results
        driver_numbers = {}
        driver_names = {}
        driver_teams = {}
        driver_colors = {}
        team_colors = {}
        dnf_drivers = []

        if results is not None:
            for _, row in results.iterrows():
                abbr = row.get('Abbreviation')
                number = row.get('DriverNumber')
                name = row.get('FullName')
                team = row.get('TeamName')
                color = row.get('TeamColor')
                status = row.get('Status', '')

                if abbr and number:
                    driver_numbers[abbr] = int(number)
                if abbr and name:
                    driver_names[abbr] = str(name)
                if abbr and team:
                    driver_teams[abbr] = team
                if abbr and color:
                    driver_colors[abbr] = str(color) if pd.notna(color) else '#CCCCCC'
                if team and color:
                    team_colors[team] = str(color) if pd.notna(color) else '#CCCCCC'

                # Track DNF drivers - any status that's not a finish
                # Finished statuses: "Finished", "Lapped", "+1 Lap", "+2 Laps", etc.
                # DNF statuses: "Retired", "Engine", "Collision", "Accident", etc.
                if abbr and status:
                    is_finished = status in ('Finished', 'Lapped') or status.startswith('+')
                    if not is_finished:
                        dnf_drivers.append(abbr)

        # Build T0Info (now uses f1_session.date directly for warmup start)
        t0_info = self._build_t0_info(f1_session, laps_df, telemetry)

        # Extract session start time as ISO string (for timezone conversion in display)
        start_time_local = None
        if hasattr(f1_session, 'date') and f1_session.date is not None:
            try:
                # Store as ISO format for timezone conversion later
                start_time_local = f1_session.date.isoformat()
            except (AttributeError, ValueError):
                pass

        metadata = SessionMetadata(
            session_type=session_type,
            year=year,
            round_number=round_num,
            event_name=event_name,
            drivers=drivers,
            driver_numbers=driver_numbers,
            driver_names=driver_names,
            driver_teams=driver_teams,
            driver_colors=driver_colors,
            team_colors=team_colors,
            track_length=self.circuit_length,
            total_laps=int(f1_session.laps['LapNumber'].max()) if f1_session.laps is not None and len(f1_session.laps) > 0 else 0,
            dnf_drivers=dnf_drivers,
            t0=t0_info,
            start_time_local=start_time_local
        )

        return metadata

    def _build_t0_info(self, f1_session, laps_df, telemetry: Optional[Dict[str, pl.DataFrame]] = None) -> Optional[T0Info]:
        """
        Build T0Info using FastF1's session start time.

        Args:
            f1_session: FastF1 session object
            laps_df: Lap data (for extracting lights_out_offset)
            telemetry: Optional telemetry for session_duration calculation

        Returns:
            T0Info with warmup_start_time and lights_out_offset

        Note:
            t0.utc = FastF1's timing zero (t0_date) - the point where session_time=0
            lights_out_offset = seconds from t0 to lights out (positive value)
            warmup_start_offset = seconds from t0 to session scheduled start (positive value)
            session_duration = total telemetry duration
        """
        t0_date = getattr(f1_session, 't0_date', None)

        if t0_date is None:
            return None

        if not isinstance(t0_date, pd.Timestamp):
            t0_date = pd.Timestamp(t0_date)

        # t0.utc is the timing zero (t0_date) - when session_time=0
        t0_utc_str = t0_date.isoformat()

        # Get session scheduled start (warmup start) from f1_session.date
        warmup_start_offset = None
        session_start = getattr(f1_session, 'date', None)
        if session_start is not None:
            if not isinstance(session_start, pd.Timestamp):
                session_start = pd.Timestamp(session_start)
            # warmup_start_offset = seconds from t0 to session scheduled start
            warmup_start_offset = (session_start - t0_date).total_seconds()

        # Extract lights_out_offset from lap data
        lights_out_offset = self._extract_lights_out_offset(laps_df, t0_date)

        # Calculate session_duration from telemetry (if available)
        session_duration = 0.0
        if telemetry:
            max_time = 0.0
            min_time = float('inf')
            for df in telemetry.values():
                if 'session_time' in df.columns and len(df) > 0:
                    max_time = max(max_time, df['session_time'].max())
                    min_time = min(min_time, df['session_time'].min())
            if min_time != float('inf'):
                session_duration = max_time - min_time

        # Extract timezone from event
        timezone_str = ""
        utc_offset = 0.0
        try:
            event = getattr(f1_session, 'event', None)
            if event is not None:
                country = getattr(event, 'Country', '')
                location = getattr(event, 'Location', '')

                TIMEZONE_MAP = {
                    'Bahrain': ('Asia/Bahrain', 3.0),
                    'Saudi Arabia': ('Asia/Riyadh', 3.0),
                    'Australia': ('Australia/Melbourne', 11.0),
                    'Japan': ('Asia/Tokyo', 9.0),
                    'China': ('Asia/Shanghai', 8.0),
                    'United States': ('America/Chicago', -6.0),
                    'Miami': ('America/New_York', -5.0),
                    'Las Vegas': ('America/Los_Angeles', -8.0),
                    'Austin': ('America/Chicago', -6.0),
                    'Monaco': ('Europe/Monaco', 2.0),
                    'Spain': ('Europe/Madrid', 2.0),
                    'Canada': ('America/Toronto', -5.0),
                    'Austria': ('Europe/Vienna', 2.0),
                    'Great Britain': ('Europe/London', 1.0),
                    'UK': ('Europe/London', 1.0),
                    'Hungary': ('Europe/Budapest', 2.0),
                    'Belgium': ('Europe/Brussels', 2.0),
                    'Netherlands': ('Europe/Amsterdam', 2.0),
                    'Italy': ('Europe/Rome', 2.0),
                    'Singapore': ('Asia/Singapore', 8.0),
                    'Mexico': ('America/Mexico_City', -6.0),
                    'Brazil': ('America/Sao_Paulo', -3.0),
                    'Qatar': ('Asia/Qatar', 3.0),
                    'United Arab Emirates': ('Asia/Dubai', 4.0),
                    'Abu Dhabi': ('Asia/Dubai', 4.0),
                    'Azerbaijan': ('Asia/Baku', 4.0),
                }
                for key in [country, location]:
                    if key in TIMEZONE_MAP:
                        timezone_str, utc_offset = TIMEZONE_MAP[key]
                        break
        except Exception:
            pass

        return T0Info(
            utc=t0_utc_str,
            timezone=timezone_str,
            utc_offset_hours=utc_offset,
            warmup_start_offset=warmup_start_offset,
            lights_out_offset=lights_out_offset,
            session_duration=session_duration
        )

    def _extract_lights_out_offset(self, laps_df, t0_date: pd.Timestamp) -> Optional[float]:
        """
        Extract lights out time (race start) from lap data.

        Lights out = when lap 1 starts (LapStartTime for lap 1).

        Args:
            laps_df: FastF1 laps DataFrame
            t0_date: Timing system zero point

        Returns:
            Seconds from t0_date to lights out, or None if not available
        """
        if laps_df is None or len(laps_df) == 0:
            return None

        try:
            # Find first lap 1 entry (any driver)
            lap1_data = laps_df[laps_df['LapNumber'] == 1]
            if len(lap1_data) == 0:
                return None

            # LapStartTime is when the lap started (lights out for lap 1)
            lap_start = lap1_data['LapStartTime'].min()
            if pd.notna(lap_start):
                # LapStartTime is timedelta from t0_date
                if hasattr(lap_start, 'total_seconds'):
                    # It's a timedelta - convert to seconds
                    return lap_start.total_seconds()
                else:
                    # It's an absolute timestamp - calculate offset
                    lap_start_ts = pd.Timestamp(lap_start)
                    return (lap_start_ts - t0_date).total_seconds()
        except Exception:
            pass

        return None

    def _add_synthetic_events(self, track_status_list: list, t0_info) -> list:
        """
        Add synthetic events to track status: Session Start and Lights Out.

        Args:
            track_status_list: Existing track status events
            t0_info: Time reference (contains warmup_start_offset and lights_out_offset)

        Returns:
            Track status list with synthetic events added
        """
        from f1_replay.models.session import TrackStatusEvent

        # Add "Start of Session" event (WARM UP)
        if t0_info and t0_info.warmup_start_offset is not None:
            track_status_list.append(TrackStatusEvent(
                session_time=t0_info.warmup_start_offset,
                status="SessionStart",
                message="Start of Session",
                scope="Track",
                sector=None,
                driver_num=""
            ))

        # Add "Lights Out" event (RACE START)
        if t0_info and t0_info.lights_out_offset is not None:
            track_status_list.append(TrackStatusEvent(
                session_time=t0_info.lights_out_offset,
                status="LightsOut",
                message="",
                scope="Track",
                sector=None,
                driver_num=""
            ))

        return track_status_list

    def _integrate_rain_events(self, track_status_list: list, weather_df: pl.DataFrame) -> list:
        """
        Add rain events to track status.

        Uses WeatherExtractor.extract_rain_events() to find rain periods,
        then adds "RainStart" and "RainEnd" events to track status.

        Args:
            track_status_list: Existing track status events
            weather_df: Weather DataFrame with rainfall data

        Returns:
            Track status list with rain events added
        """
        from f1_replay.loaders.session.weather import WeatherExtractor
        from f1_replay.models.session import TrackStatusEvent

        if weather_df is None or weather_df.height == 0:
            return track_status_list

        # Extract rain periods
        rain_events = WeatherExtractor.extract_rain_events(weather_df)

        if rain_events is None or rain_events.height == 0:
            return track_status_list

        # Add rain events to track status (as intervals with end_time already set)
        for row in rain_events.iter_rows(named=True):
            # Create Rain interval directly with start and end time
            track_status_list.append(TrackStatusEvent(
                session_time=row["start_time"],
                status="Rain",
                message="RAIN REPORTED",
                scope="Track",
                sector=None,
                driver_num="",
                end_time=row["end_time"]
            ))

        return track_status_list

    def _consolidate_track_status_intervals(self, track_status_list: list, t0_info) -> tuple[list, dict]:
        """
        Consolidate discrete track status events into intervals with start/end times.

        Transformations:
        - WARM UP (SessionStart) -> starts at warmup_start_offset, ends at lights_out_offset
        - Yellow/DoubleYellow in sector -> starts at event, ends at AllClear in that sector
        - SafetyCar -> starts at deployment, ends at AllClear
        - SCEnding -> starts at announcement, ends at AllClear
        - Rain events already have intervals (start_time in message)

        Args:
            track_status_list: Sorted list of track status events
            t0_info: Time reference for getting lights_out_offset

        Returns:
            Tuple of (intervals list, consolidation report dict)
        """
        from f1_replay.models.session import TrackStatusEvent

        intervals = []
        open_statuses = {}  # Key: (scope, sector, status) -> event
        report = {
            'total_input_events': len(track_status_list),
            'total_output_intervals': 0,
            'merged_intervals': [],
            'instant_events': [],
            'ongoing_intervals': []
        }

        for event in track_status_list:
            scope = event.scope or "Track"
            sector = event.sector
            status = event.status

            # Handle WARM UP (SessionStart / FormationLap opens, AbortedStart / LightsOut closes)
            if status == "SessionStart" or status == "FormationLap":
                # Open a new WarmUp interval
                key = ("Track", None, "WarmUp")
                open_statuses[key] = TrackStatusEvent(
                    session_time=event.session_time,
                    status="WarmUp",
                    message="FORMATION LAP STARTED",
                    scope="Track",
                    sector=None,
                    driver_num="",
                    end_time=None
                )
                continue

            # Handle AbortedStart - closes current WarmUp (but doesn't add as discrete event)
            if status == "AbortedStart":
                key = ("Track", None, "WarmUp")
                if key in open_statuses:
                    start_event = open_statuses.pop(key)
                    warmup_interval = TrackStatusEvent(
                        session_time=start_event.session_time,                        status="WarmUp",
                        message=start_event.message,
                            scope="Track",
                        sector=None,
                        driver_num="",                        end_time=event.session_time
                    )
                    intervals.append(warmup_interval)
                    report['merged_intervals'].append({
                        'type': 'WarmUp',
                        'start_event': start_event.message,
                        'end_event': 'AbortedStart',
                        'start_time': start_event.session_time,
                        'end_time': event.session_time,
                        'duration': event.session_time - start_event.session_time
                    })

                # Add AbortedStart as instant event
                intervals.append(event)
                report['instant_events'].append({
                    'status': 'AbortedStart',
                    'time': event.session_time,
                    'message': event.message
                })
                continue

            # Handle LightsOut - closes WarmUp and adds as instant event
            if status == "LightsOut":
                # Close any open WarmUp
                key = ("Track", None, "WarmUp")
                if key in open_statuses:
                    start_event = open_statuses.pop(key)
                    warmup_interval = TrackStatusEvent(
                        session_time=start_event.session_time,                        status="WarmUp",
                        message=start_event.message,
                            scope="Track",
                        sector=None,
                        driver_num="",                        end_time=event.session_time
                    )
                    intervals.append(warmup_interval)
                    report['merged_intervals'].append({
                        'type': 'WarmUp',
                        'start_event': start_event.message,
                        'end_event': 'LightsOut',
                        'start_time': start_event.session_time,
                        'end_time': event.session_time,
                        'duration': event.session_time - start_event.session_time
                    })

                # Add LightsOut as instant event
                intervals.append(event)
                report['instant_events'].append({
                    'status': 'LightsOut',
                    'time': event.session_time,
                    'message': event.message
                })
                continue

            # Handle AllClear - closes all open statuses in this scope/sector
            if status == "AllClear":
                # Close sector-specific statuses
                if sector is not None:
                    keys_to_close = [k for k in open_statuses.keys() if k[0] == scope and k[1] == sector]
                else:
                    # Track-wide clear closes everything in this scope
                    keys_to_close = [k for k in open_statuses.keys() if k[0] == scope]

                for key in keys_to_close:
                    start_event = open_statuses.pop(key)
                    closed_interval = TrackStatusEvent(
                        session_time=start_event.session_time,                        status=start_event.status,
                        message=start_event.message,
                            scope=start_event.scope,
                        sector=start_event.sector,
                        driver_num=start_event.driver_num,                        end_time=event.session_time
                    )
                    intervals.append(closed_interval)
                    report['merged_intervals'].append({
                        'type': start_event.status,
                        'start_event': start_event.status,
                        'end_event': 'AllClear',
                        'start_time': start_event.session_time,
                        'end_time': event.session_time,
                        'duration': event.session_time - start_event.session_time,
                        'sector': start_event.sector
                    })
                continue

            # Handle Rain events - already come as intervals with end_time set
            if status == "Rain":
                # Rain intervals are pre-consolidated, just add to intervals
                intervals.append(event)
                report['merged_intervals'].append({
                    'type': 'Rain',
                    'start_event': 'Rain',
                    'end_event': 'Rain',
                    'start_time': event.session_time,
                    'end_time': event.end_time,
                    'duration': event.end_time - event.session_time if event.end_time else 0
                })
                continue

            # Handle Chequered flag - instant event
            if status == "Chequered":
                intervals.append(event)
                report['instant_events'].append({
                    'status': 'Chequered',
                    'time': event.session_time,
                    'message': event.message
                })
                # Close all open statuses at chequered flag
                for start_event in open_statuses.values():
                    closed_interval = TrackStatusEvent(
                        session_time=start_event.session_time,                        status=start_event.status,
                        message=start_event.message,
                            scope=start_event.scope,
                        sector=start_event.sector,
                        driver_num=start_event.driver_num,                        end_time=event.session_time
                    )
                    intervals.append(closed_interval)
                    report['merged_intervals'].append({
                        'type': start_event.status,
                        'start_event': start_event.status,
                        'end_event': 'Chequered',
                        'start_time': start_event.session_time,
                        'end_time': event.session_time,
                        'duration': event.session_time - start_event.session_time,
                        'sector': start_event.sector,
                        'note': 'Closed at Chequered flag'
                    })
                open_statuses.clear()
                continue

            # Handle Blue flags and Black/White flags - discrete events (not intervals)
            # Each blue flag shown is a separate warning and should not be merged
            if status in ("Blue", "BlackWhite"):
                intervals.append(event)
                report['instant_events'].append({
                    'status': status,
                    'time': event.session_time,
                    'message': event.message
                })
                continue

            # All other statuses (Yellow, DoubleYellow, Red, SafetyCar, SCEnding, VSC, etc.)
            # Open a new interval
            key = (scope, sector, status)
            open_statuses[key] = event

        # Close any remaining open statuses (end_time = None means ongoing)
        for start_event in open_statuses.values():
            ongoing_interval = TrackStatusEvent(
                session_time=start_event.session_time,                status=start_event.status,
                message=start_event.message,
                            scope=start_event.scope,
                sector=start_event.sector,
                driver_num=start_event.driver_num,                end_time=None  # Ongoing
            )
            intervals.append(ongoing_interval)
            report['ongoing_intervals'].append({
                'type': start_event.status,
                'start_time': start_event.session_time,
                'sector': start_event.sector,
                'note': 'Never closed (ongoing or session ended)'
            })

        # Finalize report
        report['total_output_intervals'] = len(intervals)
        report['summary'] = {
            'merged_count': len(report['merged_intervals']),
            'instant_count': len(report['instant_events']),
            'ongoing_count': len(report['ongoing_intervals']),
            'reduction': f"{report['total_input_events']} events → {report['total_output_intervals']} intervals"
        }

        return intervals, report

    def _build_events(self, f1_session, t0_info=None) -> EventsData:
        """
        Build events data (track status and race control messages).

        All event times are normalized to t0_date (FastF1's timing zero), consistent
        with telemetry session_time. Use T0Info.lights_out_offset to convert to race_time.

        Weather data is built temporarily for rain event extraction but NOT stored.
        Rain events are integrated directly into track_status.

        Synthetic events (SessionStart, LightsOut) are added to track_status.

        IMPORTANT: FastF1 time references:
        - t0_date: Timing system zero point (session_time=0 in telemetry)
        - track_status.Time: timedeltas from t0_date
        - race_control_messages.Time: absolute timestamps (need conversion)

        Args:
            f1_session: FastF1 session object
            t0_info: Time reference (for synthetic events)
        """
        t0_date = getattr(f1_session, 't0_date', None)

        # Convert t0_date to timestamp for absolute time conversions
        t0_datetime = None
        if t0_date is not None:
            if not isinstance(t0_date, pd.Timestamp):
                t0_date = pd.Timestamp(t0_date)
            t0_datetime = t0_date

        # Extract events - all session_time values relative to t0_date
        track_status_list = self._extract_track_status(f1_session, t0_datetime, t0_info)
        race_control_list = self._extract_race_control_messages(f1_session, t0_datetime)
        status_messages_list = self._extract_status_messages(f1_session, t0_datetime, t0_info)
        weather_list = self._extract_weather_data(f1_session, t0_datetime)

        # Build weather DataFrame temporarily for rain extraction (not stored)
        weather_df = pl.DataFrame([
            {
                'temperature': sample.temperature,
                'humidity': sample.humidity,
                'wind_speed': sample.wind_speed,
                'wind_direction': sample.wind_direction,
                'track_temperature': sample.track_temperature,
                'rainfall': sample.rainfall,
                'time': sample.time,
                'session_time': sample.session_time
            }
            for sample in weather_list
        ]) if weather_list else pl.DataFrame()

        # Add synthetic events (SessionStart, LightsOut) to track status
        track_status_list = self._add_synthetic_events(track_status_list, t0_info)

        # Integrate rain events into track status
        track_status_list = self._integrate_rain_events(track_status_list, weather_df)

        # Sort track status by session_time
        track_status_list = sorted(track_status_list, key=lambda e: e.session_time if e.session_time is not None else float('inf'))

        # Consolidate discrete events into intervals with start/end times
        track_status_list, consolidation_report = self._consolidate_track_status_intervals(track_status_list, t0_info)

        # Convert lists to Polars DataFrames for efficient storage and querying
        track_status_df = pl.DataFrame([
            {
                'session_time': event.session_time,
                'status': event.status,
                'message': event.message,
                'scope': event.scope,
                'sector': event.sector,
                'driver_num': event.driver_num,
                'end_time': event.end_time
            }
            for event in track_status_list
        ]) if track_status_list else pl.DataFrame()

        # Sort by session_time to ensure chronological order after consolidation
        if track_status_df.height > 0:
            track_status_df = track_status_df.sort('session_time')

        # Wrap DataFrame with consolidation report
        from f1_replay.models.session import TrackStatusWithReport
        track_status_with_report = TrackStatusWithReport(track_status_df, consolidation_report)

        race_control_df = pl.DataFrame([
            {
                'message': msg.message,
                'time': msg.time,
                'session_time': msg.session_time
            }
            for msg in race_control_list
        ]) if race_control_list else pl.DataFrame()

        status_messages_df = pl.DataFrame(status_messages_list) if status_messages_list else pl.DataFrame()

        if track_status_list or race_control_list:
            print(f"  → Events: {len(track_status_list)} track status intervals ({consolidation_report['summary']['merged_count']} merged), {len(race_control_list)} messages, {len(status_messages_list)} status subtitles")

        return EventsData(
            track_status=track_status_with_report,
            race_control=race_control_df,
            status_messages=status_messages_df
        )

    def _extract_track_status(self, f1_session, t0_datetime=None, t0_info: T0Info = None) -> list[TrackStatusEvent]:
        """
        Extract unified track status from both session.track_status AND race_control_messages.

        All session_time values are relative to t0_date (FastF1's timing zero),
        consistent with telemetry. Use T0Info.lights_out_offset to convert to race_time.

        Priority:
        - race_control_messages[Category='SafetyCar']: SC/VSC with human-readable messages
        - race_control_messages[Category='Flag']: Yellow/Green flags with sector info
        - session.track_status: Red flags, global status (NOT SC/VSC to avoid duplicates)

        Returns list sorted by session_time.
        """
        events = []

        # Status code to human-readable mapping (from session.track_status)
        # Skip SC/VSC (codes 4, 6, 7) - we get better data from race_control_messages
        STATUS_MAP = {
            '1': 'AllClear',
            '2': 'Yellow',
            '3': 'Unknown',
            '5': 'Red',
        }

        # Flag type to status mapping (from race_control_messages)
        FLAG_TO_STATUS = {
            'YELLOW': 'Yellow',
            'DOUBLE YELLOW': 'DoubleYellow',
            'GREEN': 'AllClear',
            'CLEAR': 'AllClear',
            'RED': 'Red',
            'RED FLAG': 'Red',
            'BLUE': 'Blue',
            'BLACK AND WHITE': 'BlackWhite',
            'BLACK WHITE': 'BlackWhite',
            'CHEQUERED': 'Chequered',
        }

        # =====================================================================
        # 1. Extract from session.track_status
        # track_status.Time is timedelta from t0_date - use directly (no offset!)
        # =====================================================================
        try:
            if hasattr(f1_session, 'track_status') and f1_session.track_status is not None:
                ts_df = f1_session.track_status
                for _, row in ts_df.iterrows():
                    try:
                        status_code = str(row.get('Status', ''))

                        # Skip Yellow/Red/SC/VSC codes - we get better data from race_control_messages
                        if status_code in ('2', '4', '5', '6', '7'):
                            continue

                        message = row.get('Message', '')
                        status = STATUS_MAP.get(status_code)
                        if status is None:
                            continue  # Skip unknown status codes

                        # Parse time - timedelta from t0_date, use directly
                        time_value = row.get('Time', None)
                        if time_value is not None and hasattr(time_value, 'total_seconds'):
                            session_time = time_value.total_seconds()
                        else:
                            session_time = self._parse_time_to_session_seconds(time_value, None, t0_datetime)

                        events.append(TrackStatusEvent(
                            session_time=session_time,
                            status=status,
                            message=str(message) if pd.notna(message) else status,
                            scope="Track",
                            sector=None,
                            driver_num=""
                        ))
                    except Exception:
                        pass
        except Exception:
            pass

        # =====================================================================
        # 2. Extract from race_control_messages (flags AND safety car)
        # =====================================================================
        try:
            messages_df = None
            if hasattr(f1_session, 'race_control_messages') and f1_session.race_control_messages is not None:
                messages_df = f1_session.race_control_messages
            elif hasattr(f1_session, 'messages') and f1_session.messages is not None:
                messages_df = f1_session.messages

            if messages_df is not None and len(messages_df) > 0 and 'Category' in messages_df.columns:
                # Extract Flag messages
                flag_messages = messages_df[messages_df['Category'] == 'Flag']

                for _, row in flag_messages.iterrows():
                    try:
                        flag_type = str(row.get('Flag', '')).upper()
                        message = str(row.get('Message', ''))
                        message_upper = message.upper()

                        # GREEN LIGHT - PIT EXIT OPEN indicates formation lap start
                        # This is the actual start signal, not the "FORMATION LAP" announcement
                        if 'GREEN LIGHT' in message_upper and 'PIT EXIT OPEN' in message_upper:
                            time_value = row.get('Time', None)
                            session_time = self._parse_time_to_session_seconds(time_value, None, t0_datetime)
                            events.append(TrackStatusEvent(
                                session_time=session_time,
                                status='FormationLap',
                                message=message,
                                scope="Track",
                                sector=None,
                                driver_num=""
                            ))
                            continue

                        # Clean up blue flag messages - remove "TIMED AT..." suffix
                        if 'BLUE FLAG' in message_upper and 'TIMED AT' in message_upper:
                            # Find "TIMED AT" and remove everything from that point
                            timed_at_pos = message.upper().find('TIMED AT')
                            if timed_at_pos > 0:
                                message = message[:timed_at_pos].strip()

                        scope = str(row.get('Scope', 'Track'))
                        sector = int(row.get('Sector')) if pd.notna(row.get('Sector')) else None
                        driver_num = str(row.get('RacingNumber', '')) if pd.notna(row.get('RacingNumber')) else ''

                        # Parse time - absolute timestamp, convert to t0-relative
                        time_value = row.get('Time', None)
                        session_time = self._parse_time_to_session_seconds(time_value, None, t0_datetime)

                        # Map flag to status
                        status = FLAG_TO_STATUS.get(flag_type, 'Flag')

                        events.append(TrackStatusEvent(
                            session_time=session_time,
                            status=status,
                            message=message,
                            scope=scope,
                            sector=sector,
                            driver_num=driver_num
                        ))
                    except Exception:
                        pass

                # =====================================================================
                # 3. Extract SafetyCar/VSC from race_control_messages
                # =====================================================================
                sc_messages = messages_df[messages_df['Category'] == 'SafetyCar']

                for _, row in sc_messages.iterrows():
                    try:
                        message = str(row.get('Message', ''))
                        message_upper = message.upper()

                        # Parse time - absolute timestamp, convert to t0-relative
                        time_value = row.get('Time', None)
                        session_time = self._parse_time_to_session_seconds(time_value, None, t0_datetime)

                        # Determine SC/VSC type from message
                        if 'VIRTUAL' in message_upper or 'VSC' in message_upper:
                            if 'ENDING' in message_upper:
                                status = 'VSCEnding'
                            else:
                                status = 'VSC'
                        elif 'SAFETY CAR' in message_upper or 'SC ' in message_upper:
                            if 'IN THIS LAP' in message_upper:
                                status = 'SCEnding'  # SC coming in
                            else:
                                status = 'SafetyCar'
                        else:
                            status = 'SafetyCar'  # Default for Category=SafetyCar

                        events.append(TrackStatusEvent(
                            session_time=session_time,
                            status=status,
                            message=message,
                            scope="Track",
                            sector=None,
                            driver_num=""
                        ))
                    except Exception:
                        pass

                # =====================================================================
                # 4. Extract Aborted Start / Formation Lap from race_control_messages
                # =====================================================================
                # These are in "Other" category
                other_messages = messages_df[messages_df['Category'] == 'Other']

                for _, row in other_messages.iterrows():
                    try:
                        message = str(row.get('Message', ''))
                        message_upper = message.upper()

                        # Check for ABORTED START
                        if 'ABORTED START' in message_upper:
                            time_value = row.get('Time', None)
                            session_time = self._parse_time_to_session_seconds(time_value, None, t0_datetime)

                            events.append(TrackStatusEvent(
                                session_time=session_time,
                                status='AbortedStart',
                                message=message,
                                scope="Track",
                                sector=None,
                                driver_num=""
                            ))

                        # Check for FORMATION LAP - parse actual start time from message
                        # Message format: "FORMATION LAP WILL START AT HH:MM"
                        elif 'FORMATION LAP' in message_upper and 'WILL START AT' in message_upper:
                            import re
                            # Extract HH:MM from message (this is LOCAL time)
                            time_match = re.search(r'WILL START AT\s*(\d{1,2}):(\d{2})', message_upper)
                            if time_match and t0_datetime is not None:
                                local_hour = int(time_match.group(1))
                                local_minute = int(time_match.group(2))

                                # Convert local time to UTC by subtracting offset
                                utc_offset_hours = t0_info.utc_offset_hours if t0_info else 0
                                utc_hour = local_hour - int(utc_offset_hours)
                                utc_minute = local_minute - int((utc_offset_hours % 1) * 60)

                                # Handle hour/minute overflow
                                if utc_minute < 0:
                                    utc_minute += 60
                                    utc_hour -= 1
                                if utc_hour < 0:
                                    utc_hour += 24

                                # Build the actual start timestamp using t0_datetime's date
                                start_datetime = t0_datetime.replace(
                                    hour=utc_hour, minute=utc_minute, second=0, microsecond=0
                                )
                                # Handle day rollover (if start time is before t0)
                                if start_datetime < t0_datetime:
                                    start_datetime += pd.Timedelta(days=1)
                                session_time = (start_datetime - t0_datetime).total_seconds()

                                events.append(TrackStatusEvent(
                                    session_time=session_time,
                                    status='FormationLap',
                                    message=message,
                                    scope="Track",
                                    sector=None,
                                    driver_num=""
                                ))
                    except Exception:
                        pass

        except Exception:
            pass

        # Sort by session_time
        events.sort(key=lambda e: e.session_time)

        # Filter out post-race events (after chequered flag)
        # FastF1 sometimes includes track_status data from after the race ends
        chequered_time = None
        for e in events:
            if e.status == 'Chequered':
                chequered_time = e.session_time
                break

        if chequered_time is not None:
            # Keep all events up to and including chequered, filter out anything after
            events = [e for e in events if e.session_time <= chequered_time + 60]  # +60s buffer

        return events

    def _parse_time_to_session_seconds(self, time_value, t0_seconds_of_day: Optional[float],
                                        t0_datetime) -> float:
        """Parse FastF1 time value to session-relative seconds."""
        if time_value is None:
            return 0.0

        try:
            if hasattr(time_value, 'total_seconds'):
                # Timedelta - already relative to session start
                return time_value.total_seconds()
            elif isinstance(time_value, pd.Timestamp):
                # Absolute timestamp
                if t0_datetime is not None:
                    return (time_value - t0_datetime).total_seconds()
                elif t0_seconds_of_day is not None:
                    time_float = time_value.hour * 3600 + time_value.minute * 60 + time_value.second + time_value.microsecond / 1e6
                    return time_float - t0_seconds_of_day
                return 0.0
            else:
                return float(time_value)
        except Exception:
            return 0.0

    def _extract_race_control_messages(self, f1_session, t0_datetime=None) -> list[RaceControlMessage]:
        """Extract race control messages (normalized to t0_date)."""
        messages = []

        try:
            messages_df = None
            if hasattr(f1_session, 'race_control_messages') and f1_session.race_control_messages is not None:
                messages_df = f1_session.race_control_messages
            elif hasattr(f1_session, 'messages') and f1_session.messages is not None:
                messages_df = f1_session.messages

            if messages_df is None or len(messages_df) == 0:
                return messages

            # Filter for race control messages (FastF1 uses 'Other' for race control)
            if 'Category' in messages_df.columns:
                rc_messages = messages_df[messages_df['Category'] == 'Other']

                import re
                for _, row in rc_messages.iterrows():
                    try:
                        message_text = row.get('Message', '')
                        message_upper = str(message_text).upper() if pd.notna(message_text) else ''

                        # Skip messages already handled by track_status (single source of truth)
                        if any(pattern in message_upper for pattern in self.TRACK_STATUS_MESSAGE_PATTERNS):
                            continue

                        # Skip messages with timestamps (AT HH:MM) - these become status subtitles
                        if re.search(self.TIMESTAMP_MESSAGE_PATTERN, message_upper):
                            continue
                        time_value = row.get('Time', None)
                        time_float = 0.0
                        session_time = 0.0

                        if time_value is not None:
                            try:
                                if isinstance(time_value, pd.Timestamp):
                                    time_float = time_value.hour * 3600 + time_value.minute * 60 + time_value.second + time_value.microsecond / 1e6
                                    if t0_datetime is not None:
                                        session_time = (time_value - t0_datetime).total_seconds()
                                elif hasattr(time_value, 'total_seconds'):
                                    time_float = time_value.total_seconds()
                                    session_time = time_float
                                else:
                                    time_float = float(time_value)
                                    session_time = time_float
                            except:
                                pass

                        messages.append(RaceControlMessage(
                            message=str(message_text) if pd.notna(message_text) else '',
                            time=time_float,
                            session_time=session_time
                        ))
                    except Exception:
                        pass

        except Exception:
            pass  # Return empty if extraction fails

        return messages

    def _extract_status_messages(self, f1_session, t0_datetime=None, t0_info=None) -> list[dict]:
        """
        Extract status messages with timestamps (e.g., "RACE WILL START AT 12:47").

        These become status subtitles displayed below track status pills.
        The time in the message is local time - we use utc_offset_hours to convert to UTC.

        Returns list of dicts with: session_time, end_time, message
        """
        import re
        messages = []

        try:
            messages_df = None
            if hasattr(f1_session, 'race_control_messages') and f1_session.race_control_messages is not None:
                messages_df = f1_session.race_control_messages
            elif hasattr(f1_session, 'messages') and f1_session.messages is not None:
                messages_df = f1_session.messages

            if messages_df is None or len(messages_df) == 0:
                return messages

            # Get UTC offset (message times are in local time)
            utc_offset_hours = t0_info.utc_offset_hours if t0_info else 0

            if 'Category' in messages_df.columns:
                # Only process "Other" category messages
                other_messages = messages_df[messages_df['Category'] == 'Other']

                for _, row in other_messages.iterrows():
                    try:
                        message_text = row.get('Message', '')
                        message_str = str(message_text) if pd.notna(message_text) else ''
                        message_upper = message_str.upper()

                        # Match "AT HH:MM" pattern
                        match = re.search(self.TIMESTAMP_MESSAGE_PATTERN, message_upper)
                        if match and t0_datetime is not None:
                            # Parse announcement time
                            time_value = row.get('Time', None)
                            session_time = self._parse_time_to_session_seconds(time_value, None, t0_datetime)

                            # Parse target time from message (this is LOCAL time)
                            time_match = re.search(r'AT\s+(\d{1,2}):(\d{2})', message_upper)
                            if time_match:
                                local_hour = int(time_match.group(1))
                                local_minute = int(time_match.group(2))

                                # Convert local time to UTC by subtracting offset
                                # Then build target datetime using t0_datetime's date (which is UTC)
                                utc_hour = local_hour - int(utc_offset_hours)
                                utc_minute = local_minute - int((utc_offset_hours % 1) * 60)

                                # Handle hour/minute overflow
                                if utc_minute < 0:
                                    utc_minute += 60
                                    utc_hour -= 1
                                if utc_hour < 0:
                                    utc_hour += 24

                                target_datetime = t0_datetime.replace(
                                    hour=utc_hour, minute=utc_minute, second=0, microsecond=0
                                )
                                # Handle day rollover
                                if target_datetime < t0_datetime:
                                    target_datetime += pd.Timedelta(days=1)

                                end_time = (target_datetime - t0_datetime).total_seconds()

                                messages.append({
                                    'session_time': session_time,
                                    'end_time': end_time,
                                    'message': message_str
                                })
                    except Exception:
                        pass

        except Exception:
            pass

        return messages

    def _extract_weather_data(self, f1_session, t0_datetime=None) -> list[WeatherSample]:
        """Extract weather samples from session (normalized to t0_date)."""
        weather_samples = []

        try:
            weather_df = None
            if hasattr(f1_session, 'weather_data') and f1_session.weather_data is not None:
                weather_df = f1_session.weather_data
            elif hasattr(f1_session, 'weather') and f1_session.weather is not None:
                weather_df = f1_session.weather

            if weather_df is None or len(weather_df) == 0:
                return weather_samples

            for _, row in weather_df.iterrows():
                try:
                    time_value = row.get('Time', None)
                    time_float = 0.0
                    session_time = 0.0

                    if time_value is not None:
                        try:
                            if isinstance(time_value, pd.Timestamp):
                                time_float = time_value.hour * 3600 + time_value.minute * 60 + time_value.second + time_value.microsecond / 1e6
                                if t0_datetime is not None:
                                    session_time = (time_value - t0_datetime).total_seconds()
                            elif hasattr(time_value, 'total_seconds'):
                                time_float = time_value.total_seconds()
                                session_time = time_float
                            else:
                                time_float = float(time_value)
                                session_time = time_float
                        except:
                            pass

                    # Extract weather fields - try multiple field name variations
                    # FastF1 uses different column names in different versions
                    temp = row.get('AirTemp', row.get('Air Temp', 0.0))
                    track_temp = row.get('TrackTemp', row.get('Track Temp', 0.0))
                    humidity = row.get('Humidity', 0.0)
                    wind_speed = row.get('WindSpeed', row.get('Wind Speed', 0.0))
                    wind_direction = row.get('WindDirection', row.get('Wind Direction', None))
                    rainfall = row.get('Rainfall', False)

                    # Convert to numbers
                    temp = float(temp) if pd.notna(temp) else 0.0
                    track_temp = float(track_temp) if pd.notna(track_temp) else 0.0
                    humidity = float(humidity) if pd.notna(humidity) else 0.0
                    wind_speed = float(wind_speed) if pd.notna(wind_speed) else 0.0
                    rainfall = bool(rainfall) if pd.notna(rainfall) else False

                    weather_samples.append(WeatherSample(
                        temperature=temp,
                        humidity=humidity,
                        wind_speed=wind_speed,
                        wind_direction=str(wind_direction) if pd.notna(wind_direction) else None,
                        track_temperature=track_temp,
                        rainfall=rainfall,
                        time=time_float,
                        session_time=session_time
                    ))
                except Exception:
                    pass  # Skip malformed entries

        except Exception:
            pass  # Return empty if extraction fails

        return weather_samples

    def _build_results(self, f1_session, telemetry: Dict[str, pl.DataFrame] = None, true_t0: Optional[str] = None) -> ResultsData:
        """
        Build results data (fastest laps, position history).

        Args:
            f1_session: FastF1 session
            telemetry: Normalized telemetry dict with 'session_time' column (for extracting accurate event times)
            true_t0: Session start time (for calculating session end time)

        Extracts:
        - Fastest lap progression
        - Position snapshots at intervals
        """
        # Verify telemetry has session_time column
        if telemetry:
            first_driver = list(telemetry.keys())[0] if telemetry else None
            if first_driver:
                first_tel = telemetry[first_driver]
                has_session_time = 'session_time' in first_tel.columns
                print(f"  → Building results with telemetry: {len(telemetry)} drivers, session_time={'✓' if has_session_time else '✗'}")

        fastest_laps = self._extract_fastest_laps(f1_session, telemetry)
        position_history = self._extract_position_history(f1_session, telemetry, true_t0)

        if fastest_laps or position_history:
            print(f"  → Results: {len(fastest_laps)} fastest laps, {len(position_history)} position snapshots")

        return ResultsData(
            fastest_laps=fastest_laps,
            position_history=position_history
        )

    def _extract_fastest_laps(self, f1_session, telemetry: Dict[str, pl.DataFrame] = None) -> list[FastestLapEvent]:
        """
        Extract chronological fastest lap changes with session_time from normalized telemetry.

        Args:
            f1_session: FastF1 session object
            telemetry: Normalized telemetry dict with 'session_time' column
        """
        fastest_laps = []

        try:
            if not hasattr(f1_session, 'laps') or f1_session.laps is None or len(f1_session.laps) == 0:
                return fastest_laps

            laps_df = f1_session.laps

            # Track overall fastest lap and when it was set
            current_fastest_time = float('inf')

            try:
                # Sort laps by lap number to process chronologically
                sorted_laps = laps_df.sort_values(['LapNumber']).reset_index(drop=True)

                # Process each lap in order
                for _, lap in sorted_laps.iterrows():
                    try:
                        lap_time_seconds = lap.get('LapTime', None)
                        driver = str(lap.get('Driver', ''))
                        lap_num = int(lap.get('LapNumber', 0))

                        # Only consider valid lap times
                        if lap_time_seconds is None or pd.isna(lap_time_seconds) or not driver:
                            continue

                        # Convert timedelta to seconds if needed
                        if hasattr(lap_time_seconds, 'total_seconds'):
                            lap_time_seconds = lap_time_seconds.total_seconds()
                        else:
                            lap_time_seconds = float(lap_time_seconds)

                        # Check if this is a new fastest lap
                        if lap_time_seconds < current_fastest_time:
                            current_fastest_time = lap_time_seconds

                            # Find session_time from normalized telemetry
                            session_time = 0.0
                            if telemetry and driver in telemetry:
                                try:
                                    driver_tel = telemetry[driver]
                                    if 'LapNumber' in driver_tel.columns and 'session_time' in driver_tel.columns:
                                        # Find the last point in this lap
                                        lap_rows = driver_tel.filter(pl.col('LapNumber') == lap_num)
                                        if len(lap_rows) > 0:
                                            # Get the session_time of the last point in this lap
                                            values = lap_rows['session_time'].to_list()
                                            if values:
                                                session_time = float(values[-1])
                                except Exception:
                                    pass

                            fastest_laps.append(FastestLapEvent(                                driver=driver,
                                time=lap_time_seconds,
                                lap_time_ms=int(lap_time_seconds * 1000),
                                session_time=session_time
                            ))

                    except Exception:
                        pass  # Skip if unable to extract lap info

            except Exception:
                pass  # If processing fails, return what we have

        except Exception:
            pass  # Return empty if extraction fails

        return fastest_laps

    def _calculate_session_end_time(self, telemetry: Dict[str, pl.DataFrame] = None,
                                     true_t0: Optional[str] = None) -> float:
        """
        Calculate session end time from telemetry data.

        Args:
            telemetry: Unnormalized telemetry dict with Date column
            true_t0: Session start time (ISO format)

        Returns:
            Session end time in seconds since session start, or 0 if unable to calculate
        """
        if not telemetry or not true_t0:
            return 0.0

        try:
            # Parse session start time
            if 'T' in true_t0:
                t0_dt = pd.Timestamp(true_t0.replace('Z', '+00:00'))
            else:
                t0_dt = pd.Timestamp(true_t0)

            # Find latest timestamp in any driver's telemetry
            max_time = None
            for driver_tel in telemetry.values():
                if 'Date' in driver_tel.columns and len(driver_tel) > 0:
                    last_date = driver_tel['Date'][-1]  # Last row
                    if last_date is not None and pd.notna(last_date):
                        if not isinstance(last_date, pd.Timestamp):
                            last_date = pd.Timestamp(last_date)
                        if max_time is None or last_date > max_time:
                            max_time = last_date

            if max_time is not None:
                # Calculate seconds since session start
                session_end_seconds = (max_time - t0_dt).total_seconds()
                return max(0.0, session_end_seconds)  # Ensure non-negative

        except Exception:
            pass

        return 0.0

    def _extract_position_history(self, f1_session, telemetry: Dict[str, pl.DataFrame] = None,
                                  true_t0: Optional[str] = None) -> list[PositionSnapshot]:
        """Extract position snapshots at regular intervals.

        Args:
            f1_session: FastF1 session
            telemetry: Unnormalized telemetry dict (for calculating session end time)
            true_t0: Session start time (for calculating session end time)
        """
        position_history = []

        try:
            if not hasattr(f1_session, 'laps') or f1_session.laps is None or len(f1_session.laps) == 0:
                return position_history

            # Try to get position data from results if available
            if hasattr(f1_session, 'results') and f1_session.results is not None:
                results_df = f1_session.results

                try:
                    # Create a snapshot from final results
                    standings = []

                    for idx, (_, row) in enumerate(results_df.iterrows()):
                        try:
                            position = int(row.get('Position', idx + 1))
                            driver = row.get('Abbreviation', 'UNK')
                            gap = row.get('Points', 0)  # Using points as a proxy for gap

                            standings.append(PositionEntry(
                                position=position,
                                driver=str(driver),
                                gap=float(gap) if pd.notna(gap) else 0.0
                            ))
                        except Exception:
                            pass  # Skip malformed entries

                    if standings:
                        # Calculate actual session end time from telemetry
                        session_end_time = self._calculate_session_end_time(telemetry, true_t0)
                        # Use nan if unable to calculate (serializer converts to None for valid JSON)
                        if session_end_time == 0.0:
                            session_end_time = float('nan')
                        # Add final standings snapshot at session end
                        position_history.append(PositionSnapshot(
                            time=session_end_time,                            standings=standings
                        ))

                except Exception:
                    pass  # If results extraction fails, return empty

        except Exception:
            pass  # Return empty if extraction fails

        return position_history
