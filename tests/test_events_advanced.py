"""Tests for f1_replay.loaders.session.events: parse_time, consolidate, and synthetic events."""

import pytest
import pandas as pd

from f1_replay.models import TrackStatusEvent, T0Info
from f1_replay.loaders.session.events import (
    parse_time_to_session_seconds,
    consolidate_track_status_intervals,
    add_synthetic_events,
)


def make_event(session_time, status, message="", scope="Track", sector=None, driver_num="", end_time=None):
    return TrackStatusEvent(
        session_time=session_time, status=status, message=message,
        scope=scope, sector=sector, driver_num=driver_num, end_time=end_time
    )


# ---------------------------------------------------------------------------
# parse_time_to_session_seconds
# ---------------------------------------------------------------------------
class TestParseTimeToSessionSeconds:

    def test_none_returns_zero(self):
        assert parse_time_to_session_seconds(None, None, None) == 0.0

    def test_timedelta(self):
        td = pd.Timedelta(seconds=42.5)
        assert parse_time_to_session_seconds(td, None, None) == 42.5

    def test_timestamp_with_t0_datetime(self):
        t0 = pd.Timestamp("2024-06-01 14:00:00")
        ts = pd.Timestamp("2024-06-01 14:01:30")
        result = parse_time_to_session_seconds(ts, None, t0)
        assert result == pytest.approx(90.0)

    def test_timestamp_with_t0_seconds_of_day(self):
        # 14:00:00 = 50400 seconds of day
        t0_sod = 50400.0
        ts = pd.Timestamp("2024-06-01 14:01:30")  # 50490 seconds of day
        result = parse_time_to_session_seconds(ts, t0_sod, None)
        assert result == pytest.approx(90.0)

    def test_timestamp_no_reference(self):
        ts = pd.Timestamp("2024-06-01 14:01:30")
        assert parse_time_to_session_seconds(ts, None, None) == 0.0

    def test_float_passthrough(self):
        assert parse_time_to_session_seconds(123.456, None, None) == pytest.approx(123.456)

    def test_invalid_value(self):
        # An object whose float() raises
        class BadValue:
            def __float__(self):
                raise ValueError("nope")
        assert parse_time_to_session_seconds(BadValue(), None, None) == 0.0


# ---------------------------------------------------------------------------
# consolidate_track_status_intervals
# ---------------------------------------------------------------------------
class TestConsolidateTrackStatus:

    def _t0(self, **kwargs):
        defaults = dict(utc="2024-06-01T14:00:00", lights_out_offset=30.0)
        defaults.update(kwargs)
        return T0Info(**defaults)

    # -- basic --

    def test_empty_list(self):
        intervals, report = consolidate_track_status_intervals([], None)
        assert intervals == []
        assert report['total_input_events'] == 0
        assert report['total_output_intervals'] == 0
        assert report['summary']['merged_count'] == 0
        assert report['summary']['instant_count'] == 0
        assert report['summary']['ongoing_count'] == 0

    def test_warmup_to_lights_out(self):
        events = [
            make_event(0.0, "SessionStart", "Start of Session"),
            make_event(30.0, "LightsOut"),
        ]
        intervals, _ = consolidate_track_status_intervals(events, self._t0())
        # Should produce: WarmUp interval [0, 30] + LightsOut instant
        warmup = [i for i in intervals if i.status == "WarmUp"]
        lights = [i for i in intervals if i.status == "LightsOut"]
        assert len(warmup) == 1
        assert warmup[0].session_time == 0.0
        assert warmup[0].end_time == 30.0
        assert len(lights) == 1
        assert lights[0].session_time == 30.0

    def test_yellow_then_clear(self):
        events = [
            make_event(10.0, "Yellow", "YELLOW IN SECTOR 1", scope="Sector", sector=1),
            make_event(20.0, "AllClear", "GREEN IN SECTOR 1", scope="Sector", sector=1),
        ]
        intervals, _ = consolidate_track_status_intervals(events, None)
        yellows = [i for i in intervals if i.status == "Yellow"]
        assert len(yellows) == 1
        assert yellows[0].session_time == 10.0
        assert yellows[0].end_time == 20.0
        assert yellows[0].sector == 1

    def test_safety_car_then_clear(self):
        events = [
            make_event(50.0, "SafetyCar", "SAFETY CAR DEPLOYED"),
            make_event(100.0, "AllClear", "GREEN FLAG"),
        ]
        intervals, _ = consolidate_track_status_intervals(events, None)
        sc = [i for i in intervals if i.status == "SafetyCar"]
        assert len(sc) == 1
        assert sc[0].session_time == 50.0
        assert sc[0].end_time == 100.0

    def test_sector_specific_clear(self):
        events = [
            make_event(10.0, "Yellow", scope="Sector", sector=1),
            make_event(12.0, "Yellow", scope="Sector", sector=2),
            make_event(20.0, "AllClear", scope="Sector", sector=1),
        ]
        intervals, _ = consolidate_track_status_intervals(events, None)
        closed = [i for i in intervals if i.end_time is not None]
        ongoing = [i for i in intervals if i.end_time is None]
        # Sector 1 should be closed
        assert len(closed) == 1
        assert closed[0].sector == 1
        assert closed[0].end_time == 20.0
        # Sector 2 still open (ongoing)
        assert len(ongoing) == 1
        assert ongoing[0].sector == 2

    def test_track_wide_clear_closes_all(self):
        events = [
            make_event(10.0, "Yellow", scope="Track", sector=1),
            make_event(12.0, "Yellow", scope="Track", sector=2),
            make_event(25.0, "AllClear", scope="Track", sector=None),
        ]
        intervals, _ = consolidate_track_status_intervals(events, None)
        # Both should be closed
        assert all(i.end_time == 25.0 for i in intervals)
        assert len(intervals) == 2

    def test_chequered_closes_everything(self):
        events = [
            make_event(10.0, "Yellow", scope="Sector", sector=1),
            make_event(50.0, "SafetyCar"),
            make_event(200.0, "Chequered", "CHEQUERED FLAG"),
        ]
        intervals, _ = consolidate_track_status_intervals(events, None)
        chequered = [i for i in intervals if i.status == "Chequered"]
        assert len(chequered) == 1
        closed = [i for i in intervals if i.status != "Chequered"]
        assert len(closed) == 2
        assert all(i.end_time == 200.0 for i in closed)

    def test_rain_event_passthrough(self):
        rain = make_event(100.0, "Rain", "RAIN REPORTED", end_time=300.0)
        intervals, report = consolidate_track_status_intervals([rain], None)
        assert len(intervals) == 1
        assert intervals[0].status == "Rain"
        assert intervals[0].session_time == 100.0
        assert intervals[0].end_time == 300.0
        assert report['summary']['merged_count'] == 1

    def test_blue_flag_instant(self):
        blue = make_event(60.0, "Blue", "BLUE FLAG FOR 44", driver_num="44")
        intervals, report = consolidate_track_status_intervals([blue], None)
        assert len(intervals) == 1
        assert intervals[0].status == "Blue"
        assert intervals[0].session_time == 60.0
        assert intervals[0].end_time is None
        assert report['summary']['instant_count'] == 1

    def test_aborted_start(self):
        events = [
            make_event(0.0, "SessionStart", "Start of Session"),
            make_event(25.0, "AbortedStart", "ABORTED START"),
        ]
        intervals, report = consolidate_track_status_intervals(events, None)
        warmup = [i for i in intervals if i.status == "WarmUp"]
        aborted = [i for i in intervals if i.status == "AbortedStart"]
        assert len(warmup) == 1
        assert warmup[0].session_time == 0.0
        assert warmup[0].end_time == 25.0
        assert len(aborted) == 1
        assert aborted[0].session_time == 25.0
        assert report['summary']['instant_count'] == 1

    def test_ongoing_status(self):
        events = [
            make_event(10.0, "Yellow", scope="Sector", sector=3),
        ]
        intervals, report = consolidate_track_status_intervals(events, None)
        assert len(intervals) == 1
        assert intervals[0].status == "Yellow"
        assert intervals[0].end_time is None
        assert report['summary']['ongoing_count'] == 1

    def test_formation_lap_then_lights_out(self):
        events = [
            make_event(5.0, "FormationLap", "GREEN LIGHT - PIT EXIT OPEN"),
            make_event(35.0, "LightsOut"),
        ]
        intervals, _ = consolidate_track_status_intervals(events, None)
        warmup = [i for i in intervals if i.status == "WarmUp"]
        lights = [i for i in intervals if i.status == "LightsOut"]
        assert len(warmup) == 1
        assert warmup[0].session_time == 5.0
        assert warmup[0].end_time == 35.0
        assert len(lights) == 1

    def test_vsc_ending(self):
        events = [
            make_event(80.0, "VSCEnding", "VSC ENDING"),
            make_event(95.0, "AllClear", "GREEN FLAG"),
        ]
        intervals, _ = consolidate_track_status_intervals(events, None)
        vsc = [i for i in intervals if i.status == "VSCEnding"]
        assert len(vsc) == 1
        assert vsc[0].session_time == 80.0
        assert vsc[0].end_time == 95.0

    def test_report_counts(self):
        events = [
            make_event(0.0, "SessionStart"),
            make_event(30.0, "LightsOut"),
            make_event(60.0, "Yellow", scope="Sector", sector=1),
            make_event(70.0, "AllClear", scope="Sector", sector=1),
            make_event(100.0, "Blue", driver_num="44"),
            make_event(200.0, "Yellow", scope="Sector", sector=2),
        ]
        _, report = consolidate_track_status_intervals(events, None)
        assert report['total_input_events'] == 6
        assert report['summary']['merged_count'] == 2  # WarmUp + Yellow sector 1
        assert report['summary']['instant_count'] == 2  # LightsOut + Blue
        assert report['summary']['ongoing_count'] == 1  # Yellow sector 2


# ---------------------------------------------------------------------------
# add_synthetic_events
# ---------------------------------------------------------------------------
class TestAddSyntheticEvents:

    def test_adds_session_start(self):
        t0 = T0Info(utc="2024-06-01T14:00:00", lights_out_offset=30.0, warmup_start_offset=0.0)
        result = add_synthetic_events([], t0)
        starts = [e for e in result if e.status == "SessionStart"]
        assert len(starts) == 1
        assert starts[0].session_time == 0.0

    def test_adds_lights_out(self):
        t0 = T0Info(utc="2024-06-01T14:00:00", lights_out_offset=45.0)
        result = add_synthetic_events([], t0)
        lo = [e for e in result if e.status == "LightsOut"]
        assert len(lo) == 1
        assert lo[0].session_time == 45.0

    def test_no_t0_info(self):
        original = [make_event(10.0, "Yellow")]
        result = add_synthetic_events(original, None)
        assert result is original
        assert len(result) == 1

    def test_both_events(self):
        t0 = T0Info(utc="2024-06-01T14:00:00", lights_out_offset=30.0, warmup_start_offset=0.0)
        result = add_synthetic_events([], t0)
        statuses = [e.status for e in result]
        assert "SessionStart" in statuses
        assert "LightsOut" in statuses
        assert len(result) == 2
