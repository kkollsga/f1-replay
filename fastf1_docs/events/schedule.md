# Events: Schedule & Event Info

## Event Schedule

### Load Schedule

```python
import fastf1

schedule = fastf1.get_event_schedule(year)
```
Get all events for a season.
- `year` (int): Season year
- Returns: **EventSchedule** DataFrame

### Schedule Columns

| Column | Type | Description |
|--------|------|-------------|
| `RoundNumber` | int | Race round |
| `Country` | str | Country name |
| `Location` | str | City/venue |
| `OfficialEventName` | str | Official name |
| `EventDate` | datetime | Event date |
| `Session1` | str | Session name (usually FP1) |
| `Session1Date` | datetime | Session 1 start time |
| `Session2` | str | Session name (usually FP2) |
| `Session2Date` | datetime | Session 2 start time |
| `Session3` | str | Session name (usually FP3 or Q) |
| `Session3Date` | datetime | Session 3 start time |
| `Session4` | str | Session name (usually Q or S) |
| `Session4Date` | datetime | Session 4 start time |
| `Session5` | str | Session name (usually S or R) |
| `Session5Date` | datetime | Session 5 start time |

### Usage

```python
schedule = fastf1.get_event_schedule(2024)

# Access specific event
silverstone = schedule[schedule['Location'] == 'Silverstone']

# Get upcoming races
remaining = fastf1.get_events_remaining(2024)

# Iterate events
for idx, event in schedule.iterrows():
    print(f"{event['RoundNumber']}: {event['OfficialEventName']}")
```

## Event Object

### Load Event

```python
event = fastf1.get_event(year, gp)
```
Get event with basic info (doesn't load session data).
- `year` (int): Season year
- `gp` (str/int): Grand Prix name or round number

### Event Properties

| Property | Type | Description |
|----------|------|-------------|
| `name` | str | Official event name |
| `country` | str | Country name |
| `location` | str | City/location |
| `date` | datetime | Event date |
| `weekend` | dict | Session dates/times |

