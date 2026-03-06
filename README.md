# f1-replay

[![PyPI version](https://badge.fury.io/py/f1-replay.svg)](https://badge.fury.io/py/f1-replay)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

A Python toolkit for Formula 1 data analysis and visualization. Built on [FastF1](https://github.com/theOehrly/Fast-F1) with intelligent caching, circuit plotting, and interactive race replay.

## Installation

```bash
pip install f1-replay
```

## Quick Start

### Race Replay

Watch any historic race with an interactive 2D viewer:

```python
from f1_replay import Manager

mgr = Manager()
mgr.race(2024, "monaco")
```

Or from the command line:

```bash
f1-replay 2024 monaco
```

The viewer includes animated car positions, live standings with gap times, strategy panel, track status overlays (safety car, VSC, red flags), rain effects, race control messages, and more.

### Circuit Plotting

Generate poster-style circuit maps:

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

- [Usage Guide](https://f1-replay.readthedocs.io/en/latest/API.html) -- Loading data, circuit plots, race viewer, telemetry, CLI, REST API
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
