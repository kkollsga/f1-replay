"""
Race - High-level API for accessing F1 race data.

This module is deliberately simple - it DOES NOT import fastf1.
All FastF1 access is centralized in data_loader.py.

The Race class wraps an immutable SessionDataset and provides convenient
access to telemetry, track geometry, weather, and race events.
"""

from typing import Optional, Dict, Any, List
import numpy as np
import polars as pl

if __name__ != '__main__':
    from .data_loader import SessionDataset, RaceWeekendData


class Race:
    """
    High-level API for accessing preprocessed F1 race data.

    This class wraps an immutable SessionDataset and provides convenient
    access to all race data without any direct FastF1 dependencies.

    The data is fully loaded and immutable - no lazy loading, no API calls.

    Usage:
        # Get via data_loader (normal way)
        loader = DataLoader()
        race = loader.load_race(2024, 21)

        # Access data
        standings = race.get_standings_at_time(1200)  # At 20 minutes
        telemetry = race.telemetry_data
        track = race.track_data
    """

    def __init__(self, dataset: 'SessionDataset', weekend_data: 'RaceWeekendData'):
        """
        Initialize Race from immutable SessionDataset.

        Args:
            dataset: SessionDataset containing all session data (telemetry, track, etc.)
            weekend_data: RaceWeekendData containing weekend metadata
        """
        self._dataset = dataset
        self._weekend = weekend_data

    # =========================================================================
    # Data Properties (expose dataset fields)
    # =========================================================================

    @property
    def metadata(self) -> Dict[str, Any]:
        """Get race metadata (event name, drivers, track length, etc.)."""
        return self._dataset.metadata

    @property
    def telemetry_data(self) -> Dict[str, pl.DataFrame]:
        """
        Get telemetry for all drivers.

        Returns a dict mapping driver code to Polars DataFrame with:
        - Time, SessionTime, Distance columns
        - X, Y position data
        - Speed, Throttle, Brake, etc.

        Example:
            race = loader.load_race(2024, 21)
            max_df = race.telemetry_data['MAX']
            speeds = max_df['Speed'].to_list()
        """
        return self._dataset.telemetry

    @property
    def track_data(self) -> Dict[str, np.ndarray]:
        """
        Get track geometry (X, Y coordinates and optional distance markers).

        Returns dict with:
        - 'X': np.ndarray of X coordinates
        - 'Y': np.ndarray of Y coordinates
        - 'Distance': np.ndarray of distance along track (optional)
        """
        return self._dataset.track

    @property
    def pit_lane_data(self) -> Optional[Dict[str, np.ndarray]]:
        """Get pit lane geometry if available."""
        return self._dataset.pit_lane

    @property
    def position_history(self) -> List[Dict]:
        """Get position history snapshots (standings at intervals during race)."""
        return self._dataset.position_history

    @property
    def intervals_per_lap(self) -> List[Dict]:
        """Get per-lap interval data (gap to leader for each driver)."""
        return self._dataset.intervals

    @property
    def track_status_events(self) -> List[Dict]:
        """Get track status events (yellow flags, red flags, SC, etc.)."""
        return self._dataset.track_status

    @property
    def race_control_messages(self) -> List[Dict]:
        """Get race control messages."""
        return self._dataset.race_control

    @property
    def weather_data(self) -> List[Dict]:
        """Get weather data samples throughout the session."""
        return self._dataset.weather

    @property
    def fastest_laps(self) -> List[Dict]:
        """Get fastest lap history (fastest lap progression)."""
        return self._dataset.fastest_laps

    # =========================================================================
    # Convenience Properties
    # =========================================================================

    @property
    def drivers(self) -> List[str]:
        """Get list of driver codes."""
        return self.metadata.get('drivers', [])

    @property
    def year(self) -> int:
        """Get season year."""
        return self._weekend.year

    @property
    def round_number(self) -> int:
        """Get race round number."""
        return self._weekend.round_number

    @property
    def event_name(self) -> str:
        """Get event name (e.g., 'Bahrain Grand Prix')."""
        return self._weekend.event_name

    @property
    def circuit_name(self) -> str:
        """Get circuit name (e.g., 'Bahrain International Circuit')."""
        return self._weekend.circuit_name

    @property
    def location(self) -> str:
        """Get location (e.g., 'Sakhir')."""
        return self._weekend.location

    @property
    def country(self) -> str:
        """Get country."""
        return self._weekend.country

    @property
    def session_type(self) -> str:
        """Get session type (R for race, Q for qualifying, etc.)."""
        return self._dataset.session_type

    @property
    def track_length(self) -> float:
        """Get track length in meters."""
        return self.metadata.get('track_length', 0.0)

    @property
    def total_laps(self) -> int:
        """Get total number of laps."""
        return self.metadata.get('total_laps', 0)

    @property
    def t0_date_utc(self) -> Optional[str]:
        """Get race start time (t0) in UTC."""
        return self.metadata.get('t0_date_utc')

    # =========================================================================
    # Query Methods
    # =========================================================================

    def get_driver_telemetry(self, driver: str) -> pl.DataFrame:
        """
        Get telemetry DataFrame for a specific driver.

        Args:
            driver: Driver code (e.g., 'MAX', 'LEC')

        Returns:
            Polars DataFrame with telemetry columns

        Raises:
            ValueError: If driver not in telemetry data
        """
        if driver not in self.telemetry_data:
            raise ValueError(f"Driver {driver} not found in telemetry")
        return self.telemetry_data[driver]

    def at_time(self, time_input) -> pl.DataFrame:
        """
        Get telemetry snapshot for all drivers at a specific time.

        Args:
            time_input: Either:
                - Float/int: Time in seconds (e.g., 120 or 120.5)
                - String: Time in format "MM:SS" or "HH:MM:SS" (e.g., "2:00" or "0:02:00")

        Returns:
            Polars DataFrame with one row per driver, closest to the requested time

        Example:
            race = loader.load_race(2024, 21)
            snapshot = race.at_time(1200)  # At 20 minutes
            snapshot = race.at_time("20:00")  # Same
        """
        # Parse time
        race_time_seconds = self._parse_time_input(time_input)

        # Get closest telemetry for each driver
        rows = []

        for driver, df in self.telemetry_data.items():
            if df.height == 0:
                continue

            # Find closest point to requested time
            # Polars filter and sort for speed
            closest = df.with_columns(
                time_diff=(pl.col('SessionSeconds') - race_time_seconds).abs()
            ).sort('time_diff').head(1)

            if closest.height > 0:
                row_dict = closest.row(0, named=True)
                row_dict['Driver'] = driver
                rows.append(row_dict)

        if not rows:
            return pl.DataFrame()

        return pl.DataFrame(rows)

    def get_standings_at_time(self, time_input) -> List[Dict]:
        """
        Get standings at a specific time using position history.

        Args:
            time_input: Either:
                - Float/int: Time in seconds (e.g., 120 or 120.5)
                - String: Time in format "MM:SS" or "HH:MM:SS" (e.g., "2:00" or "0:02:00")

        Returns:
            List of driver standings with position, code, interval, etc.
        """
        race_time_seconds = self._parse_time_input(time_input)

        if not self.position_history:
            raise ValueError("No position history available")

        # Find closest time in position history
        closest = min(
            self.position_history,
            key=lambda x: abs(x.get('time', 0) - race_time_seconds)
        )

        return closest.get('standings', [])

    def t0_time(self) -> str:
        """
        Get the race start time (t0 / lights out) in local timezone.

        Returns:
            str: Race start time in "HH:MM:SS (UTCoffset)" format

        Example:
            race = loader.load_race(2024, 21)
            print(race.t0_time())
            # "15:00:00 (UTC+3)"
        """
        # Try to get from metadata
        t0_date = self.t0_date_utc

        if not t0_date:
            return "Unknown"

        try:
            import pandas as pd

            # Parse as timestamp
            if isinstance(t0_date, str):
                ts = pd.Timestamp(t0_date)
            else:
                ts = t0_date

            # Try to get local time from metadata
            start_time_local = self.metadata.get('start_time_local')

            if start_time_local:
                # Calculate timezone offset
                local_hours, local_minutes, local_seconds = map(
                    int, start_time_local.split(':')
                )
                offset_hours = local_hours - ts.hour
                offset_minutes = local_minutes - ts.minute

                # Normalize offset
                if offset_hours > 12:
                    offset_hours -= 24
                elif offset_hours < -12:
                    offset_hours += 24

                # Format result
                tz_str = f"UTC{offset_hours:+d}"
                if offset_minutes:
                    tz_str += f":{abs(offset_minutes):02d}"

                return f"{start_time_local} ({tz_str})"
            else:
                # Just return UTC time
                return ts.strftime("%H:%M:%S (UTC)")

        except Exception:
            return str(t0_date)

    # =========================================================================
    # Helper Methods
    # =========================================================================

    @staticmethod
    def _parse_time_input(time_input) -> float:
        """
        Parse time input and return seconds.

        Args:
            time_input: Float/int (seconds) or string "MM:SS" or "HH:MM:SS"

        Returns:
            Time in seconds as float
        """
        if isinstance(time_input, (int, float)):
            return float(time_input)

        if isinstance(time_input, str):
            parts = time_input.split(':')
            if len(parts) == 2:  # MM:SS
                minutes, secs = int(parts[0]), float(parts[1])
                return minutes * 60 + secs
            elif len(parts) == 3:  # HH:MM:SS
                hours, minutes, secs = int(parts[0]), int(parts[1]), float(parts[2])
                return hours * 3600 + minutes * 60 + secs
            else:
                raise ValueError("Time format should be 'MM:SS' or 'HH:MM:SS'")

        raise TypeError(f"time_input must be float, int, or str, got {type(time_input)}")

    def __repr__(self) -> str:
        """String representation."""
        return (
            f"Race({self.year} Round {self.round_number}: "
            f"{self.event_name}, {self.drivers.__len__()} drivers)"
        )
