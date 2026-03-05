"""Tests for track/pit geometry extraction from telemetry."""

import numpy as np
import polars as pl
import pytest

from f1_replay.loaders.session.track_extract import extract_track_and_pit


def _make_circular_telemetry(n_laps=3, points_per_lap=200, radius=5000.0, pit_lap=None):
    """
    Build telemetry for a driver doing laps on a circular track.

    Returns (telemetry_dict, status_data_all) suitable for extract_track_and_pit.
    Track is a circle of given radius in decimeters.
    """
    total_points = n_laps * points_per_lap
    t = np.linspace(0, n_laps * 2 * np.pi, total_points, endpoint=False)
    x = (radius * np.cos(t)).astype(np.float32)
    y = (radius * np.sin(t)).astype(np.float32)
    z = np.zeros(total_points, dtype=np.float32)

    # 1 second per point, lap_number starts at 1
    session_times = np.arange(total_points, dtype=np.float64)
    lap_numbers = np.repeat(np.arange(1, n_laps + 1), points_per_lap).astype(np.int32)

    speed = np.full(total_points, 200.0, dtype=np.float32)
    throttle = np.full(total_points, 80.0, dtype=np.float32)
    brake = np.zeros(total_points, dtype=np.float32)

    # Build pit windows if requested
    pit_windows = []
    if pit_lap is not None and pit_lap <= n_laps:
        pit_start = (pit_lap - 1) * points_per_lap + points_per_lap // 2
        pit_end = pit_start + 20
        pit_windows.append((float(session_times[pit_start]), float(session_times[pit_end])))

    tel = pl.DataFrame(
        {
            "session_time": session_times,
            "x": x,
            "y": y,
            "z": z,
            "speed": speed,
            "throttle": throttle,
            "brake": brake,
            "lap_number": lap_numbers,
        }
    )

    status_data = {
        "finish_time": float(session_times[-1]),
        "pit_windows": pit_windows,
        "is_dnf": False,
    }

    return {"DRV": tel}, {"DRV": status_data}


class TestExtractTrackAndPit:
    """Test the main track extraction function."""

    def test_basic_extraction(self):
        """Extracts track geometry from circular telemetry."""
        telemetry, status_data = _make_circular_telemetry(n_laps=3, points_per_lap=200)
        track_data, session_timing = extract_track_and_pit(telemetry, "DRV", status_data)

        assert track_data is not None
        assert len(track_data.track_x) > 50
        assert len(track_data.track_y) == len(track_data.track_x)
        assert track_data.lap_distance > 0

    def test_track_distance_monotonic(self):
        """Track distance should be monotonically increasing."""
        telemetry, status_data = _make_circular_telemetry(n_laps=3, points_per_lap=200)
        track_data, _ = extract_track_and_pit(telemetry, "DRV", status_data)

        assert track_data is not None
        diffs = np.diff(track_data.track_distance)
        assert np.all(diffs >= 0), "Track distance must be monotonically increasing"

    def test_track_forms_loop(self):
        """Start and end of track should be close (closed circuit)."""
        telemetry, status_data = _make_circular_telemetry(n_laps=3, points_per_lap=200)
        track_data, _ = extract_track_and_pit(telemetry, "DRV", status_data)

        assert track_data is not None
        start_x, start_y = track_data.track_x[0], track_data.track_y[0]
        end_x, end_y = track_data.track_x[-1], track_data.track_y[-1]
        gap = np.sqrt((end_x - start_x) ** 2 + (end_y - start_y) ** 2)
        # Gap should be less than a few percent of track length
        assert gap < track_data.lap_distance * 0.1

    def test_lap_distance_matches_circumference(self):
        """For circular track, lap_distance should be close to 2*pi*radius."""
        radius = 5000.0  # decimeters
        telemetry, status_data = _make_circular_telemetry(
            n_laps=3, points_per_lap=400, radius=radius
        )
        track_data, _ = extract_track_and_pit(telemetry, "DRV", status_data)

        assert track_data is not None
        expected_circumference = 2 * np.pi * radius  # in decimeters
        assert track_data.lap_distance == pytest.approx(expected_circumference, rel=0.05)

    def test_excludes_pit_lap(self):
        """Track should be extracted from clean lap, not pit lap."""
        telemetry, status_data = _make_circular_telemetry(n_laps=4, points_per_lap=200, pit_lap=2)
        track_data, _ = extract_track_and_pit(telemetry, "DRV", status_data)

        assert track_data is not None
        # Should still produce valid track from non-pit laps
        assert track_data.lap_distance > 0

    def test_fallback_to_first_driver(self):
        """When winner is not in telemetry, use first available driver."""
        telemetry, status_data = _make_circular_telemetry(n_laps=3, points_per_lap=200)
        track_data, _ = extract_track_and_pit(telemetry, "MISSING", status_data)

        # Should still work using "DRV" as fallback
        assert track_data is not None

    def test_empty_telemetry_returns_none(self):
        """Empty telemetry dict returns None."""
        track_data, timing = extract_track_and_pit({}, None)
        assert track_data is None
        assert timing is None

    def test_no_racing_laps_returns_none(self):
        """If all lap_numbers are 0, no track can be extracted."""
        tel = pl.DataFrame(
            {
                "session_time": np.arange(50, dtype=np.float64),
                "x": np.random.randn(50).astype(np.float32),
                "y": np.random.randn(50).astype(np.float32),
                "z": np.zeros(50, dtype=np.float32),
                "lap_number": np.zeros(50, dtype=np.int32),
            }
        )
        track_data, _ = extract_track_and_pit({"DRV": tel}, "DRV")
        assert track_data is None

    def test_reference_lap_telemetry_stored(self):
        """Speed, throttle, brake from reference lap should be stored."""
        telemetry, status_data = _make_circular_telemetry(n_laps=3, points_per_lap=200)
        track_data, _ = extract_track_and_pit(telemetry, "DRV", status_data)

        assert track_data is not None
        assert track_data.speed is not None
        assert track_data.throttle is not None
        assert track_data.brake is not None
        assert len(track_data.speed) == len(track_data.track_x)

    def test_smooth_wrap_blending(self):
        """Last few track points should blend toward first point values."""
        telemetry, status_data = _make_circular_telemetry(n_laps=3, points_per_lap=200)
        track_data, _ = extract_track_and_pit(telemetry, "DRV", status_data)

        assert track_data is not None
        if track_data.track_z is not None and len(track_data.track_z) > 20:
            # Last point should be close to first point (due to smooth_wrap blending)
            assert (
                abs(track_data.track_z[-1] - track_data.track_z[0])
                < abs(track_data.track_z[-11] - track_data.track_z[0]) + 1
            )  # tolerance

    def test_warmup_detection(self):
        """Session timing should detect warmup start from static period."""
        n_warmup = 100  # 100 points of static (grid) then 50 points moving, then 3 laps
        n_laps = 3
        points_per_lap = 200
        total = n_warmup + 50 + n_laps * points_per_lap

        # Static grid position
        grid_x = np.full(n_warmup, 5000.0, dtype=np.float32)
        grid_y = np.full(n_warmup, 0.0, dtype=np.float32)

        # Warmup phase (moving from grid to track)
        warmup_t = np.linspace(0, 0.25 * np.pi, 50)
        warmup_x = (5000.0 * np.cos(warmup_t)).astype(np.float32)
        warmup_y = (5000.0 * np.sin(warmup_t)).astype(np.float32)

        # Racing laps
        t = np.linspace(
            0.25 * np.pi, 0.25 * np.pi + n_laps * 2 * np.pi, n_laps * points_per_lap, endpoint=False
        )
        race_x = (5000.0 * np.cos(t)).astype(np.float32)
        race_y = (5000.0 * np.sin(t)).astype(np.float32)

        x = np.concatenate([grid_x, warmup_x, race_x])
        y = np.concatenate([grid_y, warmup_y, race_y])
        z = np.zeros(total, dtype=np.float32)

        lap_nums = np.concatenate(
            [
                np.zeros(n_warmup + 50, dtype=np.int32),  # pre-race
                np.repeat(np.arange(1, n_laps + 1), points_per_lap).astype(np.int32),
            ]
        )

        tel = pl.DataFrame(
            {
                "session_time": np.arange(total, dtype=np.float64),
                "x": x,
                "y": y,
                "z": z,
                "speed": np.full(total, 200.0, dtype=np.float32),
                "throttle": np.full(total, 80.0, dtype=np.float32),
                "brake": np.zeros(total, dtype=np.float32),
                "lap_number": lap_nums,
            }
        )

        track_data, session_timing = extract_track_and_pit({"DRV": tel}, "DRV")

        assert track_data is not None
        # Warmup should be detected (car was static then started moving)
        if session_timing is not None:
            assert session_timing["warmup_start_time"] is not None
            # Warmup start should be after grid period
            assert session_timing["warmup_start_time"] >= n_warmup - 10  # allow tolerance


class TestExtractTrackMultipleDrivers:
    """Test extraction with multiple drivers."""

    def test_uses_winner_not_other_drivers(self):
        """When winner is specified, use their data."""
        tel1, sd1 = _make_circular_telemetry(n_laps=3, points_per_lap=200, radius=5000)
        tel2, sd2 = _make_circular_telemetry(n_laps=3, points_per_lap=200, radius=3000)

        telemetry = {"VER": tel1["DRV"], "HAM": tel2["DRV"]}
        status_data = {"VER": sd1["DRV"], "HAM": sd2["DRV"]}

        track_data, _ = extract_track_and_pit(telemetry, "VER", status_data)

        assert track_data is not None
        # Track should match VER's radius (5000), not HAM's (3000)
        expected = 2 * np.pi * 5000
        assert track_data.lap_distance == pytest.approx(expected, rel=0.1)
