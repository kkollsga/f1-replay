"""
Manager - Top-level coordinator for seasons catalog and race launching.

Provides convenient access to seasons data and methods to load races and launch the Flask viewer.
"""

from typing import Union, Optional, List
import webbrowser

from f1_replay.data_loader import DataLoader, F1Seasons, F1Year
from f1_replay.race_weekend import RaceWeekend
from f1_replay.session import Session


class Manager:
    """
    Top-level coordinator for F1 data and race viewer.

    Manages seasons catalog, loads race/session data, and launches Flask viewer app.

    Usage:
        manager = Manager(cache_dir='race_data')

        # Access season catalog
        seasons = manager.get_seasons()
        years = manager.list_years()

        # Load race data
        weekend = manager.load_weekend(2024, 24)
        session = manager.load_race(2024, 24)

        # Launch viewer (direct Flask app)
        manager.race(2024, 24)  # By round number
        manager.race(2024, "abu dhabi")  # By event name
    """

    def __init__(self, cache_dir: str = "race_data"):
        """
        Initialize Manager.

        Args:
            cache_dir: Directory for data caching (default: "race_data")
        """
        self.cache_dir = cache_dir
        self.data_loader = DataLoader(cache_dir)
        self._seasons: Optional[F1Seasons] = None

    # =========================================================================
    # Season Catalog Methods
    # =========================================================================

    def get_seasons(self, force_update: bool = False) -> Optional[F1Seasons]:
        """
        Load F1 seasons catalog (caches in memory).

        Args:
            force_update: Force rebuild from FastF1

        Returns:
            F1Seasons object or None
        """
        if self._seasons is None or force_update:
            self._seasons = self.data_loader.load_seasons(force_update=force_update)
        return self._seasons

    def get_season(self, year: int) -> Optional[F1Year]:
        """
        Get season data for specific year.

        Args:
            year: Season year

        Returns:
            F1Year object or None if year not found
        """
        seasons = self.get_seasons()
        if seasons is None:
            return None
        return seasons.years.get(year)

    def list_years(self) -> List[int]:
        """
        Get list of available years in catalog.

        Returns:
            Sorted list of year integers
        """
        seasons = self.get_seasons()
        if seasons is None:
            return []
        return sorted(seasons.years.keys())

    def _resolve_round_number(self, year: int, round_num_or_name: Union[int, str]) -> Optional[int]:
        """
        Resolve round number, supporting both round number and event name lookup.

        Args:
            year: Season year
            round_num_or_name: Round number (int) or event name (str, case-insensitive)

        Returns:
            Round number or None if not found
        """
        # If already a number, return as-is
        if isinstance(round_num_or_name, int):
            return round_num_or_name

        # Look up by event name (case-insensitive)
        season = self.get_season(year)
        if season is None:
            return None

        search_name = round_num_or_name.lower().strip()

        for round_info in season.rounds:
            # Check event name
            if round_info.event_name.lower() == search_name:
                return round_info.round_number

            # Check location
            if round_info.location.lower() == search_name:
                return round_info.round_number

            # Check partial match (for convenience)
            if search_name in round_info.event_name.lower():
                return round_info.round_number

        print(f"✗ Round '{round_num_or_name}' not found in {year}")
        return None

    # =========================================================================
    # Loading Methods
    # =========================================================================

    def load_weekend(self, year: int, round_num_or_name: Union[int, str],
                    force_update: bool = False) -> Optional[RaceWeekend]:
        """
        Load race weekend data (circuit geometry + metadata).

        Args:
            year: Season year
            round_num_or_name: Round number or event name
            force_update: Force rebuild from FastF1 (default: False)

        Returns:
            RaceWeekend wrapper or None
        """
        round_num = self._resolve_round_number(year, round_num_or_name)
        if round_num is None:
            return None

        weekend_data = self.data_loader.load_weekend(year, round_num, force_reprocess=force_update)
        if weekend_data is None:
            return None

        return RaceWeekend(weekend_data)

    def load_session(self, year: int, round_num_or_name: Union[int, str],
                    session_type: str = "R", force_update: bool = False) -> Optional[Session]:
        """
        Load session data (telemetry, events, results).

        Args:
            year: Season year
            round_num_or_name: Round number or event name
            session_type: Session type ("R", "Q", "FP1", "FP2", "FP3", "S") (default: "R")
            force_update: Force rebuild from FastF1 (default: False)

        Returns:
            Session wrapper or None
        """
        round_num = self._resolve_round_number(year, round_num_or_name)
        if round_num is None:
            return None

        # Load weekend data for context
        weekend = self.load_weekend(year, round_num, force_update=force_update)
        if weekend is None:
            return None

        # Load session data
        session_data = self.data_loader.load_session(year, round_num, session_type, force_reprocess=force_update)
        if session_data is None:
            return None

        return Session(session_data, weekend)

    def load_race(self, year: int, round_num_or_name: Union[int, str],
                 force_update: bool = False) -> Optional[Session]:
        """
        Load race session (alias for load_session with session_type='R').

        Args:
            year: Season year
            round_num_or_name: Round number or event name
            force_update: Force rebuild from FastF1 (default: False)

        Returns:
            Session wrapper for the race or None
        """
        return self.load_session(year, round_num_or_name, 'R', force_update=force_update)

    def process_season(self, year: int, force_update: bool = False) -> None:
        """
        Process all races in a season, loading weekend and race data.

        If force_update is True, all data will be reprocessed from FastF1 (not cached).
        Useful for bulk updating a season's data or warming up the cache.

        Args:
            year: Season year to process
            force_update: Force rebuild all races from FastF1 (default: False)
        """
        season = self.get_season(year)
        if season is None:
            print(f"✗ Season {year} not found")
            return

        total_rounds = len(season.rounds)
        print(f"\n📅 Processing {year} season ({total_rounds} rounds)...")
        if force_update:
            print(f"⚠️  Force updating all races from FastF1")

        successful = 0
        failed = 0

        for round_info in season.rounds:
            round_num = round_info.round_number
            event_name = round_info.event_name

            try:
                # Load weekend data
                weekend = self.load_weekend(year, round_num, force_update=force_update)
                if weekend is None:
                    print(f"  ✗ {round_num:2d}. {event_name}: Failed to load weekend data")
                    failed += 1
                    continue

                # Load race session
                race = self.load_race(year, round_num, force_update=force_update)
                if race is None:
                    print(f"  ✗ {round_num:2d}. {event_name}: Failed to load race session")
                    failed += 1
                    continue

                print(f"  ✓ {round_num:2d}. {event_name}")
                successful += 1

            except Exception as e:
                print(f"  ✗ {round_num:2d}. {event_name}: {str(e)}")
                failed += 1

        print(f"\n✓ Processed {successful}/{total_rounds} races successfully")
        if failed > 0:
            print(f"⚠️  {failed} races failed to process")

    # =========================================================================
    # Flask App Launching
    # =========================================================================

    def race(self, year: int, round_num_or_name: Union[int, str],
            host: str = '0.0.0.0', port: int = 5000, debug: bool = True,
            force_update: bool = False) -> None:
        """
        Load race and launch interactive Flask viewer.

        Supports both round number and event name:
            manager.race(2024, 24)              # By round number
            manager.race(2024, "abu dhabi")     # By event name
            manager.race(2024, "monaco")        # Partial match
            manager.race(2024, 8, force_update=True)  # Force rebuild from FastF1

        Args:
            year: Season year
            round_num_or_name: Round number (int) or event name (str)
            host: Host to bind Flask app (default: '0.0.0.0')
            port: Port to run Flask app (default: 5000)
            debug: Enable Flask debug mode (default: True)
            force_update: Force rebuild all data from FastF1 (default: False)
        """
        print(f"\n🏎️  Loading race: {year} Round {round_num_or_name}...")

        # Load the race session
        session = self.load_race(year, round_num_or_name, force_update=force_update)
        if session is None:
            print(f"✗ Failed to load race")
            return

        print(f"✓ Loaded: {session.event_name} ({session.year})")
        print(f"\n🚀 Starting Flask app on http://{host}:{port}...")

        # Create Flask app with this session and force_update flag
        from f1_replay.api import create_app
        app = create_app(self.data_loader, session, force_update=force_update)

        # Open browser
        try:
            webbrowser.open(f'http://localhost:{port}')
        except Exception:
            pass  # Browser open failed, user can open manually

        # Run Flask
        app.run(host=host, port=port, debug=debug)

    def view(self, year: int, round_num_or_name: Union[int, str],
            host: str = '0.0.0.0', port: int = 5000, debug: bool = True,
            force_update: bool = False) -> None:
        """
        Alias for race() - for future multi-session viewer support.

        Args:
            year: Season year
            round_num_or_name: Round number (int) or event name (str)
            host: Host to bind Flask app (default: '0.0.0.0')
            port: Port to run Flask app (default: 5000)
            debug: Enable Flask debug mode (default: True)
            force_update: Force rebuild all data from FastF1 (default: False)
        """
        self.race(year, round_num_or_name, host=host, port=port, debug=debug, force_update=force_update)

    def __repr__(self) -> str:
        """String representation."""
        years = self.list_years()
        return f"Manager(cache_dir={self.cache_dir!r}, years={years})"
