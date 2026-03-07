class TrackStatus {
    constructor() {
        this.redFlag = false;
        this.safetyCar = false;
        this.vsc = false;
        this.blueFlag = false;
        this.sectorStatuses = new Map();  // Map<sectorNumber, statusType>
        this.lastLoggedEventIndex = -1;
    }

    setRedFlag(value) {
        if (this.redFlag === value) return false;
        this.redFlag = value;
        return true;
    }

    setSafetyCar(value) {
        if (this.safetyCar === value) return false;
        this.safetyCar = value;
        return true;
    }

    setVSC(value) {
        if (this.vsc === value) return false;
        this.vsc = value;
        return true;
    }

    setBlueFlag(value) {
        if (this.blueFlag === value) return false;
        this.blueFlag = value;
        return true;
    }

    setSectorStatus(sectorNum, statusType) {
        const existing = this.sectorStatuses.get(sectorNum);
        if (existing === statusType) return false;
        this.sectorStatuses.set(sectorNum, statusType);
        return true;
    }

    clearSectorStatus(sectorNum) {
        if (!this.sectorStatuses.has(sectorNum)) return false;
        this.sectorStatuses.delete(sectorNum);
        return true;
    }

    clearAll() {
        const changed = this.redFlag || this.safetyCar || this.vsc || this.blueFlag || this.sectorStatuses.size > 0;
        this.redFlag = false;
        this.safetyCar = false;
        this.vsc = false;
        this.blueFlag = false;
        this.sectorStatuses.clear();
        return changed;
    }

    getGlobalStatus() {
        if (this.redFlag) return 'RED';
        if (this.safetyCar) return 'SC';
        if (this.vsc) return 'VSC';
        if (this.blueFlag) return 'BLUE';
        if (this.sectorStatuses.size > 0) return 'YELLOW';
        return 'CLEAR';
    }

    getSectorList() {
        return Array.from(this.sectorStatuses.keys()).sort((a, b) => a - b).join(', ');
    }

    logStatusChange(eventTime, message) {
        const sectorList = this.getSectorList();
        const status = this.getGlobalStatus();

        let logMsg = `[STATUS ${eventTime.toFixed(1)}s] ${message}`;
        if (status === 'RED') {
            logMsg += ' → RED FLAG';
        } else if (status === 'BLUE') {
            logMsg += ' → BLUE FLAG';
        } else if (status === 'YELLOW' && sectorList) {
            logMsg += ` → YELLOW sectors: ${sectorList}`;
        } else if (status === 'YELLOW') {
            logMsg += ' → YELLOW FLAG';
        } else {
            logMsg += ' → CLEAR';
        }
        // Debug logging disabled for cleaner console
        // console.log(logMsg);
    }
}

// Race Control Message Manager - Single Source of Truth for Race Control Events
class RaceControl {
    constructor() {
        this.messages = [];  // Array of {time, message, element, timeoutId}
        this.lastLoggedEventIndex = -1;
        this.messagesContainer = null;
    }

    setContainer(containerEl) {
        this.messagesContainer = containerEl;
    }

    addMessage(time, message, status = null) {
        // Create message element
        const msgEl = document.createElement('div');
        msgEl.className = 'race-message';

        // Apply color class based on status parameter if provided
        if (status) {
            const s = status.toUpperCase();
            if (s === 'RED') {
                msgEl.classList.add('redflag');
            } else if (s === 'SAFETYCAR' || s === 'SC' || s === 'SCENDING') {
                msgEl.classList.add('safetycar');
            } else if (s === 'VSC' || s === 'VSCENDING') {
                msgEl.classList.add('vsc');
            } else if (s === 'YELLOW' || s === 'DOUBLEYELLOW') {
                msgEl.classList.add('yellow');
            } else if (s === 'BLUE') {
                msgEl.classList.add('blue');
            } else if (s === 'RAIN') {
                msgEl.classList.add('rain');
            } else if (s === 'ALLCLEAR' || s === 'GREEN' || s === 'CLEAR') {
                msgEl.classList.add('allclear');
            }
        } else {
            // Fallback: determine styling based on message content
            const text = (message || '').toUpperCase();
            if (text.includes('RED')) {
                msgEl.classList.add('redflag');
            } else if (text.includes('YELLOW')) {
                msgEl.classList.add('yellow');
            } else if (text.includes('SAFETY') && !text.includes('VIRTUAL')) {
                msgEl.classList.add('safetycar');
            } else if (text.includes('VIRTUAL')) {
                msgEl.classList.add('vsc');
            } else if (text.includes('RAIN')) {
                msgEl.classList.add('rain');
            } else if (text.includes('BLUE')) {
                msgEl.classList.add('blue');
            }
        }

        msgEl.innerHTML = `
            <div style="font-size: 0.8em; color: #aaa;">${this.formatTime(time)}</div>
            <div style="font-size: 0.9em;">${message}</div>
        `;

        // Add to beginning so newest messages appear at top
        if (this.messagesContainer) {
            this.messagesContainer.insertBefore(msgEl, this.messagesContainer.firstChild);
        }

        // Setup auto-removal
        const fadeOutTime = 4500;
        const removeTime = 5000;

        const fadeoutTimeout = setTimeout(() => {
            msgEl.style.opacity = '0';
            msgEl.style.transform = 'translateX(20px)';
        }, fadeOutTime);

        const removeTimeout = setTimeout(() => {
            msgEl.remove();
            // Remove from tracking array
            this.messages = this.messages.filter(m => m.element !== msgEl);
        }, removeTime);

        // Track message
        const messageObj = { time, message, element: msgEl, timeoutId: removeTimeout };
        this.messages.push(messageObj);

        // Limit to max 6 visible messages
        const allMessages = this.messagesContainer?.querySelectorAll('.race-message') || [];
        if (allMessages.length > 6) {
            allMessages[allMessages.length - 1].remove();
        }

        return messageObj;
    }

    displayStatusMessage(time, message, status = null) {
        // Display status message without logging (logging is handled by TrackStatus)
        return this.addMessage(time, message, status);
    }

    logMessage(time, message) {
        // Debug logging disabled for cleaner console
        // console.log(`[RACE CONTROL ${time.toFixed(1)}s] ${message}`);
    }

    getCurrentMessages() {
        return this.messages.map(m => ({ time: m.time, message: m.message }));
    }

    formatTime(sec) {
        const mins = Math.floor(sec / 60);
        const secs = Math.floor(sec % 60);
        return `${mins}:${secs.toString().padStart(2, '0')}`;
    }
}

// Starting Lights Manager - Handles race start lights sequence
class StartingLightsManager {
    constructor(lightsOutTime, settings = STARTING_LIGHTS_SETTINGS) {
        this.settings = settings;
        this.lightsOutTime = lightsOutTime;
        this.randomDelay = null;
        this.timings = null;
    }

    // Called once per session load - generates random delay
    initialize() {
        const s = this.settings;
        this.randomDelay = s.randomDelayMin +
            Math.random() * (s.randomDelayMax - s.randomDelayMin);
        this.calculateTimings();
    }

    // Pre-calculate all timing thresholds (working backwards from lightsOut)
    calculateTimings() {
        const s = this.settings;
        const lightsOut = this.lightsOutTime;

        // Work backwards from lights out
        const light5On = lightsOut - this.randomDelay;
        const light4On = light5On - s.lightInterval;
        const light3On = light4On - s.lightInterval;
        const light2On = light3On - s.lightInterval;
        const light1On = light2On - s.lightInterval;
        const appear = light1On - s.appearDelay;

        this.timings = {
            appear,      // Lights box appears
            light1On,    // First light turns red
            light2On,
            light3On,
            light4On,
            light5On,    // Fifth light turns red
            lightsOut    // All lights go off
        };
    }

    // Returns state for given time: { visible, activeLights, isLightsOut }
    getStateAtTime(currentTime) {
        if (!this.timings || !this.settings.enabled) {
            return { visible: false, activeLights: 0, isLightsOut: false };
        }

        const t = this.timings;

        if (currentTime < t.appear || currentTime >= t.lightsOut) {
            return { visible: false, activeLights: 0, isLightsOut: currentTime >= t.lightsOut };
        }

        let activeLights = 0;
        if (currentTime >= t.light1On) activeLights = 1;
        if (currentTime >= t.light2On) activeLights = 2;
        if (currentTime >= t.light3On) activeLights = 3;
        if (currentTime >= t.light4On) activeLights = 4;
        if (currentTime >= t.light5On) activeLights = 5;

        return { visible: true, activeLights, isLightsOut: false };
    }
}

// Qualifying Manager - Handles Q1/Q2/Q3 phases, countdown, leaderboard, elimination
class QualifyingManager {
    constructor(raceControlEvents, trackStatusEvents, drivers, lightsOutTime) {
        this.raceControlEvents = raceControlEvents || [];
        this.trackStatusEvents = trackStatusEvents || [];
        this.drivers = drivers || [];
        this.lightsOutTime = lightsOutTime || 0;
        this.phases = [];           // [{name, start, chequered, end, duration}]
        this.driverLapTimes = null; // set via setTelemetryData
        this.eliminatedAfterQ1 = new Set();
        this.eliminatedAfterQ2 = new Set();
        this._phaseResultsCache = {};  // {phaseName: [{driver, time}]}
        this.detectPhases();
    }

    detectPhases() {
        const cfg = QUALIFYING_SETTINGS;
        const phaseNames = ['Q1', 'Q2', 'Q3'];
        const pattern = cfg.chequeredPattern;

        // Find "FIRST CAR TO TAKE THE FLAG" messages
        const chequeredTimes = this.raceControlEvents
            .filter(e => pattern.test(e.message))
            .map(e => e.session_time)
            .sort((a, b) => a - b);

        if (chequeredTimes.length >= 3) {
            // Build phases from detected chequered times
            // Q1: starts at lightsOutTime, chequered at first flag
            this.phases = phaseNames.map((name, i) => ({
                name,
                start: null, // refined later
                chequered: chequeredTimes[i],
                end: null,   // refined later
                duration: cfg[name].duration,
            }));
            this.phases[0].start = this.lightsOutTime;
        } else {
            // Fallback: use standard durations from lights out
            let t = this.lightsOutTime;
            this.phases = phaseNames.map(name => {
                const dur = cfg[name].duration;
                const phase = { name, start: t, chequered: t + dur, end: t + dur + 30, duration: dur };
                t = phase.end + 5 * 60; // assume 5 min gap
                return phase;
            });
        }
    }

    setTelemetryData(driverLapTimes) {
        this.driverLapTimes = driverLapTimes;
        this._refinePhaseTimings();
    }

    _refinePhaseTimings() {
        if (!this.driverLapTimes || this.phases.length === 0) return;

        // Collect all lap end times across all drivers
        const allLapEnds = [];
        for (const code in this.driverLapTimes) {
            for (const [lap, data] of Object.entries(this.driverLapTimes[code])) {
                allLapEnds.push(data.endTime);
            }
        }
        allLapEnds.sort((a, b) => a - b);

        for (let i = 0; i < this.phases.length; i++) {
            const phase = this.phases[i];

            // Set phase end: latest lap completion within ~90s after chequered
            const postChequeredLaps = allLapEnds.filter(
                t => t > phase.chequered && t < phase.chequered + 90
            );
            phase.end = postChequeredLaps.length > 0
                ? Math.max(...postChequeredLaps) + 1
                : phase.chequered + 30;

            // Set Q2/Q3 start: first telemetry activity after previous phase end
            if (i > 0) {
                const prevEnd = this.phases[i - 1].end;
                const nextActivity = allLapEnds.find(t => t > prevEnd + 60);
                // Start is roughly one lap duration before first lap completion
                phase.start = nextActivity
                    ? nextActivity - phase.duration / (phase.duration / 90)
                    : prevEnd + 5 * 60;
                // Simpler: go back ~100s (out-lap) from first lap end after gap
                if (nextActivity) {
                    phase.start = Math.max(prevEnd + 30, nextActivity - 120);
                }
            }
        }
    }

    getCurrentPhase(time) {
        for (const phase of this.phases) {
            if (time >= phase.start && time <= phase.end) return phase;
        }
        return null;
    }

    getCountdown(time) {
        const phase = this.getCurrentPhase(time);
        if (!phase) return 0;
        const elapsed = time - phase.start;
        return phase.duration - elapsed;
    }

    isChequered(time) {
        const phase = this.getCurrentPhase(time);
        if (!phase) return false;
        return time >= phase.chequered;
    }

    isIntermission(time) {
        // Before Q1 starts or between phases
        if (time < this.phases[0]?.start) return true;
        return this.getCurrentPhase(time) === null;
    }

    getPhaseLabel(time) {
        const phase = this.getCurrentPhase(time);
        if (phase) return phase.name;
        // Between phases
        for (let i = 0; i < this.phases.length - 1; i++) {
            if (time > this.phases[i].end && time < this.phases[i + 1].start) {
                return `${this.phases[i].name} \u2192 ${this.phases[i + 1].name}`;
            }
        }
        if (time > this.phases[this.phases.length - 1]?.end) return 'Q3';
        return 'Q1';
    }

    getBestLapsInPhase(phaseName, currentTime) {
        if (!this.driverLapTimes) return [];
        const phase = this.phases.find(p => p.name === phaseName);
        if (!phase) return [];

        const cfg = QUALIFYING_SETTINGS;
        const results = [];

        // Collect best lap per driver in this phase
        for (const driver of this.drivers) {
            const laps = this.driverLapTimes[driver.code];
            if (!laps) continue;
            let best = Infinity;
            for (const [lap, data] of Object.entries(laps)) {
                // Lap must end within phase window and before current time
                if (data.endTime >= phase.start && data.endTime <= Math.min(currentTime, phase.end)) {
                    if (data.duration < best) best = data.duration;
                }
            }
            if (best < Infinity) {
                results.push({ driver: driver.code, time: best });
            }
        }

        if (results.length === 0) return results;

        // Filter out-laps: laps > fastest * maxValidLapFactor
        const fastest = Math.min(...results.map(r => r.time));
        const threshold = fastest * cfg.maxValidLapFactor;
        const valid = results.filter(r => r.time <= threshold);

        // Sort by time
        valid.sort((a, b) => a.time - b.time);

        // Add delta
        const poleTime = valid.length > 0 ? valid[0].time : 0;
        return valid.map((r, i) => ({
            ...r,
            delta: r.time - poleTime,
            position: i + 1,
        }));
    }

    // Compute eliminations based on final phase standings
    computeEliminations(currentTime) {
        const cfg = QUALIFYING_SETTINGS;

        // Q1 elimination
        if (this.phases.length > 0 && currentTime > this.phases[0].end && this.eliminatedAfterQ1.size === 0) {
            const q1Final = this._getFinalPhaseStandings('Q1');
            const cutoff = cfg.Q1.eliminateFrom;
            if (cutoff > 0) {
                // Drivers from position cutoff onwards are eliminated
                for (let i = cutoff - 1; i < q1Final.length; i++) {
                    this.eliminatedAfterQ1.add(q1Final[i].driver);
                }
                // Also add drivers with no time in Q1
                const q1Drivers = new Set(q1Final.map(r => r.driver));
                for (const d of this.drivers) {
                    if (!q1Drivers.has(d.code)) this.eliminatedAfterQ1.add(d.code);
                }
            }
        }

        // Q2 elimination
        if (this.phases.length > 1 && currentTime > this.phases[1].end && this.eliminatedAfterQ2.size === 0) {
            const q2Final = this._getFinalPhaseStandings('Q2');
            const cutoff = cfg.Q2.eliminateFrom;
            if (cutoff > 0) {
                // Of non-Q1-eliminated drivers, those from cutoff onwards are eliminated
                const activeInQ2 = q2Final.filter(r => !this.eliminatedAfterQ1.has(r.driver));
                for (let i = cutoff - 1; i < activeInQ2.length; i++) {
                    this.eliminatedAfterQ2.add(activeInQ2[i].driver);
                }
                // Drivers active in Q2 but with no time
                const q2Drivers = new Set(activeInQ2.map(r => r.driver));
                for (const d of this.drivers) {
                    if (!this.eliminatedAfterQ1.has(d.code) && !q2Drivers.has(d.code)) {
                        this.eliminatedAfterQ2.add(d.code);
                    }
                }
            }
        }
    }

    _getFinalPhaseStandings(phaseName) {
        if (this._phaseResultsCache[phaseName]) return this._phaseResultsCache[phaseName];
        const phase = this.phases.find(p => p.name === phaseName);
        if (!phase) return [];
        const results = this.getBestLapsInPhase(phaseName, phase.end);
        this._phaseResultsCache[phaseName] = results;
        return results;
    }

    getEliminatedDrivers(currentTime) {
        this.computeEliminations(currentTime);
        const eliminated = new Set(this.eliminatedAfterQ1);
        for (const d of this.eliminatedAfterQ2) eliminated.add(d);
        return eliminated;
    }

    getEliminationPhase(driverCode) {
        if (this.eliminatedAfterQ1.has(driverCode)) return 'Q1';
        if (this.eliminatedAfterQ2.has(driverCode)) return 'Q2';
        return null;
    }
}

