"""
Seasons Processor - TIER 1 Processing

Builds seasons catalog as List[EventInfo] from FastF1 API.
"""

from typing import Optional, Dict, List
from f1_replay.models.event import EventInfo, SessionInfo, get_location_dir
from f1_replay.loaders.core.client import FastF1Client


# Type alias for seasons catalog
SeasonsCatalog = Dict[int, List[EventInfo]]


class SeasonsProcessor:
    """Process and build F1 seasons catalog."""

    def __init__(self, fastf1_client: FastF1Client, display_timezone: str = ""):
        """
        Initialize processor.

        Args:
            fastf1_client: FastF1Client instance
            display_timezone: User's preferred timezone for display
        """
        self.fastf1_client = fastf1_client
        self.display_timezone = display_timezone

    def build_seasons(self, years: list) -> Optional[SeasonsCatalog]:
        """
        Build complete seasons catalog.

        Args:
            years: List of years to fetch (e.g., [2023, 2024])

        Returns:
            Dict {year: [EventInfo]} or None if error
        """
        print("→ Building F1 seasons catalog...")

        seasons: SeasonsCatalog = {}

        for year in years:
            try:
                events = self._fetch_year(year)
                if events:
                    seasons[year] = events
                    print(f"  ✓ {year}: {len(events)} rounds")
            except Exception as e:
                print(f"  ⚠ {year}: {e}")

        if not seasons:
            print("  ✗ Could not build any seasons")
            return None

        return seasons

    def _fetch_year(self, year: int) -> Optional[List[EventInfo]]:
        """
        Fetch single season from FastF1.

        Args:
            year: Season year

        Returns:
            List of EventInfo or None
        """
        schedule = self.fastf1_client.get_event_schedule(year)
        if schedule is None:
            return None

        events = []

        for _, row in schedule.iterrows():
            # Skip events without names
            if not row.get('EventName'):
                continue

            event_format = str(row.get('EventFormat', 'conventional'))

            # Get event dates (race date and first session date)
            event_date = str(row.get('EventDate', '')).split(' ')[0]  # Race date

            # Get first session date (usually FP1 on Friday)
            session1_date = row.get('Session1Date')
            event_start = ""
            if session1_date is not None:
                try:
                    event_start = str(session1_date).split(' ')[0][:10]  # YYYY-MM-DD
                except (ValueError, TypeError, AttributeError):
                    pass

            # Extract sessions with full datetime from FastF1 schedule
            sessions = []
            for i in range(1, 6):  # Session1 through Session5
                session_name = row.get(f'Session{i}')
                session_date = row.get(f'Session{i}Date')
                if session_name and str(session_name) not in ('nan', 'None'):
                    # Convert datetime to ISO string
                    date_str = ""
                    if session_date is not None:
                        try:
                            date_str = str(session_date)
                            # Clean up pandas timestamp format if needed
                            if 'T' not in date_str and ' ' in date_str:
                                date_str = date_str.replace(' ', 'T')
                        except (ValueError, TypeError, AttributeError):
                            pass
                    sessions.append(SessionInfo(name=session_name, date=date_str))

            event = EventInfo(
                name=row.get('EventName', ''),
                location=row.get('Location', ''),
                country=row.get('Country', ''),
                circuit_name=row.get('Circuit', '') or row.get('OfficialEventName', ''),
                year=year,
                round_number=int(row.get('RoundNumber', 0)),
                start_date=event_start,
                end_date=event_date,
                sessions=sessions,
                timezone=self.display_timezone,
                event_format=event_format if event_format else 'conventional',
            )
            events.append(event)

        return events if events else None

    def get_event_location_dir(self, event: EventInfo) -> str:
        """
        Get location directory name for event.

        Format: "{round:02d}_{location}"
        Example: "01_Bahrain", "21_Abu_Dhabi"

        Args:
            event: EventInfo

        Returns:
            Directory name string
        """
        return get_location_dir(event)
