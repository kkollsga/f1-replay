"""
Light Telemetry Builder - Minimal processing for track extraction.

Extracts track geometry from a single driver (race winner) without full telemetry processing.
Used by WeekendProcessor to build complete Weekend.pkl at TIER 2.

Only processes:
- session_time (from SessionTime.total_seconds())
- x, y, z coordinates
- lap_number (from lap completion times)
- pit windows (from PitInTime/PitOutTime)

Skips:
- Car data sampling (rpm, speed, gear, throttle, brake, drs) for main telemetry
- Position calculation
- Interval calculation
- Race distance
- Race status
"""

from typing import Optional, List, Tuple
import numpy as np
import pandas as pd
import polars as pl

from f1_replay.loaders.session.telemetry import TrackData
from f1_replay.models import TrackGeometry


class LightTelemetryBuilder:
    """Build minimal telemetry for track extraction only."""

    @staticmethod
    def extract_track_geometry(f1_session, driver_abbr: str) -> Optional[TrackData]:
        """
        Extract track and pit geometry using light telemetry processing.

        Only processes ONE driver (race winner).
        Only extracts minimal data needed for track geometry.

        Args:
            f1_session: FastF1 session with pos_data, car_data, laps loaded
            driver_abbr: Driver abbreviation (race winner)

        Returns:
            TrackData with track and pit geometry, or None if failed
        """
        if not hasattr(f1_session, 'pos_data') or f1_session.pos_data is None:
            print("  ⚠ No position data in session")
            return None

        if not hasattr(f1_session, 'laps') or f1_session.laps is None:
            print("  ⚠ No lap data in session")
            return None

        # Get driver's data
        # pos_data and car_data are dicts keyed by driver number
        pos_data = f1_session.pos_data
        car_data = f1_session.car_data if hasattr(f1_session, 'car_data') else None
        laps = f1_session.laps

        # Find driver number for this abbreviation
        driver_num = None
        driver_laps = laps[laps['Driver'] == driver_abbr].copy()
        if len(driver_laps) == 0:
            print(f"  ⚠ No lap data for {driver_abbr}")
            return None

        # Get driver number from first lap
        if 'DriverNumber' in driver_laps.columns:
            driver_num = driver_laps.iloc[0]['DriverNumber']

        if driver_num is None:
            print(f"  ⚠ Could not find driver number for {driver_abbr}")
            return None

        # Extract driver's position data from dict
        if driver_num not in pos_data:
            print(f"  ⚠ No position data for driver {driver_num} ({driver_abbr})")
            return None

        driver_pos = pos_data[driver_num].copy()
        if len(driver_pos) == 0:
            print(f"  ⚠ Empty position data for {driver_abbr}")
            return None

        # Build light telemetry
        print(f"  → Building light telemetry for {driver_abbr}...")
        telemetry, pit_windows = LightTelemetryBuilder._build_light_telemetry(driver_pos, driver_laps)

        if telemetry is None or len(telemetry) == 0:
            print("  ⚠ Failed to build telemetry")
            return None

        # Extract driver's car data from dict
        driver_car = None
        if car_data is not None and driver_num in car_data:
            driver_car = car_data[driver_num]

        track_data = LightTelemetryBuilder._extract_track_and_pit_light(
            telemetry, pit_windows, driver_car, driver_abbr
        )

        return track_data

    @staticmethod
    def _build_light_telemetry(pos_df: pd.DataFrame, laps_df: pd.DataFrame) -> Tuple[Optional[pl.DataFrame], List[Tuple[float, float]]]:
        """
        Build minimal telemetry for track extraction.

        Output columns: session_time, x, y, z, lap_number

        Args:
            pos_df: Position data from FastF1 (single driver)
            laps_df: Lap data from FastF1 (single driver)

        Returns:
            Tuple of (telemetry DataFrame, pit_windows list)
        """
        # Sort by SessionTime
        pos_df = pos_df.sort_values('SessionTime').reset_index(drop=True)

        # Extract basic columns
        if 'SessionTime' not in pos_df.columns:
            return None, []

        session_times = pos_df['SessionTime'].dt.total_seconds().values.astype(np.float64)
        x = pos_df['X'].values.astype(np.float32) if 'X' in pos_df.columns else np.zeros(len(pos_df), dtype=np.float32)
        y = pos_df['Y'].values.astype(np.float32) if 'Y' in pos_df.columns else np.zeros(len(pos_df), dtype=np.float32)
        z = pos_df['Z'].values.astype(np.float32) if 'Z' in pos_df.columns else np.zeros(len(pos_df), dtype=np.float32)

        # Create initial DataFrame
        telemetry_df = pl.DataFrame({
            'session_time': session_times,
            'x': x,
            'y': y,
            'z': z
        })

        # Add lap_number using lap completion times
        telemetry_df, pit_windows = LightTelemetryBuilder._add_lap_info_light(telemetry_df, laps_df)

        return telemetry_df, pit_windows

    @staticmethod
    def _add_lap_info_light(telemetry_df: pl.DataFrame, laps_df: pd.DataFrame) -> Tuple[pl.DataFrame, List[Tuple[float, float]]]:
        """
        Add lap_number to telemetry using lap completion times.

        Simplified version of TelemetryBuilder._add_lap_info():
        - Only adds lap_number (not compound, tyre_life)
        - Extracts pit windows from PitInTime/PitOutTime

        Args:
            telemetry_df: Polars DataFrame with session_time
            laps_df: FastF1 laps DataFrame

        Returns:
            Tuple of (updated telemetry DataFrame, pit_windows list)
        """
        pit_windows = []

        # Get lap completion times
        if 'LapNumber' not in laps_df.columns:
            telemetry_df = telemetry_df.with_columns(pl.lit(0).cast(pl.Int32).alias('lap_number'))
            return telemetry_df, pit_windows

        lap_nums_arr = laps_df['LapNumber'].values.astype(np.int32)

        if 'Time' in laps_df.columns:
            lap_completion_times = laps_df['Time'].dt.total_seconds().values
        else:
            lap_completion_times = np.full(len(laps_df), np.nan)

        if 'LapStartTime' in laps_df.columns:
            lap_start_times = laps_df['LapStartTime'].dt.total_seconds().values
        else:
            lap_start_times = np.full(len(laps_df), np.nan)

        # Sort by lap completion time
        valid_completion = ~np.isnan(lap_completion_times)
        if not np.any(valid_completion):
            telemetry_df = telemetry_df.with_columns(pl.lit(0).cast(pl.Int32).alias('lap_number'))
            return telemetry_df, pit_windows

        sort_idx = np.argsort(lap_completion_times)
        lap_completion_times = lap_completion_times[sort_idx]
        lap_nums_arr = lap_nums_arr[sort_idx]
        lap_start_times = lap_start_times[sort_idx]

        # Race start time (first lap's start time)
        race_start_time = lap_start_times[0] if not np.isnan(lap_start_times[0]) else 0

        # Get telemetry session times
        session_times = telemetry_df['session_time'].to_numpy()

        # Determine lap_number using lap COMPLETION times
        completed_laps = np.searchsorted(lap_completion_times, session_times, side='right')
        lap_numbers = completed_laps + 1
        lap_numbers[session_times < race_start_time] = 0

        telemetry_df = telemetry_df.with_columns(pl.Series('lap_number', lap_numbers, dtype=pl.Int32))

        # Extract pit windows from PitInTime/PitOutTime
        if 'PitInTime' in laps_df.columns:
            pit_in_series = laps_df['PitInTime'].dropna()
            if len(pit_in_series) > 0:
                pit_in_times = pit_in_series.dt.total_seconds().values
                pit_in_times = np.sort(pit_in_times)
            else:
                pit_in_times = np.array([])
        else:
            pit_in_times = np.array([])

        if 'PitOutTime' in laps_df.columns:
            pit_out_series = laps_df['PitOutTime'].dropna()
            if len(pit_out_series) > 0:
                pit_out_times = pit_out_series.dt.total_seconds().values
                pit_out_times = np.sort(pit_out_times)
            else:
                pit_out_times = np.array([])
        else:
            pit_out_times = np.array([])

        # Pair them up: each pit_in with next pit_out
        if len(pit_in_times) > 0 and len(pit_out_times) > 0:
            out_indices = np.searchsorted(pit_out_times, pit_in_times, side='right')
            for i, pit_in in enumerate(pit_in_times):
                if out_indices[i] < len(pit_out_times):
                    pit_windows.append((float(pit_in), float(pit_out_times[out_indices[i]])))

        return telemetry_df, pit_windows

    @staticmethod
    def _extract_track_and_pit_light(telemetry: pl.DataFrame, pit_windows: List[Tuple[float, float]],
                                     car_df: Optional[pd.DataFrame], driver: str) -> Optional[TrackData]:
        """
        Extract track and pit from light telemetry.

        Adapted from TelemetryBuilder._extract_track_and_pit():
        - Uses lap_number to find racing laps
        - Excludes pit laps using pit_windows
        - Extracts track from fastest clean lap
        - Extracts pit lane from winner's pit windows only
        - Samples car_data for reference lap (speed, throttle, brake)

        Args:
            telemetry: Light telemetry DataFrame
            pit_windows: List of (pit_in_time, pit_out_time) tuples
            car_df: Car data for sampling reference lap telemetry (optional)
            driver: Driver abbreviation for logging

        Returns:
            TrackData or None
        """
        # Extract track from racing laps (lap_number >= 1)
        racing = telemetry.filter(pl.col('lap_number') >= 1)
        if len(racing) == 0:
            print("  ⚠ No racing telemetry found")
            return None

        # Find laps that have pit activity
        pit_laps = set()
        if pit_windows:
            session_times = telemetry['session_time'].to_numpy()
            lap_numbers = telemetry['lap_number'].to_numpy()
            for pit_in, pit_out in pit_windows:
                pit_mask = (session_times >= pit_in) & (session_times < pit_out)
                pit_laps.update(lap_numbers[pit_mask].tolist())

        # Exclude pit laps, out-laps, and lap 1
        pit_out_laps = {lap + 1 for lap in pit_laps}
        exclude_laps = pit_laps | pit_out_laps | {1}

        # Find fastest lap by duration
        lap_times = racing.group_by('lap_number').agg([
            pl.col('session_time').min().alias('start_time'),
            pl.col('session_time').max().alias('end_time'),
            pl.len().alias('n_points')
        ]).with_columns(
            (pl.col('end_time') - pl.col('start_time')).alias('lap_duration')
        ).filter(
            (pl.col('n_points') > 100) &
            (~pl.col('lap_number').is_in(list(exclude_laps)))
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
            return None

        best_lap = lap_times['lap_number'][0]
        lap_duration = lap_times['lap_duration'][0]
        lap_tel = racing.filter(pl.col('lap_number') == best_lap)

        track_x = lap_tel['x'].to_numpy().astype(np.float32)
        track_y = lap_tel['y'].to_numpy().astype(np.float32)
        track_z = lap_tel['z'].to_numpy().astype(np.float32)

        # Sample car data for reference lap (speed, throttle, brake)
        track_speed = None
        track_throttle = None
        track_brake = None

        if car_df is not None and len(car_df) > 0:
            try:
                # Get lap timestamps
                lap_session_times = lap_tel['session_time'].to_numpy()
                car_session_times = car_df['SessionTime'].dt.total_seconds().values

                # Sample car data using nearest-neighbor
                indices = np.searchsorted(car_session_times, lap_session_times)
                indices = np.clip(indices, 0, len(car_df) - 1)

                if 'Speed' in car_df.columns:
                    track_speed = car_df['Speed'].iloc[indices].values.astype(np.float32)
                if 'Throttle' in car_df.columns:
                    track_throttle = car_df['Throttle'].iloc[indices].values.astype(np.float32)
                if 'Brake' in car_df.columns:
                    track_brake = car_df['Brake'].iloc[indices].values.astype(np.float32)
            except Exception:
                pass  # Skip if sampling fails

        # Smooth wrap-around: blend last N points toward first point
        def smooth_wrap(arr, n_blend=10):
            if arr is None or len(arr) < n_blend * 2:
                return arr
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

        print(f"    ✓ Track from {driver} lap {best_lap} ({lap_duration:.1f}s): {len(track_x)} points, {lap_distance_m:.0f}m")

        # Extract pit lane from winner's pit windows
        pit_x, pit_y = None, None
        pit_distance = None
        pit_length = 0.0
        pit_entry_dist, pit_exit_dist = None, None

        if not pit_windows or len(pit_windows) == 0:
            print(f"    ⚠ {driver} did not pit - no pit lane extracted")

        if pit_windows and len(pit_windows) > 0:
            # Get first pit stint
            pit_in, pit_out = pit_windows[0]

            # Expand window to 1 minute before and after
            expand_time = 60.0
            expanded_pit = telemetry.filter(
                (pl.col('session_time') >= pit_in - expand_time) &
                (pl.col('session_time') <= pit_out + expand_time)
            ).sort('session_time')

            if len(expanded_pit) > 10:
                pit_x_raw = expanded_pit['x'].to_numpy().astype(np.float32)
                pit_y_raw = expanded_pit['y'].to_numpy().astype(np.float32)

                # Create temporary TrackGeometry for projection
                temp_track = TrackGeometry(
                    x=track_x, y=track_y,
                    distance=track_dist_m,
                    lap_distance=lap_distance_m
                )

                # Project pit points onto track
                pit_track_dist = temp_track.progress_on_track(pit_x_raw, pit_y_raw)
                pit_dist_to_track = temp_track.distance_to_track(pit_x_raw, pit_y_raw)

                # Find pit start/end indices
                expanded_times = expanded_pit['session_time'].to_numpy()
                is_pit = (expanded_times >= pit_in) & (expanded_times < pit_out)
                pit_indices = np.where(is_pit)[0]

                if len(pit_indices) > 0:
                    pit_start_idx = pit_indices[0]
                    pit_end_idx = pit_indices[-1]

                    # Find entry/exit points (where pit lane merges with track)
                    threshold_dm = 5.0  # 0.5m
                    on_track_mask = pit_dist_to_track < threshold_dm

                    # Entry: last point before pit_start that's on track
                    before_pit = np.where(on_track_mask[:pit_start_idx + 1])[0]
                    entry_idx = before_pit[-1] if len(before_pit) > 0 else 0

                    # Exit: first point after pit_end that's on track
                    after_pit = np.where(on_track_mask[pit_end_idx:])[0]
                    exit_idx = pit_end_idx + after_pit[0] if len(after_pit) > 0 else len(pit_x_raw) - 1

                    pit_entry_dist = float(pit_track_dist[entry_idx])
                    pit_exit_dist = float(pit_track_dist[exit_idx])

                    # Trim pit lane
                    pit_x_trimmed = pit_x_raw[entry_idx:exit_idx + 1]
                    pit_y_trimmed = pit_y_raw[entry_idx:exit_idx + 1]

                    # Decimate pit points (minimum 0.5m spacing)
                    if len(pit_x_trimmed) > 2:
                        dx = np.diff(pit_x_trimmed)
                        dy = np.diff(pit_y_trimmed)
                        point_distances = np.sqrt(dx**2 + dy**2)
                        cumsum_dist = np.concatenate([[0], np.cumsum(point_distances)])

                        min_dist_dm = 5.0  # 0.5m
                        bucket = (cumsum_dist / min_dist_dm).astype(np.int32)

                        keep_mask = np.zeros(len(pit_x_trimmed), dtype=bool)
                        keep_mask[0] = True
                        keep_mask[-1] = True
                        bucket_changes = np.concatenate([[True], bucket[1:] != bucket[:-1]])
                        keep_mask |= bucket_changes

                        pit_x = pit_x_trimmed[keep_mask]
                        pit_y = pit_y_trimmed[keep_mask]
                    else:
                        pit_x = pit_x_trimmed
                        pit_y = pit_y_trimmed

                    # Calculate pit lane distance
                    pit_dx = np.diff(pit_x, prepend=pit_x[0])
                    pit_dy = np.diff(pit_y, prepend=pit_y[0])
                    pit_distances = np.sqrt(pit_dx**2 + pit_dy**2)
                    pit_distances[0] = 0
                    pit_distance = (np.cumsum(pit_distances) / 10.0).astype(np.float32)  # meters
                    pit_length = float(pit_distance[-1])

                    print(f"    ✓ Pit lane from {driver}: {len(pit_x)} points, {pit_length:.0f}m (entry={pit_entry_dist:.0f}m, exit={pit_exit_dist:.0f}m)")

        # Return TrackData
        return TrackData(
            track_x=track_x,
            track_y=track_y,
            track_z=track_z,
            track_distance=track_dist,  # decimeters
            lap_distance=lap_distance,  # decimeters
            pit_x=pit_x,
            pit_y=pit_y,
            pit_distance=pit_distance,  # meters
            pit_length=pit_length,  # meters
            pit_entry_distance=pit_entry_dist,  # meters
            pit_exit_distance=pit_exit_dist,  # meters
            marshal_sectors=[],  # Not extracted in light mode
            speed=track_speed,
            throttle=track_throttle,
            brake=track_brake
        )
