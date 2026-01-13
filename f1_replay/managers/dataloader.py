"""
Main DataLoader - Orchestrates 3-tier data loading and caching

Tier 1: Seasons (seasons.pkl) - Dict[int, List[EventInfo]]
Tier 2: F1Weekend (year/round_location/Weekend.pkl)
Tier 3: SessionData (year/round_location/SessionType.pkl)
"""

import pickle
from pathlib import Path
from typing import Optional

from f1_replay.models import (
    F1Weekend, LoadResult, CircuitData, TrackGeometry, PitLane, RaceResults, DirectionArrow, EventInfo
)
from f1_replay.loaders.seasons.processor import SeasonsCatalog
from f1_replay.loaders.core.client import FastF1Client
from f1_replay.loaders.core.mapping import to_fastf1_code, to_user_friendly
from f1_replay.loaders.seasons.processor import SeasonsProcessor
from f1_replay.loaders.weekend.processor import WeekendProcessor, get_manual_rotation
from f1_replay.loaders.session.processor import SessionProcessor


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

        # Memory cache to avoid repeated disk reads
        self._seasons_cache: Optional[SeasonsCatalog] = None

        print(f"✓ DataLoader initialized: {self.cache_dir}")

    # =========================================================================
    # TIER 1: Seasons Catalog
    # =========================================================================

    def load_seasons(self, years: list = None, force_update: bool = False) -> Optional[SeasonsCatalog]:
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
                with open(seasons_path, 'rb') as f:
                    seasons = pickle.load(f)

                # Check if current year is missing from cache
                if current_year not in seasons:
                    print(f"⚠ Cache missing {current_year}, fetching...")
                    new_rounds = self.seasons_processor._fetch_year(current_year)
                    if new_rounds:
                        seasons[current_year] = new_rounds
                        # Update disk cache
                        with open(seasons_path, 'wb') as f:
                            pickle.dump(seasons, f, protocol=pickle.HIGHEST_PROTOCOL)
                        print(f"✓ Added {current_year} to cache ({len(new_rounds)} rounds)")

                print(f"✓ Loaded seasons from cache: {sorted(seasons.keys())}")
                self._seasons_cache = seasons  # Store in memory
                return seasons
            except Exception as e:
                print(f"⚠ Could not load cached seasons: {e}")

        # Build from FastF1
        print(f"\n📡 Building seasons catalog from FastF1...")
        seasons = self.seasons_processor.build_seasons(years)

        if seasons is None:
            return None

        # Cache to disk
        try:
            with open(seasons_path, 'wb') as f:
                pickle.dump(seasons, f, protocol=pickle.HIGHEST_PROTOCOL)
            print(f"✓ Cached seasons to {seasons_path}\n")
        except Exception as e:
            print(f"⚠ Could not cache seasons: {e}")

        self._seasons_cache = seasons  # Store in memory
        return seasons


    # =========================================================================
    # TIER 2: Race Weekend
    # =========================================================================

    def load_weekend(self, year: int, round_num: int, event: EventInfo,
                    force_reprocess: bool = False, force_update: bool = False) -> Optional[F1Weekend]:
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
                with open(weekend_path, 'rb') as f:
                    weekend = pickle.load(f)
                print(f"✓ Loaded weekend from cache: {event.name}")
                return weekend
            except Exception as e:
                print(f"⚠ Could not load cached weekend: {e}")

        # Build from FastF1
        print(f"\n📡 Building weekend data from FastF1...")

        # For testing events (round=0), use dedicated testing API
        is_testing = event.format == 'testing'
        if is_testing:
            # Extract test number from event (stored by Manager)
            test_number = getattr(event, 'test_number', 1)
            weekend = self.weekend_processor.build_weekend(year, round_num, test_number=test_number)
        else:
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
                    event: EventInfo, circuit_length: float, weekend_track=None,
                    force_reprocess: bool = False, force_update: bool = False) -> Optional[LoadResult]:
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
            print(f"✗ {e}")
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
                with open(session_path, 'rb') as f:
                    session = pickle.load(f)
                print(f"✓ Loaded session from cache: {session_type}")
                return LoadResult(data=session, raw_session=None)
            except Exception as e:
                print(f"⚠ Could not load cached session: {e}")

        # Build from FastF1
        print(f"\n📡 Building session data from FastF1...")

        # Create processor with circuit length and weekend track
        processor = SessionProcessor(
            self.fastf1_client,
            circuit_length=circuit_length,
            weekend_track=weekend_track
        )

        result = processor.build_session(year, round_num, fastf1_code, event.name)

        if result is None:
            return None

        # Note: _track_data is None in new flow (track extracted during weekend build, not session)
        session, raw_session, _track_data = result

        # Cache (only SessionData, not raw_session)
        try:
            with open(session_path, 'wb') as f:
                pickle.dump(session, f, protocol=pickle.HIGHEST_PROTOCOL)
            print(f"✓ Cached session to {session_path}\n")
        except Exception as e:
            print(f"⚠ Could not cache session: {e}")

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
        f1_session = self.fastf1_client.get_session(year, round_num, 'R', load_telemetry=False)
        if f1_session is None:
            return None

        try:
            results = f1_session.results
            if results is None or len(results) == 0:
                return None

            # Get winner (P1)
            winner_row = results[results['Position'] == 1]
            if len(winner_row) == 0:
                return None

            winner = winner_row['Abbreviation'].iloc[0]
            return RaceResults(winner=winner, raw_session=f1_session)
        except Exception as e:
            print(f"  ⚠ Could not load race results: {e}")
            return None

    def get_raw_session(self, year: int, round_num: int, session_type: str = 'R'):
        """
        Get raw FastF1 session with telemetry loaded.

        This is a pass-through to fastf1_client for Manager orchestration.
        """
        return self.fastf1_client.get_session_with_all_data(year, round_num, session_type)

    # =========================================================================
    # Helpers
    # =========================================================================

    def update_weekend_track(self, weekend: F1Weekend, track_data, location_dir: str,
                             rotation: Optional[float] = None) -> F1Weekend:
        """
        Update weekend's CircuitData with extracted track geometry.

        LEGACY: Only used for backward compatibility when Weekend.pkl has placeholder track.
        New flow builds complete track during WeekendProcessor.build_weekend().

        Args:
            weekend: Current F1Weekend
            track_data: TrackData from TelemetryBuilder
            location_dir: Directory name for caching
            rotation: Optional rotation override (used when pulling from historical data)

        Returns:
            Updated F1Weekend with track geometry
        """
        from f1_replay.models import MarshalSector
        import numpy as np

        # Convert distances from decimeters to meters
        circuit_length_meters = track_data.lap_distance / 10.0
        distance_meters = track_data.track_distance / 10.0 if track_data.track_distance is not None else None

        # Convert marshal sector tuples to MarshalSector objects
        marshal_sectors = []
        if track_data.marshal_sectors:
            for sector_num, from_dist, to_dist in track_data.marshal_sectors:
                marshal_sectors.append(MarshalSector(
                    number=sector_num,
                    start_distance=from_dist,
                    end_distance=to_dist
                ))

        # Build TrackGeometry from track_data (with meters)
        track = TrackGeometry(
            x=track_data.track_x,
            y=track_data.track_y,
            distance=distance_meters.astype(np.float32) if distance_meters is not None else None,
            lap_distance=circuit_length_meters,
            marshal_sectors=marshal_sectors,
            speed=track_data.speed,
            throttle=track_data.throttle,
            brake=track_data.brake,
            z=track_data.track_z
        )

        # Build pit lane with entry/exit distances
        pit_lane = None
        if track_data.pit_x is not None and len(track_data.pit_x) > 0:
            pit_lane = PitLane(
                x=track_data.pit_x,
                y=track_data.pit_y,
                distance=track_data.pit_distance,
                length=track_data.pit_length,
                entry_track_dist=track_data.pit_entry_distance or 0.0,
                exit_track_dist=track_data.pit_exit_distance or 0.0
            )

        # Calculate direction arrow at start/finish (opposite side of pitlane)
        direction_arrow = None
        if track_data.track_x is not None and len(track_data.track_x) > 1:
            # Track direction at start/finish (from point 0 to point 1)
            dx = track_data.track_x[1] - track_data.track_x[0]
            dy = track_data.track_y[1] - track_data.track_y[0]
            length = np.sqrt(dx*dx + dy*dy)
            if length > 0:
                # Unit vector in racing direction
                dir_x, dir_y = dx / length, dy / length
                # Perpendicular (both sides)
                perp_x, perp_y = -dir_y, dir_x  # Left side

                # Determine which side is opposite the pitlane
                arrow_offset = 200  # Distance from track centerline (decimeters)
                left_x = track_data.track_x[0] + perp_x * arrow_offset
                left_y = track_data.track_y[0] + perp_y * arrow_offset
                right_x = track_data.track_x[0] - perp_x * arrow_offset
                right_y = track_data.track_y[0] - perp_y * arrow_offset

                # Check distance to pit lane to pick opposite side
                # Use nearest pit point to start/finish (not center, which can be misleading)
                if pit_lane is not None and track_data.pit_x is not None and len(track_data.pit_x) > 0:
                    # Find pit point nearest to start/finish line
                    start_x, start_y = track_data.track_x[0], track_data.track_y[0]
                    pit_dists = (track_data.pit_x - start_x)**2 + (track_data.pit_y - start_y)**2
                    nearest_idx = np.argmin(pit_dists)
                    pit_near_x = track_data.pit_x[nearest_idx]
                    pit_near_y = track_data.pit_y[nearest_idx]

                    dist_left = (left_x - pit_near_x)**2 + (left_y - pit_near_y)**2
                    dist_right = (right_x - pit_near_x)**2 + (right_y - pit_near_y)**2
                    # Pick side farther from pit (opposite side)
                    if dist_left > dist_right:
                        arrow_x, arrow_y = left_x, left_y
                    else:
                        arrow_x, arrow_y = right_x, right_y
                else:
                    # No pit lane, default to left side
                    arrow_x, arrow_y = left_x, left_y

                direction_arrow = DirectionArrow(
                    x=float(arrow_x), y=float(arrow_y),
                    dx=float(dir_x), dy=float(dir_y)
                )

        # Create updated CircuitData
        # Priority: manual override > weekend's rotation > historical rotation
        manual_rot = get_manual_rotation(weekend.circuit.name)
        if manual_rot is not None:
            final_rotation = manual_rot
        elif weekend.circuit.rotation != 0:
            final_rotation = weekend.circuit.rotation
        else:
            final_rotation = rotation if rotation is not None else 0.0
        new_circuit = CircuitData(
            track=track,
            pit_lane=pit_lane,
            circuit_length=circuit_length_meters,
            corners=weekend.circuit.corners,
            rotation=final_rotation,
            name=weekend.circuit.name,
            direction_arrow=direction_arrow,
            metadata=weekend.circuit.metadata
        )

        # Create updated weekend
        updated_weekend = F1Weekend(
            event=weekend.event,
            circuit=new_circuit
        )

        # Re-cache weekend with track data
        weekend_path = self.cache_dir / str(weekend.year) / location_dir / "Weekend.pkl"
        try:
            with open(weekend_path, 'wb') as f:
                pickle.dump(updated_weekend, f, protocol=pickle.HIGHEST_PROTOCOL)
            sectors_info = f", {len(marshal_sectors)} sectors" if marshal_sectors else ""
            pit_info = f", pit={pit_lane.length:.0f}m" if pit_lane else ""
            print(f"  ✓ Updated weekend with track geometry ({circuit_length_meters:.0f}m{sectors_info}{pit_info})")
        except Exception as e:
            print(f"  ⚠ Could not update weekend cache: {e}")

        return updated_weekend

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
            event = self.get_event(year, round_num)
            if event:
                location_dir = self.seasons_processor.get_event_location_dir(event)
                round_dir = self.cache_dir / str(year) / location_dir
                if round_dir.exists():
                    import shutil
                    shutil.rmtree(round_dir)
                    print(f"✓ Cleared cache for {year} R{round_num}")
