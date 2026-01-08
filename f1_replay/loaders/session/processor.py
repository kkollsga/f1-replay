"""
Session Processor - TIER 3 Processing

Builds SessionData (telemetry, events, results) from FastF1.
Event times are normalized to session start (t0) automatically.
"""

from typing import Optional, Dict, Any
import datetime
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

    def __init__(self, fastf1_client: FastF1Client, circuit_length: float):
        """
        Initialize processor.

        Args:
            fastf1_client: FastF1Client instance
            circuit_length: Track length for metadata
        """
        self.fastf1_client = fastf1_client
        self.circuit_length = circuit_length

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
            race_control=renormalize_df(session_data.events.race_control),
            weather=renormalize_df(session_data.events.weather)
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
                        time=new_time,
                        lap=snapshot.lap,
                        standings=snapshot.standings
                    )
                    renormalized_positions.append(new_snapshot)

                renormalized_results = replace(
                    session_data.results,
                    position_history=renormalized_positions
                )

        # Re-normalize rain_events if present
        renormalized_rain_events = session_data.rain_events
        if session_data.rain_events and len(session_data.rain_events) > 0:
            renormalized_rain_list = []
            for rain_event in session_data.rain_events:
                # Rain events have start_time and end_time
                if hasattr(rain_event, 'start_time') and hasattr(rain_event, 'end_time'):
                    new_start = rain_event.start_time - race_start_time if rain_event.start_time is not None else rain_event.start_time
                    new_end = rain_event.end_time - race_start_time if rain_event.end_time is not None else rain_event.end_time
                    new_event = rain_event.__class__(
                        start_time=new_start,
                        end_time=new_end,
                        duration=rain_event.duration
                    )
                    renormalized_rain_list.append(new_event)
            if renormalized_rain_list:
                renormalized_rain_events = renormalized_rain_list

        # Create new SessionData with renormalized times
        return replace(
            session_data,
            telemetry=renormalized_telemetry,
            events=renormalized_events,
            results=renormalized_results,
            rain_events=renormalized_rain_events
        )

    def build_session(self, year: int, round_num: int,
                     session_type: str, event_name: str) -> Optional[tuple]:
        """
        Build complete session data with telemetry-first architecture.

        Processing order:
        1. Load metadata
        2. Build COMPLETE telemetry (with RawTime, session_time, progress, status, TimeToDriverAhead)
        3. Build events (track status, weather, race control)
        4. Build results (fastest laps, position history)
        5. Extract rain events

        Args:
            year: Season year
            round_num: Round number
            session_type: "FP1", "FP2", "FP3", "Q", "S", "R"
            event_name: Event name for metadata

        Returns:
            Tuple of (SessionData, raw_f1_session, track_data) or None if error
        """
        print(f"→ Loading session {year} R{round_num} {session_type}...")

        # Load session with all data
        f1_session = self.fastf1_client.get_session_with_all_data(year, round_num, session_type)
        if f1_session is None:
            return None

        # Extract DNF drivers from results BEFORE building telemetry
        # This ensures we correctly mark retired drivers even with bad telemetry data
        dnf_drivers_set = self._extract_dnf_drivers(f1_session)

        # Build telemetry from pos_data + car_data (compacted)
        print(f"  → Building telemetry from pos_data + car_data...")
        telemetry, track_data, session_timing = TelemetryBuilder.build_telemetry(f1_session, dnf_drivers=dnf_drivers_set)

        if not telemetry:
            print(f"  ⚠ No telemetry data available")
            return None

        # Update circuit_length from track_data if available
        # track_data.lap_distance is in decimeters, convert to meters
        if track_data:
            self.circuit_length = track_data.lap_distance / 10.0

        # Add position column to telemetry
        print(f"  → Adding positions to telemetry...")
        telemetry = OrderBuilder.add_positions_to_telemetry(telemetry)
        print(f"  ✓ Positions added to {len(telemetry)} drivers")

        # Add interval column to telemetry
        print(f"  → Adding intervals to telemetry...")
        telemetry = OrderBuilder.add_intervals_to_telemetry(telemetry)
        print(f"  ✓ Intervals added")

        # Build metadata (includes T0Info with duration calculated from telemetry)
        metadata = self._build_metadata(year, round_num, session_type, event_name, f1_session, telemetry, session_timing)

        # Build events (track status, weather, race control)
        # Uses session.date as reference for time normalization
        events = self._build_events(f1_session)

        # Build results (fastest laps, position history)
        t0_utc = metadata.t0.utc if metadata.t0 else None
        results = self._build_results(f1_session, telemetry, t0_utc)

        # Extract rain events from weather data
        rain_events = WeatherExtractor.extract_rain_events(events.weather)

        # Create final SessionData
        session_data = SessionData(
            metadata=metadata,
            telemetry=telemetry,
            events=events,
            results=results,
            rain_events=rain_events
        )

        if len(rain_events) > 0:
            print(f"  ✓ Extracted {len(rain_events)} rain event(s)")

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
                       event_name: str, f1_session, telemetry: Dict[str, pl.DataFrame],
                       session_timing: Optional[dict] = None) -> SessionMetadata:
        """Build session metadata."""
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

        # Build T0Info with all time conversion references (including warmup timing)
        t0_info = self._build_t0_info(f1_session, telemetry, session_timing)

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

    def _build_t0_info(self, f1_session, telemetry: Dict[str, pl.DataFrame],
                       session_timing: Optional[dict] = None) -> Optional[T0Info]:
        """
        Build T0Info with time reference for session normalization.

        t0.utc = FastF1's timing zero (t0_date) - the point where session_time=0
        lights_out_offset = seconds from t0 to lights out (positive value)
        warmup_start_offset = seconds from t0 to formation lap start (positive value)
        session_duration = total telemetry duration

        This means session_time directly matches FastF1's SessionTime (converted to seconds).
        To get race_time (relative to lights out): race_time = session_time - lights_out_offset
        """
        t0_date = getattr(f1_session, 't0_date', None)

        if t0_date is None:
            return None

        if not isinstance(t0_date, pd.Timestamp):
            t0_date = pd.Timestamp(t0_date)

        # t0.utc is the timing zero (t0_date) - when session_time=0
        t0_utc_str = t0_date.isoformat()

        # Find actual lights out time from lap data (when lap 1 starts)
        lights_out_time = None
        try:
            laps = getattr(f1_session, 'laps', None)
            if laps is not None and len(laps) > 0:
                # Find first lap 1 entry (any driver)
                lap1_data = laps[laps['LapNumber'] == 1]
                if len(lap1_data) > 0:
                    # LapStartTime is when the lap started (lights out for lap 1)
                    lap_start = lap1_data['LapStartTime'].min()
                    if pd.notna(lap_start):
                        # LapStartTime is timedelta from t0_date
                        if hasattr(lap_start, 'total_seconds'):
                            lights_out_time = t0_date + lap_start
                        else:
                            lights_out_time = pd.Timestamp(lap_start)
        except Exception:
            pass

        # Fallback to session.date if we couldn't find lap 1 start
        if lights_out_time is None:
            session_date = getattr(f1_session, 'date', None)
            if session_date is not None:
                lights_out_time = pd.Timestamp(session_date) if not isinstance(session_date, pd.Timestamp) else session_date
            else:
                # No lights out time available, use t0_date as fallback (offset=0)
                lights_out_time = t0_date

        # lights_out_offset = seconds from t0 to lights out (positive value)
        # race_time = session_time - lights_out_offset
        lights_out_offset = (lights_out_time - t0_date).total_seconds()

        # Calculate session_duration from telemetry
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

        # Extract warmup_start_offset from session_timing
        warmup_start_offset = None
        if session_timing:
            warmup_start_offset = session_timing.get('warmup_start_time')

        return T0Info(
            utc=t0_utc_str,
            timezone=timezone_str,
            utc_offset_hours=utc_offset,
            warmup_start_offset=warmup_start_offset,
            lights_out_offset=lights_out_offset,
            session_duration=session_duration
        )

    def _build_events(self, f1_session) -> EventsData:
        """
        Build events data (track status, weather, messages).

        All event times are normalized to t0_date (FastF1's timing zero), consistent
        with telemetry session_time. Use T0Info.lights_out_offset to convert to race_time.

        IMPORTANT: FastF1 time references:
        - t0_date: Timing system zero point (session_time=0 in telemetry)
        - track_status.Time: timedeltas from t0_date
        - race_control_messages.Time: absolute timestamps (need conversion)

        Args:
            f1_session: FastF1 session object
        """
        t0_date = getattr(f1_session, 't0_date', None)

        # Convert t0_date to timestamp for absolute time conversions
        t0_datetime = None
        if t0_date is not None:
            if not isinstance(t0_date, pd.Timestamp):
                t0_date = pd.Timestamp(t0_date)
            t0_datetime = t0_date

        # Extract events - all session_time values relative to t0_date
        track_status_list = self._extract_track_status(f1_session, t0_datetime)
        race_control_list = self._extract_race_control_messages(f1_session, t0_datetime)
        weather_list = self._extract_weather_data(f1_session, t0_datetime)

        # Convert lists to Polars DataFrames for efficient storage and querying
        track_status_df = pl.DataFrame([
            {
                'session_time': event.session_time,
                'raw_time': event.raw_time,
                'status': event.status,
                'message': event.message,
                'flag_type': event.flag_type,
                'scope': event.scope,
                'sector': event.sector,
                'driver_num': event.driver_num,
                'lap': event.lap
            }
            for event in track_status_list
        ]) if track_status_list else pl.DataFrame()

        race_control_df = pl.DataFrame([
            {
                'message': msg.message,
                'time': msg.time,
                'session_time': msg.session_time
            }
            for msg in race_control_list
        ]) if race_control_list else pl.DataFrame()

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

        if track_status_list or race_control_list or weather_list:
            print(f"  → Events: {len(track_status_list)} track status, {len(race_control_list)} messages, {len(weather_list)} weather samples")

        return EventsData(
            track_status=track_status_df,
            race_control=race_control_df,
            weather=weather_df
        )

    def _extract_track_status(self, f1_session, t0_datetime=None) -> list[TrackStatusEvent]:
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

                        # Skip SC/VSC codes - we get better data from race_control_messages
                        if status_code in ('4', '6', '7'):
                            continue

                        message = row.get('Message', '')
                        status = STATUS_MAP.get(status_code)
                        if status is None:
                            continue  # Skip unknown status codes

                        # Parse time - timedelta from t0_date, use directly
                        time_value = row.get('Time', None)
                        raw_time_str = str(time_value) if time_value is not None else None
                        if time_value is not None and hasattr(time_value, 'total_seconds'):
                            session_time = time_value.total_seconds()
                        else:
                            session_time = self._parse_time_to_session_seconds(time_value, None, t0_datetime)

                        events.append(TrackStatusEvent(
                            session_time=session_time,
                            status=status,
                            message=str(message) if pd.notna(message) else status,
                            flag_type="",
                            scope="Track",
                            sector=0,
                            driver_num="",
                            lap=0,
                            raw_time=raw_time_str
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
                        scope = str(row.get('Scope', 'Track'))
                        sector = int(row.get('Sector', 0)) if pd.notna(row.get('Sector')) else 0
                        driver_num = str(row.get('RacingNumber', '')) if pd.notna(row.get('RacingNumber')) else ''
                        lap = int(row.get('Lap', 0)) if pd.notna(row.get('Lap')) else 0

                        # Parse time - absolute timestamp, convert to t0-relative
                        time_value = row.get('Time', None)
                        raw_time_str = str(time_value) if time_value is not None else None
                        session_time = self._parse_time_to_session_seconds(time_value, None, t0_datetime)

                        # Map flag to status
                        status = FLAG_TO_STATUS.get(flag_type, 'Flag')

                        events.append(TrackStatusEvent(
                            session_time=session_time,
                            status=status,
                            message=message,
                            flag_type=flag_type,
                            scope=scope,
                            sector=sector,
                            driver_num=driver_num,
                            lap=lap,
                            raw_time=raw_time_str
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
                        raw_time_str = str(time_value) if time_value is not None else None
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
                            flag_type="",
                            scope="Track",
                            sector=0,
                            driver_num="",
                            lap=0,
                            raw_time=raw_time_str
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
            if e.status == 'Chequered' or e.flag_type == 'CHEQUERED':
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

                for _, row in rc_messages.iterrows():
                    try:
                        message_text = row.get('Message', '')
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

                            fastest_laps.append(FastestLapEvent(
                                lap=lap_num,
                                driver=driver,
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
                            time=session_end_time,
                            lap=None,
                            standings=standings
                        ))

                except Exception:
                    pass  # If results extraction fails, return empty

        except Exception:
            pass  # Return empty if extraction fails

        return position_history
