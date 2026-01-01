# Multi-Session Type Support Plan

## Overview

Add support for switching between session types (Race, Sprint, Qualifying, Practice) in the F1 replay app. Sprint races are the immediate priority as they share the same data structure as Race.

---

## Phase 1: Sprint Support (Backend)

Sprint uses identical data structure to Race - minimal changes needed.

### 1.1 Verify Sprint Data Loading
- [ ] Test `DataLoader.load_session(year, round, "Sprint")` works correctly
- [ ] Verify telemetry, events, order data is populated
- [ ] Test with 2024 Sprint weekends (China, Miami, Austria, USA, Brazil, Qatar)

### 1.2 Add Weekend-Level Session Preloading (Optional)
- [ ] Add `DataLoader.load_weekend_sessions(year, round, sessions=None)` method
  - If `sessions=None`, load all available sessions for the weekend
  - If `sessions=["R", "S"]`, load only specified sessions
- [ ] Return dict: `{session_type: SessionData}`

### 1.3 Update API Endpoints
- [ ] Verify `/api/session/<year>/<round>/<session_type>` handles Sprint correctly
- [ ] Add endpoint to get available sessions: `/api/weekend/<year>/<round>/sessions`
  - Returns: `["FP1", "FP2", "FP3", "Q", "S", "R"]` or `["FP1", "FP2", "Q", "S", "R"]` for sprint weekends

---

## Phase 2: Sprint Support (Frontend)

### 2.1 Session Tabs UI
- [ ] Add tab bar above track canvas: `Race | Sprint` (or just `Race` if no sprint)
- [ ] Read `available_sessions` from weekend metadata to determine which tabs to show
- [ ] Style active tab distinctly

### 2.2 Session Switching Logic
- [ ] On tab click, fetch new session data from API
- [ ] Show loading indicator during fetch
- [ ] Reset playback state (time to 0, pause playback)
- [ ] Re-render track with new telemetry data
- [ ] Update driver standings, messages, etc.

### 2.3 URL State
- [ ] Update URL param when switching: `?year=2024&round=5&session=S`
- [ ] Read session from URL on page load (default to "R" if not specified)

---

## Phase 3: Qualifying Support (Backend)

Qualifying has different data requirements than Race/Sprint.

### 3.1 Define Qualifying Data Model
```python
@dataclass
class QualifyingPhase:
    phase: str                    # "Q1", "Q2", "Q3"
    start_time: float             # session_time when phase started
    end_time: float               # session_time when phase ended
    duration: float               # seconds
    eliminated: List[str]         # drivers eliminated (Q1/Q2 only)
    best_laps: Dict[str, LapInfo] # best lap per driver in this phase

@dataclass
class QualifyingData:
    metadata: SessionMetadata
    telemetry: Dict[str, pl.DataFrame]  # same as Race
    events: EventsData                   # same as Race
    phases: List[QualifyingPhase]        # Q1, Q2, Q3 breakdown
    grid: List[GridPosition]             # final qualifying order
```

### 3.2 Qualifying Session Processor
- [ ] Create `QualifyingProcessor` or extend `SessionProcessor`
- [ ] Parse race_control_messages to detect Q1/Q2/Q3 phase boundaries
- [ ] Extract best lap per driver per phase
- [ ] Identify eliminated drivers per phase
- [ ] Build final grid order

### 3.3 API Response
- [ ] Return qualifying-specific fields in `/api/session/.../Q` response
- [ ] Include phase timing for countdown display

---

## Phase 4: Qualifying Support (Frontend)

### 4.1 Qualifying-Specific UI
- [ ] Phase indicator: show current phase (Q1/Q2/Q3) based on session_time
- [ ] Countdown timer: show remaining time in current phase
- [ ] Knockout indicator: show eliminated drivers after Q1/Q2
- [ ] Best lap display: show best lap time per driver (not position tracking)

### 4.2 Playback Differences
- [ ] No continuous position tracking (drivers in pits most of the time)
- [ ] Focus on lap times rather than gaps
- [ ] Highlight when personal/overall best laps are set

---

## Phase 5: Practice Support (Backend)

Practice sessions are open-ended with focus on lap times and stint analysis.

### 5.1 Define Practice Data Model
```python
@dataclass
class PracticeData:
    metadata: SessionMetadata
    telemetry: Dict[str, pl.DataFrame]
    events: EventsData
    lap_times: pl.DataFrame       # all laps with times, compounds
    session_best: List[BestLap]   # leaderboard by best lap time
```

### 5.2 Practice Session Processor
- [ ] Simpler than Qualifying - no phases
- [ ] Track all lap times with compounds
- [ ] Build session leaderboard by best lap

---

## Phase 6: Practice Support (Frontend)

### 6.1 Practice-Specific UI
- [ ] Leaderboard by best lap time (not race position)
- [ ] Stint/run tracking display
- [ ] No countdown timer (open session)

---

## Implementation Order

1. **Sprint (Phase 1-2)** - Lowest effort, same data model as Race
2. **Qualifying (Phase 3-4)** - Different UI needs, phase-based timing
3. **Practice (Phase 5-6)** - Simplest data but different visualization

---

## Data Model Summary

| Session Type | Position Tracking | Phases | Countdown | Primary Metric |
|--------------|------------------|--------|-----------|----------------|
| Race         | Yes (continuous) | No     | No        | Gap to leader  |
| Sprint       | Yes (continuous) | No     | No        | Gap to leader  |
| Qualifying   | No               | Q1/Q2/Q3 | Yes     | Best lap time  |
| Practice     | No               | No     | No        | Best lap time  |

---

## Files to Modify

**Backend:**
- `data_loader/dataloader.py` - Add `load_weekend_sessions()`
- `data_loader/session_processor.py` - Add qualifying/practice logic or new processors
- `data_loader/data_models.py` - Add `QualifyingPhase`, `QualifyingData` if needed
- `api/app.py` - Add `/api/weekend/.../sessions` endpoint

**Frontend:**
- `api/templates/index.html` - Add session tabs, qualifying/practice UI modes
