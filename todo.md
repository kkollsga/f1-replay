# f1-replay Developer Experience Overhaul

---

## Phase 1 — Foundation

Get the basics right: fix broken things, add tests, set up dev tooling.

### 1.1 Project Hygiene

- [ ] Fix version mismatch: `pyproject.toml` says `0.1.10`, `__init__.py` says `0.1.0`
- [ ] Add `scipy` to dependencies in `pyproject.toml` (used for `cKDTree` in `models/weekend.py`)
- [ ] Add `matplotlib` to dependencies in `pyproject.toml` (used in `tools/weekend_plot.py`)
- [ ] Remove stale `setup.py` (redundant with `pyproject.toml`)
- [ ] Remove `legacy_f1_user/` reference from `CLAUDE.md` (directory doesn't exist)
- [ ] Add `[project.optional-dependencies]` `all` group with scipy, matplotlib, orjson, flask-cors
- [ ] Un-gitignore notebooks (`DataLoading.ipynb`, `Race.ipynb`) so they serve as docs for others

### 1.2 Logging

Replace all `print()` with proper `logging` so library consumers can control verbosity.

- [ ] Add `logging` module setup in `f1_replay/__init__.py` with named logger
- [ ] Replace all `print()` calls in `managers/dataloader.py` with logger
- [ ] Replace all `print()` calls in `managers/race_manager.py` with logger
- [ ] Replace all `print()` calls in `loaders/` with logger
- [ ] Replace all `print()` calls in `api/app.py` with logger
- [ ] Replace all `print()` calls in `api/cli.py` with logger (keep user-facing output as print)
- [ ] Add log level configuration via `config.py` or env var

### 1.3 Test Infrastructure

- [ ] Create `tests/` directory structure:
  ```
  tests/
  ├── conftest.py             # Shared fixtures (mock FastF1, sample data)
  ├── test_models.py          # Dataclass creation, F1DataMixin, serialization
  ├── test_mapping.py         # Session type mapping (to_fastf1_code, to_user_friendly)
  ├── test_serializers.py     # JSON serialization (NaN, numpy, polars, timedelta)
  ├── test_track_geometry.py  # Track projection, perpendicular projection, sector extraction
  ├── test_order.py           # Position and interval calculation
  ├── test_weather.py         # Rain event extraction
  ├── test_config.py          # Config priority (env > file > default)
  └── test_api.py             # Flask endpoint tests (seasons, weekend, session)
  ```
- [ ] Create `conftest.py` with mock fixtures (sample EventInfo, TrackGeometry, SessionData)
- [ ] Write `test_models.py` — frozen dataclass creation, F1DataMixin dict-like access
- [ ] Write `test_mapping.py` — bidirectional session type mapping, error cases
- [ ] Write `test_serializers.py` — NaN→None, numpy arrays, Polars DataFrames, timedelta
- [ ] Write `test_track_geometry.py` — perpendicular projection, KD-tree vs simple, sector extraction
- [ ] Write `test_order.py` — position calculation, interval computation, edge cases (DNF, single driver)
- [ ] Write `test_weather.py` — rain event pairing, is_raining check
- [ ] Write `test_config.py` — env var priority, config file, defaults
- [ ] Write `test_api.py` — Flask test client for all 3 endpoints + error cases

### 1.4 Dev Tooling

- [ ] Create `Makefile` with targets:
  - `make install` — pip install -e ".[dev]"
  - `make test` — pytest with coverage
  - `make lint` — flake8 + isort check
  - `make format` — black + isort
  - `make typecheck` — mypy (optional)
  - `make clean` — remove build artifacts and cache
  - `make run` — run Flask dev server
- [ ] Add `mypy` to dev dependencies and create basic `pyproject.toml` section
- [ ] Set up pre-commit hooks (black, isort, flake8) — deps exist but hooks not configured

---

## Phase 2 — Code Structure

Split monolithic files, deduplicate code, fix quality issues.

### 2.1 Split Monolithic Frontend

Split `api/templates/index.html` (4,292 lines) into modules:

- [ ] Extract CSS to `api/static/css/main.css`
- [ ] Extract core viewer class to `api/static/js/viewer.js` (F1RaceViewer)
- [ ] Extract track renderer to `api/static/js/track-renderer.js` (canvas drawing)
- [ ] Extract race controller to `api/static/js/race-controller.js` (playback, time, speed)
- [ ] Extract data service to `api/static/js/data-service.js` (API fetching, tier loading)
- [ ] Extract UI components to `api/static/js/ui-components.js` (standings, messages, selectors)
- [ ] Extract status managers to `api/static/js/status-manager.js` (TrackStatus, RaceControl, StartingLights)
- [ ] Update `index.html` to load external CSS and JS files
- [ ] Verify all functionality still works after split

### 2.2 Split Large Python Files

#### `loaders/session/processor.py` (1,806 lines → target ~400 each)

- [ ] Extract track status building to `loaders/session/track_status.py` (_extract_track_status, _consolidate_track_status_intervals)
- [ ] Extract event building to `loaders/session/events.py` (_build_events, _build_race_events, _build_practice_events)
- [ ] Extract results building to `loaders/session/results.py` (_build_results, _build_fastest_laps, _build_position_history)
- [ ] Extract t0/timing logic to `loaders/session/timing.py` (_build_t0_info, _detect_lights_out)
- [ ] Keep `processor.py` as orchestrator only (build_session + glue)

#### `loaders/session/telemetry.py` (1,386 lines → target ~500 + 400)

- [ ] Extract track extraction to `loaders/session/track_extract.py` (_extract_track_and_pit → split into _extract_track and _extract_pit)
- [ ] Keep telemetry building in `telemetry.py` (driver telemetry, status, lap info)

#### `managers/race_manager.py` (1,098 lines)

- [ ] Extract 5 duplicate schedule methods into single `_get_schedule(year, session_filter)` helper
- [ ] Extract schedule methods to `managers/schedule.py`

#### `tools/weekend_plot.py` (603-line single function)

- [ ] Split `plot_weekend` into: `_draw_track()`, `_draw_corners()`, `_draw_header()`, `_draw_elevation()`
- [ ] Extract magic layout numbers (0.01, 0.27, 0.59, 0.84...) into named constants or a layout config

### 2.3 Code Quality Fixes

- [ ] Deduplicate location aliases (weekend/processor.py + track_finder.py → shared `loaders/core/locations.py`)
- [ ] Deduplicate race vs practice event building in session/processor.py (~100+ lines near-identical)
- [ ] Replace bare `except:` clauses in weekend/processor.py with specific exceptions
- [ ] Add constants file for magic numbers (timeout windows 120s/180s, thresholds 5.0dm, pit window 60s, etc.)
- [ ] Move function-level `import fastf1` in `app.py:_get_scheduled_session_info` to top of file (consistent with rest of codebase)
- [ ] Remove `TrackTransformer` duplicate pit lane caching pattern (mirrors track caching unnecessarily)

### 2.4 Bug Risk Fixes

- [ ] Audit and fix unit inconsistency: decimeters vs meters across `telemetry.py`, `light_telemetry.py`, `weekend/processor.py` — document convention at module level
- [ ] Add validation for pit in/out pairing in `light_telemetry.py` (currently unvalidated)
- [ ] Add monotonicity assertion for `race_distance` in `order.py`
- [ ] Handle winner-DNF case in track extraction (`telemetry.py` — falls back to next finisher)
- [ ] Add explicit NaN handling in interval calculation when P1 data is missing (`order.py`)
- [ ] Add warning when optional columns (Speed, Throttle, Brake) are missing in `light_telemetry.py` (currently silent)

---

## Phase 3 — Flask Architecture

Improve the web app structure and developer workflow.

### 3.1 Flask Refactoring

- [x] Refactor `create_app()` to use Flask Blueprints for routes
- [x] Separate API routes (`/api/*`) from UI routes (`/`) into distinct blueprints
- [x] Add Flask hot reload for template/static changes (TEMPLATES_AUTO_RELOAD=True)

### 3.2 CI/CD Improvements

- [x] Update CI test job to run `pytest` with coverage across Python 3.9-3.13 matrix
- [x] Add lint job to CI workflow (black --check, isort --check, flake8)
- [x] Add coverage reporting (pytest-cov, upload artifact)
- [x] Verify Python 3.13 works in test matrix
- [x] Add `make check` target (lint + test) + CLAUDE.md instruction
- [x] Centralize flake8 config in `.flake8`, fix all flake8 errors

---

## Phase 4 — Frontend Features

Enhance the race viewer with missing visualization features.

### 4.1 Interaction

- [ ] Add keyboard shortcuts (space=play/pause, left/right=seek, +/-=speed)
- [ ] Add session switching in UI (tabs or dropdown to switch Race/Quali/FP)
- [ ] Add responsive mobile warning or proper mobile layout (sidebar is fixed 360px)

### 4.2 Visualization

- [ ] Add pit stop visualization (pit stop timing overlay, in/out markers on track)
- [ ] Add tyre strategy timeline (stint lengths, compound choices, horizontal bar chart)
- [ ] Add lap time chart (race pace, delta to leader over laps)
- [ ] Add qualifying visualization (lap times, sector comparison)

### 4.3 Data

- [ ] Add data export (CSV/JSON download of telemetry for selected driver/session)
- [ ] Consider WebSocket/SSE for real-time updates (currently full payload on load)

---

## Phase 5 — Documentation

Make the project approachable for contributors and users.

### 5.1 Developer Docs

- [ ] Add `CONTRIBUTING.md` with setup guide, coding conventions, PR process
- [ ] Add architecture diagram (ASCII or mermaid) showing 3-tier data flow
- [ ] Document unit conventions in a central place (coordinates=decimeters, distances=meters)

### 5.2 API Docs

- [ ] Add OpenAPI/Swagger spec for Flask API endpoints (or at minimum a markdown API reference)
- [ ] Document telemetry column schema (what each column means, units, ranges)

### 5.3 User Docs

- [ ] Un-gitignore and update Jupyter notebooks as runnable examples
- [ ] Add screenshots/GIFs of race viewer to README
- [ ] Add "Development" section to README (how to run from source, run tests, etc.)

---

## Phase 6 — Legacy Cleanup

Remove backward-compatibility code that adds complexity.

- [ ] Remove `_extract_track_legacy()` from `managers/race_manager.py` (or gate behind explicit flag)
- [ ] Remove `update_weekend_track()` from `managers/dataloader.py` (only needed for old cache format)
- [ ] Add cache migration script as alternative (convert old Weekend.pkl → new format, then remove compat code)
