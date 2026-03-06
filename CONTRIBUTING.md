# Contributing to f1-replay

Thank you for your interest in contributing! This guide will help you get set up and productive quickly.

## Prerequisites

- Python 3.9 or newer
- pip (or any Python package manager)
- Git

## Development Setup

```bash
git clone https://github.com/your-org/f1-replay.git
cd f1-replay

# Create and activate a virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install with all dependencies (dev tools + optional extras)
make install  # runs: pip install -e ".[dev,all]"

# Verify everything works
make check    # runs: lint + 196 tests
```

## Code Style

All formatting is enforced by CI and configured in `pyproject.toml` / `.flake8`:

| Tool | Config | Purpose |
|------|--------|---------|
| **black** | line-length 100, target py39-py311 | Code formatting |
| **isort** | profile "black", line-length 100 | Import sorting |
| **flake8** | max-line-length 100 | Linting |

```bash
make format   # Auto-fix formatting (black + isort)
make lint     # Check without modifying (black --check, isort --check, flake8)
```

## Project Structure

```
f1_replay/
├── models/          # Frozen dataclasses — the data layer
├── loaders/         # FastF1 interfaces and data processors
│   ├── core/        #   FastF1Client, session type mapping
│   ├── seasons/     #   Tier 1: season catalog processor
│   ├── weekend/     #   Tier 2: weekend + circuit geometry
│   └── session/     #   Tier 3: telemetry, events, results, order
├── wrappers/        # High-level Session and RaceWeekend classes
├── managers/        # DataLoader (caching) + Manager (orchestration)
├── services/        # TrackFinder (circuit lookup), TrackTransformer
├── api/             # Flask app, routes, serializers, CLI
│   ├── routes/      #   api_routes.py (REST), ui_routes.py (viewer)
│   ├── static/      #   css/main.css, js/{constants,status-managers,viewer}.js
│   └── templates/   #   index.html (HTML shell with Jinja)
├── tools/           # Circuit plotting, cache migration
├── config.py        # Cache directory configuration
└── log.py           # Logging (F1_REPLAY_LOG_LEVEL env var)
```

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for a full architectural deep-dive.

## Testing

```bash
make test       # Run all tests (pytest -v)
make test-cov   # Run with coverage report
make check      # Lint + tests (must pass before merging)
```

The test suite has 196 tests across 11 files covering models, serialization, track geometry, telemetry processing, event extraction, position tracking, weather, configuration, logging, and API endpoints.

Tests do **not** call the FastF1 API — all external data is mocked in `tests/conftest.py`.

## Pull Requests

1. Branch from `main` using a descriptive name: `feature/lap-chart`, `fix/interval-nan`, `docs/api-reference`
2. Make your changes
3. Run `make check` — both lint and tests must pass
4. Push and open a PR against `main`
5. CI automatically runs pytest across Python 3.9-3.13 plus lint checks

## Keeping Docs Updated

When you modify these areas, please update the corresponding documentation:

| Change | Update |
|--------|--------|
| API routes (`api/routes/`) | [docs/API.md](docs/API.md) |
| Telemetry columns (`loaders/session/telemetry.py`) | [docs/TELEMETRY.md](docs/TELEMETRY.md) |
| New CLI commands (`api/cli.py`) | [docs/API.md](docs/API.md) CLI section |
| Architecture changes | [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) |
