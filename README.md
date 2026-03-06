# f1-replay

[![PyPI version](https://badge.fury.io/py/f1-replay.svg)](https://badge.fury.io/py/f1-replay)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

A Python toolkit for Formula 1 data analysis and visualization. Built on [FastF1](https://github.com/theOehrly/Fast-F1) with intelligent caching, schedule tools, circuit plotting, and interactive race replay.

## Installation

```bash
pip install f1-replay
```

## Quick Start

```python
from f1_replay import Manager

mgr = Manager()

# Launch interactive race replay
mgr.race(2024, "monaco")

# Browse season schedule
mgr.season_schedule(2024)

# Load and explore data
weekend = mgr.load_weekend(2024, "monaco")
session = mgr.load_race(2024, "monaco")

# Access telemetry
session.telemetry["VER"]       # Polars DataFrame
session.drivers                # ["VER", "NOR", "LEC", ...]

# Generate circuit poster
weekend.plot(color_mode="speed")
```

## Features

- **3-Tier Data Management** -- Hierarchical caching for seasons, weekends, and sessions with automatic pickle storage
- **Schedule Tools** -- Query race calendars, browse events, resolve races by name or round number
- **Circuit Plotting** -- Poster-style track maps with speed, throttle, brake, height, and sector coloring
- **Race Replay** -- Interactive 2D viewer with animated car positions, live standings, strategy panel, track status overlays, rain effects, and race control messages

## CLI

```bash
f1-replay race 2024 monaco              # Launch race replay
f1-replay race 2024 8 --port 8080       # By round number
f1-replay seasons 2024                  # List races
f1-replay server                        # API server only
f1-replay config --set-cache-dir /data  # Set cache location
```

## Documentation

Full documentation at **[f1-replay.readthedocs.io](https://f1-replay.readthedocs.io/en/latest/)**

- [Usage Guide](https://f1-replay.readthedocs.io/en/latest/API.html) -- Loading data, circuit plots, race viewer, CLI reference, REST API
- [Python API Reference](https://f1-replay.readthedocs.io/en/latest/python-api.html) -- Auto-generated method documentation
- [Architecture](https://f1-replay.readthedocs.io/en/latest/ARCHITECTURE.html) -- Data pipeline, caching strategy, frontend design
- [Telemetry Reference](https://f1-replay.readthedocs.io/en/latest/TELEMETRY.html) -- Column definitions, units, processing pipeline

## Development

```bash
git clone https://github.com/kkollsga/f1-replay.git && cd f1-replay
make install   # pip install -e ".[dev,all]"
make check     # lint + tests (196 tests)
make docs      # build Sphinx documentation
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for the full development guide.

## Requirements

- Python 3.9+
- FastF1, Flask, Polars, NumPy, SciPy, Pandas
- Optional: matplotlib (circuit plots), orjson (faster JSON), flask-cors

## License

MIT
