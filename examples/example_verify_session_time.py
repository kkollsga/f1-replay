"""
Example: Verify Session Start Time and Time References

Demonstrates how to find and verify the true session start time (t0)
and understand how different data sources reference it.
"""

from f1_replay.data_loader import DataLoader, TimeNormalizer
import datetime


def example_session_start_verification():
    """
    Example 1: Verify the session start time and data source references.
    """
    print("=" * 70)
    print("Example 1: Session Start Time Verification")
    print("=" * 70)

    loader = DataLoader(cache_dir="race_data")
    race = loader.load_session(2024, 8, "Race")

    print("\n1. AUTHORITATIVE SESSION START (from metadata)")
    print("-" * 70)
    if race.metadata.t0_date_utc:
        print(f"   SessionMetadata.t0_date_utc: {race.metadata.t0_date_utc}")

        # Parse to understand the reference
        t0_str = race.metadata.t0_date_utc
        if 'T' in t0_str:
            dt = datetime.datetime.fromisoformat(t0_str.replace('Z', '+00:00'))
        else:
            dt = datetime.datetime.fromisoformat(t0_str)

        # Convert to seconds of day for reference
        seconds_of_day = dt.hour * 3600 + dt.minute * 60 + dt.second + dt.microsecond / 1e6

        print(f"   Parsed: {dt}")
        print(f"   Seconds of day: {seconds_of_day:.1f}s")
        print(f"   ✓ This is the TRUE session start time (t0)")
    else:
        print("   ⚠ No t0_date_utc in metadata")

    print("\n2. TELEMETRY REFERENCE")
    print("-" * 70)
    if race.telemetry:
        first_driver = sorted(race.telemetry.keys())[0]
        tel = race.telemetry[first_driver]

        if "SessionSeconds" in tel.columns:
            first_telemetry_time = float(tel["SessionSeconds"][0])
            first_datetime = tel["Date"][0] if "Date" in tel.columns else "Unknown"

            print(f"   First telemetry point ({first_driver}):")
            print(f"   Date: {first_datetime}")
            print(f"   SessionSeconds: {first_telemetry_time:.2f}s")
            print(f"   ✓ SessionSeconds is relative to session start (t0)")
            print(f"   → At t0 + {first_telemetry_time:.1f}s, telemetry began")

    print("\n3. EVENT REFERENCES (Track Status, Messages)")
    print("-" * 70)
    if race.events.track_status:
        first_event = race.events.track_status[0]
        print(f"   First track status event:")
        print(f"   Time field: {first_event.time:.1f}s")
        print(f"   Status: {first_event.status}")
        print(f"   Message: {first_event.message}")

        # This time field needs interpretation
        print(f"\n   How to interpret this time:")
        print(f"   → If t0_date_utc = session start")
        print(f"   → Then event.time is ABSOLUTE (seconds of day or timestamp)")
        print(f"   → Normalized time = event.time - t0_seconds_of_day")

    print("\n4. WEATHER DATA REFERENCE")
    print("-" * 70)
    if race.events.weather:
        first_weather = race.events.weather[0]
        print(f"   First weather sample:")
        print(f"   Time: {first_weather.time:.1f}s")
        print(f"   Temperature: {first_weather.temperature:.1f}°C")
        print(f"   ⚠ Weather time reference unclear - may be session-relative or absolute")

    print("\n" + "=" * 70)


def example_calculate_session_start():
    """
    Example 2: Calculate session start in different formats.
    """
    print("\n" + "=" * 70)
    print("Example 2: Calculate Session Start in Different Formats")
    print("=" * 70)

    loader = DataLoader(cache_dir="race_data")
    race = loader.load_session(2024, 8, "Race")

    if race.metadata.t0_date_utc:
        t0_str = race.metadata.t0_date_utc
        dt = datetime.datetime.fromisoformat(t0_str.replace('Z', '+00:00'))

        # Different representations
        seconds_of_day = dt.hour * 3600 + dt.minute * 60 + dt.second + dt.microsecond / 1e6
        epoch_seconds = dt.timestamp()

        print(f"\nSession Start Time (t0):")
        print(f"  ISO Format:     {t0_str}")
        print(f"  Parsed Date:    {dt}")
        print(f"  Seconds of day: {seconds_of_day:.1f}s  ← Use for event time conversion")
        print(f"  Unix timestamp: {epoch_seconds:.1f}s")
        print(f"  HH:MM:SS:mmm:   {dt.hour:02d}:{dt.minute:02d}:{dt.second:02d}.{dt.microsecond//1000:03d}")

        # How to use this
        print(f"\nUsage: Convert event times to session-relative")
        if race.events.track_status:
            first_event = race.events.track_status[0]
            event_seconds_of_day = first_event.time

            # Try to interpret
            normalized = first_event.time - seconds_of_day
            print(f"  Event raw time:      {event_seconds_of_day:.1f}s")
            print(f"  If absolute (SOD):   {normalized:.1f}s relative to t0")
            print(f"  Event message:       {first_event.message}")


def example_time_alignment_check():
    """
    Example 3: Check if times actually align.
    """
    print("\n" + "=" * 70)
    print("Example 3: Verify Time Alignment")
    print("=" * 70)

    loader = DataLoader(cache_dir="race_data")
    race = loader.load_session(2024, 8, "Race")

    # Get session start
    session_start = TimeNormalizer.get_session_start_time(race)
    print(f"\nDetected session start (t0): {session_start:.1f}s")

    # Check data ranges
    if race.telemetry:
        first_driver = sorted(race.telemetry.keys())[0]
        tel = race.telemetry[first_driver]

        if "SessionSeconds" in tel.columns:
            min_tel = float(tel["SessionSeconds"].min())
            max_tel = float(tel["SessionSeconds"].max())
            print(f"\nTelemetry range:")
            print(f"  Starts: {min_tel:.1f}s")
            print(f"  Ends:   {max_tel:.1f}s")
            print(f"  Duration: {max_tel - min_tel:.1f}s")

    if race.events.weather:
        weather_times = [w.time for w in race.events.weather]
        print(f"\nWeather range:")
        print(f"  Starts: {min(weather_times):.1f}s")
        print(f"  Ends:   {max(weather_times):.1f}s")

    if race.events.track_status:
        event_times = [e.time for e in race.events.track_status]
        print(f"\nTrack Status range:")
        print(f"  Starts: {min(event_times):.1f}s")
        print(f"  Ends:   {max(event_times):.1f}s")

    # Analysis
    print(f"\n" + "=" * 70)
    print("ANALYSIS:")
    print("=" * 70)

    if race.metadata.t0_date_utc:
        print("✓ t0_date_utc available - use as authoritative session start")
    else:
        print("⚠ t0_date_utc NOT available - using telemetry minimum as fallback")

    if race.telemetry and race.events.track_status:
        tel_start = float(race.telemetry[sorted(race.telemetry.keys())[0]]["SessionSeconds"].min())
        event_start = race.events.track_status[0].time

        print(f"\nTime references:")
        print(f"  Telemetry starts at: {tel_start:.1f}s")
        print(f"  Events start at:     {event_start:.1f}s")

        if abs(tel_start - event_start) > 10000:
            print(f"  → Large difference suggests events use different time reference (absolute)")
        elif abs(tel_start) < 100:
            print(f"  → Both close to 0, likely session-relative")


if __name__ == "__main__":
    print("\n" + "=" * 70)
    print("SESSION TIME VERIFICATION EXAMPLES")
    print("=" * 70)

    try:
        example_session_start_verification()
        example_calculate_session_start()
        example_time_alignment_check()

        print("\n" + "=" * 70)
        print("Verification complete!")
        print("=" * 70 + "\n")

    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()
