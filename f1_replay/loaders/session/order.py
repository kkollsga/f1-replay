"""
Order Builder - Adds position and interval columns to driver telemetry.

Position calculation:
- During race: rank by race_distance (highest = P1)
- Final positions: determined by finish order (first to finish = P1)
- Lapped finishers: ranked after all full-distance finishers

Interval calculation:
- For P1: interval = 0
- For P > 1: time gap to driver immediately ahead at same race_distance
"""

from typing import Dict, List, Tuple
import numpy as np
import polars as pl


class OrderBuilder:
    """Add position data to driver telemetry."""

    @staticmethod
    def add_positions_to_telemetry(telemetry: Dict[str, pl.DataFrame]) -> Dict[str, pl.DataFrame]:
        """
        Add position column to each driver's telemetry.

        Position calculation:
        - Extract finish order from finish times (who crossed first = P1)
        - Lapped finishers are ranked after full-distance finishers
        - Non-finished drivers: rank by race_distance + offset

        Args:
            telemetry: Dict mapping driver code -> telemetry DataFrame

        Returns:
            Dict of driver code -> telemetry DataFrame with position column added
        """
        if not telemetry:
            return telemetry

        # Collect drivers with valid data
        driver_list = []
        driver_dfs = {}

        for driver, tel in telemetry.items():
            if "session_time" not in tel.columns or "race_distance" not in tel.columns:
                continue
            driver_list.append(driver)

            cols = ["session_time", "race_distance"]
            renames = {"race_distance": f"{driver}_dist"}
            if "race_status" in tel.columns:
                cols.append("race_status")
                renames["race_status"] = f"{driver}_status"
            if "lap_number" in tel.columns:
                cols.append("lap_number")
                renames["lap_number"] = f"{driver}_lap"

            driver_dfs[driver] = tel.select(cols).rename(renames)

        if len(driver_list) < 2:
            result = {}
            for driver, tel in telemetry.items():
                result[driver] = tel.with_columns(pl.lit(1).cast(pl.UInt8).alias("position"))
            return result

        # Determine finish order from telemetry
        # (max_lap, finish_time) - higher lap wins, then earlier time wins
        finish_info = {}  # driver -> (max_lap, finish_time, is_finished)
        for driver, tel in telemetry.items():
            if "race_status" not in tel.columns:
                continue
            finished_rows = tel.filter(tel["race_status"] == "Finished")
            if len(finished_rows) > 0:
                first = finished_rows.head(1).to_dicts()[0]
                max_lap = first.get("lap_number", 0)
                finish_time = first.get("session_time", float("inf"))
                finish_info[driver] = (max_lap, finish_time, True)
            else:
                # Check if retired
                retired_rows = tel.filter(tel["race_status"] == "Retired")
                if len(retired_rows) > 0:
                    first = retired_rows.head(1).to_dicts()[0]
                    max_lap = first.get("lap_number", 0)
                    max_dist = tel["race_distance"].max()
                    finish_info[driver] = (max_lap, float("inf"), False, max_dist)

        # Sort finishers: by (max_lap DESC, finish_time ASC)
        # This puts full-distance finishers before lapped finishers
        finished_drivers = [(d, lap, t) for d, (lap, t, fin, *_) in finish_info.items() if fin]
        finished_drivers.sort(key=lambda x: (-x[1], x[2]))  # Higher lap first, then earlier time
        finish_position = {d: i + 1 for i, (d, _, _) in enumerate(finished_drivers)}

        # Build unified timeline
        all_times = pl.concat([
            df.select("session_time") for df in driver_dfs.values()
        ]).unique().sort("session_time")

        unified = all_times
        for driver in driver_list:
            unified = unified.join(driver_dfs[driver], on="session_time", how="left")

        # Forward-fill
        for driver in driver_list:
            unified = unified.with_columns(pl.col(f"{driver}_dist").forward_fill())
            if f"{driver}_status" in unified.columns:
                unified = unified.with_columns(pl.col(f"{driver}_status").forward_fill())
            if f"{driver}_lap" in unified.columns:
                unified = unified.with_columns(pl.col(f"{driver}_lap").forward_fill())

        # Add is_finished flag
        for driver in driver_list:
            if f"{driver}_status" in unified.columns:
                unified = unified.with_columns(
                    (pl.col(f"{driver}_status") == "Finished").alias(f"{driver}_fin")
                )
            else:
                unified = unified.with_columns(pl.lit(False).alias(f"{driver}_fin"))

        # Count finished drivers at each timestep
        unified = unified.with_columns(
            pl.sum_horizontal([pl.col(f"{d}_fin").cast(pl.UInt8) for d in driver_list]).alias("n_finished")
        )

        # Calculate position for each driver
        for driver in driver_list:
            # Rank among non-finished drivers (1 = highest race_distance)
            rank_among_non_finished = 1 + pl.sum_horizontal([
                ((~pl.col(f"{other}_fin")) &
                 (pl.col(f"{other}_dist") > pl.col(f"{driver}_dist"))).cast(pl.UInt8)
                for other in driver_list if other != driver
            ])

            if driver in finish_position:
                # Driver finished - use finish order position when finished
                final_pos = finish_position[driver]
                unified = unified.with_columns(
                    pl.when(pl.col(f"{driver}_dist").is_null())
                    .then(None)
                    .when(pl.col(f"{driver}_fin"))
                    .then(pl.lit(final_pos))
                    .otherwise(pl.col("n_finished") + rank_among_non_finished)
                    .cast(pl.UInt8)
                    .alias(f"{driver}_pos")
                )
            else:
                # Driver didn't finish - always rank by race_distance
                unified = unified.with_columns(
                    pl.when(pl.col(f"{driver}_dist").is_null())
                    .then(None)
                    .otherwise(pl.col("n_finished") + rank_among_non_finished)
                    .cast(pl.UInt8)
                    .alias(f"{driver}_pos")
                )

        # Join positions back to each driver's telemetry
        result = {}
        for driver, tel in telemetry.items():
            if driver in driver_list:
                pos_df = unified.select(["session_time", f"{driver}_pos"]).rename(
                    {f"{driver}_pos": "position"}
                )
                result[driver] = tel.join(pos_df, on="session_time", how="left")
            else:
                result[driver] = tel.with_columns(pl.lit(None).cast(pl.UInt8).alias("position"))

        return result

    @staticmethod
    def add_intervals_to_telemetry(telemetry: Dict[str, pl.DataFrame]) -> Dict[str, pl.DataFrame]:
        """
        Add interval column to each driver's telemetry using Polars lazy operations.

        Interval = time behind driver immediately ahead (at same race_distance).
        For P1: interval = 0
        For P > 1: interpolate when driver at P-1 passed same race_distance

        Args:
            telemetry: Dict mapping driver code -> telemetry DataFrame (with position column)

        Returns:
            Dict of driver code -> telemetry DataFrame with interval column added
        """
        if not telemetry:
            return telemetry

        drivers = list(telemetry.keys())
        required_cols = ["position", "race_distance", "session_time"]
        valid_drivers = [d for d in drivers
                         if all(c in telemetry[d].columns for c in required_cols)]

        if len(valid_drivers) < 2:
            return {d: tel.with_columns(pl.lit(0.0).alias("interval"))
                    for d, tel in telemetry.items()}

        # Map drivers to indices
        driver_to_idx = {d: i for i, d in enumerate(valid_drivers)}
        n_drivers = len(valid_drivers)
        max_pos = n_drivers + 5

        # Build interpolation lookup using Polars lazy (parallel preparation)
        # IMPORTANT: Only include racing data (lap_number >= 1) to exclude formation lap
        # Otherwise, race_distance values from formation lap pollute the interpolation
        driver_interp = {}
        interp_lazy = []
        for driver in valid_drivers:
            lf = (
                telemetry[driver].lazy()
                .filter(
                    pl.col("race_distance").is_not_null() &
                    (pl.col("race_distance") > 0) &
                    (pl.col("lap_number") >= 1)  # Only racing data, not formation lap
                )
                .select(["race_distance", "session_time"])
                .sort("race_distance")
                .unique(subset=["race_distance"], keep="first")
                .with_columns(pl.lit(driver).alias("_driver"))
            )
            interp_lazy.append(lf)

        # Collect all interpolation data in one pass
        all_interp = pl.concat(interp_lazy).collect()
        for driver in valid_drivers:
            driver_data = all_interp.filter(pl.col("_driver") == driver)
            if len(driver_data) > 0:
                driver_interp[driver_to_idx[driver]] = (
                    driver_data["race_distance"].to_numpy(),
                    driver_data["session_time"].to_numpy()
                )

        # Build unified timeline and position matrix using Polars lazy
        stacked_lazy = pl.concat([
            telemetry[d].lazy()
            .select(["session_time", "position"])
            .with_columns(pl.lit(driver_to_idx[d]).cast(pl.Int16).alias("driver_idx"))
            for d in valid_drivers
        ])

        # Get unified times
        unified_times = (
            stacked_lazy
            .select("session_time")
            .unique()
            .sort("session_time")
            .collect()
        )["session_time"].to_numpy()
        n_times = len(unified_times)

        # Build position matrix efficiently
        pos_to_driver = np.full((n_times, max_pos + 1), -1, dtype=np.int16)

        # Collect stacked data and populate matrix
        stacked = stacked_lazy.collect()
        stacked_times = stacked["session_time"].to_numpy()
        stacked_pos = stacked["position"].to_numpy()
        stacked_driver_idx = stacked["driver_idx"].to_numpy()

        # Vectorized time index lookup
        time_indices = np.searchsorted(unified_times, stacked_times, side='right') - 1
        time_indices = np.clip(time_indices, 0, n_times - 1)

        # Vectorized position matrix population (avoiding Python loop)
        valid_mask = ~np.isnan(stacked_pos) & (stacked_pos >= 1) & (stacked_pos <= max_pos)
        valid_time_idx = time_indices[valid_mask]
        valid_pos = stacked_pos[valid_mask].astype(np.int32)
        valid_driver = stacked_driver_idx[valid_mask]
        pos_to_driver[valid_time_idx, valid_pos] = valid_driver

        # Forward fill using vectorized numpy operations
        for pos in range(1, max_pos + 1):
            col = pos_to_driver[:, pos]
            valid_mask = col != -1
            if not np.any(valid_mask):
                continue
            valid_idx = np.where(valid_mask, np.arange(n_times), -1)
            np.maximum.accumulate(valid_idx, out=valid_idx)
            fill_mask = (col == -1) & (valid_idx >= 0)
            col[fill_mask] = col[valid_idx[fill_mask]]

        # Calculate intervals for all drivers using Polars + numpy hybrid
        result = {}
        for driver in valid_drivers:
            driver_idx = driver_to_idx[driver]
            tel = telemetry[driver]

            # Extract arrays once
            session_times = tel["session_time"].to_numpy()
            race_dists = tel["race_distance"].to_numpy()
            positions = tel["position"].to_numpy()
            n_rows = len(tel)

            intervals = np.zeros(n_rows, dtype=np.float64)

            # Vectorized time index lookup
            time_indices = np.searchsorted(unified_times, session_times, side='right') - 1
            time_indices = np.clip(time_indices, 0, n_times - 1)

            # Vectorized position and driver_ahead lookup
            valid_pos_mask = ~np.isnan(positions) & (positions > 1) & (positions <= max_pos)
            target_pos = np.where(valid_pos_mask, (positions - 1).astype(np.int32), 0)
            target_pos = np.clip(target_pos, 0, max_pos)
            drivers_ahead = pos_to_driver[time_indices, target_pos]

            valid_dist_mask = ~np.isnan(race_dists) & (race_dists > 0)
            process_mask = valid_pos_mask & valid_dist_mask

            # Vectorized interpolation per driver_ahead group
            for ahead_idx, (ahead_distances, ahead_times) in driver_interp.items():
                group_mask = (drivers_ahead == ahead_idx) & process_mask
                if not np.any(group_mask):
                    continue

                indices = np.where(group_mask)[0]
                dists = race_dists[indices]
                times = session_times[indices]

                in_range = (dists >= ahead_distances[0]) & (dists <= ahead_distances[-1])
                if not np.any(in_range):
                    continue

                valid_idx = indices[in_range]
                interp_times = np.interp(dists[in_range], ahead_distances, ahead_times)
                intervals[valid_idx] = times[in_range] - interp_times

            result[driver] = tel.with_columns(pl.Series("interval", intervals))

        # Handle invalid drivers
        for driver in drivers:
            if driver not in result:
                result[driver] = telemetry[driver].with_columns(
                    pl.lit(0.0).alias("interval")
                )

        return result

    @staticmethod
    def get_order_at_time(telemetry: Dict[str, pl.DataFrame], session_time: float) -> List[Tuple[int, str, float]]:
        """
        Get driver standings at a specific time.

        Args:
            telemetry: Dict of driver -> telemetry DataFrame (with position column)
            session_time: Time in seconds since session start

        Returns:
            List of (position, driver, race_distance) tuples sorted by position
        """
        standings = []

        for driver, tel in telemetry.items():
            if "session_time" not in tel.columns or "position" not in tel.columns:
                continue

            # Get latest data at or before session_time
            valid = tel.filter(pl.col("session_time") <= session_time)
            if len(valid) == 0:
                continue

            last_row = valid.tail(1).to_dicts()[0]
            pos = last_row.get("position")
            dist = last_row.get("race_distance", 0)

            if pos is not None:
                standings.append((int(pos), driver, float(dist) if dist else 0.0))

        return sorted(standings, key=lambda x: x[0])

    @staticmethod
    def get_order_at_lap(telemetry: Dict[str, pl.DataFrame], lap: int,
                         track_length: float) -> List[Tuple[int, str, float]]:
        """
        Get driver standings when they completed a specific lap.

        For drivers who completed the lap: order by who crossed first (lower session_time).
        For DNF drivers: order by their max race_distance.

        Args:
            telemetry: Dict of driver -> telemetry DataFrame
            lap: Lap number to check
            track_length: Track length in meters

        Returns:
            List of (position, driver, race_distance) tuples sorted by position
        """
        lap_end_distance = lap * track_length
        standings = []

        for driver, tel in telemetry.items():
            if "race_distance" not in tel.columns or "session_time" not in tel.columns:
                continue

            # Find when driver crossed lap completion distance
            completed = tel.filter(pl.col("race_distance") >= lap_end_distance)

            if len(completed) > 0:
                # Driver completed lap - use time they crossed
                first_cross = completed.head(1).to_dicts()[0]
                standings.append((
                    first_cross["session_time"],  # Sort key: time of crossing
                    driver,
                    float(first_cross["race_distance"]),
                    True  # completed
                ))
            else:
                # DNF - use max race_distance
                max_dist = tel["race_distance"].max()
                if max_dist is not None:
                    standings.append((
                        float('inf'),  # DNF sorts last
                        driver,
                        float(max_dist),
                        False  # did not complete
                    ))

        # Sort: completed drivers by crossing time, then DNF by distance (descending)
        completed = [(d, dist) for _, d, dist, c in standings if c]
        dnf = [(d, dist) for _, d, dist, c in standings if not c]

        completed.sort(key=lambda x: next(
            t for t, d, _, c in standings if d == x[0] and c
        ))
        dnf.sort(key=lambda x: -x[1])  # Higher distance = better position

        # Assign positions
        result = []
        pos = 1
        for driver, dist in completed:
            result.append((pos, driver, dist))
            pos += 1
        for driver, dist in dnf:
            result.append((pos, driver, dist))
            pos += 1

        return result
