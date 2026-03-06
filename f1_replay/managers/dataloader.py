"""
Main DataLoader - Orchestrates 3-tier data loading and caching

Tier 1: Seasons (seasons.pkl) - Dict[int, List[EventInfo]]
Tier 2: F1Weekend (year/round_location/Weekend.pkl)
Tier 3: SessionData (year/round_location/SessionType.pkl)
"""

import pickle
from pathlib import Path
from typing import Optional

from f1_replay.loaders.core.client import FastF1Client
from f1_replay.loaders.core.mapping import to_fastf1_code, to_user_friendly
from f1_replay.loaders.seasons.processor import SeasonsCatalog, SeasonsProcessor
from f1_replay.loaders.session.processor import SessionProcessor
from f1_replay.loaders.weekend.processor import WeekendProcessor
from f1_replay.log import logger
from f1_replay.models import (
    EventInfo,
    F1Weekend,
    LoadResult,
    RaceResults,
)


class DataLoader:
    """
    Main data loader orchestrating 3-tier caching.

    Usage:
        loader = DataLoader()
        seasons = loader.load_seasons()  # TIER 1
        weekend = loader.load_weekend(2024, 1)  # TIER 2
        session = loader.load_session(2024, 1, "Race")  # TIER 3
    """

    def __init__(self, cache_dir: str = None):
        """
        Initialize DataLoader.

        Args:
            cache_dir: Directory for caching. If None, uses system default
                (~/Documents/f1-replay on macOS/Windows, ~/.local/share/f1-replay on Linux).
        """
        if cache_dir is None:
            from f1_replay.config import get_cache_dir

            cache_dir = get_cache_dir()
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        # Initialize clients and processors
        self.fastf1_client = FastF1Client(self.cache_dir)
        self.seasons_processor = SeasonsProcessor(self.fastf1_client)
        self.weekend_processor = WeekendProcessor(self.fastf1_client)

        # Memory cache to avoid repeated disk reads
        self._seasons_cache: Optional[SeasonsCatalog] = None

        logger.info(f"✓ DataLoader initialized: {self.cache_dir}")

    # =========================================================================
    # TIER 1: Seasons Catalog
    # =========================================================================

    def load_seasons(
        self, years: list = None, force_update: bool = False
    ) -> Optional[SeasonsCatalog]:
        """
        Load F1 seasons catalog (TIER 1).

        File: race_data/seasons.pkl

        Automatically fetches current year if missing from cache.

        Args:
            years: List of years to fetch (default: current year + 5 previous years)
            force_update: Force rebuild from FastF1

        Returns:
            Dict[int, List[EventInfo]] or None
        """
        # Return memory cache if available (and not forcing update)
        if self._seasons_cache is not None and not force_update:
            return self._seasons_cache

        from datetime import datetime

        current_year = datetime.now().year

        if years is None:
            # Default: current year and 5 previous years
            years = list(range(current_year - 5, current_year + 1))

        seasons_path = self.cache_dir / "seasons.pkl"

        # Try disk cache
        if seasons_path.exists() and not force_update:
            try:
                with open(seasons_path, "rb") as f:
                    seasons = pickle.load(f)

                # Check if current year is missing from cache
                if current_year not in seasons:
                    logger.warning(f"⚠ Cache missing {current_year}, fetching...")
                    new_rounds = self.seasons_processor._fetch_year(current_year)
                    if new_rounds:
                        seasons[current_year] = new_rounds
                        # Update disk cache
                        with open(seasons_path, "wb") as f:
                            pickle.dump(seasons, f, protocol=pickle.HIGHEST_PROTOCOL)
                        logger.info(f"✓ Added {current_year} to cache ({len(new_rounds)} rounds)")

                logger.info(f"✓ Loaded seasons from cache: {sorted(seasons.keys())}")
                self._seasons_cache = seasons  # Store in memory
                return seasons
            except Exception as e:
                logger.warning(f"⚠ Could not load cached seasons: {e}")

        # Build from FastF1
        logger.info("📡 Building seasons catalog from FastF1...")
        seasons = self.seasons_processor.build_seasons(years)

        if seasons is None:
            return None

        # Cache to disk
        try:
            with open(seasons_path, "wb") as f:
                pickle.dump(seasons, f, protocol=pickle.HIGHEST_PROTOCOL)
            logger.info(f"✓ Cached seasons to {seasons_path}")
        except Exception as e:
            logger.warning(f"⚠ Could not cache seasons: {e}")

        self._seasons_cache = seasons  # Store in memory
        return seasons

    # =========================================================================
    # TIER 2: Race Weekend
    # =========================================================================

    def load_weekend(
        self,
        year: int,
        round_num: int,
        event: EventInfo,
        force_reprocess: bool = False,
        force_update: bool = False,
    ) -> Optional[F1Weekend]:
        """
        Load race weekend data (TIER 2): circuit + metadata.

        File: race_data/year/round_location/Weekend.pkl

        Args:
            year: Season year
            round_num: Round number
            event: EventInfo from seasons catalog
            force_reprocess: Force rebuild from FastF1
            force_update: Alias for force_reprocess (for API consistency)

        Returns:
            F1Weekend object or None
        """
        # Support both force_reprocess and force_update for consistency
        force_reprocess = force_reprocess or force_update

        # Build cache path
        location_dir = self.seasons_processor.get_event_location_dir(event)
        weekend_dir = self.cache_dir / str(year) / location_dir
        weekend_dir.mkdir(parents=True, exist_ok=True)

        weekend_path = weekend_dir / "Weekend.pkl"

        # Try cache
        if weekend_path.exists() and not force_reprocess:
            try:
                with open(weekend_path, "rb") as f:
                    weekend = pickle.load(f)
                logger.info(f"✓ Loaded weekend from cache: {event.name}")
                return weekend
            except Exception as e:
                logger.warning(f"⚠ Could not load cached weekend: {e}")

        # Build from FastF1
        logger.info("📡 Building weekend data from FastF1...")

        # For testing events (round=0), use dedicated testing API
        is_testing = event.format == "testing"
        if is_testing:
            # Extract test number from event (stored by Manager)
            test_number = getattr(event, "test_number", 1)
            weekend = self.weekend_processor.build_weekend(year, round_num, test_number=test_number)
        else:
            weekend = self.weekend_processor.build_weekend(year, round_num)

        if weekend is None:
            return None

        # Cache
        try:
            with open(weekend_path, "wb") as f:
                pickle.dump(weekend, f, protocol=pickle.HIGHEST_PROTOCOL)
            logger.info(f"✓ Cached weekend to {weekend_path}")
        except Exception as e:
            logger.warning(f"⚠ Could not cache weekend: {e}")

        return weekend

    # =========================================================================
    # TIER 3: Session Data
    # =========================================================================

    def load_session(
        self,
        year: int,
        round_num: int,
        session_type: str,
        event: EventInfo,
        circuit_length: float,
        weekend_track=None,
        force_reprocess: bool = False,
        force_update: bool = False,
    ) -> Optional[LoadResult]:
        """
        Load session data (TIER 3): telemetry, events, results.

        File: race_data/year/round_location/{SessionType}.pkl
        Example: race_data/2024/08_Monaco/Race.pkl

        Args:
            year: Season year
            round_num: Round number
            session_type: User-friendly names ("Race", "Qualifying", "Practice1", etc.)
                         or FastF1 codes ("R", "Q", "FP1", etc.)
            event: EventInfo from seasons catalog
            circuit_length: Circuit length in meters (from weekend)
            weekend_track: Optional TrackGeometry from Weekend (for adding track_distance to telemetry)
            force_reprocess: Force rebuild from FastF1
            force_update: Alias for force_reprocess (for API consistency)

        Returns:
            LoadResult with .data (SessionData) and .raw_session (FastF1 session or None)
            raw_session is only populated when freshly processed (not from cache)
        """
        # Support both force_reprocess and force_update for consistency
        force_reprocess = force_reprocess or force_update
        # Convert user-friendly session type to FastF1 code
        try:
            fastf1_code = to_fastf1_code(session_type)
        except ValueError as e:
            logger.error(f"✗ {e}")
            return None

        # Build cache path (use user-friendly name for file)
        location_dir = self.seasons_processor.get_event_location_dir(event)
        session_dir = self.cache_dir / str(year) / location_dir
        session_dir.mkdir(parents=True, exist_ok=True)

        # Convert fastf1_code to user-friendly name for filename
        user_friendly_name = to_user_friendly(fastf1_code)
        session_path = session_dir / f"{user_friendly_name}.pkl"

        # Try cache (raw_session is None when loaded from cache)
        if session_path.exists() and not force_reprocess:
            try:
                with open(session_path, "rb") as f:
                    session = pickle.load(f)
                logger.info(f"✓ Loaded session from cache: {session_type}")
                return LoadResult(data=session, raw_session=None)
            except Exception as e:
                logger.warning(f"⚠ Could not load cached session: {e}")

        # Build from FastF1
        logger.info("📡 Building session data from FastF1...")

        # Create processor with circuit length and weekend track
        processor = SessionProcessor(
            self.fastf1_client, circuit_length=circuit_length, weekend_track=weekend_track
        )

        result = processor.build_session(year, round_num, fastf1_code, event.name)

        if result is None:
            return None

        # Note: _track_data is None in new flow (track extracted during weekend build, not session)
        session, raw_session, _track_data = result

        # Cache (only SessionData, not raw_session)
        try:
            with open(session_path, "wb") as f:
                pickle.dump(session, f, protocol=pickle.HIGHEST_PROTOCOL)
            logger.info(f"✓ Cached session to {session_path}")
        except Exception as e:
            logger.warning(f"⚠ Could not cache session: {e}")

        return LoadResult(data=session, raw_session=raw_session)

    # =========================================================================
    # Incremental Loading (for Manager)
    # =========================================================================

    def load_race_results(self, year: int, round_num: int) -> Optional[RaceResults]:
        """
        Load just race results (positions, winner) without full telemetry.

        Returns:
            RaceResults with winner and raw_session, or None
        """
        f1_session = self.fastf1_client.get_session(year, round_num, "R", load_telemetry=False)
        if f1_session is None:
            return None

        try:
            results = f1_session.results
            if results is None or len(results) == 0:
                return None

            # Get winner (P1)
            winner_row = results[results["Position"] == 1]
            if len(winner_row) == 0:
                return None

            winner = winner_row["Abbreviation"].iloc[0]
            return RaceResults(winner=winner, raw_session=f1_session)
        except Exception as e:
            logger.warning(f"  ⚠ Could not load race results: {e}")
            return None

    def get_raw_session(self, year: int, round_num: int, session_type: str = "R"):
        """
        Get raw FastF1 session with telemetry loaded.

        This is a pass-through to fastf1_client for Manager orchestration.
        """
        return self.fastf1_client.get_session_with_all_data(year, round_num, session_type)

    def get_event(self, year: int, round_num: int) -> Optional[EventInfo]:
        """Get EventInfo from seasons catalog."""
        seasons = self.load_seasons()
        if seasons is None:
            return None
        season = seasons.get(year)
        if season is None:
            return None
        for event in season:
            if event.round_number == round_num:
                return event
        return None

    def get_cache_info(self) -> dict:
        """Get information about cached data."""
        pkl_files = list(self.cache_dir.rglob("*.pkl"))
        seasons_pkl = self.cache_dir / "seasons.pkl"

        return {
            "cache_dir": str(self.cache_dir),
            "total_pkl_files": len(pkl_files),
            "seasons_cached": seasons_pkl.exists(),
            "cached_files": [str(f.relative_to(self.cache_dir)) for f in pkl_files],
        }

    def clear_cache(self, year: Optional[int] = None, round_num: Optional[int] = None):
        """
        Clear cached data.

        Args:
            year: If specified, only clear that year
            round_num: If specified with year, only clear that round
        """
        if year is None:
            # Clear everything
            import shutil

            shutil.rmtree(self.cache_dir)
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            logger.info(f"✓ Cleared all cache: {self.cache_dir}")
        elif round_num is None:
            # Clear specific year
            year_dir = self.cache_dir / str(year)
            if year_dir.exists():
                import shutil

                shutil.rmtree(year_dir)
                logger.info(f"✓ Cleared cache for {year}")
        else:
            # Clear specific round
            event = self.get_event(year, round_num)
            if event:
                location_dir = self.seasons_processor.get_event_location_dir(event)
                round_dir = self.cache_dir / str(year) / location_dir
                if round_dir.exists():
                    import shutil

                    shutil.rmtree(round_dir)
                    logger.info(f"✓ Cleared cache for {year} R{round_num}")
