# f1-replay

A Python wrapper around the [FastF1](https://github.com/theOehrly/Fast-F1) library for interactive Formula 1 race replays. View historic races in a 2D map visualization with real-time car positions using telemetry data.

## Installation

```bash
pip install f1-replay
```

Or from source:

```bash
pip install -e .
```

## Quick Start

```python
from f1_replay import Manager

# Initialize manager
manager = Manager()

# Launch race replay viewer
manager.race(2024, "monaco")      # By event name
manager.race(2024, 8)             # By round number
```

This opens a Flask-based web viewer showing:

- 2D track map with live car positions
- Race progression with telemetry data
- Driver information and timing

## Usage

### Browse Available Races

```python
from f1_replay import Manager

manager = Manager()

# List available seasons
print(manager.list_years())

# Get season details
season = manager.get_season(2024)
for race in season.rounds:
    print(f"{race.round_number}. {race.event_name}")
```

### Launch Race Viewer

```python
# Multiple ways to select a race
manager.race(2024, 24)              # By round number
manager.race(2024, "abu dhabi")     # By event name (case-insensitive)
manager.race(2024, "monaco")        # Partial match works too

# Custom host/port
manager.race(2024, 8, host='localhost', port=8080)

# Force refresh data from FastF1
manager.race(2024, 8, force_update=True)
```

### CLI Usage

```bash
# Launch race viewer
f1-replay race 2024 monaco
f1-replay race 2024 8 --port 8080

# List available races
f1-replay seasons
f1-replay seasons 2024

# Run standalone API server
f1-replay server --port 5000
```

## Configuration

Set a global cache directory so f1-replay remembers where your data is stored:

```bash
# Set global cache directory (persists across sessions)
f1-replay config --set-cache-dir /path/to/race_data

# View current configuration
f1-replay config
```

Or set it in Python:

```python
from f1_replay import set_cache_dir

set_cache_dir("/path/to/race_data")  # Persists globally
```

Or use an environment variable (takes priority over config file):

```bash
export F1_REPLAY_CACHE_DIR=/path/to/race_data
```

**Priority:** Environment variable > Config file > Default (`./race_data`)

Config file: `~/.f1replay/config.json`

## Features

- Interactive 2D race replay with car positions
- Telemetry-based animation using FastF1 data
- Support for all session types (Race, Qualifying, Practice, Sprint)
- Automatic data caching for fast loading
- Event name or round number lookup

## Requirements

- Python 3.9+
- FastF1
- Flask

---

## Advanced Usage

### Direct Data Access

For custom analysis or building your own visualizations:

```python
from f1_replay import Manager

manager = Manager()

# Load session data directly
session = manager.load_race(2024, "monaco")

# Access telemetry
telemetry = session.telemetry["VER"]  # Polars DataFrame
print(f"Telemetry points: {len(telemetry)}")

# Access track geometry
track = session.weekend.track
pit_lane = session.weekend.pit_lane

# Access events and results
weather = session.weather
fastest_laps = session.fastest_laps
```

### Data Loading (DataLoader)

For more control over data loading:

```python
from f1_replay.data_loader import DataLoader

loader = DataLoader(cache_dir="race_data")

# TIER 1: Season catalog
seasons = loader.load_seasons()

# TIER 2: Weekend data (circuit geometry)
weekend = loader.load_weekend(2024, 8)
print(f"Track length: {weekend.circuit.circuit_length:.0f}m")

# TIER 3: Session data (telemetry, events, results)
race = loader.load_session(2024, 8, "Race")
```

### Cache Structure

Data is cached to disk for fast subsequent loads:

```
race_data/
├── seasons.pkl
└── 2024/
    ├── 08_Monaco/
    │   ├── Weekend.pkl    # Circuit + metadata
    │   └── R.pkl          # Race telemetry
    └── ...
```

### Data Models

**TIER 1: F1Seasons** - Season catalog with race schedule

**TIER 2: F1Weekend** - Circuit geometry, pit lane, track segments

**TIER 3: SessionData** - Telemetry (Polars), events, results per driver

## License

MIT
