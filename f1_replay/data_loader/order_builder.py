"""
Order Builder - Tracks driver positions throughout session

Calculates driver progress using: lap * circuit_length + distance
Filters to only include time steps where the order changed.
"""

from typing import Dict, List, Tuple, Optional, TYPE_CHECKING
import polars as pl

if TYPE_CHECKING:
    from f1_replay.data_loader.data_models import SessionData


class OrderBuilder:
    """Build driver position order dataset from telemetry."""

    @staticmethod
    def add_progress_to_telemetry(telemetry: Dict[str, pl.DataFrame],
                                  circuit_length: float) -> Dict[str, pl.DataFrame]:
        """
        Add progress column to all driver telemetry.

        Progress = (LapNumber - 1) * circuit_length + Distance

        Args:
            telemetry: Dict mapping driver code -> telemetry DataFrame
            circuit_length: Track length in meters

        Returns:
            Dict of driver code -> telemetry DataFrame with progress column added
        """
        result = {}

        for driver, tel in telemetry.items():
            if "LapNumber" in tel.columns and "Distance" in tel.columns:
                # Calculate progress for this driver
                progress = (tel["LapNumber"] - 1) * circuit_length + tel["Distance"]
                tel_with_progress = tel.with_columns([
                    progress.alias("progress")
                ])
                result[driver] = tel_with_progress
            else:
                result[driver] = tel

        return result

    @staticmethod
    def build_order(telemetry: Dict[str, pl.DataFrame],
                   circuit_length: float) -> pl.DataFrame:
        """
        Build order dataset from telemetry.

        One row per time step. Each driver gets two columns: {driver}_progress and {driver}_position.

        Args:
            telemetry: Dict mapping driver code -> telemetry DataFrame
            circuit_length: Track length in meters

        Returns:
            Polars DataFrame with columns: session_time, VER_progress, VER_position, HAM_progress, HAM_position, etc.
        """
        if not telemetry or circuit_length <= 0:
            return pl.DataFrame()

        # Collect telemetry for all drivers with required columns
        driver_dfs = {}
        driver_list = []

        for driver, tel in telemetry.items():
            if "session_time" not in tel.columns or "LapNumber" not in tel.columns or "Distance" not in tel.columns:
                continue

            driver_list.append(driver)

            # Calculate progress for this driver
            df = tel.select(["session_time", "LapNumber", "Distance"]).with_columns([
                ((pl.col("LapNumber") - 1) * circuit_length + pl.col("Distance")).alias(f"{driver}_progress")
            ]).select(["session_time", f"{driver}_progress"])

            driver_dfs[driver] = df

        if not driver_dfs:
            return pl.DataFrame()

        # Create a single combined dataframe with all unique session times
        all_times = pl.concat([
            driver_dfs[driver].select("session_time").unique()
            for driver in driver_list
        ]).unique().sort("session_time")

        # Join each driver's progress to the combined times
        result = all_times
        for driver in driver_list:
            result = result.join(
                driver_dfs[driver],
                on="session_time",
                how="left"
            )

        # Forward-fill progress values (each driver keeps their last known progress)
        for driver in driver_list:
            result = result.with_columns([
                pl.col(f"{driver}_progress").forward_fill()
            ])

        # Calculate positions for each time step using row-wise operations
        # Create a list of position columns
        for driver in driver_list:
            # For each driver, calculate their position based on progress
            # This requires comparing their progress to all other drivers
            position_expr = 1 + pl.sum_horizontal([
                (pl.col(f"{other}_progress") > pl.col(f"{driver}_progress")).cast(pl.UInt8)
                for other in driver_list
                if other != driver
            ])

            # Only assign position if the driver has progress data
            result = result.with_columns([
                pl.when(pl.col(f"{driver}_progress").is_not_null())
                .then(position_expr)
                .otherwise(None)
                .alias(f"{driver}_position")
            ])

        # Filter to only rows where order changed
        result = OrderBuilder._filter_order_changes(result, driver_list)

        # Keep both progress and position columns for QC
        # Organize columns: session_time, then all progress columns, then all position columns
        progress_cols = [f"{driver}_progress" for driver in driver_list]
        position_cols = [f"{driver}_position" for driver in driver_list]
        ordered_cols = ["session_time"] + progress_cols + position_cols

        result = result.select(ordered_cols)

        return result

    @staticmethod
    def _filter_order_changes(df: pl.DataFrame, driver_list: List[str]) -> pl.DataFrame:
        """
        Filter to only rows where the order changed.

        Ensures one row per unique session_time, checking if order changed from previous time.
        This handles cases where multiple drivers have data at the same session_time.

        Args:
            df: DataFrame with session_time and position columns
            driver_list: List of driver codes

        Returns:
            Filtered DataFrame with only rows where order changed (one row per unique session_time)
        """
        if len(df) == 0:
            return df

        # Create position columns list
        position_cols = [f"{driver}_position" for driver in driver_list]

        # Step 1: Deduplicate by session_time - keep last row for each unique session_time
        # This ensures exactly one row per session_time with the final order at that time
        df_dedup = df.with_row_index("_row_idx").group_by(
            "session_time"
        ).agg(
            pl.col("_row_idx").max().alias("_row_idx")
        ).join(
            df.with_row_index("_row_idx"),
            on=["session_time", "_row_idx"],
            how="left"
        ).drop("_row_idx").sort("session_time")

        # Step 2: Filter to only rows where order changed
        if len(df_dedup) == 0:
            return df_dedup

        df_dicts = df_dedup.select(position_cols).to_dicts()

        # Always keep the first entry (session start)
        keep_indices = [0]

        # Compare each time step with the previous
        for i in range(1, len(df_dicts)):
            current_positions = df_dicts[i]
            previous_positions = df_dicts[i - 1]

            # Check if any position changed
            order_changed = any(
                current_positions.get(col) != previous_positions.get(col)
                for col in position_cols
            )

            if order_changed:
                keep_indices.append(i)

        # Select only rows where order changed
        result = df_dedup[keep_indices]

        return result

    @staticmethod
    def get_standings_at_time(order_df: pl.DataFrame, session_time: float) -> List[Tuple[int, str]]:
        """
        Get driver standings at a specific time.

        Args:
            order_df: Order DataFrame from build_order()
            session_time: Time in seconds since session start

        Returns:
            List of (position, driver) tuples in order
        """
        if len(order_df) == 0:
            return []

        # Get the latest order at or before this time
        valid_orders = order_df.filter(pl.col("session_time") <= session_time)

        if len(valid_orders) == 0:
            return []

        # Get the last time an order was recorded
        latest_time = valid_orders["session_time"].max()
        latest_order = valid_orders.filter(pl.col("session_time") == latest_time)

        return [(row["position"], row["driver"]) for row in latest_order.to_dicts()]

    @staticmethod
    def get_driver_ahead(order_df: pl.DataFrame, session_time: float, driver: str) -> Optional[Tuple[int, str]]:
        """
        Get the driver ahead of a given driver at a specific time.

        Args:
            order_df: Order DataFrame from build_order()
            session_time: Time in seconds since session start
            driver: Driver code

        Returns:
            Tuple of (position_ahead, driver_code) or None if driver is P1
        """
        if len(order_df) == 0:
            return None

        # Find the order state at or before this time
        valid_orders = order_df.filter(pl.col("session_time") <= session_time)
        if len(valid_orders) == 0:
            return None

        # Get the last order state before this time
        latest_time = valid_orders["session_time"].max()
        latest_order = valid_orders.filter(pl.col("session_time") == latest_time)

        if len(latest_order) == 0:
            return None

        row = latest_order.to_dicts()[0]
        driver_position = row.get(f"{driver}_position")

        if driver_position is None or driver_position <= 1:
            return None  # Already in P1

        # Find driver with position one place ahead
        target_position = driver_position - 1
        for col, val in row.items():
            if col.endswith("_position") and val == target_position:
                driver_ahead = col.replace("_position", "")
                return (target_position, driver_ahead)

        return None

    @staticmethod
    def _calculateIntervalTime(telemetry_dict: Dict[str, pl.DataFrame],
                               driver_ahead: str,
                               target_distance: float) -> Optional[float]:
        """
        Calculate session_time when driver ahead was at target distance.

        Uses linear interpolation to find exact time at target distance.

        Args:
            telemetry_dict: Dict of driver code -> telemetry DataFrame
            driver_ahead: Driver code
            target_distance: Distance to find (meters)

        Returns:
            session_time when driver_ahead was at target_distance, or None
        """
        if driver_ahead not in telemetry_dict:
            return None

        tel = telemetry_dict[driver_ahead]

        if "Distance" not in tel.columns or "session_time" not in tel.columns:
            return None

        distances = tel["Distance"].to_list()
        times = tel["session_time"].to_list()

        # Find where target distance falls
        for i in range(len(distances) - 1):
            d1, d2 = float(distances[i]), float(distances[i + 1])
            t1, t2 = float(times[i]), float(times[i + 1])

            # Check if target is between these two points
            if (d1 <= target_distance <= d2) or (d2 <= target_distance <= d1):
                # Linear interpolation
                if d2 != d1:
                    ratio = (target_distance - d1) / (d2 - d1)
                    interpolated_time = t1 + ratio * (t2 - t1)
                    return interpolated_time
                else:
                    return t1

        return None

    @staticmethod
    def _build_position_lookup(order_df: pl.DataFrame) -> Dict[float, Dict[str, int]]:
        """
        Build a position lookup table: time -> {driver: position}.

        Allows O(1) lookup of driver positions at any recorded time.

        Args:
            order_df: Order DataFrame from build_order()

        Returns:
            Dict mapping session_time to {driver_code: position}
        """
        lookup = {}

        for row in order_df.to_dicts():
            session_time = float(row["session_time"])
            positions = {}

            # Extract positions from row
            for col, val in row.items():
                if col.endswith("_position") and val is not None:
                    driver = col.replace("_position", "")
                    positions[driver] = int(val)

            lookup[session_time] = positions

        return lookup

    @staticmethod
    def _get_driver_ahead_at_time(position_lookup: Dict[float, Dict[str, int]],
                                  session_time: float,
                                  driver: str) -> Optional[str]:
        """
        Get driver ahead at a specific time using cached lookup.

        Args:
            position_lookup: Pre-built position lookup
            session_time: Session time
            driver: Driver code

        Returns:
            Driver code of driver ahead, or None if in P1
        """
        # Find the closest time at or before session_time
        valid_times = [t for t in position_lookup.keys() if t <= session_time]
        if not valid_times:
            return None

        latest_time = max(valid_times)
        positions = position_lookup[latest_time]

        driver_pos = positions.get(driver)
        if driver_pos is None or driver_pos <= 1:
            return None

        # Find driver with position one ahead
        target_pos = driver_pos - 1
        for drv, pos in positions.items():
            if pos == target_pos:
                return drv

        return None

    @staticmethod
    def calculate_time_to_driver_ahead(order_df: pl.DataFrame,
                                       telemetry_dict: Dict[str, pl.DataFrame]) -> Dict[str, pl.DataFrame]:
        """
        Calculate TimeToDriverAhead for all drivers at all timesteps.

        TimeToDriverAhead represents the time gap to the driver in the position ahead,
        calculated as: (current_driver_time_at_progress) - (driver_ahead_time_at_progress).
        Uses progress column from telemetry (which must be present).
        Positive values indicate behind, negative would indicate ahead.

        Note: This calculation can be slow (10-30s for 700k+ telemetry points).
        Use for analysis only, not in high-frequency processing loops.

        Args:
            order_df: Order DataFrame from build_order()
            telemetry_dict: Dict of driver code -> telemetry DataFrame (must contain 'progress' column)

        Returns:
            Dict of driver code -> telemetry DataFrame with TimeToDriverAhead column
        """
        import numpy as np

        # Pre-build lookup for fast position queries
        position_lookup = OrderBuilder._build_position_lookup(order_df)

        # Build progress-to-time mapping for each driver (for fast interpolation)
        progress_to_time_cache = {}
        for driver, tel in telemetry_dict.items():
            if "progress" in tel.columns and "session_time" in tel.columns:
                progress_list = tel["progress"].to_list()
                time_list = tel["session_time"].to_list()
                progress_to_time_cache[driver] = (np.array(progress_list), np.array(time_list))

        result = {}

        for driver, tel in telemetry_dict.items():
            if "progress" not in tel.columns:
                # No progress column, skip
                result[driver] = tel
                continue

            time_to_ahead = np.full(len(tel), np.nan, dtype=np.float64)

            progress_arr = tel["progress"].to_numpy()
            time_arr = tel["session_time"].to_numpy()

            for i in range(len(tel)):
                session_time = float(time_arr[i])
                progress = float(progress_arr[i])

                if np.isnan(progress):
                    continue

                # Find driver ahead using cached lookup
                driver_ahead = OrderBuilder._get_driver_ahead_at_time(position_lookup, session_time, driver)

                if driver_ahead is None:
                    continue

                if driver_ahead not in progress_to_time_cache:
                    continue

                # Interpolate using numpy arrays (faster)
                ahead_progress, ahead_times = progress_to_time_cache[driver_ahead]
                time_ahead = OrderBuilder._interpolate_numpy(ahead_progress, ahead_times, progress)

                if time_ahead is not None:
                    time_to_ahead[i] = session_time - time_ahead

            # Add TimeToDriverAhead column to telemetry
            tel_with_interval = tel.with_columns([
                pl.Series("TimeToDriverAhead", time_to_ahead, dtype=pl.Float64)
            ])
            result[driver] = tel_with_interval

        return result

    @staticmethod
    def _interpolate_numpy(x_arr, y_arr, x_target: float) -> Optional[float]:
        """
        Fast numpy-based interpolation.

        Args:
            x_arr: X values (progress)
            y_arr: Y values (time)
            x_target: Target X value

        Returns:
            Interpolated Y value or None
        """
        import numpy as np

        # Find indices where x_arr is closest to x_target
        idx = np.searchsorted(x_arr, x_target)

        if idx == 0:
            if len(x_arr) > 0 and x_arr[0] == x_target:
                return float(y_arr[0])
            return None

        if idx == len(x_arr):
            if x_arr[-1] == x_target:
                return float(y_arr[-1])
            return None

        # Interpolate between idx-1 and idx
        x1, x2 = x_arr[idx - 1], x_arr[idx]
        y1, y2 = y_arr[idx - 1], y_arr[idx]

        if x1 == x2:
            return float(y1)

        # Linear interpolation
        ratio = (x_target - x1) / (x2 - x1)
        return float(y1 + ratio * (y2 - y1))

    @staticmethod
    def _interpolate_time_at_distance(dist_time_pairs: List[Tuple[float, float]],
                                      target_distance: float) -> Optional[float]:
        """
        Interpolate time at a target distance using cached distance-time pairs.

        Args:
            dist_time_pairs: List of (distance, time) tuples
            target_distance: Target distance

        Returns:
            Interpolated session_time, or None if not found
        """
        for i in range(len(dist_time_pairs) - 1):
            d1, t1 = dist_time_pairs[i]
            d2, t2 = dist_time_pairs[i + 1]

            # Check if target falls between these points
            if (d1 <= target_distance <= d2) or (d2 <= target_distance <= d1):
                if d2 != d1:
                    ratio = (target_distance - d1) / (d2 - d1)
                    return t1 + ratio * (t2 - t1)
                else:
                    return t1

        return None

    @staticmethod
    def replace_order(session_data: "SessionData", order_df: pl.DataFrame) -> "SessionData":
        """
        Create a new SessionData with updated order field.

        Args:
            session_data: Original SessionData
            order_df: Order DataFrame from build_order()

        Returns:
            New SessionData with order field set
        """
        from dataclasses import replace
        return replace(session_data, order=order_df)
