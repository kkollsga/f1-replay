"""
Weekend and circuit data models.

TIER 2: F1Weekend with circuit geometry for track visualization.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, TYPE_CHECKING
import numpy as np
from scipy.spatial import cKDTree

from f1_replay.models.base import F1DataMixin

if TYPE_CHECKING:
    from f1_replay.models.event import EventInfo


@dataclass(frozen=True)
class MarshalSector(F1DataMixin):
    """Marshal sector boundary (used for yellow flag zones)."""
    number: int  # Sector number (1-based)
    start_distance: float  # Start distance in meters
    end_distance: float  # End distance in meters

    def __repr__(self) -> str:
        return f"MarshalSector({self.number}: {self.start_distance:.0f}m-{self.end_distance:.0f}m)"


@dataclass(frozen=True)
class Corner(F1DataMixin):
    """Track corner marker."""
    number: int  # Corner number (1-based)
    distance: float  # Track distance in meters
    angle: float  # Corner angle in degrees
    letter: str = ""  # Optional letter suffix (e.g., 'A', 'B' for chicanes)

    def __repr__(self) -> str:
        suffix = self.letter if self.letter else ""
        return f"Corner({self.number}{suffix} @ {self.distance:.0f}m, {self.angle:.0f}°)"


@dataclass(frozen=True)
class TrackGeometry(F1DataMixin):
    """
    Track or pit lane coordinates with distance in meters.

    Coordinates (x, y) are in FastF1's decimeter units.
    Distance array is converted to meters for convenience.

    Provides vectorized methods for projecting points onto track:
    - progress_on_track(x, y): Get track distance for each point
    - distance_to_track(x, y): Get perpendicular distance to track
    """
    x: np.ndarray  # float32 array of X coordinates (decimeters)
    y: np.ndarray  # float32 array of Y coordinates (decimeters)
    distance: Optional[np.ndarray] = None  # float32 cumulative distance in METERS
    lap_distance: float = 0.0  # Total lap distance in METERS
    marshal_sectors: List[MarshalSector] = field(default_factory=list)
    # Reference lap telemetry (from winner's fastest lap)
    speed: Optional[np.ndarray] = None  # km/h at each track point
    throttle: Optional[np.ndarray] = None  # 0-100% at each track point
    brake: Optional[np.ndarray] = None  # 0-100 at each track point
    z: Optional[np.ndarray] = None  # Height/elevation at each track point (decimeters)

    def __repr__(self) -> str:
        n = len(self.x) if self.x is not None else 0
        sectors = f", {len(self.marshal_sectors)} sectors" if self.marshal_sectors else ""
        return f"TrackGeometry({n} points, {self.lap_distance:.0f}m{sectors})"

    def get_full_track(self) -> tuple:
        """Return full track coordinates (x, y arrays)."""
        return self.x, self.y

    def progress_on_track(self, px: np.ndarray, py: np.ndarray) -> np.ndarray:
        """
        Get track progress (distance along track) for each point.

        Uses perpendicular projection: finds where a 90° line from track
        hits each point. If multiple perpendiculars hit, uses closest one.

        Args:
            px, py: Point coordinates (N points, in decimeters)

        Returns:
            Track distance for each point (N values, in meters, wrapped to [0, lap_distance))
        """
        track_dist, _ = self._project_perpendicular(px, py)
        return track_dist

    def distance_to_track(self, px: np.ndarray, py: np.ndarray) -> np.ndarray:
        """
        Get perpendicular distance from track for each point.

        Uses perpendicular projection: finds where a 90° line from track
        hits each point. If multiple perpendiculars hit, uses closest one.

        Args:
            px, py: Point coordinates (N points, in decimeters)

        Returns:
            Distance to track for each point (N values, in decimeters)
        """
        _, dist_to_track = self._project_perpendicular(px, py)
        return dist_to_track

    def _project_perpendicular(self, px: np.ndarray, py: np.ndarray) -> tuple:
        """
        Optimized perpendicular projection onto track segments using KD-tree.

        Uses spatial indexing to find nearby track points first, then only
        computes perpendicular projection for adjacent segments. This reduces
        complexity from O(N×M) to O(N×K×log(M)) where K is small.

        For each point:
        1. Find K nearest track points using KD-tree
        2. Get segments adjacent to those points
        3. Calculate perpendicular from those segments only
        4. Pick the segment with minimum perpendicular distance

        Args:
            px, py: Point coordinates (N points, in decimeters)

        Returns:
            Tuple of (track_distance, distance_to_track) arrays
        """
        if self.x is None or len(self.x) == 0 or self.distance is None:
            n = len(px) if hasattr(px, '__len__') else 1
            return np.zeros(n, dtype=np.float32), np.zeros(n, dtype=np.float32)

        px = np.asarray(px, dtype=np.float32)
        py = np.asarray(py, dtype=np.float32)
        n_points = len(px)
        n_track = len(self.x)

        # For small inputs, use simple vectorized approach (KD-tree overhead not worth it)
        if n_points * n_track < 10000:
            return self._project_perpendicular_simple(px, py)

        # Build KD-tree from track points (cache for reuse)
        if not hasattr(self, '_kdtree') or self._kdtree is None:
            track_points = np.column_stack([self.x, self.y])
            object.__setattr__(self, '_kdtree', cKDTree(track_points))

        # Close the track loop for segment calculations
        track_x = np.concatenate([self.x, self.x[:1]])
        track_y = np.concatenate([self.y, self.y[:1]])
        track_dist = np.concatenate([self.distance, [self.lap_distance]])
        n_segments = n_track  # One segment per point (wrapping)

        # Precompute segment vectors
        seg_dx = track_x[1:] - track_x[:-1]
        seg_dy = track_y[1:] - track_y[:-1]
        seg_len_sq = seg_dx**2 + seg_dy**2 + 1e-10

        # Find K nearest track points for each query point
        k_neighbors = min(16, n_track)  # Check 16 nearest points (8 segments each side)
        query_points = np.column_stack([px, py])
        _, nearest_indices = self._kdtree.query(query_points, k=k_neighbors)

        # Ensure 2D even for single point
        if n_points == 1:
            nearest_indices = nearest_indices.reshape(1, -1)

        # Build candidate segments for each point: both segment starting at point and previous segment
        # Shape: (n_points, k_neighbors * 2)
        seg_at_point = nearest_indices % n_segments
        seg_before_point = (nearest_indices - 1) % n_segments
        candidate_segs = np.concatenate([seg_at_point, seg_before_point], axis=1)

        # For each point, we have 2*k candidate segments (with duplicates)
        # Vectorized: compute projection for all (point, segment) pairs
        n_candidates = candidate_segs.shape[1]

        # Expand point coordinates: (n_points, n_candidates)
        px_exp = np.broadcast_to(px[:, np.newaxis], (n_points, n_candidates))
        py_exp = np.broadcast_to(py[:, np.newaxis], (n_points, n_candidates))

        # Get segment data for all candidates: (n_points, n_candidates)
        seg_start_x = track_x[candidate_segs]
        seg_start_y = track_y[candidate_segs]
        seg_dx_cand = seg_dx[candidate_segs]
        seg_dy_cand = seg_dy[candidate_segs]
        seg_len_sq_cand = seg_len_sq[candidate_segs]

        # Vector from segment start to point
        to_point_x = px_exp - seg_start_x
        to_point_y = py_exp - seg_start_y

        # Projection parameter t, clamped to [0, 1]
        t_raw = (to_point_x * seg_dx_cand + to_point_y * seg_dy_cand) / seg_len_sq_cand
        t_clamped = np.clip(t_raw, 0, 1)

        # Closest point on each segment
        closest_x = seg_start_x + t_clamped * seg_dx_cand
        closest_y = seg_start_y + t_clamped * seg_dy_cand

        # Distance squared to closest point
        dist_sq = (px_exp - closest_x)**2 + (py_exp - closest_y)**2

        # Find best segment for each point
        best_cand_idx = np.argmin(dist_sq, axis=1)  # (n_points,)
        row_idx = np.arange(n_points)

        best_seg = candidate_segs[row_idx, best_cand_idx]
        best_t = t_clamped[row_idx, best_cand_idx]
        best_dist = np.sqrt(dist_sq[row_idx, best_cand_idx])

        # Interpolate track distance
        best_track_dist = track_dist[best_seg] + best_t * (track_dist[best_seg + 1] - track_dist[best_seg])

        # Wrap to [0, lap_distance)
        best_track_dist = np.mod(best_track_dist, self.lap_distance).astype(np.float32)

        return best_track_dist, best_dist.astype(np.float32)

    def _project_perpendicular_simple(self, px: np.ndarray, py: np.ndarray) -> tuple:
        """
        Simple vectorized perpendicular projection (for small inputs).

        Creates full (N×M) matrices - efficient for small N×M products.
        """
        # Close the track loop
        track_x = np.concatenate([self.x, self.x[:1]])
        track_y = np.concatenate([self.y, self.y[:1]])
        track_dist = np.concatenate([self.distance, [self.lap_distance]])

        n_points = len(px)

        # Segment vectors: (M,)
        seg_dx = track_x[1:] - track_x[:-1]
        seg_dy = track_y[1:] - track_y[:-1]
        seg_len_sq = seg_dx**2 + seg_dy**2 + 1e-10

        # Vector from segment start to each point: (N, M)
        to_point_x = px[:, np.newaxis] - track_x[:-1]
        to_point_y = py[:, np.newaxis] - track_y[:-1]

        # Projection parameter t: (N, M)
        t_raw = (to_point_x * seg_dx + to_point_y * seg_dy) / seg_len_sq
        t_clamped = np.clip(t_raw, 0, 1)

        # Closest point on each segment
        closest_x = track_x[:-1] + t_clamped * seg_dx
        closest_y = track_y[:-1] + t_clamped * seg_dy
        dist_sq = (px[:, np.newaxis] - closest_x)**2 + (py[:, np.newaxis] - closest_y)**2

        # Find best segment for each point
        best_seg = np.argmin(dist_sq, axis=1)

        # Extract values for best segments
        row_idx = np.arange(n_points)
        best_t = t_clamped[row_idx, best_seg]
        best_dist = np.sqrt(dist_sq[row_idx, best_seg])

        # Interpolate track distance
        seg_start_dist = track_dist[:-1]
        seg_end_dist = track_dist[1:]
        track_distance = seg_start_dist[best_seg] + best_t * (seg_end_dist[best_seg] - seg_start_dist[best_seg])

        # Wrap to [0, lap_distance)
        track_distance = np.mod(track_distance, self.lap_distance).astype(np.float32)

        return track_distance, best_dist.astype(np.float32)

    def get_sector_track(self, sector: int) -> Optional[tuple]:
        """
        Get track coordinates for a specific marshal sector.

        Returns (x, y) arrays for the sector, with boundary points
        interpolated for exact sector edges.
        """
        if not self.marshal_sectors or self.distance is None:
            return None

        # Find the sector
        sector_info = None
        for s in self.marshal_sectors:
            if s.number == sector:
                sector_info = s
                break

        if sector_info is None:
            return None

        return self._extract_segment(sector_info.start_distance, sector_info.end_distance)

    def get_all_sectors(self) -> List[tuple]:
        """
        Get track split into all marshal sectors.

        Returns list of (sector_num, x, y) tuples.
        Sector boundaries are interpolated and repeated on adjacent sectors.
        """
        if not self.marshal_sectors or self.distance is None:
            return [(0, self.x, self.y)]  # Return full track as sector 0

        result = []
        for sector in self.marshal_sectors:
            segment = self._extract_segment(sector.start_distance, sector.end_distance)
            if segment:
                result.append((sector.number, segment[0], segment[1]))
        return result

    def _extract_segment(self, from_dist: float, to_dist: float) -> Optional[tuple]:
        """Extract track segment between two distances with interpolation."""
        if self.distance is None or len(self.distance) == 0:
            return None

        # Handle wrapping case (to_dist > lap_distance means it wraps to start)
        if to_dist > self.lap_distance:
            # Extract two parts: from_dist to end, then start to wrapped portion
            part1 = self._extract_segment_simple(from_dist, self.lap_distance)
            part2 = self._extract_segment_simple(0, to_dist - self.lap_distance)
            if part1 is not None and part2 is not None:
                return (np.concatenate([part1[0], part2[0]]),
                        np.concatenate([part1[1], part2[1]]))
            return part1 or part2

        return self._extract_segment_simple(from_dist, to_dist)

    def _extract_segment_simple(self, from_dist: float, to_dist: float) -> Optional[tuple]:
        """Extract track segment without wrap handling."""
        if self.distance is None or len(self.distance) == 0:
            return None

        # Find indices within range
        mask = (self.distance >= from_dist) & (self.distance <= to_dist)
        indices = np.where(mask)[0]

        if len(indices) == 0:
            return None

        # Get segment points
        x_seg = self.x[indices].copy()
        y_seg = self.y[indices].copy()

        # Interpolate start point if needed
        if indices[0] > 0 and self.distance[indices[0]] > from_dist:
            i_prev = indices[0] - 1
            t = (from_dist - self.distance[i_prev]) / (self.distance[indices[0]] - self.distance[i_prev])
            x_start = self.x[i_prev] + t * (self.x[indices[0]] - self.x[i_prev])
            y_start = self.y[i_prev] + t * (self.y[indices[0]] - self.y[i_prev])
            x_seg = np.insert(x_seg, 0, x_start)
            y_seg = np.insert(y_seg, 0, y_start)

        # Interpolate end point if needed
        if indices[-1] < len(self.distance) - 1 and self.distance[indices[-1]] < to_dist:
            i_next = indices[-1] + 1
            t = (to_dist - self.distance[indices[-1]]) / (self.distance[i_next] - self.distance[indices[-1]])
            x_end = self.x[indices[-1]] + t * (self.x[i_next] - self.x[indices[-1]])
            y_end = self.y[indices[-1]] + t * (self.y[i_next] - self.y[indices[-1]])
            x_seg = np.append(x_seg, x_end)
            y_seg = np.append(y_seg, y_end)

        return (x_seg.astype(np.float32), y_seg.astype(np.float32))


@dataclass(frozen=True)
class DirectionArrow(F1DataMixin):
    """
    Direction arrow at start/finish line.

    Position is on the outside of track (opposite pitlane).
    Direction points in racing direction.
    """
    x: float  # Arrow base position (decimeters)
    y: float
    dx: float  # Direction unit vector (racing direction)
    dy: float

    def __repr__(self) -> str:
        return f"DirectionArrow(pos=({self.x:.0f}, {self.y:.0f}), dir=({self.dx:.2f}, {self.dy:.2f}))"


@dataclass(frozen=True)
class PitLane(F1DataMixin):
    """
    Pit lane geometry with entry/exit points on main track.

    x, y: Coordinates along pit lane (decimeters, same as track)
    distance: Cumulative distance along pit lane (meters)
    entry_track_dist: Track distance where pit entry begins (meters)
    exit_track_dist: Track distance where pit exit ends (meters)
    """
    x: np.ndarray  # float32 array of X coordinates
    y: np.ndarray  # float32 array of Y coordinates
    distance: Optional[np.ndarray] = None  # Cumulative distance in meters
    length: float = 0.0  # Total pit lane length in meters
    entry_track_dist: float = 0.0  # Where pit entry meets main track
    exit_track_dist: float = 0.0   # Where pit exit meets main track

    def __repr__(self) -> str:
        n = len(self.x) if self.x is not None else 0
        return f"PitLane({n} points, {self.length:.0f}m, entry={self.entry_track_dist:.0f}m, exit={self.exit_track_dist:.0f}m)"


@dataclass(frozen=True)
class CircuitData(F1DataMixin):
    """
    Complete circuit information.

    Provides convenience methods for track projection via the track attribute:
    - progress_on_track(x, y): Get track distance for points
    - distance_to_track(x, y): Get perpendicular distance to track
    """
    track: TrackGeometry  # Track outline
    pit_lane: Optional[PitLane] = None  # Pit lane with entry/exit
    circuit_length: float = 0.0  # Total track length (meters)
    corners: List[Corner] = field(default_factory=list)  # Corner markers
    rotation: float = 0.0  # Track rotation in degrees (from FastF1)
    name: str = ""  # Circuit name (e.g., "Albert Park", "Bahrain International Circuit")
    direction_arrow: Optional[DirectionArrow] = None  # Arrow showing racing direction
    metadata: Dict[str, Any] = field(default_factory=dict)  # DRS zones, etc.

    def __repr__(self) -> str:
        name = f"'{self.name}', " if self.name else ""
        pit = f", pit={self.pit_lane}" if self.pit_lane else ""
        return f"CircuitData({name}track={self.track}{pit}, rot={self.rotation:.0f}°)"

    def progress_on_track(self, px: np.ndarray, py: np.ndarray) -> np.ndarray:
        """
        Get track progress (distance along track) for each point.

        Delegates to track.progress_on_track().

        Args:
            px, py: Point coordinates (N points, in decimeters)

        Returns:
            Track distance for each point (N values, in meters)
        """
        return self.track.progress_on_track(px, py)

    def distance_to_track(self, px: np.ndarray, py: np.ndarray) -> np.ndarray:
        """
        Get perpendicular distance from track for each point.

        Delegates to track.distance_to_track().

        Args:
            px, py: Point coordinates (N points, in decimeters)

        Returns:
            Distance to track for each point (N values, in decimeters)
        """
        return self.track.distance_to_track(px, py)

@dataclass(frozen=True)
class F1Weekend(F1DataMixin):
    """
    Complete immutable race weekend: EventInfo + CircuitData.

    EventInfo provides all event metadata (name, location, sessions, etc.)
    CircuitData provides track geometry for visualization.
    """
    event: 'EventInfo'  # Forward reference to avoid circular import
    circuit: CircuitData

    # Convenience accessors for common EventInfo fields
    @property
    def year(self) -> int:
        return self.event.year

    @property
    def round_number(self) -> int:
        return self.event.round_number

    @property
    def name(self) -> str:
        return self.event.name

    @property
    def official_name(self) -> str:
        return self.event.official_name

    @property
    def circuit_name(self) -> str:
        return self.event.circuit_name

    @property
    def country(self) -> str:
        return self.event.country

    @property
    def timezone_offset(self) -> str:
        return self.event.timezone_offset

    @property
    def start_date(self) -> str:
        return self.event.start_date

    @property
    def end_date(self) -> str:
        return self.event.end_date

    @property
    def format(self) -> str:
        return self.event.format

    @property
    def session_schedule(self) -> Dict[str, str]:
        return self.event.session_schedule
