"""Tests for TrackGeometry projection methods."""

import numpy as np
import pytest

from f1_replay.models.weekend import TrackGeometry, MarshalSector


def _make_line_track(n=50, length=500.0):
    """Straight-line track for simple geometry tests."""
    x = np.linspace(0, length, n, dtype=np.float32)
    y = np.zeros(n, dtype=np.float32)
    dist = x / 10.0  # meters (x is in decimeters)
    return TrackGeometry(x=x, y=y, distance=dist.astype(np.float32), lap_distance=float(dist[-1]))


def _make_sector_track():
    """Straight track with 3 marshal sectors for segment extraction tests."""
    n = 100
    x = np.linspace(0, 1000.0, n, dtype=np.float32)  # 1000 dm = 100m
    y = np.zeros(n, dtype=np.float32)
    dist = (x / 10.0).astype(np.float32)  # 0 to 100m
    lap_distance = float(dist[-1])
    sectors = [
        MarshalSector(number=1, start_distance=0.0, end_distance=33.0),
        MarshalSector(number=2, start_distance=33.0, end_distance=66.0),
        MarshalSector(number=3, start_distance=66.0, end_distance=lap_distance),
    ]
    return TrackGeometry(x=x, y=y, distance=dist, lap_distance=lap_distance, marshal_sectors=sectors)


class TestProgressOnTrack:
    """Test point-to-track projection."""

    def test_point_on_track(self, sample_track_geometry):
        """Point exactly on track should return correct distance."""
        track = sample_track_geometry
        px = np.array([track.x[0]], dtype=np.float32)
        py = np.array([track.y[0]], dtype=np.float32)
        dist = track.progress_on_track(px, py)
        assert dist[0] == pytest.approx(0.0, abs=1.0)

    def test_multiple_points(self, sample_track_geometry):
        """Multiple points should return array of distances."""
        track = sample_track_geometry
        px = track.x[:5].copy()
        py = track.y[:5].copy()
        dist = track.progress_on_track(px, py)
        assert len(dist) == 5
        assert all(dist[i] <= dist[i + 1] for i in range(len(dist) - 1))

    def test_distances_within_lap(self, sample_track_geometry):
        """All distances should be within [0, lap_distance)."""
        track = sample_track_geometry
        px = track.x.copy()
        py = track.y.copy()
        dist = track.progress_on_track(px, py)
        assert np.all(dist >= 0)
        assert np.all(dist <= track.lap_distance + 1.0)

    def test_point_offset_perpendicular(self):
        """Point offset perpendicular to track should project to nearest track point."""
        track = _make_line_track(n=50, length=500.0)
        # Point at x=250dm, y=100dm (offset 100dm from track)
        px = np.array([250.0], dtype=np.float32)
        py = np.array([100.0], dtype=np.float32)
        dist = track.progress_on_track(px, py)
        assert dist[0] == pytest.approx(25.0, abs=1.0)  # 250dm = 25m

    def test_large_input_uses_kdtree(self):
        """Input large enough to trigger KD-tree code path (N*M >= 10000)."""
        n_track = 200
        t = np.linspace(0, 2 * np.pi, n_track, endpoint=False)
        radius = 1000.0
        x = (radius * np.cos(t)).astype(np.float32)
        y = (radius * np.sin(t)).astype(np.float32)
        dx = np.diff(x, prepend=x[-1])
        dy = np.diff(y, prepend=y[-1])
        dist = np.cumsum(np.sqrt(dx**2 + dy**2)).astype(np.float32)
        dist[0] = 0.0
        lap_distance = float(dist[-1]) / 10.0
        dist_m = (dist / 10.0).astype(np.float32)
        track = TrackGeometry(x=x, y=y, distance=dist_m, lap_distance=lap_distance)

        # 100 query points on the track → 100*200 = 20000 >= 10000, triggers KD-tree
        px = x[:100].copy()
        py = y[:100].copy()
        result_dist = track.progress_on_track(px, py)
        assert len(result_dist) == 100
        assert np.all(result_dist >= 0)
        assert np.all(result_dist <= lap_distance + 1.0)

    def test_single_point_input(self):
        """Single point input should work with both simple and KD-tree paths."""
        track = _make_line_track(n=50, length=500.0)
        px = np.array([100.0], dtype=np.float32)
        py = np.array([0.0], dtype=np.float32)
        dist = track.progress_on_track(px, py)
        assert len(dist) == 1
        assert dist[0] == pytest.approx(10.0, abs=1.0)  # 100dm = 10m

    def test_empty_track_returns_zeros(self):
        """Empty track geometry returns zeros."""
        track = TrackGeometry(x=np.array([], dtype=np.float32), y=np.array([], dtype=np.float32))
        px = np.array([1.0], dtype=np.float32)
        py = np.array([1.0], dtype=np.float32)
        dist = track.progress_on_track(px, py)
        assert dist[0] == 0.0


class TestDistanceToTrack:
    """Test perpendicular distance from track."""

    def test_point_on_track(self, sample_track_geometry):
        """Point on track should have ~0 distance."""
        track = sample_track_geometry
        px = np.array([track.x[50]], dtype=np.float32)
        py = np.array([track.y[50]], dtype=np.float32)
        dist = track.distance_to_track(px, py)
        assert dist[0] == pytest.approx(0.0, abs=5.0)

    def test_point_off_track(self, sample_track_geometry):
        """Point off track should have nonzero distance."""
        track = sample_track_geometry
        px = np.array([0.0], dtype=np.float32)
        py = np.array([0.0], dtype=np.float32)
        dist = track.distance_to_track(px, py)
        assert dist[0] > 50.0

    def test_known_perpendicular_distance(self):
        """Point offset 50dm from straight track → distance = 50."""
        track = _make_line_track(n=50, length=500.0)
        px = np.array([250.0], dtype=np.float32)
        py = np.array([50.0], dtype=np.float32)
        dist = track.distance_to_track(px, py)
        assert dist[0] == pytest.approx(50.0, abs=2.0)

    def test_symmetry(self):
        """Points equidistant on opposite sides should have same distance."""
        track = _make_line_track(n=50, length=500.0)
        px = np.array([250.0, 250.0], dtype=np.float32)
        py = np.array([50.0, -50.0], dtype=np.float32)
        dist = track.distance_to_track(px, py)
        assert dist[0] == pytest.approx(dist[1], abs=1.0)


class TestExtractSegment:
    """Test _extract_segment and _extract_segment_simple."""

    def test_basic_segment(self):
        """Extract middle portion of track."""
        track = _make_sector_track()
        seg = track._extract_segment(20.0, 50.0)
        assert seg is not None
        x_seg, y_seg = seg
        assert len(x_seg) > 0
        # All x values should correspond to 20-50m = 200-500dm
        assert x_seg[0] == pytest.approx(200.0, abs=15.0)
        assert x_seg[-1] == pytest.approx(500.0, abs=15.0)

    def test_full_track_segment(self):
        """Extracting 0 to lap_distance returns full track."""
        track = _make_sector_track()
        seg = track._extract_segment(0.0, track.lap_distance)
        assert seg is not None
        x_seg, y_seg = seg
        assert len(x_seg) >= 90  # Most or all track points

    def test_wrapping_segment(self):
        """Segment that wraps around (to_dist > lap_distance)."""
        track = _make_sector_track()
        # from 80m to 120m on a 100m track → 80-100m + 0-20m
        seg = track._extract_segment(80.0, 120.0)
        assert seg is not None
        x_seg, y_seg = seg
        # Should contain points from end of track AND start of track
        assert len(x_seg) > 5

    def test_empty_range(self):
        """Segment with no points returns None."""
        track = TrackGeometry(
            x=np.array([], dtype=np.float32),
            y=np.array([], dtype=np.float32),
            distance=np.array([], dtype=np.float32),
            lap_distance=100.0,
        )
        seg = track._extract_segment(10.0, 20.0)
        assert seg is None

    def test_interpolated_boundaries(self):
        """Start and end points should be interpolated to exact distance."""
        track = _make_sector_track()
        # Request 15.5m to 45.5m (unlikely to land exactly on a track point)
        seg = track._extract_segment(15.5, 45.5)
        assert seg is not None
        x_seg, y_seg = seg
        # First x should be interpolated to ~155dm
        assert x_seg[0] == pytest.approx(155.0, abs=15.0)
        # Last x should be interpolated to ~455dm
        assert x_seg[-1] == pytest.approx(455.0, abs=15.0)

    def test_segment_preserves_float32(self):
        """Output arrays should be float32."""
        track = _make_sector_track()
        seg = track._extract_segment(10.0, 50.0)
        assert seg is not None
        assert seg[0].dtype == np.float32
        assert seg[1].dtype == np.float32


class TestGetSectorTrack:
    """Test sector-specific track extraction."""

    def test_get_existing_sector(self):
        """Get coordinates for a specific sector."""
        track = _make_sector_track()
        result = track.get_sector_track(1)
        assert result is not None
        x, y = result
        assert len(x) > 0

    def test_get_nonexistent_sector(self):
        """Non-existent sector returns None."""
        track = _make_sector_track()
        result = track.get_sector_track(99)
        assert result is None

    def test_no_sectors(self):
        """Track without sectors returns None."""
        track = _make_line_track()
        result = track.get_sector_track(1)
        assert result is None


class TestGetAllSectors:
    """Test sector extraction from track geometry."""

    def test_sectors_returned(self, sample_track_geometry):
        """get_all_sectors should return sector data."""
        sectors = list(sample_track_geometry.get_all_sectors())
        assert len(sectors) == 3
        for sector_num, sx, sy in sectors:
            assert isinstance(sector_num, int)
            assert len(sx) > 0
            assert len(sy) > 0

    def test_sectors_cover_full_track(self):
        """All sectors together should cover the full track."""
        track = _make_sector_track()
        sectors = track.get_all_sectors()
        total_points = sum(len(sx) for _, sx, _ in sectors)
        # Allow overlap at boundaries, but should have more points than any single sector
        assert total_points >= len(track.x) * 0.8

    def test_no_sectors_returns_full_track(self):
        """Track without sectors returns full track as sector 0."""
        track = _make_line_track()
        sectors = track.get_all_sectors()
        assert len(sectors) == 1
        assert sectors[0][0] == 0
        assert len(sectors[0][1]) == len(track.x)


class TestProjectionConsistency:
    """Verify progress_on_track and distance_to_track are consistent."""

    def test_on_track_point_has_zero_distance(self, sample_track_geometry):
        """Points on track should have distance ≈ 0 and valid progress."""
        track = sample_track_geometry
        for i in range(0, len(track.x), 10):
            px = np.array([track.x[i]], dtype=np.float32)
            py = np.array([track.y[i]], dtype=np.float32)
            prog = track.progress_on_track(px, py)
            dist = track.distance_to_track(px, py)
            assert dist[0] < 5.0, f"Point {i} on track has distance {dist[0]}"
            assert prog[0] >= 0
            assert prog[0] <= track.lap_distance + 1.0

    def test_monotonic_progress_along_track(self, sample_track_geometry):
        """Sequential track points should have monotonically increasing progress."""
        track = sample_track_geometry
        # Use first half of track (no wrapping)
        n = len(track.x) // 2
        px = track.x[:n].copy()
        py = track.y[:n].copy()
        prog = track.progress_on_track(px, py)
        for i in range(len(prog) - 1):
            assert prog[i] <= prog[i + 1] + 0.1, (
                f"Progress not monotonic at {i}: {prog[i]} > {prog[i+1]}"
            )
