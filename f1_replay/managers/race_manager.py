"""
Manager - Top-level coordinator for seasons catalog and race launching.

Provides convenient access to seasons data and methods to load races and launch the Flask viewer.
"""

from typing import Union, Optional, List, Dict, Any
from datetime import datetime
import webbrowser

from f1_replay.managers.dataloader import DataLoader
from f1_replay.models import EventInfo, get_location_dir
from f1_replay.loaders.seasons.processor import SeasonsCatalog
from f1_replay.loaders import TelemetryBuilder
from f1_replay.wrappers import RaceWeekend, Session, create_session
from f1_replay.config import get_cache_dir
from f1_replay.services import TrackFinder


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
        seasons = manager.seasons  # {year: [EventInfo, ...]}
        manager.seasons[2024]  # List of rounds for 2024

        # Load race data
        weekend = manager.load_weekend(2024, 24)
        session = manager.load_race(2024, 24)

        # Launch viewer (direct Flask app)
        manager.race(2024, 24)  # By round number
        manager.race(2024, "abu dhabi")  # By event name
    """

    def __init__(self, cache_dir: Optional[str] = None, timezone: Optional[str] = None):
        """
        Initialize Manager.

        Args:
            cache_dir: Directory for data caching (default: from global config)
            timezone: Timezone for display (e.g., "Europe/Oslo", "America/New_York")
                      Default: None (shows UTC times)
        """
        self.cache_dir = cache_dir or get_cache_dir()
        self.data_loader = DataLoader(self.cache_dir)
        self._seasons: Optional[SeasonsCatalog] = None
        self._weekend: Optional[RaceWeekend] = None
        self._session: Optional[Session] = None
        self._current_event: Optional[EventInfo] = None
        self.timezone = timezone
        self._track_finder = TrackFinder(self.get_season)

    # =========================================================================
    # Season Catalog Methods
    # =========================================================================

    def get_seasons(self, force_update: bool = False) -> Optional[SeasonsCatalog]:
        """
        Load F1 seasons catalog (caches in memory).

        Args:
            force_update: Force rebuild from FastF1

        Returns:
            Dict {year: [EventInfo]} or None
        """
        if self._seasons is None or force_update:
            self._seasons = self.data_loader.load_seasons(force_update=force_update)
        return self._seasons

    def get_season(self, year: int) -> Optional[List[EventInfo]]:
        """
        Get season data for specific year.

        Args:
            year: Season year

        Returns:
            List of EventInfo or None if year not found
        """
        seasons = self.get_seasons()
        if seasons is None:
            return None
        return seasons.get(year)

    def list_years(self) -> List[int]:
        """
        Get list of available years in catalog.

        Returns:
            Sorted list of year integers
        """
        seasons = self.get_seasons()
        if seasons is None:
            return []
        return sorted(seasons.keys())

    @property
    def seasons(self) -> SeasonsCatalog:
        """
        Get dict of available seasons (year -> [EventInfo]).

        Usage:
            manager.seasons[2024]  # Get 2024 events
            manager.seasons[2024][0]  # First EventInfo
            manager.seasons[2024][0].name  # Event name
        """
        seasons = self.get_seasons()
        if seasons is None:
            return {}
        return seasons

    # Map FastF1 session names to short codes for display
    SESSION_SHORT = {
        'Practice 1': 'FP1',
        'Practice 2': 'FP2',
        'Practice 3': 'FP3',
        'Qualifying': 'Q',
        'Race': 'R',
        'Sprint Qualifying': 'SQ',
        'Sprint Shootout': 'SQ',
        'Sprint': 'S',
    }

    def season_schedule(self, year: int, force_update: bool = False) -> None:
        """
        Print a formatted schedule for the season.

        Args:
            year: Season year
            force_update: Force refresh from FastF1
        """
        season = self.get_season(year)
        if season is None:
            if force_update:
                self.get_seasons(force_update=True)
                season = self.get_season(year)
            if season is None:
                print(f"No data for {year}")
                return

        # Calculate max widths for alignment (with GP shortening)
        max_name = max(len(e.name.replace('Grand Prix', 'GP')) for e in season)
        max_loc = max(len(e.circuit_name) for e in season)

        # Header
        print(f"\n  F1 SEASON {year}")
        print(f"  {'═'*(22 + max_name + max_loc + 25)}")

        testing_count = 0
        for event in season:
            date_str = self._format_date_range(event.start_date, event.end_date)
            name = event.name.replace('Grand Prix', 'GP')
            location = event.circuit_name
            sessions = list(event.session_schedule.keys())

            # Convert to short codes
            short_sessions = [self.SESSION_SHORT.get(s, s) for s in sessions]
            sessions_str = ', '.join(short_sessions)

            # Round number (testing events show as T01, T02, etc.)
            round_num = event.round_number
            is_testing = event.format == 'testing'
            if is_testing:
                testing_count += 1
                round_str = f"T{testing_count:02d}"
            else:
                round_str = f"R{round_num:02d}"

            # Aligned columns
            print(f"  {round_str}  {date_str:>11}  {name:<{max_name}}  {location:<{max_loc}}  {sessions_str}")

        print()

    def _format_date_range(self, start_date: str, end_date: str) -> str:
        """Format date range like '26 - 28 Feb' or '28 Feb - 2 Mar'."""
        from datetime import datetime

        # Filter out invalid date strings (NaT, empty, etc.)
        def parse_date(s):
            if not s or 'NaT' in str(s) or len(str(s)) < 10:
                return None
            try:
                return datetime.strptime(str(s)[:10], '%Y-%m-%d')
            except (ValueError, TypeError):
                return None

        start = parse_date(start_date)
        end = parse_date(end_date)

        if start is None and end is None:
            return "TBD"
        if start is None:
            return end.strftime('%d %b')
        if end is None:
            return start.strftime('%d %b')

        # Same month or different months - always use end month
        return f"{start.day:2d} - {end.day:2d} {end.strftime('%b')}"

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

    def _get_event(self, year: int, round_num: int) -> Optional[EventInfo]:
        """Get EventInfo for a specific year and round number."""
        season = self.get_season(year)
        if season is None:
            return None
        for event in season:
            if event.round_number == round_num:
                return event
        return None

    def _resolve_event(self, year: int, round_num_or_name: Union[int, str]) -> Optional[EventInfo]:
        """
        Resolve event, supporting both round number and event name lookup.

        Args:
            year: Season year
            round_num_or_name: Round number (int) or event name (str, case-insensitive)

        Returns:
            EventInfo or None if not found
        """
        # If already a number, look up directly
        if isinstance(round_num_or_name, int):
            return self._get_event(year, round_num_or_name)

        # Look up by event name (case-insensitive)
        season = self.get_season(year)
        if season is None:
            return None

        search_name = round_num_or_name.lower().strip()

        for event in season:
            # Check event name
            if event.name.lower() == search_name:
                return event

            # Check circuit_name (location)
            if event.circuit_name.lower() == search_name:
                return event

            # Check partial match (for convenience)
            if search_name in event.name.lower():
                return event

        print(f"✗ Round '{round_num_or_name}' not found in {year}")
        return None

    def _find_testing_event(self, year: int, testing_num: int = 1) -> Optional[EventInfo]:
        """
        Find testing event by number (T01, T02, etc.).

        Args:
            year: Season year
            testing_num: Testing event number (1 = first testing, 2 = second, etc.)

        Returns:
            EventInfo for the testing event or None if not found
        """
        season = self.get_season(year)
        if season is None:
            return None

        testing_count = 0
        for event in season:
            if event.format == 'testing':
                testing_count += 1
                if testing_count == testing_num:
                    return event

        return None

    # =========================================================================
    # Loading Methods
    # =========================================================================

    @property
    def weekend(self) -> Optional[RaceWeekend]:
        """Get currently loaded weekend."""
        return self._weekend

    @property
    def session(self) -> Optional[Session]:
        """Get currently loaded session."""
        return self._session

    def load_weekend(self, year: int, round_num_or_name: Union[int, str] = None,
                    force_update: bool = False, testing: Union[bool, int, str] = False,
                    sessions: Optional[List[str]] = None) -> 'Manager':
        """
        Load race weekend data (circuit geometry + metadata) into manager.

        If track geometry is placeholder (not yet extracted), efficiently loads
        just the race results and winner's telemetry to extract track/pit lane.

        Access loaded data via manager.weekend property.

        Args:
            year: Season year
            round_num_or_name: Round number or event name (required unless testing=True)
            force_update: Force rebuild from FastF1 (default: False)
            testing: Load pre-season testing instead of race weekend:
                     - True or 1 or "T1" or "T01": First testing event
                     - 2 or "T2" or "T02": Second testing event
                     - etc.
            sessions: List of sessions to load (e.g., ['race', 'qualifying'] or ['R', 'Q'])

        Returns:
            self (for method chaining)
        """
        # Force refresh seasons if force_update (applies to all tiers)
        if force_update:
            self.get_seasons(force_update=True)

        # Handle testing events
        if testing:
            # Parse testing number
            if testing is True:
                testing_num = 1
            elif isinstance(testing, int):
                testing_num = testing
            elif isinstance(testing, str):
                # Parse "T1", "T01", "T2", "T02", etc.
                testing_num = int(testing.upper().lstrip('T').lstrip('0') or '1')
            else:
                testing_num = 1

            event = self._find_testing_event(year, testing_num)
            if event is None:
                print(f"✗ Testing event T{testing_num:02d} not found in {year}")
                self._weekend = None
                self._session = None
                return self
        else:
            if round_num_or_name is None:
                print("✗ Must specify round_num_or_name or testing=True")
                self._weekend = None
                self._session = None
                return self
            event = self._resolve_event(year, round_num_or_name)
            if event is None:
                self._weekend = None
                self._session = None
                return self

        round_num = event.round_number
        self._current_event = event  # Cache for load_session

        weekend_data = self.data_loader.load_weekend(year, round_num, event, force_reprocess=force_update)
        if weekend_data is None:
            self._weekend = None
            self._session = None
            return self

        # Check if track is placeholder (legacy cache file)
        has_real_track = (
            weekend_data.circuit.track.x is not None and
            len(weekend_data.circuit.track.x) > 0
        )

        # Only run legacy extraction if placeholder track (not if force_update with real track)
        # When force_update=True AND we got real track from new flow, don't overwrite it
        if not has_real_track:
            print(f"  ⚠ Legacy cache detected - extracting track...")
            weekend_data = self._extract_track_legacy(weekend_data, event, year, round_num)

        # Create session loader callback for weekend.load_session()
        def session_loader(session_type: str, force: bool = False) -> Optional[Session]:
            return self._load_session_internal(session_type, force)

        self._weekend = RaceWeekend(
            data=weekend_data,
            display_timezone=self.timezone,
            session_loader=session_loader
        )
        self._session = None  # Clear session when new weekend is loaded

        # Load requested sessions
        if sessions:
            for session_type in sessions:
                self._weekend.load_session(session_type, force_update=force_update)

        return self

    def _extract_track_legacy(self, weekend_data, event, year: int, round_num: int):
        """
        Legacy track extraction for old cache files (backward compatibility).

        Extracts track geometry using TelemetryBuilder.extract_track_from_driver
        and updates Weekend.pkl.

        Args:
            weekend_data: F1Weekend with placeholder track
            event: EventInfo
            year: Season year
            round_num: Round number

        Returns:
            Updated F1Weekend with real track geometry
        """
        track_data = None
        historical = None
        is_testing = event.format == 'testing'

        if is_testing:
            # Testing events: always use historical race data for track geometry
            print(f"  → Testing event - searching for historical race at {event.circuit_name}...")
            historical = self._track_finder.find_historical_race(
                event.circuit_name, year,
                circuit=event.circuit_name
            )
        else:
            # Race events: try to get results, fall back to historical
            results = self.data_loader.load_race_results(year, round_num)

            if results:
                print(f"  → Race winner: {results.winner}")
                print(f"  → Extracting track from {results.winner}'s telemetry...")

                # Load session with telemetry for track extraction
                raw_session = self.data_loader.get_raw_session(year, round_num, 'R')
                if raw_session:
                    # Extract track directly using TelemetryBuilder
                    from f1_replay.loaders.session.telemetry import TelemetryBuilder
                    track_data = TelemetryBuilder.extract_track_from_driver(
                        raw_session, results.winner
                    )
            else:
                # Future race - try to get track from historical data
                circuit_name = event.circuit_name
                print(f"  → Future race - searching historical data for {circuit_name}...")
                historical = self._track_finder.find_historical_race(
                    event.circuit_name, year,
                    circuit=event.circuit_name
                )

        # Extract from historical if needed
        historical_rotation = None
        if track_data is None and historical:
            hist_year, hist_round, hist_event = historical
            print(f"  → Using track data from {hist_year} {hist_event.name}")

            # Get results and extract track from historical race
            hist_results = self.data_loader.load_race_results(hist_year, hist_round)
            if hist_results:
                raw_session = self.data_loader.get_raw_session(hist_year, hist_round, 'R')
                if raw_session:
                    from f1_replay.loaders.session.telemetry import TelemetryBuilder
                    track_data = TelemetryBuilder.extract_track_from_driver(
                        raw_session, hist_results.winner
                    )
                    # Get rotation from historical session
                    try:
                        circuit_info = raw_session.get_circuit_info()
                        if circuit_info and hasattr(circuit_info, 'rotation'):
                            historical_rotation = float(circuit_info.rotation)
                    except:
                        pass

        if track_data is None and not is_testing:
            print(f"  ✗ No historical data for '{event.circuit_name}' - new circuit on calendar")

        if track_data:
            from f1_replay.models.event import get_location_dir
            location_dir = get_location_dir(event)

            # Update weekend with track data (DataLoader handles caching)
            weekend_data = self.data_loader.update_weekend_track(
                weekend_data, track_data, location_dir, rotation=historical_rotation
            )

        return weekend_data

    def _load_session_internal(self, session_type: str, force_update: bool = False) -> Optional[Session]:
        """
        Internal method to load a session for the current weekend.

        Used by weekend.load_session() callback.

        Args:
            session_type: Session type code ('R', 'Q', 'FP1', etc.)
            force_update: Force rebuild from FastF1

        Returns:
            Session object or None
        """
        if self._weekend is None:
            return None

        year = self._weekend.year
        round_num = self._weekend.round_number
        event = self._current_event

        # Check if session has occurred
        event_date = event.end_date if event else None
        if event_date:
            try:
                event_dt = datetime.strptime(str(event_date)[:10], '%Y-%m-%d')
                if event_dt > datetime.now():
                    print(f"✗ Session not yet available - {self._weekend.name} is scheduled for {event_date[:10]}")
                    return None
            except (ValueError, TypeError):
                pass

        # Load session data
        result = self.data_loader.load_session(
            year, round_num, session_type,
            event=event,
            circuit_length=self._weekend.circuit_length,
            weekend_track=self._weekend.circuit.track,
            force_reprocess=force_update
        )
        if result is None:
            return None

        return create_session(data=result.data, weekend=self._weekend, raw_session=result.raw_session)

    def load_session(self, year: Optional[int] = None, round_num_or_name: Optional[Union[int, str]] = None,
                    session_type: str = "R", force_update: bool = False) -> 'Manager':
        """
        Load session data (telemetry, events, results) into manager.

        Uses already loaded weekend if available, otherwise loads it first.
        If year/round not specified, uses currently loaded weekend.
        Access loaded data via manager.session and manager.weekend properties.

        Args:
            year: Season year (optional if weekend already loaded)
            round_num_or_name: Round number or event name (optional if weekend already loaded)
            session_type: Session type ("R", "Q", "FP1", "FP2", "FP3", "S") (default: "R")
            force_update: Force rebuild from FastF1 (default: False)

        Returns:
            self (for method chaining)
        """
        # Use current weekend if year/round not specified
        if year is None or round_num_or_name is None:
            if self._weekend is None:
                print("✗ No weekend loaded. Specify year and round.")
                self._session = None
                return self
            year = self._weekend.year
            round_num = self._weekend.round_number
            event = self._current_event
        else:
            event = self._resolve_event(year, round_num_or_name)
            if event is None:
                self._session = None
                return self
            round_num = event.round_number

        # Load weekend if not already loaded for this race
        # (don't reload if already loaded, even with force_update - session force_update is for session only)
        weekend_matches = (
            self._weekend is not None and
            self._weekend.year == year and
            self._weekend.round_number == round_num
        )
        if not weekend_matches:
            self.load_weekend(year, round_num, force_update=force_update)
        if self._weekend is None:
            self._session = None
            return self

        # Check if session has occurred (future races have no data)
        event_date = event.end_date if event else self._current_event.end_date if self._current_event else None
        if event_date:
            try:
                event_dt = datetime.strptime(str(event_date)[:10], '%Y-%m-%d')
                if event_dt > datetime.now():
                    print(f"✗ Session not yet available - {self._weekend.name} is scheduled for {event_date[:10]}")
                    self._session = None
                    return self
            except (ValueError, TypeError):
                pass

        # Load full session data (pass weekend track for track_distance calculation)
        result = self.data_loader.load_session(
            year, round_num, session_type,
            event=event or self._current_event,
            circuit_length=self._weekend.circuit_length,
            weekend_track=self._weekend.circuit.track,
            force_reprocess=force_update
        )
        if result is None:
            self._session = None
            return self

        session = create_session(data=result.data, weekend=self._weekend, raw_session=result.raw_session)
        self._weekend.set_session(session_type, session)
        self._session = session  # Keep shortcut for backward compatibility

        # Print tier 3 session summary
        print(f"\n{'='*60}")
        print(f"TIER 3 SESSION LOADED: {year} R{round_num} {session_type}")
        print(f"{'='*60}")
        print(f"Metadata:")
        print(f"  session_type: {session.session_type}")
        print(f"  event_name: {session.event_name}")
        print(f"  drivers: {session.drivers}")
        print(f"  track_length: {session.track_length}")
        print(f"  total_laps: {session.total_laps}")
        print(f"  t0_utc: {session.t0_utc}")
        print(f"Telemetry: {len(session.telemetry)} drivers")
        for drv, df in list(session.telemetry.items())[:3]:
            print(f"  {drv}: {len(df)} rows, columns={list(df.columns)[:8]}...")
        print(f"Events:")
        print(f"  track_status: {len(session.track_status) if session.track_status is not None else 0} events")
        print(f"  race_control: {len(session.race_control) if session.race_control is not None else 0} events")
        print(f"{'='*60}\n")

        return self

    def load_race(self, year: Optional[int] = None, round_num_or_name: Optional[Union[int, str]] = None,
                 force_update: bool = False) -> 'Manager':
        """
        Load race session (alias for load_session with session_type='R').

        If year/round not specified, uses currently loaded weekend.
        Access loaded data via manager.session and manager.weekend properties.

        Args:
            year: Season year (optional if weekend already loaded)
            round_num_or_name: Round number or event name (optional if weekend already loaded)
            force_update: Force rebuild from FastF1 (default: False)

        Returns:
            self (for method chaining)
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

        total_rounds = len(season)
        print(f"\n📅 Processing {year} season ({total_rounds} rounds)...")
        if force_update:
            print(f"⚠️  Force updating all races from FastF1")

        successful = 0
        failed = 0

        for event in season:
            round_num = event.round_number
            event_name = event.name

            try:
                # Load weekend data
                self.load_weekend(year, round_num, force_update=force_update)
                if self._weekend is None:
                    print(f"  ✗ {round_num:2d}. {event_name}: Failed to load weekend data")
                    failed += 1
                    continue

                # Load race session
                self.load_race(force_update=force_update)
                if self._session is None:
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

    def race(self, year: Optional[int] = None, round_num_or_name: Optional[Union[int, str]] = None,
            host: str = '0.0.0.0', port: int = 5001, debug: bool = True,
            force_update: bool = False) -> None:
        """
        Load race and launch interactive Flask viewer.

        If year/round not specified, uses currently loaded race session.

        Supports both round number and event name:
            manager.race(2024, 24)              # By round number
            manager.race(2024, "abu dhabi")     # By event name
            manager.race(2024, "monaco")        # Partial match
            manager.race(2024, 8, force_update=True)  # Force rebuild from FastF1
            manager.race()                      # Use already loaded session

        Args:
            year: Season year (optional if weekend with race already loaded)
            round_num_or_name: Round number (int) or event name (str)
            host: Host to bind Flask app (default: '0.0.0.0')
            port: Port to run Flask app (default: 5000)
            debug: Enable Flask debug mode (default: True)
            force_update: Force rebuild all data from FastF1 (default: False)
        """
        # Use already loaded race session if no year/round specified
        if year is None and round_num_or_name is None:
            # Check if race session is already loaded
            if self._weekend and self._weekend.is_session_loaded('R'):
                session = self._weekend.race
                print(f"\n✓ Using loaded race: {session.event_name} ({session.year})")
                print(f"\n Starting Flask app on http://{host}:{port}...")

                from f1_replay.api import create_app
                app = create_app(self.data_loader, session, force_update=force_update)

                try:
                    webbrowser.open(f'http://localhost:{port}')
                except Exception:
                    pass

                app.run(host=host, port=port, debug=debug, use_reloader=False)
                return
            else:
                print("No race session loaded. Specify year and round, or load with:")
                print("  manager.load_weekend(year, round, sessions=['race'])")
                return

        print(f"\n Loading race: {year} Round {round_num_or_name}...")

        # Load the race session
        self.load_race(year, round_num_or_name, force_update=force_update)
        if self._session is None:
            print(f"Failed to load race")
            return

        print(f"✓ Loaded: {self._session.event_name} ({self._session.year})")
        print(f"\n Starting Flask app on http://{host}:{port}...")

        # Create Flask app with this session and force_update flag
        from f1_replay.api import create_app
        app = create_app(self.data_loader, self._session, force_update=force_update)

        # Open browser
        try:
            webbrowser.open(f'http://localhost:{port}')
        except Exception:
            pass  # Browser open failed, user can open manually

        # Run Flask (use_reloader=False to work in Jupyter)
        app.run(host=host, port=port, debug=debug, use_reloader=False)

    def view(self, year: int, round_num_or_name: Union[int, str],
            host: str = '0.0.0.0', port: int = 5001, debug: bool = True,
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
        parts = ["Manager("]

        # Show available seasons as dict-like
        years = self.list_years()
        if years:
            years_str = ", ".join(str(y) for y in years)
            parts.append(f"  seasons[{years_str}],")

        # Show loaded weekend
        if self._weekend:
            parts.append(f"  weekend={self._weekend!r}")

        parts.append(")")
        return "\n".join(parts)
