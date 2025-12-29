"""
Session - High-level wrapper for SessionData.

Provides convenient property-based access to session metadata, telemetry, events, and results.
Combines session-specific data with weekend context (circuit, track geometry).
"""

from typing import Dict, List, Optional, Tuple
import polars as pl

from f1_replay.data_loader.data_models import SessionData, TrackGeometry
from f1_replay.race_weekend import RaceWeekend
from f1_replay.data_loader.weather_extractor import WeatherExtractor


class Session:
    """
    Wraps SessionData and RaceWeekend, provides convenient access to all session information.

    Combines session-specific data (telemetry, events, results) with weekend context
    (circuit geometry, track info).

    Usage:
        session = Session(session_data, race_weekend)
        print(f"{session.session_type} at {session.event_name}")
        tel = session.get_driver_telemetry('VER')
        is_wet = session.is_raining(3600.0)
    """

    def __init__(self, session_data: SessionData, weekend: RaceWeekend):
        """
        Initialize from SessionData and RaceWeekend.

        Args:
            session_data: SessionData immutable dataclass
            weekend: RaceWeekend wrapper object
        """
        self._data = session_data
        self._weekend = weekend

    # =========================================================================
    # Session Metadata Properties
    # =========================================================================

    @property
    def session_type(self) -> str:
        """Get session type (e.g., 'R', 'Q', 'FP1', 'FP2', 'FP3', 'S')."""
        return self._data.metadata.session_type

    @property
    def year(self) -> int:
        """Get season year."""
        return self._data.metadata.year

    @property
    def round_number(self) -> int:
        """Get race round number."""
        return self._data.metadata.round_number

    @property
    def event_name(self) -> str:
        """Get event name (e.g., 'Abu Dhabi Grand Prix')."""
        return self._data.metadata.event_name

    @property
    def drivers(self) -> List[str]:
        """Get list of driver abbreviations in session."""
        return self._data.metadata.drivers

    @property
    def driver_info(self) -> Dict[str, Dict]:
        """
        Get driver information as a convenient dict.

        Returns:
            {driver_code: {number, name, team, color}}
            e.g., {'VER': {'number': 1, 'name': 'Max Verstappen', 'team': 'Red Bull Racing', 'color': '#0600EF'}}
        """
        result = {}
        for driver in self.drivers:
            result[driver] = {
                'number': self._data.metadata.driver_numbers.get(driver),
                'name': self._data.metadata.driver_names.get(driver),
                'team': self._data.metadata.driver_teams.get(driver),
                'color': self._data.metadata.driver_colors.get(driver)
            }
        return result

    @property
    def track_length(self) -> float:
        """Get circuit length in meters."""
        return self._data.metadata.track_length

    @property
    def total_laps(self) -> int:
        """Get total number of laps in session."""
        return self._data.metadata.total_laps

    @property
    def t0_date_utc(self) -> Optional[str]:
        """Get session start time in UTC (ISO format)."""
        return self._data.metadata.t0_date_utc

    @property
    def start_time_local(self) -> Optional[str]:
        """Get session start time in local timezone."""
        return self._data.metadata.start_time_local

    # =========================================================================
    # Telemetry Properties
    # =========================================================================

    @property
    def telemetry(self) -> Dict[str, pl.DataFrame]:
        """
        Get telemetry for all drivers.

        Returns:
            Dict mapping driver code to telemetry DataFrame
            Columns: session_time, LapNumber, X, Y, Distance, progress, TimeToDriverAhead, etc.
        """
        return self._data.telemetry

    # =========================================================================
    # Events Properties
    # =========================================================================

    @property
    def track_status(self) -> pl.DataFrame:
        """
        Get track status events.

        Returns:
            DataFrame with columns: status, message, time, session_time
        """
        return self._data.events.track_status

    @property
    def race_control(self) -> pl.DataFrame:
        """
        Get race control messages.

        Returns:
            DataFrame with columns: message, time, session_time
        """
        return self._data.events.race_control

    @property
    def weather(self) -> pl.DataFrame:
        """
        Get weather samples.

        Returns:
            DataFrame with columns: temperature, humidity, wind_speed, wind_direction,
            track_temperature, rainfall, time, session_time
        """
        return self._data.events.weather

    @property
    def rain_events(self) -> pl.DataFrame:
        """
        Get compacted rain events (transitions only).

        Returns:
            DataFrame with columns: start_time, end_time, duration
            Each row represents one continuous rain period.
            Empty DataFrame if not available (for backward compatibility with cached data).
        """
        if hasattr(self._data, 'rain_events') and self._data.rain_events is not None:
            return self._data.rain_events
        # Return empty DataFrame for backward compatibility with older cached sessions
        return pl.DataFrame({'start_time': [], 'end_time': [], 'duration': []})

    # =========================================================================
    # Results Properties
    # =========================================================================

    @property
    def fastest_laps(self):
        """
        Get fastest lap progression (chronological record of fastest lap changes).

        Returns:
            List of FastestLapEvent objects with:
            - lap: lap number when fastest lap was set
            - driver: driver code
            - time: lap duration in seconds
            - lap_time_ms: lap duration in milliseconds
            - session_time: when during the session the fastest lap was completed (seconds since t0)

        Example:
            session = Session(session_data, race_weekend)
            for fastest_lap in session.fastest_laps:
                print(f"{fastest_lap.driver} set fastest lap on lap {fastest_lap.lap}: {fastest_lap.time:.3f}s")
        """
        return self._data.results.fastest_laps

    @property
    def position_history(self):
        """
        Get position snapshots (standings at moments in time).

        Returns:
            List of PositionSnapshot objects with time, lap, standings
        """
        return self._data.results.position_history

    @property
    def order(self) -> pl.DataFrame:
        """
        Get order (position changes).

        Returns:
            DataFrame with session_time and driver positions (only rows where order changed)
            Columns vary by session type but include session_time, driver positions/progress
        """
        return self._data.order

    # =========================================================================
    # Query Methods
    # =========================================================================

    def get_driver_telemetry(self, driver: str) -> Optional[pl.DataFrame]:
        """
        Get telemetry for a specific driver.

        Args:
            driver: Driver abbreviation (e.g., 'VER')

        Returns:
            Telemetry DataFrame or None if driver not in session
        """
        return self._data.telemetry.get(driver)

    def get_drivers_at_time(self, session_time: float) -> List[Tuple[int, str]]:
        """
        Get driver positions at a specific session time.

        Uses order dataset and interpolates between recorded position changes.

        Args:
            session_time: Session time in seconds

        Returns:
            List of (position, driver) tuples sorted by position
            e.g., [(1, 'VER'), (2, 'LEC'), (3, 'HAM')]
        """
        if len(self.order) == 0:
            return []

        # Find the row with session_time <= target
        order_rows = self.order.filter(
            pl.col('session_time') <= session_time
        ).sort('session_time', descending=True)

        if len(order_rows) == 0:
            return []

        # Use the most recent row
        latest_row = order_rows[0]
        row_dict = latest_row.to_dicts()[0]

        # Extract position columns (format: "{driver}_position")
        positions = []
        for driver in self.drivers:
            pos_col = f'{driver}_position'
            if pos_col in row_dict and row_dict[pos_col] is not None:
                pos = int(row_dict[pos_col])
                positions.append((pos, driver))

        # Sort by position
        positions.sort(key=lambda x: x[0])
        return positions

    def is_raining(self, session_time: float) -> bool:
        """
        Check if it's raining at a specific session time.

        Args:
            session_time: Session time in seconds

        Returns:
            True if raining at this time, False otherwise
        """
        return WeatherExtractor.is_raining(self.rain_events, session_time)

    # =========================================================================
    # Weekend Pass-Through Properties
    # =========================================================================

    @property
    def weekend(self) -> RaceWeekend:
        """Get the underlying RaceWeekend object."""
        return self._weekend

    @property
    def circuit_length(self) -> float:
        """Get circuit length in meters (from weekend)."""
        return self._weekend.circuit_length

    @property
    def track(self) -> TrackGeometry:
        """Get track geometry (from weekend)."""
        return self._weekend.track

    @property
    def pit_lane(self) -> Optional[TrackGeometry]:
        """Get pit lane geometry (from weekend)."""
        return self._weekend.pit_lane

    def __repr__(self) -> str:
        """String representation."""
        return f"Session({self.year} R{self.round_number} {self.session_type}: {self.event_name})"
