# FastF1 API Quick Reference

**FastF1** - Python library for F1 data access and analysis

## Quick Start

```python
import fastf1
from fastf1 import utils

# Load session data
session = fastf1.get_session(2024, 'Silverstone', 'R')
laps = session.laps
telemetry = session.telemetry

# Get schedule
schedule = fastf1.get_event_schedule(2024)
```

## Modules

| Module | Purpose |
|--------|---------|
| [**core**](core/) | Sessions, laps, telemetry, results |
| [**events**](events/) | Event schedules and event info |
| [**plotting**](plotting/) | Colors, styles, legends |
| [**ergast**](ergast/) | Historical F1 data API |
| [**utils**](utils/) | Utility functions |

## Main Functions

- `get_session(year, gp, session)` - Load session data
- `get_testing_session(year, test_num)` - Load test session
- `get_event_schedule(year)` - Get full calendar
- `get_event(year, gp)` - Get specific event info

## Key Classes

- **Session** - Main data container with laps, telemetry, results
- **Laps** - DataFrame-like lap collection with filtering
- **Lap** - Single lap with data and telemetry
- **Telemetry** - Positional and car data

## Documentation Links

- Official: https://docs.fastf1.dev/
- GitHub: https://github.com/theOehrly/Fast-F1
