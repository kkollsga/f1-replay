"""
Time Normalizer - Synchronizes timing across all data sources

Normalizes telemetry, events, and weather data to start at t=0 from session start.
"""

from typing import Optional, Dict
import polars as pl
from f1_replay.data_loader.data_models import SessionData, EventsData


class TimeNormalizer:
    """Normalize timing across all data sources to session-relative time."""

    @staticmethod
    def get_session_start_time(session_data: SessionData) -> Optional[float]:
        """
        Find the session start time reference point.

        The session start is always at the minimum SessionSeconds from telemetry,
        since SessionSeconds is already a timedelta (relative to session start).

        Args:
            session_data: SessionData with telemetry

        Returns:
            Session start time offset in seconds (minimum telemetry time)
        """
        if not session_data.telemetry:
            return None

        # Find minimum SessionSeconds across all drivers
        # This is the session start since SessionSeconds is relative timing (timedelta)
        min_time = float('inf')

        for tel in session_data.telemetry.values():
            if "SessionSeconds" in tel.columns:
                min_val = tel["SessionSeconds"].min()
                if min_val is not None and min_val < min_time:
                    min_time = min_val

        if min_time == float('inf'):
            return None

        return float(min_time)

    @staticmethod
    def normalize_telemetry(session_data: SessionData) -> Dict[str, pl.DataFrame]:
        """
        Normalize telemetry times to start at t=0.

        Creates a new 'session_time' column with timestamps normalized to session start.

        Args:
            session_data: SessionData with telemetry

        Returns:
            Dict of driver -> normalized telemetry DataFrames with session_time column
        """
        session_start = TimeNormalizer.get_session_start_time(session_data)

        if session_start is None:
            return session_data.telemetry

        normalized = {}

        for driver, tel in session_data.telemetry.items():
            if "SessionSeconds" in tel.columns:
                # Create session_time column: normalize to t0 = 0
                session_time = tel["SessionSeconds"] - session_start
                tel_normalized = tel.with_columns(
                    pl.Series("session_time", session_time, dtype=pl.Float64)
                )
                normalized[driver] = tel_normalized
            else:
                normalized[driver] = tel

        return normalized

    @staticmethod
    def normalize_events(session_data: SessionData) -> EventsData:
        """
        Normalize event times to start at t=0.

        NOTE: Events are now stored as Polars DataFrames and are already normalized
        at extraction time (session_time field). This method is provided for
        backward compatibility or if re-normalization is needed.

        Args:
            session_data: SessionData with events

        Returns:
            Normalized EventsData
        """
        # Events are already stored as Polars DataFrames with session_time normalized
        # Just return the events as-is (session_time is already normalized at extraction)
        return session_data.events

    @staticmethod
    def normalize_session_data(session_data: SessionData) -> SessionData:
        """
        Normalize all timing in a SessionData to start at t=0.

        Creates a new SessionData object with normalized times across:
        - Telemetry (SessionSeconds)
        - Events (track status, messages, weather)

        Args:
            session_data: Original SessionData

        Returns:
            New SessionData with normalized times
        """
        # Normalize telemetry and events
        normalized_telemetry = TimeNormalizer.normalize_telemetry(session_data)
        normalized_events = TimeNormalizer.normalize_events(session_data)

        # Return new SessionData with normalized times
        from dataclasses import replace

        return replace(
            session_data,
            telemetry=normalized_telemetry,
            events=normalized_events
        )

    @staticmethod
    def get_time_offset(session_data: SessionData) -> float:
        """
        Get the time offset used for normalization.

        Useful for understanding how much to subtract from any time value
        to align it with session start (t=0).

        Args:
            session_data: SessionData

        Returns:
            Time offset in seconds (subtract this from any time to normalize)
        """
        session_start = TimeNormalizer.get_session_start_time(session_data)
        return session_start if session_start is not None else 0.0

    @staticmethod
    def print_timing_report(session_data: SessionData) -> None:
        """
        Print a report of timing alignment across data sources.

        Args:
            session_data: SessionData to analyze
        """
        print("\n" + "=" * 60)
        print("TIMING ALIGNMENT REPORT")
        print("=" * 60)

        # Get session start
        session_start = TimeNormalizer.get_session_start_time(session_data)
        print(f"\nSession Start Time: {session_start:.1f}s")

        # Telemetry timing
        if session_data.telemetry:
            min_session_time = float('inf')
            max_session_time = float('-inf')

            for tel in session_data.telemetry.values():
                if "session_time" in tel.columns:
                    min_session_time = min(min_session_time, float(tel["session_time"].min()))
                    max_session_time = max(max_session_time, float(tel["session_time"].max()))

            if min_session_time != float('inf'):
                print(f"\nTelemetry (session_time):")
                print(f"  Starts at: {min_session_time:.1f}s")
                print(f"  Ends at:   {max_session_time:.1f}s")
                print(f"  Duration:  {max_session_time - min_session_time:.1f}s")

        # Event timing (events are stored as Polars DataFrames)
        if session_data.events:
            total_events = 0
            min_event = float('inf')
            max_event = float('-inf')

            # Collect session_time from all event types
            if len(session_data.events.track_status) > 0:
                total_events += len(session_data.events.track_status)
                min_event = min(min_event, float(session_data.events.track_status["session_time"].min()))
                max_event = max(max_event, float(session_data.events.track_status["session_time"].max()))

            if len(session_data.events.race_control) > 0:
                total_events += len(session_data.events.race_control)
                min_event = min(min_event, float(session_data.events.race_control["session_time"].min()))
                max_event = max(max_event, float(session_data.events.race_control["session_time"].max()))

            if len(session_data.events.weather) > 0:
                total_events += len(session_data.events.weather)
                min_event = min(min_event, float(session_data.events.weather["session_time"].min()))
                max_event = max(max_event, float(session_data.events.weather["session_time"].max()))

            if total_events > 0 and min_event != float('inf'):
                print(f"\nEvents (Track Status, Race Control, Weather):")
                print(f"  Total events: {total_events}")
                print(f"  Starts at: {min_event:.1f}s")
                print(f"  Ends at:   {max_event:.1f}s")
                print(f"  Duration:  {max_event - min_event:.1f}s")

        # Breakdown by event type
        if session_data.events:
            print(f"\nEvent Breakdown:")
            print(f"  Track Status:  {len(session_data.events.track_status)} events")
            if len(session_data.events.track_status) > 0:
                min_ts = float(session_data.events.track_status["session_time"].min())
                max_ts = float(session_data.events.track_status["session_time"].max())
                print(f"    Range: {min_ts:.1f}s - {max_ts:.1f}s")

            print(f"  Race Control:  {len(session_data.events.race_control)} messages")
            if len(session_data.events.race_control) > 0:
                min_rc = float(session_data.events.race_control["session_time"].min())
                max_rc = float(session_data.events.race_control["session_time"].max())
                print(f"    Range: {min_rc:.1f}s - {max_rc:.1f}s")

            print(f"  Weather:       {len(session_data.events.weather)} samples")
            if len(session_data.events.weather) > 0:
                min_w = float(session_data.events.weather["session_time"].min())
                max_w = float(session_data.events.weather["session_time"].max())
                print(f"    Range: {min_w:.1f}s - {max_w:.1f}s")

        print("\n" + "=" * 60)
        print("All times are normalized to session start (t0 = 0)")
        print("=" * 60 + "\n")


def align_to_session_start(session_data: SessionData) -> SessionData:
    """
    Convenience function to normalize a session's timing to start at t=0.

    Args:
        session_data: Original session data

    Returns:
        Session data with all times normalized to session start (t=0)
    """
    return TimeNormalizer.normalize_session_data(session_data)
