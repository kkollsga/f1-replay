# Telemetry Reference

## Overview

Each driver's telemetry is stored as a [Polars](https://pola.rs/) DataFrame in `session.telemetry["VER"]`. Telemetry is built from two FastF1 data sources:

- **pos_data** -- Car positions at ~4.5Hz (session_time, x, y, z, status)
- **car_data** -- ECU telemetry (speed, throttle, brake, rpm, gear, DRS)

These are merged, enriched with lap info and velocity vectors, then projected onto the track geometry to produce the final DataFrame. See [Processing Pipeline](#processing-pipeline) below.

## Column Reference

| Column | Polars Type | Unit | Description |
|--------|-------------|------|-------------|
| `session_time` | Float64 | seconds | Time since session t0 (timing zero) |
| `x` | Float32 | decimeters | Track X coordinate |
| `y` | Float32 | decimeters | Track Y coordinate |
| `z` | Float32 | decimeters | Elevation above reference |
| `speed` | Float32 | km/h | Car speed |
| `rpm` | Float32 | RPM | Engine RPM |
| `n_gear` | Int8 | -- | Gear number (0 = neutral, 1-8) |
| `throttle` | Float32 | % | Throttle position (0-100) |
| `brake` | Float32 | -- | Brake application (0-100) |
| `drs` | Int8 | -- | DRS status code |
| `lap_number` | Int32 | -- | Current lap (0 = before race start) |
| `compound` | Utf8 | -- | Tyre compound: SOFT, MEDIUM, HARD, INTERMEDIATE, WET |
| `tyre_life` | Int32 | laps | Laps driven on current tyre set |
| `track_distance` | Float32 | meters | Position along track (0 to `lap_distance`) |
| `race_distance` | Float32 | meters | Total cumulative distance covered |
| `position` | Int32 | -- | Current race position (1-20) |
| `interval` | Float64 | seconds | Time gap to race leader |
| `status` | Utf8 | -- | Driver status (see [Status Values](#driver-status-values)) |
| `vx` | Float32 | dm/s | X velocity vector (for interpolation) |
| `vy` | Float32 | dm/s | Y velocity vector (for interpolation) |

Not all columns are present in every session. Practice and qualifying sessions may lack `position`, `interval`, and `race_distance`.

## Processing Pipeline

Raw FastF1 data goes through 8 steps in `TelemetryBuilder` and `SessionProcessor`:

### 1. Position Compaction

Raw pos_data contains ~4.5Hz samples. When a car is stationary (e.g., on the grid, in the pit box), consecutive samples with <1 decimeter movement are compacted to a single sample. This typically reduces data size by 15-30% without losing information.

### 2. Car Data Sampling

ECU telemetry (speed, throttle, brake, etc.) arrives at different timestamps than position data. Each position timestamp is matched to the nearest car_data timestamp via nearest-neighbor lookup, aligning all data to a single timeline.

### 3. Lap Info Assignment

Lap numbers are assigned by matching `session_time` against FastF1's laps DataFrame. The boundary is the **lap completion time** (when the car crosses the finish line). Before the first crossing, `lap_number = 0`. Tyre `compound` and `tyre_life` are extracted from FastF1's lap metadata. Pit in/out windows are identified from `PitInTime`/`PitOutTime` fields.

### 4. Velocity Vector Computation

`vx` and `vy` are computed via central finite differences on (x, y, session_time), then smoothed with bidirectional exponential moving average (window ~2 samples). Values are:
- **Clamped** to +/-1000 dm/s (~360 km/h) to suppress noise spikes
- **Zeroed** across large time gaps (>5 seconds, e.g., pit stops) to prevent extrapolation artifacts

### 5. Track Distance Projection

Each car position (x, y) is projected **perpendicular** onto the weekend's `TrackGeometry` to compute `track_distance` in meters. For datasets >1000 points, a KD-tree spatial index accelerates the projection. The result wraps from `lap_distance` back to 0 at the start/finish line.

### 6. Race Distance

```
race_distance = track_distance + (lap_number - 1) * lap_distance
```

This produces a monotonically increasing measure of total distance covered. A warning is logged if non-monotonic values are detected (can happen at track geometry boundaries). Race distance is **frozen** when a driver finishes or retires.

### 7. Status Assignment

Each telemetry sample is assigned one of the [driver status values](#driver-status-values) based on:
- **Events timing**: Formation lap start (WarmUp), lights out (Racing)
- **Pit windows**: PitInTime/PitOutTime from FastF1 laps
- **Race results**: Finished flag, DNF/retirement status
- **Priority**: DNF > Finished > Pit > Racing > WarmUp > PreSession

### 8. Position & Interval Tracking

`OrderBuilder` ranks all drivers by `race_distance` at each timestamp:
- **Position 1** = greatest race_distance (excluding lapped cars with finished status)
- **Interval** for P1 = 0.0 seconds
- **Interval** for others = time gap to leader, computed by interpolating when the leader was at the same race_distance
- Drivers with null race_distance get null position/interval

## Hermite Interpolation

The frontend interpolates between telemetry samples (~0.22s apart) using **cubic Hermite splines** for smooth car movement:

At each sample point `(t, x, y)`, the tangent vector is `(vx, vy) * dt` where `dt` is the time step to the next sample. This produces smooth curves that follow the actual racing line through corners, avoiding the "corner cutting" that linear interpolation would produce.

Velocity vectors are zeroed at pit stop gaps, so cars smoothly decelerate to a stop rather than jumping to the pit box.

## Driver Status Values

| Status | Meaning |
|--------|---------|
| `PreSession` | Before session timing starts |
| `WarmUp` | Formation lap / warm-up lap |
| `Racing` | On track under racing conditions |
| `Pit` | In pit lane (between PitInTime and PitOutTime) |
| `Finished` | Crossed the finish line (race_distance frozen) |
| `DNF` | Did not finish / retired (race_distance frozen) |

## Track Status Events

Track status events are consolidated from FastF1's track_status and race_control_messages into intervals with start/end times:

| Status | Scope | Description |
|--------|-------|-------------|
| `AllClear` | Track | Green flag, normal racing conditions |
| `Yellow` | Sector | Local yellow in a specific marshal sector |
| `DoubleYellow` | Sector | Double waved yellow, extreme caution |
| `SafetyCar` | Track | Full safety car deployed |
| `VSC` | Track | Virtual safety car active |
| `VSCEnding` | Track | VSC ending, prepare for green |
| `Red` | Track | Red flag, session stopped |
| `FormationLap` | Track | Cars on formation lap before start |

Sector-scoped statuses include a `sector` number matching the circuit's marshal sectors.

## Serialization for the Frontend

When telemetry is served via `/api/session/`, it goes through `serialize_telemetry()`:

**Default fields** (14 columns): `session_time`, `lap_number`, `x`, `y`, `track_distance`, `race_distance`, `position`, `interval`, `status`, `compound`, `tyre_life`, `speed`, `vx`, `vy`

**Custom fields**: Pass `?telemetry_fields=session_time,x,y,speed` to the API endpoint.

**Float rounding** (to reduce JSON payload size):

| Field | Precision | Example |
|-------|-----------|---------|
| `session_time` | 0.01s | `123.45` |
| `x`, `y` | 0.1 dm | `1234.5` |
| `track_distance`, `race_distance` | 0.1 m | `3456.7` |
| `interval` | 0.001s | `1.234` |
| `speed` | 0.1 km/h | `305.2` |
| `vx`, `vy` | 0.1 dm/s | `45.3` |

**Special values**: `NaN` and `Inf` are converted to `null` in JSON output.

**Wire format**: Column-oriented — `{"VER": {"session_time": [0.0, 0.22, ...], "x": [1234.5, ...]}}` rather than row-oriented, for efficient parsing and smaller payload.
