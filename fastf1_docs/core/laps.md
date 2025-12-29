# Core: Laps & Lap Data

## Laps Collection

**Laps** is a pandas DataFrame with filtering methods for lap data.

### Filtering Methods

```python
laps.pick_driver(driver)
```
Select laps by driver number or abbreviation.

```python
laps.pick_fastest()
```
Get fastest lap in collection.

```python
laps.pick_lap(lap_number)
```
Get specific lap by number.

```python
laps.pick_companies(compounds)
```
Filter by tire compound (soft, medium, hard, inter, wet).

### Key Columns

| Column | Type | Description |
|--------|------|-------------|
| `LapNumber` | int | Lap count |
| `Driver` | str | Driver abbreviation |
| `DriverNumber` | int | Driver number |
| `LapTime` | timedelta | Lap duration |
| `Sector1Time` | timedelta | Sector 1 duration |
| `Sector2Time` | timedelta | Sector 2 duration |
| `Sector3Time` | timedelta | Sector 3 duration |
| `Compound` | str | Tire compound (soft/medium/hard) |
| `TyreLife` | int | Laps on current tire |
| `FreshTire` | bool | Fresh tire |
| `Team` | str | Driver team |
| `IsAccurate` | bool | Data quality flag |

### Usage

```python
session = fastf1.get_session(2024, 'Silverstone', 'R')

# Get driver's laps
ver_laps = session.laps.pick_driver('VER')

# Filter by compound
soft_laps = session.laps.pick_compounds('soft')

# Get fastest lap
fastest = session.laps.pick_fastest()
print(f"Fastest: {fastest['Driver']} - {fastest['LapTime']}")
```

## Lap Object

Single lap with data access and telemetry.

### Methods

```python
lap.get_telemetry()
```
Get telemetry for this lap.

```python
lap.get_car_data()
```
Get car data (position, speed) for lap.

```python
lap.get_weather_data()
```
Get weather conditions during lap.

### Access Telemetry

```python
fastest_lap = session.laps.pick_fastest()
telemetry = fastest_lap.get_telemetry()
```

