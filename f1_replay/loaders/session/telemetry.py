"""
Telemetry Builder - Build driver telemetry from pos_data and car_data.

Uses position data as primary sampling source, compacts static positions,
and samples car data using nearest-neighbor matching.

Output columns (all lowercase/snake_case):
    session_time, status, x, y, z, rpm, speed, n_gear, throttle, brake, drs,
    lap_number, compound, tyre_life, track_distance, race_distance

Also extracts track and pit lane geometry from race winner's telemetry.
"""

from dataclasses import dataclass
from typing import Dict, Optional, Tuple
import numpy as np
import pandas as pd
import polars as pl


# Re-export for backwards compatibility
__all__ = ['TelemetryBuilder', 'TrackData']


@dataclass
class TrackData:
    """Track and pit lane geometry extracted from telemetry."""
    track_x: np.ndarray
    track_y: np.ndarray
    track_distance: np.ndarray  # Cumulative distance along track (decimeters)
    lap_distance: float  # Total track length (decimeters)
    pit_x: Optional[np.ndarray] = None
    pit_y: Optional[np.ndarray] = None
    pit_distance: Optional[np.ndarray] = None  # Cumulative distance along pit (meters)
    pit_length: float = 0.0  # Total pit lane length (meters)
    pit_entry_distance: Optional[float] = None  # Track distance at pit entry (meters)
    pit_exit_distance: Optional[float] = None   # Track distance at pit exit (meters)
    marshal_sectors: Optional[list] = None  # List of (sector_num, from_dist, to_dist) in meters
    corners: Optional[list] = None  # List of (number, distance_m, angle, letter)
    # Reference lap telemetry (from winner's fastest lap)
    speed: Optional[np.ndarray] = None  # km/h
    throttle: Optional[np.ndarray] = None  # 0-100%
    brake: Optional[np.ndarray] = None  # 0-100 (boolean in some cases)
    track_z: Optional[np.ndarray] = None  # Height/elevation (decimeters)


class TelemetryBuilder:
    """Build compacted telemetry from FastF1 pos_data and car_data."""

    @staticmethod
    def build_telemetry(f1_session, dnf_drivers: set = None, extract_track: bool = False) -> Tuple[Dict[str, pl.DataFrame], Optional[TrackData], Optional[dict], Dict[str, dict]]:
        """
        Build telemetry for all drivers from pos_data and car_data.

        Args:
            f1_session: FastF1 session with loaded data
            dnf_drivers: Set of driver abbreviations who retired (from results)
            extract_track: If True, extract track geometry (legacy mode for backward compatibility).
                          If False (default), skip track extraction - track comes from Weekend.pkl.

        Returns:
            Tuple of:
            - Dict mapping driver code to Polars DataFrame
            - TrackData with track and pit lane geometry (or None if extract_track=False)
            - Session timing dict with {warmup_start_time} (or None if extract_track=False)
            - status_data_all dict mapping driver -> {finish_time, pit_windows, is_dnf}
        """
        if dnf_drivers is None:
            dnf_drivers = set()
        telemetry = {}
        status_data_all = {}  # Collect status data per driver for deferred calculation

        pos_data = getattr(f1_session, 'pos_data', None)
        car_data = getattr(f1_session, 'car_data', None)
        laps = getattr(f1_session, 'laps', None)

        if pos_data is None or car_data is None:
            print("  ⚠ pos_data or car_data not available")
            return telemetry, None, None, status_data_all

        # Calculate race_length (max laps across all drivers)
        race_length = 0
        if laps is not None and len(laps) > 0 and 'LapNumber' in laps.columns:
            race_length = int(laps['LapNumber'].max())
            print(f"  → Race length: {race_length} laps")

        # Find race winner (P1)
        winner = TelemetryBuilder._get_race_winner(f1_session)

        # Build mapping from driver number to driver code
        driver_map = TelemetryBuilder._build_driver_map(f1_session)

        for driver_num, pos_df in pos_data.items():
            driver_code = driver_map.get(str(driver_num), str(driver_num))

            try:
                car_df = car_data.get(driver_num)
                if car_df is None or len(pos_df) == 0:
                    continue

                driver_laps = None
                if laps is not None and len(laps) > 0:
                    driver_laps = laps[laps['Driver'] == driver_code]

                is_dnf = driver_code in dnf_drivers
                driver_tel, status_data = TelemetryBuilder._build_driver_telemetry(
                    pos_df, car_df, driver_laps, race_length, is_dnf
                )

                if driver_tel is not None and len(driver_tel) > 0:
                    telemetry[driver_code] = driver_tel
                    status_data_all[driver_code] = status_data
                    print(f"    ✓ {driver_code}: {len(driver_tel)} points")

            except Exception as e:
                print(f"    ⚠ {driver_code}: {e}")

        # Extract track and pit lane geometry, then add track_distance
        # Only extract if explicitly requested (legacy mode for backward compatibility)
        track_data = None
        session_timing = None
        if extract_track and telemetry:
            track_data, session_timing = TelemetryBuilder._extract_track_and_pit(telemetry, winner, status_data_all)
            if track_data:
                # Add track_distance, race_distance, lap_number (from wrap detection)
                telemetry = TelemetryBuilder._add_track_distance_all(telemetry, track_data, session_timing)
                # Legacy mode: Status would be added here but is now handled by SessionProcessor

        return telemetry, track_data, session_timing, status_data_all

    @staticmethod
    def _get_race_winner(f1_session) -> Optional[str]:
        """Get race winner (P1) driver code from results."""
        try:
            results = f1_session.results
            if results is not None and len(results) > 0:
                p1 = results[results['Position'] == 1]
                if len(p1) > 0:
                    return p1.iloc[0]['Abbreviation']
        except Exception:
            pass
        return None

    @staticmethod
    def _build_driver_map(f1_session) -> Dict[str, str]:
        """Build mapping from driver number to driver code."""
        driver_map = {}
        try:
            results = f1_session.results
            if results is not None and len(results) > 0:
                # Vectorized: extract columns and zip
                nums = results['DriverNumber'].astype(str).values
                abbrs = results['Abbreviation'].values
                # Build dict from valid pairs
                driver_map = {
                    num: abbr for num, abbr in zip(nums, abbrs)
                    if num and abbr
                }
        except Exception:
            pass
        return driver_map

    @staticmethod
    def _build_driver_telemetry(pos_df: pd.DataFrame, car_df: pd.DataFrame,
                                 driver_laps: Optional[pd.DataFrame] = None,
                                 race_length: int = 0,  # Kept for API compatibility
                                 is_dnf: bool = False) -> Tuple[Optional[pl.DataFrame], Optional[dict]]:
        """
        Build telemetry for a single driver.

        1. Sort pos_data by time
        2. Sample car_data to pos_data timestamps (nearest neighbor)
        3. Add lap info (lap_number, compound, tyre_life) from laps data
        4. Convert to Polars DataFrame
        5. Return status_data separately (for deferred status calculation)

        Args:
            pos_df: Position data (Date, Status, X, Y, Z, SessionTime)
            car_df: Car data (RPM, Speed, nGear, Throttle, Brake, DRS, SessionTime)
            driver_laps: Driver's lap data (LapNumber, LapStartTime, Time, Compound, TyreLife)
            race_length: Total laps in the race (max across all drivers)
            is_dnf: True if driver retired (from FastF1 results)

        Returns:
            Tuple of:
            - Polars DataFrame with telemetry columns (snake_case), status will be updated later
            - status_data dict with {finish_time, pit_windows, is_dnf} for deferred status calc
        """
        if len(pos_df) == 0:
            return None, None

        # Sort by time (no compaction - keep all points for accurate order tracking)
        if 'SessionTime' in pos_df.columns:
            pos_df = pos_df.sort_values('SessionTime').reset_index(drop=True)

        # Sample car_data to pos_data timestamps
        telemetry_df = TelemetryBuilder._sample_car_data(pos_df, car_df)

        # Add lap info (also extracts pit windows)
        telemetry_df, _, finish_time, pit_windows = TelemetryBuilder._add_lap_info(telemetry_df, driver_laps)

        # Build status_data for deferred status calculation (after lap_number is finalized)
        status_data = {
            'finish_time': finish_time,
            'pit_windows': pit_windows,
            'is_dnf': is_dnf
        }

        # Add velocity vectors for smooth interpolation
        telemetry_df = TelemetryBuilder._add_velocity_vectors(telemetry_df)

        # Convert to Polars (status will be updated later by SessionProcessor)
        return pl.from_pandas(telemetry_df), status_data

    @staticmethod
    def _compact_position_data(pos_df: pd.DataFrame) -> pd.DataFrame:
        """
        Compact position data by removing intermediate rows with same X, Y, Z.

        For consecutive rows with identical X, Y, Z values, keep only the first
        and last row of each group.

        Args:
            pos_df: Position DataFrame with X, Y, Z columns

        Returns:
            Compacted DataFrame
        """
        if len(pos_df) == 0:
            return pos_df

        # Ensure sorted by time
        if 'SessionTime' in pos_df.columns:
            pos_df = pos_df.sort_values('SessionTime').reset_index(drop=True)

        # Get X, Y, Z as arrays
        x = pos_df['X'].values if 'X' in pos_df.columns else np.zeros(len(pos_df))
        y = pos_df['Y'].values if 'Y' in pos_df.columns else np.zeros(len(pos_df))
        z = pos_df['Z'].values if 'Z' in pos_df.columns else np.zeros(len(pos_df))

        # Find rows to keep (first and last of each static group)
        keep_mask = np.zeros(len(pos_df), dtype=bool)

        if len(pos_df) == 1:
            keep_mask[0] = True
            return pos_df[keep_mask].reset_index(drop=True)

        # Detect position changes
        x_changed = np.concatenate([[True], x[1:] != x[:-1]])
        y_changed = np.concatenate([[True], y[1:] != y[:-1]])
        z_changed = np.concatenate([[True], z[1:] != z[:-1]])
        position_changed = x_changed | y_changed | z_changed

        # Group consecutive rows with same position
        group_id = np.cumsum(position_changed)

        # Vectorized: keep first and last of each group
        # First of each group: where group_id changes (position_changed is True)
        keep_mask[position_changed] = True
        # Last of each group: where next row has different group_id
        keep_mask[:-1] |= (group_id[:-1] != group_id[1:])
        keep_mask[-1] = True  # Always keep last row

        compacted = pos_df[keep_mask].reset_index(drop=True)
        return compacted

    @staticmethod
    def _sample_car_data(pos_df: pd.DataFrame, car_df: pd.DataFrame) -> pd.DataFrame:
        """
        Sample car_data to match pos_data timestamps using nearest neighbor.

        Args:
            pos_df: Compacted position DataFrame
            car_df: Car telemetry DataFrame

        Returns:
            Combined DataFrame with position and car data (snake_case columns)
        """
        # Convert SessionTime to seconds for matching
        if 'SessionTime' in pos_df.columns:
            pos_times = pos_df['SessionTime'].dt.total_seconds().values
        else:
            pos_times = np.arange(len(pos_df))

        if 'SessionTime' in car_df.columns:
            car_times = car_df['SessionTime'].dt.total_seconds().values
        else:
            car_times = np.arange(len(car_df))

        # Find nearest car_data index for each pos_data timestamp (vectorized)
        nearest_indices = np.searchsorted(car_times, pos_times)
        # Clamp to valid range
        nearest_indices = np.clip(nearest_indices, 0, len(car_times) - 1)

        # Vectorized: check if previous index is closer
        prev_indices = np.maximum(nearest_indices - 1, 0)
        dist_current = np.abs(car_times[nearest_indices] - pos_times)
        dist_prev = np.abs(car_times[prev_indices] - pos_times)
        use_prev = (nearest_indices > 0) & (dist_prev < dist_current)
        nearest_indices = np.where(use_prev, prev_indices, nearest_indices)

        # Build result DataFrame with snake_case column names
        result = pd.DataFrame()

        # Add session_time (from pos_data, converted to seconds)
        result['session_time'] = pos_times

        # Add position columns (lowercase)
        result['status'] = pos_df['Status'].values if 'Status' in pos_df.columns else 'Unknown'
        result['x'] = pos_df['X'].values if 'X' in pos_df.columns else 0.0
        result['y'] = pos_df['Y'].values if 'Y' in pos_df.columns else 0.0
        result['z'] = pos_df['Z'].values if 'Z' in pos_df.columns else 0.0

        # Sample car data columns (with snake_case names)
        car_column_map = {
            'RPM': 'rpm',
            'Speed': 'speed',
            'nGear': 'n_gear',
            'Throttle': 'throttle',
            'Brake': 'brake',
            'DRS': 'drs'
        }
        for src_col, dst_col in car_column_map.items():
            if src_col in car_df.columns:
                result[dst_col] = car_df[src_col].values[nearest_indices]
            else:
                result[dst_col] = 0

        return result

    @staticmethod
    def _add_velocity_vectors(telemetry_df: pd.DataFrame) -> pd.DataFrame:
        """
        Compute velocity vectors (vx, vy) using central differences for smooth Hermite interpolation.

        Central differences: v[i] = (p[i+1] - p[i-1]) / (t[i+1] - t[i-1])
        Boundary handling: forward/backward differences at edges.
        Large time gaps (>2s): zero velocity at boundaries (pit stops, stoppages).

        Args:
            telemetry_df: Telemetry DataFrame with session_time, x, y columns

        Returns:
            DataFrame with vx, vy columns added (decimeters/second)
        """
        n = len(telemetry_df)
        if n < 2:
            telemetry_df['vx'] = 0.0
            telemetry_df['vy'] = 0.0
            return telemetry_df

        x = telemetry_df['x'].values.astype(np.float64)
        y = telemetry_df['y'].values.astype(np.float64)
        t = telemetry_df['session_time'].values.astype(np.float64)

        vx = np.zeros(n, dtype=np.float32)
        vy = np.zeros(n, dtype=np.float32)

        # Central differences for interior points
        if n >= 3:
            dt = t[2:] - t[:-2]
            dt = np.where(dt > 0, dt, 0.001)  # Avoid division by zero
            vx[1:-1] = (x[2:] - x[:-2]) / dt
            vy[1:-1] = (y[2:] - y[:-2]) / dt

        # Forward difference for first point
        dt0 = t[1] - t[0]
        if dt0 > 0:
            vx[0] = (x[1] - x[0]) / dt0
            vy[0] = (y[1] - y[0]) / dt0

        # Backward difference for last point
        dt_last = t[-1] - t[-2]
        if dt_last > 0:
            vx[-1] = (x[-1] - x[-2]) / dt_last
            vy[-1] = (y[-1] - y[-2]) / dt_last

        # Handle large time gaps (pit stops, stoppages) - zero velocity at boundaries
        MAX_GAP = 2.0
        dt_forward = np.diff(t, prepend=t[0])
        gap_mask = dt_forward > MAX_GAP
        vx[gap_mask] = 0.0
        vy[gap_mask] = 0.0
        # Also zero the point before a gap
        gap_indices = np.where(gap_mask)[0]
        for idx in gap_indices:
            if idx > 0:
                vx[idx - 1] = 0.0
                vy[idx - 1] = 0.0

        # Clamp extreme velocities (max ~100 m/s = 1000 dm/s)
        MAX_VEL = 1000.0
        vx = np.clip(vx, -MAX_VEL, MAX_VEL)
        vy = np.clip(vy, -MAX_VEL, MAX_VEL)

        # Smooth velocity vectors to reduce noise-induced oscillations
        # Use exponential moving average (EMA) with alpha ~0.3 for good smoothing
        # Apply forward then backward pass for zero-lag smoothing
        def smooth_ema_bidirectional(arr, alpha=0.3):
            if len(arr) < 3:
                return arr
            # Forward pass
            fwd = np.zeros_like(arr)
            fwd[0] = arr[0]
            for i in range(1, len(arr)):
                fwd[i] = alpha * arr[i] + (1 - alpha) * fwd[i - 1]
            # Backward pass
            bwd = np.zeros_like(arr)
            bwd[-1] = arr[-1]
            for i in range(len(arr) - 2, -1, -1):
                bwd[i] = alpha * arr[i] + (1 - alpha) * bwd[i + 1]
            # Average forward and backward for zero-lag result
            return (fwd + bwd) / 2

        vx = smooth_ema_bidirectional(vx)
        vy = smooth_ema_bidirectional(vy)

        telemetry_df['vx'] = vx.astype(np.float32)
        telemetry_df['vy'] = vy.astype(np.float32)

        return telemetry_df

    @staticmethod
    def _add_lap_info(telemetry_df: pd.DataFrame, driver_laps: Optional[pd.DataFrame]) -> tuple:
        """
        Add lap_number, compound, tyre_life to telemetry based on lap data.

        Uses lap COMPLETION times (Time column) to determine which lap the driver is on:
        - Before race starts (lights out) → lap_number = 0
        - After lights out, before lap 1 complete → lap_number = 1
        - After lap N complete → lap_number = N + 1

        This ensures lap_number increments at the exact moment the driver crosses
        the finish line, synchronized with track_distance wrap.

        Also extracts pit windows from PitInTime/PitOutTime columns.

        Args:
            telemetry_df: Telemetry DataFrame with session_time column
            driver_laps: Driver's lap data from FastF1

        Returns:
            Tuple of (telemetry_df with lap columns added, max_lap number, finish_time in seconds or None, pit_windows list)
        """
        n_rows = len(telemetry_df)

        # Default values
        lap_numbers = np.zeros(n_rows, dtype=np.int32)
        compounds = np.array(['UNKNOWN'] * n_rows, dtype=object)
        tyre_life = np.zeros(n_rows, dtype=np.float32)
        max_lap = 0
        finish_time = None  # Session time when driver crossed finish line on last lap
        pit_windows = []  # List of (pit_in_seconds, pit_out_seconds) tuples

        if driver_laps is None or len(driver_laps) == 0:
            telemetry_df['lap_number'] = lap_numbers
            telemetry_df['compound'] = compounds
            telemetry_df['tyre_life'] = tyre_life
            return telemetry_df, max_lap, finish_time, pit_windows

        # Vectorized extraction of lap info (avoid iterrows)
        laps_df = driver_laps.copy()

        # Filter valid laps (have LapNumber and Time for completion-based tracking)
        valid_mask = laps_df['LapNumber'].notna()
        if 'Time' in laps_df.columns:
            valid_mask = valid_mask & laps_df['Time'].notna()
        laps_df = laps_df[valid_mask]

        if len(laps_df) == 0:
            telemetry_df['lap_number'] = lap_numbers
            telemetry_df['compound'] = compounds
            telemetry_df['tyre_life'] = tyre_life
            return telemetry_df, max_lap, finish_time, pit_windows

        # Convert times to seconds (vectorized)
        lap_nums_arr = laps_df['LapNumber'].values.astype(np.int32)

        # Get lap completion times (Time column) and start times
        if 'Time' in laps_df.columns:
            lap_completion_times = laps_df['Time'].dt.total_seconds().values
        else:
            lap_completion_times = np.full(len(laps_df), np.nan)

        if 'LapStartTime' in laps_df.columns:
            lap_start_times = laps_df['LapStartTime'].dt.total_seconds().values
        else:
            lap_start_times = np.full(len(laps_df), np.nan)

        # Handle Compound - fill NaN with 'UNKNOWN'
        if 'Compound' in laps_df.columns:
            compounds_arr = laps_df['Compound'].fillna('UNKNOWN').values
        else:
            compounds_arr = np.array(['UNKNOWN'] * len(laps_df))

        # Handle TyreLife - fill NaN with 0
        if 'TyreLife' in laps_df.columns:
            tyre_life_arr = laps_df['TyreLife'].fillna(0).values.astype(np.float32)
        else:
            tyre_life_arr = np.zeros(len(laps_df), dtype=np.float32)

        # Sort by lap completion time
        valid_completion = ~np.isnan(lap_completion_times)
        if not np.any(valid_completion):
            telemetry_df['lap_number'] = lap_numbers
            telemetry_df['compound'] = compounds
            telemetry_df['tyre_life'] = tyre_life
            return telemetry_df, max_lap, finish_time, pit_windows

        sort_idx = np.argsort(lap_completion_times)
        lap_completion_times = lap_completion_times[sort_idx]
        lap_nums_arr = lap_nums_arr[sort_idx]
        lap_start_times = lap_start_times[sort_idx]
        compounds_arr = compounds_arr[sort_idx]
        tyre_life_arr = tyre_life_arr[sort_idx]

        # Get max lap and finish time
        max_lap = int(lap_nums_arr.max())
        finish_time = float(lap_completion_times[-1]) if len(lap_completion_times) > 0 else None

        # Race start time (lights out) - first lap's start time
        race_start_time = lap_start_times[0] if not np.isnan(lap_start_times[0]) else 0

        # Get telemetry times
        session_times = telemetry_df['session_time'].values

        # Determine lap_number using lap COMPLETION times:
        # completed_laps = how many laps have been completed at each session_time
        completed_laps = np.searchsorted(lap_completion_times, session_times, side='right')
        # lap_number = completed_laps + 1 (the lap we're currently on)
        # But before race starts, lap_number = 0
        lap_numbers = completed_laps + 1
        lap_numbers[session_times < race_start_time] = 0

        # Assign compound and tyre_life based on current lap
        # For lap N, use the tyre info from lap N's data
        lap_indices = np.clip(completed_laps, 0, len(lap_nums_arr) - 1)
        compounds = compounds_arr[lap_indices]
        tyre_life = tyre_life_arr[lap_indices]

        telemetry_df['lap_number'] = lap_numbers
        telemetry_df['compound'] = compounds
        telemetry_df['tyre_life'] = tyre_life

        # Extract pit windows from PitInTime/PitOutTime (vectorized)
        # PitInTime = when car entered pit (on in-lap)
        # PitOutTime = when car exited pit (on out-lap, usually next lap)
        if 'PitInTime' in driver_laps.columns:
            pit_in_series = driver_laps['PitInTime'].dropna()
            if len(pit_in_series) > 0:
                pit_in_times = pit_in_series.dt.total_seconds().values
                pit_in_times = np.sort(pit_in_times)
            else:
                pit_in_times = np.array([])
        else:
            pit_in_times = np.array([])

        if 'PitOutTime' in driver_laps.columns:
            pit_out_series = driver_laps['PitOutTime'].dropna()
            if len(pit_out_series) > 0:
                pit_out_times = pit_out_series.dt.total_seconds().values
                pit_out_times = np.sort(pit_out_times)
            else:
                pit_out_times = np.array([])
        else:
            pit_out_times = np.array([])

        # Pair them up using searchsorted: each pit_in with next pit_out after it
        if len(pit_in_times) > 0 and len(pit_out_times) > 0:
            # Find index of first pit_out > pit_in for each pit_in
            out_indices = np.searchsorted(pit_out_times, pit_in_times, side='right')
            for i, pit_in in enumerate(pit_in_times):
                if out_indices[i] < len(pit_out_times):
                    pit_windows.append((float(pit_in), float(pit_out_times[out_indices[i]])))

        return telemetry_df, max_lap, finish_time, pit_windows

    @staticmethod
    def _extract_track_and_pit(telemetry: Dict[str, pl.DataFrame], winner: Optional[str],
                                status_data_all: Optional[Dict[str, dict]] = None) -> Tuple[Optional[TrackData], Optional[dict]]:
        """
        Extract track and pit lane geometry from race winner's telemetry.

        Also detects session timing boundaries (warmup start).

        - Track: from winner's fastest racing lap
        - Pit lane: from winner's first pit stint, extended to merge with track

        Args:
            telemetry: Dict of driver -> Polars DataFrame
            winner: Race winner driver code (or None to use first available)
            status_data_all: Dict of driver -> status data (for pit detection)

        Returns:
            Tuple of (TrackData, session_timing dict)

        Returns:
            Tuple of:
            - TrackData with track and pit geometry (or None)
            - Session timing dict with {warmup_start_time, race_start_time} (or None)
        """
        from f1_replay.models import TrackGeometry

        # Use winner or first available driver
        if winner and winner in telemetry:
            driver = winner
        else:
            driver = list(telemetry.keys())[0] if telemetry else None

        if driver is None:
            return None, None

        tel = telemetry[driver]
        print(f"  → Extracting track/pit from {driver}")

        # Extract track from racing laps (lap_number >= 1)
        racing = tel.filter(pl.col('lap_number') >= 1)
        if len(racing) == 0:
            print("  ⚠ No racing telemetry found")
            return None, None

        # Find laps that have pit activity using pit_windows from status_data
        pit_laps = set()
        if status_data_all and driver in status_data_all:
            driver_status = status_data_all[driver]
            driver_pit_windows = driver_status.get('pit_windows', [])
            if driver_pit_windows:
                session_times = tel['session_time'].to_numpy()
                lap_numbers = tel['lap_number'].to_numpy()
                for pit_in, pit_out in driver_pit_windows:
                    pit_mask = (session_times >= pit_in) & (session_times < pit_out)
                    pit_laps.update(lap_numbers[pit_mask].tolist())

        # Also exclude the lap after pit (out-lap) - typically has slower exit
        pit_out_laps = {lap + 1 for lap in pit_laps}
        # Exclude lap 1 (first racing lap, often includes grid start anomalies)
        exclude_laps = pit_laps | pit_out_laps | {1}

        # Find fastest lap by calculating lap duration from telemetry
        lap_times = racing.group_by('lap_number').agg([
            pl.col('session_time').min().alias('start_time'),
            pl.col('session_time').max().alias('end_time'),
            pl.len().alias('n_points')
        ]).with_columns(
            (pl.col('end_time') - pl.col('start_time')).alias('lap_duration')
        ).filter(
            (pl.col('n_points') > 100) &  # Must have reasonable telemetry coverage
            (~pl.col('lap_number').is_in(list(exclude_laps)))  # Exclude pit/out laps and lap 1
        ).sort('lap_duration')

        # Fallback: if no clean laps, try without excluding pit laps
        if len(lap_times) == 0:
            print("  ⚠ No clean laps, falling back to any racing lap")
            lap_times = racing.group_by('lap_number').agg([
                pl.col('session_time').min().alias('start_time'),
                pl.col('session_time').max().alias('end_time'),
                pl.len().alias('n_points')
            ]).with_columns(
                (pl.col('end_time') - pl.col('start_time')).alias('lap_duration')
            ).filter(pl.col('n_points') > 100).sort('lap_duration')

        if len(lap_times) == 0:
            print("  ⚠ No valid laps found")
            return None, None

        best_lap = lap_times['lap_number'][0]
        lap_duration = lap_times['lap_duration'][0]
        lap_tel = racing.filter(pl.col('lap_number') == best_lap)

        track_x = lap_tel['x'].to_numpy().astype(np.float32)
        track_y = lap_tel['y'].to_numpy().astype(np.float32)
        track_z = lap_tel['z'].to_numpy().astype(np.float32) if 'z' in lap_tel.columns else None

        # Extract speed, throttle, brake from the reference lap
        track_speed = lap_tel['speed'].to_numpy().astype(np.float32) if 'speed' in lap_tel.columns else None
        track_throttle = lap_tel['throttle'].to_numpy().astype(np.float32) if 'throttle' in lap_tel.columns else None
        track_brake = lap_tel['brake'].to_numpy().astype(np.float32) if 'brake' in lap_tel.columns else None

        # Smooth wrap-around: blend last N points toward first point values
        def smooth_wrap(arr, n_blend=10):
            if arr is None or len(arr) < n_blend * 2:
                return arr
            # Linearly blend last n_blend points toward first value
            blend_weights = np.linspace(1, 0, n_blend)
            arr = arr.copy()
            arr[-n_blend:] = arr[-n_blend:] * blend_weights + arr[0] * (1 - blend_weights)
            return arr

        track_speed = smooth_wrap(track_speed)
        track_throttle = smooth_wrap(track_throttle)
        track_brake = smooth_wrap(track_brake)
        track_z = smooth_wrap(track_z)

        # Calculate cumulative distance along track (in decimeters)
        dx = np.diff(track_x, prepend=track_x[0])
        dy = np.diff(track_y, prepend=track_y[0])
        distances = np.sqrt(dx**2 + dy**2)
        distances[0] = 0
        track_dist = np.cumsum(distances).astype(np.float32)
        lap_distance = float(track_dist[-1])

        # Convert to meters for projection
        track_dist_m = (track_dist / 10.0).astype(np.float32)
        lap_distance_m = lap_distance / 10.0

        print(f"    ✓ Track from lap {best_lap} ({lap_duration:.1f}s): {len(track_x)} points, {lap_distance_m:.0f}m")

        # Extract pit lane - find a driver who actually pitted
        # Race winner may not have pitted, so search all drivers for pit data
        # Use pit_windows from status_data for reliable pit detection
        pit_tel = None
        pit_driver = None
        pit_windows_for_extraction = []

        if status_data_all:
            for d, d_tel in telemetry.items():
                d_status = status_data_all.get(d, {})
                d_pit_windows = d_status.get('pit_windows', [])
                if d_pit_windows and len(d_pit_windows) > 0:
                    # Use pit_windows to filter telemetry to pit times
                    session_times = d_tel['session_time'].to_numpy()
                    pit_mask = np.zeros(len(session_times), dtype=bool)
                    for pit_in, pit_out in d_pit_windows:
                        pit_mask |= (session_times >= pit_in) & (session_times < pit_out)

                    if np.sum(pit_mask) > 10:  # Need meaningful pit data
                        pit_tel = d_tel.filter(pl.Series(pit_mask))
                        pit_driver = d
                        pit_windows_for_extraction = d_pit_windows
                        break

        pit_x, pit_y = None, None
        pit_distance = None
        pit_length = 0.0
        pit_entry_dist, pit_exit_dist = None, None

        if pit_tel is not None and len(pit_tel) > 0:
            tel_for_pit = telemetry[pit_driver]  # Use the driver who pitted
            # Get first continuous pit stint
            pit_times = pit_tel['session_time'].to_numpy()
            time_gaps = np.diff(pit_times)
            # Find where gap > 60s (new pit stop)
            gap_indices = np.where(time_gaps > 60)[0]
            end_idx = gap_indices[0] + 1 if len(gap_indices) > 0 else len(pit_tel)

            first_pit = pit_tel.head(end_idx)
            pit_start_time = first_pit['session_time'][0]
            pit_end_time = first_pit['session_time'][-1]

            # Expand window to 1 minute before and after pit stint
            expand_time = 60.0  # seconds
            expanded_pit = tel_for_pit.filter(
                (pl.col('session_time') >= pit_start_time - expand_time) &
                (pl.col('session_time') <= pit_end_time + expand_time)
            ).sort('session_time')

            pit_x_raw = expanded_pit['x'].to_numpy().astype(np.float32)
            pit_y_raw = expanded_pit['y'].to_numpy().astype(np.float32)

            if len(pit_x_raw) > 1:
                # Create temporary TrackGeometry for projection
                temp_track = TrackGeometry(
                    x=track_x, y=track_y,
                    distance=track_dist_m,
                    lap_distance=lap_distance_m
                )

                # Project all points onto track
                pit_track_dist = temp_track.progress_on_track(pit_x_raw, pit_y_raw)
                pit_dist_to_track = temp_track.distance_to_track(pit_x_raw, pit_y_raw)

                # Find where pit status starts/ends in the expanded window (vectorized)
                # Use pit_windows for reliable pit detection
                expanded_times = expanded_pit['session_time'].to_numpy()
                is_pit_status = np.zeros(len(expanded_times), dtype=bool)
                for pit_in, pit_out in pit_windows_for_extraction:
                    is_pit_status |= (expanded_times >= pit_in) & (expanded_times < pit_out)

                # Find first and last pit indices using np.where
                pit_indices = np.where(is_pit_status)[0]
                if len(pit_indices) > 0:
                    pit_start_idx = pit_indices[0]
                    pit_end_idx = pit_indices[-1]
                else:
                    pit_start_idx = 0
                    pit_end_idx = len(pit_x_raw) - 1

                # Threshold for being "on track" (0.5m = 5 decimeters)
                threshold_dm = 5.0

                # Vectorized: find entry point (last point before pit_start that's on track)
                on_track_mask = pit_dist_to_track < threshold_dm
                before_pit_on_track = np.where(on_track_mask[:pit_start_idx + 1])[0]
                entry_idx = before_pit_on_track[-1] if len(before_pit_on_track) > 0 else 0

                # Vectorized: find exit point (first point after pit_end that's on track)
                after_pit_on_track = np.where(on_track_mask[pit_end_idx:])[0]
                exit_idx = pit_end_idx + after_pit_on_track[0] if len(after_pit_on_track) > 0 else len(pit_x_raw) - 1

                pit_entry_dist = float(pit_track_dist[entry_idx])
                pit_exit_dist = float(pit_track_dist[exit_idx])

                # Trim pit lane to entry/exit merge points
                pit_x_trimmed = pit_x_raw[entry_idx:exit_idx + 1]
                pit_y_trimmed = pit_y_raw[entry_idx:exit_idx + 1]

                # Remove duplicate/close points (minimum distance between consecutive points)
                min_dist_dm = 5.0  # 0.5m = 5 decimeters minimum spacing
                if len(pit_x_trimmed) > 2:
                    # Calculate cumulative distance (vectorized)
                    dx = np.diff(pit_x_trimmed)
                    dy = np.diff(pit_y_trimmed)
                    point_distances = np.sqrt(dx**2 + dy**2)
                    cumsum_dist = np.concatenate([[0], np.cumsum(point_distances)])

                    # Vectorized decimation: keep points at distance intervals
                    # Find which "bucket" each point belongs to
                    bucket = (cumsum_dist / min_dist_dm).astype(np.int32)

                    # Keep first point of each bucket + always keep first and last
                    keep_mask = np.zeros(len(pit_x_trimmed), dtype=bool)
                    keep_mask[0] = True  # Always keep first
                    keep_mask[-1] = True  # Always keep last

                    # Keep first point where bucket changes (bucket transitions)
                    bucket_changes = np.concatenate([[True], bucket[1:] != bucket[:-1]])
                    keep_mask |= bucket_changes

                    pit_x = pit_x_trimmed[keep_mask]
                    pit_y = pit_y_trimmed[keep_mask]
                else:
                    pit_x = pit_x_trimmed
                    pit_y = pit_y_trimmed

                # Calculate pit lane cumulative distance (in decimeters, convert to meters)
                pit_dx = np.diff(pit_x, prepend=pit_x[0])
                pit_dy = np.diff(pit_y, prepend=pit_y[0])
                pit_distances = np.sqrt(pit_dx**2 + pit_dy**2)
                pit_distances[0] = 0
                pit_distance = (np.cumsum(pit_distances) / 10.0).astype(np.float32)  # meters
                pit_length = float(pit_distance[-1])

                print(f"    ✓ Pit lane from {pit_driver}: {len(pit_x)} points, {pit_length:.0f}m (entry={pit_entry_dist:.0f}m, exit={pit_exit_dist:.0f}m)")

        # Detect warmup start from winner's telemetry (using wrap-based approach)
        warmup_start_time = None

        tel = telemetry.get(driver)
        if tel is not None and 'lap_number' in tel.columns and 'session_time' in tel.columns:
            lap_numbers = tel['lap_number'].to_numpy()
            session_times = tel['session_time'].to_numpy()
            px = tel['x'].to_numpy().astype(np.float32)
            py = tel['y'].to_numpy().astype(np.float32)
            pz = tel['z'].to_numpy().astype(np.float32) if 'z' in tel.columns else np.zeros(len(tel))

            # Find race start index: when FastF1 lap_number changes from 0 to 1
            race_start_mask = lap_numbers >= 1
            if np.any(race_start_mask):
                race_start_idx = np.where(race_start_mask)[0][0]
                race_start_time = float(session_times[race_start_idx])

                # Calculate movement: True if position changed from previous point
                moving = np.zeros(len(px), dtype=bool)
                moving[1:] = (px[1:] != px[:-1]) | (py[1:] != py[:-1]) | (pz[1:] != pz[:-1])

                # Search backwards from race_start to find grid position (stationary period)
                # Need at least 50 consecutive static points (~5s) to be sure it's the grid
                min_static_duration = 50
                search_limit = max(0, race_start_idx - 6000)  # Search up to 600s back

                found_grid = False
                for i in range(race_start_idx - 1, search_limit, -1):
                    if i >= min_static_duration:
                        # Check if min_static_duration points before i are all static
                        all_static = all(not moving[j] for j in range(i - min_static_duration, i))

                        if all_static:
                            # Found end of grid position - extend backwards to find full duration
                            grid_start = i - min_static_duration
                            while grid_start > 0 and not moving[grid_start - 1]:
                                grid_start -= 1

                            # Find when car starts moving after grid = warmup start
                            for j in range(grid_start, len(moving)):
                                if moving[j]:
                                    warmup_start_time = float(session_times[j])
                                    grid_duration = session_times[j] - session_times[grid_start]
                                    warmup_duration = race_start_time - warmup_start_time
                                    print(f"    ✓ Warmup detection: Grid {grid_duration:.1f}s, "
                                          f"starts at {warmup_start_time:.1f}s, duration: {warmup_duration:.1f}s")
                                    found_grid = True
                                    break

                            if found_grid:
                                break

                if not found_grid:
                    print(f"    ⚠ Could not detect warmup start (no grid position found)")

        # Build session timing dict
        session_timing = {
            'warmup_start_time': warmup_start_time
        } if warmup_start_time is not None else None

        track_data = TrackData(
            track_x=track_x,
            track_y=track_y,
            track_distance=track_dist,  # Keep in decimeters, dataloader converts
            lap_distance=lap_distance,   # Keep in decimeters
            pit_x=pit_x,
            pit_y=pit_y,
            pit_distance=pit_distance,   # In meters
            pit_length=pit_length,       # In meters
            pit_entry_distance=pit_entry_dist,  # In meters
            pit_exit_distance=pit_exit_dist,    # In meters
            speed=track_speed,
            throttle=track_throttle,
            brake=track_brake,
            track_z=track_z
        )

        return track_data, session_timing

    @staticmethod
    def _add_track_distance_all(telemetry: Dict[str, pl.DataFrame], track_data: TrackData,
                                 session_timing: Optional[dict] = None) -> Dict[str, pl.DataFrame]:
        """
        Add track_distance, race_distance, and recalculate lap_number from wrap detection.

        track_distance: Position along the track (0 to track_length meters)
        race_distance: finish_crossings * track_length + track_distance
        lap_number: finish_crossings + 1 (during race), 0 (during warmup), -1 (before warmup)

        Lap boundaries:
        - PreSession (lap_number=-1): before warmup_start_time
        - WarmUp (lap_number=0): from warmup_start_time until first wrap
        - Racing (lap_number>=1): after first wrap, using wrap-based counting

        Lap detection uses track_distance wraps (finish line crossings) as single source
        of truth, which is more accurate than FastF1's lap completion times and ensures
        lap_number and race_distance are perfectly synchronized.

        For pit lane positions, interpolates track_distance between pit entry and exit
        based on progress along the pit lane path.

        Args:
            telemetry: Dict of driver -> Polars DataFrame
            track_data: TrackData with track geometry
            session_timing: Dict with {warmup_start_time} for lap boundary detection

        Returns:
            Updated telemetry dict with track_distance, race_distance, lap_number columns
        """
        from f1_replay.models import TrackGeometry

        # Convert to meters for TrackGeometry
        track_dist_m = (track_data.track_distance / 10.0).astype(np.float32)
        lap_distance_m = track_data.lap_distance / 10.0

        # Create TrackGeometry for main track projection
        track_geom = TrackGeometry(
            x=track_data.track_x,
            y=track_data.track_y,
            distance=track_dist_m,
            lap_distance=lap_distance_m
        )

        # Add track_distance and race_distance to each driver
        # track_distance: projection onto track (0 to track_length), works for pit lane too
        # race_distance: finish_crossings * track_length + track_distance
        updated = {}
        for driver, tel in telemetry.items():
            px = tel['x'].to_numpy().astype(np.float32)
            py = tel['y'].to_numpy().astype(np.float32)

            # Project all positions onto track (including pit lane positions)
            # This gives track_distance as progress along the circuit
            track_distance = track_geom.progress_on_track(px, py)

            # Calculate lap_number and race_distance using track_distance wraps as source of truth
            # This ensures lap_number and race_distance are perfectly synchronized
            session_times = tel['session_time'].to_numpy()

            # Find warmup start index from session_timing
            warmup_start_idx = 0
            warmup_start_time = session_timing.get('warmup_start_time') if session_timing else None
            if warmup_start_time is not None:
                warmup_mask = session_times >= warmup_start_time
                if np.any(warmup_mask):
                    warmup_start_idx = np.where(warmup_mask)[0][0]

            # Detect finish line crossings: track_distance drops by >80% of track length
            # Minimum time between valid lap completions (filters spurious wraps from pit projection)
            MIN_LAP_TIME = 60.0  # seconds
            finish_crossings = np.zeros(len(track_distance), dtype=np.int32)
            first_wrap_idx = None

            if len(track_distance) > 1:
                dist_diff = np.diff(track_distance)
                wrap_threshold = -0.8 * lap_distance_m
                wrap_mask = dist_diff < wrap_threshold
                wrap_indices = np.where(wrap_mask)[0] + 1  # +1 because diff shifts by 1

                # The first wrap after warmup_start is when racing begins (end of formation lap)
                if len(wrap_indices) > 0:
                    wraps_after_warmup = wrap_indices[wrap_indices >= warmup_start_idx]

                    # Filter wraps to only include those at least MIN_LAP_TIME apart
                    # This prevents false lap counts from pit lane projection noise
                    if len(wraps_after_warmup) > 0:
                        valid_wraps = [wraps_after_warmup[0]]
                        last_wrap_time = session_times[wraps_after_warmup[0]]
                        for wrap_idx in wraps_after_warmup[1:]:
                            wrap_time = session_times[wrap_idx]
                            if wrap_time - last_wrap_time >= MIN_LAP_TIME:
                                valid_wraps.append(wrap_idx)
                                last_wrap_time = wrap_time
                        wraps_after_warmup = np.array(valid_wraps)

                    if len(wraps_after_warmup) > 0:
                        first_wrap_idx = wraps_after_warmup[0]

                        # Count finish crossings starting from first wrap
                        # First wrap completes warmup lap (lap 0), subsequent wraps complete racing laps
                        for i, wrap_idx in enumerate(wraps_after_warmup):
                            # i because first wrap completes lap 0, second wrap completes lap 1, etc.
                            finish_crossings[wrap_idx:] = i

            # Calculate lap_number from wrap detection
            # Pre-session: lap_number = -1 (before warmup starts)
            # Warmup: lap_number = 0 (formation lap, from warmup_start until first wrap)
            # Racing: lap_number = finish_crossings + 1 (lap we're currently on)
            new_lap_numbers = np.full(len(track_distance), -1, dtype=np.int32)

            # Mark warmup period
            if first_wrap_idx is not None:
                new_lap_numbers[warmup_start_idx:first_wrap_idx] = 0
                # After first wrap: lap_number = finish_crossings + 1
                new_lap_numbers[first_wrap_idx:] = finish_crossings[first_wrap_idx:] + 1
            elif warmup_start_idx < len(track_distance):
                # No wraps detected, everything after warmup_start is warmup
                new_lap_numbers[warmup_start_idx:] = 0

            # Calculate race_distance = (lap_number - 1) * track_length + track_distance
            # This gives negative values during warmup (lap 0), starting at 0 for lap 1
            # PreSession (lap -1): very negative, Warmup (lap 0): -track_length to 0, Lap 1+: 0 onwards
            # Note: race_distance freezing happens in _add_status_all() after status is determined
            race_distance = ((new_lap_numbers - 1) * lap_distance_m + track_distance).astype(np.float32)

            # Add/update columns to telemetry (status updated later by SessionProcessor)
            updated[driver] = (
                tel.lazy()
                .with_columns(pl.Series('track_distance', track_distance))
                .with_columns(pl.Series('race_distance', race_distance))
                .with_columns(pl.Series('lap_number', new_lap_numbers))
                .collect()
            )

        print(f"  ✓ Added track_distance, race_distance, lap_number (track: {lap_distance_m:.0f}m)")
        return updated

    @staticmethod
    def _add_status_all(telemetry: Dict[str, pl.DataFrame],
                        status_data_all: Dict[str, dict],
                        warmup_intervals: list = None,
                        lights_out_offset: float = None) -> Dict[str, pl.DataFrame]:
        """
        Update status column for all drivers using track status and laps data.

        Called AFTER _add_track_distance_all() so lap_number is finalized from wrap detection.

        Status values (in priority order):
        - PreSession: Before any warmup starts
        - Retired: DNF detected (static position or is_dnf flag)
        - Finished: session_time >= finish_time (last lap completion, and not DNF)
        - Pit: session_time within a pit_window
        - WarmUp: session_time within any warmup interval (from track_status)
        - Racing: session_time >= lights_out (default after race start)

        Also freezes race_distance when Finished/Retired.

        Args:
            telemetry: Dict of driver -> Polars DataFrame (with lap_number, race_distance)
            status_data_all: Dict of driver -> {finish_time, pit_windows, is_dnf}
            warmup_intervals: List of (start_time, end_time) tuples for WarmUp periods
            lights_out_offset: Time when lights out happened (race start)

        Returns:
            Updated telemetry dict with status column updated
        """
        updated = {}

        for driver, tel in telemetry.items():
            status_data = status_data_all.get(driver, {})
            finish_time = status_data.get('finish_time')
            pit_windows = status_data.get('pit_windows', [])
            is_dnf = status_data.get('is_dnf', False)

            # Extract arrays (copy arrays we'll modify)
            lap_numbers = tel['lap_number'].to_numpy().copy()
            session_times = tel['session_time'].to_numpy()
            race_distance = tel['race_distance'].to_numpy().copy()
            x = tel['x'].to_numpy()
            y = tel['y'].to_numpy()
            z = tel['z'].to_numpy() if 'z' in tel.columns else np.zeros(len(tel))
            n_rows = len(tel)

            # Detect retirement timing from static position (car stopped moving)
            driver_actually_retired = is_dnf
            retirement_start_idx = n_rows  # Default: no retirement

            if n_rows > 1:
                # Vectorized static position detection
                static_pos = np.zeros(n_rows, dtype=bool)
                static_pos[1:] = (x[1:] == x[:-1]) & (y[1:] == y[:-1]) & (z[1:] == z[:-1])

                if np.any(static_pos):
                    moving = ~static_pos
                    if np.any(moving):
                        last_moving_idx = np.where(moving)[0][-1]
                        static_at_end = n_rows - last_moving_idx - 1

                        # Significant static period (>5 seconds at ~10Hz = 50 rows)
                        if static_at_end > 50:
                            static_start_idx = last_moving_idx + 1
                            static_start_time = session_times[static_start_idx]

                            if is_dnf:
                                retirement_start_idx = static_start_idx
                            elif finish_time is not None:
                                if static_start_time < finish_time:
                                    retirement_start_idx = static_start_idx
                                    driver_actually_retired = True
                            else:
                                retirement_start_idx = static_start_idx
                                driver_actually_retired = True

            # For DNF without static detection, use max lap
            if is_dnf and retirement_start_idx == n_rows:
                max_lap = lap_numbers.max() if len(lap_numbers) > 0 else 0
                if max_lap > 0:
                    on_max_lap = lap_numbers >= max_lap
                    if np.any(on_max_lap):
                        retirement_start_idx = np.where(on_max_lap)[0][0]

            # Build status masks (vectorized)
            # PreSession: Before any warmup starts
            if warmup_intervals and len(warmup_intervals) > 0:
                first_warmup_start = warmup_intervals[0][0]
                is_presession = session_times < first_warmup_start
            else:
                # Fallback to lights_out_offset if no warmup intervals
                if lights_out_offset is not None:
                    is_presession = session_times < lights_out_offset
                else:
                    is_presession = np.zeros(n_rows, dtype=bool)

            # WarmUp: Within any warmup interval
            is_warmup = np.zeros(n_rows, dtype=bool)
            if warmup_intervals:
                for start, end in warmup_intervals:
                    in_warmup = (session_times >= start) & (session_times < end)
                    is_warmup = is_warmup | in_warmup

            # Retired mask
            if driver_actually_retired:
                is_retired = np.arange(n_rows) >= retirement_start_idx
            else:
                is_retired = np.zeros(n_rows, dtype=bool)

            # Finished mask (only if not DNF)
            if finish_time is not None and not driver_actually_retired:
                is_finished = session_times >= finish_time
            else:
                is_finished = np.zeros(n_rows, dtype=bool)

            # Pit mask (vectorized with broadcasting)
            is_pit = np.zeros(n_rows, dtype=bool)
            if pit_windows:
                pit_arr = np.array(pit_windows)
                pit_ins = pit_arr[:, 0]
                pit_outs = pit_arr[:, 1]
                is_pit = np.any(
                    (session_times[:, None] >= pit_ins[None, :]) &
                    (session_times[:, None] < pit_outs[None, :]),
                    axis=1
                )

            # Build status using np.select (priority order matters)
            conditions = [is_presession, is_retired, is_finished, is_pit, is_warmup]
            choices = ['PreSession', 'Retired', 'Finished', 'Pit', 'WarmUp']
            status = np.select(conditions, choices, default='Racing')

            # lap_number comes from wrap detection in _add_track_distance_all() as single source of truth
            # Do NOT modify lap_numbers here - only freeze values for Finished/Retired below

            # Freeze race_distance and lap_number when Finished/Retired
            # Use values from just BEFORE the status change (wrap detection increments at finish line)
            if np.any(is_finished):
                first_finish_idx = np.where(is_finished)[0][0]
                if first_finish_idx > 0:
                    finish_race_distance = race_distance[first_finish_idx - 1]
                    finish_lap_number = lap_numbers[first_finish_idx - 1]
                else:
                    finish_race_distance = race_distance[first_finish_idx]
                    finish_lap_number = lap_numbers[first_finish_idx]
                race_distance[is_finished] = finish_race_distance
                lap_numbers[is_finished] = finish_lap_number

            if np.any(is_retired):
                first_retire_idx = np.where(is_retired)[0][0]
                retire_race_distance = race_distance[first_retire_idx]
                retire_lap_number = lap_numbers[first_retire_idx]
                race_distance[is_retired] = retire_race_distance
                lap_numbers[is_retired] = retire_lap_number

            # Update telemetry with updated status, frozen race_distance and lap_number
            updated[driver] = (
                tel.lazy()
                .with_columns(pl.Series('status', status))
                .with_columns(pl.Series('race_distance', race_distance))
                .with_columns(pl.Series('lap_number', lap_numbers))
                .collect()
            )

        print(f"  ✓ Updated status for {len(updated)} drivers")
        return updated

    @staticmethod
    def extract_track_from_driver(f1_session, driver: str) -> Optional[TrackData]:
        """
        Extract track geometry from a single driver's telemetry.

        Used for efficient weekend loading - only needs one driver's data
        to get track and pit lane geometry.

        Args:
            f1_session: FastF1 session with loaded data
            driver: Driver abbreviation (e.g., 'LEC')

        Returns:
            TrackData with track and pit geometry, or None if failed
        """
        pos_data = getattr(f1_session, 'pos_data', None)
        car_data = getattr(f1_session, 'car_data', None)
        laps = getattr(f1_session, 'laps', None)

        if pos_data is None:
            print(f"  ⚠ No position data available")
            return None

        # Build driver map and find driver's number
        driver_map = TelemetryBuilder._build_driver_map(f1_session)
        driver_num = None
        for num, code in driver_map.items():
            if code == driver:
                driver_num = num
                break

        if driver_num is None:
            print(f"  ⚠ Driver {driver} not found in session")
            return None

        # Get position data for this driver
        pos_df = pos_data.get(driver_num)
        if pos_df is None:
            print(f"  ⚠ No position data for {driver}")
            return None

        # Get car data (may be None)
        car_df = car_data.get(driver_num) if car_data else None

        # Get driver's laps
        driver_laps = None
        if laps is not None and 'Driver' in laps.columns:
            driver_laps = laps[laps['Driver'] == driver]

        # Get race length
        race_length = 0
        if laps is not None and len(laps) > 0 and 'LapNumber' in laps.columns:
            race_length = int(laps['LapNumber'].max())

        # Build telemetry for this driver
        tel, _ = TelemetryBuilder._build_driver_telemetry(pos_df, car_df, driver_laps, race_length)
        if tel is None or len(tel) == 0:
            print(f"  ⚠ Could not build telemetry for {driver}")
            return None

        # Extract track and pit from this driver's telemetry
        track_data, _ = TelemetryBuilder._extract_track_and_pit({driver: tel}, driver)

        # Extract marshal sectors from circuit info
        if track_data is not None:
            track_data = TelemetryBuilder._add_marshal_sectors(f1_session, track_data)

        return track_data

    @staticmethod
    def _add_marshal_sectors(f1_session, track_data: TrackData) -> TrackData:
        """
        Extract marshal sectors from circuit_info and calculate distances.

        FastF1's marshal_sectors provides X, Y coordinates for each sector boundary.
        We project these onto the track to get the distance.

        Args:
            f1_session: FastF1 session
            track_data: TrackData with track geometry

        Returns:
            TrackData with marshal_sectors populated
        """
        try:
            circuit_info = f1_session.get_circuit_info()
            if circuit_info is None or not hasattr(circuit_info, 'marshal_sectors'):
                return track_data

            marshal_df = circuit_info.marshal_sectors
            if marshal_df is None or len(marshal_df) == 0:
                return track_data

            # Get track geometry
            track_x = track_data.track_x
            track_y = track_data.track_y
            track_dist = track_data.track_distance
            lap_distance_dm = track_data.lap_distance  # in decimeters

            # Marshal sectors have X, Y coordinates (in decimeters)
            # Vectorized: project all sector boundaries onto track at once
            sector_nums = marshal_df['Number'].values.astype(np.int32)
            sector_x = marshal_df['X'].values.astype(np.float32)
            sector_y = marshal_df['Y'].values.astype(np.float32)

            # Broadcasting: compute distances from all sectors to all track points
            # sector_x[:, None] shape: (n_sectors, 1), track_x[None, :] shape: (1, n_track)
            # Result shape: (n_sectors, n_track)
            dist_sq = (sector_x[:, None] - track_x[None, :])**2 + (sector_y[:, None] - track_y[None, :])**2
            closest_indices = np.argmin(dist_sq, axis=1)  # Shape: (n_sectors,)

            # Get track distances at closest points (convert to meters)
            dist_meters = track_dist[closest_indices] / 10.0

            # Build (sector_num, dist) pairs and sort by distance
            sector_distances = list(zip(sector_nums, dist_meters))
            sector_distances.sort(key=lambda x: x[1])

            # Build sector ranges (from current to next boundary)
            marshal_sectors = []
            lap_distance_m = lap_distance_dm / 10.0

            for i, (sector_num, from_dist) in enumerate(sector_distances):
                # Next sector boundary (wrap around for last sector)
                if i + 1 < len(sector_distances):
                    to_dist = sector_distances[i + 1][1]
                else:
                    # Last sector wraps to first
                    to_dist = lap_distance_m + sector_distances[0][1]

                marshal_sectors.append((sector_num, from_dist, to_dist))

            if marshal_sectors:
                print(f"    ✓ Marshal sectors: {len(marshal_sectors)}")

            # Return new TrackData with marshal_sectors
            return TrackData(
                track_x=track_data.track_x,
                track_y=track_data.track_y,
                track_distance=track_data.track_distance,
                lap_distance=track_data.lap_distance,
                pit_x=track_data.pit_x,
                pit_y=track_data.pit_y,
                pit_distance=track_data.pit_distance,
                pit_length=track_data.pit_length,
                pit_entry_distance=track_data.pit_entry_distance,
                pit_exit_distance=track_data.pit_exit_distance,
                marshal_sectors=marshal_sectors,
                speed=track_data.speed,
                throttle=track_data.throttle,
                brake=track_data.brake,
                track_z=track_data.track_z
            )

        except Exception as e:
            print(f"    ⚠ Could not extract marshal sectors: {e}")
            return track_data

