"""
Session Processor - TIER 3 Processing

Builds SessionData (telemetry, events, results) from FastF1.
Event times are normalized to session start (t0) automatically.
"""

from typing import Optional, Dict
import datetime
import polars as pl
import pandas as pd
from f1_replay.data_loader.data_models import (
    SessionData, SessionMetadata, EventsData, ResultsData,
    FastestLapEvent, PositionSnapshot, PositionEntry,
    TrackStatusEvent, RaceControlMessage, WeatherSample
)
from f1_replay.data_loader.fastf1_client import FastF1Client
from f1_replay.data_loader.order_builder import OrderBuilder
from f1_replay.data_loader.weather_extractor import WeatherExtractor


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
        which corresponds to the second GREEN LIGHT event in track_status.

        Args:
            events: EventsData with track status events
            session_type: Type of session ("R", "Q", "FP1", etc.)

        Returns:
            session_time offset in seconds, or None if not found
        """
        if session_type != "R" or len(events.track_status) == 0:
            return None

        try:
            # Convert to list of dicts for easier filtering
            track_status_list = events.track_status.to_dicts()

            # Look for GREEN LIGHT events that happen during the race
            # The first GREEN LIGHT (around -2400s) is pre-race pit exit open
            # The second GREEN LIGHT (around 100-300s) is formation lap start
            green_lights = [e for e in track_status_list if e.get('status') == 'GREEN' and 'GREEN LIGHT' in e.get('message', '')]

            if len(green_lights) >= 2:
                # Use the second GREEN LIGHT as race start (lights out)
                race_start_time = green_lights[1].get('session_time')
                if race_start_time is not None:
                    return float(race_start_time)
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

        # Re-normalize order dataset (stored in SessionData, not ResultsData)
        renormalized_order = session_data.order
        if len(renormalized_order) > 0 and "session_time" in renormalized_order.columns:
            new_session_time = renormalized_order["session_time"] - race_start_time
            renormalized_order = renormalized_order.with_columns(
                pl.Series("session_time", new_session_time, dtype=pl.Float64)
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
            order=renormalized_order,
            rain_events=renormalized_rain_events
        )

    def build_session(self, year: int, round_num: int,
                     session_type: str, event_name: str) -> Optional[SessionData]:
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
            SessionData or None if error
        """
        print(f"→ Loading session {year} R{round_num} {session_type}...")

        # Load session with all data
        f1_session = self.fastf1_client.get_session_with_all_data(year, round_num, session_type)
        if f1_session is None:
            return None

        # Build metadata
        metadata = self._build_metadata(year, round_num, session_type, event_name, f1_session)

        # Build COMPLETE telemetry (includes RawTime, session_time, progress, status, TimeToDriverAhead)
        # Also returns the order dataset for UI position tracking
        telemetry, order = self._build_complete_telemetry(f1_session)

        if not telemetry:
            return None

        # For event normalization, use the telemetry start time
        telemetry_t0 = self._get_true_session_start_from_telemetry(telemetry)
        event_t0 = telemetry_t0 if telemetry_t0 else metadata.t0_date_utc

        # Build events (track status, weather, race control)
        events = self._build_events(f1_session, event_t0)

        # Build results (fastest laps, position history)
        results = self._build_results(f1_session, telemetry, metadata.t0_date_utc)

        # Extract rain events from weather data
        rain_events = WeatherExtractor.extract_rain_events(events.weather)

        # Create final SessionData
        session_data = SessionData(
            metadata=metadata,
            telemetry=telemetry,
            events=events,
            results=results,
            order=order,
            rain_events=rain_events
        )

        if len(rain_events) > 0:
            print(f"  ✓ Extracted {len(rain_events)} rain event(s)")

        print(f"  ✓ Session complete: {len(metadata.drivers)} drivers, {len(telemetry)} with telemetry")
        return session_data

    def _build_metadata(self, year: int, round_num: int, session_type: str,
                       event_name: str, f1_session) -> SessionMetadata:
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

                # Track DNF drivers (status = "Retired")
                if abbr and status == 'Retired':
                    dnf_drivers.append(abbr)

        # Get session start time if available
        t0_date = getattr(f1_session, 'date', None)
        if t0_date:
            t0_date = str(t0_date)

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
            total_laps=len(f1_session.laps) if f1_session.laps is not None else 0,
            dnf_drivers=dnf_drivers,
            t0_date_utc=t0_date,
            start_time_local=None  # TODO: Extract from session
        )

        return metadata

    def _build_complete_telemetry(self, f1_session) -> tuple[Dict[str, pl.DataFrame], pl.DataFrame]:
        """
        Build COMPLETE telemetry with all derived fields and order dataset.

        Single-pass processing that builds:
        - RawTime: Original FastF1 timestamp for reference
        - session_time: Normalized time (t=0 at session start)
        - progress: Lap-based progress around circuit
        - TimeToDriverAhead: Time gap to driver ahead
        - status: 'racing' or 'retired'
        - order dataset: Driver position tracking

        Returns:
            tuple: (telemetry_dict, order_dataframe)
                - telemetry_dict: Dict mapping driver code -> complete Polars DataFrame
                - order_dataframe: Order dataset for position tracking
        """
        print(f"  → Building complete telemetry (time, progress, status, gaps, order)...")
        telemetry_data = {}

        if f1_session.laps is None or len(f1_session.laps) == 0:
            return telemetry_data, pl.DataFrame()

        # ===================================================================
        # STEP 1: Build raw telemetry for each driver
        # ===================================================================
        for driver in f1_session.laps['Driver'].unique():
            try:
                driver_laps = f1_session.laps.pick_drivers(driver)
                all_telemetry = []

                for _, lap in driver_laps.iterrows():
                    try:
                        tel = lap.get_telemetry()
                        if tel is not None and not tel.empty:
                            tel = tel.copy()
                            tel['LapNumber'] = lap['LapNumber']

                            # Add SessionTime if not present (lap_start + relative_time)
                            if 'SessionTime' not in tel.columns and 'Time' in tel.columns:
                                lap_start = lap.get('LapStartTime')
                                if pd.notna(lap_start):
                                    tel['SessionTime'] = lap_start + tel['Time']

                            all_telemetry.append(tel)
                    except:
                        continue

                if all_telemetry:
                    combined = pd.concat(all_telemetry, ignore_index=True)

                    # Convert to seconds for normalization
                    if 'SessionTime' in combined.columns:
                        combined['SessionSeconds'] = combined['SessionTime'].dt.total_seconds()

                    # Convert to Polars and store
                    df_polars = pl.from_pandas(
                        combined.sort_values('SessionTime', na_position='last').reset_index(drop=True)
                    )
                    telemetry_data[driver] = df_polars
                    print(f"    ✓ {driver}: {len(combined)} raw points")

            except Exception as e:
                print(f"    ⚠ {driver}: {e}")

        if not telemetry_data:
            return telemetry_data, pl.DataFrame()

        # ===================================================================
        # STEP 2: Normalize time (convert to session_time with t0=0)
        # ===================================================================
        print(f"  → Normalizing time to session start...")

        # Find minimum SessionSeconds across all drivers
        min_session_seconds = float('inf')
        for driver, tel in telemetry_data.items():
            if 'SessionSeconds' in tel.columns and len(tel) > 0:
                driver_min = float(tel['SessionSeconds'].min())
                min_session_seconds = min(min_session_seconds, driver_min)

        if min_session_seconds == float('inf'):
            min_session_seconds = 0.0

        # Add RawTime (keep Date) and normalized session_time
        normalized_telemetry = {}
        for driver, tel in telemetry_data.items():
            # Rename Date to RawTime and calculate session_time
            df = tel.rename({'Date': 'RawTime'}) if 'Date' in tel.columns else tel

            if 'SessionSeconds' in df.columns:
                df = df.with_columns([
                    (pl.col('SessionSeconds') - min_session_seconds).alias('session_time')
                ])

            # Drop intermediate columns: Time, SessionTime, SessionSeconds
            cols_to_drop = ['Time', 'SessionTime', 'SessionSeconds']
            df = df.drop([col for col in cols_to_drop if col in df.columns])

            normalized_telemetry[driver] = df

        # ===================================================================
        # STEP 3: Add progress column
        # ===================================================================
        print(f"  → Adding progress column...")

        telemetry_with_progress = {}
        for driver, tel in normalized_telemetry.items():
            if 'LapNumber' in tel.columns and 'Distance' in tel.columns:
                progress = (tel['LapNumber'] - 1) * self.circuit_length + tel['Distance']
                df = tel.with_columns([progress.alias('progress')])
                telemetry_with_progress[driver] = df
            else:
                telemetry_with_progress[driver] = tel

        # ===================================================================
        # STEP 4: Add status column (racing/retired)
        # ===================================================================
        print(f"  → Adding status column...")

        telemetry_with_status = self._add_status_column_to_telemetry_vectorized(
            telemetry_with_progress
        )

        # ===================================================================
        # STEP 5: Build order dataset
        # ===================================================================
        print(f"  → Building order dataset...")

        order_df = OrderBuilder.build_order(telemetry_with_status, self.circuit_length)

        # ===================================================================
        # STEP 6: Calculate TimeToDriverAhead
        # ===================================================================
        print(f"  → Calculating TimeToDriverAhead gaps...")

        telemetry_complete = OrderBuilder.calculate_time_to_driver_ahead(
            order_df, telemetry_with_status
        )

        print(f"  ✓ Complete telemetry: {len(telemetry_complete)} drivers with all derived fields")
        return telemetry_complete, order_df

    def _add_status_column_to_telemetry_vectorized(self, telemetry: Dict[str, pl.DataFrame]) -> Dict[str, pl.DataFrame]:
        """
        Add status column (racing/retired) to telemetry using vectorized operations.

        Optimized version integrated into telemetry building pipeline.
        """
        if not telemetry:
            return telemetry

        result = {}
        import numpy as np

        for driver_code, driver_df in telemetry.items():
            if 'session_time' not in driver_df.columns or 'progress' not in driver_df.columns:
                result[driver_code] = driver_df
                continue

            df = driver_df.clone()

            # Vectorized status detection using numpy
            times = df['session_time'].to_numpy()
            progress = df['progress'].to_numpy()

            status = np.array(['racing'] * len(times), dtype=object)

            for i in range(len(times)):
                # Find progress value from 60 seconds ago
                idx_60s_ago = np.searchsorted(times, times[i] - 60)

                # If there's a point 60s ago and progress hasn't changed → retired
                if idx_60s_ago < i and np.isclose(progress[i], progress[idx_60s_ago]):
                    status[i] = 'retired'

            df = df.with_columns(pl.Series('status', status, dtype=pl.Utf8))
            result[driver_code] = df

        return result

    def _build_events(self, f1_session, t0_date_utc: Optional[str] = None) -> EventsData:
        """
        Build events data (track status, weather, messages).

        All event times are normalized to session start (t0 = 0).
        Note: FastF1 events use absolute timestamps (seconds of day),
        so we use t0_date_utc to establish the session start reference.

        Args:
            f1_session: FastF1 session object
            t0_date_utc: Session start time in ISO format (from metadata)

        Extracts:
        - Track status changes (yellows, reds, SCs, VSCs)
        - Race control messages
        - Weather samples throughout session
        """
        # Convert t0_date_utc to seconds of day for event normalization
        # FastF1 events use absolute timestamps, so we need the actual session start time
        t0_seconds_of_day = self._get_session_start_seconds_of_day(t0_date_utc)

        # Parse t0_date_utc as datetime for precise timestamp comparison
        t0_datetime = None
        if t0_date_utc:
            try:
                if 'T' in str(t0_date_utc):
                    t0_datetime = datetime.datetime.fromisoformat(str(t0_date_utc).replace('Z', '+00:00'))
                else:
                    t0_datetime = datetime.datetime.fromisoformat(str(t0_date_utc))
            except Exception:
                pass

        track_status_list = self._extract_track_status(f1_session, t0_seconds_of_day, t0_datetime)
        race_control_list = self._extract_race_control_messages(f1_session, t0_seconds_of_day, t0_datetime)
        weather_list = self._extract_weather_data(f1_session, t0_seconds_of_day, t0_datetime)

        # Convert lists to Polars DataFrames for efficient storage and querying
        track_status_df = pl.DataFrame([
            {
                'status': event.status,
                'message': event.message,
                'time': event.time,
                'session_time': event.session_time
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

    def _extract_track_status(self, f1_session, t0_seconds_of_day: Optional[float] = None,
                            t0_datetime=None) -> list[TrackStatusEvent]:
        """Extract track status changes from messages (normalized to session start)."""
        track_status = []

        try:
            # FastF1 exposes messages as race_control_messages
            messages_df = None
            if hasattr(f1_session, 'race_control_messages') and f1_session.race_control_messages is not None:
                messages_df = f1_session.race_control_messages
            elif hasattr(f1_session, 'messages') and f1_session.messages is not None:
                messages_df = f1_session.messages

            if messages_df is None or len(messages_df) == 0:
                return track_status

            # Filter for track status messages (FastF1 uses 'Flag' for status)
            if 'Category' in messages_df.columns:
                status_messages = messages_df[messages_df['Category'] == 'Flag']

                for _, row in status_messages.iterrows():
                    try:
                        # Extract flag type and message
                        status = row.get('Flag', row.get('Status', 'Unknown'))
                        message = row.get('Message', '')

                        # Get time value (FastF1 provides this as pd.Timestamp)
                        time_value = row.get('Time', None)
                        time_float = 0.0
                        session_time = 0.0

                        if time_value is not None:
                            try:
                                # Handle different time formats from FastF1
                                if isinstance(time_value, pd.Timestamp):
                                    # For absolute timestamps: store seconds of day as original time
                                    time_float = time_value.hour * 3600 + time_value.minute * 60 + time_value.second + time_value.microsecond / 1e6
                                    # Calculate session-relative time using datetime comparison
                                    if t0_datetime is not None:
                                        session_time = (time_value - t0_datetime).total_seconds()
                                    elif t0_seconds_of_day is not None:
                                        session_time = time_float - t0_seconds_of_day
                                elif hasattr(time_value, 'total_seconds'):
                                    # Handle timedelta objects (already relative to session start)
                                    time_float = time_value.total_seconds()
                                    session_time = time_float
                                else:
                                    # Numeric value
                                    time_float = float(time_value)
                                    session_time = time_float
                            except:
                                time_float = 0.0
                                session_time = 0.0

                        track_status.append(TrackStatusEvent(
                            status=str(status),
                            message=str(message) if pd.notna(message) else '',
                            time=time_float,
                            session_time=session_time
                        ))
                    except Exception:
                        pass  # Skip malformed entries

        except Exception:
            pass  # Return empty if extraction fails

        return track_status

    def _extract_race_control_messages(self, f1_session, t0_seconds_of_day: Optional[float] = None,
                                      t0_datetime=None) -> list[RaceControlMessage]:
        """Extract race control messages (normalized to session start)."""
        messages = []

        try:
            # FastF1 exposes messages as race_control_messages
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
                        # Get message text
                        message_text = row.get('Message', '')

                        # Get time value (FastF1 provides this as pd.Timestamp)
                        time_value = row.get('Time', None)
                        time_float = 0.0
                        session_time = 0.0

                        if time_value is not None:
                            try:
                                # Handle different time formats from FastF1
                                if isinstance(time_value, pd.Timestamp):
                                    # For absolute timestamps: store seconds of day as original time
                                    time_float = time_value.hour * 3600 + time_value.minute * 60 + time_value.second + time_value.microsecond / 1e6
                                    # Calculate session-relative time using datetime comparison
                                    if t0_datetime is not None:
                                        session_time = (time_value - t0_datetime).total_seconds()
                                    elif t0_seconds_of_day is not None:
                                        session_time = time_float - t0_seconds_of_day
                                elif hasattr(time_value, 'total_seconds'):
                                    # Handle timedelta objects (already relative to session start)
                                    time_float = time_value.total_seconds()
                                    session_time = time_float
                                else:
                                    # Numeric value
                                    time_float = float(time_value)
                                    session_time = time_float
                            except:
                                time_float = 0.0
                                session_time = 0.0

                        messages.append(RaceControlMessage(
                            message=str(message_text) if pd.notna(message_text) else '',
                            time=time_float,
                            session_time=session_time
                        ))
                    except Exception:
                        pass  # Skip malformed entries

        except Exception:
            pass  # Return empty if extraction fails

        return messages

    def _extract_weather_data(self, f1_session, t0_seconds_of_day: Optional[float] = None,
                             t0_datetime=None) -> list[WeatherSample]:
        """Extract weather samples from session (normalized to session start)."""
        weather_samples = []

        try:
            # FastF1 exposes weather as weather_data, not weather
            weather_df = None
            if hasattr(f1_session, 'weather_data') and f1_session.weather_data is not None:
                weather_df = f1_session.weather_data
            elif hasattr(f1_session, 'weather') and f1_session.weather is not None:
                weather_df = f1_session.weather

            if weather_df is None or len(weather_df) == 0:
                return weather_samples

            for _, row in weather_df.iterrows():
                try:
                    # Get time value (FastF1 provides this as pd.Timestamp)
                    time_value = row.get('Time', None)
                    time_float = 0.0
                    session_time = 0.0

                    if time_value is not None:
                        try:
                            # Handle different time formats from FastF1
                            if isinstance(time_value, pd.Timestamp):
                                # For absolute timestamps: store seconds of day as original time
                                time_float = time_value.hour * 3600 + time_value.minute * 60 + time_value.second + time_value.microsecond / 1e6
                                # Calculate session-relative time using datetime comparison
                                if t0_datetime is not None:
                                    session_time = (time_value - t0_datetime).total_seconds()
                                elif t0_seconds_of_day is not None:
                                    session_time = time_float - t0_seconds_of_day
                            elif hasattr(time_value, 'total_seconds'):
                                # Handle timedelta objects (already relative to session start)
                                time_float = time_value.total_seconds()
                                session_time = time_float
                            else:
                                # Numeric value
                                time_float = float(time_value)
                                session_time = time_float
                        except:
                            time_float = 0.0
                            session_time = 0.0

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
