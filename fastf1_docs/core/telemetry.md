# Core: Telemetry Data

## Telemetry Object

High-frequency (200Hz) car and track data for analysis and visualization.

### Key Columns

| Column | Type | Description |
|--------|------|-------------|
| `Time` | timedelta | Session time from start |
| `X` | float | Track position X |
| `Y` | float | Track position Y |
| `Z` | float | Track position Z (elevation) |
| `Speed` | float | Car speed (km/h) |
| `Throttle` | int | Throttle percentage (0-100) |
| `Brake` | int | Brake percentage (0-100) |
| `DRS` | int | DRS engagement (0/1) |
| `Gear` | int | Current gear (-1 to 8) |
| `RPM` | int | Engine RPM |
| `Distance` | float | Distance traveled |

### Loading Telemetry

```python
session = fastf1.get_session(2024, 'Silverstone', 'R')
session.load(telemetry=True)

# Get lap telemetry
lap = session.laps.pick_fastest()
telemetry = lap.get_telemetry()

# Get driver session telemetry
driver_tel = session.laps.pick_driver('VER').get_telemetry()
```

### Filtering & Slicing

```python
# Get specific time range
tel_filtered = telemetry.slice_by_time(
    start_time='00:05:00',
    end_time='00:06:00'
)

# Get by distance
tel_slice = telemetry.slice_by_distance(
    start_distance=100,
    end_distance=200
)
```

### Methods

```python
telemetry.add_distance()
```
Calculate cumulative distance (auto-added).

```python
telemetry.add_relative_distance()
```
Add distance relative to lap start.

### Performance

⚠️ **Warning**: Loading full session telemetry for all drivers is slow and memory-intensive. Load selectively:

```python
# Load only for specific drivers
ver_laps = session.laps.pick_driver('VER')
ver_tel = ver_laps.get_telemetry()

# Or load single lap
fastest_tel = session.laps.pick_fastest().get_telemetry()
```

