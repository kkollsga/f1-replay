# Utils: Utility Functions

## Time Conversion

```python
from fastf1 import utils

utils.to_timedelta(string)
```
Convert string time to timedelta.
- Input: '1:23.456' format
- Returns: timedelta object

```python
utils.to_lap_time(value)
```
Convert value to lap time string.

## Distance Conversion

```python
utils.to_distance(meters)
```
Convert meters to appropriate distance unit.

## Data Types

### SessionTime vs DateTime

- **SessionTime** (timedelta): Time elapsed from session start
  - `00:05:30.123` - 5 minutes, 30 seconds into session

- **DateTime** (Timestamp): Absolute wall-clock time
  - `2024-07-07 15:30:45` - Real clock time

```python
# SessionTime columns
session.laps['Time']  # timedelta
session.telemetry['Time']  # timedelta

# DateTime columns
session.laps['DatetimeUTC']  # Timestamp
schedule['EventDate']  # Timestamp
```

## Value Validation

```python
utils.is_distance(value)
```
Check if value is distance-like.

```python
utils.is_timedelta(value)
```
Check if value is timedelta.

## Data Cleaning

```python
# Telemetry automatically handles NaN values
# Use pandas methods for custom cleaning

import pandas as pd

tel = lap.get_telemetry()
tel_clean = tel.dropna()
tel_fill = tel.fillna(method='ffill')
```

## Driver & Team Info

```python
from fastf1 import plotting

plotting.list_driver_names()  # Get all F1 drivers
plotting.list_team_names()   # Get all F1 teams
```

