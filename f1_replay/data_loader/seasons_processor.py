"""
Seasons Processor - TIER 1 Processing

Builds F1Seasons catalog from FastF1 API.
"""

from typing import Optional
from datetime import datetime
from f1_replay.data_loader.data_models import F1Seasons, F1Year, RoundInfo
from f1_replay.data_loader.fastf1_client import FastF1Client


class SeasonsProcessor:
    """Process and build F1 seasons catalog."""

    def __init__(self, fastf1_client: FastF1Client):
        """
        Initialize processor.

        Args:
            fastf1_client: FastF1Client instance
        """
        self.fastf1_client = fastf1_client

    def build_seasons(self, years: list) -> Optional[F1Seasons]:
        """
        Build complete seasons catalog.

        Args:
            years: List of years to fetch (e.g., [2023, 2024])

        Returns:
            F1Seasons object or None if error
        """
        print("→ Building F1 seasons catalog...")

        seasons_dict = {}

        for year in years:
            try:
                f1_year = self._fetch_year(year)
                if f1_year:
                    seasons_dict[year] = f1_year
                    print(f"  ✓ {year}: {f1_year.total_rounds} rounds")
            except Exception as e:
                print(f"  ⚠ {year}: {e}")

        if not seasons_dict:
            print("  ✗ Could not build any seasons")
            return None

        catalog = F1Seasons(
            years=seasons_dict,
            last_updated=datetime.now().isoformat()
        )

        return catalog

    def _fetch_year(self, year: int) -> Optional[F1Year]:
        """
        Fetch single season from FastF1.

        Args:
            year: Season year

        Returns:
            F1Year object or None
        """
        schedule = self.fastf1_client.get_event_schedule(year)
        if schedule is None:
            return None

        rounds = []

        for _, row in schedule.iterrows():
            # Skip test events (no EventName)
            if not row.get('EventName'):
                continue

            round_info = RoundInfo(
                round_number=int(row.get('RoundNumber', 0)),
                event_name=row.get('EventName', ''),
                location=row.get('Location', ''),
                country=row.get('Country', ''),
                circuit_name=row.get('Circuit', ''),
                date=str(row.get('EventDate', '')).split(' ')[0],  # YYYY-MM-DD
                available_sessions=['FP1', 'FP2', 'FP3', 'Q', 'R']  # TODO: check actual
            )
            rounds.append(round_info)

        if not rounds:
            return None

        return F1Year(
            year=year,
            total_rounds=len(rounds),
            rounds=rounds
        )

    def get_round_location_name(self, round_info: RoundInfo) -> str:
        """
        Get location directory name for round.

        Format: "{round_number:02d}_{location}"
        Example: "01_Bahrain", "21_Abu Dhabi"

        Args:
            round_info: RoundInfo object

        Returns:
            Directory name string
        """
        # Sanitize location name (remove special chars)
        location_safe = round_info.location.replace(' ', '_').replace('-', '_')
        return f"{round_info.round_number:02d}_{location_safe}"
