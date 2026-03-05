"""Tests for WeatherExtractor rain event pairing."""

import polars as pl

from f1_replay.loaders.session.weather import WeatherExtractor


class TestExtractRainEvents:
    """Test rain start/end pairing."""

    def test_single_rain_period(self):
        df = pl.DataFrame(
            {
                "session_time": [0.0, 10.0, 20.0, 30.0, 40.0],
                "rainfall": [False, True, True, False, False],
            }
        )
        result = WeatherExtractor.extract_rain_events(df)
        assert len(result) == 1
        assert result["start_time"][0] == 10.0
        assert result["end_time"][0] == 30.0
        assert result["duration"][0] == 20.0

    def test_multiple_rain_periods(self):
        df = pl.DataFrame(
            {
                "session_time": [0.0, 10.0, 20.0, 30.0, 40.0, 50.0],
                "rainfall": [False, True, False, False, True, False],
            }
        )
        result = WeatherExtractor.extract_rain_events(df)
        assert len(result) == 2

    def test_no_rain(self):
        df = pl.DataFrame(
            {
                "session_time": [0.0, 10.0, 20.0],
                "rainfall": [False, False, False],
            }
        )
        result = WeatherExtractor.extract_rain_events(df)
        assert len(result) == 0

    def test_rain_at_start(self):
        df = pl.DataFrame(
            {
                "session_time": [0.0, 10.0, 20.0],
                "rainfall": [True, True, False],
            }
        )
        result = WeatherExtractor.extract_rain_events(df)
        assert len(result) == 1
        assert result["start_time"][0] == 0.0

    def test_rain_ongoing_at_end(self):
        df = pl.DataFrame(
            {
                "session_time": [0.0, 10.0, 20.0],
                "rainfall": [False, True, True],
            }
        )
        result = WeatherExtractor.extract_rain_events(df)
        assert len(result) == 1
        assert result["end_time"][0] == 20.0

    def test_empty_dataframe(self):
        df = pl.DataFrame({"session_time": [], "rainfall": []})
        result = WeatherExtractor.extract_rain_events(df)
        assert len(result) == 0

    def test_missing_columns(self):
        df = pl.DataFrame({"time": [0.0], "temp": [20.0]})
        result = WeatherExtractor.extract_rain_events(df)
        assert len(result) == 0
