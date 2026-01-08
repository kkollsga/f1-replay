"""
Weather Extractor - Extract and compact weather events from session data

Focuses on rain events: only records when rain starts and when it ends.
"""

from typing import Optional, List
import numpy as np
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

        # Vectorized approach using polars shift
        df = weather_df.select([
            pl.col("session_time"),
            pl.col("rainfall").cast(pl.Boolean)
        ]).with_columns([
            pl.col("rainfall").shift(1).alias("prev_rainfall")
        ])

        # Find transitions: start (False->True) and end (True->False)
        starts = df.filter(
            pl.col("rainfall") & (pl.col("prev_rainfall").is_null() | ~pl.col("prev_rainfall"))
        ).select("session_time").to_series().to_list()

        ends = df.filter(
            ~pl.col("rainfall") & pl.col("prev_rainfall").fill_null(False)
        ).select("session_time").to_series().to_list()

        # Handle case where rain is ongoing at end
        rainfall_arr = weather_df["rainfall"].to_numpy()
        if len(rainfall_arr) > 0 and rainfall_arr[-1]:
            ends.append(float(weather_df["session_time"][-1]))

        # Build rain events
        rain_events = []
        for i, start in enumerate(starts):
            # Find matching end (first end after this start)
            matching_ends = [e for e in ends if e > start]
            if matching_ends:
                end = matching_ends[0]
                rain_events.append({
                    "start_time": float(start),
                    "end_time": float(end),
                    "duration": float(end - start)
                })

        if not rain_events:
            return pl.DataFrame({"start_time": [], "end_time": [], "duration": []})

        return pl.DataFrame(rain_events).select([
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

        # Vectorized check
        starts = rain_events["start_time"].to_numpy()
        ends = rain_events["end_time"].to_numpy()
        return bool(np.any((starts <= session_time) & (session_time <= ends)))

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

        # Early exit if no rain events
        if len(rain_events) == 0:
            for driver, tel in telemetry_dict.items():
                if "session_time" in tel.columns:
                    tel = tel.with_columns(pl.lit(False).alias("is_raining"))
                result[driver] = tel
            return result

        # Pre-extract rain intervals as numpy arrays (once)
        starts = rain_events["start_time"].to_numpy()
        ends = rain_events["end_time"].to_numpy()

        for driver, tel in telemetry_dict.items():
            if "session_time" not in tel.columns:
                result[driver] = tel
                continue

            # Vectorized: check all session times against all rain intervals
            times = tel["session_time"].to_numpy()

            # Broadcasting: times[:, None] vs starts[None, :] gives (n_times, n_events) matrix
            # For each time, check if it falls within ANY rain interval
            in_rain = np.any(
                (times[:, None] >= starts[None, :]) & (times[:, None] <= ends[None, :]),
                axis=1
            )

            tel_with_rain = tel.with_columns([
                pl.Series("is_raining", in_rain, dtype=pl.Boolean)
            ])
            result[driver] = tel_with_rain

        return result
