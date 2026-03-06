"""
Migrate legacy cache files that have placeholder track geometry.

Walks race_data/*/Weekend.pkl, identifies caches with empty track data,
re-extracts track geometry using the current pipeline, and re-saves.

Usage:
    f1-replay migrate-cache
    f1-replay migrate-cache --cache-dir /path/to/data --dry-run
"""

import pickle
from pathlib import Path

from f1_replay.log import logger, setup_logging


def find_legacy_weekends(cache_dir: Path):
    """Find Weekend.pkl files with placeholder (empty) track geometry."""
    legacy = []
    for pkl_path in sorted(cache_dir.rglob("Weekend.pkl")):
        try:
            with open(pkl_path, "rb") as f:
                weekend = pickle.load(f)
            track = weekend.circuit.track
            if track.x is None or len(track.x) == 0:
                legacy.append((pkl_path, weekend))
        except Exception as e:
            logger.warning(f"  Could not read {pkl_path}: {e}")
    return legacy


def migrate_weekend(pkl_path: Path, weekend):
    """Re-extract track geometry for a legacy weekend and re-save."""
    from f1_replay.loaders.session.telemetry import TelemetryBuilder
    from f1_replay.managers import DataLoader

    # Parse year from path: cache_dir/<year>/<location>/Weekend.pkl
    year_dir = pkl_path.parent.parent
    try:
        year = int(year_dir.name)
    except ValueError:
        logger.warning(f"  Skip {pkl_path}: cannot parse year from path")
        return False

    cache_dir = year_dir.parent
    loader = DataLoader(cache_dir=str(cache_dir))

    # Find matching event
    event = weekend.event
    round_num = event.round_number

    # Try to load race results and extract track
    results = loader.load_race_results(year, round_num)
    if not results:
        logger.warning(f"  Skip {event.name} ({year}): no race results available")
        return False

    raw_session = loader.get_raw_session(year, round_num, "R")
    if not raw_session:
        logger.warning(f"  Skip {event.name} ({year}): cannot load raw session")
        return False

    track_data = TelemetryBuilder.extract_track_from_driver(raw_session, results.winner)
    if track_data is None:
        logger.warning(f"  Skip {event.name} ({year}): track extraction failed")
        return False

    # Use WeekendProcessor to rebuild weekend with track
    from f1_replay.loaders.weekend.processor import WeekendProcessor

    processor = WeekendProcessor(loader._client)
    rebuilt = processor.build_weekend(event, year, round_num)
    if rebuilt and rebuilt.circuit.track.x is not None and len(rebuilt.circuit.track.x) > 0:
        with open(pkl_path, "wb") as f:
            pickle.dump(rebuilt, f, protocol=pickle.HIGHEST_PROTOCOL)
        logger.info(
            f"  Migrated: {event.name} ({year}) - {rebuilt.circuit.circuit_length:.0f}m track"
        )
        return True

    logger.warning(f"  Skip {event.name} ({year}): rebuild produced no track")
    return False


def run_migration(cache_dir: str = None, dry_run: bool = False):
    """Run cache migration."""
    setup_logging()

    if cache_dir is None:
        from f1_replay.config import get_cache_dir

        cache_dir = get_cache_dir()

    cache_path = Path(cache_dir)
    if not cache_path.exists():
        logger.error(f"Cache directory not found: {cache_path}")
        return

    logger.info(f"Scanning {cache_path} for legacy caches...")
    legacy = find_legacy_weekends(cache_path)

    if not legacy:
        logger.info("No legacy caches found. Nothing to migrate.")
        return

    logger.info(f"Found {len(legacy)} legacy cache(s)")

    if dry_run:
        for pkl_path, weekend in legacy:
            print(f"  Would migrate: {weekend.event.name} ({pkl_path.parent.parent.name})")
        return

    migrated = 0
    for pkl_path, weekend in legacy:
        logger.info(f"Migrating {weekend.event.name}...")
        if migrate_weekend(pkl_path, weekend):
            migrated += 1

    logger.info(f"Migration complete: {migrated}/{len(legacy)} caches updated")
