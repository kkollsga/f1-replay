# F1_Replay - Formula 1 Race Replay Library

A Python library for accessing, processing, and analyzing Formula 1 race data with hierarchical 3-tier caching for optimal performance.

## Features

✅ **3-Tier Hierarchical Data Loading**
- TIER 1: F1Seasons - Season catalog (~50 KB)
- TIER 2: F1Weekend - Circuit data + metadata (~500 KB)
- TIER 3: SessionData - Telemetry, events, results (~12 MB)

✅ **Efficient Data Processing**
- Polars DataFrames for telemetry (2-5x faster than Pandas)
- NumPy arrays for track geometry (compact storage)
- Immutable frozen dataclasses (thread-safe)

✅ **Smart Caching**
- Disk cache: `race_data/year/round_location/session.pkl`
- Automatic cache management
- Force reprocess option for updates

✅ **Track Extraction**
- Track geometry from fastest lap
- Pit lane detection from in/out laps
- Automatic segmentation (marshal sectors)

## Installation

```bash
pip install -e .
```

Or with development dependencies:

```bash
pip install -e ".[dev]"
```

## Quick Start

```python
from f1_replay.data_loader import DataLoader

# Initialize loader
loader = DataLoader(cache_dir="race_data")

# TIER 1: Load season catalog
seasons = loader.load_seasons([2023, 2024])
print(f"Available years: {list(seasons.years.keys())}")

# TIER 2: Load race weekend (2024 Monaco - Round 8)
weekend = loader.load_weekend(2024, 8)
print(f"Event: {weekend.metadata.event_name}")
print(f"Track length: {weekend.circuit.circuit_length:.0f}m")

# Access track and pit lane
track = weekend.circuit.track
pit_lane = weekend.circuit.pit_lane
segments = weekend.circuit.track_segments

# TIER 3: Load race session
race = loader.load_session(2024, 8, "Race")
print(f"Drivers: {race.metadata.drivers}")

# Access telemetry
ver_telemetry = race.telemetry["VER"]
print(f"VER telemetry points: {len(ver_telemetry)}")

# Switch to another session (TIER 2 stays in memory)
qualifying = loader.load_session(2024, 8, "Qualifying")
```

## Directory Structure

```
f1_replay/
├── data_loader/
│   ├── __init__.py
│   ├── data_models.py          # Dataclasses for all tiers
│   ├── dataloader.py           # Main orchestrator
│   ├── fastf1_client.py        # FastF1 API communication
│   ├── seasons_processor.py    # TIER 1 processing
│   ├── weekend_processor.py    # TIER 2 processing
│   ├── session_processor.py    # TIER 3 processing
│   └── track_extractor.py      # Track geometry extraction
├── manager/
│   ├── __init__.py
│   └── race_manager.py         # Placeholder
├── race/
│   ├── __init__.py
│   ├── race_weekend.py         # Placeholder
│   └── race.py                 # Placeholder
└── __init__.py

race_data/                       # Cache directory (auto-created)
├── seasons.pkl
├── 2024/
│   ├── 01_Bahrain/
│   │   ├── Weekend.pkl
│   │   ├── FP1.pkl
│   │   ├── FP2.pkl
│   │   ├── FP3.pkl
│   │   ├── Q.pkl
│   │   └── R.pkl
│   ├── 08_Monaco/
│   │   └── ...
│   └── ...
└── 2023/
    └── ...
```

## Cache Structure

Files are stored efficiently with this structure:

```
race_data/
{year}/{round:02d}_{location}/
├── Weekend.pkl (TIER 2) - Circuit data + metadata
├── FP1.pkl (TIER 3)     - Session data
├── FP2.pkl (TIER 3)
├── FP3.pkl (TIER 3)
├── Q.pkl (TIER 3)       - Qualifying
├── S.pkl (TIER 3)       - Sprint (if applicable)
└── R.pkl (TIER 3)       - Race

Example: race_data/2024/08_Monaco/Race.pkl
```

## Data Models

### TIER 1: F1Seasons
- `years`: Dict of F1Year objects
- Access: `seasons.years[2024].rounds[0].event_name`

### TIER 2: F1Weekend
- `metadata`: WeekendMetadata (event info, timezone, schedule)
- `circuit`: CircuitData (track geometry, pit lane, segments)
- Access: `weekend.circuit.track.x`, `weekend.circuit.pit_lane`

### TIER 3: SessionData
- `metadata`: SessionMetadata (drivers, colors, session info)
- `telemetry`: Dict[driver_code] -> Polars DataFrame (200Hz telemetry)
- `events`: EventsData (track status, weather, messages)
- `results`: ResultsData (fastest laps, position history)
- Access: `session.telemetry["VER"]`, `session.events.weather`

## Features Overview

### Data Consolidation & Analysis
✅ **Telemetry Consolidation** - Combine all driver telemetries by distance along track
✅ **Pit Lane Detection** - Automatic identification of pit vs on-track driving
✅ **Driver Comparison** - Compare drivers at specific track locations
✅ **Pit Stop Analysis** - Identify pit entry/exit and duration

### Event & Results Extraction
✅ **Track Status Events** - Yellow flags, safety cars, virtual safety cars
✅ **Race Control Messages** - Official communications
✅ **Weather Data** - Temperature, humidity, wind throughout session
✅ **Fastest Laps** - Fastest lap per driver
✅ **Position History** - Final standings and driver positions

## TODO

- [x] Extract events (track_status, race_control, weather) ✓
- [x] Extract results (fastest_laps, position_history) ✓
- [x] Telemetry consolidation & analysis ✓
- [ ] RaceManager implementation
- [ ] RaceWeekend wrapper
- [ ] Race wrapper with Flask app integration
- [ ] Calculate DRS zones from circuit data
- [ ] Add comprehensive tests
- [ ] Add documentation

## License

MIT

## Development

### Running Tests

```bash
pytest tests/
```

### Code Formatting

```bash
black f1_replay/
isort f1_replay/
```

## Contributing

Contributions welcome! Please follow the code style guidelines.
