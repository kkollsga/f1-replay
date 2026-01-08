"""
Basic Usage Example - F1 Replay

Demonstrates:
1. Loading season catalog
2. Loading race weekend data
3. Loading session data
4. Accessing various data elements
"""

from f1_replay.managers import DataLoader


def main():
    """Run basic usage example."""
    print("="*70)
    print("F1 Replay - Basic Usage Example")
    print("="*70)

    # Initialize loader
    print("\n1. Initializing DataLoader...")
    loader = DataLoader(cache_dir="race_data")

    # TIER 1: Load seasons - returns Dict[int, List[EventInfo]]
    print("\n2. Loading F1 seasons catalog...")
    seasons = loader.load_seasons(years=[2024])

    print(f"\n   Available years: {list(seasons.keys())}")
    for year, events in seasons.items():
        print(f"\n   {year} - {len(events)} events:")
        for event in events[:5]:  # First 5 events
            print(f"     R{event.round_number:02d}: {event.name} ({event.location})")
        if len(events) > 5:
            print(f"     ... and {len(events) - 5} more")

    # TIER 2: Load race weekend (2024 Monaco - Round 8)
    print("\n3. Loading race weekend data (2024 Monaco)...")
    try:
        # Get event info first
        event = loader.get_event(2024, 8)
        weekend = loader.load_weekend(2024, 8, event)

        if weekend:
            event_info = weekend.event
            circuit = weekend.circuit

            print(f"\n   Event: {event_info.name}")
            print(f"   Location: {event_info.location}, {event_info.country}")
            print(f"   Date: {event_info.end_date}")
            print(f"   Timezone: {event_info.timezone}")

            print(f"\n   Circuit:")
            print(f"     Track length: {circuit.circuit_length:.0f}m")
            print(f"     Track points: {len(circuit.track.x)}")
            print(f"     Pit lane available: {circuit.pit_lane is not None}")
            if circuit.pit_lane:
                print(f"     Pit lane points: {len(circuit.pit_lane.x)}")
            print(f"     Track segments: {len(circuit.track_segments)}")

            for segment in circuit.track_segments:
                print(f"       - {segment.name}: {segment.start_distance:.0f}m - {segment.end_distance:.0f}m")

    except Exception as e:
        print(f"   Error loading weekend: {e}")
        print("   (This may occur if FastF1 is not accessible)")
        return

    # TIER 3: Load race session
    print("\n4. Loading race session data (Race)...")
    try:
        result = loader.load_session(2024, 8, "Race", event=event, circuit_length=circuit.circuit_length)

        if result:
            race = result.data
            metadata = race.metadata

            print(f"\n   Session: {metadata.session_type}")
            print(f"   Drivers: {len(metadata.drivers)} - {', '.join(metadata.drivers[:5])}...")
            print(f"   Track length: {metadata.track_length:.0f}m")
            print(f"   Total laps: {metadata.total_laps}")

            print(f"\n   Telemetry:")
            for driver in list(metadata.drivers)[:3]:
                if driver in race.telemetry:
                    tel = race.telemetry[driver]
                    print(f"     {driver}: {len(tel)} points")

                    # Show columns
                    if hasattr(tel, 'columns'):
                        cols = list(tel.columns)
                    elif hasattr(tel, 'schema'):
                        cols = list(tel.schema.names())
                    else:
                        cols = []

                    print(f"            Columns: {', '.join(cols[:5])}...")

            print(f"\n   Events:")
            print(f"     Track status events: {len(race.events.track_status)}")
            print(f"     Race control messages: {len(race.events.race_control)}")
            print(f"     Weather samples: {len(race.events.weather)}")

            print(f"\n   Results:")
            print(f"     Fastest laps: {len(race.results.fastest_laps)}")
            print(f"     Position snapshots: {len(race.results.position_history)}")

    except Exception as e:
        print(f"   Error loading session: {e}")
        print("   (This may occur if FastF1 is not accessible or session not cached)")
        import traceback
        traceback.print_exc()

    # Show cache info
    print("\n5. Cache information:")
    cache_info = loader.get_cache_info()
    print(f"   Cache directory: {cache_info['cache_dir']}")
    print(f"   Total pkl files: {cache_info['total_pkl_files']}")
    print(f"   Seasons cached: {cache_info['seasons_cached']}")

    print("\n" + "="*70)
    print("Example complete!")
    print("="*70)


if __name__ == "__main__":
    main()
