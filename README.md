# F1-Replay — Interactive Formula 1 Race Replay & Circuit Visualization

[![PyPI version](https://badge.fury.io/py/f1-replay.svg)](https://badge.fury.io/py/f1-replay)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Documentation](https://readthedocs.org/projects/f1-replay/badge/?version=latest)](https://f1-replay.readthedocs.io/en/latest/)

Replay any historic Formula 1 race as an animated 2D map with real telemetry data, live timing, strategy overlays, and circuit visualizations. Built on [FastF1](https://github.com/theOehrly/Fast-F1) with intelligent caching and a Flask-based viewer.

## Why F1-Replay?

- **Watch any race** — Animated car positions on a real circuit map with sub-second telemetry
- **Live timing overlay** — Gap times, position changes, pit stops, and tyre strategy in real time
- **Track status** — Safety car, VSC, red flag overlays and rain effects rendered on canvas
- **Circuit posters** — Generate publication-quality circuit maps colored by speed, sectors, throttle, brake, or elevation
- **One command** — `f1-replay 2024 monaco` and you're watching the race in your browser
- **Python API** — Full programmatic access to seasons, weekends, sessions, and telemetry DataFrames (Polars)

## Quick Start

```bash
pip install f1-replay
```

### Race Replay

```python
from f1_replay import Manager

mgr = Manager()
mgr.race(2024, "monaco")
```

Or from the command line:

```bash
f1-replay 2024 monaco
```

Opens an interactive viewer at `http://localhost:8080` with animated car positions, live standings, strategy panel, race control messages, and more.

### Circuit Plotting

```python
mgr = Manager()
weekend = mgr.load_weekend(2024, "monaco")

weekend.plot()                        # Clean white track
weekend.plot(color_mode="speed")      # Colored by speed
weekend.plot(color_mode="sectors")    # Marshal sectors
weekend.plot(save_path="monaco.png")  # Save to file
```

Color modes: `white`, `sectors`, `speed`, `throttle`, `brake`, `height`

## CLI

```bash
f1-replay 2024 monaco                  # Race replay (shorthand)
f1-replay 2024 8                       # By round number
f1-replay race 2024 monaco -p 9000     # Custom port
f1-replay seasons 2024                 # List races
f1-replay config --set-cache-dir /data # Set cache location
```

## Documentation

Full documentation at **[f1-replay.readthedocs.io](https://f1-replay.readthedocs.io/en/latest/)**

- [Usage Guide](https://f1-replay.readthedocs.io/en/latest/API.html) — Data loading, circuit plots, race viewer, telemetry, CLI, REST API
- [Python API Reference](https://f1-replay.readthedocs.io/en/latest/python-api.html) — Auto-generated from docstrings
- [Architecture](https://f1-replay.readthedocs.io/en/latest/ARCHITECTURE.html) — Data pipeline, caching, frontend design
- [Telemetry Reference](https://f1-replay.readthedocs.io/en/latest/TELEMETRY.html) — Column definitions, units, processing

## Development

```bash
git clone https://github.com/kkollsga/f1-replay.git && cd f1-replay
make install   # pip install -e ".[dev,all]"
make check     # lint + tests (196 tests)
make docs      # build Sphinx documentation
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for the full development guide.

## License

MIT
