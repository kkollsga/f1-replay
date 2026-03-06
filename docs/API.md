# Usage Guide

## Getting Started

```python
from f1_replay import Manager

mgr = Manager()
```

The Manager is the main entry point. It handles data loading, caching, and launching the viewer.

**Options:**

```python
mgr = Manager(
    cache_dir="/path/to/data",   # Override cache directory
    timezone="Europe/Oslo",       # Display times in local timezone
)
```

---

## Seasons & Schedules

### Browsing Seasons

```python
mgr.list_years()              # Available seasons: [2018, 2019, ..., 2025]
mgr.get_season(2024)          # All events for a year
mgr.seasons                   # Full catalog: {year: [EventInfo, ...]}
```

### Schedule Queries

Print formatted schedule tables filtered by session type:

```python
mgr.season_schedule(2024)          # Full season overview
mgr.race_schedule(2024)            # Race sessions only
mgr.sprint_schedule(2024)          # Sprint weekends
mgr.qualification_schedule(2024)   # Qualifying sessions
mgr.practice_schedule(2024)        # Practice sessions
```

### Flexible Event Lookup

Events can be found by round number or name (case-insensitive, partial match):

```python
mgr.load_weekend(2024, 8)              # By round number
mgr.load_weekend(2024, "monaco")       # By name
mgr.load_weekend(2024, "abu dhabi")    # Partial match
```

---

## Loading Data

f1-replay uses a 3-tier caching system. Each tier builds on the previous one.

### Tier 1: Season Catalog

Loaded automatically when needed. Contains event metadata for all races in a year.

### Tier 2: Weekend Data

Load circuit geometry and weekend metadata:

```python
weekend = mgr.load_weekend(2024, "monaco")

weekend.circuit.track          # Track geometry (x, y, z coordinates)
weekend.circuit.pit_lane       # Pit lane coordinates
weekend.circuit.corners        # Corner positions and numbers
weekend.circuit.circuit_length # Total lap distance in meters
```

### Tier 3: Session Telemetry

Load full telemetry, events, and results for a specific session:

```python
session = mgr.load_session(2024, "monaco", "Race")
# Or shorthand:
session = mgr.load_race(2024, "monaco")

session.drivers                # ["VER", "NOR", "LEC", ...]
session.driver_colors          # {"VER": "#3671C6", ...}
session.driver_names           # {"VER": "Max Verstappen", ...}
session.driver_teams           # {"VER": "Red Bull Racing", ...}
session.telemetry              # Dict[str, pl.DataFrame]
session.track_status           # Yellow flags, safety cars, etc.
session.race_control           # Race control messages
session.fastest_laps           # Fastest lap events
```

**Telemetry columns:** `session_time`, `x`, `y`, `z`, `speed`, `throttle`, `brake`, `rpm`, `gear`, `drs`, `lap_number`, `compound`, `tyre_life`, `track_distance`, `race_distance`, `position`, `interval`, `status`, `vx`, `vy`

See [Telemetry Reference](TELEMETRY.md) for full column documentation.

### Advanced: DataLoader

For lower-level control over data loading and caching:

```python
from f1_replay import DataLoader

loader = DataLoader()  # uses ~/Documents/f1-replay by default

seasons = loader.load_seasons()
weekend = loader.load_weekend(year, round_num, event)
result = loader.load_session(year, round_num, "Race",
                              event=event,
                              circuit_length=weekend.circuit.circuit_length)
# result.data = SessionData, result.raw_session = FastF1 session (optional)
```

---

## Working with Telemetry

### Per-Driver DataFrames

Each driver's telemetry is a [Polars](https://pola.rs/) DataFrame:

```python
ver = session.telemetry["VER"]
print(ver.columns)   # ['session_time', 'x', 'y', 'speed', 'lap_number', ...]
print(ver.shape)     # (rows, columns)
```

### Sampling Helpers

Get one telemetry point per lap:

```python
# First point of each lap
lap_data = session.get_telemetry_every_lap("VER")

# Last point of each lap
lap_data = session.get_telemetry_every_lap("VER", offset=-1)
```

Get telemetry at regular time intervals:

```python
# Every minute
minute_data = session.get_telemetry_every_minute("VER")

# Every 30 seconds
half_min = session.get_telemetry_every_minute("VER", interval=0.5)
```

### Race Order Queries

```python
# Who was in what position at session time 3600s?
order = session.get_order_at_time(3600.0)
# Returns: [(1, "VER", 45230.5), (2, "NOR", 45180.2), ...]

# Standings after lap 30
order = session.get_order_at_lap(30)

# Race leader at a specific time
leader = session.get_leader_at_time(3600.0)  # "VER"
```

For the full method reference, see the [Python API Reference](python-api.rst).

---

## Circuit Plotting

Generate poster-style circuit maps with customizable visualization:

```python
weekend = mgr.load_weekend(2024, "monaco")

# Clean white track
weekend.plot()

# Colored by marshal sectors
weekend.plot(color_mode="sectors")

# Telemetry overlays (requires session data loaded first)
weekend.plot(color_mode="speed")
weekend.plot(color_mode="throttle")
weekend.plot(color_mode="brake")
weekend.plot(color_mode="height")
```

**Saving to file:**

```python
weekend.plot(save_path="monaco_2024.png", dpi=300)
```

**Customizing:**

```python
weekend.plot(
    figsize=(16, 12),     # Figure size (width, height)
    color_mode="speed",   # Track coloring
    track_width=6,        # Line width
    dpi=150,              # Resolution for saved file
)
```

You can also use the lower-level function directly:

```python
from f1_replay.tools import plot_weekend

fig = plot_weekend(weekend.circuit, weekend.event, color_mode="sectors")
```

---

## Race Replay Viewer

### Launching from Python

```python
mgr.race(2024, "monaco")

# With options
mgr.race(2024, 8, port=8080, force_update=True, sessions=["R", "Q"])
```

### Launching from CLI

```bash
f1-replay race 2024 monaco
f1-replay race 2024 8 --port 8080
f1-replay race 2024 "abu dhabi" --force-update
```

### Viewer Features

- 2D track map with animated car positions and driver colors
- Live standings with position tracking, gap times, and tyre compounds
- Strategy panel with tyre stint bars and pit stop markers
- Lap time chart overlay (top 5 + chased driver)
- Starting lights animation and formation lap
- Track status overlays (safety car, VSC, red flag, sector yellows)
- Rain overlay with particle animation
- Race control message feed
- Chase mode (follow individual driver with auto-zoom)
- Pan/zoom with mouse, session tabs (switch R/Q/FP)
- Qualifying results view with delta to pole
- Data export (CSV/JSON)

### Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `Space` | Play / Pause |
| `Left` / `Right` | Seek 10 seconds |
| `Shift+Left` / `Shift+Right` | Seek 60 seconds |
| `+` / `-` | Increase / Decrease playback speed |
| `C` or `Escape` | Exit chase mode |
| `L` | Toggle lap time chart |
| `S` | Toggle strategy panel |

---

## Configuration

### Cache Directory

```python
from f1_replay import set_cache_dir, get_cache_dir

set_cache_dir("/path/to/data")    # Persists to ~/.f1replay/config.json
get_cache_dir()                   # Current cache directory
```

```bash
# Environment variable (highest priority)
export F1_REPLAY_CACHE_DIR=/path/to/data
```

**Priority order:** Environment variable > Config file (`~/.f1replay/config.json`) > Default (`~/Documents/f1-replay`)

### Cache Structure

```text
~/Documents/f1-replay/
├── seasons.pkl
└── 2024/
    └── 08_Monaco/
        ├── Weekend.pkl     # Circuit geometry + metadata
        ├── Race.pkl        # Race telemetry
        ├── Qualifying.pkl  # Qualifying telemetry
        └── ...
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

---

## REST API

All endpoints return JSON. The API is served by Flask at `http://localhost:5000` by default.

### GET /api/seasons

Returns the complete seasons catalog.

**Response:**

```javascript
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

### GET /api/weekend/\<year\>/\<round\>

Returns weekend metadata and circuit geometry.

**Parameters:**

| Parameter | Type | Example |
|-----------|------|---------|
| `year` | int | `2024` |
| `round` | int | `8` |

**Response:**

```javascript
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

```javascript
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

```javascript
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
