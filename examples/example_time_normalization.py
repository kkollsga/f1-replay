"""
Example: Time Normalization

Demonstrates how to normalize timing across telemetry, events, and weather data
to start at t=0 from session start.
"""

from f1_replay.data_loader import DataLoader, TimeNormalizer, align_to_session_start


def example_timing_report():
    """
    Example 1: Generate a timing alignment report.

    Shows where each data source starts and how they're offset from session start.
    """
    print("=" * 60)
    print("Example 1: Timing Alignment Report")
    print("=" * 60)

    loader = DataLoader(cache_dir="race_data")
    race = loader.load_session(2024, 8, "Race")

    # Print timing report
    TimeNormalizer.print_timing_report(race)


def example_normalize_all():
    """
    Example 2: Normalize all timing to start at t=0.
    """
    print("\n" + "=" * 60)
    print("Example 2: Normalize All Data to t=0")
    print("=" * 60)

    loader = DataLoader(cache_dir="race_data")
    race = loader.load_session(2024, 8, "Race")

    print("\nBefore normalization:")
    print(f"  Telemetry starts at: {race.telemetry['VER']['SessionSeconds'][0]:.1f}s")
    print(f"  Weather starts at:   {race.events.weather[0].time:.1f}s")
    if race.events.track_status:
        print(f"  Track status at:     {race.events.track_status[0].time:.1f}s")

    # Normalize
    normalized = align_to_session_start(race)

    print("\nAfter normalization:")
    print(f"  Telemetry starts at: {normalized.telemetry['VER']['SessionSeconds'][0]:.1f}s")
    print(f"  Weather starts at:   {normalized.events.weather[0].time:.1f}s")
    if normalized.events.track_status:
        print(f"  Track status at:     {normalized.events.track_status[0].time:.1f}s")

    print("\nNow all data is aligned! Events happen at their actual time relative to session start.")


def example_compare_normalized_vs_raw():
    """
    Example 3: Compare raw vs normalized event times.
    """
    print("\n" + "=" * 60)
    print("Example 3: Raw vs Normalized Times")
    print("=" * 60)

    loader = DataLoader(cache_dir="race_data")
    race = loader.load_session(2024, 8, "Race")

    # Get session start offset
    offset = TimeNormalizer.get_time_offset(race)

    print(f"\nSession start offset: {offset:.1f}s")
    print(f"(Subtract this from any time to align with session start)")

    print("\nTrack Status Events (first 5):")
    print(f"{'Raw Time':>12} {'Normalized':>12} {'Event':<40}")
    print("-" * 66)

    for event in race.events.track_status[:5]:
        normalized_time = event.time - offset
        print(f"{event.time:>12.1f}s {normalized_time:>12.1f}s {event.message[:40]}")

    print("\nWeather Samples (first 5):")
    print(f"{'Raw Time':>12} {'Normalized':>12} {'Temp':>6} {'Humidity':>10}")
    print("-" * 44)

    for weather in race.events.weather[:5]:
        normalized_time = weather.time - offset
        print(f"{weather.time:>12.1f}s {normalized_time:>12.1f}s {weather.temperature:>6.1f}°C {weather.humidity:>9.1f}%")


def example_telemetry_alignment():
    """
    Example 4: Check telemetry alignment across drivers.
    """
    print("\n" + "=" * 60)
    print("Example 4: Telemetry Start Time Alignment")
    print("=" * 60)

    loader = DataLoader(cache_dir="race_data")
    race = loader.load_session(2024, 8, "Race")

    print("\nDriver telemetry start times (raw):")
    drivers = sorted(race.telemetry.keys())[:5]

    for driver in drivers:
        tel = race.telemetry[driver]
        if "SessionSeconds" in tel.columns:
            start_time = float(tel["SessionSeconds"][0])
            print(f"  {driver}: {start_time:.1f}s")

    # Normalize
    normalized = align_to_session_start(race)

    print("\nDriver telemetry start times (normalized to t=0):")
    for driver in drivers:
        tel = normalized.telemetry[driver]
        if "SessionSeconds" in tel.columns:
            start_time = float(tel["SessionSeconds"][0])
            print(f"  {driver}: {start_time:.1f}s")

    print("\nAll drivers now start at t=0! ✓")


def example_analysis_on_normalized_data():
    """
    Example 5: Perform analysis on normalized data.
    """
    print("\n" + "=" * 60)
    print("Example 5: Analysis on Normalized Data")
    print("=" * 60)

    loader = DataLoader(cache_dir="race_data")
    weekend = loader.load_weekend(2024, 8)
    race = loader.load_session(2024, 8, "Race")

    # Normalize
    normalized = align_to_session_start(race)

    print("\nAnalyzing normalized data:\n")

    # Find when first track status event occurs
    if normalized.events.track_status:
        first_event = normalized.events.track_status[0]
        print(f"First track status event at: {first_event.time:.1f}s")
        print(f"  {first_event.status}: {first_event.message}")

        # Find corresponding telemetry
        ver_tel = normalized.telemetry["VER"]
        if "SessionSeconds" in ver_tel.columns:
            # Find telemetry at that time
            times = ver_tel["SessionSeconds"].to_list()
            idx = min(range(len(times)), key=lambda i: abs(times[i] - first_event.time))
            tel_point = ver_tel.row(idx, named=True)

            print(f"  VER telemetry at that time:")
            print(f"    Speed: {tel_point.get('Speed', 'N/A')} km/h")
            print(f"    Position: ({tel_point.get('X', 'N/A'):.0f}, {tel_point.get('Y', 'N/A'):.0f})")

    # Find weather at a specific time (e.g., 500s into race)
    target_time = 500.0
    print(f"\nWeather at {target_time:.0f}s into race:")

    closest_weather = min(
        normalized.events.weather,
        key=lambda w: abs(w.time - target_time)
    )

    print(f"  Temperature: {closest_weather.temperature:.1f}°C")
    print(f"  Track temp: {closest_weather.track_temperature:.1f}°C")
    print(f"  Humidity: {closest_weather.humidity:.0f}%")
    print(f"  Wind: {closest_weather.wind_speed:.1f} m/s ({closest_weather.wind_direction})")


if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("TIME NORMALIZATION EXAMPLES")
    print("=" * 60)

    try:
        example_timing_report()
        example_normalize_all()
        example_compare_normalized_vs_raw()
        example_telemetry_alignment()
        example_analysis_on_normalized_data()

        print("\n" + "=" * 60)
        print("All examples completed!")
        print("=" * 60 + "\n")

    except Exception as e:
        print(f"\nError: {e}")
        print("Make sure you have run: python examples/example_basic_usage.py first")
        print("This will cache the required data.\n")
