"""Tests for F1DataMixin and frozen dataclasses."""

import pytest

from f1_replay.models.event import EventInfo, SessionInfo, get_location_dir


class TestF1DataMixin:
    """Test dict-like access on F1DataMixin subclasses (e.g., SessionMetadata)."""

    def test_keys(self, sample_session_metadata):
        keys = sample_session_metadata.keys()
        assert "session_type" in keys
        assert "year" in keys
        assert "drivers" in keys

    def test_getitem(self, sample_session_metadata):
        assert sample_session_metadata["session_type"] == "R"
        assert sample_session_metadata["year"] == 2024

    def test_getitem_missing(self, sample_session_metadata):
        with pytest.raises(KeyError):
            sample_session_metadata["nonexistent"]

    def test_get_default(self, sample_session_metadata):
        assert sample_session_metadata.get("session_type") == "R"
        assert sample_session_metadata.get("missing", "default") == "default"

    def test_contains(self, sample_session_metadata):
        assert "session_type" in sample_session_metadata
        assert "missing" not in sample_session_metadata

    def test_to_dict(self, sample_session_metadata):
        d = sample_session_metadata.to_dict()
        assert isinstance(d, dict)
        assert d["session_type"] == "R"
        assert d["year"] == 2024

    def test_items(self, sample_session_metadata):
        items = sample_session_metadata.items()
        names = [k for k, v in items]
        assert "session_type" in names


class TestEventInfo:
    """Test EventInfo frozen dataclass."""

    def test_frozen(self, sample_event_info):
        with pytest.raises(AttributeError):
            sample_event_info.name = "Changed"

    def test_session_schedule(self, sample_event_info):
        schedule = sample_event_info.session_schedule
        assert "Race" in schedule
        assert "Qualifying" in schedule

    def test_get_session_date(self, sample_event_info):
        date = sample_event_info.get_session_date("Race")
        assert date == "2024-05-26T15:00:00+02:00"
        assert sample_event_info.get_session_date("Missing") is None

    def test_repr(self, sample_event_info):
        r = repr(sample_event_info)
        assert "Monaco" in r
        assert "2024" in r


class TestGetLocationDir:
    """Test location directory name generation."""

    def test_simple(self, sample_event_info):
        assert get_location_dir(sample_event_info) == "08_Monte_Carlo"

    def test_spaces_replaced(self):
        event = EventInfo(
            name="Test GP",
            official_name="",
            circuit_name="Abu Dhabi",
            country="UAE",
            year=2024,
            round_number=21,
            start_date="",
            end_date="",
        )
        assert get_location_dir(event) == "21_Abu_Dhabi"


class TestSessionInfo:
    """Test SessionInfo."""

    def test_frozen(self):
        s = SessionInfo(name="Race", date="2024-05-26T15:00:00+02:00")
        with pytest.raises(AttributeError):
            s.name = "Changed"

    def test_repr(self):
        s = SessionInfo(name="Race", date="2024-05-26T15:00:00+02:00")
        assert "Race" in repr(s)
