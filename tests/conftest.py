"""Shared fixtures for f1-replay tests."""

import numpy as np
import polars as pl
import pytest

from f1_replay.models.event import EventInfo, SessionInfo
from f1_replay.models.session import (
    EventsData,
    ResultsData,
    SessionData,
    SessionMetadata,
    T0Info,
)
from f1_replay.models.weekend import (
    CircuitData,
    Corner,
    F1Weekend,
    MarshalSector,
    TrackGeometry,
)


@pytest.fixture
def sample_event_info():
    """Realistic EventInfo for Monaco 2024."""
    return EventInfo(
        name="Monaco Grand Prix",
        official_name="FORMULA 1 GRAND PRIX DE MONACO 2024",
        circuit_name="Monte Carlo",
        country="Monaco",
        year=2024,
        round_number=8,
        start_date="2024-05-23",
        end_date="2024-05-26",
        sessions=[
            SessionInfo(name="Practice 1", date="2024-05-23T13:30:00+02:00"),
            SessionInfo(name="Practice 2", date="2024-05-23T17:00:00+02:00"),
            SessionInfo(name="Practice 3", date="2024-05-24T12:30:00+02:00"),
            SessionInfo(name="Qualifying", date="2024-05-25T16:00:00+02:00"),
            SessionInfo(name="Race", date="2024-05-26T15:00:00+02:00"),
        ],
        timezone_offset="+02:00",
        format="conventional",
    )


@pytest.fixture
def sample_track_geometry():
    """Simple circular track (easy to verify projection math)."""
    n = 100
    t = np.linspace(0, 2 * np.pi, n, endpoint=False)
    radius = 1000.0  # decimeters
    x = (radius * np.cos(t)).astype(np.float32)
    y = (radius * np.sin(t)).astype(np.float32)
    dx = np.diff(x, prepend=x[-1])
    dy = np.diff(y, prepend=y[-1])
    dist = np.cumsum(np.sqrt(dx**2 + dy**2)).astype(np.float32)
    dist[0] = 0.0
    lap_distance = float(dist[-1]) / 10.0  # meters
    dist_m = (dist / 10.0).astype(np.float32)
    return TrackGeometry(
        x=x,
        y=y,
        distance=dist_m,
        lap_distance=lap_distance,
        marshal_sectors=[
            MarshalSector(number=1, start_distance=0.0, end_distance=lap_distance / 3),
            MarshalSector(
                number=2, start_distance=lap_distance / 3, end_distance=2 * lap_distance / 3
            ),
            MarshalSector(number=3, start_distance=2 * lap_distance / 3, end_distance=lap_distance),
        ],
    )


@pytest.fixture
def sample_circuit_data(sample_track_geometry):
    """CircuitData with track + pit lane."""
    return CircuitData(
        track=sample_track_geometry,
        pit_lane=None,
        circuit_length=sample_track_geometry.lap_distance,
        corners=[Corner(number=1, distance=50.0, angle=90.0, letter="")],
        rotation=0.0,
        name="Test Circuit",
    )


@pytest.fixture
def sample_session_metadata():
    """SessionMetadata with 3 drivers."""
    return SessionMetadata(
        session_type="R",
        year=2024,
        round_number=8,
        event_name="Monaco Grand Prix",
        drivers=["VER", "NOR", "LEC"],
        driver_numbers={"VER": 1, "NOR": 4, "LEC": 16},
        driver_names={"VER": "Max Verstappen", "NOR": "Lando Norris", "LEC": "Charles Leclerc"},
        driver_teams={"VER": "Red Bull Racing", "NOR": "McLaren", "LEC": "Ferrari"},
        driver_colors={"VER": "#3671C6", "NOR": "#FF8000", "LEC": "#E8002D"},
        team_colors={"Red Bull Racing": "#3671C6", "McLaren": "#FF8000", "Ferrari": "#E8002D"},
        track_length=3337.0,
        total_laps=78,
        t0=T0Info(utc="2024-05-26T13:00:00", lights_out_offset=3335.0),
    )


@pytest.fixture
def sample_telemetry():
    """Dict of 3 driver Polars DataFrames (10 rows each)."""
    drivers = ["VER", "NOR", "LEC"]
    telemetry = {}
    for i, drv in enumerate(drivers):
        telemetry[drv] = pl.DataFrame(
            {
                "session_time": np.linspace(0, 100, 10).tolist(),
                "x": np.random.default_rng(i).uniform(-1000, 1000, 10).tolist(),
                "y": np.random.default_rng(i + 10).uniform(-1000, 1000, 10).tolist(),
                "speed": np.random.default_rng(i + 20).uniform(50, 350, 10).tolist(),
                "lap_number": [1] * 5 + [2] * 5,
                "track_distance": np.linspace(0, 3337, 10).tolist(),
                "race_distance": np.linspace(0, 6674, 10).tolist(),
                "compound": ["SOFT"] * 10,
                "tyre_life": list(range(1, 11)),
                "status": ["Racing"] * 10,
                "position": [i + 1] * 10,
                "interval": [float(i)] * 10,
            }
        )
    return telemetry


@pytest.fixture
def sample_session_data(sample_session_metadata, sample_telemetry):
    """Complete SessionData."""
    return SessionData(
        metadata=sample_session_metadata,
        telemetry=sample_telemetry,
        events=EventsData(),
        results=ResultsData(),
    )


@pytest.fixture
def sample_weekend(sample_event_info, sample_circuit_data):
    """F1Weekend for API tests."""
    return F1Weekend(event=sample_event_info, circuit=sample_circuit_data)
