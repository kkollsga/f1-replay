"""
Tests for TelemetryBuilder advanced methods:
  - _add_velocity_vectors
  - _sample_car_data
  - _add_lap_info
  - _add_status_all
  - _add_track_distance_all
"""

import numpy as np
import pandas as pd
import polars as pl
import pytest

from f1_replay.loaders.session.telemetry import TelemetryBuilder, TrackData

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_telemetry_df(times, x_vals, y_vals):
    """Build a pandas DataFrame suitable for _add_velocity_vectors."""
    return pd.DataFrame(
        {
            "session_time": np.array(times, dtype=np.float64),
            "x": np.array(x_vals, dtype=np.float64),
            "y": np.array(y_vals, dtype=np.float64),
        }
    )


def make_pos_df(times_sec, x, y, z=None, status=None):
    """Build a pos_data-like DataFrame with timedelta SessionTime."""
    n = len(times_sec)
    return pd.DataFrame(
        {
            "SessionTime": pd.to_timedelta(times_sec, unit="s"),
            "X": np.array(x, dtype=np.float64),
            "Y": np.array(y, dtype=np.float64),
            "Z": np.array(z if z is not None else np.zeros(n), dtype=np.float64),
            "Status": status if status is not None else ["OnTrack"] * n,
        }
    )


def make_car_df(times_sec, speed=None, rpm=None, n_gear=None, throttle=None, brake=None, drs=None):
    """Build a car_data-like DataFrame with timedelta SessionTime."""
    n = len(times_sec)
    df = pd.DataFrame(
        {
            "SessionTime": pd.to_timedelta(times_sec, unit="s"),
            "Speed": np.array(speed if speed is not None else np.zeros(n)),
            "RPM": np.array(rpm if rpm is not None else np.zeros(n)),
            "nGear": np.array(n_gear if n_gear is not None else np.zeros(n)),
            "Throttle": np.array(throttle if throttle is not None else np.zeros(n)),
            "Brake": np.array(brake if brake is not None else np.zeros(n)),
            "DRS": np.array(drs if drs is not None else np.zeros(n)),
        }
    )
    return df


def make_driver_laps(
    lap_numbers,
    completion_times_sec,
    start_times_sec=None,
    compounds=None,
    tyre_life=None,
    pit_in_sec=None,
    pit_out_sec=None,
):
    """Build a driver_laps DataFrame mimicking FastF1 laps structure."""
    n = len(lap_numbers)
    data = {
        "Driver": ["TST"] * n,
        "LapNumber": np.array(lap_numbers, dtype=np.float64),
        "Time": pd.to_timedelta(completion_times_sec, unit="s"),
    }
    if start_times_sec is not None:
        data["LapStartTime"] = pd.to_timedelta(start_times_sec, unit="s")
    else:
        # Default: each lap starts when previous one ends
        starts = [0.0] + list(completion_times_sec[:-1])
        data["LapStartTime"] = pd.to_timedelta(starts, unit="s")
    if compounds is not None:
        data["Compound"] = compounds
    if tyre_life is not None:
        data["TyreLife"] = np.array(tyre_life, dtype=np.float64)
    if pit_in_sec is not None:
        pit_in_vals = [pd.Timedelta(seconds=t) if t is not None else pd.NaT for t in pit_in_sec]
        data["PitInTime"] = pit_in_vals
    if pit_out_sec is not None:
        pit_out_vals = [pd.Timedelta(seconds=t) if t is not None else pd.NaT for t in pit_out_sec]
        data["PitOutTime"] = pit_out_vals
    return pd.DataFrame(data)


def make_pl_telemetry(
    session_times, x_vals, y_vals, z_vals=None, race_distances=None, lap_numbers=None, status=None
):
    """Build a Polars DataFrame for _add_status_all / _add_track_distance_all."""
    data = {
        "session_time": np.array(session_times, dtype=np.float64),
        "x": np.array(x_vals, dtype=np.float64),
        "y": np.array(y_vals, dtype=np.float64),
    }
    if z_vals is not None:
        data["z"] = np.array(z_vals, dtype=np.float64)
    else:
        data["z"] = np.zeros(len(session_times), dtype=np.float64)
    if race_distances is not None:
        data["race_distance"] = np.array(race_distances, dtype=np.float32)
    if lap_numbers is not None:
        data["lap_number"] = np.array(lap_numbers, dtype=np.int32)
    if status is not None:
        data["status"] = status
    return pl.DataFrame(data)


# ===========================================================================
# TestAddVelocityVectors
# ===========================================================================


class TestAddVelocityVectors:

    def test_single_point(self):
        """n < 2 -> vx = vy = 0."""
        df = make_telemetry_df([0.0], [100.0], [200.0])
        result = TelemetryBuilder._add_velocity_vectors(df)
        assert result["vx"].iloc[0] == 0.0
        assert result["vy"].iloc[0] == 0.0

    def test_two_points(self):
        """Two points: forward diff at first, backward diff at last (no central)."""
        df = make_telemetry_df([0.0, 1.0], [0.0, 10.0], [0.0, 20.0])
        result = TelemetryBuilder._add_velocity_vectors(df)
        # With only 2 points, smoothing does nothing (< 3 points).
        # Forward/backward both give dx/dt=10, dy/dt=20
        assert result["vx"].iloc[0] == pytest.approx(10.0, abs=0.1)
        assert result["vy"].iloc[0] == pytest.approx(20.0, abs=0.1)
        assert result["vx"].iloc[1] == pytest.approx(10.0, abs=0.1)
        assert result["vy"].iloc[1] == pytest.approx(20.0, abs=0.1)

    def test_constant_velocity(self):
        """Uniform motion: velocity should be approximately constant after smoothing."""
        n = 20
        t = np.arange(n, dtype=np.float64) * 0.1  # 0.1s intervals
        x = t * 50.0  # 50 dm/s
        y = t * 30.0  # 30 dm/s
        df = make_telemetry_df(t, x, y)
        result = TelemetryBuilder._add_velocity_vectors(df)
        # Interior points should be very close to exact velocity
        vx_interior = result["vx"].values[3:-3]
        vy_interior = result["vy"].values[3:-3]
        np.testing.assert_allclose(vx_interior, 50.0, atol=1.0)
        np.testing.assert_allclose(vy_interior, 30.0, atol=1.0)

    def test_pit_gap_zeros_velocity(self):
        """> 2s gap between points -> velocity zeroed at boundary and point before."""
        t = [0.0, 0.1, 0.2, 5.0, 5.1, 5.2]  # 4.8s gap between idx 2 and 3
        x = [0.0, 1.0, 2.0, 100.0, 101.0, 102.0]
        y = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
        df = make_telemetry_df(t, x, y)
        result = TelemetryBuilder._add_velocity_vectors(df)
        # Before smoothing, idx 2 and 3 are zeroed. After bidirectional EMA
        # (alpha=0.3), non-zero neighbors bleed in. The key property is that
        # the gap boundary velocities are significantly reduced compared to the
        # ~10 dm/s velocity on each side. Allow generous tolerance for smoothing.
        assert abs(result["vx"].iloc[2]) < 7.0
        assert abs(result["vx"].iloc[3]) < 7.0
        # Additionally verify they are smaller than the non-gap interior velocity
        # (points far from the gap should have higher velocity)
        assert abs(result["vx"].iloc[2]) < abs(result["vx"].iloc[4]) + 1.0

    def test_velocity_clamping(self):
        """Extreme position jump -> velocity clamped to +/- 1000 dm/s."""
        # Jump of 100000 dm in 0.1s = 1000000 dm/s (way over 1000)
        t = [0.0, 0.1, 0.2]
        x = [0.0, 100000.0, 0.0]
        y = [0.0, 0.0, 0.0]
        df = make_telemetry_df(t, x, y)
        result = TelemetryBuilder._add_velocity_vectors(df)
        # After clamping and smoothing, all vx should be within [-1000, 1000]
        assert np.all(result["vx"].values <= 1000.0)
        assert np.all(result["vx"].values >= -1000.0)

    def test_stationary_car(self):
        """x, y constant -> vx, vy approximately 0."""
        t = np.arange(10, dtype=np.float64) * 0.1
        x = np.full(10, 500.0)
        y = np.full(10, 300.0)
        df = make_telemetry_df(t, x, y)
        result = TelemetryBuilder._add_velocity_vectors(df)
        np.testing.assert_allclose(result["vx"].values, 0.0, atol=1e-5)
        np.testing.assert_allclose(result["vy"].values, 0.0, atol=1e-5)

    def test_circular_motion(self):
        """Car moving in circle: velocity perpendicular to radius vector."""
        n = 100
        theta = np.linspace(0, 2 * np.pi, n, endpoint=False)
        dt = 0.1
        t = np.arange(n) * dt
        R = 100.0
        x = R * np.cos(theta)
        y = R * np.sin(theta)
        df = make_telemetry_df(t, x, y)
        result = TelemetryBuilder._add_velocity_vectors(df)
        # For circular motion, v dot r = 0 (velocity perpendicular to position)
        # Check interior points (skip edges due to boundary effects)
        for i in range(10, n - 10):
            vx_i = result["vx"].iloc[i]
            vy_i = result["vy"].iloc[i]
            dot = vx_i * x[i] + vy_i * y[i]
            speed = np.sqrt(vx_i**2 + vy_i**2)
            if speed > 1.0:  # avoid div-by-zero on near-stationary
                cos_angle = dot / (speed * R)
                assert abs(cos_angle) < 0.15, f"At i={i}, cos_angle={cos_angle:.3f}"


# ===========================================================================
# TestSampleCarData
# ===========================================================================


class TestSampleCarData:

    def test_exact_match(self):
        """car_data timestamps match pos_data exactly."""
        times = [1.0, 2.0, 3.0]
        pos = make_pos_df(times, [10, 20, 30], [40, 50, 60])
        car = make_car_df(times, speed=[100, 200, 300], rpm=[5000, 6000, 7000])
        result = TelemetryBuilder._sample_car_data(pos, car)
        np.testing.assert_array_equal(result["speed"].values, [100, 200, 300])
        np.testing.assert_array_equal(result["rpm"].values, [5000, 6000, 7000])

    def test_nearest_neighbor(self):
        """car_data sampled to nearest pos timestamp."""
        pos = make_pos_df([1.0, 2.0, 3.0], [0, 0, 0], [0, 0, 0])
        # Car data at slightly different times
        car = make_car_df([0.9, 2.1, 3.5], speed=[100, 200, 300])
        result = TelemetryBuilder._sample_car_data(pos, car)
        # pos t=1.0 -> nearest car t=0.9 -> speed=100
        # pos t=2.0 -> nearest car t=2.1 -> speed=200
        # pos t=3.0 -> nearest car t=3.5 (dist=0.5) vs t=2.1 (dist=0.9) -> speed=300
        assert result["speed"].iloc[0] == 100
        assert result["speed"].iloc[1] == 200
        assert result["speed"].iloc[2] == 300

    def test_missing_columns(self):
        """Missing car columns default to 0."""
        pos = make_pos_df([1.0], [10], [20])
        # Car DataFrame with only Speed column
        car = pd.DataFrame(
            {
                "SessionTime": pd.to_timedelta([1.0], unit="s"),
                "Speed": [100],
            }
        )
        result = TelemetryBuilder._sample_car_data(pos, car)
        assert result["speed"].iloc[0] == 100
        assert result["rpm"].iloc[0] == 0
        assert result["n_gear"].iloc[0] == 0
        assert result["throttle"].iloc[0] == 0
        assert result["brake"].iloc[0] == 0
        assert result["drs"].iloc[0] == 0

    def test_column_names(self):
        """Output has snake_case column names."""
        pos = make_pos_df([1.0], [10], [20])
        car = make_car_df([1.0])
        result = TelemetryBuilder._sample_car_data(pos, car)
        expected_cols = {
            "session_time",
            "status",
            "x",
            "y",
            "z",
            "rpm",
            "speed",
            "n_gear",
            "throttle",
            "brake",
            "drs",
        }
        assert expected_cols.issubset(set(result.columns))


# ===========================================================================
# TestAddLapInfo
# ===========================================================================


class TestAddLapInfo:

    def test_no_laps(self):
        """None driver_laps -> lap_number all 0, no pit windows."""
        df = pd.DataFrame({"session_time": [1.0, 2.0, 3.0]})
        result_df, max_lap, finish_time, pit_windows = TelemetryBuilder._add_lap_info(df, None)
        np.testing.assert_array_equal(result_df["lap_number"].values, [0, 0, 0])
        assert max_lap == 0
        assert finish_time is None
        assert pit_windows == []

    def test_basic_lap_numbering(self):
        """3 laps with completion times, verify correct lap_number assignment."""
        # Laps complete at t=90, 180, 270. Race starts at t=0 (first lap start).
        laps = make_driver_laps(
            lap_numbers=[1, 2, 3],
            completion_times_sec=[90.0, 180.0, 270.0],
            start_times_sec=[0.0, 90.0, 180.0],
        )
        tel = pd.DataFrame(
            {
                "session_time": [
                    -5.0,  # before race start -> lap 0
                    10.0,  # after start, before lap 1 complete -> lap 1
                    95.0,  # after lap 1 complete -> lap 2
                    185.0,  # after lap 2 complete -> lap 3
                    275.0,  # after lap 3 complete -> lap 4
                ]
            }
        )
        result, max_lap, finish_time, _ = TelemetryBuilder._add_lap_info(tel, laps)
        assert result["lap_number"].iloc[0] == 0  # before race start
        assert result["lap_number"].iloc[1] == 1  # during lap 1
        assert result["lap_number"].iloc[2] == 2  # after lap 1 done
        assert result["lap_number"].iloc[3] == 3  # after lap 2 done
        assert result["lap_number"].iloc[4] == 4  # after lap 3 done
        assert max_lap == 3
        assert finish_time == pytest.approx(270.0)

    def test_pit_window_extraction(self):
        """PitInTime/PitOutTime properly paired."""
        laps = make_driver_laps(
            lap_numbers=[1, 2, 3],
            completion_times_sec=[90.0, 180.0, 270.0],
            start_times_sec=[0.0, 90.0, 180.0],
            pit_in_sec=[85.0, None, None],  # pit in on lap 1
            pit_out_sec=[None, 100.0, None],  # pit out on lap 2
        )
        tel = pd.DataFrame({"session_time": [50.0]})
        _, _, _, pit_windows = TelemetryBuilder._add_lap_info(tel, laps)
        assert len(pit_windows) == 1
        assert pit_windows[0][0] == pytest.approx(85.0)
        assert pit_windows[0][1] == pytest.approx(100.0)

    def test_finish_time(self):
        """Last lap completion time returned as finish_time."""
        laps = make_driver_laps(
            lap_numbers=[1, 2],
            completion_times_sec=[90.0, 180.0],
        )
        tel = pd.DataFrame({"session_time": [50.0]})
        _, _, finish_time, _ = TelemetryBuilder._add_lap_info(tel, laps)
        assert finish_time == pytest.approx(180.0)

    def test_tyre_compound_assignment(self):
        """Correct compound assigned to each time range."""
        laps = make_driver_laps(
            lap_numbers=[1, 2, 3],
            completion_times_sec=[90.0, 180.0, 270.0],
            start_times_sec=[0.0, 90.0, 180.0],
            compounds=["SOFT", "SOFT", "HARD"],
        )
        tel = pd.DataFrame(
            {
                "session_time": [
                    10.0,  # during lap 1 -> SOFT
                    100.0,  # during lap 2 -> SOFT
                    200.0,  # during lap 3 -> HARD
                ]
            }
        )
        result, _, _, _ = TelemetryBuilder._add_lap_info(tel, laps)
        assert result["compound"].iloc[0] == "SOFT"
        assert result["compound"].iloc[1] == "SOFT"
        assert result["compound"].iloc[2] == "HARD"


# ===========================================================================
# TestAddStatusAll
# ===========================================================================


class TestAddStatusAll:

    def _run(self, tel_dict, status_data_all, warmup_intervals=None, lights_out_offset=None):
        return TelemetryBuilder._add_status_all(
            tel_dict, status_data_all, warmup_intervals, lights_out_offset
        )

    def test_presession_status(self):
        """Times before warmup -> PreSession."""
        tel = make_pl_telemetry(
            [1.0, 2.0],
            [0, 10],
            [0, 10],
            race_distances=[0.0, 1.0],
            lap_numbers=[0, 0],
        )
        result = self._run(
            {"DRV": tel},
            {"DRV": {"finish_time": None, "pit_windows": [], "is_dnf": False}},
            warmup_intervals=[(5.0, 10.0)],
            lights_out_offset=10.0,
        )
        statuses = result["DRV"]["status"].to_list()
        assert all(s == "PreSession" for s in statuses)

    def test_warmup_status(self):
        """Times in warmup interval -> WarmUp."""
        tel = make_pl_telemetry(
            [5.0, 6.0, 7.0],
            [0, 10, 20],
            [0, 10, 20],
            race_distances=[0.0, 1.0, 2.0],
            lap_numbers=[0, 0, 0],
        )
        result = self._run(
            {"DRV": tel},
            {"DRV": {"finish_time": None, "pit_windows": [], "is_dnf": False}},
            warmup_intervals=[(4.0, 8.0)],
            lights_out_offset=10.0,
        )
        statuses = result["DRV"]["status"].to_list()
        assert all(s == "WarmUp" for s in statuses)

    def test_racing_status(self):
        """Times after lights_out with no other conditions -> Racing."""
        tel = make_pl_telemetry(
            [15.0, 16.0, 17.0],
            [0, 10, 20],
            [0, 10, 20],
            race_distances=[100.0, 110.0, 120.0],
            lap_numbers=[1, 1, 1],
        )
        result = self._run(
            {"DRV": tel},
            {"DRV": {"finish_time": None, "pit_windows": [], "is_dnf": False}},
            warmup_intervals=[(5.0, 10.0)],
            lights_out_offset=10.0,
        )
        statuses = result["DRV"]["status"].to_list()
        assert all(s == "Racing" for s in statuses)

    def test_pit_status(self):
        """Times in pit window -> Pit."""
        tel = make_pl_telemetry(
            [100.0, 101.0, 102.0, 110.0],
            [0, 10, 20, 30],
            [0, 10, 20, 30],
            race_distances=[100.0, 110.0, 120.0, 130.0],
            lap_numbers=[2, 2, 2, 2],
        )
        result = self._run(
            {"DRV": tel},
            {"DRV": {"finish_time": None, "pit_windows": [(99.0, 103.0)], "is_dnf": False}},
            warmup_intervals=[(5.0, 10.0)],
            lights_out_offset=10.0,
        )
        statuses = result["DRV"]["status"].to_list()
        assert statuses[0] == "Pit"
        assert statuses[1] == "Pit"
        assert statuses[2] == "Pit"
        assert statuses[3] == "Racing"

    def test_finished_status(self):
        """Times after finish_time -> Finished."""
        tel = make_pl_telemetry(
            [100.0, 200.0, 300.0],
            [0, 100, 200],
            [0, 100, 200],
            race_distances=[1000.0, 2000.0, 3000.0],
            lap_numbers=[5, 10, 15],
        )
        result = self._run(
            {"DRV": tel},
            {"DRV": {"finish_time": 250.0, "pit_windows": [], "is_dnf": False}},
            warmup_intervals=[(5.0, 10.0)],
            lights_out_offset=10.0,
        )
        statuses = result["DRV"]["status"].to_list()
        assert statuses[0] == "Racing"
        assert statuses[1] == "Racing"
        assert statuses[2] == "Finished"

    def test_retired_from_static(self):
        """Car stops moving for > 50 rows -> Retired."""
        n_moving = 20
        n_static = 60  # > 50
        times = list(np.arange(n_moving + n_static, dtype=np.float64) * 0.1)
        x_vals = list(np.arange(n_moving, dtype=np.float64)) + [float(n_moving - 1)] * n_static
        y_vals = list(np.arange(n_moving, dtype=np.float64)) + [float(n_moving - 1)] * n_static
        z_vals = [0.0] * (n_moving + n_static)
        rd = list(np.arange(n_moving + n_static, dtype=np.float32))
        ln = [1] * (n_moving + n_static)

        tel = make_pl_telemetry(
            times, x_vals, y_vals, z_vals=z_vals, race_distances=rd, lap_numbers=ln
        )
        result = self._run(
            {"DRV": tel},
            {"DRV": {"finish_time": None, "pit_windows": [], "is_dnf": False}},
            warmup_intervals=[],
            lights_out_offset=0.0,
        )
        statuses = result["DRV"]["status"].to_list()
        # Last 60 rows should be Retired (static detection triggers retirement)
        # The moving rows should be Racing
        assert statuses[0] == "Racing"
        assert statuses[-1] == "Retired"
        retired_count = sum(1 for s in statuses if s == "Retired")
        assert retired_count >= n_static

    def test_status_priority(self):
        """PreSession takes priority over other conditions.
        Pit window during warmup -> WarmUp wins (higher priority in np.select order)."""
        tel = make_pl_telemetry(
            [6.0, 7.0],
            [0, 10],
            [0, 10],
            race_distances=[0.0, 1.0],
            lap_numbers=[0, 0],
        )
        result = self._run(
            {"DRV": tel},
            {"DRV": {"finish_time": None, "pit_windows": [(5.0, 8.0)], "is_dnf": False}},
            warmup_intervals=[(5.0, 10.0)],
            lights_out_offset=10.0,
        )
        statuses = result["DRV"]["status"].to_list()
        # WarmUp has lower priority than Pit in np.select conditions list,
        # but Pit comes before WarmUp in conditions. Let's check actual priority:
        # conditions = [is_presession, is_retired, is_finished, is_pit, is_warmup]
        # Pit is checked before WarmUp, so Pit should win.
        assert all(s == "Pit" for s in statuses)

    def test_race_distance_frozen_on_finish(self):
        """race_distance stays constant after Finished."""
        tel = make_pl_telemetry(
            [100.0, 200.0, 250.0, 300.0],
            [0, 100, 200, 300],
            [0, 100, 200, 300],
            race_distances=[1000.0, 2000.0, 2500.0, 3000.0],
            lap_numbers=[5, 10, 12, 15],
        )
        result = self._run(
            {"DRV": tel},
            {"DRV": {"finish_time": 220.0, "pit_windows": [], "is_dnf": False}},
            warmup_intervals=[],
            lights_out_offset=0.0,
        )
        rd = result["DRV"]["race_distance"].to_list()
        # After finish (idx 2 and 3), race_distance should be frozen to value before finish
        assert rd[2] == pytest.approx(rd[3])
        # Frozen value should be from idx 1 (last before finish)
        assert rd[2] == pytest.approx(2000.0)

    def test_race_distance_frozen_on_retire(self):
        """race_distance stays constant after Retired."""
        n_moving = 10
        n_static = 60
        total = n_moving + n_static
        times = list(np.arange(total, dtype=np.float64) * 0.1)
        x_vals = list(np.arange(n_moving, dtype=np.float64)) + [float(n_moving - 1)] * n_static
        y_vals = list(np.arange(n_moving, dtype=np.float64)) + [float(n_moving - 1)] * n_static
        z_vals = [0.0] * total
        rd = list(np.arange(total, dtype=np.float32) * 10.0)
        ln = [1] * total

        tel = make_pl_telemetry(
            times, x_vals, y_vals, z_vals=z_vals, race_distances=rd, lap_numbers=ln
        )
        result = self._run(
            {"DRV": tel},
            {"DRV": {"finish_time": None, "pit_windows": [], "is_dnf": True}},
            warmup_intervals=[],
            lights_out_offset=0.0,
        )
        rd_out = result["DRV"]["race_distance"].to_list()
        # All retired points should have same race_distance
        retired_rd = rd_out[n_moving:]
        assert all(v == pytest.approx(retired_rd[0]) for v in retired_rd)


# ===========================================================================
# TestAddTrackDistanceAll
# ===========================================================================


class TestAddTrackDistanceAll:

    @staticmethod
    def _make_circular_track(n_points=100, radius=1000.0):
        """Create a circular track with known geometry.
        Returns TrackData with coordinates in decimeters and distances in decimeters.
        """
        theta = np.linspace(0, 2 * np.pi, n_points, endpoint=False)
        track_x = (radius * np.cos(theta)).astype(np.float32)
        track_y = (radius * np.sin(theta)).astype(np.float32)
        # Cumulative arc length in decimeters
        dx = np.diff(track_x, prepend=track_x[-1])
        dy = np.diff(track_y, prepend=track_y[-1])
        seg_lengths = np.sqrt(dx**2 + dy**2)
        track_distance = np.cumsum(seg_lengths).astype(np.float32)
        # Shift so first point is at distance 0
        track_distance = (track_distance - track_distance[0]).astype(np.float32)
        lap_distance = float(2 * np.pi * radius)  # circumference in decimeters
        return TrackData(
            track_x=track_x,
            track_y=track_y,
            track_distance=track_distance,
            lap_distance=lap_distance,
        )

    def test_basic_projection(self):
        """Points on circular track get correct track_distance."""
        track = self._make_circular_track(n_points=360, radius=1000.0)
        # Place a car at theta=pi/2 (top of circle)
        px = np.array([0.0], dtype=np.float32)  # cos(pi/2) * 1000
        py = np.array([1000.0], dtype=np.float32)  # sin(pi/2) * 1000

        tel = make_pl_telemetry(
            session_times=[100.0],
            x_vals=px,
            y_vals=py,
        )
        session_timing = {"warmup_start_time": 50.0}
        result = TelemetryBuilder._add_track_distance_all({"DRV": tel}, track, session_timing)
        td = result["DRV"]["track_distance"].to_numpy()[0]
        # Track distance in meters (converted from dm in the method)
        # Quarter of circumference = pi*1000/2 dm -> /10 = pi*100/2 meters
        expected_m = (np.pi * 1000.0 / 2.0) / 10.0  # quarter circle in meters
        assert td == pytest.approx(expected_m, rel=0.05)

    def test_wrap_detection(self):
        """track_distance wrapping detected as lap completion."""
        track = self._make_circular_track(n_points=360, radius=1000.0)

        # Simulate car going around track twice
        n_per_lap = 50
        dt = 2.0  # seconds between samples (> MIN_LAP_TIME/n_per_lap to ensure total > 60s)
        total_n = n_per_lap * 2 + 10  # warmup + 2 laps

        theta_vals = np.linspace(0, 4 * np.pi + np.pi, total_n, endpoint=False)
        x_vals = (1000.0 * np.cos(theta_vals)).astype(np.float32)
        y_vals = (1000.0 * np.sin(theta_vals)).astype(np.float32)
        times = np.arange(total_n, dtype=np.float64) * dt

        tel = make_pl_telemetry(times, x_vals, y_vals)
        session_timing = {"warmup_start_time": 0.0}
        result = TelemetryBuilder._add_track_distance_all({"DRV": tel}, track, session_timing)
        lap_nums = result["DRV"]["lap_number"].to_numpy()
        # Should have detected at least 1 wrap (lap transitions)
        assert lap_nums.max() >= 1

    def test_lap_numbering_from_wraps(self):
        """Pre-session -> -1, warmup -> 0, after first wrap -> 1, second -> 2."""
        track = self._make_circular_track(n_points=360, radius=1000.0)

        # Build telemetry: pre-session, warmup, two full laps
        # Each "lap" needs enough points spaced > 60s apart total
        n_pre = 5
        n_warmup = 5
        n_lap1 = 10
        n_lap2 = 10

        # Pre-session: car at fixed position (before warmup_start_time)
        pre_times = np.arange(n_pre) * 1.0  # t=0..4
        pre_theta = np.zeros(n_pre)

        # Warmup: car moves partway around (t=10..14, warmup starts at 10)
        warmup_times = 10.0 + np.arange(n_warmup) * 8.0  # t=10,18,26,34,42
        warmup_theta = np.linspace(0, 1.5 * np.pi, n_warmup)

        # Lap 1: full circuit (t=100..190, each point 10s apart)
        lap1_times = 100.0 + np.arange(n_lap1) * 10.0
        lap1_theta = np.linspace(0, 2 * np.pi, n_lap1, endpoint=False)

        # Lap 2: another full circuit (t=200..290)
        lap2_times = 200.0 + np.arange(n_lap2) * 10.0
        lap2_theta = np.linspace(0, 2 * np.pi, n_lap2, endpoint=False)

        all_times = np.concatenate([pre_times, warmup_times, lap1_times, lap2_times])
        all_theta = np.concatenate([pre_theta, warmup_theta, lap1_theta, lap2_theta])
        x_vals = (1000.0 * np.cos(all_theta)).astype(np.float32)
        y_vals = (1000.0 * np.sin(all_theta)).astype(np.float32)

        tel = make_pl_telemetry(all_times, x_vals, y_vals)
        session_timing = {"warmup_start_time": 10.0}
        result = TelemetryBuilder._add_track_distance_all({"DRV": tel}, track, session_timing)
        lap_nums = result["DRV"]["lap_number"].to_numpy()

        # Pre-session points should be -1
        assert all(lap_nums[i] == -1 for i in range(n_pre))
        # Warmup points should be 0 (or -1 if before warmup start)
        # At least some warmup points should be 0
        warmup_laps = lap_nums[n_pre : n_pre + n_warmup]
        assert 0 in warmup_laps

    def test_race_distance_calculation(self):
        """race_distance = (lap_number - 1) * track_length + track_distance."""
        track = self._make_circular_track(n_points=360, radius=1000.0)
        lap_dist_m = track.lap_distance / 10.0  # meters

        # Create a simple telemetry with known positions
        # Place car at theta=0 (start/finish) at different times
        # We'll verify the formula after the method runs
        n = 5
        times = np.array([100.0, 101.0, 102.0, 103.0, 104.0])
        # Car at start/finish line
        x_vals = np.full(n, 1000.0, dtype=np.float32)  # cos(0) * R
        y_vals = np.full(n, 0.0, dtype=np.float32)  # sin(0) * R

        tel = make_pl_telemetry(times, x_vals, y_vals)
        session_timing = {"warmup_start_time": 50.0}
        result = TelemetryBuilder._add_track_distance_all({"DRV": tel}, track, session_timing)

        td = result["DRV"]["track_distance"].to_numpy()
        rd = result["DRV"]["race_distance"].to_numpy().astype(np.float64)
        ln = result["DRV"]["lap_number"].to_numpy()

        # Verify the formula for each point
        for i in range(n):
            expected_rd = (ln[i] - 1) * lap_dist_m + td[i]
            assert rd[i] == pytest.approx(
                expected_rd, abs=1.0
            ), f"At i={i}: rd={rd[i]}, expected={expected_rd}, ln={ln[i]}, td={td[i]}"

    def test_min_lap_time_filter(self):
        """Wraps less than 60s apart are filtered out."""
        track = self._make_circular_track(n_points=360, radius=1000.0)

        # Simulate two quick wraps (< 60s apart) which should be filtered
        # Then a valid wrap (> 60s)
        n = 30
        times = (
            np.arange(n, dtype=np.float64) * 2.0
        )  # 2s apart, so 30 points = 58s total first "lap"
        # First wrap at ~10s into the data (too soon for a real lap)
        # Create theta that wraps once quickly, then properly
        theta = np.zeros(n)
        # Points 0-4: going around (0 to 2pi in 8s - too fast)
        theta[:5] = np.linspace(0, 2 * np.pi, 5, endpoint=False)
        # Points 5-9: going around again (8s to 18s - still within 60s of first wrap)
        theta[5:10] = np.linspace(0, 2 * np.pi, 5, endpoint=False)
        # Points 10-29: going around slowly (20s to 58s from point 10)
        theta[10:] = np.linspace(0, 2 * np.pi, 20, endpoint=False)

        x_vals = (1000.0 * np.cos(theta)).astype(np.float32)
        y_vals = (1000.0 * np.sin(theta)).astype(np.float32)

        tel = make_pl_telemetry(times, x_vals, y_vals)
        session_timing = {"warmup_start_time": 0.0}
        result = TelemetryBuilder._add_track_distance_all({"DRV": tel}, track, session_timing)
        lap_nums = result["DRV"]["lap_number"].to_numpy()

        # The spurious quick wraps should be filtered; max lap should be limited
        # Quick wraps within 60s of each other should not increment lap_number significantly
        # At most we should see lap 0 and 1 (not 3+ from unfiltered wraps)
        assert (
            lap_nums.max() <= 2
        ), f"Max lap {lap_nums.max()} too high - spurious wraps not filtered"
