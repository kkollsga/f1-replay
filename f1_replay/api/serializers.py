"""
JSON Serialization utilities for Flask API.

Converts Polars DataFrames, NumPy arrays, and custom types to JSON-safe formats.
Handles telemetry field filtering and optimized payload generation.
"""

from typing import Any, Dict, Optional, List
from dataclasses import asdict, is_dataclass
import numpy as np
import polars as pl


def to_json_safe(obj: Any) -> Any:
    """
    Recursively convert objects to JSON-safe types.

    Handles:
    - Dataclass objects → dicts
    - TrackStatusWithReport → underlying DataFrame
    - Polars DataFrames → list of dicts
    - NumPy arrays → lists
    - NumPy/Python scalar types → Python primitives
    - Timedelta → seconds (float)
    - NaN/Inf → None
    - Dicts and lists → recursively converted

    Args:
        obj: Object to convert

    Returns:
        JSON-safe representation
    """
    # Dataclass objects - convert to dict then recursively process
    if is_dataclass(obj) and not isinstance(obj, type):
        return to_json_safe(asdict(obj))

    # TrackStatusWithReport wrapper - extract underlying DataFrame
    if hasattr(obj, '_df') and isinstance(getattr(obj, '_df', None), pl.DataFrame):
        return to_json_safe(obj._df)

    # Polars DataFrame - convert to dicts then recursively process
    if isinstance(obj, pl.DataFrame):
        dicts = obj.to_dicts()
        return [to_json_safe(d) for d in dicts]

    # NumPy array
    if isinstance(obj, np.ndarray):
        return [to_json_safe(item) for item in obj.tolist()]

    # NumPy scalar types
    if isinstance(obj, (np.integer, np.floating)):
        val = obj.item()
        if isinstance(val, float):
            if np.isnan(val) or np.isinf(val):
                return None
        return val

    # Python numeric types that might be NaN or Inf
    if isinstance(obj, float):
        if np.isnan(obj) or np.isinf(obj):
            return None
        return obj

    # Timedelta
    if hasattr(obj, 'total_seconds'):
        return obj.total_seconds()

    # Dict - recursively convert values
    if isinstance(obj, dict):
        return {k: to_json_safe(v) for k, v in obj.items()}

    # List - recursively convert items
    if isinstance(obj, (list, tuple)):
        return [to_json_safe(item) for item in obj]

    # Already JSON-safe
    return obj


def serialize_telemetry(telemetry_dict: Dict[str, pl.DataFrame],
                       fields: Optional[List[str]] = None) -> Dict[str, Dict]:
    """
    Serialize telemetry with field filtering and optimization.

    Args:
        telemetry_dict: Dict mapping driver code to telemetry DataFrame
        fields: Specific fields to include. If None, uses default essential fields.

    Returns:
        {driver_code: {field: [values]}}
        e.g., {'VER': {'session_time': [0.0, 0.076, ...], 'lap_number': [1, 1, ...]}}
    """
    if fields is None:
        # Default fields for race visualization (snake_case)
        fields = [
            'session_time', 'lap_number', 'x', 'y',
            'track_distance', 'race_distance', 'position', 'interval',
            'status', 'compound', 'tyre_life', 'speed',
            'vx', 'vy'  # Velocity vectors for Hermite interpolation
        ]

    # Fields that should be rounded to reduce JSON size
    ROUND_PRECISION = {
        'session_time': 2,  # 0.01s precision
        'x': 1,             # 0.1 decimeter precision
        'y': 1,             # 0.1 decimeter precision
        'track_distance': 1,  # 0.1m precision
        'race_distance': 1,   # 0.1m precision
        'interval': 3,        # 0.001s precision
        'speed': 1,           # 0.1 km/h precision
        'vx': 1,              # 0.1 dm/s precision
        'vy': 1,              # 0.1 dm/s precision
    }

    result = {}

    for driver, tel_df in telemetry_dict.items():
        # Filter to available fields
        available_fields = [f for f in fields if f in tel_df.columns]

        if not available_fields:
            result[driver] = {}
            continue

        # Select only needed columns and convert to dict efficiently
        subset_df = tel_df.select(available_fields)
        driver_data = {}
        for field in available_fields:
            col = subset_df[field]
            # Use Polars native conversion - much faster than per-item
            if col.dtype in (pl.Float32, pl.Float64):
                # Round floats to reduce JSON size
                precision = ROUND_PRECISION.get(field)
                if precision is not None:
                    col = col.round(precision)
                driver_data[field] = col.fill_nan(None).to_list()
            else:
                driver_data[field] = col.to_list()

        result[driver] = driver_data

    return result


def serialize_track_geometry(track) -> Dict[str, Any]:
    """
    Serialize track/pit lane geometry to JSON-safe dict.

    Args:
        track: TrackGeometry (with lap_distance) or PitLane (with length)

    Returns:
        {x: [], y: [], distance: [] (optional), lap_distance: float}
    """
    if track is None:
        return None

    result = {
        'x': track.x.tolist() if isinstance(track.x, np.ndarray) else (track.x if track.x is not None else []),
        'y': track.y.tolist() if isinstance(track.y, np.ndarray) else (track.y if track.y is not None else []),
    }

    # Handle both TrackGeometry (lap_distance) and PitLane (length)
    if hasattr(track, 'lap_distance'):
        result['lap_distance'] = float(track.lap_distance) if track.lap_distance else 0.0
    elif hasattr(track, 'length'):
        result['lap_distance'] = float(track.length) if track.length else 0.0
    else:
        result['lap_distance'] = 0.0

    if track.distance is not None:
        result['distance'] = (
            track.distance.tolist() if isinstance(track.distance, np.ndarray)
            else track.distance
        )

    return result


def serialize_events(events) -> Dict[str, List[Dict]]:
    """
    Serialize all event DataFrames to JSON-safe format.

    Args:
        events: EventsData object with track_status, race_control, status_messages DataFrames

    Returns:
        {
            'track_status': [...],
            'race_control': [...],
            'status_messages': [...]
        }
    """
    return {
        'track_status': to_json_safe(events.track_status),
        'race_control': to_json_safe(events.race_control),
        'status_messages': to_json_safe(events.status_messages),
    }


def serialize_rain_events(rain_df: pl.DataFrame) -> List[Dict]:
    """
    Serialize rain events DataFrame to JSON-safe list.

    Args:
        rain_df: Rain events DataFrame with columns: start_time, end_time, duration

    Returns:
        [{start_time, end_time, duration}, ...]
    """
    return to_json_safe(rain_df)


def serialize_position_history(position_history) -> List[Dict]:
    """
    Serialize position history snapshots to JSON-safe format.

    Args:
        position_history: List of PositionSnapshot objects

    Returns:
        [{time, lap, standings: [{position, driver, gap}]}, ...]
    """
    result = []
    for snapshot in position_history:
        standings = [
            {
                'position': entry.position,
                'driver': entry.driver,
                'gap': to_json_safe(entry.gap)  # Convert gap (may be NaN/Inf)
            }
            for entry in snapshot.standings
        ]
        result.append({
            'time': to_json_safe(snapshot.time),  # Convert time (may be NaN/Inf)
            'lap': snapshot.lap,
            'standings': standings
        })
    return result


def serialize_fastest_laps(fastest_laps) -> List[Dict]:
    """
    Serialize fastest lap events to JSON-safe format.

    Args:
        fastest_laps: List of FastestLapEvent objects

    Returns:
        [{lap, driver, time, lap_time_ms, session_time}, ...]
    """
    result = []
    for event in fastest_laps:
        result.append({
            'lap': event.lap,
            'driver': event.driver,
            'time': to_json_safe(event.time),  # Convert time (may be NaN/Inf)
            'lap_time_ms': event.lap_time_ms,
            'session_time': to_json_safe(event.session_time)  # Time when lap was completed
        })
    return result
