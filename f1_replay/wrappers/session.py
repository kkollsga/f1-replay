"""
Session wrapper classes for F1 data.

Wraps SessionData dataclass with convenience methods.

Session Type Hierarchy:
    Session (base)
    ├── RaceSession (position tracking during race)
    ├── SprintSession
    ├── QualiSession
    ├── SprintQualiSession
    └── PracticeSession (FP1, FP2, FP3)
"""

from typing import TYPE_CHECKING, Dict, List, Optional, Tuple, Any
import polars as pl

from f1_replay.models import SessionData, TrackGeometry, PitLane
from f1_replay.loaders.session.weather import WeatherExtractor

if TYPE_CHECKING:
    from f1_replay.wrappers.race_weekend import RaceWeekend


class Session:
    """
    Base session wrapper - delegates to SessionData dataclass.

    Stores the immutable SessionData and adds convenience methods.
    """

    def __init__(
        self,
        data: SessionData,
        weekend: "RaceWeekend",
        raw_session: Any = None,
    ):
        self._data = data
        self._weekend = weekend
        self._raw_session = raw_session

    # =========================================================================
    # Metadata properties (delegate to _data.metadata)
    # =========================================================================

    @property
    def session_type(self) -> str:
        return self._data.metadata.session_type

    @property
    def year(self) -> int:
        return self._data.metadata.year

    @property
    def round_number(self) -> int:
        return self._data.metadata.round_number

    @property
    def event_name(self) -> str:
        return self._data.metadata.event_name

    @property
    def drivers(self) -> List[str]:
        return self._data.metadata.drivers

    @property
    def driver_numbers(self) -> Dict[str, int]:
        return self._data.metadata.driver_numbers

    @property
    def driver_names(self) -> Dict[str, str]:
        return self._data.metadata.driver_names

    @property
    def driver_teams(self) -> Dict[str, str]:
        return self._data.metadata.driver_teams

    @property
    def driver_colors(self) -> Dict[str, str]:
        return self._data.metadata.driver_colors

    @property
    def track_length(self) -> float:
        return self._data.metadata.track_length

    @property
    def total_laps(self) -> int:
        return self._data.metadata.total_laps

    @property
    def dnf_drivers(self) -> List[str]:
        return self._data.metadata.dnf_drivers

    @property
    def start_time_local(self) -> Optional[str]:
        return self._data.metadata.start_time_local

    # =========================================================================
    # T0 / timing properties
    # =========================================================================

    @property
    def t0_utc(self) -> Optional[str]:
        return self._data.metadata.t0.utc if self._data.metadata.t0 else None

    @property
    def t0_timezone(self) -> str:
        return self._data.metadata.t0.timezone if self._data.metadata.t0 else ""

    @property
    def lights_out_offset(self) -> float:
        return self._data.metadata.t0.lights_out_offset if self._data.metadata.t0 else 0.0

    @property
    def warmup_start_time(self) -> Optional[float]:
        """Session time when formation lap starts (seconds since t0)."""
        return self._data.metadata.t0.warmup_start_offset if self._data.metadata.t0 else None

    @property
    def race_start_time(self) -> Optional[float]:
        """Session time when lights go out / race starts (seconds since t0)."""
        return self._data.metadata.t0.lights_out_offset if self._data.metadata.t0 else 0.0

    @property
    def warm_up_offset(self) -> Optional[float]:
        """Alias for warmup_start_time (for backwards compatibility)."""
        return self.warmup_start_time

    # =========================================================================
    # Data properties (delegate to _data)
    # =========================================================================

    @property
    def telemetry(self) -> Dict[str, pl.DataFrame]:
        return self._data.telemetry

    @property
    def track_status(self) -> pl.DataFrame:
        return self._data.events.track_status

    @property
    def race_control(self) -> pl.DataFrame:
        return self._data.events.race_control

    @property
    def weather(self) -> pl.DataFrame:
        """Weather data (empty - weather is integrated into track_status as rain events)."""
        return pl.DataFrame()

    @property
    def rain_events(self) -> pl.DataFrame:
        """Extract rain events from track_status."""
        track_status = self._data.events.track_status
        if track_status.height == 0:
            return pl.DataFrame(schema={'start_time': pl.Float64, 'end_time': pl.Float64, 'duration': pl.Float64})

        # Filter rain events
        rain_starts = track_status.filter(pl.col('status') == 'RainStart')
        rain_ends = track_status.filter(pl.col('status') == 'RainEnd')

        if rain_starts.height == 0 or rain_ends.height == 0:
            return pl.DataFrame(schema={'start_time': pl.Float64, 'end_time': pl.Float64, 'duration': pl.Float64})

        # Pair starts with ends
        rain_events = []
        start_times = rain_starts['session_time'].to_list()
        end_times = rain_ends['session_time'].to_list()

        for start in start_times:
            # Find next end after this start
            matching_ends = [end for end in end_times if end > start]
            if matching_ends:
                end = min(matching_ends)
                rain_events.append({
                    'start_time': start,
                    'end_time': end,
                    'duration': end - start
                })

        return pl.DataFrame(rain_events) if rain_events else pl.DataFrame(schema={'start_time': pl.Float64, 'end_time': pl.Float64, 'duration': pl.Float64})

    @property
    def fastest_laps(self) -> List:
        return self._data.results.fastest_laps

    @property
    def position_history(self) -> List:
        return self._data.results.position_history

    # =========================================================================
    # References
    # =========================================================================

    @property
    def data(self) -> SessionData:
        """Underlying SessionData dataclass."""
        return self._data

    @property
    def raw_session(self):
        """Raw FastF1 session (only when freshly loaded, not from cache)."""
        return self._raw_session

    @property
    def weekend(self) -> "RaceWeekend":
        """Parent RaceWeekend."""
        return self._weekend

    @property
    def circuit_length(self) -> float:
        """Circuit length from weekend."""
        return self._weekend.circuit_length

    @property
    def track(self) -> TrackGeometry:
        """Track geometry from weekend."""
        return self._weekend.track

    @property
    def pit_lane(self) -> Optional[PitLane]:
        """Pit lane geometry from weekend."""
        return self._weekend.pit_lane

    # =========================================================================
    # Convenience methods
    # =========================================================================

    @property
    def driver_info(self) -> Dict[str, Dict]:
        """Get driver information as {driver: {number, name, team, color}}."""
        return {
            driver: {
                'number': self.driver_numbers.get(driver),
                'name': self.driver_names.get(driver),
                'team': self.driver_teams.get(driver),
                'color': self.driver_colors.get(driver)
            }
            for driver in self.drivers
        }

    def get_driver_telemetry(self, driver: str) -> Optional[pl.DataFrame]:
        """Get telemetry for a specific driver."""
        return self.telemetry.get(driver)

    def is_raining(self, session_time: float) -> bool:
        """Check if it's raining at a specific session time."""
        return WeatherExtractor.is_raining(self.rain_events, session_time)

    def __repr__(self) -> str:
        return f"Session({self.year} R{self.round_number} {self.session_type}: {self.event_name})"


class RaceSession(Session):
    """Race session with position tracking methods."""

    @property
    def lights_out(self) -> float:
        """Lights out time as offset in seconds from session start (t0)."""
        return self._data.metadata.t0.lights_out_offset if self._data.metadata.t0 else 0.0

    @property
    def lights_out_idx(self) -> Optional[int]:
        """Row index in telemetry where the race starts (lights out)."""
        if not self.telemetry:
            return None
        # Use first available driver's telemetry
        driver = next(iter(self.telemetry))
        tel = self.telemetry[driver]
        if "session_time" not in tel.columns:
            return None
        # Find first row where session_time >= lights_out
        mask = tel["session_time"] >= self.lights_out
        if not mask.any():
            return None
        return mask.arg_max()

    def get_order_at_time(self, session_time: float) -> List[Tuple[int, str, float]]:
        """
        Get driver standings at a specific time.

        Args:
            session_time: Time in seconds since session start

        Returns:
            List of (position, driver, race_distance) tuples sorted by position
        """
        from f1_replay.loaders.session.order import OrderBuilder
        return OrderBuilder.get_order_at_time(self.telemetry, session_time)

    def get_order_at_lap(self, lap: int) -> List[Tuple[int, str, float]]:
        """
        Get driver standings when they completed a specific lap.

        For drivers who completed the lap: order by who crossed first.
        For DNF drivers: order by their max race_distance.

        Args:
            lap: Lap number to check

        Returns:
            List of (position, driver, race_distance) tuples sorted by position
        """
        from f1_replay.loaders.session.order import OrderBuilder
        return OrderBuilder.get_order_at_lap(self.telemetry, lap, self.track_length)

    def get_leader_at_time(self, session_time: float) -> Optional[str]:
        """Get race leader at a specific time."""
        order = self.get_order_at_time(session_time)
        return order[0][1] if order else None

    def get_telemetry_every_lap(self, driver: str, offset: int = 0) -> Optional[pl.DataFrame]:
        """
        Get one telemetry point per lap for a driver.

        Args:
            driver: Driver code (e.g., 'LEC')
            offset: Which point within each lap to return:
                    0 = first point of each lap (default)
                    -1 = last point of each lap
                    n = nth point of each lap

        Returns:
            DataFrame with one row per lap, or None if driver not found
        """
        tel = self.telemetry.get(driver)
        if tel is None:
            return None

        if "lap_number" not in tel.columns:
            return None

        # Group by lap_number and get the specified row from each group
        if offset == 0:
            # First point of each lap
            result = tel.group_by("lap_number", maintain_order=True).first()
        elif offset == -1:
            # Last point of each lap
            result = tel.group_by("lap_number", maintain_order=True).last()
        else:
            # Nth point of each lap
            result = (
                tel.with_row_index("_row_idx")
                .with_columns(
                    pl.col("_row_idx").rank("ordinal").over("lap_number").alias("_lap_idx")
                )
                .filter(pl.col("_lap_idx") == (offset + 1 if offset >= 0 else pl.col("_lap_idx").max().over("lap_number") + offset + 1))
                .drop(["_row_idx", "_lap_idx"])
            )

        return result.sort("lap_number")

    def get_telemetry_every_minute(self, driver: str, interval: float = 1.0) -> Optional[pl.DataFrame]:
        """
        Get telemetry at regular time intervals for a driver.

        Args:
            driver: Driver code (e.g., 'LEC')
            interval: Time interval in minutes (default=1.0, so 0.5=30s, 2.0=120s)

        Returns:
            DataFrame with one row per interval, or None if driver not found
        """
        tel = self.telemetry.get(driver)
        if tel is None:
            return None

        if "session_time" not in tel.columns:
            return None

        interval_seconds = interval * 60.0

        # Get min/max session_time
        min_time = tel["session_time"].min()
        max_time = tel["session_time"].max()

        if min_time is None or max_time is None:
            return None

        # Generate target times
        import numpy as np
        target_times = np.arange(min_time, max_time, interval_seconds)

        if len(target_times) == 0:
            return None

        # For each target time, find the closest row
        results = []
        for target in target_times:
            # Get the row with session_time closest to target
            closest = tel.with_columns(
                (pl.col("session_time") - target).abs().alias("_diff")
            ).sort("_diff").head(1)
            results.append(closest.drop("_diff"))

        return pl.concat(results)

    def __repr__(self) -> str:
        return f"RaceSession({self.year} R{self.round_number}: {self.event_name})"


class SprintSession(RaceSession):
    """Sprint race session."""
    def __repr__(self) -> str:
        return f"SprintSession({self.year} R{self.round_number}: {self.event_name})"


class QualiSession(Session):
    """Qualifying session."""
    def __repr__(self) -> str:
        return f"QualiSession({self.year} R{self.round_number}: {self.event_name})"


class SprintQualiSession(Session):
    """Sprint qualifying session."""
    def __repr__(self) -> str:
        return f"SprintQualiSession({self.year} R{self.round_number}: {self.event_name})"


class PracticeSession(Session):
    """Free practice session (FP1, FP2, FP3)."""
    def __repr__(self) -> str:
        return f"PracticeSession({self.year} R{self.round_number} {self.session_type}: {self.event_name})"


def create_session(
    data: SessionData,
    weekend: "RaceWeekend",
    raw_session: Any = None,
) -> Session:
    """
    Factory function to create the appropriate session type.

    Args:
        data: SessionData dataclass
        weekend: Parent RaceWeekend
        raw_session: Optional FastF1 session
    """
    session_type = data.metadata.session_type

    if session_type == 'R':
        return RaceSession(data=data, weekend=weekend, raw_session=raw_session)
    elif session_type == 'S':
        return SprintSession(data=data, weekend=weekend, raw_session=raw_session)
    elif session_type == 'Q':
        return QualiSession(data=data, weekend=weekend, raw_session=raw_session)
    elif session_type == 'SQ':
        return SprintQualiSession(data=data, weekend=weekend, raw_session=raw_session)
    else:  # FP1, FP2, FP3
        return PracticeSession(data=data, weekend=weekend, raw_session=raw_session)
