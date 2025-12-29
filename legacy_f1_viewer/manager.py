"""
RaceManager - Lightweight coordinator for F1 Viewer app.

Coordinates DataLoader and Flask app integration. Provides clean, user-friendly API.
"""

from typing import TYPE_CHECKING, Optional

from .data_loader import DataLoader, F1Catalog, SeasonInfo

if TYPE_CHECKING:
    from flask import Flask


class RaceManager:
    """
    Lightweight application-focused API for F1 Viewer.

    Coordinates data loading via DataLoader and Flask app integration.
    Provides simple methods to load races and launch the viewer.

    Usage:
        manager = RaceManager()

        # Launch race directly
        manager.race(2024, 21)

        # Get Race object for data exploration
        race = manager.get_race(2024, 21)
        print(race)

        # Access season catalog
        season_info = manager.get_season(2024)
        for race in season_info.races:
            print(f"{race.round_number}: {race.event_name}")

        # Create app without running
        app = manager.create_app(2024, 21)
        app.run()
    """

    def __init__(self, cache_dir: str = "race_data"):
        """Initialize manager with cache directory."""
        self.data_loader = DataLoader(cache_dir)
        self._current_race = None
        self._catalog: Optional[F1Catalog] = None

    def race(self, year: int, round_num: int,
             host: str = '0.0.0.0', port: int = 5000,
             debug: bool = True) -> None:
        """
        Load race and launch Flask app.

        Downloads/caches race data from FastF1 and starts the viewer.

        Args:
            year: Season year
            round_num: Round number (1-24)
            host: Server host (default: 0.0.0.0)
            port: Server port (default: 5000)
            debug: Enable Flask debug mode (default: True)
        """
        from .app.app import create_app

        # Load race data
        race = self.data_loader.load_race(year, round_num)
        self._current_race = race

        # Create Flask app (pass manager for catalog access)
        app = create_app(race, manager=self)

        # Start server
        print(f"\n{'='*60}")
        print(f"✓ Starting F1 Viewer: {race.event_name} ({year})")
        print(f"{'='*60}")
        print(f"Open your browser to: http://{host}:{port}")
        print(f"Press Ctrl+C to stop")
        print(f"{'='*60}\n")

        app.run(host=host, port=port, debug=debug)

    def view(self, year: int, round_num: int,
             host: str = '0.0.0.0', port: int = 5000,
             debug: bool = True) -> None:
        """
        Load weekend and launch Flask app.

        Currently an alias for race() - only race viewer is implemented.
        Future: Will support viewing practice, qualifying, sprint, race.

        Args:
            year: Season year
            round_num: Round number (1-24)
            host: Server host (default: 0.0.0.0)
            port: Server port (default: 5000)
            debug: Enable Flask debug mode (default: True)
        """
        self.race(year, round_num, host, port, debug)

    def create_app(self, year: int, round_num: int) -> 'Flask':
        """
        Create Flask app without running server.

        Loads race data and creates Flask app for manual control.

        Args:
            year: Season year
            round_num: Round number (1-24)

        Returns:
            Flask app instance (not running)
        """
        from .app.app import create_app

        race = self.data_loader.load_race(year, round_num)
        self._current_race = race
        return create_app(race, manager=self)

    def get_race(self, year: int, round_num: int) -> 'Race':
        """
        Get Race instance without launching app.

        Loads race data for data exploration and analysis.

        Args:
            year: Season year
            round_num: Round number (1-24)

        Returns:
            Race instance with all preprocessed data
        """
        return self.data_loader.load_race(year, round_num)

    @property
    def catalog(self) -> F1Catalog:
        """
        Get F1 catalog (all seasons).

        Cached in memory for performance. Updated incrementally when
        new seasons are accessed.

        Returns:
            F1Catalog containing all seasons and races
        """
        if self._catalog is None:
            print("→ Loading F1 catalog...")
            self._catalog = self.data_loader.load_catalog()
            print(f"✓ Catalog loaded: {len(self._catalog.seasons)} seasons")
        return self._catalog

    def get_season(self, year: int) -> Optional[SeasonInfo]:
        """
        Get season info from catalog.

        Args:
            year: Season year (e.g., 2024)

        Returns:
            SeasonInfo with all races in that season, or None if not found

        Example:
            manager = RaceManager()
            season_2024 = manager.get_season(2024)
            for race_info in season_2024.races:
                print(f"{race_info.round_number}: {race_info.event_name}")
        """
        return self.catalog.seasons.get(year)

    def reprocess(self, year: int, round_num: int):
        """
        Force reprocess of a race from FastF1.

        Clears cache and reprocesses all race data from FastF1.
        Useful when FastF1 data is updated or for recalculations.

        Args:
            year: Season year
            round_num: Round number (1-24)

        Returns:
            Race object with fresh data from FastF1
        """
        print(f"\n⚠ Force reprocessing race data for {year} Round {round_num}...")
        race = self.data_loader.load_race(year, round_num, force_reprocess=True)
        print(f"✓ Reprocessing complete!\n")

        return race
