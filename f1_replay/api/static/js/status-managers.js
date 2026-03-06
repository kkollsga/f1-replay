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

