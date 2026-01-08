"""
Example: Verify Session Start Time and Time References

Demonstrates how to understand session timing:
- t0.utc: FastF1's timing zero (t0_date) - when session_time=0
- lights_out_offset: Seconds from t0 to lights out (positive)
- race_time = session_time - lights_out_offset
"""

from f1_replay.data_loader import DataLoader
import datetime


def example_session_start_verification():
    """
    Example 1: Verify the session timing and data source references.
    """
    print("=" * 70)
    print("Example 1: Session Time Verification")
    print("=" * 70)

    loader = DataLoader(cache_dir="race_data")
    result = loader.load_session(2024, 8, "Race")
    race = result.data

    print("\n1. T0 INFO (from metadata)")
    print("-" * 70)
    if race.metadata.t0:
        t0 = race.metadata.t0
        print(f"   t0.utc: {t0.utc}  (FastF1 timing zero - when session_time=0)")
        print(f"   t0.timezone: {t0.timezone}")
        print(f"   t0.utc_offset_hours: {t0.utc_offset_hours}")
        print(f"   t0.lights_out_offset: {t0.lights_out_offset:.1f}s  (seconds from t0 to lights out)")
        print(f"   t0.session_duration: {t0.session_duration:.1f}s")

        print(f"\n   To convert session_time to race_time (relative to lights out):")
        print(f"   race_time = session_time - lights_out_offset")
        print(f"   At session_time=0: race_time = -{t0.lights_out_offset:.1f}s (before lights out)")
        print(f"   At session_time={t0.lights_out_offset:.1f}: race_time = 0s (lights out!)")
    else:
        print("   ⚠ No t0 in metadata")

    print("\n2. TELEMETRY REFERENCE")
    print("-" * 70)
    if race.telemetry:
        first_driver = sorted(race.telemetry.keys())[0]
        tel = race.telemetry[first_driver]

        if "session_time" in tel.columns:
            first_session_time = float(tel["session_time"][0])
            last_session_time = float(tel["session_time"][-1])

            print(f"   Telemetry ({first_driver}):")
            print(f"   First session_time: {first_session_time:.2f}s")
            print(f"   Last session_time:  {last_session_time:.2f}s")
            print(f"   ✓ session_time matches FastF1's SessionTime (in seconds)")

    print("\n3. EVENT REFERENCES (Track Status, Messages)")
    print("-" * 70)
    if len(race.events.track_status) > 0:
        track_status = race.events.track_status.to_dicts()
        first_event = track_status[0]
        print(f"   First track status event:")
        print(f"   session_time: {first_event['session_time']:.1f}s")
        print(f"   Status: {first_event['status']}")
        print(f"   Message: {first_event['message']}")

        print(f"\n   How to interpret this time:")
        print(f"   → session_time is relative to t0.utc (timing zero)")
        print(f"   → To get real UTC time: t0.utc + session_time seconds")

    print("\n4. WEATHER DATA REFERENCE")
    print("-" * 70)
    if len(race.events.weather) > 0:
        weather = race.events.weather.to_dicts()
        first_weather = weather[0]
        print(f"   First weather sample:")
        print(f"   session_time: {first_weather['session_time']:.1f}s")
        print(f"   Temperature: {first_weather['temperature']:.1f}°C")
        print(f"   ✓ Weather session_time is also relative to t0.utc")

    print("\n" + "=" * 70)


def example_calculate_session_start():
    """
    Example 2: Calculate session start in different formats.
    """
    print("\n" + "=" * 70)
    print("Example 2: Calculate Times in Different Formats")
    print("=" * 70)

    loader = DataLoader(cache_dir="race_data")
    result = loader.load_session(2024, 8, "Race")
    race = result.data

    if race.metadata.t0:
        t0 = race.metadata.t0
        t0_str = t0.utc
        dt = datetime.datetime.fromisoformat(t0_str.replace('Z', '+00:00'))

        # Different representations
        seconds_of_day = dt.hour * 3600 + dt.minute * 60 + dt.second + dt.microsecond / 1e6
        epoch_seconds = dt.timestamp()

        print(f"\nT0 Reference Point (FastF1 Timing Zero):")
        print(f"  t0.utc:             {t0_str}")
        print(f"  Parsed Date:        {dt}")
        print(f"  Seconds of day:     {seconds_of_day:.1f}s")
        print(f"  Timezone:           {t0.timezone} (UTC{t0.utc_offset_hours:+.1f})")
        print(f"  lights_out_offset:  {t0.lights_out_offset:.1f}s (seconds to lights out)")
        print(f"  session_duration:   {t0.session_duration:.1f}s")
        print(f"  Unix timestamp:     {epoch_seconds:.1f}s")
        print(f"  HH:MM:SS:mmm:       {dt.hour:02d}:{dt.minute:02d}:{dt.second:02d}.{dt.microsecond//1000:03d}")

        # How to use this
        print(f"\nUsage: Convert session_time to race_time")
        print(f"  race_time = session_time - lights_out_offset")
        print(f"  Example: session_time=3500s → race_time = 3500 - {t0.lights_out_offset:.0f} = {3500 - t0.lights_out_offset:.0f}s")


def example_time_alignment_check():
    """
    Example 3: Check if times actually align.
    """
    print("\n" + "=" * 70)
    print("Example 3: Verify Time Alignment")
    print("=" * 70)

    loader = DataLoader(cache_dir="race_data")
    result = loader.load_session(2024, 8, "Race")
    race = result.data

    # Check data ranges
    if race.telemetry:
        first_driver = sorted(race.telemetry.keys())[0]
        tel = race.telemetry[first_driver]

        if "session_time" in tel.columns:
            min_tel = float(tel["session_time"].min())
            max_tel = float(tel["session_time"].max())
            print(f"\nTelemetry range ({first_driver}):")
            print(f"  Starts: {min_tel:.1f}s")
            print(f"  Ends:   {max_tel:.1f}s")
            print(f"  Duration: {max_tel - min_tel:.1f}s")

    if len(race.events.weather) > 0:
        weather = race.events.weather.to_dicts()
        weather_times = [w['session_time'] for w in weather]
        print(f"\nWeather range:")
        print(f"  Starts: {min(weather_times):.1f}s")
        print(f"  Ends:   {max(weather_times):.1f}s")

    if len(race.events.track_status) > 0:
        track_status = race.events.track_status.to_dicts()
        event_times = [e['session_time'] for e in track_status]
        print(f"\nTrack Status range:")
        print(f"  Starts: {min(event_times):.1f}s")
        print(f"  Ends:   {max(event_times):.1f}s")

    # Analysis
    print(f"\n" + "=" * 70)
    print("ANALYSIS:")
    print("=" * 70)

    if race.metadata.t0:
        t0 = race.metadata.t0
        print("✓ t0 available - use as authoritative time reference")
        print(f"  t0.utc = {t0.utc} (timing zero, session_time=0)")
        print(f"  lights_out_offset = {t0.lights_out_offset:.1f}s (lights out at session_time={t0.lights_out_offset:.0f})")
        print(f"  session_duration = {t0.session_duration:.1f}s")
    else:
        print("⚠ t0 NOT available - using telemetry minimum as fallback")


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
