"""
Track Finder - Find historical race data for track geometry extraction.

Used when loading future races or testing events that need track geometry
from a previous race at the same circuit.
"""

from typing import Optional, Tuple, List, Callable
from f1_replay.models import EventInfo


# Location aliases - tracks that have different names across years
# Each group contains equivalent location names (bidirectional matching)
LOCATION_ALIASES = [
    {"yas marina", "yas island"},  # Abu Dhabi
    {"imola", "emilia romagna"},   # Imola
    {"portimao", "algarve"},       # Portugal
]


def normalize_circuit_name(name: str) -> str:
    """Normalize circuit/location name for matching."""
    s = name.lower().strip()
    # Remove common suffixes
    for suffix in [' circuit', ' international', ' street circuit', ' grand prix']:
        if s.endswith(suffix):
            s = s[:-len(suffix)]
    return s


def get_location_aliases(name: str) -> set:
    """Get all aliases for a location name."""
    name_lower = name.lower()
    for alias_group in LOCATION_ALIASES:
        if any(alias in name_lower or name_lower in alias for alias in alias_group):
            return alias_group
    return {name_lower}


def matches_location(search: str, candidate: str) -> bool:
    """Check if search term matches candidate (contains, equal, or alias)."""
    search_norm = normalize_circuit_name(search)
    cand_norm = normalize_circuit_name(candidate)

    # Direct match
    if search_norm == cand_norm or search_norm in cand_norm or cand_norm in search_norm:
        return True

    # Alias match
    search_aliases = get_location_aliases(search_norm)
    cand_aliases = get_location_aliases(cand_norm)
    return bool(search_aliases & cand_aliases)


class TrackFinder:
    """
    Find historical races for track geometry extraction.

    Searches backwards through seasons to find matching circuits.
    Prioritizes circuit name match (same physical track) over location.

    Usage:
        finder = TrackFinder(get_season_func)
        result = finder.find_historical_race("Barcelona", 2025, circuit="Circuit de Catalunya")
        if result:
            year, round_num, event = result
    """

    def __init__(self, get_season: Callable[[int], Optional[List[EventInfo]]]):
        """
        Initialize finder with season lookup function.

        Args:
            get_season: Function that takes year and returns List[EventInfo] or None
        """
        self.get_season = get_season

    def find_historical_race(
        self,
        location: str,
        current_year: int,
        circuit: str = "",
        max_years_back: int = 5
    ) -> Optional[Tuple[int, int, EventInfo]]:
        """
        Find a previous race at the same circuit.

        Searches backwards through seasons to find a matching circuit.
        Prioritizes circuit name match (same physical track) over location.

        Args:
            location: Location to match (e.g., "Barcelona")
            current_year: Year to search backwards from
            circuit: Circuit name to match (e.g., "Circuit de Barcelona-Catalunya")
            max_years_back: Maximum years to search back (default: 5)

        Returns:
            Tuple of (year, round_num, EventInfo) or None if not found
        """
        search_location = location.lower()
        search_circuit = circuit.lower() if circuit else ""

        def is_race_event(event: EventInfo) -> bool:
            """Check if event is a race event (not testing)."""
            return event.round_number > 0 and event.format != 'testing'

        # First pass: circuit name match (most reliable - same physical track)
        if search_circuit:
            for year_offset in range(1, max_years_back + 1):
                prev_year = current_year - year_offset
                season = self.get_season(prev_year)
                if season is None:
                    continue

                for event in season:
                    if not is_race_event(event):
                        continue
                    hist_circuit = event.circuit_name
                    if hist_circuit and matches_location(search_circuit, hist_circuit):
                        return (prev_year, event.round_number, event)

        # Second pass: location match (fallback)
        for year_offset in range(1, max_years_back + 1):
            prev_year = current_year - year_offset
            season = self.get_season(prev_year)
            if season is None:
                continue

            for event in season:
                if not is_race_event(event):
                    continue
                hist_location = event.circuit_name
                if matches_location(search_location, hist_location):
                    return (prev_year, event.round_number, event)

        return None

    def find_any_race_at_circuit(
        self,
        circuit_name: str,
        exclude_year: Optional[int] = None,
        years_range: Tuple[int, int] = (2020, 2025)
    ) -> Optional[Tuple[int, int, EventInfo]]:
        """
        Find any race at a specific circuit within a year range.

        Args:
            circuit_name: Circuit name to match
            exclude_year: Year to skip (e.g., current year)
            years_range: (start_year, end_year) to search

        Returns:
            Tuple of (year, round_num, EventInfo) or None if not found
        """
        for year in range(years_range[1], years_range[0] - 1, -1):
            if year == exclude_year:
                continue

            season = self.get_season(year)
            if season is None:
                continue

            for event in season:
                if event.round_number == 0 or event.format == 'testing':
                    continue
                if event.circuit_name and matches_location(circuit_name, event.circuit_name):
                    return (year, event.round_number, event)

        return None
