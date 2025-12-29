"""
FastF1 Client - Centralized FastF1 API Communication

All FastF1 API calls go through this module. Handles caching and error handling.
"""

from typing import Optional, Dict, Any, List
from pathlib import Path
import logging
import fastf1
import pandas as pd

# Suppress verbose FastF1 warnings (e.g., "Car number X cannot be located on track")
logging.getLogger('fastf1').setLevel(logging.ERROR)


class FastF1Client:
    """Centralized client for FastF1 API communication."""

    def __init__(self, cache_dir: Path):
        """
        Initialize FastF1 client.

        Args:
            cache_dir: Directory for FastF1 cache
        """
        self.cache_dir = cache_dir
        self._setup_cache()

    def _setup_cache(self):
        """Setup FastF1 caching."""
        fastf1_cache = self.cache_dir / ".fastf1_cache"
        fastf1_cache.mkdir(parents=True, exist_ok=True)
        fastf1.Cache.enable_cache(str(fastf1_cache))
        print(f"✓ FastF1 cache: {fastf1_cache}")

    # =========================================================================
    # Tier 1: Season Catalog
    # =========================================================================

    def get_event_schedule(self, year: int) -> Optional[pd.DataFrame]:
        """
        Get event schedule for a season.

        Args:
            year: Season year

        Returns:
            DataFrame with EventName, RoundNumber, Location, Country, etc.
            or None if error
        """
        try:
            schedule = fastf1.get_event_schedule(year)
            return schedule
        except Exception as e:
            print(f"✗ Error fetching {year} schedule: {e}")
            return None

    def get_event(self, year: int, round_num: int) -> Optional[pd.Series]:
        """
        Get event info for specific round.

        Args:
            year: Season year
            round_num: Round number

        Returns:
            Series with EventName, Location, Country, etc. or None
        """
        try:
            event = fastf1.get_event(year, round_num)
            return event
        except Exception as e:
            print(f"✗ Error fetching {year} R{round_num} event: {e}")
            return None

    # =========================================================================
    # Tier 2: Weekend Data
    # =========================================================================

    def get_session(self, year: int, round_num: int,
                   session_type: str, load_telemetry: bool = False):
        """
        Get FastF1 session object.

        Args:
            year: Season year
            round_num: Round number
            session_type: "FP1", "FP2", "FP3", "Q", "S", "R"
            load_telemetry: Whether to load telemetry data

        Returns:
            FastF1 Session object or None if error
        """
        try:
            session = fastf1.get_session(year, round_num, session_type)

            # Load data
            load_kwargs = {
                'laps': True,
                'telemetry': load_telemetry,
                'weather': False,
                'messages': False
            }
            session.load(**load_kwargs)

            return session

        except Exception as e:
            print(f"✗ Error fetching {year} R{round_num} {session_type}: {e}")
            return None

    # =========================================================================
    # Tier 3: Session Telemetry & Events
    # =========================================================================

    def get_session_with_all_data(self, year: int, round_num: int,
                                  session_type: str):
        """
        Get session with all data loaded (telemetry, weather, messages).

        Args:
            year: Season year
            round_num: Round number
            session_type: "FP1", "FP2", "FP3", "Q", "S", "R"

        Returns:
            FastF1 Session with all data loaded
        """
        try:
            session = fastf1.get_session(year, round_num, session_type)
            session.load(laps=True, telemetry=True, weather=True, messages=True)
            return session

        except Exception as e:
            print(f"✗ Error loading {year} R{round_num} {session_type}: {e}")
            return None

    # =========================================================================
    # Helpers
    # =========================================================================

    def get_fastest_lap(self, session) -> Optional:
        """Get fastest lap from session."""
        try:
            if session.laps is None or len(session.laps) == 0:
                return None
            return session.laps.pick_fastest()
        except Exception as e:
            print(f"⚠ Error getting fastest lap: {e}")
            return None

    def get_pit_stop_laps(self, session) -> tuple:
        """Get in-laps and out-laps from session."""
        try:
            in_laps = session.laps.pick_box_laps(which='in')
            out_laps = session.laps.pick_box_laps(which='out')
            return in_laps, out_laps
        except Exception as e:
            print(f"⚠ Error getting pit stop laps: {e}")
            return None, None

    def get_drivers_in_session(self, session) -> List[str]:
        """Get list of driver codes in session."""
        try:
            if session.laps is None or len(session.laps) == 0:
                return []
            return sorted(session.laps['Driver'].unique().tolist())
        except Exception as e:
            print(f"⚠ Error getting drivers: {e}")
            return []

    def get_driver_results(self, session) -> Optional[pd.DataFrame]:
        """Get driver results/standings from session."""
        try:
            if session.results is None:
                return None
            return session.results
        except Exception as e:
            print(f"⚠ Error getting results: {e}")
            return None
