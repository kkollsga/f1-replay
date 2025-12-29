"""
Telemetry Consolidator - UTILITY MODULE

Combines telemetry from all drivers into a single consolidated dataframe
using distance along track as the primary index.

Features:
- Consolidate all drivers by track distance
- Detect pit lane vs on-track driving
- Calculate standings at any point in race
- Interpolate positions for smooth visualization
- Compare drivers at specific locations
"""

from typing import Dict, Tuple, Optional, List
import numpy as np
import polars as pl
from f1_replay.data_loader.data_models import SessionData, CircuitData


class TelemetryConsolidator:
    """Consolidate and analyze telemetry from multiple drivers."""

    def __init__(self, session_data: SessionData, circuit_data: CircuitData):
        """
        Initialize consolidator.

        Args:
            session_data: SessionData with telemetry for all drivers
            circuit_data: CircuitData with track geometry
        """
        self.session_data = session_data
        self.circuit_data = circuit_data
        self.track = circuit_data.circuit.track
        self.pit_lane = circuit_data.circuit.pit_lane

    def consolidate_telemetry(
        self,
        sample_every_n_points: int = 1,
        distance_threshold: float = 50.0
    ) -> pl.DataFrame:
        """
        Consolidate all driver telemetries into a single dataframe.

        Uses distance along track as the primary index. Each driver becomes
        columns: {driver}_speed, {driver}_throttle, {driver}_brake, etc.
        Adds location tracking: {driver}_on_track boolean column.

        Args:
            sample_every_n_points: Sample every Nth telemetry point (for performance)
            distance_threshold: Distance in meters to pit lane to mark as pit (default 50m)

        Returns:
            Polars DataFrame with structure:
            - Distance: float (distance along track in meters)
            - {driver}_Speed: int (km/h)
            - {driver}_Throttle: int (0-100)
            - {driver}_Brake: int (0-100)
            - {driver}_OnTrack: bool (True if on track, False if in pit)
            - {driver}_SessionSeconds: float
            - ... other columns per driver
        """
        if not self.session_data.telemetry:
            raise ValueError("No telemetry data available in session")

        # Get all drivers
        drivers = sorted(self.session_data.telemetry.keys())

        # Process each driver's telemetry
        driver_data = {}
        for driver in drivers:
            tel = self.session_data.telemetry[driver]

            # Sample if requested
            if sample_every_n_points > 1:
                tel = tel[::sample_every_n_points]

            # Add on-track detection
            tel = self._add_on_track_detection(tel, distance_threshold)
            driver_data[driver] = tel

        # Find common distance range
        all_distances = []
        for tel in driver_data.values():
            if "Distance" in tel.columns:
                all_distances.extend(tel["Distance"].to_list())

        if not all_distances:
            raise ValueError("No distance data in telemetry")

        # Create distance index (every meter)
        min_dist = 0
        max_dist = max(all_distances)
        distance_index = np.arange(min_dist, max_dist + 1, 1.0)

        # Interpolate each driver to the common distance index
        consolidated_data = {"Distance": distance_index}

        for driver in drivers:
            tel = driver_data[driver]
            if "Distance" not in tel.columns:
                continue

            # Extract key columns
            for col in ["Speed", "Throttle", "Brake", "DRS", "Gear", "RPM"]:
                if col in tel.columns:
                    interpolated = self._interpolate_to_distance(
                        tel, col, distance_index
                    )
                    consolidated_data[f"{driver}_{col}"] = interpolated

            # Add on-track status
            if "OnTrack" in tel.columns:
                on_track = self._interpolate_to_distance(
                    tel, "OnTrack", distance_index, method="nearest"
                )
                consolidated_data[f"{driver}_OnTrack"] = on_track

            # Add session time for reference
            if "SessionSeconds" in tel.columns:
                session_seconds = self._interpolate_to_distance(
                    tel, "SessionSeconds", distance_index
                )
                consolidated_data[f"{driver}_SessionSeconds"] = session_seconds

        return pl.DataFrame(consolidated_data)

    def get_pit_stops(self, driver: str) -> list[Tuple[float, float]]:
        """
        Identify pit stops for a driver.

        Args:
            driver: Driver code (e.g., "VER")

        Returns:
            List of (entry_distance, exit_distance) tuples
        """
        if driver not in self.session_data.telemetry:
            return []

        tel = self.session_data.telemetry[driver]
        if "OnTrack" not in tel.columns:
            tel = self._add_on_track_detection(tel)

        on_track = tel["OnTrack"].to_list()
        distance = tel["Distance"].to_list() if "Distance" in tel.columns else None

        if distance is None:
            return []

        pit_stops = []
        in_pit = False
        pit_entry_idx = None

        for i, is_on_track in enumerate(on_track):
            if not is_on_track and not in_pit:
                # Entering pit
                in_pit = True
                pit_entry_idx = i
            elif is_on_track and in_pit:
                # Exiting pit
                in_pit = False
                if pit_entry_idx is not None:
                    pit_stops.append((distance[pit_entry_idx], distance[i]))

        return pit_stops

    def compare_drivers_at_distance(
        self,
        distance: float,
        drivers: Optional[list[str]] = None,
        window: float = 100.0
    ) -> Dict[str, Dict]:
        """
        Compare drivers' telemetry at a specific distance along track.

        Args:
            distance: Distance along track in meters
            drivers: List of drivers to compare (default: all)
            window: Distance window around the target (default: 100m)

        Returns:
            Dict with driver data at that distance
        """
        if drivers is None:
            drivers = sorted(self.session_data.telemetry.keys())

        result = {}
        for driver in drivers:
            if driver not in self.session_data.telemetry:
                continue

            tel = self.session_data.telemetry[driver]
            if "Distance" not in tel.columns:
                continue

            # Find nearest points within window
            mask = tel["Distance"].is_between(distance - window / 2, distance + window / 2)
            window_data = tel.filter(mask)

            if len(window_data) > 0:
                # Get data closest to the target distance
                idx = min(
                    range(len(window_data)),
                    key=lambda i: abs(window_data["Distance"][i] - distance)
                )

                row = window_data.row(idx, named=True)
                result[driver] = {
                    "Distance": row.get("Distance", distance),
                    "Speed": row.get("Speed", None),
                    "Throttle": row.get("Throttle", None),
                    "Brake": row.get("Brake", None),
                    "OnTrack": row.get("OnTrack", None),
                    "SessionSeconds": row.get("SessionSeconds", None),
                }

        return result

    def get_standings_at_distance(
        self,
        distance: float,
        drivers: Optional[list[str]] = None
    ) -> List[Tuple[int, str, float]]:
        """
        Calculate race standings (position) at a specific distance along track.

        At any point in the race, determines which drivers are ahead based on:
        1. Furthest distance traveled on current lap
        2. Lap number (more laps ahead = better)

        Args:
            distance: Reference distance (e.g., 1000m means standings after 1000m of track)
            drivers: List of drivers to include (default: all)

        Returns:
            List of (position, driver, gap_to_leader) sorted by position
        """
        if drivers is None:
            drivers = sorted(self.session_data.telemetry.keys())

        driver_progress = {}

        for driver in drivers:
            if driver not in self.session_data.telemetry:
                continue

            tel = self.session_data.telemetry[driver]
            if "Distance" not in tel.columns or "LapNumber" not in tel.columns:
                continue

            # Find telemetry point closest to the reference distance
            mask = tel["Distance"] <= distance
            if mask.sum() == 0:
                continue

            filtered = tel.filter(mask)
            if len(filtered) == 0:
                continue

            # Get the last (furthest) point at or before this distance
            last_idx = len(filtered) - 1
            row = filtered.row(last_idx, named=True)

            lap_number = row.get("LapNumber", 0)
            actual_distance = row.get("Distance", 0.0)

            # Store as (lap_number, distance_on_this_lap, driver)
            # Higher lap number is better, then higher distance
            driver_progress[driver] = (
                lap_number,
                actual_distance,
                row.get("SessionSeconds", 0.0)
            )

        # Sort by lap number (descending), then distance (descending)
        standings = sorted(
            driver_progress.items(),
            key=lambda x: (x[1][0], x[1][1]),
            reverse=True
        )

        # Calculate gaps
        if standings:
            leader_laps, leader_distance, _ = standings[0][1]
            leader_distance_at_lap = leader_distance

            result = []
            for position, (driver, (lap_num, dist, session_sec)) in enumerate(standings, 1):
                # Gap calculation
                if lap_num < leader_laps:
                    # If behind in laps, calculate gap as negative
                    gap = -(leader_laps - lap_num) * 1000.0  # Rough lap length proxy
                else:
                    # Same lap: gap in meters
                    gap = leader_distance_at_lap - dist

                result.append((position, driver, gap))

            return result

        return []

    def get_standings_at_lap(self, lap_number: float) -> List[Tuple[int, str, float]]:
        """
        Calculate race standings at completion of a specific lap.

        Args:
            lap_number: Which lap to calculate standings for (e.g., 10.5 = halfway through lap 11)

        Returns:
            List of (position, driver, gap_to_leader) sorted by position
        """
        driver_progress = {}

        for driver in sorted(self.session_data.telemetry.keys()):
            tel = self.session_data.telemetry[driver]
            if "LapNumber" not in tel.columns or "Distance" not in tel.columns:
                continue

            # Find telemetry at the specified lap
            mask = tel["LapNumber"] <= lap_number
            if mask.sum() == 0:
                continue

            filtered = tel.filter(mask)
            if len(filtered) == 0:
                continue

            # Get the last point at or before this lap
            last_idx = len(filtered) - 1
            row = filtered.row(last_idx, named=True)

            actual_lap = row.get("LapNumber", 0)
            distance = row.get("Distance", 0.0)

            driver_progress[driver] = (actual_lap, distance)

        # Sort by lap (descending), then distance (descending)
        standings = sorted(
            driver_progress.items(),
            key=lambda x: (x[1][0], x[1][1]),
            reverse=True
        )

        # Calculate gaps to leader
        if standings:
            leader_lap, leader_distance = standings[0][1]

            result = []
            for position, (driver, (lap_num, dist)) in enumerate(standings, 1):
                if lap_num < leader_lap:
                    gap = -(leader_lap - lap_num) * 1000.0
                else:
                    gap = leader_distance - dist

                result.append((position, driver, gap))

            return result

        return []

    def get_position_interpolation(
        self,
        sample_interval: float = 100.0
    ) -> pl.DataFrame:
        """
        Get smoothly interpolated x,y positions for all drivers at distance intervals.

        Perfect for animation/visualization: shows where each driver was at any point
        along the track, allowing smooth playback of the race.

        Args:
            sample_interval: Sample positions every N meters (default: 100m)

        Returns:
            Polars DataFrame with columns:
            - Distance: meters along track
            - {driver}_X: x coordinate
            - {driver}_Y: y coordinate
            - {driver}_OnTrack: boolean
            - {driver}_Speed: speed at this distance
            - {driver}_LapNumber: which lap
        """
        # Get distance range
        all_distances = []
        for tel in self.session_data.telemetry.values():
            if "Distance" in tel.columns:
                all_distances.extend(tel["Distance"].to_list())

        if not all_distances:
            raise ValueError("No distance data available")

        max_distance = max(all_distances)
        distance_samples = np.arange(0, max_distance + 1, sample_interval)

        # Build consolidated position data
        position_data = {"Distance": distance_samples}

        for driver in sorted(self.session_data.telemetry.keys()):
            tel = self.session_data.telemetry[driver]

            # X, Y interpolation
            if "X" in tel.columns and "Y" in tel.columns:
                x_list = tel["X"].to_list()
                y_list = tel["Y"].to_list()
                distances = tel["Distance"].to_list()

                # Interpolate X
                x_interp = np.interp(
                    distance_samples, distances, x_list,
                    left=np.nan, right=np.nan
                )
                position_data[f"{driver}_X"] = x_interp

                # Interpolate Y
                y_interp = np.interp(
                    distance_samples, distances, y_list,
                    left=np.nan, right=np.nan
                )
                position_data[f"{driver}_Y"] = y_interp

            # Speed
            if "Speed" in tel.columns:
                speed_list = tel["Speed"].to_list()
                distances = tel["Distance"].to_list()

                speed_interp = np.interp(
                    distance_samples, distances, speed_list,
                    left=np.nan, right=np.nan
                )
                position_data[f"{driver}_Speed"] = speed_interp.astype(int)

            # Lap number (nearest, not interpolated)
            if "LapNumber" in tel.columns:
                lap_list = tel["LapNumber"].to_list()
                distances = tel["Distance"].to_list()

                lap_nearest = []
                for d in distance_samples:
                    idx = np.argmin(np.abs(np.array(distances) - d))
                    lap_nearest.append(int(lap_list[idx]))

                position_data[f"{driver}_LapNumber"] = lap_nearest

            # OnTrack status (nearest)
            if "OnTrack" in tel.columns:
                on_track_list = tel["OnTrack"].to_list()
                distances = tel["Distance"].to_list()

                on_track_nearest = []
                for d in distance_samples:
                    idx = np.argmin(np.abs(np.array(distances) - d))
                    on_track_nearest.append(bool(on_track_list[idx]))

                position_data[f"{driver}_OnTrack"] = on_track_nearest

        return pl.DataFrame(position_data)

    def get_race_timeline(
        self,
        sample_every_n_laps: float = 1.0
    ) -> Dict[str, List[Tuple[int, str, float]]]:
        """
        Get race standings at each lap interval.

        Returns a dictionary where each key is a lap number, and value is the standings
        at that lap (list of (position, driver, gap) tuples).

        Args:
            sample_every_n_laps: Sample standings every N laps (default: 1.0 = every lap)

        Returns:
            Dict mapping lap number -> standings list
        """
        # Find max lap
        max_lap = 0
        for tel in self.session_data.telemetry.values():
            if "LapNumber" in tel.columns:
                max_lap = max(max_lap, int(tel["LapNumber"].max()))

        if max_lap == 0:
            return {}

        timeline = {}
        lap = sample_every_n_laps

        while lap <= max_lap:
            standings = self.get_standings_at_lap(lap)
            if standings:
                timeline[lap] = standings
            lap += sample_every_n_laps

        return timeline

    def _add_on_track_detection(
        self,
        telemetry: pl.DataFrame,
        distance_threshold: float = 50.0
    ) -> pl.DataFrame:
        """
        Add OnTrack column using track/pit geometry.

        Args:
            telemetry: Driver telemetry dataframe
            distance_threshold: Distance to pit lane boundary (meters)

        Returns:
            Telemetry with OnTrack column added
        """
        if "X" not in telemetry.columns or "Y" not in telemetry.columns:
            # Fallback: use speed threshold (pit lane speed < 50 km/h for extended periods)
            return self._add_on_track_by_speed(telemetry)

        # Calculate minimum distance to pit lane
        pit_coords = np.column_stack([self.pit_lane.x, self.pit_lane.y])
        track_coords = np.column_stack([self.track.x, self.track.y])

        on_track_list = []
        x_list = telemetry["X"].to_list()
        y_list = telemetry["Y"].to_list()

        for x, y in zip(x_list, y_list):
            pos = np.array([x, y])

            # Distance to pit lane
            pit_dist = np.min(np.linalg.norm(pit_coords - pos, axis=1))

            # Distance to track
            track_dist = np.min(np.linalg.norm(track_coords - pos, axis=1))

            # If closer to pit lane and within threshold, mark as pit
            on_track = track_dist <= pit_dist or pit_dist > distance_threshold

            on_track_list.append(on_track)

        return telemetry.with_columns(
            pl.Series("OnTrack", on_track_list, dtype=pl.Boolean)
        )

    def _add_on_track_by_speed(self, telemetry: pl.DataFrame) -> pl.DataFrame:
        """
        Fallback: detect pit lane by speed threshold.

        Drivers in pit lane typically: slow down, low speed for extended time, high brake.
        """
        if "Speed" not in telemetry.columns:
            return telemetry.with_columns(
                pl.Series("OnTrack", [True] * len(telemetry), dtype=pl.Boolean)
            )

        speed = telemetry["Speed"].to_list()
        on_track_list = []

        for i, s in enumerate(speed):
            # Speed < 60 km/h indicates pit lane
            # But check adjacent points to avoid momentary slow zones
            is_slow = s < 60

            if is_slow and i > 0 and i < len(speed) - 1:
                is_slow = speed[i - 1] < 80 and speed[i + 1] < 80

            on_track_list.append(not is_slow)

        return telemetry.with_columns(
            pl.Series("OnTrack", on_track_list, dtype=pl.Boolean)
        )

    def _interpolate_to_distance(
        self,
        telemetry: pl.DataFrame,
        column: str,
        distance_index: np.ndarray,
        method: str = "linear"
    ) -> np.ndarray:
        """
        Interpolate telemetry values to a distance index.

        Args:
            telemetry: Driver telemetry
            column: Column to interpolate
            distance_index: Target distance values
            method: "linear" or "nearest"

        Returns:
            Interpolated values as numpy array
        """
        if "Distance" not in telemetry.columns or column not in telemetry.columns:
            return np.full(len(distance_index), np.nan)

        x = telemetry["Distance"].to_numpy()
        y = telemetry[column].to_numpy()

        # Convert boolean to float for interpolation
        if telemetry[column].dtype == pl.Boolean:
            y = y.astype(float)
            method = "nearest"

        if method == "nearest":
            # Nearest neighbor interpolation
            result = np.full(len(distance_index), np.nan)
            for i, d in enumerate(distance_index):
                idx = np.argmin(np.abs(x - d))
                if not np.isnan(x[idx]) and not np.isnan(y[idx]):
                    result[i] = y[idx]
            return result
        else:
            # Linear interpolation
            result = np.interp(
                distance_index, x, y,
                left=np.nan, right=np.nan
            )
            return result
