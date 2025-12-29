"""
Weather Extractor - Extract and compact weather events from session data

Focuses on rain events: only records when rain starts and when it ends.
"""

from typing import Optional, List
import polars as pl


class WeatherExtractor:
    """Extract and compact weather information from session events."""

    @staticmethod
    def extract_rain_events(weather_df: pl.DataFrame) -> pl.DataFrame:
        """
        Extract rain start/end events from weather data.

        Compacts boolean rainfall data into a minimal dataset showing only
        transitions: when rain starts and when it ends.

        Args:
            weather_df: Weather DataFrame with 'rainfall' (bool) and 'session_time' (float) columns

        Returns:
            Polars DataFrame with columns: start_time, end_time, duration
            Each row represents one continuous rain period.
        """
        if len(weather_df) == 0:
            return pl.DataFrame({"start_time": [], "end_time": [], "duration": []})

        if "rainfall" not in weather_df.columns or "session_time" not in weather_df.columns:
            return pl.DataFrame({"start_time": [], "end_time": [], "duration": []})

        # Get rainfall and session_time columns
        rainfall = weather_df["rainfall"].to_list()
        times = weather_df["session_time"].to_list()

        # Find transitions
        rain_events = []
        rain_start = None

        for i in range(len(rainfall)):
            # Check for start of rain (false->true)
            if rainfall[i] and (i == 0 or not rainfall[i - 1]):
                rain_start = float(times[i])

            # Check for end of rain (true->false)
            if not rainfall[i] and i > 0 and rainfall[i - 1]:
                if rain_start is not None:
                    rain_end = float(times[i])
                    duration = rain_end - rain_start
                    rain_events.append({
                        "start_time": rain_start,
                        "end_time": rain_end,
                        "duration": duration
                    })
                    rain_start = None

        # Handle case where rain is still ongoing at end of session
        if rain_start is not None and len(rainfall) > 0 and rainfall[-1]:
            rain_end = float(times[-1])
            duration = rain_end - rain_start
            rain_events.append({
                "start_time": rain_start,
                "end_time": rain_end,
                "duration": duration
            })

        if not rain_events:
            return pl.DataFrame({"start_time": [], "end_time": [], "duration": []})

        # Convert to DataFrame
        df = pl.DataFrame(rain_events)
        return df.select([
            pl.col("start_time").cast(pl.Float64),
            pl.col("end_time").cast(pl.Float64),
            pl.col("duration").cast(pl.Float64)
        ])

    @staticmethod
    def is_raining(rain_events: pl.DataFrame, session_time: float) -> bool:
        """
        Check if it's raining at a specific session time.

        Args:
            rain_events: Rain events DataFrame from extract_rain_events()
            session_time: Session time in seconds

        Returns:
            True if raining at this time, False otherwise
        """
        if len(rain_events) == 0:
            return False

        for row in rain_events.to_dicts():
            if row["start_time"] <= session_time <= row["end_time"]:
                return True

        return False

    @staticmethod
    def add_rain_flag_to_telemetry(telemetry_dict, rain_events: pl.DataFrame):
        """
        Add a 'is_raining' column to all driver telemetry.

        Args:
            telemetry_dict: Dict of driver code -> telemetry DataFrame
            rain_events: Rain events DataFrame from extract_rain_events()

        Returns:
            Dict of driver code -> telemetry DataFrame with 'is_raining' column
        """
        result = {}

        for driver, tel in telemetry_dict.items():
            if "session_time" not in tel.columns:
                result[driver] = tel
                continue

            # Create is_raining column
            is_raining = []
            for session_time in tel["session_time"].to_list():
                is_raining.append(WeatherExtractor.is_raining(rain_events, float(session_time)))

            tel_with_rain = tel.with_columns([
                pl.Series("is_raining", is_raining, dtype=pl.Boolean)
            ])
            result[driver] = tel_with_rain

        return result
