"""
Manager - Top-level coordinator for seasons catalog and race launching.

Provides convenient access to seasons data and methods to load races and launch the Flask viewer.
"""

from typing import Union, Optional, List, Dict, Any
from datetime import datetime
import webbrowser

from f1_replay.data_loader import DataLoader, F1Seasons, F1Year
from f1_replay.race_weekend import RaceWeekend
from f1_replay.session import Session
from f1_replay.config import get_cache_dir


class ScheduleList(list):
    """
    List of schedule items with pretty printing support.

    Each item is a dict with: title, start, end, session_type, round, location
    """

    def __init__(self, items: List[Dict[str, Any]], schedule_type: str = "Schedule"):
        super().__init__(items)
        self.schedule_type = schedule_type

    def __getitem__(self, key):
        result = super().__getitem__(key)
        if isinstance(key, slice):
            return ScheduleList(result, self.schedule_type)
        return result

    def __repr__(self) -> str:
        return self._format_table()

    def __str__(self) -> str:
        return self._format_table()

    def _format_table(self) -> str:
        if not self:
            return f"\n  No {self.schedule_type.lower()} events found.\n"

        # Build formatted output
        lines = [f"\n  {self.schedule_type}", "  " + "=" * 70]

        for item in self:
            # Parse start time
            start = item.get('start')
            if isinstance(start, str):
                try:
                    start = datetime.fromisoformat(start.replace('Z', '+00:00'))
                except:
                    pass

            # Format date/time
            if isinstance(start, datetime):
                date_str = start.strftime("%a %d %b")
                time_str = start.strftime("%H:%M")
            else:
                date_str = str(start)[:10] if start else "TBD"
                time_str = ""

            title = item.get('title', 'Unknown')
            location = item.get('location', '')
            round_num = item.get('round', '')

            # Format: "  R01  Sun 16 Mar  15:00  Bahrain Grand Prix (Sakhir)"
            round_str = f"R{round_num:02d}" if isinstance(round_num, int) else str(round_num)
            loc_str = f"({location})" if location else ""

            lines.append(f"  {round_str}  {date_str}  {time_str:>5}  {title} {loc_str}")

        lines.append("")
        return "\n".join(lines)


class Manager:
    """
    Top-level coordinator for F1 data and race viewer.

    Manages seasons catalog, loads race/session data, and launches Flask viewer app.

    Usage:
        manager = Manager()  # Uses global config

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

    def __init__(self, cache_dir: Optional[str] = None):
        """
        Initialize Manager.

        Args:
            cache_dir: Directory for data caching (default: from global config)
        """
        self.cache_dir = cache_dir or get_cache_dir()
        self.data_loader = DataLoader(self.cache_dir)
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

    # =========================================================================
    # Schedule Methods
    # =========================================================================

    def _get_event_schedule(self, year: int):
        """Get FastF1 event schedule for a year."""
        import fastf1
        return fastf1.get_event_schedule(year)

    def _build_schedule_item(self, event, session_num: int, round_num: int) -> Optional[Dict[str, Any]]:
        """Build a schedule item dict from event row and session number."""
        session_name = event.get(f'Session{session_num}')
        session_date = event.get(f'Session{session_num}Date')

        if not session_name or session_date is None:
            return None

        # Get end time (estimate 2 hours for races, 1 hour for others)
        duration_hours = 2 if session_name in ['Race', 'Sprint'] else 1
        try:
            end_time = session_date + __import__('datetime').timedelta(hours=duration_hours)
        except:
            end_time = None

        return {
            'title': f"{event.get('EventName', '')} - {session_name}",
            'start': session_date.isoformat() if hasattr(session_date, 'isoformat') else str(session_date),
            'end': end_time.isoformat() if end_time and hasattr(end_time, 'isoformat') else None,
            'session_type': session_name,
            'round': round_num,
            'location': event.get('Location', ''),
            'country': event.get('Country', ''),
            'event_name': event.get('EventName', '')
        }

    def weekend_schedule(self, year: int) -> ScheduleList:
        """
        Get all race weekends for a season (excludes testing events).

        Args:
            year: Season year

        Returns:
            ScheduleList with weekend events (title, start, end for each weekend)
        """
        schedule = self._get_event_schedule(year)
        if schedule is None:
            return ScheduleList([], f"{year} Race Weekends")

        items = []
        for _, event in schedule.iterrows():
            round_num = event.get('RoundNumber', 0)
            event_name = event.get('EventName', '')

            # Skip testing/non-race events
            if round_num == 0 or 'Test' in event_name:
                continue

            event_date = event.get('EventDate')
            # Weekend spans from first session to race
            session1_date = event.get('Session1Date')
            session5_date = event.get('Session5Date')

            items.append({
                'title': event_name,
                'start': (session1_date.isoformat() if hasattr(session1_date, 'isoformat')
                         else str(event_date)[:10] if event_date else None),
                'end': (session5_date.isoformat() if hasattr(session5_date, 'isoformat')
                       else str(event_date)[:10] if event_date else None),
                'round': round_num,
                'location': event.get('Location', ''),
                'country': event.get('Country', '')
            })

        return ScheduleList(items, f"{year} Race Weekends")

    def race_schedule(self, year: int) -> ScheduleList:
        """
        Get race session schedule for a season.

        Args:
            year: Season year

        Returns:
            ScheduleList with race events
        """
        schedule = self._get_event_schedule(year)
        if schedule is None:
            return ScheduleList([], f"{year} Races")

        items = []
        for _, event in schedule.iterrows():
            round_num = event.get('RoundNumber', 0)
            if round_num == 0:
                continue

            # Find Race session (usually Session5, but check by name)
            for i in range(1, 6):
                if event.get(f'Session{i}') == 'Race':
                    item = self._build_schedule_item(event, i, round_num)
                    if item:
                        item['title'] = event.get('EventName', '')  # Cleaner title
                        items.append(item)
                    break

        return ScheduleList(items, f"{year} Races")

    def sprint_schedule(self, year: int) -> ScheduleList:
        """
        Get sprint race schedule for a season.

        Args:
            year: Season year

        Returns:
            ScheduleList with sprint race events
        """
        schedule = self._get_event_schedule(year)
        if schedule is None:
            return ScheduleList([], f"{year} Sprint Races")

        items = []
        for _, event in schedule.iterrows():
            round_num = event.get('RoundNumber', 0)
            if round_num == 0:
                continue

            # Find Sprint session
            for i in range(1, 6):
                if event.get(f'Session{i}') == 'Sprint':
                    item = self._build_schedule_item(event, i, round_num)
                    if item:
                        item['title'] = event.get('EventName', '')
                        items.append(item)
                    break

        return ScheduleList(items, f"{year} Sprint Races")

    def qualification_schedule(self, year: int) -> ScheduleList:
        """
        Get qualifying session schedule for a season.

        Args:
            year: Season year

        Returns:
            ScheduleList with qualifying events
        """
        schedule = self._get_event_schedule(year)
        if schedule is None:
            return ScheduleList([], f"{year} Qualifying")

        items = []
        for _, event in schedule.iterrows():
            round_num = event.get('RoundNumber', 0)
            if round_num == 0:
                continue

            # Find Qualifying session
            for i in range(1, 6):
                if event.get(f'Session{i}') == 'Qualifying':
                    item = self._build_schedule_item(event, i, round_num)
                    if item:
                        item['title'] = event.get('EventName', '')
                        items.append(item)
                    break

        return ScheduleList(items, f"{year} Qualifying")

    def sprintquali_schedule(self, year: int) -> ScheduleList:
        """
        Get sprint qualifying (shootout) schedule for a season.

        Args:
            year: Season year

        Returns:
            ScheduleList with sprint qualifying events
        """
        schedule = self._get_event_schedule(year)
        if schedule is None:
            return ScheduleList([], f"{year} Sprint Qualifying")

        items = []
        for _, event in schedule.iterrows():
            round_num = event.get('RoundNumber', 0)
            if round_num == 0:
                continue

            # Find Sprint Qualifying/Shootout session
            for i in range(1, 6):
                session_name = event.get(f'Session{i}')
                if session_name in ['Sprint Qualifying', 'Sprint Shootout']:
                    item = self._build_schedule_item(event, i, round_num)
                    if item:
                        item['title'] = event.get('EventName', '')
                        items.append(item)
                    break

        return ScheduleList(items, f"{year} Sprint Qualifying")

    def practice_schedule(self, year: int) -> ScheduleList:
        """
        Get practice and testing session schedule for a season.

        Args:
            year: Season year

        Returns:
            ScheduleList with practice/testing events
        """
        schedule = self._get_event_schedule(year)
        if schedule is None:
            return ScheduleList([], f"{year} Practice Sessions")

        items = []
        practice_sessions = ['Practice 1', 'Practice 2', 'Practice 3', 'FP1', 'FP2', 'FP3']

        for _, event in schedule.iterrows():
            round_num = event.get('RoundNumber', 0)
            event_name = event.get('EventName', '')

            # Include testing events (round 0) and practice sessions
            for i in range(1, 6):
                session_name = event.get(f'Session{i}')
                if session_name and (session_name in practice_sessions or
                                    'Practice' in str(session_name) or
                                    'Test' in str(session_name) or
                                    round_num == 0):  # Testing events
                    item = self._build_schedule_item(event, i, round_num if round_num else 0)
                    if item:
                        if round_num == 0:
                            item['title'] = f"{event_name} - {session_name}"
                        else:
                            item['title'] = f"{event_name} - {session_name}"
                        items.append(item)

        return ScheduleList(items, f"{year} Practice & Testing")

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
