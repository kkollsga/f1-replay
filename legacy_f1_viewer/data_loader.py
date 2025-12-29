"""
DataLoader - Centralized FastF1 data loading, processing, and caching.

This is the ONLY module that imports fastf1. All data access flows through here.

Architecture:
- RaceDataLoader: Handles FastF1 API calls and data processing
- SessionDataset: Immutable, cached session data (telemetry, track, weather, etc.)
- RaceWeekendData: Immutable weekend metadata
- F1Catalog: Immutable catalog of all F1 seasons
- DataLoader: Facade for backward compatibility
"""

from pathlib import Path
from typing import Optional, Dict, Any, List, TypeVar, Type
from dataclasses import dataclass, field
import pickle
import json
from datetime import datetime

import fastf1
import polars as pl
import pandas as pd
import numpy as np

T = TypeVar('T')

# ============================================================================
# Tier 1: F1Catalog (All Seasons)
# ============================================================================

@dataclass
class RaceInfo:
    """Information about a single race weekend."""
    round_number: int
    event_name: str
    location: str
    country: str
    date: str
    circuit_name: str


@dataclass
class SeasonInfo:
    """Information about an entire season."""
    year: int
    races: List[RaceInfo]
    total_rounds: int


@dataclass(frozen=True)
class F1Catalog:
    """
    Complete catalog of all F1 seasons.

    Immutable, cached in memory and on disk.
    Updated incrementally as new seasons are accessed.
    """
    seasons: Dict[int, SeasonInfo] = field(default_factory=dict)
    last_updated: str = field(default_factory=lambda: datetime.now().isoformat())


# ============================================================================
# Tier 2: RaceWeekendData (Race Weekend Metadata)
# ============================================================================

@dataclass(frozen=True)
class RaceWeekendData:
    """
    Metadata for a single race weekend.

    Contains circuit info, location, and session schedule.
    Immutable, cached to disk once per weekend.
    """
    year: int
    round_number: int
    event_name: str
    circuit_name: str
    location: str
    country: str
    timezone: str
    event_date: str
    session_schedule: Dict[str, str]  # {FP1: time, FP2: time, Q: time, R: time}
    available_sessions: List[str]  # ['FP1', 'FP2', 'Q', 'R', etc.]


# ============================================================================
# Tier 3: SessionDataset (Complete Session Data)
# ============================================================================

@dataclass(frozen=True)
class SessionDataset:
    """
    Complete immutable dataset for a single session (race, qualifying, practice).

    Contains all telemetry, track data, weather, race control messages, etc.
    Optimized data structures:
    - Telemetry: Polars DataFrames (2-5x less memory than Pandas, faster queries)
    - Track geometry: NumPy arrays (compact, fast indexing)
    - Metadata: Python dicts (simple, readable)
    - Events: List[Dict] (lightweight)
    """
    version: str = "1.0.0"
    session_type: str = ""  # 'R', 'Q', 'FP1', etc.
    metadata: Dict[str, Any] = field(default_factory=dict)
    telemetry: Dict[str, pl.DataFrame] = field(default_factory=dict)
    track: Dict[str, np.ndarray] = field(default_factory=dict)
    pit_lane: Optional[Dict[str, np.ndarray]] = None
    position_history: List[Dict] = field(default_factory=list)
    intervals: List[Dict] = field(default_factory=list)
    track_status: List[Dict] = field(default_factory=list)
    race_control: List[Dict] = field(default_factory=list)
    weather: List[Dict] = field(default_factory=list)
    fastest_laps: List[Dict] = field(default_factory=list)


# ============================================================================
# Main Loader: RaceDataLoader
# ============================================================================

class RaceDataLoader:
    """
    Handles all FastF1 API access and data processing.

    This is the ONLY class that imports and uses fastf1.
    Creates immutable dataset objects that are cached to disk.
    """

    def __init__(self, cache_dir: str = "race_data"):
        """Initialize loader with cache directory."""
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        # Setup FastF1 cache at project root
        fastf1_cache = Path.cwd() / ".fastf1_cache"
        fastf1_cache.mkdir(parents=True, exist_ok=True)
        fastf1.Cache.enable_cache(str(fastf1_cache))

    # =========================================================================
    # Tier 1: Catalog Operations
    # =========================================================================

    def load_catalog(self, force_update: bool = False) -> F1Catalog:
        """
        Load or create F1 catalog containing all seasons.

        Cached to disk as single file. Updated incrementally when new seasons
        are accessed.
        """
        catalog_path = self.cache_dir / "catalog.pkl"

        # Try to load from cache
        if catalog_path.exists() and not force_update:
            try:
                with open(catalog_path, 'rb') as f:
                    return pickle.load(f)
            except Exception as e:
                print(f"  ⚠ Could not load catalog from cache: {e}")

        # Create new catalog from FastF1
        print("→ Building F1 catalog from FastF1...")
        seasons = {}

        # Fetch recent years (can be extended)
        for year in range(2023, datetime.now().year + 1):
            try:
                season_info = self._fetch_season_from_fastf1(year)
                if season_info:
                    seasons[year] = season_info
                    print(f"  ✓ {year}: {len(season_info.races)} races")
            except Exception as e:
                print(f"  ⚠ Could not fetch {year}: {e}")

        catalog = F1Catalog(seasons=seasons)

        # Save to cache
        try:
            with open(catalog_path, 'wb') as f:
                pickle.dump(catalog, f, protocol=pickle.HIGHEST_PROTOCOL)
            print(f"  ✓ Catalog cached to {catalog_path}")
        except Exception as e:
            print(f"  ⚠ Could not cache catalog: {e}")

        return catalog

    def _fetch_season_from_fastf1(self, year: int) -> Optional[SeasonInfo]:
        """Fetch season schedule from FastF1."""
        try:
            schedule = fastf1.get_event_schedule(year)

            races = []
            for _, row in schedule.iterrows():
                if row.get('EventName'):  # Skip test events
                    race = RaceInfo(
                        round_number=int(row.get('RoundNumber', 0)),
                        event_name=row.get('EventName', ''),
                        location=row.get('Location', ''),
                        country=row.get('Country', ''),
                        date=str(row.get('EventDate', '')),
                        circuit_name=row.get('Circuit', ''),
                    )
                    races.append(race)

            return SeasonInfo(
                year=year,
                races=races,
                total_rounds=len(races)
            )
        except Exception as e:
            print(f"  ⚠ Error fetching {year}: {e}")
            return None

    # =========================================================================
    # Tier 2: Weekend Operations
    # =========================================================================

    def load_weekend(self, year: int, round_num: int,
                     force_reprocess: bool = False) -> RaceWeekendData:
        """Load race weekend metadata."""
        weekend_dir = self.cache_dir / "weekends" / str(year)
        weekend_dir.mkdir(parents=True, exist_ok=True)

        # Try cache first
        if not force_reprocess:
            cached = self._load_from_cache(weekend_dir / "weekend_data.pkl", RaceWeekendData)
            if cached:
                return cached

        # Fetch from FastF1
        weekend_data = self._fetch_weekend_from_fastf1(year, round_num)

        # Save to cache
        try:
            self._save_to_cache(weekend_data, weekend_dir / "weekend_data.pkl")
        except Exception as e:
            print(f"  ⚠ Could not cache weekend data: {e}")

        return weekend_data

    def _fetch_weekend_from_fastf1(self, year: int, round_num: int) -> RaceWeekendData:
        """Fetch weekend metadata from FastF1."""
        event = fastf1.get_event(year, round_num)

        # Get session times if available
        session_schedule = {}
        available_sessions = []

        for session_type in ['FP1', 'FP2', 'FP3', 'Q', 'S', 'R']:  # S = Sprint
            try:
                session = fastf1.get_session(year, round_num, session_type)
                if session and hasattr(session, 'date'):
                    session_schedule[session_type] = str(session.date)
                    available_sessions.append(session_type)
            except Exception:
                pass

        return RaceWeekendData(
            year=year,
            round_number=event.get('RoundNumber', round_num),
            event_name=event.get('EventName', ''),
            circuit_name=event.get('Circuit', ''),
            location=event.get('Location', ''),
            country=event.get('Country', ''),
            timezone=event.get('TimeZone', 'UTC'),
            event_date=str(event.get('EventDate', '')),
            session_schedule=session_schedule,
            available_sessions=available_sessions,
        )

    # =========================================================================
    # Tier 3: Session Operations (Heavy Processing)
    # =========================================================================

    def load_session(self, year: int, round_num: int, session_id: str,
                     force_reprocess: bool = False) -> SessionDataset:
        """
        Load or process a race session.

        This is the heavy lifting - fetches from FastF1, processes telemetry,
        converts to Polars, and caches to disk.
        """
        session_dir = (self.cache_dir / "weekends" / str(year) /
                      f"{round_num:02d}_event" / "sessions")
        session_dir.mkdir(parents=True, exist_ok=True)

        session_file = session_dir / f"{session_id.lower()}.pkl"

        # Try cache first
        if session_file.exists() and not force_reprocess:
            try:
                with open(session_file, 'rb') as f:
                    return pickle.load(f)
            except Exception as e:
                print(f"  ⚠ Could not load cached session: {e}")

        # Fetch and process
        print(f"→ Processing {year} Round {round_num} {session_id}...")
        dataset = self._fetch_and_process_session(year, round_num, session_id)

        # Save to cache
        try:
            with open(session_file, 'wb') as f:
                pickle.dump(dataset, f, protocol=pickle.HIGHEST_PROTOCOL)
            print(f"  ✓ Cached to {session_file}")
        except Exception as e:
            print(f"  ⚠ Could not cache session: {e}")

        return dataset

    def _fetch_and_process_session(self, year: int, round_num: int,
                                   session_id: str) -> SessionDataset:
        """
        Fetch session from FastF1 and process into SessionDataset.

        This is where Polars conversion happens.
        """
        # Get FastF1 session
        try:
            f1_session = fastf1.get_session(year, round_num, session_id)
            f1_session.load(laps=True, telemetry=True, weather=True, messages=True)
        except Exception as e:
            print(f"  ✗ Could not load session: {e}")
            raise

        # Extract and process telemetry -> Polars
        print("  → Converting telemetry to Polars...")
        telemetry_data = {}

        for driver in f1_session.laps['Driver'].unique():
            try:
                driver_laps = f1_session.laps.pick_drivers(driver)
                all_telemetry = []

                for _, lap in driver_laps.iterrows():
                    try:
                        tel = lap.get_telemetry()
                        if tel is not None and not tel.empty:
                            tel = tel.copy()
                            tel['LapNumber'] = lap['LapNumber']
                            if 'SessionTime' not in tel.columns and 'Time' in tel.columns:
                                lap_start = lap['LapStartTime']
                                if pd.notna(lap_start):
                                    tel['SessionTime'] = lap_start + tel['Time']
                            all_telemetry.append(tel)
                    except Exception:
                        continue

                if all_telemetry:
                    combined = pd.concat(all_telemetry, ignore_index=True)
                    if 'SessionTime' in combined.columns:
                        combined['SessionSeconds'] = combined['SessionTime'].dt.total_seconds()

                    # Convert Pandas to Polars (2-5x memory efficient)
                    telemetry_data[driver] = pl.from_pandas(
                        combined.sort_values('SessionTime').reset_index(drop=True)
                    )
                    print(f"    ✓ {driver}: {len(combined)} telemetry points")
            except Exception as e:
                print(f"    ⚠ {driver}: {e}")

        # Extract metadata
        metadata = {
            'year': year,
            'round': round_num,
            'event_name': getattr(f1_session.event, 'EventName', ''),
            'session_type': session_id,
            'drivers': list(telemetry_data.keys()),
        }

        # Extract team colors from FastF1 session results
        driver_colors = {}
        try:
            if hasattr(f1_session, 'results') and f1_session.results is not None:
                results_df = f1_session.results
                # SessionResults is a DataFrame subclass with Abbreviation and TeamColor columns
                if hasattr(results_df, 'iterrows') and 'Abbreviation' in results_df.columns and 'TeamColor' in results_df.columns:
                    for _, row in results_df.iterrows():
                        driver_code = row['Abbreviation']
                        team_color = row['TeamColor']
                        if pd.notna(driver_code) and pd.notna(team_color):
                            color_str = str(team_color)
                            # Ensure it has # prefix (FastF1 returns colors without #)
                            if not color_str.startswith('#'):
                                color_str = f'#{color_str}'
                            driver_colors[driver_code] = color_str

                if driver_colors:
                    print(f"  ✓ Extracted team colors for {len(driver_colors)} drivers")
                    metadata['driver_colors'] = driver_colors
        except Exception as e:
            print(f"  ℹ Could not extract team colors: {e}")

        # Extract track geometry
        track_data = {}
        try:
            fastest_lap = f1_session.laps.pick_fastest()
            if fastest_lap is not None:
                tel = fastest_lap.get_telemetry()
                if tel is not None and not tel.empty:
                    track_data = {
                        'X': tel['X'].astype(np.float32).values,
                        'Y': tel['Y'].astype(np.float32).values,
                    }
                    if 'Distance' in tel.columns:
                        track_data['Distance'] = tel['Distance'].astype(np.float32).values
        except Exception:
            pass

        # Extract pit lane geometry from laps with pit stops
        # Strategy:
        # 1. Get full telemetry from one in-lap (car entering pit)
        # 2. Get full telemetry from one out-lap (car exiting pit)
        # 3. Combine and deduplicate, removing stationary periods
        pit_lane_data = None
        try:
            # Find laps where drivers entered pits (in-laps) and exited (out-laps)
            in_laps = f1_session.laps.pick_box_laps(which='in')
            out_laps = f1_session.laps.pick_box_laps(which='out')

            in_lap_count = len(in_laps) if in_laps is not None else 0
            out_lap_count = len(out_laps) if out_laps is not None else 0

            if in_lap_count == 0 and out_lap_count == 0:
                print(f"  ℹ Pit lane not available (no pit stops)")
                pit_lane_data = None
            else:
                print(f"  → Pit stop laps found: {in_lap_count} in-laps, {out_lap_count} out-laps")

                all_pit_x, all_pit_y = [], []

                # Extract full telemetry from one in-lap
                if in_laps is not None and len(in_laps) > 0:
                    for _, in_lap in in_laps.iterrows():
                        try:
                            tel = in_lap.get_telemetry()
                            if tel is None or len(tel) < 100:
                                continue

                            all_pit_x.extend(tel['X'].values)
                            all_pit_y.extend(tel['Y'].values)
                            driver = in_lap['Driver']
                            lap_num = in_lap['LapNumber']
                            print(f"    In-lap: {len(tel)} points (lap {lap_num}, {driver})")
                            break  # Use first valid one
                        except Exception:
                            continue

                # Extract full telemetry from one out-lap
                if out_laps is not None and len(out_laps) > 0:
                    for _, lap in out_laps.iterrows():
                        try:
                            tel = lap.get_telemetry()
                            if tel is None or len(tel) < 100:
                                continue

                            all_pit_x.extend(tel['X'].values)
                            all_pit_y.extend(tel['Y'].values)
                            driver = lap['Driver']
                            lap_num = lap['LapNumber']
                            print(f"    Out-lap: {len(tel)} points (lap {lap_num}, {driver})")
                            break  # Use first valid one
                        except Exception:
                            continue

                if len(all_pit_x) < 10:
                    print(f"  ℹ Not enough pit lane data points ({len(all_pit_x)})")
                    pit_lane_data = None
                else:
                    # Remove consecutive duplicates (e.g., from red flag stationary periods)
                    # Keep same resolution as track but remove points where car didn't move
                    unique_x, unique_y = [all_pit_x[0]], [all_pit_y[0]]
                    for i in range(1, len(all_pit_x)):
                        # Keep point if it moved more than 1m from previous
                        dist = np.sqrt((all_pit_x[i] - unique_x[-1])**2 + (all_pit_y[i] - unique_y[-1])**2)
                        if dist > 1.0:
                            unique_x.append(all_pit_x[i])
                            unique_y.append(all_pit_y[i])

                    print(f"    Deduplicated: {len(unique_x)} points (from {len(all_pit_x)})")

                    # Clip 500 points from each end to remove on-track portions
                    if len(unique_x) > 1000:
                        unique_x = unique_x[500:-500]
                        unique_y = unique_y[500:-500]
                        print(f"    Clipped 500 from each end: {len(unique_x)} points")

                    pit_lane_data = {
                        'X': np.array(unique_x, dtype=np.float32),
                        'Y': np.array(unique_y, dtype=np.float32),
                    }

                    print(f"  ✓ Pit lane extracted: {len(pit_lane_data['X'])} points")

        except Exception as e:
            print(f"  ℹ Could not extract pit lane: {e}")
            pit_lane_data = None

        # Create immutable SessionDataset
        return SessionDataset(
            version="1.0.0",
            session_type=session_id,
            metadata=metadata,
            telemetry=telemetry_data,
            track=track_data,
            pit_lane=pit_lane_data,  # Extracted from circuit_info
            position_history=[],  # TODO: Build position history
            intervals=[],  # TODO: Extract interval data
            track_status=[],  # TODO: Extract track status
            race_control=[],  # TODO: Extract race control messages
            weather=[],  # TODO: Extract weather data
            fastest_laps=[],  # TODO: Extract fastest laps
        )

    # =========================================================================
    # Cache Operations
    # =========================================================================

    def _load_from_cache(self, cache_path: Path, data_class: Type[T]) -> Optional[T]:
        """Load data from pickle cache."""
        if cache_path.exists():
            try:
                with open(cache_path, 'rb') as f:
                    return pickle.load(f)
            except Exception:
                return None
        return None

    def _save_to_cache(self, dataset: Any, cache_path: Path) -> None:
        """Save data to pickle cache."""
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        with open(cache_path, 'wb') as f:
            pickle.dump(dataset, f, protocol=pickle.HIGHEST_PROTOCOL)


# ============================================================================
# Backward Compatibility: DataLoader Facade
# ============================================================================

class DataLoader:
    """
    Facade for backward compatibility.

    Wraps RaceDataLoader and creates Race instances from SessionDataset objects.
    """

    def __init__(self, cache_dir: str = "race_data"):
        """Initialize data loader with cache directory."""
        self.cache_dir = Path(cache_dir)
        self._loader = RaceDataLoader(str(cache_dir))

    def load_race(self, year: int, round_num: int,
                  force_reprocess: bool = False) -> 'Race':
        """
        Load race data from cache or FastF1.

        Returns a Race instance wrapping the SessionDataset.
        """
        from .race import Race

        # Load session dataset
        dataset = self._loader.load_session(year, round_num, 'R', force_reprocess)
        weekend_data = self._loader.load_weekend(year, round_num, force_reprocess)

        # Create Race instance
        return Race(dataset, weekend_data)

    def load_catalog(self) -> F1Catalog:
        """Load F1 catalog (all seasons)."""
        return self._loader.load_catalog()
