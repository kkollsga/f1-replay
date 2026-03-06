# f1-replay Developer Experience Overhaul

---

## Phase 1 — Foundation ✅

Get the basics right: fix broken things, add tests, set up dev tooling.

### 1.1 Project Hygiene

- [x] Fix version mismatch: `pyproject.toml` says `0.1.10`, `__init__.py` says `0.1.0`
- [x] Add `scipy` to dependencies in `pyproject.toml` (used for `cKDTree` in `models/weekend.py`)
- [x] Add `matplotlib` to dependencies in `pyproject.toml` (used in `tools/weekend_plot.py`)
- [x] Remove stale `setup.py` (redundant with `pyproject.toml`)
- [x] Remove `legacy_f1_user/` reference from `CLAUDE.md` (directory doesn't exist)
- [x] Add `[project.optional-dependencies]` `all` group with scipy, matplotlib, orjson, flask-cors
- [x] Un-gitignore notebooks (`DataLoading.ipynb`, `Race.ipynb`) so they serve as docs for others

### 1.2 Logging

- [x] Add `logging` module setup in `f1_replay/log.py` with named logger
- [x] Replace all `print()` calls in loaders/managers/api with logger
- [x] Add log level configuration via `F1_REPLAY_LOG_LEVEL` env var

### 1.3 Test Infrastructure

- [x] 196 tests across 11 files (models, mapping, serializers, track_geometry, order, weather, config, api, log, events, telemetry, track_extract)
- [x] `conftest.py` with mock fixtures

### 1.4 Dev Tooling

- [x] `Makefile` with install, test, test-cov, lint, format, clean, run, check targets
- [x] CI runs pytest + lint (black, isort, flake8)

---

## Phase 2 — Code Structure ✅

### 2.1 Split Monolithic Frontend

- [x] Extract CSS to `api/static/css/main.css` (1344 lines)
- [x] Extract constants to `api/static/js/constants.js` (39 lines)
- [x] Extract status managers to `api/static/js/status-managers.js` (267 lines — TrackStatus, RaceControl, StartingLightsManager)
- [x] Extract viewer to `api/static/js/viewer.js` (3311 lines — F1RaceViewer)
- [x] `index.html` reduced from 5146 → 185 lines (HTML + Jinja + script tags)

### 2.2 Split Large Python Files

- [x] `processor.py` split: events.py, results.py, track_extract.py extracted (1806 → 710 lines)
- [x] `telemetry.py` split: track_extract.py extracted (1386 → 907 lines)
- [x] `weekend_plot.py`: duplicated `get_label_params` extracted to module-level `_get_label_params`

### 2.3 Code Quality Fixes

- [x] Location aliases deduplicated in `services/track_finder.py`
- [x] Race vs practice event building unified (`build_events()`)
- [x] Bare except clauses replaced with specific exceptions
- [x] Function-level import in app.py intentional (lazy FastF1 load)

### 2.4 Bug Risk Fixes

- [x] Unit conventions documented and correct (decimeters in loaders, meters in public API)
- [x] Pit in/out validation implemented (searchsorted)
- [x] Race_distance monotonicity warning added to telemetry.py
- [x] Winner-DNF fallback handled in track_extract.py
- [x] Interval NaN handling comprehensive in order.py
- [x] Missing optional columns (Speed/Throttle/Brake) warning added to light_telemetry.py

---

## Phase 3 — Flask Architecture ✅

- [x] Flask Blueprints (api_bp, ui_bp)
- [x] CI: pytest + lint across Python matrix
- [x] `make check` = lint + test

---

## Phase 4 — Frontend Features ✅

### 4.1 Interaction

- [x] Keyboard shortcuts (space, arrows, shift+arrows, +/-, C, Esc, L, S)
- [x] Session switching tabs (dynamic from weekend data)
- [x] Responsive mobile layout

### 4.2 Visualization

- [x] Pit stop visualization (dots on progress bar, strategy panel with stint bars)
- [x] Tyre strategy timeline (compound choices, time marker)
- [x] Lap time chart (top 5 + chased driver, L key toggle)
- [x] Qualifying results view (delta to pole, Q1/Q2/Q3 grouping)

### 4.3 Data

- [x] Data export (CSV/JSON download buttons)
- [ ] Consider WebSocket/SSE for real-time updates (future)

---

## Phase 5 — Documentation

- [ ] Add `CONTRIBUTING.md` with setup guide
- [ ] Add architecture diagram to README
- [ ] Document unit conventions
- [ ] API endpoint docs

---

## Phase 6 — Legacy Cleanup ✅

- [x] Created `f1_replay/tools/migrate_cache.py` — migration script for legacy Weekend.pkl files
- [x] Added `f1-replay migrate-cache` CLI command (with `--dry-run`)
- [x] Removed `_extract_track_legacy()` from `race_manager.py` (~95 lines)
- [x] Removed `update_weekend_track()` from `dataloader.py` (~150 lines)
- [x] Legacy cache now shows error pointing to `f1-replay migrate-cache`
