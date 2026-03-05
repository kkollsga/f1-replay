"""Event extraction and consolidation for session track status and race control data."""

from typing import Optional

import pandas as pd
import polars as pl

from f1_replay.log import logger
from f1_replay.models import EventsData, T0Info, TrackStatusEvent

# Message patterns from "Other" category that are routed to track_status/subtitle
# These are excluded from race_control to avoid duplicates
TRACK_STATUS_MESSAGE_PATTERNS = ["ABORTED START"]

# Regex pattern for messages with timestamps (e.g., "RACE WILL START AT 12:47")
# These become status subtitles, not race control messages
TIMESTAMP_MESSAGE_PATTERN = r"AT\s+\d{1,2}:\d{2}"


def parse_time_to_session_seconds(
    time_value, t0_seconds_of_day: Optional[float], t0_datetime
) -> float:
    """Parse FastF1 time value to session-relative seconds."""
    if time_value is None:
        return 0.0

    try:
        if hasattr(time_value, "total_seconds"):
            # Timedelta - already relative to session start
            return time_value.total_seconds()
        elif isinstance(time_value, pd.Timestamp):
            # Absolute timestamp
            if t0_datetime is not None:
                return (time_value - t0_datetime).total_seconds()
            elif t0_seconds_of_day is not None:
                time_float = (
                    time_value.hour * 3600
                    + time_value.minute * 60
                    + time_value.second
                    + time_value.microsecond / 1e6
                )
                return time_float - t0_seconds_of_day
            return 0.0
        else:
            return float(time_value)
    except Exception:
        return 0.0


def extract_track_status(
    f1_session,
    t0_datetime=None,
    t0_info: T0Info = None,
    track_status_patterns: list = None,
    timestamp_pattern: str = None,
) -> list[TrackStatusEvent]:
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
        "1": "AllClear",
        "2": "Yellow",
        "3": "Unknown",
        "5": "Red",
    }

    # Flag type to status mapping (from race_control_messages)
    FLAG_TO_STATUS = {
        "YELLOW": "Yellow",
        "DOUBLE YELLOW": "DoubleYellow",
        "GREEN": "AllClear",
        "CLEAR": "AllClear",
        "RED": "Red",
        "RED FLAG": "Red",
        "BLUE": "Blue",
        "BLACK AND WHITE": "BlackWhite",
        "BLACK WHITE": "BlackWhite",
        "CHEQUERED": "Chequered",
    }

    # =====================================================================
    # 1. Extract from session.track_status
    # track_status.Time is timedelta from t0_date - use directly (no offset!)
    # =====================================================================
    try:
        if hasattr(f1_session, "track_status") and f1_session.track_status is not None:
            ts_df = f1_session.track_status
            for _, row in ts_df.iterrows():
                try:
                    status_code = str(row.get("Status", ""))

                    # Skip Yellow/Red/SC/VSC codes - we get better data from race_control_messages
                    if status_code in ("2", "4", "5", "6", "7"):
                        continue

                    message = row.get("Message", "")
                    status = STATUS_MAP.get(status_code)
                    if status is None:
                        continue  # Skip unknown status codes

                    # Parse time - timedelta from t0_date, use directly
                    time_value = row.get("Time", None)
                    if time_value is not None and hasattr(time_value, "total_seconds"):
                        session_time = time_value.total_seconds()
                    else:
                        session_time = parse_time_to_session_seconds(time_value, None, t0_datetime)

                    events.append(
                        TrackStatusEvent(
                            session_time=session_time,
                            status=status,
                            message=str(message) if pd.notna(message) else status,
                            scope="Track",
                            sector=None,
                            driver_num="",
                        )
                    )
                except Exception:
                    pass
    except Exception:
        pass

    # =====================================================================
    # 2. Extract from race_control_messages (flags AND safety car)
    # =====================================================================
    try:
        messages_df = None
        if (
            hasattr(f1_session, "race_control_messages")
            and f1_session.race_control_messages is not None
        ):
            messages_df = f1_session.race_control_messages
        elif hasattr(f1_session, "messages") and f1_session.messages is not None:
            messages_df = f1_session.messages

        if messages_df is not None and len(messages_df) > 0 and "Category" in messages_df.columns:
            # Extract Flag messages
            flag_messages = messages_df[messages_df["Category"] == "Flag"]

            for _, row in flag_messages.iterrows():
                try:
                    flag_type = str(row.get("Flag", "")).upper()
                    message = str(row.get("Message", ""))
                    message_upper = message.upper()

                    # GREEN LIGHT - PIT EXIT OPEN indicates formation lap start
                    # This is the actual start signal, not the "FORMATION LAP" announcement
                    if "GREEN LIGHT" in message_upper and "PIT EXIT OPEN" in message_upper:
                        time_value = row.get("Time", None)
                        session_time = parse_time_to_session_seconds(time_value, None, t0_datetime)
                        events.append(
                            TrackStatusEvent(
                                session_time=session_time,
                                status="FormationLap",
                                message=message,
                                scope="Track",
                                sector=None,
                                driver_num="",
                            )
                        )
                        continue

                    # Clean up blue flag messages - remove "TIMED AT..." suffix
                    if "BLUE FLAG" in message_upper and "TIMED AT" in message_upper:
                        # Find "TIMED AT" and remove everything from that point
                        timed_at_pos = message.upper().find("TIMED AT")
                        if timed_at_pos > 0:
                            message = message[:timed_at_pos].strip()

                    scope = str(row.get("Scope", "Track"))
                    sector = int(row.get("Sector")) if pd.notna(row.get("Sector")) else None
                    driver_num = (
                        str(row.get("RacingNumber", ""))
                        if pd.notna(row.get("RacingNumber"))
                        else ""
                    )

                    # Parse time - absolute timestamp, convert to t0-relative
                    time_value = row.get("Time", None)
                    session_time = parse_time_to_session_seconds(time_value, None, t0_datetime)

                    # Map flag to status
                    status = FLAG_TO_STATUS.get(flag_type, "Flag")

                    events.append(
                        TrackStatusEvent(
                            session_time=session_time,
                            status=status,
                            message=message,
                            scope=scope,
                            sector=sector,
                            driver_num=driver_num,
                        )
                    )
                except Exception:
                    pass

            # =====================================================================
            # 3. Extract SafetyCar/VSC from race_control_messages
            # =====================================================================
            sc_messages = messages_df[messages_df["Category"] == "SafetyCar"]

            for _, row in sc_messages.iterrows():
                try:
                    message = str(row.get("Message", ""))
                    message_upper = message.upper()

                    # Parse time - absolute timestamp, convert to t0-relative
                    time_value = row.get("Time", None)
                    session_time = parse_time_to_session_seconds(time_value, None, t0_datetime)

                    # Determine SC/VSC type from message
                    if "VIRTUAL" in message_upper or "VSC" in message_upper:
                        if "ENDING" in message_upper:
                            status = "VSCEnding"
                        else:
                            status = "VSC"
                    elif "SAFETY CAR" in message_upper or "SC " in message_upper:
                        if "IN THIS LAP" in message_upper:
                            status = "SCEnding"  # SC coming in
                        else:
                            status = "SafetyCar"
                    else:
                        status = "SafetyCar"  # Default for Category=SafetyCar

                    events.append(
                        TrackStatusEvent(
                            session_time=session_time,
                            status=status,
                            message=message,
                            scope="Track",
                            sector=None,
                            driver_num="",
                        )
                    )
                except Exception:
                    pass

            # =====================================================================
            # 4. Extract Aborted Start / Formation Lap from race_control_messages
            # =====================================================================
            # These are in "Other" category
            other_messages = messages_df[messages_df["Category"] == "Other"]

            for _, row in other_messages.iterrows():
                try:
                    message = str(row.get("Message", ""))
                    message_upper = message.upper()

                    # Check for ABORTED START
                    if "ABORTED START" in message_upper:
                        time_value = row.get("Time", None)
                        session_time = parse_time_to_session_seconds(time_value, None, t0_datetime)

                        events.append(
                            TrackStatusEvent(
                                session_time=session_time,
                                status="AbortedStart",
                                message=message,
                                scope="Track",
                                sector=None,
                                driver_num="",
                            )
                        )

                    # Check for FORMATION LAP - parse actual start time from message
                    # Message format: "FORMATION LAP WILL START AT HH:MM"
                    elif "FORMATION LAP" in message_upper and "WILL START AT" in message_upper:
                        import re

                        # Extract HH:MM from message (this is LOCAL time)
                        time_match = re.search(r"WILL START AT\s*(\d{1,2}):(\d{2})", message_upper)
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

                            events.append(
                                TrackStatusEvent(
                                    session_time=session_time,
                                    status="FormationLap",
                                    message=message,
                                    scope="Track",
                                    sector=None,
                                    driver_num="",
                                )
                            )
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
        if e.status == "Chequered":
            chequered_time = e.session_time
            break

    if chequered_time is not None:
        # Keep all events up to and including chequered, filter out anything after
        events = [e for e in events if e.session_time <= chequered_time + 60]  # +60s buffer

    return events


def add_synthetic_events(track_status_list: list, t0_info) -> list:
    """
    Add synthetic events to track status: Session Start and Lights Out.

    Args:
        track_status_list: Existing track status events
        t0_info: Time reference (contains warmup_start_offset and lights_out_offset)

    Returns:
        Track status list with synthetic events added
    """
    # Add "Start of Session" event (WARM UP)
    if t0_info and t0_info.warmup_start_offset is not None:
        track_status_list.append(
            TrackStatusEvent(
                session_time=t0_info.warmup_start_offset,
                status="SessionStart",
                message="Start of Session",
                scope="Track",
                sector=None,
                driver_num="",
            )
        )

    # Add "Lights Out" event (RACE START)
    if t0_info and t0_info.lights_out_offset is not None:
        track_status_list.append(
            TrackStatusEvent(
                session_time=t0_info.lights_out_offset,
                status="LightsOut",
                message="",
                scope="Track",
                sector=None,
                driver_num="",
            )
        )

    return track_status_list


def integrate_rain_events(track_status_list: list, weather_df: pl.DataFrame) -> list:
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

    if weather_df is None or weather_df.height == 0:
        return track_status_list

    # Extract rain periods
    rain_events = WeatherExtractor.extract_rain_events(weather_df)

    if rain_events is None or rain_events.height == 0:
        return track_status_list

    # Add rain events to track status (as intervals with end_time already set)
    for row in rain_events.iter_rows(named=True):
        # Create Rain interval directly with start and end time
        track_status_list.append(
            TrackStatusEvent(
                session_time=row["start_time"],
                status="Rain",
                message="RAIN REPORTED",
                scope="Track",
                sector=None,
                driver_num="",
                end_time=row["end_time"],
            )
        )

    return track_status_list


def consolidate_track_status_intervals(track_status_list: list, t0_info) -> tuple[list, dict]:
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
    intervals = []
    open_statuses = {}  # Key: (scope, sector, status) -> event
    report = {
        "total_input_events": len(track_status_list),
        "total_output_intervals": 0,
        "merged_intervals": [],
        "instant_events": [],
        "ongoing_intervals": [],
    }

    for event in track_status_list:
        scope = event.scope or "Track"
        sector = event.sector
        status = event.status

        # Handle WARM UP (SessionStart / FormationLap opens, AbortedStart / LightsOut closes)
        if status == "SessionStart" or status == "FormationLap":
            # Open a new WarmUp interval (no message - "Formation Lap" pill handles display)
            key = ("Track", None, "WarmUp")
            open_statuses[key] = TrackStatusEvent(
                session_time=event.session_time,
                status="WarmUp",
                message="",
                scope="Track",
                sector=None,
                driver_num="",
                end_time=None,
            )
            continue

        # Handle AbortedStart - closes current WarmUp (but doesn't add as discrete event)
        if status == "AbortedStart":
            key = ("Track", None, "WarmUp")
            if key in open_statuses:
                start_event = open_statuses.pop(key)
                warmup_interval = TrackStatusEvent(
                    session_time=start_event.session_time,
                    status="WarmUp",
                    message=start_event.message,
                    scope="Track",
                    sector=None,
                    driver_num="",
                    end_time=event.session_time,
                )
                intervals.append(warmup_interval)
                report["merged_intervals"].append(
                    {
                        "type": "WarmUp",
                        "start_event": start_event.message,
                        "end_event": "AbortedStart",
                        "start_time": start_event.session_time,
                        "end_time": event.session_time,
                        "duration": event.session_time - start_event.session_time,
                    }
                )

            # Add AbortedStart as instant event
            intervals.append(event)
            report["instant_events"].append(
                {"status": "AbortedStart", "time": event.session_time, "message": event.message}
            )
            continue

        # Handle LightsOut - closes WarmUp and adds as instant event
        if status == "LightsOut":
            # Close any open WarmUp
            key = ("Track", None, "WarmUp")
            if key in open_statuses:
                start_event = open_statuses.pop(key)
                warmup_interval = TrackStatusEvent(
                    session_time=start_event.session_time,
                    status="WarmUp",
                    message=start_event.message,
                    scope="Track",
                    sector=None,
                    driver_num="",
                    end_time=event.session_time,
                )
                intervals.append(warmup_interval)
                report["merged_intervals"].append(
                    {
                        "type": "WarmUp",
                        "start_event": start_event.message,
                        "end_event": "LightsOut",
                        "start_time": start_event.session_time,
                        "end_time": event.session_time,
                        "duration": event.session_time - start_event.session_time,
                    }
                )

            # Add LightsOut as instant event
            intervals.append(event)
            report["instant_events"].append(
                {"status": "LightsOut", "time": event.session_time, "message": event.message}
            )
            continue

        # Handle AllClear - closes all open statuses in this scope/sector
        if status == "AllClear":
            # Close sector-specific statuses
            if sector is not None:
                keys_to_close = [
                    k for k in open_statuses.keys() if k[0] == scope and k[1] == sector
                ]
            else:
                # Track-wide clear closes everything in this scope
                keys_to_close = [k for k in open_statuses.keys() if k[0] == scope]

            for key in keys_to_close:
                start_event = open_statuses.pop(key)
                closed_interval = TrackStatusEvent(
                    session_time=start_event.session_time,
                    status=start_event.status,
                    message=start_event.message,
                    scope=start_event.scope,
                    sector=start_event.sector,
                    driver_num=start_event.driver_num,
                    end_time=event.session_time,
                )
                intervals.append(closed_interval)
                report["merged_intervals"].append(
                    {
                        "type": start_event.status,
                        "start_event": start_event.status,
                        "end_event": "AllClear",
                        "start_time": start_event.session_time,
                        "end_time": event.session_time,
                        "duration": event.session_time - start_event.session_time,
                        "sector": start_event.sector,
                    }
                )
            continue

        # Handle Rain events - already come as intervals with end_time set
        if status == "Rain":
            # Rain intervals are pre-consolidated, just add to intervals
            intervals.append(event)
            report["merged_intervals"].append(
                {
                    "type": "Rain",
                    "start_event": "Rain",
                    "end_event": "Rain",
                    "start_time": event.session_time,
                    "end_time": event.end_time,
                    "duration": event.end_time - event.session_time if event.end_time else 0,
                }
            )
            continue

        # Handle Chequered flag - instant event
        if status == "Chequered":
            intervals.append(event)
            report["instant_events"].append(
                {"status": "Chequered", "time": event.session_time, "message": event.message}
            )
            # Close all open statuses at chequered flag
            for start_event in open_statuses.values():
                closed_interval = TrackStatusEvent(
                    session_time=start_event.session_time,
                    status=start_event.status,
                    message=start_event.message,
                    scope=start_event.scope,
                    sector=start_event.sector,
                    driver_num=start_event.driver_num,
                    end_time=event.session_time,
                )
                intervals.append(closed_interval)
                report["merged_intervals"].append(
                    {
                        "type": start_event.status,
                        "start_event": start_event.status,
                        "end_event": "Chequered",
                        "start_time": start_event.session_time,
                        "end_time": event.session_time,
                        "duration": event.session_time - start_event.session_time,
                        "sector": start_event.sector,
                        "note": "Closed at Chequered flag",
                    }
                )
            open_statuses.clear()
            continue

        # Handle Blue flags and Black/White flags - discrete events (not intervals)
        # Each blue flag shown is a separate warning and should not be merged
        if status in ("Blue", "BlackWhite"):
            intervals.append(event)
            report["instant_events"].append(
                {"status": status, "time": event.session_time, "message": event.message}
            )
            continue

        # All other statuses (Yellow, DoubleYellow, Red, SafetyCar, SCEnding, VSC, etc.)
        # Open a new interval
        key = (scope, sector, status)
        open_statuses[key] = event

    # Close any remaining open statuses (end_time = None means ongoing)
    for start_event in open_statuses.values():
        ongoing_interval = TrackStatusEvent(
            session_time=start_event.session_time,
            status=start_event.status,
            message=start_event.message,
            scope=start_event.scope,
            sector=start_event.sector,
            driver_num=start_event.driver_num,
            end_time=None,  # Ongoing
        )
        intervals.append(ongoing_interval)
        report["ongoing_intervals"].append(
            {
                "type": start_event.status,
                "start_time": start_event.session_time,
                "sector": start_event.sector,
                "note": "Never closed (ongoing or session ended)",
            }
        )

    # Finalize report
    report["total_output_intervals"] = len(intervals)
    report["summary"] = {
        "merged_count": len(report["merged_intervals"]),
        "instant_count": len(report["instant_events"]),
        "ongoing_count": len(report["ongoing_intervals"]),
        "reduction": f"{report['total_input_events']} events -> {report['total_output_intervals']} intervals",
    }

    return intervals, report


def build_events(f1_session, t0_info=None) -> EventsData:
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
    t0_date = getattr(f1_session, "t0_date", None)

    # Convert t0_date to timestamp for absolute time conversions
    t0_datetime = None
    if t0_date is not None:
        if not isinstance(t0_date, pd.Timestamp):
            t0_date = pd.Timestamp(t0_date)
        t0_datetime = t0_date

    # Lazy imports to avoid circular imports
    from f1_replay.loaders.session.results import (
        extract_race_control_messages,
        extract_status_messages,
        extract_weather_data,
    )

    # Extract events - all session_time values relative to t0_date
    track_status_list = extract_track_status(
        f1_session, t0_datetime, t0_info, TRACK_STATUS_MESSAGE_PATTERNS, TIMESTAMP_MESSAGE_PATTERN
    )
    race_control_list = extract_race_control_messages(f1_session, t0_datetime)
    status_messages_list = extract_status_messages(f1_session, t0_datetime, t0_info)
    weather_list = extract_weather_data(f1_session, t0_datetime)

    # Build weather DataFrame temporarily for rain extraction (not stored)
    weather_df = (
        pl.DataFrame(
            [
                {
                    "temperature": sample.temperature,
                    "humidity": sample.humidity,
                    "wind_speed": sample.wind_speed,
                    "wind_direction": sample.wind_direction,
                    "track_temperature": sample.track_temperature,
                    "rainfall": sample.rainfall,
                    "time": sample.time,
                    "session_time": sample.session_time,
                }
                for sample in weather_list
            ]
        )
        if weather_list
        else pl.DataFrame()
    )

    # Add synthetic events (SessionStart, LightsOut) to track status
    track_status_list = add_synthetic_events(track_status_list, t0_info)

    # Integrate rain events into track status
    track_status_list = integrate_rain_events(track_status_list, weather_df)

    # Sort track status by session_time
    track_status_list = sorted(
        track_status_list,
        key=lambda e: e.session_time if e.session_time is not None else float("inf"),
    )

    # Consolidate discrete events into intervals with start/end times
    track_status_list, consolidation_report = consolidate_track_status_intervals(
        track_status_list, t0_info
    )

    # Convert lists to Polars DataFrames for efficient storage and querying
    track_status_df = (
        pl.DataFrame(
            [
                {
                    "session_time": event.session_time,
                    "status": event.status,
                    "message": event.message,
                    "scope": event.scope,
                    "sector": event.sector,
                    "driver_num": event.driver_num,
                    "end_time": event.end_time,
                }
                for event in track_status_list
            ]
        )
        if track_status_list
        else pl.DataFrame()
    )

    # Sort by session_time to ensure chronological order after consolidation
    if track_status_df.height > 0:
        track_status_df = track_status_df.sort("session_time")

    # Wrap DataFrame with consolidation report
    from f1_replay.models.session import TrackStatusWithReport

    track_status_with_report = TrackStatusWithReport(track_status_df, consolidation_report)

    race_control_df = (
        pl.DataFrame(
            [
                {"message": msg.message, "time": msg.time, "session_time": msg.session_time}
                for msg in race_control_list
            ]
        )
        if race_control_list
        else pl.DataFrame()
    )

    status_messages_df = (
        pl.DataFrame(status_messages_list) if status_messages_list else pl.DataFrame()
    )

    if track_status_list or race_control_list:
        logger.info(
            f"  -> Events: {len(track_status_list)} track status intervals ({consolidation_report['summary']['merged_count']} merged), {len(race_control_list)} messages, {len(status_messages_list)} status subtitles"
        )

    return EventsData(
        track_status=track_status_with_report,
        race_control=race_control_df,
        status_messages=status_messages_df,
    )
