"""Tests for JSON serialization utilities."""

import math
from datetime import timedelta

import numpy as np
import polars as pl
import pytest

from f1_replay.api.serializers import to_json_safe, serialize_telemetry


class TestToJsonSafe:
    """Test recursive JSON-safe conversion."""

    def test_nan_to_none(self):
        assert to_json_safe(float("nan")) is None

    def test_inf_to_none(self):
        assert to_json_safe(float("inf")) is None
        assert to_json_safe(float("-inf")) is None

    def test_normal_float(self):
        assert to_json_safe(3.14) == 3.14

    def test_numpy_int(self):
        val = to_json_safe(np.int64(42))
        assert val == 42
        assert isinstance(val, int)

    def test_numpy_float(self):
        val = to_json_safe(np.float64(3.14))
        assert isinstance(val, float)

    def test_numpy_float_nan(self):
        assert to_json_safe(np.float64("nan")) is None

    def test_numpy_array(self):
        arr = np.array([1, 2, 3])
        result = to_json_safe(arr)
        assert result == [1, 2, 3]

    def test_polars_dataframe(self):
        df = pl.DataFrame({"a": [1, 2], "b": ["x", "y"]})
        result = to_json_safe(df)
        assert result == [{"a": 1, "b": "x"}, {"a": 2, "b": "y"}]

    def test_timedelta(self):
        td = timedelta(seconds=90.5)
        assert to_json_safe(td) == 90.5

    def test_dict_recursive(self):
        d = {"a": float("nan"), "b": np.int64(1), "c": [np.float64(2.0)]}
        result = to_json_safe(d)
        assert result == {"a": None, "b": 1, "c": [2.0]}

    def test_dataclass(self, sample_event_info):
        result = to_json_safe(sample_event_info)
        assert isinstance(result, dict)
        assert result["name"] == "Monaco Grand Prix"
        assert result["year"] == 2024

    def test_string_passthrough(self):
        assert to_json_safe("hello") == "hello"

    def test_none_passthrough(self):
        assert to_json_safe(None) is None


class TestSerializeTelemetry:
    """Test telemetry serialization with field filtering."""

    def test_default_fields(self, sample_telemetry):
        result = serialize_telemetry(sample_telemetry)
        assert "VER" in result
        assert "session_time" in result["VER"]
        assert len(result["VER"]["session_time"]) == 10

    def test_custom_fields(self, sample_telemetry):
        result = serialize_telemetry(sample_telemetry, fields=["session_time", "speed"])
        assert set(result["VER"].keys()) == {"session_time", "speed"}

    def test_missing_fields_ignored(self, sample_telemetry):
        result = serialize_telemetry(sample_telemetry, fields=["session_time", "nonexistent"])
        assert "session_time" in result["VER"]
        assert "nonexistent" not in result["VER"]

    def test_empty_telemetry(self):
        result = serialize_telemetry({})
        assert result == {}

    def test_float_rounding(self, sample_telemetry):
        result = serialize_telemetry(sample_telemetry, fields=["session_time"])
        # session_time is rounded to 2 decimal places
        for val in result["VER"]["session_time"]:
            if val is not None:
                assert round(val, 2) == val
