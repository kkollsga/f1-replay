# FastF1 Common Tasks & Examples

## Load Race Data

```python
import fastf1
from fastf1 import utils, plotting

session = fastf1.get_session(2024, 'Silverstone', 'R')
session.load()

# Or with specific settings
session = fastf1.get_session(
    year=2024,
    gp='Silverstone',  # or round number 10
    session='R',       # Race (or FP1, FP2, FP3, Q, S)
    with_telemetry=True
)
```

## Get Driver's Laps & Fastest Lap

```python
# Get specific driver's laps
ver_laps = session.laps[session.laps['Driver'] == 'VER']
# or
ver_laps = session.laps.pick_driver('VER')

# Get fastest lap overall
fastest = session.laps.pick_fastest()
print(f"Fastest: {fastest['Driver']} - {fastest['LapTime']}")

# Get driver's fastest lap
ver_fastest = ver_laps.pick_fastest()
print(f"VER fastest: {ver_fastest['LapTime']}")
```

## Analyze Lap Data

```python
lap = session.laps.iloc[0]

# Lap info
print(lap['LapNumber'])     # Lap count
print(lap['LapTime'])       # Total lap time
print(lap['Sector1Time'])   # Sector 1
print(lap['Sector2Time'])   # Sector 2
print(lap['Sector3Time'])   # Sector 3
print(lap['Compound'])      # Tire (soft/medium/hard)
print(lap['TyreLife'])      # Laps on tires
print(lap['Team'])          # Team name
```

## Get Telemetry

```python
# Full session telemetry (slow!)
session.load(telemetry=True)
session_tel = session.telemetry

# Specific driver
ver_laps = session.laps.pick_driver('VER')
ver_tel = ver_laps.get_telemetry()

# Single lap
fastest_lap = session.laps.pick_fastest()
fastest_tel = fastest_lap.get_telemetry()

# Time range
tel_slice = session_tel.slice_by_time('00:05:00', '00:06:00')

# By distance
tel_slice = session_tel.slice_by_distance(100, 200)
```

## Compare Two Drivers

```python
ver_laps = session.laps.pick_driver('VER')
ham_laps = session.laps.pick_driver('HAM')

ver_fastest = ver_laps.pick_fastest()['LapTime']
ham_fastest = ham_laps.pick_fastest()['LapTime']

delta = abs(ver_fastest - ham_fastest)
print(f"Delta: {delta.total_seconds():.3f}s")
```

## Check Results

```python
# Session results/standings
results = session.results

# Key columns
results[['Abbreviation', 'Points', 'Position', 'GridPosition']]

# Specific driver
ver_result = results[results['Abbreviation'] == 'VER']
print(ver_result[['Position', 'Points', 'Time']])
```

## Get Schedule

```python
schedule = fastf1.get_event_schedule(2024)

# View events
print(schedule[['RoundNumber', 'Country', 'Location', 'EventDate']])

# Get remaining races
remaining = fastf1.get_events_remaining(2024)

# Find specific race
silverstone = schedule[schedule['Location'] == 'Silverstone']
```

## Use Driver/Team Colors

```python
from fastf1 import plotting

plotting.setup_mpl()

# Get colors
ver_color = plotting.get_driver_color('VER')
rb_color = plotting.get_team_color('Red Bull Racing')
soft_color = plotting.get_compound_color('soft')

# Get abbreviations
ver_abbr = plotting.get_driver_abbreviation('1')

# List all
all_teams = plotting.list_team_names()
all_drivers = plotting.list_driver_names()
```

## Tire Strategy Analysis

```python
# Get stints by compound
soft_laps = session.laps[session.laps['Compound'] == 'soft']
med_laps = session.laps[session.laps['Compound'] == 'medium']

# Count stints
soft_stint_count = soft_laps.groupby('Driver').size()

# Check tire life
laps_sorted = session.laps.sort_values(['Driver', 'LapNumber'])
latest_tires = laps_sorted.groupby('Driver').tail(1)
print(latest_tires[['Driver', 'Compound', 'TyreLife']])
```

## Error Handling

```python
try:
    session = fastf1.get_session(2024, 'Silverstone', 'R')
    session.load()
except Exception as e:
    print(f"Error loading session: {e}")
    # Handle missing data, network errors, etc.
```

