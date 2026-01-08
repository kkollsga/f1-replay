# Backend Code Changes - Reminder

## What Was Removed from processor.py

The following code was removed from `f1_replay/loaders/session/processor.py` to speed up processing:

```python
from f1_replay.loaders.session.order import OrderBuilder

# These lines were after circuit_length update (around line 293):
# Add position column to telemetry
print(f"  → Adding positions to telemetry...")
telemetry = OrderBuilder.add_positions_to_telemetry(telemetry)
print(f"  ✓ Positions added to {len(telemetry)} drivers")

# Add interval column to telemetry
print(f"  → Adding intervals to telemetry...")
telemetry = OrderBuilder.add_intervals_to_telemetry(telemetry)
print(f"  ✓ Intervals added")
```

## What These Functions Do

### `add_positions_to_telemetry` (order.py)
- Adds `position` column to each driver's telemetry
- Ranks drivers by `race_distance` (highest = P1)
- Fast calculation (~1-2 seconds)

### `add_intervals_to_telemetry` (order.py)
- Adds `interval` column (time gap to driver ahead)
- For P1: interval = 0
- For P > 1: interpolates when driver ahead passed same race_distance
- SLOW calculation (~10-30 seconds) - this was the bottleneck

## Current Telemetry Columns (Still Working)

These are calculated in `telemetry.py._add_track_distance_all()`:
- `track_distance` - position along track (0 to track_length meters)
- `race_distance` - total distance (laps * track_length + track_distance)
- `lap_number` - current lap from wrap detection
- `race_status` - Racing/Finished/Retired/PreSession

## Frontend Impact

Without `position` and `interval`:
- Frontend calculates position by sorting `race_distance` (works fine)
- Frontend shows distance gaps instead of time gaps (fallback behavior)

## To Re-enable (if needed)

Add back to `processor.py` after line 291:

```python
from f1_replay.loaders.session.order import OrderBuilder

# After: self.circuit_length = track_data.lap_distance / 10.0

# Option 1: Just positions (fast)
telemetry = OrderBuilder.add_positions_to_telemetry(telemetry)

# Option 2: Positions + intervals (slow but shows time gaps)
telemetry = OrderBuilder.add_positions_to_telemetry(telemetry)
telemetry = OrderBuilder.add_intervals_to_telemetry(telemetry)
```

## Helper Methods Added (session.py)

```python
# Get one telemetry point per lap
race.get_telemetry_every_lap("LEC")           # First point of each lap
race.get_telemetry_every_lap("LEC", offset=-1) # Last point of each lap

# Get telemetry at time intervals
race.get_telemetry_every_minute("LEC", interval=0.5)  # Every 30s
race.get_telemetry_every_minute("LEC")                 # Every 60s (default)
```
