# f1-replay

[![PyPI version](https://badge.fury.io/py/f1-replay.svg)](https://badge.fury.io/py/f1-replay)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

A Python toolkit for Formula 1 data analysis and visualization. Built on [FastF1](https://github.com/theOehrly/Fast-F1) with intelligent caching, schedule tools, circuit plotting, and live race replay.

## Installation

```bash
pip install f1-replay
```

## Features

- **3-Tier Data Management** — Hierarchical caching system for seasons, weekends, and sessions
- **F1 Info Tools** — Query schedules, browse events, and resolve races by name or round
- **Circuit Plotting** — Poster-style track maps with sector coloring and telemetry overlays
- **Race Replay** — Interactive 2D visualization with real-time car positions

---

## Quick Start

```python
from f1_replay import Manager

manager = Manager()

# Launch interactive race replay
manager.race(2024, "monaco")

# Browse available races
manager.season_schedule(2024)
```

---

## Data Management

Intelligent 3-tier caching system that minimizes API calls and enables fast data access.

### Tier 1: Seasons Catalog

```python
manager.list_years()           # Available seasons
manager.get_season(2024)       # All events for a year
```

### Tier 2: Weekend Data

```python
weekend = manager.load_weekend(2024, "monaco")

weekend.circuit.track          # Track geometry (x, y, z)
weekend.circuit.pit_lane       # Pit lane coordinates
weekend.circuit.corners        # Corner positions and numbers
```

### Tier 3: Session Telemetry

```python
session = manager.load_session(2024, "monaco", "Race")

session.telemetry["VER"]       # Polars DataFrame with full telemetry
session.drivers                # ["VER", "NOR", "LEC", ...]
session.driver_colors          # {"VER": "#3671C6", ...}
session.track_status           # Yellow flags, safety cars, etc.
session.race_control           # Race control messages
```

**Telemetry columns:** `session_time`, `x`, `y`, `z`, `speed`, `throttle`, `brake`, `rpm`, `gear`, `drs`, `lap_number`, `compound`, `tyre_life`, `track_distance`

---

## F1 Info Tools

Query schedules and find events with flexible resolution.

```python
# Schedule queries
manager.season_schedule(2024)      # Full season overview
manager.race_schedule(2024)        # Race sessions only
manager.sprint_schedule(2024)      # Sprint weekends
manager.qualification_schedule(2024)
manager.practice_schedule(2024)

# Flexible event lookup
manager.load_weekend(2024, 8)           # By round number
manager.load_weekend(2024, "monaco")    # By name (case-insensitive)
manager.load_weekend(2024, "abu dhabi") # Partial match supported
```

---

## Circuit Plotting

Generate poster-style circuit maps with customizable visualization.

```python
from f1_replay.tools import plot_weekend

weekend = manager.load_weekend(2024, "monaco")

# Clean white track
plot_weekend(weekend.circuit, weekend.event)

# Colored by marshal sectors
plot_weekend(weekend.circuit, weekend.event, color_mode='sectors')

# Telemetry overlay (requires session data)
plot_weekend(weekend.circuit, weekend.event, color_mode='speed')
```

**Color modes:** `white`, `sectors`, `speed`, `throttle`, `brake`, `height`

---

## Race Replay

Launch an interactive web viewer with real-time car positions.

```python
# Python API
manager.race(2024, "monaco")
manager.race(2024, 8, port=8080)

# With force refresh from FastF1
manager.race(2024, "monaco", force_update=True)
```

```bash
# CLI
f1-replay race 2024 monaco
f1-replay race 2024 8 --port 8080
```

The viewer displays:

- 2D track map with animated car positions
- Driver colors and identification
- Race progression from telemetry data

---

## CLI Reference

```bash
# Race replay
f1-replay race <year> <round|name> [--port PORT]

# Browse seasons
f1-replay seasons [year]

# Standalone API server
f1-replay server [--port PORT]

# Configuration
f1-replay config                          # Show current config
f1-replay config --set-cache-dir /path    # Set cache directory
```

---

## Configuration

```python
from f1_replay import set_cache_dir, get_cache_dir

set_cache_dir("/path/to/data")    # Persists to ~/.f1replay/config.json
get_cache_dir()                   # Current cache directory
```

```bash
# Environment variable (highest priority)
export F1_REPLAY_CACHE_DIR=/path/to/data
```

**Priority:** Environment variable → Config file → Default (`./race_data`)

---

## Cache Structure

```
race_data/
├── seasons.pkl
└── 2024/
    └── 08_Monaco/
        ├── Weekend.pkl     # Circuit geometry + metadata
        ├── Race.pkl        # Race telemetry
        ├── Qualifying.pkl  # Qualifying telemetry
        └── ...
```

---

## Requirements

- Python 3.9+
- FastF1
- Flask
- Polars
- Matplotlib

## License

MIT
