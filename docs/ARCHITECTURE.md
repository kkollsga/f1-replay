# Architecture

## Overview

f1-replay is built around a **3-tier hierarchical data system** on top of [FastF1](https://docs.fastf1.dev/):

1. **Seasons** -- Event metadata for all races in a year
2. **Weekend** -- Circuit geometry (track, pit lane, corners, sectors)
3. **Session** -- Full telemetry, events, and results for a single session

All data is stored as **frozen dataclasses** (immutable), cached as **pickle files**, and served via a **Flask API** to a **canvas-based JavaScript viewer**.

## Data Pipeline

```{mermaid}
flowchart TD
    F1[FastF1 API] --> Client[FastF1Client]

    Client --> SP[SeasonsProcessor]
    Client --> WP[WeekendProcessor]
    Client --> SessP[SessionProcessor]

    SP --> S_PKL[(seasons.pkl)]
    WP --> W_PKL[(Weekend.pkl)]

    SessP --> TB[TelemetryBuilder]
    SessP --> OB[OrderBuilder]
    SessP --> EB[EventsBuilder]
    SessP --> WE[WeatherExtractor]
    SessP --> RB[ResultsBuilder]
    TB & OB & EB & WE & RB --> SESS_PKL[(Session.pkl)]

    S_PKL & W_PKL & SESS_PKL --> DL[DataLoader]
    DL --> MGR[Manager]
    MGR --> FLASK[Flask API]
    FLASK --> VIEWER[Web Viewer]
```

## Layer Descriptions

### models/ -- Pure Data

Frozen dataclasses with no business logic. These define the shape of all data flowing through the system.

| Type | File | Purpose |
|------|------|---------|
| `EventInfo` | `event.py` | Race weekend metadata (name, dates, location, sessions) |
| `SessionInfo` | `event.py` | Individual session info (name, datetime) |
| `F1Weekend` | `weekend.py` | EventInfo + CircuitData |
| `CircuitData` | `weekend.py` | Track geometry, pit lane, corners, rotation, metadata |
| `TrackGeometry` | `weekend.py` | X/Y/Z coordinates, distance array, marshal sectors |
| `PitLane` | `weekend.py` | Pit lane coordinates and entry/exit distances |
| `Corner` | `weekend.py` | Corner number, track distance, angle |
| `MarshalSector` | `weekend.py` | Sector number, start/end distances |
| `DirectionArrow` | `weekend.py` | Start/finish direction indicator |
| `SessionData` | `session.py` | Complete session: metadata + telemetry + events + results |
| `SessionMetadata` | `session.py` | Drivers, teams, colors, track length, total laps, T0Info |
| `T0Info` | `session.py` | Timing zero reference, lights out offset, session duration |
| `EventsData` | `session.py` | Track status intervals, race control messages |
| `ResultsData` | `session.py` | Grid, final results, fastest laps, position history |
| `RaceResults` | `results.py` | Race winner, grid order, finishing order |
| `LoadResult` | `results.py` | Wrapper for loaded data + optional raw FastF1 session |

### loaders/ -- FastF1 Interface

Reads from FastF1 and transforms raw data into model objects. Each tier has a dedicated processor.

| File | Purpose |
|------|---------|
| `core/client.py` | `FastF1Client` -- wraps FastF1 library calls |
| `core/mapping.py` | Session type mapping (R/Q/FP1 ↔ Race/Qualifying/Practice1) |
| `seasons/processor.py` | `SeasonsProcessor` -- builds Tier 1 catalog from FastF1 |
| `weekend/processor.py` | `WeekendProcessor` -- builds Tier 2 with circuit geometry |
| `weekend/light_telemetry.py` | Lightweight telemetry for track extraction (Tier 2 only) |
| `session/processor.py` | `SessionProcessor` -- orchestrates Tier 3 building |
| `session/telemetry.py` | `TelemetryBuilder` -- position/car data → Polars DataFrames |
| `session/order.py` | `OrderBuilder` -- position and gap tracking |
| `session/events.py` | Track status consolidation, race control messages |
| `session/results.py` | Fastest laps, race results, position history |
| `session/track_extract.py` | Track geometry extraction from driver telemetry |
| `session/weather.py` | `WeatherExtractor` -- rain detection from weather data |

### wrappers/ -- Convenience API

Wraps frozen dataclasses with computed properties and methods for the public Python API.

- **`session.py`** -- `Session` base class with subclasses: `RaceSession`, `SprintSession`, `QualiSession`, `PracticeSession`. Provides properties like `.drivers`, `.telemetry`, `.track_status`.
- **`race_weekend.py`** -- `RaceWeekend` wraps `F1Weekend` with session loading callbacks and circuit properties.

### managers/ -- Orchestration

| File | Purpose |
|------|---------|
| `dataloader.py` | `DataLoader` -- 3-tier pickle caching, load/save, force update |
| `race_manager.py` | `Manager` -- top-level API: `race()`, `load_weekend()`, `load_session()`, schedule queries, Flask launcher |
| `schedule.py` | Schedule query helpers for filtering events by session type |

### api/ -- Flask Web Application

| File | Purpose |
|------|---------|
| `app.py` | Flask app factory with orjson support, CORS, blueprint registration |
| `routes/api_routes.py` | REST API: `/api/seasons`, `/api/weekend/<y>/<r>`, `/api/session/<y>/<r>/<t>` |
| `routes/ui_routes.py` | Serves `index.html` with Jinja-templated year/round |
| `serializers.py` | Polars→JSON conversion, telemetry field filtering, float rounding |
| `cli.py` | CLI entry point: `race`, `config`, `server`, `seasons`, `migrate-cache` |

### services/ -- Utilities

- **`track_finder.py`** -- `TrackFinder` resolves circuit names across years (handles renames, aliases) to find historical track data for future races.
- **`track_transformer.py`** -- `TrackTransformer` applies rotation and normalization transforms to track coordinates for visualization.

### tools/

- **`weekend_plot.py`** -- `plot_weekend()` generates poster-style circuit maps with color modes (speed, throttle, brake, height, sectors).
- **`migrate_cache.py`** -- Migrates legacy Weekend.pkl files with placeholder tracks to the current format.

## File Layout

```
f1_replay/                          11,574 lines total
├── __init__.py                     Public API exports
├── config.py                       Cache dir config (env > file > default)
├── log.py                          Logger setup (F1_REPLAY_LOG_LEVEL)
├── models/
│   ├── __init__.py                 Re-exports all model types
│   ├── base.py                     F1DataMixin (dict-like access)
│   ├── event.py                    EventInfo, SessionInfo, get_location_dir
│   ├── weekend.py            520   CircuitData, TrackGeometry, PitLane, Corner, etc.
│   ├── session.py            248   SessionData, SessionMetadata, T0Info, EventsData
│   └── results.py                  RaceResults, LoadResult
├── loaders/
│   ├── __init__.py                 Re-exports processors and builders
│   ├── core/
│   │   ├── client.py         252   FastF1Client wrapper
│   │   └── mapping.py              Session type name mapping
│   ├── seasons/
│   │   └── processor.py      162   SeasonsProcessor
│   ├── weekend/
│   │   ├── processor.py      585   WeekendProcessor + manual rotations
│   │   └── light_telemetry.py 516  Lightweight track extraction
│   └── session/
│       ├── processor.py      710   SessionProcessor orchestrator
│       ├── telemetry.py      913   TelemetryBuilder (largest file)
│       ├── order.py          472   OrderBuilder (positions, intervals)
│       ├── events.py         812   Track status, race control, synthetic events
│       ├── results.py        521   Fastest laps, race results
│       ├── track_extract.py  548   Track geometry from telemetry
│       └── weather.py        151   Rain detection
├── wrappers/
│   ├── session.py            474   Session class hierarchy
│   └── race_weekend.py       468   RaceWeekend wrapper
├── managers/
│   ├── dataloader.py         393   DataLoader (3-tier caching)
│   ├── race_manager.py       818   Manager (top-level API)
│   └── schedule.py           153   Schedule query helpers
├── services/
│   ├── track_finder.py       165   Historical circuit resolution
│   └── track_transformer.py  273   Coordinate transforms
├── tools/
│   ├── weekend_plot.py       783   Circuit poster plotting
│   └── migrate_cache.py            Legacy cache migration
└── api/
    ├── app.py                      Flask factory
    ├── cli.py                190   CLI entry point
    ├── serializers.py        285   JSON serialization
    ├── routes/
    │   ├── api_routes.py     230   REST API endpoints
    │   └── ui_routes.py            Viewer page route
    ├── static/
    │   ├── css/main.css     1344   All CSS styles
    │   └── js/
    │       ├── constants.js   39   UI settings, colors, light config
    │       ├── status-managers.js 267  TrackStatus, RaceControl, StartingLightsManager
    │       └── viewer.js    3311   F1RaceViewer (main viewer class)
    └── templates/
        └── index.html        185   HTML shell with Jinja + script tags
```

## Telemetry Processing Pipeline

When a session is loaded, raw FastF1 data goes through 8 processing steps to produce frontend-ready telemetry:

1. **Position Compaction** -- FastF1 provides position data at ~4.5Hz. Consecutive samples where the car hasn't moved (<1 decimeter) are removed to reduce data size without losing information.

2. **Car Data Sampling** -- ECU telemetry (speed, throttle, brake, rpm, gear, DRS) arrives at different timestamps than position data. Nearest-neighbor matching aligns car data to position timestamps.

3. **Lap Info Assignment** -- Lap numbers are determined from finish-line crossing times in FastF1's laps DataFrame. Tyre compound and tyre life are extracted from lap metadata. Pit in/out windows are identified.

4. **Velocity Vector Computation** -- `vx` and `vy` are computed via central finite differences on (x, y, session_time), then smoothed with bidirectional exponential moving average (sigma=2 samples). Values are clamped to +/-1000 dm/s and zeroed across large time gaps (pit stops).

5. **Track Distance Projection** -- Each car position (x, y) is projected perpendicular onto the weekend's TrackGeometry to get `track_distance` in meters. Uses KD-tree spatial indexing when the dataset exceeds 1000 points.

6. **Race Distance** -- `race_distance = track_distance + (lap_number - 1) * lap_distance`. This monotonically increasing value measures total distance covered and is the basis for position ranking.

7. **Status Assignment** -- Each sample is assigned a status (`PreSession`, `WarmUp`, `Racing`, `Pit`, `Finished`, `DNF`) based on event timing, pit windows, and result data. Race distance is frozen when a driver finishes or retires.

8. **Position & Interval** -- `OrderBuilder` ranks drivers by race_distance at each timestamp. The leader gets interval=0, others get the time gap to the leader computed by interpolating when the leader was at the same race_distance.

See [TELEMETRY.md](TELEMETRY.md) for the full column reference.

## Unit Conventions

| Quantity | Unit | Notes |
|----------|------|-------|
| Position (x, y) | decimeters | FastF1 native format, used throughout |
| Elevation (z) | decimeters | |
| Track distance | meters | Converted from decimeters in `WeekendProcessor` |
| Lap distance | meters | Total circuit length |
| Race distance | meters | Cumulative distance covered |
| Speed | km/h | From FastF1 car data |
| Velocity (vx, vy) | dm/s | Used for Hermite interpolation on frontend |
| Time | seconds | All times relative to session t0 |
| Throttle | % (0-100) | |
| Brake | 0-100 | |

FastF1 provides all coordinates in **decimeters**. Track/race distances are converted to **meters** when building `TrackGeometry` in `WeekendProcessor`. The frontend receives coordinates in decimeters and distances in meters.

## Caching Strategy

### Pickle File Hierarchy

```
{cache_dir}/
├── seasons.pkl                         Dict[int, List[EventInfo]]
├── .fastf1_cache/                      FastF1's internal HTTP cache
└── {year}/
    └── {round:02d}_{location_name}/
        ├── Weekend.pkl                 F1Weekend (circuit geometry)
        ├── Race.pkl                    SessionData
        ├── Qualifying.pkl              SessionData
        ├── Sprint.pkl                  SessionData
        └── Practice{1,2,3}.pkl         SessionData
```

### Cache Directory Resolution

Priority (highest wins):

1. `F1_REPLAY_CACHE_DIR` environment variable
2. `~/.f1replay/config.json` `cache_dir` key
3. Default: `~/Documents/f1-replay` (macOS/Windows) or `~/.local/share/f1-replay` (Linux)

### Cache Behavior

- **Memory caching**: `DataLoader` caches seasons in memory. Flask app caches weekends and sessions per request cycle.
- **Force update**: `--force-update` CLI flag (or `force_update=True` in Python) bypasses cache and re-fetches from FastF1.
- **Legacy migration**: Old cache files with placeholder track data can be migrated via `f1-replay migrate-cache`.

## Frontend Architecture

The viewer is a **vanilla JavaScript** application with no framework or build system.

### File Structure

| File | Lines | Purpose |
|------|-------|---------|
| `constants.js` | 39 | `STANDINGS_SETTINGS`, `SECTOR_STATUS_COLORS`, `STARTING_LIGHTS_SETTINGS` |
| `status-managers.js` | 267 | `TrackStatus` (flag state), `RaceControl` (messages), `StartingLightsManager` |
| `viewer.js` | 3311 | `F1RaceViewer` -- the entire viewer application |

### Load Order

```html
<script src="constants.js"></script>
<script src="status-managers.js"></script>
<script>/* Jinja-templated YEAR, ROUND, SESSION_TYPE */</script>
<script src="viewer.js"></script>
<script>new F1RaceViewer();</script>
```

### Rendering Pipeline (per frame)

1. Clear canvas
2. Draw track (Catmull-Rom spline smoothing on track coordinates)
3. Draw pit lane, corners, marshal sectors
4. Draw track status overlays (yellow sectors, safety car zone)
5. Draw rain animation (particle system on overlay canvas)
6. Interpolate car positions (cubic Hermite using vx/vy velocity vectors)
7. Draw cars as colored circles with driver identification
8. Update standings list (position, name, gap, tyre compound)
9. Update strategy markers and lap chart (if visible)
10. Process and display race control messages

### Data Loading

The viewer fetches data via two AJAX calls on initialization:

```
GET /api/weekend/{year}/{round}    → circuit geometry
GET /api/session/{year}/{round}/R  → telemetry, events, results
```

Session switching (e.g., Race → Qualifying) triggers a new `/api/session/` call without reloading the page.
