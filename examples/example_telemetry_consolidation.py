"""
Example: Consolidate Telemetry from Multiple Drivers

Demonstrates how to combine telemetry from all drivers into a single
consolidated dataframe using distance along track as the primary index.

NOTE: This example uses normalized data (t=0 = session start) for proper
timing alignment across telemetry and events.
"""

from f1_replay.data_loader import DataLoader, TelemetryConsolidator, align_to_session_start


def example_consolidate_race():
    """
    Example 1: Consolidate race telemetry and compare drivers.
    """
    print("=" * 60)
    print("Example 1: Consolidate Race Telemetry")
    print("=" * 60)

    # Load data
    loader = DataLoader(cache_dir="race_data")
    weekend = loader.load_weekend(2024, 8)  # Monaco
    race = loader.load_session(2024, 8, "Race")

    # Normalize timing to start at t=0
    race = align_to_session_start(race)

    print(f"\nLoaded {len(race.telemetry)} drivers")
    print(f"Drivers: {sorted(race.telemetry.keys())}\n")

    # Create consolidator
    consolidator = TelemetryConsolidator(race, weekend)

    # Consolidate telemetry
    print("Consolidating telemetry using distance along track...")
    consolidated = consolidator.consolidate_telemetry(
        sample_every_n_points=10,  # Sample every 10 points for performance
        distance_threshold=50.0     # 50m from pit lane = pit
    )

    print(f"Consolidated shape: {consolidated.shape}")
    print(f"Columns: {consolidated.columns}\n")

    # Display first few rows
    print("First 5 distance points (sampled):")
    print(consolidated.head(5))
    print()


def example_pit_detection():
    """
    Example 2: Detect pit stops for each driver.
    """
    print("\n" + "=" * 60)
    print("Example 2: Detect Pit Stops")
    print("=" * 60)

    loader = DataLoader(cache_dir="race_data")
    weekend = loader.load_weekend(2024, 8)
    race = loader.load_session(2024, 8, "Race")

    consolidator = TelemetryConsolidator(race, weekend)

    print("\nPit stops detected:\n")
    for driver in sorted(race.telemetry.keys())[:5]:  # First 5 drivers
        pit_stops = consolidator.get_pit_stops(driver)
        if pit_stops:
            print(f"{driver}:")
            for entry_dist, exit_dist in pit_stops:
                pit_duration = exit_dist - entry_dist
                print(f"  Entry: {entry_dist:.1f}m, Exit: {exit_dist:.1f}m, Duration: {pit_duration:.1f}m")
        else:
            print(f"{driver}: No pit stops detected")
    print()


def example_compare_at_location():
    """
    Example 3: Compare drivers at a specific track location.
    """
    print("\n" + "=" * 60)
    print("Example 3: Compare Drivers at Track Location")
    print("=" * 60)

    loader = DataLoader(cache_dir="race_data")
    weekend = loader.load_weekend(2024, 8)
    race = loader.load_session(2024, 8, "Race")

    consolidator = TelemetryConsolidator(race, weekend)

    # Compare at specific distances
    distances = [100, 500, 1000, 1500]  # meters along track

    for distance in distances:
        print(f"\nAt {distance}m along track:")
        comparison = consolidator.compare_drivers_at_distance(
            distance=distance,
            window=100.0  # 100m window
        )

        # Show speeds
        speeds = [(drv, data['Speed']) for drv, data in comparison.items()
                 if data['Speed'] is not None]
        speeds.sort(key=lambda x: x[1], reverse=True)

        for driver, speed in speeds[:5]:  # Top 5 speeds
            on_track = comparison[driver]['OnTrack']
            location = "ON TRACK" if on_track else "PIT"
            print(f"  {driver}: {speed} km/h ({location})")


def example_telemetry_at_pit():
    """
    Example 4: Analyze telemetry around pit stops.
    """
    print("\n" + "=" * 60)
    print("Example 4: Analyze Pit Stop Telemetry")
    print("=" * 60)

    loader = DataLoader(cache_dir="race_data")
    weekend = loader.load_weekend(2024, 8)
    race = loader.load_session(2024, 8, "Race")

    consolidator = TelemetryConsolidator(race, weekend)

    # Get a driver with pit stops
    for driver in sorted(race.telemetry.keys()):
        pit_stops = consolidator.get_pit_stops(driver)
        if pit_stops:
            print(f"\nAnalyzing {driver}'s pit stop:\n")

            entry_dist, exit_dist = pit_stops[0]  # First pit stop

            # Get driver's full telemetry
            tel = race.telemetry[driver]

            # Filter to pit window
            pit_telemetry = tel.filter(
                (tel["Distance"] >= entry_dist - 50) &
                (tel["Distance"] <= exit_dist + 50)
            )

            if "Speed" in pit_telemetry.columns:
                min_speed = pit_telemetry["Speed"].min()
                max_speed = pit_telemetry["Speed"].max()
                print(f"  Entry distance: {entry_dist:.1f}m")
                print(f"  Exit distance: {exit_dist:.1f}m")
                print(f"  Pit duration: {(exit_dist - entry_dist):.1f}m")
                print(f"  Speed before pit: {max_speed} km/h")
                print(f"  Min speed in pit: {min_speed} km/h")

            break  # Just show first driver with pit stops


def example_on_track_analysis():
    """
    Example 5: Analyze time spent on track vs pit for each driver.
    """
    print("\n" + "=" * 60)
    print("Example 5: On-Track vs Pit Analysis")
    print("=" * 60)

    loader = DataLoader(cache_dir="race_data")
    weekend = loader.load_weekend(2024, 8)
    race = loader.load_session(2024, 8, "Race")

    consolidator = TelemetryConsolidator(race, weekend)

    # Consolidate
    consolidated = consolidator.consolidate_telemetry(sample_every_n_points=5)

    print("\nDistance on-track vs in-pit:\n")
    for driver in sorted(race.telemetry.keys())[:5]:
        on_track_col = f"{driver}_OnTrack"
        if on_track_col in consolidated.columns:
            on_track = consolidated[on_track_col].to_list()
            on_track_count = sum(1 for x in on_track if x)
            pit_count = sum(1 for x in on_track if not x)
            total = len(on_track)

            on_track_pct = (on_track_count / total * 100) if total > 0 else 0
            pit_pct = (pit_count / total * 100) if total > 0 else 0

            print(f"{driver}:")
            print(f"  On-track: {on_track_pct:.1f}%")
            print(f"  In pit:   {pit_pct:.1f}%")


if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("TELEMETRY CONSOLIDATION EXAMPLES")
    print("=" * 60)

    try:
        example_consolidate_race()
        example_pit_detection()
        example_compare_at_location()
        example_telemetry_at_pit()
        example_on_track_analysis()

        print("\n" + "=" * 60)
        print("All examples completed!")
        print("=" * 60 + "\n")

    except Exception as e:
        print(f"\nError: {e}")
        print("Make sure you have run: python examples/example_basic_usage.py first")
        print("This will cache the required data.\n")
