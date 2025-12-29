"""
RaceWeekend - High-level wrapper for F1Weekend data.

Provides convenient property-based access to weekend metadata and circuit geometry.
"""

from typing import Dict, List, Optional
import math
import numpy as np

from f1_replay.data_loader.data_models import F1Weekend, TrackGeometry, TrackSegment


class RaceWeekend:
    """
    Wraps F1Weekend data model, provides convenient access to circuit geometry and metadata.

    Usage:
        weekend = RaceWeekend(f1_weekend_obj)
        print(f"{weekend.event_name} at {weekend.location}")
        track_coords = weekend.get_track_coords()
    """

    def __init__(self, weekend: F1Weekend):
        """
        Initialize from F1Weekend data model.

        Args:
            weekend: F1Weekend immutable dataclass
        """
        self._weekend = weekend

    # =========================================================================
    # Metadata Properties
    # =========================================================================

    @property
    def year(self) -> int:
        """Get season year."""
        return self._weekend.metadata.year

    @property
    def round_number(self) -> int:
        """Get race round number."""
        return self._weekend.metadata.round_number

    @property
    def event_name(self) -> str:
        """Get event name (e.g., 'Abu Dhabi Grand Prix')."""
        return self._weekend.metadata.event_name

    @property
    def location(self) -> str:
        """Get location (e.g., 'Yas Island')."""
        return self._weekend.metadata.location

    @property
    def country(self) -> str:
        """Get country (e.g., 'United Arab Emirates')."""
        return self._weekend.metadata.country

    @property
    def circuit_name(self) -> str:
        """Get circuit name (e.g., 'Yas Marina Circuit')."""
        return self._weekend.metadata.circuit_name

    @property
    def timezone(self) -> str:
        """Get timezone (e.g., 'UTC+4')."""
        return self._weekend.metadata.timezone

    @property
    def event_date(self) -> str:
        """Get event date in ISO format (e.g., '2024-12-08')."""
        return self._weekend.metadata.event_date

    @property
    def available_sessions(self) -> List[str]:
        """Get list of available sessions (e.g., ['FP1', 'FP2', 'FP3', 'Q', 'R'])."""
        return self._weekend.metadata.available_sessions

    # =========================================================================
    # Circuit Properties
    # =========================================================================

    @property
    def circuit(self):
        """Get underlying CircuitData object."""
        return self._weekend.circuit

    @property
    def track(self) -> TrackGeometry:
        """Get track geometry."""
        return self._weekend.circuit.track

    @property
    def pit_lane(self) -> Optional[TrackGeometry]:
        """Get pit lane geometry (may be None if unavailable)."""
        return self._weekend.circuit.pit_lane

    @property
    def circuit_length(self) -> float:
        """Get circuit length in meters."""
        return self._weekend.circuit.circuit_length

    @property
    def corners(self) -> int:
        """Get number of corners on the circuit."""
        return self._weekend.circuit.corners

    @property
    def track_segments(self) -> List[TrackSegment]:
        """Get track segments (sectors, DRS zones, etc.)."""
        return self._weekend.circuit.track_segments

    @property
    def rotation(self) -> float:
        """Get track rotation in degrees (from FastF1)."""
        return self._weekend.circuit.rotation

    # =========================================================================
    # Query Methods
    # =========================================================================

    def get_track_coords(self) -> Dict[str, list]:
        """
        Get track coordinates as JSON-friendly lists.

        Returns:
            Dict with keys 'x', 'y', 'distance' (if available), 'lap_distance'
        """
        result = {
            'x': self.track.x.tolist() if isinstance(self.track.x, np.ndarray) else self.track.x,
            'y': self.track.y.tolist() if isinstance(self.track.y, np.ndarray) else self.track.y,
            'lap_distance': float(self.track.lap_distance)
        }

        if self.track.distance is not None:
            result['distance'] = (
                self.track.distance.tolist()
                if isinstance(self.track.distance, np.ndarray)
                else self.track.distance
            )

        return result

    def get_pit_lane_coords(self) -> Optional[Dict[str, list]]:
        """
        Get pit lane coordinates as JSON-friendly lists.

        Returns:
            Dict with keys 'x', 'y', 'lap_distance' or None if pit lane unavailable
        """
        if self.pit_lane is None:
            return None

        return {
            'x': self.pit_lane.x.tolist() if isinstance(self.pit_lane.x, np.ndarray) else self.pit_lane.x,
            'y': self.pit_lane.y.tolist() if isinstance(self.pit_lane.y, np.ndarray) else self.pit_lane.y,
            'lap_distance': float(self.pit_lane.lap_distance)
        }

    def get_sectors(self) -> List[TrackSegment]:
        """
        Get marshal sectors (filter segments by type='sector').

        Returns:
            List of TrackSegment objects where segment_type='sector'
        """
        return [seg for seg in self.track_segments if seg.segment_type == 'sector']

    def get_drs_zones(self) -> List[TrackSegment]:
        """
        Get DRS zones (filter segments by type='drs_zone').

        Returns:
            List of TrackSegment objects where segment_type='drs_zone'
        """
        return [seg for seg in self.track_segments if seg.segment_type == 'drs_zone']

    def __repr__(self) -> str:
        """String representation."""
        return f"RaceWeekend({self.year} R{self.round_number}: {self.event_name})"
