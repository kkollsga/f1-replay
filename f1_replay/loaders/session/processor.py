"""
Session Processor - TIER 3 Processing

Builds SessionData (telemetry, events, results) from FastF1.
Event times are normalized to session start (t0) automatically.
"""

import datetime
from typing import Dict, Optional

import numpy as np
import pandas as pd
import polars as pl

from f1_replay.loaders.core.client import FastF1Client
from f1_replay.loaders.session import events as evt
from f1_replay.loaders.session import results as res
from f1_replay.loaders.session.order import OrderBuilder
from f1_replay.loaders.session.telemetry import TelemetryBuilder
from f1_replay.log import logger
from f1_replay.models import EventsData, ResultsData, SessionData, SessionMetadata, T0Info


class SessionProcessor:
    """Process and build SessionData."""

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
            if "T" in t0_date_utc:
                dt = datetime.datetime.fromisoformat(t0_date_utc.replace("Z", "+00:00"))
            else:
                dt = datetime.datetime.fromisoformat(t0_date_utc)

            seconds_of_day = dt.hour * 3600 + dt.minute * 60 + dt.second + dt.microsecond / 1e6
            return seconds_of_day
        except Exception:
            return None

    def _get_true_session_start_from_telemetry(
        self, telemetry: Dict[str, pl.DataFrame]
    ) -> Optional[str]:
        """Get true session start time from telemetry data (RawTime column)."""
        if not telemetry:
            return None

        try:
            earliest_date = None

            for driver_tel in telemetry.values():
                # Use RawTime (renamed from Date in complete telemetry)
                col_name = "RawTime" if "RawTime" in driver_tel.columns else "Date"

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

    def _normalize_event_time(
        self, raw_time: float, t0_seconds_of_day: Optional[float], time_obj=None, t0_datetime=None
    ) -> float:
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
                green_lights = [
                    e for e in race_control_list if "GREEN LIGHT" in e.get("message", "").upper()
                ]

                if len(green_lights) >= 2:
                    # Use the second GREEN LIGHT as race start
                    race_start_time = green_lights[1].get("session_time")
                    if race_start_time is not None:
                        return float(race_start_time)

            # Fallback: use first AllClear from track_status that's near session start
            if len(events.track_status) > 0:
                track_status_list = events.track_status.to_dicts()
                for e in track_status_list:
                    if e.get("status") == "AllClear":
                        session_time = e.get("session_time", 0)
                        # First AllClear should be right after lights out (< 60 seconds)
                        if 0 <= session_time < 60:
                            return float(session_time)

        except Exception:
            pass

        return None

    def _renormalize_to_race_start(
        self, session_data: SessionData, race_start_time: float
    ) -> SessionData:
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
            return df.with_columns(pl.Series("session_time", new_session_time, dtype=pl.Float64))

        renormalized_events = EventsData(
            track_status=renormalize_df(session_data.events.track_status),
            race_control=renormalize_df(session_data.events.race_control),
        )

        # Re-normalize results if they have session_time
        renormalized_results = session_data.results
        if session_data.results and hasattr(session_data.results, "position_history"):
            if session_data.results.position_history:
                renormalized_positions = []
                for snapshot in session_data.results.position_history:
                    # Update snapshot time
                    new_time = (
                        snapshot.time - race_start_time
                        if snapshot.time is not None
                        else snapshot.time
                    )
                    new_snapshot = snapshot.__class__(time=new_time, standings=snapshot.standings)
                    renormalized_positions.append(new_snapshot)

                renormalized_results = replace(
                    session_data.results, position_history=renormalized_positions
                )

        # Create new SessionData with renormalized times
        return replace(
            session_data,
            telemetry=renormalized_telemetry,
            events=renormalized_events,
            results=renormalized_results,
        )

    def build_session(
        self, year: int, round_num: int, session_type: str, event_name: str
    ) -> Optional[tuple]:
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
        logger.info(f"→ Loading session {year} R{round_num} {session_type}...")

        # STEP 1: Load FastF1 session
        f1_session = self.fastf1_client.get_session_with_all_data(year, round_num, session_type)
        if f1_session is None:
            return None

        # STEP 2: Extract DNF drivers
        dnf_drivers_set = self._extract_dnf_drivers(f1_session)

        # STEP 3: Build SessionMetadata FIRST ★
        logger.info("  → Building metadata...")
        metadata = self._build_metadata(
            year,
            round_num,
            session_type,
            event_name,
            f1_session,
            laps_df=f1_session.laps,  # For lights_out_offset extraction
        )
        logger.info(f"  ✓ Metadata built with {len(metadata.drivers)} drivers")

        # STEP 4: Build EventsData SECOND ★
        logger.info("  → Building events...")
        events = self._build_events(f1_session, t0_info=metadata.t0)
        logger.info("  ✓ Events built")

        # STEP 5: Build Telemetry LAST ★
        logger.info("  → Building telemetry from pos_data + car_data...")
        telemetry, track_data, session_timing, status_data_all = TelemetryBuilder.build_telemetry(
            f1_session,
            dnf_drivers=dnf_drivers_set,
            extract_track=False,  # Track extracted during weekend build, not session
        )

        if not telemetry:
            logger.warning("  ⚠ No telemetry data available")
            return None

        # STEP 6: Add track distance using weekend's track geometry
        if self.weekend_track is not None and self.weekend_track.x is not None:
            logger.info("  → Adding track_distance from weekend track geometry...")
            # Create a temporary TrackData-like structure for TelemetryBuilder
            from f1_replay.loaders.session.telemetry import TrackData

            temp_track_data = TrackData(
                track_x=self.weekend_track.x,
                track_y=self.weekend_track.y,
                track_z=self.weekend_track.z,
                track_distance=(
                    (self.weekend_track.distance * 10.0).astype(np.float32)
                    if self.weekend_track.distance is not None
                    else None
                ),  # meters -> decimeters
                lap_distance=self.weekend_track.lap_distance * 10.0,  # meters -> decimeters
                pit_x=None,
                pit_y=None,
                pit_distance=None,
                pit_length=0.0,
                pit_entry_distance=None,
                pit_exit_distance=None,
                marshal_sectors=[],
                speed=None,
                throttle=None,
                brake=None,
            )
            # Use metadata.t0 for session_timing (compatibility with existing code)
            session_timing_compat = None
            if metadata.t0 and metadata.t0.warmup_start_offset is not None:
                session_timing_compat = {"warmup_start_time": metadata.t0.warmup_start_offset}

            # Add track_distance, race_distance, and update lap_number
            telemetry = TelemetryBuilder._add_track_distance_all(
                telemetry, temp_track_data, session_timing_compat
            )
            logger.info("  ✓ Track distance added from weekend track")
        else:
            # No track geometry available - add placeholder columns for status update
            logger.warning("  ⚠ No weekend track geometry, adding placeholder distance columns")
            for driver, tel in telemetry.items():
                telemetry[driver] = tel.with_columns(
                    [
                        pl.lit(0.0).cast(pl.Float32).alias("track_distance"),
                        pl.lit(0.0).cast(pl.Float32).alias("race_distance"),
                    ]
                )

        # STEP 6.5: Update status column (ALWAYS, regardless of track geometry)
        # Extract warmup intervals from track_status
        warmup_intervals = []
        if events and events.track_status is not None:
            warmup_events = events.track_status.filter(events.track_status["status"] == "WarmUp")
            for row in warmup_events.iter_rows(named=True):
                start = row["session_time"]
                end = row.get("end_time", None)
                if start is not None and end is not None:
                    warmup_intervals.append((start, end))

        # Get lights_out_offset from metadata
        lights_out_offset = metadata.t0.lights_out_offset if metadata.t0 else None

        # Update status column using warmup intervals and lights_out
        telemetry = TelemetryBuilder._add_status_all(
            telemetry,
            status_data_all,
            warmup_intervals=warmup_intervals,
            lights_out_offset=lights_out_offset,
        )
        logger.info("  ✓ Status updated from track events")

        # STEP 7: Add positions and intervals
        logger.info("  → Adding positions to telemetry...")
        telemetry = OrderBuilder.add_positions_to_telemetry(telemetry)
        logger.info(f"  ✓ Positions added to {len(telemetry)} drivers")

        logger.info("  → Adding intervals to telemetry...")
        telemetry = OrderBuilder.add_intervals_to_telemetry(telemetry)
        logger.info("  ✓ Intervals added")

        # STEP 8: Build results
        t0_utc = metadata.t0.utc if metadata.t0 else None
        results = self._build_results(f1_session, telemetry, t0_utc)

        # STEP 9: Update metadata with telemetry session_duration
        if metadata.t0 and telemetry:
            # Recalculate session_duration now that we have telemetry
            max_time = 0.0
            min_time = float("inf")
            for df in telemetry.values():
                if "session_time" in df.columns and len(df) > 0:
                    max_time = max(max_time, df["session_time"].max())
                    min_time = min(min_time, df["session_time"].min())
            if min_time != float("inf"):
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
                        session_duration=session_duration,
                    ),
                    start_time_local=metadata.start_time_local,
                )

        # Create final SessionData
        session_data = SessionData(
            metadata=metadata, telemetry=telemetry, events=events, results=results
        )

        logger.info(
            f"  ✓ Session complete: {len(metadata.drivers)} drivers, {len(telemetry)} with telemetry"
        )
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
                abbr = row.get("Abbreviation")
                status = row.get("Status", "")
                if abbr and status:
                    is_finished = status in ("Finished", "Lapped") or status.startswith("+")
                    if not is_finished:
                        dnf_drivers.add(abbr)

        if dnf_drivers:
            logger.info(f"  → DNF drivers from results: {', '.join(sorted(dnf_drivers))}")

        return dnf_drivers

    def _build_metadata(
        self,
        year: int,
        round_num: int,
        session_type: str,
        event_name: str,
        f1_session,
        laps_df,
        telemetry: Optional[Dict[str, pl.DataFrame]] = None,
    ) -> SessionMetadata:
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
                abbr = row.get("Abbreviation")
                number = row.get("DriverNumber")
                name = row.get("FullName")
                team = row.get("TeamName")
                color = row.get("TeamColor")
                status = row.get("Status", "")

                if abbr and number:
                    driver_numbers[abbr] = int(number)
                if abbr and name:
                    driver_names[abbr] = str(name)
                if abbr and team:
                    driver_teams[abbr] = team
                if abbr and color:
                    driver_colors[abbr] = str(color) if pd.notna(color) else "#CCCCCC"
                if team and color:
                    team_colors[team] = str(color) if pd.notna(color) else "#CCCCCC"

                # Track DNF drivers - any status that's not a finish
                # Finished statuses: "Finished", "Lapped", "+1 Lap", "+2 Laps", etc.
                # DNF statuses: "Retired", "Engine", "Collision", "Accident", etc.
                if abbr and status:
                    is_finished = status in ("Finished", "Lapped") or status.startswith("+")
                    if not is_finished:
                        dnf_drivers.append(abbr)

        # Build T0Info (now uses f1_session.date directly for warmup start)
        t0_info = self._build_t0_info(f1_session, laps_df, telemetry)

        # Extract session start time as ISO string (for timezone conversion in display)
        start_time_local = None
        try:
            session_date = f1_session.date
            if session_date is not None:
                start_time_local = session_date.isoformat()
        except Exception:
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
            total_laps=(
                int(f1_session.laps["LapNumber"].max())
                if f1_session.laps is not None and len(f1_session.laps) > 0
                else 0
            ),
            dnf_drivers=dnf_drivers,
            t0=t0_info,
            start_time_local=start_time_local,
        )

        return metadata

    def _build_t0_info(
        self, f1_session, laps_df, telemetry: Optional[Dict[str, pl.DataFrame]] = None
    ) -> Optional[T0Info]:
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
        try:
            t0_date = f1_session.t0_date
        except Exception:
            t0_date = None

        if t0_date is None:
            return None

        if not isinstance(t0_date, pd.Timestamp):
            t0_date = pd.Timestamp(t0_date)

        # t0.utc is the timing zero (t0_date) - when session_time=0
        t0_utc_str = t0_date.isoformat()

        # Get session scheduled start (warmup start) from f1_session.date
        warmup_start_offset = None
        session_start = getattr(f1_session, "date", None)
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
            min_time = float("inf")
            for df in telemetry.values():
                if "session_time" in df.columns and len(df) > 0:
                    max_time = max(max_time, df["session_time"].max())
                    min_time = min(min_time, df["session_time"].min())
            if min_time != float("inf"):
                session_duration = max_time - min_time

        # Extract timezone from event
        timezone_str = ""
        utc_offset = 0.0
        try:
            event = getattr(f1_session, "event", None)
            if event is not None:
                country = getattr(event, "Country", "")
                location = getattr(event, "Location", "")

                TIMEZONE_MAP = {
                    "Bahrain": ("Asia/Bahrain", 3.0),
                    "Saudi Arabia": ("Asia/Riyadh", 3.0),
                    "Australia": ("Australia/Melbourne", 11.0),
                    "Japan": ("Asia/Tokyo", 9.0),
                    "China": ("Asia/Shanghai", 8.0),
                    "United States": ("America/Chicago", -6.0),
                    "Miami": ("America/New_York", -5.0),
                    "Las Vegas": ("America/Los_Angeles", -8.0),
                    "Austin": ("America/Chicago", -6.0),
                    "Monaco": ("Europe/Monaco", 2.0),
                    "Spain": ("Europe/Madrid", 2.0),
                    "Canada": ("America/Toronto", -5.0),
                    "Austria": ("Europe/Vienna", 2.0),
                    "Great Britain": ("Europe/London", 1.0),
                    "UK": ("Europe/London", 1.0),
                    "Hungary": ("Europe/Budapest", 2.0),
                    "Belgium": ("Europe/Brussels", 2.0),
                    "Netherlands": ("Europe/Amsterdam", 2.0),
                    "Italy": ("Europe/Rome", 2.0),
                    "Singapore": ("Asia/Singapore", 8.0),
                    "Mexico": ("America/Mexico_City", -6.0),
                    "Brazil": ("America/Sao_Paulo", -3.0),
                    "Qatar": ("Asia/Qatar", 3.0),
                    "United Arab Emirates": ("Asia/Dubai", 4.0),
                    "Abu Dhabi": ("Asia/Dubai", 4.0),
                    "Azerbaijan": ("Asia/Baku", 4.0),
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
            session_duration=session_duration,
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
            lap1_data = laps_df[laps_df["LapNumber"] == 1]
            if len(lap1_data) == 0:
                return None

            # LapStartTime is when the lap started (lights out for lap 1)
            lap_start = lap1_data["LapStartTime"].min()
            if pd.notna(lap_start):
                # LapStartTime is timedelta from t0_date
                if hasattr(lap_start, "total_seconds"):
                    # It's a timedelta - convert to seconds
                    return lap_start.total_seconds()
                else:
                    # It's an absolute timestamp - calculate offset
                    lap_start_ts = pd.Timestamp(lap_start)
                    return (lap_start_ts - t0_date).total_seconds()
        except Exception:
            pass

        return None

    def _build_events(self, f1_session, t0_info=None) -> EventsData:
        """Build events data — delegates to events module."""
        return evt.build_events(f1_session, t0_info)

    def _build_results(self, f1_session, telemetry=None, true_t0=None) -> ResultsData:
        """Build results data — delegates to results module."""
        return res.build_results(f1_session, telemetry, true_t0)
