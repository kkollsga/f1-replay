"""Results and message extraction functions for session processing."""

from typing import Optional, Dict

import pandas as pd
import polars as pl

from f1_replay.log import logger
from f1_replay.models import (
    ResultsData, FastestLapEvent, PositionSnapshot, PositionEntry,
    RaceControlMessage, WeatherSample
)


def extract_race_control_messages(
    f1_session,
    t0_datetime=None,
    track_status_patterns=None,
    timestamp_pattern=None,
) -> list[RaceControlMessage]:
    """Extract race control messages (normalized to t0_date)."""
    if track_status_patterns is None or timestamp_pattern is None:
        from f1_replay.loaders.session.events import (
            TRACK_STATUS_MESSAGE_PATTERNS,
            TIMESTAMP_MESSAGE_PATTERN,
        )
        if track_status_patterns is None:
            track_status_patterns = TRACK_STATUS_MESSAGE_PATTERNS
        if timestamp_pattern is None:
            timestamp_pattern = TIMESTAMP_MESSAGE_PATTERN

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
                    if any(pattern in message_upper for pattern in track_status_patterns):
                        continue

                    # Skip messages with timestamps (AT HH:MM) - these become status subtitles
                    if re.search(timestamp_pattern, message_upper):
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
                        except (ValueError, TypeError):
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


def extract_status_messages(
    f1_session,
    t0_datetime=None,
    t0_info=None,
    timestamp_pattern=None,
) -> list[dict]:
    """
    Extract status messages with timestamps (e.g., "RACE WILL START AT 12:47").

    These become status subtitles displayed below track status pills.
    The time in the message is local time - we use utc_offset_hours to convert to UTC.

    Returns list of dicts with: session_time, end_time, message
    """
    if timestamp_pattern is None:
        from f1_replay.loaders.session.events import TIMESTAMP_MESSAGE_PATTERN
        timestamp_pattern = TIMESTAMP_MESSAGE_PATTERN

    from f1_replay.loaders.session.events import parse_time_to_session_seconds

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
                    match = re.search(timestamp_pattern, message_upper)
                    if match and t0_datetime is not None:
                        # Parse announcement time
                        time_value = row.get('Time', None)
                        session_time = parse_time_to_session_seconds(time_value, None, t0_datetime)

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


def extract_weather_data(f1_session, t0_datetime=None) -> list[WeatherSample]:
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
                    except (ValueError, TypeError):
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


def extract_fastest_laps(f1_session) -> list[FastestLapEvent]:
    """
    Extract chronological fastest lap changes from laps data.

    Args:
        f1_session: FastF1 session object with laps data
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

                        # Calculate session_time from LapStartTime + LapTime
                        # This gives us when the lap was completed relative to session t0
                        session_time = 0.0
                        lap_start = lap.get('LapStartTime', None)
                        lap_time_td = lap.get('LapTime', None)
                        if lap_start is not None and not pd.isna(lap_start) and lap_time_td is not None and not pd.isna(lap_time_td):
                            try:
                                # Convert to seconds
                                if hasattr(lap_start, 'total_seconds'):
                                    lap_start_sec = lap_start.total_seconds()
                                else:
                                    lap_start_sec = float(lap_start)
                                if hasattr(lap_time_td, 'total_seconds'):
                                    lap_time_sec = lap_time_td.total_seconds()
                                else:
                                    lap_time_sec = float(lap_time_td)
                                session_time = lap_start_sec + lap_time_sec
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


def calculate_session_end_time(
    telemetry: Dict[str, pl.DataFrame] = None,
    true_t0: Optional[str] = None,
) -> float:
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


def extract_position_history(
    f1_session,
    telemetry: Dict[str, pl.DataFrame] = None,
    true_t0: Optional[str] = None,
) -> list[PositionSnapshot]:
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
                    session_end_time = calculate_session_end_time(telemetry, true_t0)
                    # Use nan if unable to calculate (serializer converts to None for valid JSON)
                    if session_end_time == 0.0:
                        session_end_time = float('nan')
                    # Add final standings snapshot at session end
                    position_history.append(PositionSnapshot(
                        time=session_end_time,
                        standings=standings
                    ))

            except Exception:
                pass  # If results extraction fails, return empty

    except Exception:
        pass  # Return empty if extraction fails

    return position_history


def build_results(
    f1_session,
    telemetry: Dict[str, pl.DataFrame] = None,
    true_t0: Optional[str] = None,
) -> ResultsData:
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
            logger.info(f"  -> Building results with telemetry: {len(telemetry)} drivers, session_time={'yes' if has_session_time else 'no'}")

    fastest_laps = extract_fastest_laps(f1_session)
    position_history = extract_position_history(f1_session, telemetry, true_t0)

    if fastest_laps or position_history:
        logger.info(f"  -> Results: {len(fastest_laps)} fastest laps, {len(position_history)} position snapshots")

    return ResultsData(
        fastest_laps=fastest_laps,
        position_history=position_history
    )
