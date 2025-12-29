"""
Main DataLoader - Orchestrates 3-tier data loading and caching

Tier 1: F1Seasons (seasons.pkl)
Tier 2: F1Weekend (year/round_location/Weekend.pkl)
Tier 3: SessionData (year/round_location/SessionType.pkl)
"""

import pickle
from pathlib import Path
from typing import Optional

from f1_replay.data_loader.data_models import F1Seasons, F1Weekend, SessionData
from f1_replay.data_loader.fastf1_client import FastF1Client
from f1_replay.data_loader.seasons_processor import SeasonsProcessor
from f1_replay.data_loader.weekend_processor import WeekendProcessor
from f1_replay.data_loader.session_processor import SessionProcessor
from f1_replay.data_loader.session_mapping import to_fastf1_code, to_user_friendly


class DataLoader:
    """
    Main data loader orchestrating 3-tier caching.

    Usage:
        loader = DataLoader()
        seasons = loader.load_seasons()  # TIER 1
        weekend = loader.load_weekend(2024, 1)  # TIER 2
        session = loader.load_session(2024, 1, "Race")  # TIER 3
    """

    def __init__(self, cache_dir: str = "race_data"):
        """
        Initialize DataLoader.

        Args:
            cache_dir: Directory for caching (default: "race_data")
        """
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        # Initialize clients and processors
        self.fastf1_client = FastF1Client(self.cache_dir)
        self.seasons_processor = SeasonsProcessor(self.fastf1_client)
        self.weekend_processor = WeekendProcessor(self.fastf1_client)

        print(f"✓ DataLoader initialized: {self.cache_dir}")

    # =========================================================================
    # TIER 1: Seasons Catalog
    # =========================================================================

    def load_seasons(self, years: list = None, force_update: bool = False) -> Optional[F1Seasons]:
        """
        Load F1 seasons catalog (TIER 1).

        File: race_data/seasons.pkl

        Args:
            years: List of years to fetch (default: [2023, 2024])
            force_update: Force rebuild from FastF1

        Returns:
            F1Seasons object or None
        """
        if years is None:
            years = [2023, 2024]

        seasons_path = self.cache_dir / "seasons.pkl"

        # Try cache
        if seasons_path.exists() and not force_update:
            try:
                with open(seasons_path, 'rb') as f:
                    seasons = pickle.load(f)
                print(f"✓ Loaded seasons from cache: {list(seasons.years.keys())}")
                return seasons
            except Exception as e:
                print(f"⚠ Could not load cached seasons: {e}")

        # Build from FastF1
        print(f"\n📡 Building seasons catalog from FastF1...")
        seasons = self.seasons_processor.build_seasons(years)

        if seasons is None:
            return None

        # Cache
        try:
            with open(seasons_path, 'wb') as f:
                pickle.dump(seasons, f, protocol=pickle.HIGHEST_PROTOCOL)
            print(f"✓ Cached seasons to {seasons_path}\n")
        except Exception as e:
            print(f"⚠ Could not cache seasons: {e}")

        return seasons

    # =========================================================================
    # TIER 2: Race Weekend
    # =========================================================================

    def load_weekend(self, year: int, round_num: int,
                    force_reprocess: bool = False, force_update: bool = False) -> Optional[F1Weekend]:
        """
        Load race weekend data (TIER 2): circuit + metadata.

        File: race_data/year/round_location/Weekend.pkl

        Args:
            year: Season year
            round_num: Round number
            force_reprocess: Force rebuild from FastF1
            force_update: Alias for force_reprocess (for API consistency)

        Returns:
            F1Weekend object or None
        """
        # Support both force_reprocess and force_update for consistency
        force_reprocess = force_reprocess or force_update
        # Get round location for directory
        seasons = self.load_seasons()
        if seasons is None or year not in seasons.years:
            print(f"✗ Year {year} not in catalog")
            return None

        f1_year = seasons.years[year]
        round_info = None
        for r in f1_year.rounds:
            if r.round_number == round_num:
                round_info = r
                break

        if round_info is None:
            print(f"✗ Round {round_num} not found in {year}")
            return None

        # Build cache path
        location_dir = self.seasons_processor.get_round_location_name(round_info)
        weekend_dir = self.cache_dir / str(year) / location_dir
        weekend_dir.mkdir(parents=True, exist_ok=True)

        weekend_path = weekend_dir / "Weekend.pkl"

        # Try cache
        if weekend_path.exists() and not force_reprocess:
            try:
                with open(weekend_path, 'rb') as f:
                    weekend = pickle.load(f)
                print(f"✓ Loaded weekend from cache: {round_info.event_name}")
                return weekend
            except Exception as e:
                print(f"⚠ Could not load cached weekend: {e}")

        # Build from FastF1
        print(f"\n📡 Building weekend data from FastF1...")
        weekend = self.weekend_processor.build_weekend(year, round_num)

        if weekend is None:
            return None

        # Cache
        try:
            with open(weekend_path, 'wb') as f:
                pickle.dump(weekend, f, protocol=pickle.HIGHEST_PROTOCOL)
            print(f"✓ Cached weekend to {weekend_path}\n")
        except Exception as e:
            print(f"⚠ Could not cache weekend: {e}")

        return weekend

    # =========================================================================
    # TIER 3: Session Data
    # =========================================================================

    def load_session(self, year: int, round_num: int, session_type: str,
                    force_reprocess: bool = False, force_update: bool = False) -> Optional[SessionData]:
        """
        Load session data (TIER 3): telemetry, events, results.

        File: race_data/year/round_location/{SessionType}.pkl
        Example: race_data/2024/08_Monaco/Race.pkl

        Args:
            year: Season year
            round_num: Round number
            session_type: User-friendly names ("Race", "Qualifying", "Practice1", etc.)
                         or FastF1 codes ("R", "Q", "FP1", etc.)
            force_reprocess: Force rebuild from FastF1
            force_update: Alias for force_reprocess (for API consistency)

        Returns:
            SessionData object or None
        """
        # Support both force_reprocess and force_update for consistency
        force_reprocess = force_reprocess or force_update
        # Convert user-friendly session type to FastF1 code
        try:
            fastf1_code = to_fastf1_code(session_type)
        except ValueError as e:
            print(f"✗ {e}")
            return None

        # Load weekend first to get circuit length and round info
        weekend = self.load_weekend(year, round_num)
        if weekend is None:
            print(f"✗ Could not load weekend {year} R{round_num}")
            return None

        # Get round location for directory
        seasons = self.load_seasons()
        f1_year = seasons.years[year]
        round_info = None
        for r in f1_year.rounds:
            if r.round_number == round_num:
                round_info = r
                break

        # Build cache path (use user-friendly name for file)
        location_dir = self.seasons_processor.get_round_location_name(round_info)
        session_dir = self.cache_dir / str(year) / location_dir
        session_dir.mkdir(parents=True, exist_ok=True)

        # Convert fastf1_code to user-friendly name for filename
        user_friendly_name = to_user_friendly(fastf1_code)
        session_path = session_dir / f"{user_friendly_name}.pkl"

        # Try cache
        if session_path.exists() and not force_reprocess:
            try:
                with open(session_path, 'rb') as f:
                    session = pickle.load(f)
                print(f"✓ Loaded session from cache: {session_type}")
                return session
            except Exception as e:
                print(f"⚠ Could not load cached session: {e}")

        # Build from FastF1
        print(f"\n📡 Building session data from FastF1...")

        # Create processor with circuit length
        processor = SessionProcessor(
            self.fastf1_client,
            circuit_length=weekend.circuit.circuit_length
        )

        session = processor.build_session(year, round_num, fastf1_code, round_info.event_name)

        if session is None:
            return None

        # Cache
        try:
            with open(session_path, 'wb') as f:
                pickle.dump(session, f, protocol=pickle.HIGHEST_PROTOCOL)
            print(f"✓ Cached session to {session_path}\n")
        except Exception as e:
            print(f"⚠ Could not cache session: {e}")

        return session

    # =========================================================================
    # Helpers
    # =========================================================================

    def get_cache_info(self) -> dict:
        """Get information about cached data."""
        pkl_files = list(self.cache_dir.rglob("*.pkl"))
        seasons_pkl = self.cache_dir / "seasons.pkl"

        return {
            'cache_dir': str(self.cache_dir),
            'total_pkl_files': len(pkl_files),
            'seasons_cached': seasons_pkl.exists(),
            'cached_files': [str(f.relative_to(self.cache_dir)) for f in pkl_files]
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
            print(f"✓ Cleared all cache: {self.cache_dir}")
        elif round_num is None:
            # Clear specific year
            year_dir = self.cache_dir / str(year)
            if year_dir.exists():
                import shutil
                shutil.rmtree(year_dir)
                print(f"✓ Cleared cache for {year}")
        else:
            # Clear specific round
            seasons = self.load_seasons()
            if seasons and year in seasons.years:
                f1_year = seasons.years[year]
                for r in f1_year.rounds:
                    if r.round_number == round_num:
                        location_dir = self.seasons_processor.get_round_location_name(r)
                        round_dir = self.cache_dir / str(year) / location_dir
                        if round_dir.exists():
                            import shutil
                            shutil.rmtree(round_dir)
                            print(f"✓ Cleared cache for {year} R{round_num}")
                        break
