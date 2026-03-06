# API Reference

## REST Endpoints

All endpoints return JSON. The API is served by Flask at `http://localhost:5000` by default.

### GET /api/seasons

Returns the complete seasons catalog.

**Response:**

```json
{
  "seasons": {
    "2024": {
      "total_rounds": 24,
      "rounds": [
        {
          "name": "Bahrain Grand Prix",
          "official_name": "...",
          "circuit_name": "Bahrain International Circuit",
          "country": "Bahrain",
          "year": 2024,
          "round_number": 1,
          "start_date": "2024-02-29",
          "end_date": "2024-03-02",
          "sessions": [
            {"name": "Practice 1", "date": "2024-02-29T11:30:00+03:00"},
            {"name": "Race", "date": "2024-03-02T18:00:00+03:00"}
          ],
          "timezone_offset": "+03:00",
          "format": "conventional"
        }
      ]
    }
  }
}
```

**Errors:** `500` if seasons cannot be loaded.

---

### GET /api/weekend/\<year\>/\<round\>

Returns weekend metadata and circuit geometry.

**Parameters:**

| Parameter | Type | Example |
|-----------|------|---------|
| `year` | int | `2024` |
| `round` | int | `8` |

**Response:**

```json
{
  "event": {
    "name": "Monaco Grand Prix",
    "circuit_name": "Monte Carlo",
    "year": 2024,
    "round_number": 8,
    "sessions": [...]
  },
  "circuit": {
    "track": {
      "x": [1234.5, 1235.1, ...],
      "y": [5678.3, 5679.0, ...],
      "distance": [0.0, 5.6, 11.2, ...],
      "lap_distance": 3337.0,
      "marshal_sectors": [
        {"number": 1, "start_distance": 0.0, "end_distance": 450.0}
      ],
      "speed": [120.5, 125.3, ...],
      "z": [100.2, 100.5, ...]
    },
    "pit_lane": {
      "x": [...], "y": [...],
      "length": 235.0,
      "entry_track_dist": 3100.0,
      "exit_track_dist": 200.0
    },
    "corners": [
      {"number": 1, "distance": 120.5, "angle": 90.0, "letter": ""}
    ],
    "rotation": 38.0,
    "circuit_length": 3337.0,
    "direction_arrow": {"x": 1200.0, "y": 5600.0, "dx": 0.7, "dy": 0.3}
  }
}
```

**Errors:** `404` if round not found, `500` on server error.

---

### GET /api/session/\<year\>/\<round\>/\<session_type\>

Returns complete session data: metadata, telemetry, events, and results.

**Parameters:**

| Parameter | Type | Values |
|-----------|------|--------|
| `year` | int | `2024` |
| `round` | int | `8` |
| `session_type` | string | `R`, `Q`, `S`, `SQ`, `FP1`, `FP2`, `FP3` (or long names: `Race`, `Qualifying`, `Sprint`, `SprintQualifying`, `Practice1`, `Practice2`, `Practice3`) |

**Query Parameters:**

| Param | Type | Description |
|-------|------|-------------|
| `telemetry_fields` | string | Comma-separated column names to include. If omitted, uses default set. |

**Default telemetry fields:** `session_time`, `lap_number`, `x`, `y`, `track_distance`, `race_distance`, `position`, `interval`, `status`, `compound`, `tyre_life`, `speed`, `vx`, `vy`

**Response:**

```json
{
  "metadata": {
    "session_type": "R",
    "year": 2024,
    "round_number": 8,
    "event_name": "Monaco Grand Prix",
    "drivers": ["VER", "LEC", "NOR"],
    "driver_numbers": {"VER": 1, "LEC": 16, "NOR": 4},
    "driver_names": {"VER": "Max Verstappen", "LEC": "Charles Leclerc"},
    "driver_teams": {"VER": "Red Bull Racing", "LEC": "Ferrari"},
    "driver_colors": {"VER": "#3671C6", "LEC": "#E8002D"},
    "team_colors": {"Red Bull Racing": "#3671C6", "Ferrari": "#E8002D"},
    "track_length": 3337.0,
    "total_laps": 78,
    "dnf_drivers": ["PER"]
  },
  "telemetry": {
    "VER": {
      "session_time": [0.0, 0.22, 0.44, ...],
      "x": [1234.5, 1236.1, ...],
      "y": [5678.3, 5680.0, ...],
      "lap_number": [0, 0, 1, 1, ...],
      "position": [1, 1, 1, ...],
      "compound": ["MEDIUM", "MEDIUM", ...],
      "speed": [0.0, 45.2, 120.5, ...]
    }
  },
  "events": {
    "track_status": [...],
    "race_control": [...],
    "status_messages": [...]
  },
  "results": {
    "fastest_laps": [...],
    "position_history": [...]
  }
}
```

**Scheduled sessions** (future races) return:

```json
{
  "scheduled": true,
  "name": "Monaco Grand Prix",
  "session_type": "Race",
  "scheduled_date": "2025-05-25T15:00:00+02:00",
  "scheduled_date_formatted": "Sun 25th May at 15:00",
  "message": "The Race is scheduled for Sun 25th May at 15:00"
}
```

**Errors:** `404` if session not found, `500` on server error.

---

## Python API

### Manager

The primary interface for using f1-replay programmatically.

```python
from f1_replay import Manager

mgr = Manager(cache_dir="/path/to/data", timezone="Europe/Oslo")
```

**Season Methods:**

```python
mgr.get_seasons()                  # Dict[int, List[EventInfo]]
mgr.get_season(2024)               # List[EventInfo] for one year
mgr.list_years()                   # List[int] of available years
mgr.seasons                        # Property alias for get_seasons()
```

**Schedule Methods:**

```python
mgr.season_schedule(2024)          # Print full season schedule
mgr.race_schedule(2024)            # Print race sessions only
mgr.sprint_schedule(2024)          # Print sprint weekends
mgr.qualification_schedule(2024)   # Print qualifying sessions
mgr.practice_schedule(2024)        # Print practice sessions
```

**Data Loading (chainable):**

```python
mgr.load_weekend(2024, "monaco")   # By name (case-insensitive, partial match)
mgr.load_weekend(2024, 8)          # By round number
mgr.load_session(2024, 8, "Race")  # Load session into current weekend

mgr.weekend                        # RaceWeekend (after load_weekend)
mgr.session                        # Session (after load_session)
```

**Viewer:**

```python
mgr.race(2024, "monaco")           # Load data + launch Flask viewer
mgr.race(2024, 8, port=8080, force_update=True, sessions=["R", "Q"])
```

### DataLoader

Lower-level interface for data loading and caching.

```python
from f1_replay import DataLoader

loader = DataLoader(cache_dir="race_data")

seasons = loader.load_seasons()                    # SeasonsCatalog
weekend = loader.load_weekend(year, round_num, event)  # F1Weekend
result = loader.load_session(year, round_num, "Race",
                              event=event,
                              circuit_length=weekend.circuit.circuit_length)
# result.data = SessionData, result.raw_session = FastF1 session (optional)
```

### Session

Wrapper around SessionData with convenience properties.

```python
session = mgr.session               # After load_session()

session.drivers                     # ["VER", "NOR", "LEC", ...]
session.driver_colors               # {"VER": "#3671C6", ...}
session.driver_names                # {"VER": "Max Verstappen", ...}
session.driver_teams                # {"VER": "Red Bull Racing", ...}
session.telemetry                   # Dict[str, pl.DataFrame]
session.track_status                # Track status intervals
session.race_control                # Race control messages
session.fastest_laps                # List of FastestLapEvent
session.position_history            # List of PositionSnapshot
session.session_type                # "R", "Q", etc.
session.year                        # 2024
session.round_number                # 8
session.event_name                  # "Monaco Grand Prix"
session.total_laps                  # 78
session.dnf_drivers                 # ["PER"]
```

---

## CLI Reference

Entry point: `f1-replay` (installed via pip)

### f1-replay race

Launch the interactive race viewer.

```bash
f1-replay race <year> <round|name> [options]

# Examples
f1-replay race 2024 monaco
f1-replay race 2024 8 --port 8080
f1-replay race 2024 "abu dhabi" --force-update
```

| Option | Default | Description |
|--------|---------|-------------|
| `--host` | `0.0.0.0` | Host to bind |
| `--port`, `-p` | `5000` | Port number |
| `--no-debug` | | Disable Flask debug mode |
| `--force-update`, `-f` | | Force reload from FastF1 (bypass cache) |
| `--cache-dir` | auto | Override cache directory |

### f1-replay seasons

List available seasons and races.

```bash
f1-replay seasons              # List all available years
f1-replay seasons 2024         # List races for 2024
```

### f1-replay server

Run the Flask API server without pre-loading any race.

```bash
f1-replay server --port 8080
```

| Option | Default | Description |
|--------|---------|-------------|
| `--host` | `0.0.0.0` | Host to bind |
| `--port`, `-p` | `5000` | Port number |
| `--no-debug` | | Disable Flask debug mode |
| `--cache-dir` | auto | Override cache directory |

### f1-replay config

Show or set configuration.

```bash
f1-replay config                              # Show current config
f1-replay config --set-cache-dir /path/to/data  # Set cache directory
```

### f1-replay migrate-cache

Migrate legacy cache files with placeholder track geometry.

```bash
f1-replay migrate-cache              # Migrate all legacy caches
f1-replay migrate-cache --dry-run    # Show what would be migrated
```

| Option | Description |
|--------|-------------|
| `--dry-run` | Preview without modifying files |
| `--cache-dir` | Override cache directory |
