# Core: Sessions & Data Loading

## Loading Data

### Main Functions

```python
fastf1.get_session(year, gp, session)
```
Load session data from a specific event.
- `year` (int): Season year
- `gp` (str): Grand Prix name or round number
- `session` (str): 'FP1', 'FP2', 'FP3', 'Q', 'S', 'R' (Sprint/Race)
- Returns: **Session** object

```python
fastf1.get_testing_session(year, test_num)
```
Load winter or in-season test data.

```python
fastf1.get_event(year, gp)
```
Get Event object with basic info (doesn't load session data).

## Session Object

### Key Properties

| Property | Type | Description |
|----------|------|-------------|
| `laps` | Laps | All laps in session |
| `results` | DataFrame | Driver results/standings |
| `telemetry` | Telemetry | Full session telemetry |
| `session_info` | dict | Metadata about session |
| `weather_data` | DataFrame | Track weather data |
| `track_status` | DataFrame | Track status history |
| `drivers` | list | Driver numbers in session |
| `event` | Event | Parent event object |

### Key Methods

```python
session.load()
```
Load/cache all data from API.

```python
session.load(telemetry=True)
```
Explicitly load telemetry (slow for large sessions).

### Common Usage

```python
session = fastf1.get_session(2024, 'Silverstone', 'R')
session.load()

# Access data
driver_laps = session.laps[session.laps['Driver'] == 'VER']
fastest = driver_laps.pick_fastest()
```

## Cache Management

```python
import fastf1

# Enable cache (default)
fastf1.set_cache_dir(path='path/to/cache')

# Clear cache
fastf1.clear_cache()
```

