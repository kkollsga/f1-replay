# F1 Race Viewer - Data Structure & Requirements

Complete mapping of Flask app data requirements to backend data classes.

## Overview

The Flask app requires data from the `Race` class, which wraps two immutable data structures:
- **SessionDataset** - Complete session data (telemetry, track, events)
- **RaceWeekendData** - Weekend metadata (event info, schedule)

---

## API Endpoints & Data Requirements

### 1. **GET /api/race_info** - Basic Race Information

**Data Class:** `Race` (combines `SessionDataset.metadata` + `RaceWeekendData`)

| Endpoint Field | Source | Type | Example |
|---|---|---|---|
| `year` | `Race.year` (RaceWeekendData) | int | `2024` |
| `event_name` | `Race.event_name` (RaceWeekendData) | str | `"Abu Dhabi Grand Prix"` |
| `race_name` | `Race.event_name` | str | `"Abu Dhabi Grand Prix"` |
| `location` | `Race.location` (RaceWeekendData) | str | `"Yas Island"` |
| `track_length` | `Race.metadata['track_length']` | float | `5281.0` |
| `total_laps` | `Race.metadata['total_laps']` | int | `58` |
| `fastest_lap` | `Race.fastest_laps[0]['lap']` (SessionDataset) | int | `32` |
| `race_start_time` | `Race.metadata['start_time']` | float | `0.0` |
| `t0_date` | `Race.metadata['t0_date_utc']` | datetime | `"2024-12-08T13:00:00Z"` |
| `t0_time_local` | `Race.metadata['start_time_local']` | str | `"17:00:00"` |
| `t0_time_formatted` | `Race.t0_time()` method | str | `"17:00:00 (UTC+4)"` |
| `gmt_offset` | Calculated from t0_date_utc + start_time_local | int | `14400` (seconds) |
| `global_min_time` | `Race.metadata['time_range']['start']` | float | `0.0` |
| `rotation` | `Race.metadata['rotation']` | float | `0.0` |
| `marshal_sectors` | `Race.metadata['marshal_sectors']` | list | `[]` |

**Data Class Source:**
```python
SessionDataset.metadata = {
    'year': int,
    'round': int,
    'event_name': str,
    'session_type': str,
    'drivers': List[str],
    'track_length': float,
    'total_laps': int,
    't0_date_utc': datetime,
    'start_time_local': str,
    'rotation': float,
    'marshal_sectors': List,
    'time_range': {'start': float},
    'driver_colors': {'VER': '#0600EF', ...}
}

RaceWeekendData = {
    'year': int,
    'round_number': int,
    'event_name': str,
    'location': str,
    'country': str,
    'circuit_name': str,
    'timezone': str,
    'event_date': str,
    'session_schedule': Dict[str, str],
    'available_sessions': List[str]
}
```

---

### 2. **GET /api/track** - Track Geometry

**Data Class:** `SessionDataset.track` (Dict of numpy arrays)

| Field | Type | Source | Description |
|---|---|---|---|
| `x` | list[float] | `track['X'].tolist()` | X coordinates (meters) |
| `y` | list[float] | `track['Y'].tolist()` | Y coordinates (meters) |
| `distance` | list[float] | `track['Distance'].tolist()` (optional) | Distance along track (meters) |

**Data Class Source:**
```python
SessionDataset.track = {
    'X': np.ndarray (float32),  # ~10,000-15,000 points per lap
    'Y': np.ndarray (float32),
    'Distance': np.ndarray (float32)  # Optional
}

# Built from fastest lap telemetry:
fastest_lap = f1_session.laps.pick_fastest()
tel = fastest_lap.get_telemetry()
track_data['X'] = tel['X'].astype(np.float32).values
track_data['Y'] = tel['Y'].astype(np.float32).values
track_data['Distance'] = tel['Distance'].astype(np.float32).values
```

---

### 3. **GET /api/pit_lane** - Pit Lane Geometry

**Data Class:** `SessionDataset.pit_lane` (Optional Dict of numpy arrays)

| Field | Type | Source | Description |
|---|---|---|---|
| `available` | bool | pit_lane is not None | Pit lane available |
| `x` | list[float] | `pit_lane['X'].tolist()` | X coordinates |
| `y` | list[float] | `pit_lane['Y'].tolist()` | Y coordinates |

**Data Class Source:**
```python
SessionDataset.pit_lane = {
    'X': np.ndarray (float32),  # Built from in-lap + out-lap telemetry
    'Y': np.ndarray (float32),
}

# Built from pit stop laps:
in_laps = f1_session.laps.pick_box_laps(which='in')
out_laps = f1_session.laps.pick_box_laps(which='out')
# Combine telemetry from both, deduplicate, clip to pit lane section
```

---

### 4. **GET /api/telemetry** - Driver Telemetry Data

**Data Class:** `SessionDataset.telemetry` (Dict mapping driver code → Polars DataFrame)

**Format:**
```json
{
  "VER": {
    "info": { "abbreviation": "VER", "color": "#0600EF" },
    "telemetry": {
      "Time": [timedelta, ...],
      "SessionTime": [timedelta, ...],
      "Distance": [float, ...],
      "X": [float, ...],
      "Y": [float, ...],
      "Speed": [int, ...],
      "Throttle": [int, ...],
      "Brake": [int, ...],
      "DRS": [int, ...],
      "Gear": [int, ...],
      "RPM": [int, ...],
      "SessionSeconds": [float, ...],
      "LapNumber": [int, ...]
    }
  },
  "HAM": { ... },
  ...
}
```

**Data Class Source:**
```python
SessionDataset.telemetry = {
    'VER': pl.DataFrame,  # Polars DataFrame (2-5x memory efficient vs Pandas)
    'HAM': pl.DataFrame,
    ...
}

# Columns in each Polars DataFrame:
# - Time (timedelta): Time within lap
# - SessionTime (timedelta): Time from session start
# - Distance (float): Distance along track (meters)
# - X, Y (float): Track position
# - Speed (int): Speed (km/h)
# - Throttle (int): 0-100
# - Brake (int): 0-100
# - DRS (int): 0 or 1
# - Gear (int): -1 to 8
# - RPM (int): Engine revs
# - SessionSeconds (float): Session time in seconds
# - LapNumber (int): Lap number

# Built from all laps per driver, converted from Pandas:
driver_laps = f1_session.laps.pick_drivers(driver)
all_telemetry = []
for _, lap in driver_laps.iterrows():
    tel = lap.get_telemetry()  # Returns Pandas DataFrame
    tel['LapNumber'] = lap['LapNumber']
    tel['SessionTime'] = lap['LapStartTime'] + tel['Time']
    all_telemetry.append(tel)

combined = pd.concat(all_telemetry)
telemetry_data[driver] = pl.from_pandas(combined)  # Convert to Polars
```

**Driver Colors:**
```python
# Extracted from FastF1 session results:
SessionDataset.metadata['driver_colors'] = {
    'VER': '#0600EF',  # Red Bull colors
    'HAM': '#00D2BE',  # Mercedes colors
    ...
}
```

---

### 5. **GET /api/schedule/<year>** - Season Schedule

**Data Class:** `RaceManager.catalog` → `F1Catalog.seasons[year]` → `SeasonInfo.races`

**Format:**
```json
{
  "races": [
    {
      "round": 1,
      "name": "Bahrain Grand Prix",
      "event_name": "Bahrain Grand Prix",
      "location": "Sakhir",
      "country": "Bahrain",
      "date": "2024-03-02"
    },
    ...
  ]
}
```

**Data Class Source:**
```python
F1Catalog = {
    'seasons': {
        2024: SeasonInfo(
            year=2024,
            total_rounds=24,
            races=[
                RaceInfo(
                    round_number=1,
                    event_name="Bahrain Grand Prix",
                    location="Sakhir",
                    country="Bahrain",
                    date="2024-03-02",
                    circuit_name="Bahrain International Circuit"
                ),
                ...
            ]
        ),
        2023: SeasonInfo(...),
        ...
    },
    'last_updated': "2024-12-20T10:30:45.123456"
}

# Built from FastF1 schedule:
schedule = fastf1.get_event_schedule(year)
for _, row in schedule.iterrows():
    race = RaceInfo(
        round_number=int(row['RoundNumber']),
        event_name=row['EventName'],
        location=row['Location'],
        country=row['Country'],
        date=str(row['EventDate']),
        circuit_name=row['Circuit']
    )
```

---

### 6. **GET /api/track_status** - Track Status Events

**Data Class:** `SessionDataset.track_status` (List[Dict])

**Expected Format:**
```json
[
  {
    "time": 0.0,
    "status": "AllClear",
    "message": "All clear"
  },
  {
    "time": 120.5,
    "status": "Yellow",
    "message": "Yellow flag"
  },
  ...
]
```

**Data Class Source:**
```python
SessionDataset.track_status = [
    {
        'time': float (session seconds),
        'status': str,  # AllClear, Yellow, SafetyCar, VirtualSafetyCar, Red, etc.
        'message': str,
    },
    ...
]

# TODO: Extract from f1_session.track_status or similar
```

---

### 7. **GET /api/race_control** - Race Control Messages

**Data Class:** `SessionDataset.race_control` (List[Dict])

**Expected Format:**
```json
[
  {
    "time": 0.0,
    "message": "Safety car deployed"
  },
  ...
]
```

**Data Class Source:**
```python
SessionDataset.race_control = [
    {
        'time': float (session seconds),
        'message': str,
    },
    ...
]

# TODO: Extract from f1_session.messages or race_control_messages
```

---

### 8. **GET /api/weather** - Weather Data Samples

**Data Class:** `SessionDataset.weather` (List[Dict])

**Expected Format:**
```json
[
  {
    "time": 0.0,
    "temperature": 18.5,
    "humidity": 65,
    "wind_speed": 5.2,
    "track_temperature": 22.0
  },
  ...
]
```

**Data Class Source:**
```python
SessionDataset.weather = [
    {
        'time': float (session seconds),
        'temperature': float (°C),
        'humidity': float (0-100),
        'wind_speed': float (m/s),
        'track_temperature': float (°C),
    },
    ...
]

# TODO: Extract from f1_session.weather_data or similar
```

---

### 9. **GET /api/fastest_lap_history** - Fastest Lap Progression

**Data Class:** `SessionDataset.fastest_laps` (List[Dict])

**Expected Format:**
```json
[
  {
    "lap": 2,
    "driver": "VER",
    "time": 92.453,
    "lap_time": 92453
  },
  {
    "lap": 5,
    "driver": "HAM",
    "time": 91.823,
    "lap_time": 91823
  },
  ...
]
```

**Data Class Source:**
```python
SessionDataset.fastest_laps = [
    {
        'lap': int,
        'driver': str (abbreviation),
        'time': float (seconds),
        'lap_time': int (milliseconds),
    },
    ...
]

# TODO: Track fastest lap progression through session
```

---

### 10. **GET /api/intervals** - Gap to Leader Per Lap

**Data Class:** `SessionDataset.intervals` (List[Dict])

**Expected Format:**
```json
[
  {
    "lap": 1,
    "standings": [
      { "driver": "VER", "interval": 0.0 },
      { "driver": "LEC", "interval": 0.234 },
      ...
    ]
  },
  {
    "lap": 2,
    "standings": [ ... ]
  },
  ...
]
```

**Data Class Source:**
```python
SessionDataset.intervals = [
    {
        'lap': int,
        'standings': [
            {
                'driver': str (abbreviation),
                'interval': float (seconds to leader),
            },
            ...
        ]
    },
    ...
]

# TODO: Extract from laps and calculate intervals
```

---

### 11. **GET /api/position_history** - Position Snapshots

**Data Class:** `SessionDataset.position_history` (List[Dict])

**Expected Format:**
```json
[
  {
    "time": 300.0,
    "standings": [
      { "position": 1, "driver": "VER", "gap": 0.0 },
      { "position": 2, "driver": "LEC", "gap": 1.234 },
      ...
    ]
  },
  {
    "time": 600.0,
    "standings": [ ... ]
  },
  ...
]
```

**Data Class Source:**
```python
SessionDataset.position_history = [
    {
        'time': float (session seconds),
        'standings': [
            {
                'position': int (1-20),
                'driver': str (abbreviation),
                'gap': float (seconds to leader),
            },
            ...
        ]
    },
    ...
]

# TODO: Extract from telemetry snapshots at intervals
```

---

## Data Hierarchy

```
Flask App
  ↓
Race (race.py)
  ├── SessionDataset (immutable, cached)
  │   ├── metadata {Dict}
  │   ├── telemetry {Dict[str, pl.DataFrame]}
  │   ├── track {Dict[str, np.ndarray]}
  │   ├── pit_lane {Dict[str, np.ndarray]}
  │   ├── position_history {List[Dict]}
  │   ├── intervals {List[Dict]}
  │   ├── track_status {List[Dict]}
  │   ├── race_control {List[Dict]}
  │   ├── weather {List[Dict]}
  │   └── fastest_laps {List[Dict]}
  │
  └── RaceWeekendData (immutable, cached)
      ├── year {int}
      ├── round_number {int}
      ├── event_name {str}
      ├── location {str}
      ├── country {str}
      ├── circuit_name {str}
      ├── timezone {str}
      ├── event_date {str}
      ├── session_schedule {Dict}
      └── available_sessions {List}

DataLoader
  ↓
RaceDataLoader
  ├── F1Catalog (all seasons)
  │   └── SeasonInfo (per year)
  │       └── RaceInfo[] (all races)
  │
  ├── RaceWeekendData (per round)
  └── SessionDataset (per session)
```

---

## Data Loading Flow

```
1. RaceManager / DataLoader
   ↓
2. RaceDataLoader.load_session(year, round, session_type)
   ↓
3. Fetch from FastF1 → Process → Create SessionDataset
   ├── Extract telemetry: pd.DataFrame → pl.DataFrame
   ├── Extract track geometry: numpy arrays
   ├── Extract pit lane geometry: numpy arrays
   ├── Extract metadata: event info, driver colors
   └── TODO: Extract events (track_status, race_control, weather, etc.)
   ↓
4. Cache SessionDataset to disk (pickle)
   ↓
5. Create Race wrapper for frontend access
   ↓
6. Flask routes access via race.property_name
```

---

## TODO: Missing Data Extractions

The following data fields are stubbed (empty lists) and need extraction from FastF1:

- `SessionDataset.track_status` - Extract from `f1_session.track_status`
- `SessionDataset.race_control` - Extract from `f1_session.messages` (race control messages)
- `SessionDataset.weather` - Extract from `f1_session.weather_data`
- `SessionDataset.fastest_laps` - Track fastest lap progression through session
- `SessionDataset.intervals` - Calculate from lap times
- `SessionDataset.position_history` - Build from telemetry snapshots

These need to be populated in `RaceDataLoader._fetch_and_process_session()`.

---

## Data Types & Formats

| Type | Source | Usage |
|---|---|---|
| **Polars DataFrame** | Telemetry (converted from Pandas) | Time-series data, 200Hz sampling |
| **NumPy Arrays** | Track geometry | Rendering (efficient, compact) |
| **Python Dicts** | Metadata, events | JSON serialization, easy iteration |
| **Immutable (frozen dataclass)** | SessionDataset, RaceWeekendData | Thread-safe caching |
| **Pickle** | Cache file format | Fast disk I/O, preserves types |

