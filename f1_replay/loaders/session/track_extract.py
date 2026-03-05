"""
Track & Pit Extraction - Extract track/pit geometry from telemetry.

Extracted from TelemetryBuilder to reduce file size.
Functions operate on telemetry DataFrames and return TrackData.
"""

from typing import Dict, Optional, Tuple

import numpy as np
import polars as pl

from f1_replay.loaders.session.telemetry import TrackData
from f1_replay.log import logger


def extract_track_and_pit(
    telemetry: Dict[str, pl.DataFrame],
    winner: Optional[str],
    status_data_all: Optional[Dict[str, dict]] = None,
) -> Tuple[Optional[TrackData], Optional[dict]]:
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
        Tuple of:
        - TrackData with track and pit geometry (or None)
        - Session timing dict with {warmup_start_time} (or None)
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
    logger.info(f"  → Extracting track/pit from {driver}")

    # Extract track from racing laps (lap_number >= 1)
    racing = tel.filter(pl.col("lap_number") >= 1)
    if len(racing) == 0:
        logger.warning("  ⚠ No racing telemetry found")
        return None, None

    # Find laps that have pit activity using pit_windows from status_data
    pit_laps = set()
    if status_data_all and driver in status_data_all:
        driver_status = status_data_all[driver]
        driver_pit_windows = driver_status.get("pit_windows", [])
        if driver_pit_windows:
            session_times = tel["session_time"].to_numpy()
            lap_numbers = tel["lap_number"].to_numpy()
            for pit_in, pit_out in driver_pit_windows:
                pit_mask = (session_times >= pit_in) & (session_times < pit_out)
                pit_laps.update(lap_numbers[pit_mask].tolist())

    # Also exclude the lap after pit (out-lap) - typically has slower exit
    pit_out_laps = {lap + 1 for lap in pit_laps}
    # Exclude lap 1 (first racing lap, often includes grid start anomalies)
    exclude_laps = pit_laps | pit_out_laps | {1}

    # Find fastest lap by calculating lap duration from telemetry
    lap_times = (
        racing.group_by("lap_number")
        .agg(
            [
                pl.col("session_time").min().alias("start_time"),
                pl.col("session_time").max().alias("end_time"),
                pl.len().alias("n_points"),
            ]
        )
        .with_columns((pl.col("end_time") - pl.col("start_time")).alias("lap_duration"))
        .filter(
            (pl.col("n_points") > 100)  # Must have reasonable telemetry coverage
            & (~pl.col("lap_number").is_in(list(exclude_laps)))  # Exclude pit/out laps and lap 1
        )
        .sort("lap_duration")
    )

    # Fallback: if no clean laps, try without excluding pit laps
    if len(lap_times) == 0:
        logger.warning("  ⚠ No clean laps, falling back to any racing lap")
        lap_times = (
            racing.group_by("lap_number")
            .agg(
                [
                    pl.col("session_time").min().alias("start_time"),
                    pl.col("session_time").max().alias("end_time"),
                    pl.len().alias("n_points"),
                ]
            )
            .with_columns((pl.col("end_time") - pl.col("start_time")).alias("lap_duration"))
            .filter(pl.col("n_points") > 100)
            .sort("lap_duration")
        )

    if len(lap_times) == 0:
        logger.warning("  ⚠ No valid laps found")
        return None, None

    best_lap = lap_times["lap_number"][0]
    lap_duration = lap_times["lap_duration"][0]
    lap_tel = racing.filter(pl.col("lap_number") == best_lap)

    track_x = lap_tel["x"].to_numpy().astype(np.float32)
    track_y = lap_tel["y"].to_numpy().astype(np.float32)
    track_z = lap_tel["z"].to_numpy().astype(np.float32) if "z" in lap_tel.columns else None

    # Extract speed, throttle, brake from the reference lap
    track_speed = (
        lap_tel["speed"].to_numpy().astype(np.float32) if "speed" in lap_tel.columns else None
    )
    track_throttle = (
        lap_tel["throttle"].to_numpy().astype(np.float32) if "throttle" in lap_tel.columns else None
    )
    track_brake = (
        lap_tel["brake"].to_numpy().astype(np.float32) if "brake" in lap_tel.columns else None
    )

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

    logger.info(
        f"    ✓ Track from lap {best_lap} ({lap_duration:.1f}s): {len(track_x)} points, {lap_distance_m:.0f}m"
    )

    # Extract pit lane - find a driver who actually pitted
    # Race winner may not have pitted, so search all drivers for pit data
    # Use pit_windows from status_data for reliable pit detection
    pit_tel = None
    pit_driver = None
    pit_windows_for_extraction = []

    if status_data_all:
        for d, d_tel in telemetry.items():
            d_status = status_data_all.get(d, {})
            d_pit_windows = d_status.get("pit_windows", [])
            if d_pit_windows and len(d_pit_windows) > 0:
                # Use pit_windows to filter telemetry to pit times
                session_times = d_tel["session_time"].to_numpy()
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
        pit_times = pit_tel["session_time"].to_numpy()
        time_gaps = np.diff(pit_times)
        # Find where gap > 60s (new pit stop)
        gap_indices = np.where(time_gaps > 60)[0]
        end_idx = gap_indices[0] + 1 if len(gap_indices) > 0 else len(pit_tel)

        first_pit = pit_tel.head(end_idx)
        pit_start_time = first_pit["session_time"][0]
        pit_end_time = first_pit["session_time"][-1]

        # Expand window to 1 minute before and after pit stint
        expand_time = 60.0  # seconds
        expanded_pit = tel_for_pit.filter(
            (pl.col("session_time") >= pit_start_time - expand_time)
            & (pl.col("session_time") <= pit_end_time + expand_time)
        ).sort("session_time")

        pit_x_raw = expanded_pit["x"].to_numpy().astype(np.float32)
        pit_y_raw = expanded_pit["y"].to_numpy().astype(np.float32)

        if len(pit_x_raw) > 1:
            # Create temporary TrackGeometry for projection
            temp_track = TrackGeometry(
                x=track_x, y=track_y, distance=track_dist_m, lap_distance=lap_distance_m
            )

            # Project all points onto track
            pit_track_dist = temp_track.progress_on_track(pit_x_raw, pit_y_raw)
            pit_dist_to_track = temp_track.distance_to_track(pit_x_raw, pit_y_raw)

            # Find where pit status starts/ends in the expanded window (vectorized)
            # Use pit_windows for reliable pit detection
            expanded_times = expanded_pit["session_time"].to_numpy()
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
            before_pit_on_track = np.where(on_track_mask[: pit_start_idx + 1])[0]
            entry_idx = before_pit_on_track[-1] if len(before_pit_on_track) > 0 else 0

            # Vectorized: find exit point (first point after pit_end that's on track)
            after_pit_on_track = np.where(on_track_mask[pit_end_idx:])[0]
            exit_idx = (
                pit_end_idx + after_pit_on_track[0]
                if len(after_pit_on_track) > 0
                else len(pit_x_raw) - 1
            )

            pit_entry_dist = float(pit_track_dist[entry_idx])
            pit_exit_dist = float(pit_track_dist[exit_idx])

            # Trim pit lane to entry/exit merge points
            pit_x_trimmed = pit_x_raw[entry_idx : exit_idx + 1]
            pit_y_trimmed = pit_y_raw[entry_idx : exit_idx + 1]

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

            logger.info(
                f"    ✓ Pit lane from {pit_driver}: {len(pit_x)} points, {pit_length:.0f}m (entry={pit_entry_dist:.0f}m, exit={pit_exit_dist:.0f}m)"
            )

    # Detect warmup start from winner's telemetry (using wrap-based approach)
    warmup_start_time = None

    tel = telemetry.get(driver)
    if tel is not None and "lap_number" in tel.columns and "session_time" in tel.columns:
        lap_numbers = tel["lap_number"].to_numpy()
        session_times = tel["session_time"].to_numpy()
        px = tel["x"].to_numpy().astype(np.float32)
        py = tel["y"].to_numpy().astype(np.float32)
        pz = tel["z"].to_numpy().astype(np.float32) if "z" in tel.columns else np.zeros(len(tel))

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
                                logger.info(
                                    f"    ✓ Warmup detection: Grid {grid_duration:.1f}s, "
                                    f"starts at {warmup_start_time:.1f}s, duration: {warmup_duration:.1f}s"
                                )
                                found_grid = True
                                break

                        if found_grid:
                            break

            if not found_grid:
                logger.warning("    ⚠ Could not detect warmup start (no grid position found)")

    # Build session timing dict
    session_timing = (
        {"warmup_start_time": warmup_start_time} if warmup_start_time is not None else None
    )

    track_data = TrackData(
        track_x=track_x,
        track_y=track_y,
        track_distance=track_dist,  # Keep in decimeters, dataloader converts
        lap_distance=lap_distance,  # Keep in decimeters
        pit_x=pit_x,
        pit_y=pit_y,
        pit_distance=pit_distance,  # In meters
        pit_length=pit_length,  # In meters
        pit_entry_distance=pit_entry_dist,  # In meters
        pit_exit_distance=pit_exit_dist,  # In meters
        speed=track_speed,
        throttle=track_throttle,
        brake=track_brake,
        track_z=track_z,
    )

    return track_data, session_timing


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
    from f1_replay.loaders.session.telemetry import TelemetryBuilder

    pos_data = getattr(f1_session, "pos_data", None)
    car_data = getattr(f1_session, "car_data", None)
    laps = getattr(f1_session, "laps", None)

    if pos_data is None:
        logger.warning("  ⚠ No position data available")
        return None

    # Build driver map and find driver's number
    driver_map = TelemetryBuilder._build_driver_map(f1_session)
    driver_num = None
    for num, code in driver_map.items():
        if code == driver:
            driver_num = num
            break

    if driver_num is None:
        logger.warning(f"  ⚠ Driver {driver} not found in session")
        return None

    # Get position data for this driver
    pos_df = pos_data.get(driver_num)
    if pos_df is None:
        logger.warning(f"  ⚠ No position data for {driver}")
        return None

    # Get car data (may be None)
    car_df = car_data.get(driver_num) if car_data else None

    # Get driver's laps
    driver_laps = None
    if laps is not None and "Driver" in laps.columns:
        driver_laps = laps[laps["Driver"] == driver]

    # Get race length
    race_length = 0
    if laps is not None and len(laps) > 0 and "LapNumber" in laps.columns:
        race_length = int(laps["LapNumber"].max())

    # Build telemetry for this driver
    tel, _ = TelemetryBuilder._build_driver_telemetry(pos_df, car_df, driver_laps, race_length)
    if tel is None or len(tel) == 0:
        logger.warning(f"  ⚠ Could not build telemetry for {driver}")
        return None

    # Extract track and pit from this driver's telemetry
    track_data, _ = extract_track_and_pit({driver: tel}, driver)

    # Extract marshal sectors from circuit info
    if track_data is not None:
        track_data = add_marshal_sectors(f1_session, track_data)

    return track_data


def add_marshal_sectors(f1_session, track_data: TrackData) -> TrackData:
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
        if circuit_info is None or not hasattr(circuit_info, "marshal_sectors"):
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
        sector_nums = marshal_df["Number"].values.astype(np.int32)
        sector_x = marshal_df["X"].values.astype(np.float32)
        sector_y = marshal_df["Y"].values.astype(np.float32)

        # Broadcasting: compute distances from all sectors to all track points
        # sector_x[:, None] shape: (n_sectors, 1), track_x[None, :] shape: (1, n_track)
        # Result shape: (n_sectors, n_track)
        dist_sq = (sector_x[:, None] - track_x[None, :]) ** 2 + (
            sector_y[:, None] - track_y[None, :]
        ) ** 2
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
            logger.info(f"    ✓ Marshal sectors: {len(marshal_sectors)}")

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
            track_z=track_data.track_z,
        )

    except Exception as e:
        logger.warning(f"    ⚠ Could not extract marshal sectors: {e}")
        return track_data
