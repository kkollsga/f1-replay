# Ergast: Historical Data API

## Overview

Access historical F1 data via the Ergast API (1950-present).

## Load Data

```python
from fastf1.ergast import Ergast

# Get driver standings for a season
ergast = Ergast()
standings = ergast.driver_standings(season=2024)
```

## Main Endpoints

### Driver Standings

```python
ergast.driver_standings(season, round=None)
```
Get driver championship standings.
- `season` (int): Year
- `round` (int, optional): Specific round
- Returns: DataFrame with standings

### Constructor Standings

```python
ergast.constructor_standings(season, round=None)
```
Get team/constructor standings.

### Race Results

```python
ergast.race_results(season, round=None)
```
Get race results and finishing positions.

### Driver Info

```python
ergast.drivers()
```
Get all F1 drivers with info.

```python
ergast.drivers(surname='Verstappen')
```
Search drivers by name.

## Response Format

Results are returned as pandas DataFrames with columns like:
- `driverId`, `surname`, `forename`, `nationality`
- `points`, `position`, `wins`
- `constructorId`, `name`
- `date`, `raceId`, `raceName`

## Rate Limiting

⚠️ **Note**: Ergast API has rate limiting. Caching is recommended.

```python
# FastF1 handles caching automatically
# Cache location: ~/.fastf1/cache/ (default)
```

## Example: Get Historical Stats

```python
from fastf1.ergast import Ergast

ergast = Ergast()

# Get 2023 driver standings
standings_2023 = ergast.driver_standings(season=2023)
print(standings_2023[['surname', 'points', 'position']])

# Get specific race
race_2024_spa = ergast.race_results(season=2024, round=14)
```

## Limitations

- Historical data only (no live session data)
- Smaller dataset than session telemetry
- Useful for championship analysis and statistics

