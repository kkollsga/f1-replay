class F1RaceViewer {
    constructor() {
        // Apply settings as CSS variables
        this.applySettings();

        this.canvas = document.getElementById('trackCanvas');
        this.ctx = this.canvas.getContext('2d');
        this.setupCanvas();

        // State
        this.isPlaying = false;
        this.playSpeed = 1;
        this.currentTime = 0;
        this.minTime = 0;
        this.maxTime = 0;
        this.lightsOutTime = 0;

        // Data
        this.weekendData = null;
        this.sessionData = null;
        this.trackData = null;
        this.pitLaneData = null;
        this.drivers = [];

        // Tier loading state (for independent error handling)
        this.hasTrackData = false;      // Tier 2 loaded successfully
        this.hasSessionData = false;    // Tier 3 loaded successfully
        this.tier2Error = null;         // Tier 2 error message
        this.tier3Error = null;         // Tier 3 error message
        this.telemetryIndexCache = {};  // Cache last index for each driver
        this.previousPositions = null;  // Cache positions for comparison
        this.previousChaseMode = null;  // Track previous chase mode for styling updates

        // Track rendering
        this.trackColor = '#FFFFFF';
        this.baseTrackColor = '#FFFFFF';  // Base color before pulsing
        this.trackPulsing = false;        // Whether track should pulse (SC/VSC ending)
        this.bounds = null;
        this.scale = 1;
        this.offsetX = 0;
        this.offsetY = 0;
        this.rotation = 0;
        this.trackStatus = new TrackStatus();  // State manager for track flags
        this.raceControl = new RaceControl();  // State manager for race control messages
        this.startingLights = null;  // Initialized in initializeSession()
        this._currentSubtitle = null;  // Track current subtitle to avoid unnecessary DOM updates

        // Rain animation system
        this.rainDrops = [];
        this.rainActive = false;
        this.rainCanvas = null;
        this.rainCtx = null;

        // Zoom and pan state (overview mode)
        this.baseScale = 1;               // Scale to fit track in canvas (100% reference)
        this.userZoom = 1.0;              // User zoom multiplier (1.0 = 100%)
        this.panX = 0;                    // Pan offset in track space
        this.panY = 0;
        this.isDraggingPan = false;       // Pan drag state
        this.dragStartX = 0;
        this.dragStartY = 0;
        this.dragStartPanX = 0;
        this.dragStartPanY = 0;
        this.zoomIndicatorTimeout = null; // For auto-hiding zoom indicator

        // Message tracking
        this.displayedMessageIds = new Set();
        this.displayedEventPills = new Set();
        this.trackStatusEvents = [];
        this.raceControlEvents = [];
        this.lastMessageIndexTrackStatus = 0;  // Cache last processed index
        this.lastMessageIndexRaceControl = 0;  // Cache last processed index
        this.lastLoggedTrackStatusIndex = -1;  // Track last logged track status event

        // Active event states
        this.activeEvents = {
            redFlag: false,
            safetyCar: false,
            vsc: false,
            rain: false
        };

        // Time tracking for messages
        this.previousTime = -Infinity;
        this.lastProcessedStatusTime = -1;  // Track time for scrub detection
        this.scrubDebounceTimer = null;     // Debounce timer for scrub updates

        // Selector state
        this.seasonsData = null;
        this.currentYear = YEAR;
        this.currentRound = ROUND;
        this.selectedYear = YEAR;
        this.selectedRound = ROUND;
        this.isLoading = false;

        // Cache for total laps calculation
        this.cachedTotalLaps = null;

        // Progress bar state
        this.isDraggingKnob = false;

        // Blue flag tracking (set of driver numbers with active blue flags)
        this.blueFlagDrivers = new Set();

        // Fastest lap tracking
        this.currentFastestLapDriver = null;  // Driver code with fastest lap
        this.lastProcessedFastestLapIndex = -1;  // Track which fastest lap events we've already processed

        // Chase mode state (null = overview mode, driver code = chasing that driver)
        this.chaseMode = null;
        this.currentZoom = 1.0;  // Zoom level in chase mode (1.0 = 100%, fits track)

        // Strategy data (populated in initializeSession)
        this.driverStints = {};
        this.pitStops = [];
        this.driverLapTimes = {};
        this.showStrategyTab = false;
        this.strategyView = false;
        this.lapChartVisible = false;
        this._lastLapChartUpdate = 0;

        // Standings display mode: 'time' or 'tire'
        // Scrolling: deterministic by lap position (2 laps time, 0.5 lap tire cycle)
        // Fast playback (5x+): lap-based cycling
        // Normal playback: time-based (90s time, 20s tire)
        this.standingsMode = 'time';
        this.standingsModeLastSwitch = 0;  // Real timestamp of last mode switch
        this.standingsModeLastLap = 0;     // Leader lap at last mode switch

        // Initialize
        this.setupEventListeners();
        this.initRainSystem();
        this.loadSeasons();
        this.loadData();

        // Animation loop
        this.lastFrameTime = Date.now();
        requestAnimationFrame(() => this.animate());
    }

    setupCanvas() {
        const dpr = window.devicePixelRatio || 1;
        // Reset inline styles so canvas can resize with container
        this.canvas.style.width = '';
        this.canvas.style.height = '';
        // Get the container dimensions
        const container = this.canvas.parentElement;
        const rect = container.getBoundingClientRect();
        this.canvas.width = rect.width * dpr;
        this.canvas.height = rect.height * dpr;
        this.ctx.scale(dpr, dpr);
        // Recalculate base scale for new canvas size
        this.calculateBaseScale();
    }

    calculateBaseScale() {
        if (!this.trackData) return;

        const width = this.canvas.width / (window.devicePixelRatio || 1);
        const height = this.canvas.height / (window.devicePixelRatio || 1);

        // Calculate raw bounds
        let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
        for (let i = 0; i < this.trackData.x.length; i++) {
            minX = Math.min(minX, this.trackData.x[i]);
            maxX = Math.max(maxX, this.trackData.x[i]);
            minY = Math.min(minY, this.trackData.y[i]);
            maxY = Math.max(maxY, this.trackData.y[i]);
        }

        if (this.pitLaneData) {
            for (let i = 0; i < this.pitLaneData.x.length; i++) {
                minX = Math.min(minX, this.pitLaneData.x[i]);
                maxX = Math.max(maxX, this.pitLaneData.x[i]);
                minY = Math.min(minY, this.pitLaneData.y[i]);
                maxY = Math.max(maxY, this.pitLaneData.y[i]);
            }
        }

        // Cache track center for rotation
        this.trackCenterX = (minX + maxX) / 2;
        this.trackCenterY = (minY + maxY) / 2;

        // Calculate rotated bounds
        const rotRad = this.rotation;
        const cos = Math.cos(rotRad);
        const sin = Math.sin(rotRad);

        let rotMinX = Infinity, rotMaxX = -Infinity, rotMinY = Infinity, rotMaxY = -Infinity;
        for (let i = 0; i < this.trackData.x.length; i++) {
            const dx = this.trackData.x[i] - this.trackCenterX;
            const dy = this.trackData.y[i] - this.trackCenterY;
            const rotX = dx * cos - dy * sin + this.trackCenterX;
            const rotY = dx * sin + dy * cos + this.trackCenterY;
            rotMinX = Math.min(rotMinX, rotX);
            rotMaxX = Math.max(rotMaxX, rotX);
            rotMinY = Math.min(rotMinY, rotY);
            rotMaxY = Math.max(rotMaxY, rotY);
        }

        // Cache rotated bounds
        this.rotBounds = {
            minX: rotMinX, maxX: rotMaxX, minY: rotMinY, maxY: rotMaxY,
            width: rotMaxX - rotMinX,
            height: rotMaxY - rotMinY,
            centerX: (rotMinX + rotMaxX) / 2,
            centerY: (rotMinY + rotMaxY) / 2
        };

        // Calculate base scale (100% zoom = track fits in canvas)
        const padding = 40;
        const availWidth = width - padding * 2;
        const availHeight = height - padding * 2;
        const scaleX = availWidth / this.rotBounds.width;
        const scaleY = availHeight / this.rotBounds.height;
        this.baseScale = Math.min(scaleX, scaleY);
    }

    // Convert screen coordinates to track coordinates
    screenToTrack(screenX, screenY) {
        const rotRad = this.rotation;
        const cos = Math.cos(-rotRad); // Inverse rotation
        const sin = Math.sin(-rotRad);

        // Reverse the screen transform
        const rotX = (screenX - this.offsetX) / this.scale;
        const rotY = -(screenY - this.offsetY) / this.scale;

        // Reverse the rotation
        const dx = rotX - this.trackCenterX;
        const dy = rotY - this.trackCenterY;
        const trackX = dx * cos - dy * sin + this.trackCenterX;
        const trackY = dx * sin + dy * cos + this.trackCenterY;

        return { x: trackX, y: trackY };
    }

    handleWheel(e) {
        e.preventDefault();
        if (!this.trackData || !this.rotBounds) return;

        const rect = this.canvas.getBoundingClientRect();
        const mouseX = e.clientX - rect.left;
        const mouseY = e.clientY - rect.top;

        // Zoom factor: scroll up = zoom in, scroll down = zoom out
        const zoomFactor = e.deltaY > 0 ? 0.9 : 1.1;

        if (this.chaseMode) {
            // Chase mode: zoom centered on chased car
            const newZoom = Math.max(1.0, Math.min(10.0, this.currentZoom * zoomFactor));
            this.currentZoom = newZoom;
        } else {
            // Overview mode: zoom centered on cursor
            const oldZoom = this.userZoom;
            const newZoom = Math.max(1.0, Math.min(10.0, oldZoom * zoomFactor));

            if (newZoom !== oldZoom) {
                // Get track position under cursor before zoom
                const trackPos = this.screenToTrack(mouseX, mouseY);

                // Apply new zoom
                this.userZoom = newZoom;
                this.scale = this.baseScale * this.userZoom;

                // Calculate where that track position would be on screen after zoom
                const rotRad = this.rotation;
                const cos = Math.cos(rotRad);
                const sin = Math.sin(rotRad);
                const dx = trackPos.x - this.trackCenterX;
                const dy = trackPos.y - this.trackCenterY;
                const rotX = dx * cos - dy * sin + this.trackCenterX;
                const rotY = dx * sin + dy * cos + this.trackCenterY;

                // Adjust pan so cursor stays over the same track position
                const width = this.canvas.width / (window.devicePixelRatio || 1);
                const height = this.canvas.height / (window.devicePixelRatio || 1);
                const centerCanvasX = width / 2;
                const centerCanvasY = height / 2;

                // New offset needed to keep track point under cursor
                const newOffsetX = mouseX - rotX * this.scale;
                const newOffsetY = mouseY + rotY * this.scale;

                // Convert to pan offset
                this.panX = this.rotBounds.centerX - (centerCanvasX - newOffsetX) / this.scale;
                this.panY = (newOffsetY - centerCanvasY) / this.scale - this.rotBounds.centerY;

                // Constrain pan
                this.constrainPan();
            }
        }

        this.showZoomIndicator();

        // Update cursor based on zoom state
        if (!this.chaseMode && !this.isDraggingPan) {
            this.canvas.style.cursor = this.userZoom > 1.0 ? 'grab' : 'default';
        }
    }

    handlePanStart(e) {
        // Only pan in overview mode and with left mouse button
        if (this.chaseMode || e.button !== 0) return;
        if (!this.trackData || this.userZoom <= 1.0) return;

        this.isDraggingPan = true;
        this.dragStartX = e.clientX;
        this.dragStartY = e.clientY;
        this.dragStartPanX = this.panX;
        this.dragStartPanY = this.panY;
        this.canvas.style.cursor = 'grabbing';
        e.preventDefault();
    }

    handlePanMove(e) {
        if (!this.isDraggingPan) return;

        const dx = e.clientX - this.dragStartX;
        const dy = e.clientY - this.dragStartY;

        // Convert screen delta to track space (drag down = pan up, like scrolling)
        this.panX = this.dragStartPanX + dx / this.scale;
        this.panY = this.dragStartPanY + dy / this.scale;

        this.constrainPan();
    }

    handlePanEnd() {
        if (this.isDraggingPan) {
            this.isDraggingPan = false;
            this.canvas.style.cursor = this.userZoom > 1.0 ? 'grab' : 'default';
        }
    }

    constrainPan() {
        if (!this.rotBounds || this.userZoom <= 1.0) {
            this.panX = 0;
            this.panY = 0;
            return;
        }

        // Allow panning to center any point on the track
        // Max pan = half the track dimension (from center to edge)
        const maxPanX = this.rotBounds.width / 2;
        const maxPanY = this.rotBounds.height / 2;

        this.panX = Math.max(-maxPanX, Math.min(maxPanX, this.panX));
        this.panY = Math.max(-maxPanY, Math.min(maxPanY, this.panY));
    }

    showZoomIndicator() {
        const indicator = document.getElementById('zoomIndicator');
        if (!indicator) return;

        const zoom = this.chaseMode ? this.currentZoom : this.userZoom;
        indicator.textContent = Math.round(zoom * 100) + '%';
        indicator.classList.add('visible');

        // Clear existing timeout
        if (this.zoomIndicatorTimeout) {
            clearTimeout(this.zoomIndicatorTimeout);
        }

        // Hide after 1 second
        this.zoomIndicatorTimeout = setTimeout(() => {
            indicator.classList.remove('visible');
        }, 1000);
    }

    resetZoomPan() {
        this.userZoom = 1.0;
        this.panX = 0;
        this.panY = 0;
        this.currentZoom = 1.0;
        this.canvas.style.cursor = 'default';
    }

    applySettings() {
        // Apply settings as CSS variables to the standings card
        const root = document.documentElement;

        // Font sizes
        root.style.setProperty('--position-size', STANDINGS_SETTINGS.positionSize);
        root.style.setProperty('--driver-name-size', STANDINGS_SETTINGS.driverNameSize);
        root.style.setProperty('--driver-number-size', STANDINGS_SETTINGS.driverNumberSize);
        root.style.setProperty('--time-size', STANDINGS_SETTINGS.timeSize);

        // Color bar
        root.style.setProperty('--driver-color-width', STANDINGS_SETTINGS.driverColorWidth);
        root.style.setProperty('--driver-color-height', STANDINGS_SETTINGS.driverColorHeight);

        // Margins
        root.style.setProperty('--driver-position-margin', STANDINGS_SETTINGS.driverPositionMargin);
        root.style.setProperty('--driver-color-margin', STANDINGS_SETTINGS.driverColorMargin);
        root.style.setProperty('--driver-color-margin-right', STANDINGS_SETTINGS.driverColorMarginRight);
        root.style.setProperty('--driver-name-margin', STANDINGS_SETTINGS.driverNameMargin);
        root.style.setProperty('--driver-number-margin', STANDINGS_SETTINGS.driverNumberMargin);
    }

    // Debounce utility for resize handler
    debounce(func, wait) {
        let timeout;
        return (...args) => {
            clearTimeout(timeout);
            timeout = setTimeout(() => func.apply(this, args), wait);
        };
    }

    setupEventListeners() {
        document.getElementById('playPauseBtn').addEventListener('click', () => this.togglePlayPause());
        document.getElementById('speedSelector').addEventListener('click', (e) => this.handleSpeedChange(e));

        // Close speed dropdown when clicking outside
        document.addEventListener('click', (e) => {
            const speedSelector = document.getElementById('speedSelector');
            if (!speedSelector.contains(e.target)) {
                speedSelector.querySelector('.speed-dropdown').classList.remove('open');
            }
        });

        // Resize handler for smooth scaling
        const handleResize = () => {
            this.setupCanvas();
            this.resizeRainCanvas();
            this.render();
        };
        window.addEventListener('resize', handleResize);

        // Also handle orientation change for mobile devices
        window.addEventListener('orientationchange', () => {
            setTimeout(() => {
                this.setupCanvas();
                this.resizeRainCanvas();
                this.render();
            }, 200);
        });

        // Mouse wheel zoom
        this.canvas.addEventListener('wheel', (e) => this.handleWheel(e), { passive: false });

        // Pan with mouse drag (overview mode only)
        this.canvas.addEventListener('mousedown', (e) => this.handlePanStart(e));
        document.addEventListener('mousemove', (e) => this.handlePanMove(e));
        document.addEventListener('mouseup', () => this.handlePanEnd());

        // Mobile panel toggle buttons
        const sidebar = document.getElementById('sidebar');
        const messageCenter = document.getElementById('messageCenter');
        const toggleStandings = document.getElementById('toggleStandings');
        const toggleMessages = document.getElementById('toggleMessages');

        if (toggleStandings && toggleMessages) {
            toggleStandings.addEventListener('click', () => {
                sidebar.classList.toggle('visible');
                messageCenter.classList.remove('visible');
                toggleStandings.classList.toggle('active');
                toggleMessages.classList.remove('active');
                // Re-render after panel animation
                setTimeout(() => {
                    this.setupCanvas();
                    this.render();
                }, 350);
            });

            toggleMessages.addEventListener('click', () => {
                messageCenter.classList.toggle('visible');
                sidebar.classList.remove('visible');
                toggleMessages.classList.toggle('active');
                toggleStandings.classList.remove('active');
                // Re-render after panel animation
                setTimeout(() => {
                    this.setupCanvas();
                    this.render();
                }, 350);
            });

            // Close panels when clicking on canvas (mobile)
            this.canvas.addEventListener('click', (e) => {
                if (window.innerWidth <= 1100) {
                    if (sidebar.classList.contains('visible') || messageCenter.classList.contains('visible')) {
                        sidebar.classList.remove('visible');
                        messageCenter.classList.remove('visible');
                        toggleStandings.classList.remove('active');
                        toggleMessages.classList.remove('active');
                        e.stopPropagation();
                    }
                }
            });
        }

        // Progress bar events
        const knob = document.getElementById('raceProgressKnob');
        const track = document.getElementById('raceProgressTrack');

        knob.addEventListener('mousedown', (e) => this.startKnobDrag(e));
        document.addEventListener('mousemove', (e) => this.handleKnobDrag(e));
        document.addEventListener('mouseup', () => this.endKnobDrag());

        // Click on track to seek
        track.addEventListener('click', (e) => this.seekToClick(e));

        // Selector events
        document.getElementById('yearSelector').addEventListener('change', () => this.onYearChanged());
        document.getElementById('eventSelector').addEventListener('change', () => this.onEventChanged());
        document.getElementById('cancelBtn').addEventListener('click', () => this.onCancel());
        document.getElementById('loadBtn').addEventListener('click', () => this.onLoad());

        // Follow mode events
        document.getElementById('prevDriverBtn').addEventListener('click', () => this.switchDriver(-1));
        document.getElementById('nextDriverBtn').addEventListener('click', () => this.switchDriver(1));
        document.getElementById('closeChaseBtn').addEventListener('click', () => this.exitFollowMode());

        // Sidebar tab toggle (Standings / Strategy)
        document.getElementById('sidebarTabToggle').addEventListener('click', (e) => {
            const btn = e.target.closest('.sidebar-tab-btn');
            if (!btn) return;
            const tab = btn.dataset.tab;
            this.switchSidebarTab(tab);
        });

        // Lap chart close button
        document.getElementById('lapChartClose').addEventListener('click', () => this.toggleLapChart(false));

        // Data export buttons
        document.getElementById('exportCsvBtn').addEventListener('click', () => this.exportData('csv'));
        document.getElementById('exportJsonBtn').addEventListener('click', () => this.exportData('json'));

        // Keyboard shortcuts
        const SPEEDS = [0.25, 0.5, 1, 2, 5, 10, 20, 50];
        document.addEventListener('keydown', (e) => {
            // Ignore when typing in inputs
            if (e.target.tagName === 'INPUT' || e.target.tagName === 'SELECT' || e.target.tagName === 'TEXTAREA') return;

            const seekAmount = e.shiftKey ? 60 : 10;

            switch (e.key) {
                case ' ':
                    e.preventDefault();
                    this.togglePlayPause();
                    break;
                case 'ArrowLeft':
                    e.preventDefault();
                    this.currentTime = Math.max(this.minTime, this.currentTime - seekAmount);
                    this.updateProgressBar();
                    this.rebuildTrackStatusSilently();
                    break;
                case 'ArrowRight':
                    e.preventDefault();
                    this.currentTime = Math.min(this.maxTime, this.currentTime + seekAmount);
                    this.updateProgressBar();
                    this.rebuildTrackStatusSilently();
                    break;
                case '+':
                case '=': {
                    e.preventDefault();
                    const curIdx = SPEEDS.indexOf(this.playSpeed);
                    const nextIdx = Math.min(SPEEDS.length - 1, (curIdx >= 0 ? curIdx : 2) + 1);
                    this.setSpeed(SPEEDS[nextIdx]);
                    break;
                }
                case '-': {
                    e.preventDefault();
                    const curIdx = SPEEDS.indexOf(this.playSpeed);
                    const nextIdx = Math.max(0, (curIdx >= 0 ? curIdx : 2) - 1);
                    this.setSpeed(SPEEDS[nextIdx]);
                    break;
                }
                case 'c':
                case 'C':
                    if (this.chaseMode) {
                        this.exitFollowMode();
                    }
                    break;
                case 'Escape':
                    if (this.chaseMode) {
                        this.exitFollowMode();
                    }
                    break;
                case 'l':
                case 'L':
                    this.toggleLapChart();
                    break;
                case 's':
                case 'S':
                    if (this.showStrategyTab) {
                        this.switchSidebarTab(this.strategyView ? 'standings' : 'strategy');
                    }
                    break;
            }
        });
    }

    async loadSeasons() {
        try {
            const resp = await fetch('/api/seasons');
            this.seasonsData = await resp.json();
            console.log('TIER 1 data received:', this.seasonsData);
            this.populateSelectors();
        } catch (e) {
            console.error('TIER 1 error:', e);
        }
    }

    populateSelectors() {
        if (!this.seasonsData) return;

        const seasons = this.seasonsData.seasons;
        const yearSelect = document.getElementById('yearSelector');
        const eventSelect = document.getElementById('eventSelector');

        // Populate years
        yearSelect.innerHTML = '';
        Object.keys(seasons).sort().reverse().forEach(year => {
            const option = document.createElement('option');
            option.value = year;
            option.textContent = year;
            if (parseInt(year) === this.currentYear) {
                option.selected = true;
            }
            yearSelect.appendChild(option);
        });

        // Populate events for current year
        this.updateEventSelector();
    }

    updateEventSelector() {
        if (!this.seasonsData) return;

        const seasons = this.seasonsData.seasons;
        const yearSelect = document.getElementById('yearSelector');
        const eventSelect = document.getElementById('eventSelector');
        const selectedYear = parseInt(yearSelect.value);

        eventSelect.innerHTML = '';
        const year = seasons[selectedYear];
        if (year && year.rounds) {
            year.rounds.forEach(round => {
                const option = document.createElement('option');
                option.value = round.round_number;
                option.textContent = round.name;
                if (round.round_number === this.selectedRound) {
                    option.selected = true;
                }
                eventSelect.appendChild(option);
            });
        }
    }

    onYearChanged() {
        const yearSelect = document.getElementById('yearSelector');
        this.selectedYear = parseInt(yearSelect.value);
        this.updateEventSelector();
        this.updateActionButtons();
    }

    onEventChanged() {
        const eventSelect = document.getElementById('eventSelector');
        this.selectedRound = parseInt(eventSelect.value);
        this.updateActionButtons();
    }

    updateActionButtons() {
        const hasChanges = this.selectedYear !== this.currentYear || this.selectedRound !== this.currentRound;
        const actionsDiv = document.querySelector('.selector-controls-actions');
        if (hasChanges) {
            actionsDiv.classList.add('visible');
        } else {
            actionsDiv.classList.remove('visible');
        }
    }

    onCancel() {
        this.selectedYear = this.currentYear;
        this.selectedRound = this.currentRound;
        document.getElementById('yearSelector').value = this.currentYear;
        document.getElementById('eventSelector').value = this.currentRound;
        this.updateEventSelector();
        this.updateActionButtons();
    }

    async onLoad() {
        if (this.isLoading) return;
        this.isLoading = true;

        const loadingStatus = document.getElementById('loadingStatus');
        const yearSelect = document.getElementById('yearSelector');
        const eventSelect = document.getElementById('eventSelector');
        const actionsDiv = document.querySelector('.selector-controls-actions');
        const eventName = document.querySelector('#eventSelector option:checked').textContent;
        const year = this.selectedYear;

        // Hide selectors and action buttons, show loading message
        yearSelect.style.display = 'none';
        eventSelect.style.display = 'none';
        actionsDiv.style.display = 'none';
        loadingStatus.textContent = `Loading ${eventName} (${year})...`;
        loadingStatus.classList.add('visible');

        // Preload the new event data
        try {
            await Promise.all([
                fetch(`/api/weekend/${this.selectedYear}/${this.selectedRound}`),
                fetch(`/api/session/${this.selectedYear}/${this.selectedRound}/R`)
            ]);

            // Data loaded, refresh with new race
            const newUrl = `${window.location.pathname}?year=${this.selectedYear}&round=${this.selectedRound}`;
            window.location.href = newUrl;
        } catch (e) {
            console.error('Failed to load new event:', e);
            loadingStatus.classList.remove('visible');
            yearSelect.style.display = 'block';
            eventSelect.style.display = 'block';
            actionsDiv.style.display = 'flex';
            this.isLoading = false;
            this.updateActionButtons();
        }
    }

    // Tier 2: Load weekend/circuit data independently
    async loadWeekend() {
        try {
            const resp = await fetch(`/api/weekend/${YEAR}/${ROUND}`);
            if (!resp.ok) throw new Error(`API returned ${resp.status}`);
            this.weekendData = await resp.json();
            console.log('TIER 2 data received:', this.weekendData);
            this.initializeTrack();
            this.hasTrackData = true;
            this.renderSessionTabs();
            this.render();  // Show track immediately
        } catch (e) {
            console.error('TIER 2 error:', e.message);
            this.tier2Error = e.message;
            this.showTrackError();
        }
    }

    // Tier 3: Load session/telemetry data independently
    async loadSession() {
        try {
            const telemetryFields = ['session_time', 'lap_number', 'x', 'y', 'track_distance', 'race_distance', 'position', 'interval', 'status', 'compound', 'tyre_life', 'speed'];
            const resp = await fetch(`/api/session/${YEAR}/${ROUND}/${SESSION_TYPE}?telemetry_fields=${telemetryFields.join(',')}`);
            if (!resp.ok) throw new Error(`API returned ${resp.status}`);
            this.sessionData = await resp.json();
            console.log('TIER 3 data received:', this.sessionData);

            // Check if this is a future scheduled race
            if (this.sessionData.scheduled) {
                this.showScheduledMessage(this.sessionData);
                return;
            }

            this.initializeSession();
            this.hasSessionData = true;

            // Auto-play on session load
            this.isPlaying = true;
            this.updatePlayPauseButton();
            this.render();
        } catch (e) {
            console.error('TIER 3 error:', e.message);
            this.tier3Error = e.message;
            this.showSessionError();
        }
    }

    // Load both tiers in parallel but with independent error handling
    async loadData() {
        await Promise.all([
            this.loadWeekend(),
            this.loadSession()
        ]);
    }

    showScheduledMessage(scheduledData) {
        // Hide the canvas and show a scheduled message
        const canvas = document.getElementById('raceCanvas');
        canvas.style.display = 'none';

        // Hide controls
        const controls = document.querySelector('.controls');
        if (controls) controls.style.display = 'none';

        // Create scheduled message overlay
        const overlay = document.createElement('div');
        overlay.className = 'scheduled-overlay';
        overlay.innerHTML = `
            <div class="scheduled-content">
                <h1>🏁 ${scheduledData.name}</h1>
                <p class="scheduled-type">${scheduledData.session_type}</p>
                <p class="scheduled-date">${scheduledData.scheduled_date_formatted}</p>
                <p class="scheduled-message">${scheduledData.message}</p>
                <button onclick="window.history.back()" class="back-btn">← Back to race selection</button>
            </div>
        `;
        document.querySelector('.container').appendChild(overlay);

        // Add styles for the overlay
        const style = document.createElement('style');
        style.textContent = `
            .scheduled-overlay {
                position: fixed;
                top: 0;
                left: 0;
                right: 0;
                bottom: 0;
                display: flex;
                align-items: center;
                justify-content: center;
                background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
                z-index: 1000;
            }
            .scheduled-content {
                text-align: center;
                color: white;
                padding: 40px;
            }
            .scheduled-content h1 {
                font-size: 2.5em;
                margin-bottom: 20px;
            }
            .scheduled-type {
                font-size: 1.2em;
                color: #888;
                text-transform: uppercase;
                letter-spacing: 2px;
            }
            .scheduled-date {
                font-size: 2em;
                color: #e10600;
                margin: 20px 0;
                font-weight: bold;
            }
            .scheduled-message {
                font-size: 1.1em;
                color: #aaa;
                margin-bottom: 30px;
            }
            .back-btn {
                background: #e10600;
                color: white;
                border: none;
                padding: 12px 24px;
                font-size: 1em;
                border-radius: 5px;
                cursor: pointer;
            }
            .back-btn:hover {
                background: #ff1a1a;
            }
        `;
        document.head.appendChild(style);
    }

    // Display error when Tier 2 (track/weekend) fails to load
    showTrackError() {
        const width = this.canvas.width / (window.devicePixelRatio || 1);
        const height = this.canvas.height / (window.devicePixelRatio || 1);

        this.ctx.fillStyle = '#000';
        this.ctx.fillRect(0, 0, width, height);
        this.ctx.fillStyle = '#FF4444';
        this.ctx.font = 'bold 18px Arial';
        this.ctx.textAlign = 'center';
        this.ctx.textBaseline = 'middle';
        this.ctx.fillText('Failed to load track', width / 2, height / 2 - 10);
        this.ctx.font = '14px Arial';
        this.ctx.fillStyle = '#888';
        this.ctx.fillText(this.tier2Error || 'Unknown error', width / 2, height / 2 + 15);
    }

    // Display error when Tier 3 (session) fails to load - track still visible
    showSessionError() {
        // Update timer display to show error state
        const timerEl = document.getElementById('raceTimer');
        if (timerEl) {
            timerEl.textContent = '--:--:--';
            timerEl.style.opacity = '0.5';
        }

        // Disable play controls
        const playBtn = document.getElementById('playPauseBtn');
        if (playBtn) playBtn.disabled = true;

        // Show message in standings area
        const standings = document.getElementById('standings');
        if (standings) {
            standings.innerHTML = '<div style="padding: 20px; color: #888; text-align: center; font-size: 14px;">Session data unavailable</div>';
        }
    }

    // Tier 2 initialization: Track geometry only
    initializeTrack() {
        const track = this.weekendData.circuit.track;
        this.trackData = { x: track.x, y: track.y, distance: track.distance };

        if (this.weekendData.circuit.pit_lane) {
            this.pitLaneData = this.weekendData.circuit.pit_lane;
        }

        // Store track segments (marshal sectors with start/end distances)
        this.trackSegments = this.weekendData.circuit.track?.marshal_sectors || [];

        // Rotation (convert degrees to radians)
        const rotationDeg = this.weekendData.circuit.rotation || 0;
        this.rotation = rotationDeg * Math.PI / 180;
        console.log(`Track rotation: ${rotationDeg}° (${this.rotation.toFixed(3)} rad)`);

        // Pre-compute sector number for each track point (O(1) lookup during render)
        this.trackSectorMap = null;
        if (this.trackData.distance && this.trackSegments.length > 0) {
            this.trackSectorMap = new Array(this.trackData.x.length);
            for (let i = 0; i < this.trackData.x.length; i++) {
                this.trackSectorMap[i] = this.getSectorForDistance(this.trackData.distance[i]);
            }
        }

        // Reset zoom/pan and calculate base scale for new track
        this.resetZoomPan();
        this.calculateBaseScale();
    }

    // Get sector number for a given track distance (uses backend-provided boundaries)
    getSectorForDistance(distance) {
        if (!this.trackSegments || this.trackSegments.length === 0) {
            return null;
        }
        for (const seg of this.trackSegments) {
            // Handle wrap-around case (last sector wraps past lap distance)
            if (seg.end_distance > seg.start_distance) {
                if (distance >= seg.start_distance && distance < seg.end_distance) {
                    return seg.number;
                }
            } else {
                // Wrap-around: sector spans end of track to start
                if (distance >= seg.start_distance || distance < seg.end_distance) {
                    return seg.number;
                }
            }
        }
        return null;
    }

    // Tier 3 initialization: Session telemetry and events
    initializeSession() {
        if (!this.sessionData?.metadata) return;

        // Track status events (ensure they're arrays)
        this.trackStatusEvents = Array.isArray(this.sessionData.events?.track_status)
            ? this.sessionData.events.track_status
            : [];
        this.raceControlEvents = Array.isArray(this.sessionData.events?.race_control)
            ? this.sessionData.events.race_control
            : [];

        // Reset message processing indices
        this.lastMessageIndexTrackStatus = 0;
        this.lastMessageIndexRaceControl = 0;
        this.lastLoggedTrackStatusIndex = -1;
        this.displayedMessageIds.clear();
        this.cachedTotalLaps = null;  // Reset lap cache for new session
        this.blueFlagDrivers = new Set();  // Reset blue flags for new session
        this._currentSubtitle = null;  // Reset subtitle state for new session

        // Reset track status and race control message indices
        this.trackStatus.lastLoggedEventIndex = -1;
        this.raceControl.lastLoggedEventIndex = -1;
        this.lastProcessedStatusTime = -1;  // Will be set properly after first updateTrackStatus()

        // Setup RaceControl message container
        const messagesContainer = document.getElementById('raceMessages');
        this.raceControl.setContainer(messagesContainer);

        // Flash state for VSC
        this.flashState = false;
        this.flashInterval = null;

        // Max time from telemetry (use last element since arrays are sorted)
        let maxTime = 0;
        for (const driver in this.sessionData.telemetry) {
            const tel = this.sessionData.telemetry[driver];
            if (tel.session_time && tel.session_time.length > 0) {
                const lastTime = tel.session_time[tel.session_time.length - 1];
                if (lastTime > maxTime) maxTime = lastTime;
            }
        }
        this.maxTime = maxTime;

        // Start time: warmup lap start (formation lap) or 0
        const t0 = this.sessionData.metadata.t0;
        this.minTime = t0?.warmup_start_offset ?? 0;
        this.lightsOutTime = t0?.lights_out_offset ?? 0;
        this.currentTime = this.minTime;

        // Initialize starting lights (random delay generated once per session)
        this.startingLights = new StartingLightsManager(this.lightsOutTime);
        this.startingLights.initialize();

        // Initialize progress bar
        this.updateProgressBar();

        // Build drivers
        const dnfList = this.sessionData.metadata.dnf_drivers || [];
        const meta = this.sessionData.metadata;
        this.drivers = meta.drivers.map(code => {
            let color = meta.driver_colors?.[code] || '#CCCCCC';
            if (color && !color.startsWith('#')) {
                color = '#' + color;
            }
            const dnf = dnfList.includes(code);
            return {
                code,
                color,
                number: meta.driver_numbers?.[code] || 0,
                name: meta.driver_names?.[code] || code,
                telemetry: this.sessionData.telemetry[code] || { session_time: [] },
                dnf: dnf
            };
        });

        // Extract strategy data (stints, pit stops, lap times)
        this.extractStrategyData();

        this.initializeFastestLapOverlay();
        this.updateStandings();
        this.updateTrackStatus();

        // Show strategy/results tab based on session type
        const sessionType = this.sessionData.metadata.session_type;
        this.isQualifying = ['Q', 'SQ'].includes(sessionType);
        this.showStrategyTab = ['R', 'S'].includes(sessionType);
        this.strategyView = false;
        this.lapChartVisible = false;
        const tabToggle = document.getElementById('sidebarTabToggle');
        if (this.showStrategyTab) {
            tabToggle.style.display = 'flex';
        } else {
            tabToggle.style.display = 'none';
        }

        // Initialize qualifying manager
        if (this.isQualifying) {
            this.qualifyingManager = new QualifyingManager(
                this.raceControlEvents,
                this.trackStatusEvents,
                this.drivers,
                this.lightsOutTime
            );
            this.qualifyingManager.setTelemetryData(this.driverLapTimes);
        }

        // Render pit stop dots / phase markers on progress bar
        this.renderPitStopDots();
        if (this.isQualifying && this.qualifyingManager) {
            this.renderQualifyingPhaseMarkers();
        }
    }

    // Extract stints, pit stops, and lap times from telemetry (called once per session)
    extractStrategyData() {
        this.driverStints = {};
        this.pitStops = [];
        this.driverLapTimes = {};

        for (const driver of this.drivers) {
            const tel = driver.telemetry;
            if (!tel.session_time || tel.session_time.length === 0) continue;

            // Extract stints (compound changes)
            const stints = [];
            let currentCompound = null;
            let stintStartTime = null;
            let stintStartLap = null;

            for (let i = 0; i < tel.session_time.length; i++) {
                const compound = tel.compound ? tel.compound[i] : null;
                if (!compound) continue;
                const lap = tel.lap_number ? tel.lap_number[i] : 1;
                const time = tel.session_time[i];

                if (compound !== currentCompound) {
                    if (currentCompound !== null) {
                        stints.push({
                            compound: currentCompound,
                            startLap: stintStartLap,
                            endLap: lap - 1,
                            startTime: stintStartTime,
                            endTime: time
                        });
                    }
                    currentCompound = compound;
                    stintStartTime = time;
                    stintStartLap = lap;
                }
            }
            // Close final stint
            if (currentCompound !== null) {
                const lastIdx = tel.session_time.length - 1;
                stints.push({
                    compound: currentCompound,
                    startLap: stintStartLap,
                    endLap: tel.lap_number ? tel.lap_number[lastIdx] : 1,
                    startTime: stintStartTime,
                    endTime: tel.session_time[lastIdx]
                });
            }
            this.driverStints[driver.code] = stints;

            // Extract pit stops from stint boundaries
            for (let s = 1; s < stints.length; s++) {
                this.pitStops.push({
                    driver: driver.code,
                    color: driver.color,
                    lap: stints[s].startLap,
                    time: stints[s].startTime,
                    compoundFrom: stints[s - 1].compound,
                    compoundTo: stints[s].compound
                });
            }

            // Extract lap times
            const lapTimes = {};
            let lastLapStart = null;
            let currentLap = null;
            for (let i = 0; i < tel.session_time.length; i++) {
                const lap = tel.lap_number ? tel.lap_number[i] : null;
                if (lap === null) continue;
                const time = tel.session_time[i];
                if (lap !== currentLap) {
                    if (currentLap !== null && currentLap > 1 && lastLapStart !== null) {
                        lapTimes[currentLap] = { duration: time - lastLapStart, endTime: time };
                    }
                    currentLap = lap;
                    lastLapStart = time;
                }
            }
            this.driverLapTimes[driver.code] = lapTimes;
        }

        // Sort pit stops by time
        this.pitStops.sort((a, b) => a.time - b.time);
    }

    initializeFastestLapOverlay() {
        // Create indicator placeholders in the overlay for all drivers
        const overlay = document.getElementById('fastestLapIndicatorsOverlay');
        overlay.innerHTML = '';

        this.drivers.forEach(driver => {
            const indicator = document.createElement('div');
            indicator.className = 'fastest-lap-indicator-item';
            indicator.dataset.driver = driver.code;
            indicator.innerHTML = `
                <span class="fastest-lap-icon">⏱</span>
            `;
            overlay.appendChild(indicator);
        });
    }

    updateFastestLapIndicatorPositions() {
        // Update positions of indicators to match driver rows
        const standings = document.getElementById('standings');
        const driverRows = standings.querySelectorAll('.driver-row');
        const wrapper = document.querySelector('.standings-wrapper');
        if (!wrapper) return;

        const wrapperRect = wrapper.getBoundingClientRect();

        driverRows.forEach(row => {
            const driver = row.dataset.driver;
            const indicator = document.querySelector(`.fastest-lap-indicator-item[data-driver="${driver}"]`);

            if (indicator && row) {
                const rowRect = row.getBoundingClientRect();
                const rowTop = rowRect.top - wrapperRect.top;
                indicator.style.setProperty('--top-offset', rowTop + 'px');
                indicator.style.setProperty('--row-height', rowRect.height + 'px');
            }
        });
    }

    updateTrackStatus() {
        // Process track status events and update the TrackStatus state object
        if (!Array.isArray(this.trackStatusEvents)) {
            this.updateTrackColor();
            return;
        }

        // Always rebuild status from current time (handles blue flags, safety car, etc.)
        this.rebuildTrackStatusSilently();

        // Display new track status messages during forward playback
        this.displayTrackStatusMessages();

        this.lastProcessedStatusTime = this.currentTime;
    }

    // Update starting lights display based on current time
    updateStartingLights() {
        const state = this.startingLights?.getStateAtTime(this.currentTime);
        if (!state) return;

        const container = document.getElementById('startingLights');
        const notifications = document.getElementById('eventNotifications');

        if (state.visible) {
            container.style.visibility = 'visible';
            notifications.style.visibility = 'hidden';

            // Update each light SVG element
            const settings = this.startingLights.settings;
            for (let i = 1; i <= 5; i++) {
                const light = document.getElementById(`startLight${i}`);
                const isOn = i <= state.activeLights;
                light.setAttribute('fill', isOn ? settings.lightOnColor : settings.lightOffColor);
                light.style.filter = isOn
                    ? `drop-shadow(0 0 ${settings.lightGlowSize}px ${settings.lightGlowColor})`
                    : 'none';
            }
        } else {
            container.style.visibility = 'hidden';
            notifications.style.visibility = 'visible';
        }
    }

    // Display track status messages that have occurred since last update
    displayTrackStatusMessages() {
        // Skip message display when scrubbing or on first update (just set index)
        const isFirstUpdate = this.lastProcessedStatusTime < 0;
        const timeDelta = this.currentTime - this.lastProcessedStatusTime;
        const isScrubbing = timeDelta < 0 || timeDelta > 2;

        if (isFirstUpdate || isScrubbing) {
            // Just update index without displaying messages
            this.trackStatus.lastLoggedEventIndex = -1;
            for (let i = 0; i < this.trackStatusEvents.length; i++) {
                const event = this.trackStatusEvents[i];
                if (!event || event.session_time > this.currentTime) break;
                this.trackStatus.lastLoggedEventIndex = i;
            }
            return;
        }

        // Normal playback - display messages from last logged index forward
        for (let i = this.trackStatus.lastLoggedEventIndex + 1; i < this.trackStatusEvents.length; i++) {
            const event = this.trackStatusEvents[i];
            if (!event || event.session_time > this.currentTime) break;

            const message = event.message || '';
            // Display ALL non-empty messages with color coding based on status
            if (message) {
                this.raceControl.displayStatusMessage(event.session_time, message, event.status);
            }
            this.trackStatus.lastLoggedEventIndex = i;
        }
    }

    // Get all active statuses at current time
    // Returns: { statuses: [...], sectorStatuses: Map<sector, statusType>, blueFlagDrivers: Set }
    getActiveStatuses() {
        const BLUE_FLAG_DURATION = 3; // Blue flag shows for 3 seconds
        const statuses = [];
        const sectorStatuses = new Map();  // sector -> status type ('Yellow' or 'DoubleYellow')
        const blueFlagDrivers = new Set();

        for (const event of this.trackStatusEvents) {
            if (!event) continue;

            const status = (event.status || '').toUpperCase();

            // Blue flags are instant events (no end_time) - active for 3 seconds
            if (status === 'BLUE') {
                if (event.driver_num &&
                    this.currentTime >= event.session_time &&
                    this.currentTime < event.session_time + BLUE_FLAG_DURATION) {
                    blueFlagDrivers.add(event.driver_num);
                }
                continue;
            }

            // All other events need end_time to be intervals
            if (event.end_time === null || event.end_time === undefined) continue;

            // Active if: session_time <= currentTime < end_time
            if (this.currentTime < event.session_time || this.currentTime >= event.end_time) continue;

            if (status === 'RED' && !statuses.includes('Red')) {
                statuses.push('Red');
            } else if (status === 'SCENDING' && !statuses.includes('SafetyCarEnding')) {
                // SC Ending overrides regular SC
                statuses.push('SafetyCarEnding');
            } else if (status === 'SAFETYCAR' && !statuses.includes('SafetyCar') && !statuses.includes('SafetyCarEnding')) {
                statuses.push('SafetyCar');
            } else if (status === 'VSCENDING' && !statuses.includes('VSCEnding')) {
                // VSC Ending overrides regular VSC
                statuses.push('VSCEnding');
            } else if (status === 'VSC' && !statuses.includes('VSC') && !statuses.includes('VSCEnding')) {
                statuses.push('VSC');
            } else if (status === 'YELLOW' || status === 'DOUBLEYELLOW') {
                if (event.sector) {
                    const statusType = status === 'DOUBLEYELLOW' ? 'DoubleYellow' : 'Yellow';
                    // DoubleYellow takes priority over Yellow for same sector
                    const existing = sectorStatuses.get(event.sector);
                    if (!existing || statusType === 'DoubleYellow') {
                        sectorStatuses.set(event.sector, statusType);
                    }
                }
            } else if (status === 'RAIN' && !statuses.includes('Rain')) {
                statuses.push('Rain');
            } else if (status === 'WARMUP' && !statuses.includes('WarmUp')) {
                statuses.push('WarmUp');
            }
        }

        return { statuses, sectorStatuses, blueFlagDrivers };
    }

    // Update track from list of active statuses
    // Called every frame/scrub with current active statuses
    updateTrackFromStatuses(activeStatuses, sectorStatuses, blueFlagDrivers) {
        // Check for ending states
        const scEnding = activeStatuses.includes('SafetyCarEnding');
        const vscEnding = activeStatuses.includes('VSCEnding');
        const scActive = activeStatuses.includes('SafetyCar') || scEnding;
        const vscActive = activeStatuses.includes('VSC') || vscEnding;

        // Update internal state
        this.trackStatus.redFlag = activeStatuses.includes('Red');
        this.trackStatus.safetyCar = scActive;
        this.trackStatus.vsc = vscActive;
        this.trackStatus.sectorStatuses = sectorStatuses;
        this.blueFlagDrivers = blueFlagDrivers; // Store for rendering

        // Track whether we're in an ending state (for pulsing)
        this.trackPulsing = scEnding || vscEnding;

        // Determine base track color (priority: red > safetyCar > vsc > white)
        // Yellow sectors are handled separately in track rendering
        if (this.trackStatus.redFlag) {
            this.baseTrackColor = '#FF0000';
            this.trackPulsing = false; // No pulsing for red flag
        } else if (scActive) {
            this.baseTrackColor = '#FFD700'; // Gold for SC
        } else if (vscActive) {
            this.baseTrackColor = '#FFA500'; // Orange for VSC
        } else {
            this.baseTrackColor = '#FFFFFF';
            this.trackPulsing = false;
        }

        // Calculate actual track color (with pulsing if ending)
        this.trackColor = this.trackPulsing ? this.getPulsingColor(this.baseTrackColor) : this.baseTrackColor;

        // Update pills - each pill is independent, can show multiple
        const scPill = document.getElementById('safetyCarPill');
        const vscPill = document.getElementById('vscPill');
        const redFlagPill = document.getElementById('redFlagPill');
        const rainPill = document.getElementById('rainPill');
        const formationLapPill = document.getElementById('formationLapPill');

        // Show/hide pills and update text for ending states
        if (scPill) {
            scPill.classList.toggle('hidden', !scActive);
            scPill.textContent = scEnding ? 'Safety Car Ending' : 'Safety Car';
        }
        if (vscPill) {
            vscPill.classList.toggle('hidden', !vscActive);
            vscPill.textContent = vscEnding ? 'VSC Ending' : 'Virtual Safety Car';
        }
        if (redFlagPill) redFlagPill.classList.toggle('hidden', !activeStatuses.includes('Red'));
        if (rainPill) rainPill.classList.toggle('hidden', !activeStatuses.includes('Rain'));

        // Set rain active state for animation
        this.rainActive = activeStatuses.includes('Rain');

        // Formation lap pill - hide 20 seconds before lights out
        if (formationLapPill) {
            const warmUpActive = activeStatuses.includes('WarmUp');
            const nearLightsOut = this.lightsOutTime > 0 && this.currentTime >= (this.lightsOutTime - 20);
            formationLapPill.classList.toggle('hidden', !warmUpActive || nearLightsOut);
        }

        // Update status subtitle (WILL START AT / WILL RESUME AT messages)
        this.updateStatusSubtitle();
    }

    // Update status subtitle with "WILL START AT" type messages
    // Only updates DOM when content actually changes
    updateStatusSubtitle() {
        const statusMessages = this.sessionData?.events?.status_messages || [];

        // Find the latest active subtitle message (highest session_time that's still active)
        let activeMessage = null;
        let targetSessionTime = null;
        let latestSessionTime = -1;

        for (const msg of statusMessages) {
            if (!msg) continue;
            // Active if: session_time <= currentTime < end_time
            if (this.currentTime >= msg.session_time && this.currentTime < msg.end_time) {
                // Pick the latest message (replaces earlier ones)
                if (msg.session_time > latestSessionTime) {
                    activeMessage = msg.message;
                    targetSessionTime = msg.end_time;
                    latestSessionTime = msg.session_time;
                }
            }
        }

        let newSubtitleText = null;
        if (activeMessage && targetSessionTime !== null) {
            let formattedTime;
            if (targetSessionTime < this.lightsOutTime) {
                // Pre-race: show local time
                formattedTime = this.sessionTimeToLocalTime(targetSessionTime);
            } else {
                // During race: show race clock time
                const raceClockTime = targetSessionTime - this.lightsOutTime;
                const hours = Math.floor(raceClockTime / 3600);
                const minutes = Math.floor((raceClockTime % 3600) / 60);
                const seconds = Math.floor(raceClockTime % 60);
                formattedTime = `${hours}:${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`;
            }

            // Replace the "AT HH:MM" portion while preserving any suffix
            const parts = activeMessage.match(/(.+?)\s+AT\s+\d{1,2}:\d{2}(.*)/i);
            if (parts) {
                const prefix = parts[1].toUpperCase();
                const suffix = parts[2] || '';
                newSubtitleText = `${prefix} AT ${formattedTime}${suffix.toUpperCase()}`;
            } else {
                newSubtitleText = `WILL START AT ${formattedTime}`;
            }
        }

        // Only update DOM if subtitle changed
        if (newSubtitleText !== this._currentSubtitle) {
            this._currentSubtitle = newSubtitleText;
            const subtitle = document.getElementById('statusSubtitle');
            if (subtitle) {
                if (newSubtitleText) {
                    subtitle.textContent = newSubtitleText;
                    subtitle.classList.remove('hidden');
                } else {
                    subtitle.classList.add('hidden');
                }
            }
        }
    }

    // Get pulsing color - oscillates between base color and white
    getPulsingColor(baseColor) {
        // Use real time for smooth animation regardless of playback speed
        const pulseSpeed = 2; // Full cycle every ~3 seconds
        const t = (Date.now() / 1000) * pulseSpeed;
        const blend = 0.5 + 0.5 * Math.sin(t * Math.PI); // 0 to 1 (0 = white, 1 = base color)

        // Parse base hex color
        const r = parseInt(baseColor.slice(1, 3), 16);
        const g = parseInt(baseColor.slice(3, 5), 16);
        const b = parseInt(baseColor.slice(5, 7), 16);

        // Interpolate between white (255,255,255) and base color
        const nr = Math.round(255 + (r - 255) * blend);
        const ng = Math.round(255 + (g - 255) * blend);
        const nb = Math.round(255 + (b - 255) * blend);

        return `#${nr.toString(16).padStart(2, '0')}${ng.toString(16).padStart(2, '0')}${nb.toString(16).padStart(2, '0')}`;
    }

    // Update track status from current time (called on every frame/scrub)
    rebuildTrackStatusSilently() {
        const { statuses, sectorStatuses, blueFlagDrivers } = this.getActiveStatuses();
        this.updateTrackFromStatuses(statuses, sectorStatuses, blueFlagDrivers);
    }

    // Process track status events forward from last processed index
    // Uses structured data fields: status, flag_type, scope, sector, driver_num
    processTrackStatusForward(silent) {
        const startIndex = silent ? 0 : (this.trackStatus.lastLoggedEventIndex + 1);

        for (let eventIndex = startIndex; eventIndex < this.trackStatusEvents.length; eventIndex++) {
            const event = this.trackStatusEvents[eventIndex];
            if (!event || event.session_time > this.currentTime) break;

            const status = (event.status || '').toUpperCase();
            const flagType = (event.flag_type || '').toUpperCase();
            const scope = event.scope || 'Track';
            const sector = event.sector || 0;
            const driverNum = event.driver_num || '';
            const message = event.message || '';

            let changed = false;

            // Handle global track states (from session.track_status)
            if (status === 'RED') {
                changed |= this.trackStatus.setRedFlag(true);
                changed |= this.trackStatus.setSafetyCar(false);
                changed |= this.trackStatus.setVSC(false);
                changed |= this.trackStatus.setBlueFlag(false);
                if (this.trackStatus.sectorStatuses.size > 0) {
                    this.trackStatus.sectorStatuses.clear();
                    changed = true;
                }
            } else if (status === 'SAFETYCAR') {
                changed |= this.trackStatus.setSafetyCar(true);
                changed |= this.trackStatus.setVSC(false);
                changed |= this.trackStatus.setRedFlag(false);
                if (this.trackStatus.sectorStatuses.size > 0) {
                    this.trackStatus.sectorStatuses.clear();
                    changed = true;
                }
            } else if (status === 'VSC') {
                changed |= this.trackStatus.setVSC(true);
                changed |= this.trackStatus.setSafetyCar(false);
                changed |= this.trackStatus.setRedFlag(false);
            } else if (status === 'VSCENDING') {
                // VSC ending - will be followed by AllClear
                changed |= this.trackStatus.setVSC(false);
            } else if (status === 'YELLOW' || status === 'DOUBLEYELLOW' || flagType === 'YELLOW' || flagType === 'DOUBLE YELLOW') {
                // Yellow flag - use structured sector field if available
                if (!this.trackStatus.redFlag && !this.trackStatus.safetyCar) {
                    if (sector > 0) {
                        const statusType = (status === 'DOUBLEYELLOW' || flagType === 'DOUBLE YELLOW') ? 'DoubleYellow' : 'Yellow';
                        changed |= this.trackStatus.setSectorStatus(sector, statusType);
                    } else if (scope === 'Track') {
                        // Global yellow (session.track_status) - track-wide yellow state
                        // Don't add to sectors, just note it's yellow
                    }
                }
            } else if (status === 'ALLCLEAR' || (scope === 'Track' && (flagType === 'GREEN' || flagType === 'CLEAR'))) {
                // Track clear - reset all states
                changed |= this.trackStatus.setRedFlag(false);
                changed |= this.trackStatus.setSafetyCar(false);
                changed |= this.trackStatus.setVSC(false);
                if (this.trackStatus.sectorStatuses.size > 0) {
                    this.trackStatus.sectorStatuses.clear();
                    changed = true;
                }
            } else if (scope === 'Sector' && (flagType === 'GREEN' || flagType === 'CLEAR')) {
                // Sector clear - use structured sector field
                if (sector > 0 && !this.trackStatus.redFlag) {
                    changed |= this.trackStatus.clearSectorStatus(sector);
                }
            } else if (status === 'CHEQUERED' || flagType === 'CHEQUERED') {
                // Race finished
                changed |= this.trackStatus.clearAll();
            }

            // Log status changes during normal playback
            if (changed && !silent) {
                this.trackStatus.logStatusChange(event.session_time, message);
            }

            // Display ALL non-empty messages in race control (with color coding)
            if (message && !silent) {
                this.raceControl.displayStatusMessage(event.session_time, message, event.status);
            }
            this.trackStatus.lastLoggedEventIndex = eventIndex;
        }

        // Update visual representation
        this.updateTrackColor();
    }

    updateTrackColor() {
        // Update track color based on current track status state
        const globalStatus = this.trackStatus.getGlobalStatus();

        // Clear any existing flash interval
        if (this.flashInterval) clearInterval(this.flashInterval);

        // Set track color based on global status (note: blue flags no longer change track color)
        switch (globalStatus) {
            case 'RED':
                this.trackColor = '#FF0000';
                this.flashState = false;
                break;
            case 'SC':
                this.trackColor = '#FFD700';  // Gold/yellow for Safety Car
                this.flashState = false;
                break;
            case 'VSC':
                this.trackColor = '#FFA500';  // Orange for Virtual Safety Car
                this.flashState = false;
                break;
            case 'YELLOW':
                // Yellow flags are sector-specific
                this.trackColor = '#FFFFFF';
                this.flashState = false;
                break;
            case 'CLEAR':
            default:
                this.trackColor = '#FFFFFF';
                this.flashState = false;
        }

        // Update pills visibility
        this.updateStatusPills(globalStatus);
    }

    updateStatusPills(globalStatus) {
        // Show/hide status pills based on current track status state
        const scPill = document.getElementById('safetyCarPill');
        const vscPill = document.getElementById('vscPill');
        const redFlagPill = document.getElementById('redFlagPill');

        if (scPill) scPill.classList.toggle('hidden', globalStatus !== 'SC');
        if (vscPill) vscPill.classList.toggle('hidden', globalStatus !== 'VSC');
        if (redFlagPill) redFlagPill.classList.toggle('hidden', globalStatus !== 'RED');
    }

    // Blue flag cleanup is now handled by getActiveStatuses() with 3-second duration

    toggleChaseMode(driverCode) {
        // Toggle chase mode: if already chasing this driver, disable; otherwise enable
        if (this.chaseMode === driverCode) {
            this.chaseMode = null;  // Return to overview mode
        } else {
            this.chaseMode = driverCode;  // Enter chase mode for this driver
        }
        this.updateFollowMode();  // Update follow mode panel
        this.updateStandings();  // Update styling
    }

    updateFollowMode() {
        const followModePanel = document.getElementById('followModePanel');
        const selectorControls = document.getElementById('selectorControls');

        if (this.chaseMode) {
            // In follow mode - show follow panel, hide selectors
            followModePanel.classList.add('visible');
            selectorControls.style.display = 'none';

            // Update driver info display
            const positions = this.getDriversAtTime();
            const currentPosition = positions.findIndex(p => p.code === this.chaseMode) + 1;
            const driver = this.drivers.find(d => d.code === this.chaseMode);

            if (driver) {
                // Update position
                document.getElementById('followDriverPosition').textContent = currentPosition + '.';

                // Update name with team color
                const driverNameEl = document.getElementById('followDriverName');
                driverNameEl.textContent = driver.name;
                driverNameEl.style.color = driver.color;

                // Update number
                document.getElementById('followDriverNumber').textContent = '#' + driver.number;
            }

            // Reset zoom when entering follow mode
            this.currentZoom = 1.0;
        } else {
            // Not in follow mode - show selectors, hide follow panel
            followModePanel.classList.remove('visible');
            selectorControls.style.display = 'flex';
        }
    }

    switchDriver(direction) {
        if (!this.chaseMode) return;

        const positions = this.getDriversAtTime();
        const currentIndex = positions.findIndex(p => p.code === this.chaseMode);

        if (currentIndex === -1) return;

        // Calculate next index (wrap around at boundaries)
        // Positive direction = up arrow = move to lower index (higher position)
        let nextIndex = currentIndex - direction;
        if (nextIndex < 0) nextIndex = positions.length - 1;
        if (nextIndex >= positions.length) nextIndex = 0;

        const nextDriver = positions[nextIndex];
        this.chaseMode = nextDriver.code;
        this.updateFollowMode();
        this.updateStandings();
    }

    exitFollowMode() {
        this.chaseMode = null;
        // Reset overview zoom/pan when exiting follow mode
        this.userZoom = 1.0;
        this.panX = 0;
        this.panY = 0;
        this.canvas.style.cursor = 'default';
        this.updateFollowMode();
        this.updateStandings();
    }

    updateChaseModePosition(positions) {
        // Update only the position in the chase menu when driver position changes
        if (!this.chaseMode) return;

        const currentPosition = positions.findIndex(p => p.code === this.chaseMode) + 1;
        if (currentPosition > 0) {
            document.getElementById('followDriverPosition').textContent = currentPosition + '.';
        }
    }

    togglePlayPause() {
        this.isPlaying = !this.isPlaying;
        this.updatePlayPauseButton();
    }

    setSpeed(speed) {
        this.playSpeed = speed;
        document.getElementById('speedValue').textContent = speed + 'x';
        document.querySelectorAll('.speed-option').forEach(opt => {
            opt.classList.toggle('selected', parseFloat(opt.dataset.speed) === speed);
        });
    }

    renderSessionTabs() {
        const container = document.getElementById('sessionTabs');
        if (!container || !this.weekendData?.event?.sessions) return;

        const SESSION_MAP = {
            'Practice 1': 'FP1', 'Practice 2': 'FP2', 'Practice 3': 'FP3',
            'Qualifying': 'Q', 'Race': 'R',
            'Sprint': 'S', 'Sprint Qualifying': 'SQ', 'Sprint Shootout': 'SQ'
        };

        container.innerHTML = '';
        for (const session of this.weekendData.event.sessions) {
            const code = SESSION_MAP[session.name];
            if (!code) continue;
            const tab = document.createElement('div');
            tab.className = 'session-tab' + (code === SESSION_TYPE ? ' active' : '');
            tab.textContent = code;
            tab.addEventListener('click', () => this.switchSession(code));
            container.appendChild(tab);
        }
    }

    switchSession(sessionType) {
        if (sessionType === SESSION_TYPE) return;
        SESSION_TYPE = sessionType;

        // Update URL
        const url = new URL(window.location);
        url.searchParams.set('session', sessionType);
        history.replaceState(null, '', url);

        // Update active tab
        document.querySelectorAll('.session-tab').forEach(tab => {
            tab.classList.toggle('active', tab.textContent === sessionType);
        });

        // Reset session state
        this.isPlaying = false;
        this.updatePlayPauseButton();
        this.sessionData = null;
        this.hasSessionData = false;
        this.tier3Error = null;
        this.currentTime = 0;
        this.telemetryIndexCache = {};
        this.previousPositions = null;
        this.displayedMessageIds.clear();
        this.displayedEventPills.clear();
        this.trackStatusEvents = [];
        this.raceControlEvents = [];
        this.lastMessageIndexTrackStatus = 0;
        this.lastMessageIndexRaceControl = 0;

        // Clear UI
        document.getElementById('standings').innerHTML = '';
        const msgContainer = document.getElementById('raceMessages');
        if (msgContainer) msgContainer.innerHTML = '';

        // Reload session data
        this.loadSession();
    }

    updatePlayPauseButton() {
        const btn = document.getElementById('playPauseBtn');
        btn.textContent = this.isPlaying ? '⏸' : '▶';
    }

    handleSpeedChange(e) {
        const speedSelector = document.getElementById('speedSelector');
        const dropdown = speedSelector.querySelector('.speed-dropdown');

        if (e.target.classList.contains('speed-option')) {
            // Speed option clicked
            this.playSpeed = parseFloat(e.target.dataset.speed);
            document.querySelectorAll('.speed-option').forEach(opt => opt.classList.remove('selected'));
            e.target.classList.add('selected');
            document.getElementById('speedValue').textContent = this.playSpeed + 'x';
            // Auto-close dropdown
            dropdown.classList.remove('open');
        } else if (e.currentTarget.id === 'speedSelector') {
            // Speed selector button clicked - toggle dropdown
            dropdown.classList.toggle('open');
        }
    }

    isDriverRetired(driverCode) {
        // Check status column in telemetry
        const driver = this.drivers.find(d => d.code === driverCode);
        if (!driver || !driver.telemetry) return false;

        const tel = driver.telemetry;
        if (!tel.status) {
            // Status column not in API response - need to restart Flask server
            return false;
        }

        // Find closest telemetry entry to current time
        let idx = this.binarySearchTelemetryIndex(tel.session_time, this.currentTime);
        if (idx >= 0 && idx < tel.status.length) {
            return tel.status[idx] === 'Retired';  // Capital R - matches backend
        }
        return false;
    }

    getDriversAtTime() {
        const positions = [];
        for (const driver of this.drivers) {
            const tel = driver.telemetry;
            if (!tel.session_time || tel.session_time.length === 0) continue;

            // Get cached index or use binary search
            let idx1 = this.binarySearchTelemetryIndex(tel.session_time, this.currentTime);

            if (idx1 >= 0 && idx1 < tel.x.length) {
                // Get interpolated position between two samples
                const interpolated = this.interpolateDriverPosition(tel, idx1);

                positions.push({
                    code: driver.code,
                    number: driver.number,
                    x: interpolated.x,
                    y: interpolated.y,
                    progress: interpolated.progress,
                    interval: interpolated.interval,
                    compound: interpolated.compound,
                    tyreLife: interpolated.tyreLife,
                    status: interpolated.status,
                    color: driver.color
                });
            }
        }

        positions.sort((a, b) => b.progress - a.progress);
        return positions;
    }

    binarySearchTelemetryIndex(sessionTimes, targetTime) {
        let left = 0;
        let right = sessionTimes.length - 1;

        // Quick exit for out of bounds
        if (targetTime < sessionTimes[0]) return 0;
        if (targetTime >= sessionTimes[right]) return right;

        // Binary search for largest index where sessionTimes[i] <= targetTime
        while (left < right) {
            const mid = Math.floor((left + right + 1) / 2);
            if (sessionTimes[mid] <= targetTime) {
                left = mid;
            } else {
                right = mid - 1;
            }
        }

        return left;
    }

    /**
     * Cubic Hermite interpolation for smooth car movement.
     * p(t) = h00*p0 + h10*m0*dt + h01*p1 + h11*m1*dt
     */
    hermiteInterpolate(p0, p1, m0, m1, t, dt) {
        const t2 = t * t;
        const t3 = t2 * t;
        const h00 = 2*t3 - 3*t2 + 1;
        const h10 = t3 - 2*t2 + t;
        const h01 = -2*t3 + 3*t2;
        const h11 = t3 - t2;
        return h00 * p0 + h10 * m0 * dt + h01 * p1 + h11 * m1 * dt;
    }

    interpolateDriverPosition(telemetry, idx1) {
        const time1 = telemetry.session_time[idx1];
        const idx2 = idx1 + 1;

        // Get tire info and status (no interpolation needed - use current value)
        const compound = telemetry.compound ? telemetry.compound[idx1] : null;
        const tyreLife = telemetry.tyre_life ? telemetry.tyre_life[idx1] : null;
        const status = telemetry.status ? telemetry.status[idx1] : null;

        // If we're at the last sample or beyond current time, return without interpolation
        if (idx2 >= telemetry.session_time.length) {
            return {
                x: telemetry.x[idx1],
                y: telemetry.y[idx1],
                progress: telemetry.race_distance ? telemetry.race_distance[idx1] : 0,
                interval: telemetry.interval ? telemetry.interval[idx1] : null,
                compound,
                tyreLife,
                status
            };
        }

        const time2 = telemetry.session_time[idx2];
        const timeDelta = time2 - time1;

        // If samples are at same time, return first sample
        if (timeDelta <= 0) {
            return {
                x: telemetry.x[idx1],
                y: telemetry.y[idx1],
                progress: telemetry.race_distance ? telemetry.race_distance[idx1] : 0,
                interval: telemetry.interval ? telemetry.interval[idx1] : null,
                compound,
                tyreLife,
                status
            };
        }

        // Calculate interpolation factor (0 to 1)
        const t = Math.max(0, Math.min(1, (this.currentTime - time1) / timeDelta));

        // Check if velocity data is available for Hermite interpolation
        const hasVelocity = telemetry.vx && telemetry.vy &&
                            idx1 < telemetry.vx.length && idx2 < telemetry.vx.length;

        let x, y;
        if (hasVelocity) {
            // Cubic Hermite interpolation (smooth curves)
            const vx1 = telemetry.vx[idx1] || 0;
            const vy1 = telemetry.vy[idx1] || 0;
            const vx2 = telemetry.vx[idx2] || 0;
            const vy2 = telemetry.vy[idx2] || 0;
            x = this.hermiteInterpolate(telemetry.x[idx1], telemetry.x[idx2], vx1, vx2, t, timeDelta);
            y = this.hermiteInterpolate(telemetry.y[idx1], telemetry.y[idx2], vy1, vy2, t, timeDelta);
        } else {
            // Fallback to linear interpolation
            x = telemetry.x[idx1] + (telemetry.x[idx2] - telemetry.x[idx1]) * t;
            y = telemetry.y[idx1] + (telemetry.y[idx2] - telemetry.y[idx1]) * t;
        }

        // Interpolate race_distance (progress) - linear is fine
        let progress = telemetry.race_distance ? telemetry.race_distance[idx1] : 0;
        if (telemetry.race_distance && idx2 < telemetry.race_distance.length) {
            progress = telemetry.race_distance[idx1] + (telemetry.race_distance[idx2] - telemetry.race_distance[idx1]) * t;
        }

        // Use nearest interval value (don't interpolate)
        let interval = telemetry.interval ? telemetry.interval[idx1] : null;

        return { x, y, progress, interval, compound, tyreLife, status };
    }

    updateQualifyingStandings() {
        const qm = this.qualifyingManager;
        const phase = qm.getCurrentPhase(this.currentTime);
        const phaseName = phase ? phase.name : qm.getPhaseLabel(this.currentTime);
        const eliminated = qm.getEliminatedDrivers(this.currentTime);

        // Get best laps for current (or most recent) phase
        let activePhaseName = phase?.name;
        if (!activePhaseName) {
            // During intermission, show results from last completed phase
            for (let i = qm.phases.length - 1; i >= 0; i--) {
                if (this.currentTime > qm.phases[i].end) {
                    activePhaseName = qm.phases[i].name;
                    break;
                }
            }
            if (!activePhaseName) activePhaseName = 'Q1';
        }

        const bestLaps = qm.getBestLapsInPhase(activePhaseName, this.currentTime);
        const bestLapMap = new Map(bestLaps.map(r => [r.driver, r]));

        // Build sorted driver list: active with times, active without times, eliminated
        const activeWithTime = [];
        const activeNoTime = [];
        const eliminatedList = [];

        for (const driver of this.drivers) {
            const code = driver.code;
            const isElim = eliminated.has(code);
            const lapData = bestLapMap.get(code);

            if (isElim) {
                eliminatedList.push({ code, lapData, phase: qm.getEliminationPhase(code) });
            } else if (lapData) {
                activeWithTime.push({ code, lapData });
            } else {
                activeNoTime.push({ code });
            }
        }

        // Sort active by lap time
        activeWithTime.sort((a, b) => a.lapData.time - b.lapData.time);

        // Build final order
        const ordered = [
            ...activeWithTime.map((d, i) => ({ ...d, pos: i + 1, type: 'active' })),
            ...activeNoTime.map((d, i) => ({ ...d, pos: activeWithTime.length + i + 1, type: 'notime' })),
            ...eliminatedList.map(d => ({ ...d, type: 'eliminated' })),
        ];

        // Check if order changed
        const orderKey = ordered.map(d => d.code).join(',');
        const orderChanged = orderKey !== this._prevQualiOrder || this._prevQualiPhase !== activePhaseName;

        const standings = document.getElementById('standings');

        if (orderChanged) {
            standings.innerHTML = '';
            const poleTime = activeWithTime.length > 0 ? activeWithTime[0].lapData.time : 0;

            ordered.forEach((entry, idx) => {
                const driver = this.drivers.find(d => d.code === entry.code);
                const color = driver?.color || '#CCCCCC';
                const row = document.createElement('div');
                row.className = 'driver-row';
                row.dataset.driver = entry.code;
                row.style.cursor = 'pointer';

                if (entry.type === 'eliminated') {
                    row.classList.add('eliminated');
                }
                if (idx === 0 && entry.type === 'active') {
                    row.classList.add('leader');
                }
                if (this.chaseMode === entry.code) {
                    row.style.backgroundColor = 'rgba(255, 255, 255, 0.15)';
                    row.style.borderLeft = '3px solid #FFD700';
                    row.style.paddingLeft = '11px';
                }

                let timeDisplay, deltaDisplay;
                if (entry.type === 'active' && entry.lapData) {
                    timeDisplay = this.formatLapTime(entry.lapData.time);
                    deltaDisplay = entry.lapData.delta === 0
                        ? `<span style="color:#FFD700">P1</span>`
                        : `<span style="color:#888">+${entry.lapData.delta.toFixed(3)}</span>`;
                } else if (entry.type === 'eliminated' && entry.lapData) {
                    timeDisplay = this.formatLapTime(entry.lapData.time);
                    deltaDisplay = `<span style="color:#666">${entry.phase}</span>`;
                } else {
                    timeDisplay = '<span style="color:#555">NO TIME</span>';
                    deltaDisplay = '';
                }

                const posNum = entry.type === 'eliminated' ? '' : entry.pos;
                row.innerHTML = `
                    <div class="driver-position">${posNum}</div>
                    <div class="driver-color" style="background: ${color}"></div>
                    <div class="driver-info">
                        <div class="driver-header">
                            <div class="driver-name">${entry.code}</div>
                            <div class="driver-timing" style="font-family:monospace;font-size:${STANDINGS_SETTINGS.timeSize}">
                                ${timeDisplay}
                            </div>
                        </div>
                        <div class="driver-detail" style="font-size:9px;text-align:right">
                            ${deltaDisplay}
                        </div>
                    </div>
                `;

                row.addEventListener('click', () => this.toggleChaseMode(entry.code));
                standings.appendChild(row);
            });

            this._prevQualiOrder = orderKey;
            this._prevQualiPhase = activePhaseName;
        }

        // Update chase mode position display
        if (this.chaseMode) {
            const positions = this.getDriversAtTime();
            if (positions.length > 0) this.updateChaseModePosition(positions);
        }

        this.updateRaceMessages();
        this.updateFastestLapIndicatorPositions();
    }

    updateStandings() {
        if (this.isQualifying && this.qualifyingManager) {
            this.updateQualifyingStandings();
            return;
        }
        const positions = this.getDriversAtTime();

        // Update standings mode (time/tire cycling)
        const modeChanged = this.updateStandingsMode(positions);

        // Check if standings order changed (compare driver order) or if chase mode changed
        const orderChanged = !this.previousPositions ||
            this.previousPositions.length !== positions.length ||
            this.previousPositions.some((p, i) => p.code !== positions[i].code) ||
            this.previousChaseMode !== this.chaseMode;

        // Full rebuild if order changed or mode changed
        if (orderChanged || modeChanged) {
            const standings = document.getElementById('standings');
            standings.innerHTML = '';

            positions.forEach((pos, idx) => {
                const driver = this.drivers.find(d => d.code === pos.code);
                // Check status column for retirement
                const isDNF = this.isDriverRetired(pos.code);

                const row = document.createElement('div');
                row.className = 'driver-row' + (idx === 0 ? ' leader' : '');

                // Add chase mode styling if this driver is being chased
                if (this.chaseMode === pos.code) {
                    row.style.backgroundColor = 'rgba(255, 255, 255, 0.15)';
                    row.style.borderLeft = '3px solid #FFD700';
                    row.style.paddingLeft = '11px';
                }

                // Keep team color, but make driver name grey if DNF
                const displayColor = pos.color;
                const nameColor = isDNF ? '#666666' : '#FFFFFF';

                // Generate info column based on standings mode
                let infoColumn;
                if (this.standingsMode === 'tire') {
                    infoColumn = this.renderTireInfo(pos, isDNF);
                } else {
                    infoColumn = this.renderTimeInfo(pos, idx, positions, isDNF);
                }

                row.innerHTML = `
                    <div class="driver-position">${idx + 1}</div>
                    <div class="driver-color" style="background: ${displayColor}"></div>
                    <div class="driver-info">
                        <div class="driver-header">
                            <div class="driver-name" style="color: ${nameColor}">${pos.code}</div>
                            <div class="driver-number">#${pos.number}</div>
                        </div>
                        ${infoColumn}
                    </div>
                `;
                row.dataset.driver = pos.code;

                // Add click handler to toggle chase mode
                row.style.cursor = 'pointer';
                row.addEventListener('click', () => this.toggleChaseMode(pos.code));

                standings.appendChild(row);
            });

            this.previousPositions = positions;
            this.previousChaseMode = this.chaseMode;
        } else {
            // Just update the info column (time gaps or tire info) without full rebuild
            this.updateStandingsInfo(positions);
        }

        // Update chase mode position display if following a driver
        if (this.chaseMode && positions.length > 0) {
            this.updateChaseModePosition(positions);
        }

        // Update lap info
        if (positions.length > 0) {
            const trackLength = this.sessionData.metadata.track_length;
            const lap = Math.max(1, Math.floor(positions[0].progress / trackLength) + 1);

            // Calculate total laps once and cache it
            if (this.cachedTotalLaps === null) {
                let totalLaps = this.sessionData.metadata.total_laps;

                // Fallback: if total_laps seems invalid (too high or zero), calculate from telemetry
                if (!totalLaps || totalLaps > 500) {
                    let maxLap = 1;
                    for (const driver in this.sessionData.telemetry) {
                        const tel = this.sessionData.telemetry[driver];
                        if (tel.lap_number && tel.lap_number.length > 0) {
                            const driverMaxLap = Math.max(...tel.lap_number);
                            maxLap = Math.max(maxLap, driverMaxLap);
                        }
                    }
                    totalLaps = maxLap;
                }

                this.cachedTotalLaps = totalLaps;
            }

            document.getElementById('lapCounter').textContent = `Lap ${lap} / ${this.cachedTotalLaps}`;
        }

        // Update race control messages
        this.updateRaceMessages();

        // Update fastest lap indicator positions
        this.updateFastestLapIndicatorPositions();

        // Update fastest lap display
        this.updateFastestLapDisplay();
    }

    // Standings mode cycling between time and tire display
    // Scrolling: deterministic based on lap position (2 laps time, 0.5 lap tire per cycle)
    // Fast playback (5x+): lap-based cycling
    // Normal playback (2x or slower): time-based cycling (90s time, 20s tire)
    updateStandingsMode(positions) {
        const now = Date.now();
        const timeSinceSwitch = (now - this.standingsModeLastSwitch) / 1000;

        // Calculate current leader lap (fractional)
        let currentLap = 0;
        if (positions.length > 0 && this.sessionData) {
            const trackLength = this.sessionData.metadata.track_length;
            currentLap = positions[0].progress / trackLength;
        }

        // When scrolling, mode is deterministic based on lap position
        if (this.isDraggingKnob) {
            // Cycle: 2 laps time, 0.5 lap tire (2.5 lap total cycle)
            const cycleLength = 2.5;
            const positionInCycle = currentLap % cycleLength;
            const newMode = positionInCycle < 2 ? 'time' : 'tire';

            if (newMode !== this.standingsMode) {
                this.standingsMode = newMode;
                this.standingsModeLastSwitch = now;
                this.standingsModeLastLap = currentLap;
                return true;
            }
            return false;
        }

        const lapsSinceSwitch = currentLap - this.standingsModeLastLap;
        let shouldSwitch = false;

        if (this.playSpeed >= 5) {
            // Fast playback: lap-based cycling
            if (this.standingsMode === 'time') {
                if (lapsSinceSwitch >= 2 && timeSinceSwitch >= 1) {
                    shouldSwitch = true;
                }
            } else {
                if (lapsSinceSwitch >= 0.5 && timeSinceSwitch >= 1) {
                    shouldSwitch = true;
                }
            }
        } else {
            // Normal playback: time-based cycling (90s time, 20s tire)
            if (this.standingsMode === 'time') {
                if (timeSinceSwitch >= 90) {
                    shouldSwitch = true;
                }
            } else {
                if (timeSinceSwitch >= 20) {
                    shouldSwitch = true;
                }
            }
        }

        if (shouldSwitch) {
            this.standingsMode = this.standingsMode === 'time' ? 'tire' : 'time';
            this.standingsModeLastSwitch = now;
            this.standingsModeLastLap = currentLap;
            return true;
        }

        return false;
    }

    // Render time/gap info for a driver
    renderTimeInfo(pos, idx, positions, isDNF) {
        const inPit = pos.status === 'pit';
        const isPreRace = pos.status === 'PreSession' || pos.status === 'WarmUp';

        let gap;
        if (isDNF) {
            gap = 'DNF';
        } else if (idx === 0) {
            gap = 'LEADER';
        } else if (isPreRace) {
            // Show distance to car ahead in meters during pre-race phases
            const aheadPos = positions[idx - 1];
            const distGap = aheadPos.progress - pos.progress;
            gap = '+' + Math.round(distGap) + 'm';
        } else if (pos.interval !== null && pos.interval !== undefined) {
            gap = '+' + pos.interval.toFixed(2) + 's';
        } else {
            // Fallback to distance if time unavailable
            gap = '+' + (positions[0].progress - pos.progress).toFixed(1) + 'm';
        }

        // Show tire icon if driver recently changed tires (TyreLife <= 2 laps)
        let tireIndicator = '';
        if (!isDNF && pos.tyreLife !== null && pos.tyreLife !== undefined && pos.tyreLife <= 2) {
            const tireColor = this.getTireColor(pos.compound);
            tireIndicator = `<span style="margin-right: 4px;">${this.tireIcon(tireColor, '#2D2D32', '#141416', 12)}</span>`;
        }

        // Brighter colors when in pit (white instead of grey, yellow instead of gold)
        const textColor = inPit ? (idx === 0 ? '#FFFF00' : '#FFFFFF') : '';
        const styleAttr = textColor ? ` style="color: ${textColor}"` : '';

        return `<div class="driver-interval"${styleAttr}>${tireIndicator}${gap}</div>`;
    }

    // Update just the info column (time/tire) without full DOM rebuild
    updateStandingsInfo(positions) {
        const standings = document.getElementById('standings');
        const rows = standings.querySelectorAll('.driver-row');

        rows.forEach((row, idx) => {
            const pos = positions[idx];
            if (!pos) return;

            const isDNF = this.isDriverRetired(pos.code);

            // Find and update the info element
            const infoContainer = row.querySelector('.driver-info');
            if (!infoContainer) return;

            // Remove old interval/tire element
            const oldInterval = infoContainer.querySelector('.driver-interval');
            const oldTire = infoContainer.querySelector('.driver-tire');
            if (oldInterval) oldInterval.remove();
            if (oldTire) oldTire.remove();

            // Add new info based on current mode
            if (this.standingsMode === 'tire') {
                infoContainer.insertAdjacentHTML('beforeend', this.renderTireInfo(pos, isDNF));
            } else {
                infoContainer.insertAdjacentHTML('beforeend', this.renderTimeInfo(pos, idx, positions, isDNF));
            }
        });
    }

    // Switch sidebar between standings and strategy/results views
    switchSidebarTab(tab) {
        const standings = document.getElementById('standings');
        const strategy = document.getElementById('strategyPanel');
        const buttons = document.querySelectorAll('.sidebar-tab-btn');

        if (tab === 'strategy') {
            this.strategyView = true;
            standings.style.display = 'none';
            strategy.style.display = 'block';
            if (this.isQualifying) {
                this.renderQualifyingResults();
            } else {
                this.renderStrategyPanel();
            }
        } else {
            this.strategyView = false;
            standings.style.display = 'block';
            strategy.style.display = 'none';
        }

        buttons.forEach(btn => {
            btn.classList.toggle('active', btn.dataset.tab === tab);
        });
    }

    // Render tyre strategy bars for all drivers
    renderStrategyPanel() {
        const panel = document.getElementById('strategyPanel');
        if (!this.driverStints || !this.sessionData) return;

        const totalLaps = this.cachedTotalLaps || this.sessionData.metadata.total_laps || 1;

        // Sort drivers by finishing position (use last position_history entry)
        const history = this.sessionData.results?.position_history;
        let driverOrder = this.drivers.map(d => d.code);
        if (history && history.length > 0) {
            const last = history[history.length - 1];
            if (last.standings) {
                driverOrder = last.standings.map(s => s.driver);
            }
        }

        let html = '';
        for (const code of driverOrder) {
            const stints = this.driverStints[code];
            if (!stints || stints.length === 0) continue;

            const pitCount = stints.length - 1;
            let barsHtml = '';
            for (const stint of stints) {
                const laps = Math.max(1, stint.endLap - stint.startLap + 1);
                const widthPct = (laps / totalLaps) * 100;
                const color = this.getTireColor(stint.compound);
                const isFuture = stint.startTime > this.currentTime;
                const futureClass = isFuture ? ' future' : '';
                const label = laps >= 3 ? stint.compound?.charAt(0) || '' : '';
                barsHtml += `<div class="stint-segment${futureClass}" style="width:${widthPct}%;background:${color}">${label}</div>`;
            }

            html += `<div class="strategy-row">
                <span class="strategy-driver">${code}</span>
                <div class="strategy-bar">${barsHtml}<div class="strategy-marker" id="marker-${code}"></div></div>
                <span class="strategy-pit-count">${pitCount}</span>
            </div>`;
        }
        panel.innerHTML = html;
    }

    // Update strategy "now" markers (called from animate when strategy view is active)
    updateStrategyMarkers() {
        if (!this.strategyView || !this.driverStints) return;
        for (const code in this.driverStints) {
            const stints = this.driverStints[code];
            if (!stints || stints.length === 0) continue;
            const marker = document.getElementById(`marker-${code}`);
            if (!marker) continue;

            const firstTime = stints[0].startTime;
            const lastTime = stints[stints.length - 1].endTime;
            const totalDuration = lastTime - firstTime;
            if (totalDuration <= 0) continue;

            const progress = Math.max(0, Math.min(1, (this.currentTime - firstTime) / totalDuration));
            marker.style.left = `${progress * 100}%`;

            // Update future/past opacity on stint segments
            const bar = marker.parentElement;
            const segments = bar.querySelectorAll('.stint-segment');
            let stintIdx = 0;
            segments.forEach(seg => {
                if (stintIdx < stints.length) {
                    seg.classList.toggle('future', stints[stintIdx].startTime > this.currentTime);
                }
                stintIdx++;
            });
        }
    }

    // Render pit stop dots on the progress bar
    renderPitStopDots() {
        const track = document.getElementById('raceProgressTrack');
        // Remove old dots
        track.querySelectorAll('.pit-stop-dot').forEach(d => d.remove());

        if (!this.pitStops || !this.maxTime || !this.minTime) return;
        const range = this.maxTime - this.minTime;
        if (range <= 0) return;

        for (const pit of this.pitStops) {
            const pct = ((pit.time - this.minTime) / range) * 100;
            const dot = document.createElement('div');
            dot.className = 'pit-stop-dot';
            dot.style.left = `${pct}%`;
            dot.style.background = pit.color;
            track.appendChild(dot);
        }
    }

    renderQualifyingPhaseMarkers() {
        const track = document.getElementById('raceProgressTrack');
        track.querySelectorAll('.quali-phase-marker').forEach(d => d.remove());

        if (!this.qualifyingManager || !this.maxTime || !this.minTime) return;
        const range = this.maxTime - this.minTime;
        if (range <= 0) return;

        for (const phase of this.qualifyingManager.phases) {
            // Phase start marker
            const startPct = ((phase.start - this.minTime) / range) * 100;
            const startEl = document.createElement('div');
            startEl.className = 'quali-phase-marker';
            startEl.style.cssText = `position:absolute;left:${startPct}%;top:-12px;font-size:8px;color:#aaa;transform:translateX(-50%)`;
            startEl.textContent = phase.name;
            track.appendChild(startEl);

            // Phase end line
            const endPct = ((phase.chequered - this.minTime) / range) * 100;
            const lineEl = document.createElement('div');
            lineEl.className = 'quali-phase-marker';
            lineEl.style.cssText = `position:absolute;left:${endPct}%;top:0;bottom:0;width:1px;background:rgba(255,255,255,0.3)`;
            track.appendChild(lineEl);
        }
    }

    // Toggle lap time chart overlay
    toggleLapChart(forceState) {
        const overlay = document.getElementById('lapChartOverlay');
        const show = forceState !== undefined ? forceState : !overlay.classList.contains('visible');
        overlay.classList.toggle('visible', show);
        this.lapChartVisible = show;
        if (show) this.renderLapChart();
    }

    // Render lap time chart on canvas
    renderLapChart() {
        const canvas = document.getElementById('lapChart');
        const ctx = canvas.getContext('2d');
        const W = canvas.width;
        const H = canvas.height;
        ctx.clearRect(0, 0, W, H);

        if (!this.driverLapTimes || !this.sessionData) return;

        const totalLaps = this.cachedTotalLaps || this.sessionData.metadata.total_laps || 1;

        // Get current leader lap for time-sync
        const positions = this.getDriversAtTime();
        let currentLap = 1;
        if (positions.length > 0) {
            const trackLength = this.sessionData.metadata.track_length;
            currentLap = Math.floor(positions[0].progress / trackLength) + 1;
        }

        // Pick which drivers to show: top 5 + chased driver
        const showDrivers = new Set();
        const meta = this.sessionData.metadata;
        if (positions.length > 0) {
            for (let i = 0; i < Math.min(5, positions.length); i++) {
                showDrivers.add(positions[i].code);
            }
        }
        if (this.chaseMode) showDrivers.add(this.chaseMode);

        // Compute Y range (min/max lap time, excluding outliers like pit laps)
        let allTimes = [];
        for (const code of showDrivers) {
            const laps = this.driverLapTimes[code];
            if (!laps) continue;
            for (const [lap, data] of Object.entries(laps)) {
                if (+lap <= currentLap && data.duration < 300) {
                    allTimes.push(data.duration);
                }
            }
        }
        if (allTimes.length === 0) return;

        // Remove outliers (>median * 1.5)
        allTimes.sort((a, b) => a - b);
        const median = allTimes[Math.floor(allTimes.length / 2)];
        const threshold = median * 1.5;
        allTimes = allTimes.filter(t => t < threshold);
        if (allTimes.length === 0) return;

        const minTime = allTimes[0] * 0.99;
        const maxTime = allTimes[allTimes.length - 1] * 1.01;
        const timeRange = maxTime - minTime || 1;

        const padL = 40, padR = 10, padT = 5, padB = 20;
        const plotW = W - padL - padR;
        const plotH = H - padT - padB;

        // Draw axes
        ctx.strokeStyle = 'rgba(255,255,255,0.15)';
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(padL, padT);
        ctx.lineTo(padL, H - padB);
        ctx.lineTo(W - padR, H - padB);
        ctx.stroke();

        // Y axis labels
        ctx.fillStyle = '#666';
        ctx.font = '9px monospace';
        ctx.textAlign = 'right';
        for (let i = 0; i <= 3; i++) {
            const t = minTime + (timeRange * i / 3);
            const y = padT + plotH - (plotH * i / 3);
            const mins = Math.floor(t / 60);
            const secs = (t % 60).toFixed(0).padStart(2, '0');
            ctx.fillText(`${mins}:${secs}`, padL - 4, y + 3);
        }

        // X axis labels
        ctx.textAlign = 'center';
        const lapStep = Math.max(1, Math.ceil(totalLaps / 6));
        for (let lap = 1; lap <= totalLaps; lap += lapStep) {
            const x = padL + (plotW * (lap - 1) / (totalLaps - 1 || 1));
            ctx.fillText(lap, x, H - 4);
        }

        // Draw driver lines
        for (const code of showDrivers) {
            const laps = this.driverLapTimes[code];
            if (!laps) continue;
            const driver = this.drivers.find(d => d.code === code);
            const color = driver?.color || '#CCCCCC';

            ctx.strokeStyle = color;
            ctx.lineWidth = this.chaseMode === code ? 2 : 1;
            ctx.globalAlpha = this.chaseMode && this.chaseMode !== code ? 0.4 : 0.8;
            ctx.beginPath();

            let started = false;
            for (let lap = 2; lap <= currentLap; lap++) {
                const data = laps[lap];
                if (!data || data.duration >= threshold) continue;

                const x = padL + (plotW * (lap - 1) / (totalLaps - 1 || 1));
                const y = padT + plotH - (plotH * (data.duration - minTime) / timeRange);

                if (!started) {
                    ctx.moveTo(x, y);
                    started = true;
                } else {
                    ctx.lineTo(x, y);
                }
            }
            ctx.stroke();
            ctx.globalAlpha = 1;
        }

        // Highlight fastest lap
        const fastestLaps = this.sessionData.results?.fastest_laps;
        if (fastestLaps && fastestLaps.length > 0) {
            const fastest = fastestLaps[fastestLaps.length - 1];
            if (fastest.session_time <= this.currentTime) {
                const driver = this.drivers.find(d => d.code === fastest.driver);
                const x = padL + (plotW * (fastest.lap - 1) / (totalLaps - 1 || 1));
                const lapData = this.driverLapTimes[fastest.driver]?.[fastest.lap];
                if (lapData && lapData.duration < threshold) {
                    const y = padT + plotH - (plotH * (lapData.duration - minTime) / timeRange);
                    ctx.beginPath();
                    ctx.arc(x, y, 4, 0, Math.PI * 2);
                    ctx.fillStyle = '#BB86FC';
                    ctx.fill();
                }
            }
        }
    }

    // Render qualifying results view
    renderQualifyingResults() {
        const panel = document.getElementById('strategyPanel');
        if (!this.sessionData) return;

        // Get best lap per driver from fastest_laps or driverLapTimes
        const driverBest = {};
        for (const code of this.sessionData.metadata.drivers) {
            const laps = this.driverLapTimes[code];
            if (!laps) continue;
            let best = Infinity;
            for (const data of Object.values(laps)) {
                if (data.duration < best) best = data.duration;
            }
            if (best < Infinity) driverBest[code] = best;
        }

        // Sort by lap time
        const sorted = Object.entries(driverBest).sort((a, b) => a[1] - b[1]);
        if (sorted.length === 0) { panel.innerHTML = '<div style="padding:10px;color:#666">No qualifying data</div>'; return; }

        const poleTime = sorted[0][1];
        const maxDelta = sorted[sorted.length - 1][1] - poleTime;

        // Q1/Q2/Q3 elimination lines
        const q3Cut = 10;
        const q2Cut = 15;

        let html = '';
        sorted.forEach(([code, time], idx) => {
            const driver = this.drivers.find(d => d.code === code);
            const color = driver?.color || '#CCCCCC';
            const delta = time - poleTime;
            const barWidth = maxDelta > 0 ? (delta / maxDelta) * 100 : 0;
            const deltaStr = idx === 0 ? 'POLE' : `+${delta.toFixed(3)}`;

            // Add Q-elimination separator
            let separator = '';
            if (idx === q3Cut || idx === q2Cut) {
                const label = idx === q3Cut ? 'Q2 eliminated' : 'Q1 eliminated';
                separator = `<div style="padding:2px 6px;font-size:9px;color:#666;border-top:1px solid rgba(255,255,255,0.1);margin-top:2px">${label}</div>`;
            }

            html += separator + `<div class="strategy-row" style="gap:4px">
                <span style="width:18px;color:#666;font-size:10px;text-align:right">${idx + 1}</span>
                <span style="width:3px;background:${color};border-radius:1px;align-self:stretch"></span>
                <span class="strategy-driver">${code}</span>
                <span style="flex:1;font-size:10px;color:#AAAAAA;font-family:monospace">${this.formatLapTime(time)}</span>
                <span style="width:60px;text-align:right;font-size:10px;color:${idx === 0 ? '#FFD700' : '#666'};font-family:monospace">${deltaStr}</span>
            </div>`;
        });
        panel.innerHTML = html;
    }

    // Export session data as CSV or JSON
    exportData(format) {
        if (!this.sessionData) return;
        const meta = this.sessionData.metadata;
        const filename = `${meta.year}_R${meta.round_number}_${meta.session_type}`;

        if (format === 'json') {
            const data = {
                metadata: meta,
                stints: this.driverStints,
                pitStops: this.pitStops,
                lapTimes: this.driverLapTimes,
                results: this.sessionData.results
            };
            this.downloadFile(`${filename}.json`, JSON.stringify(data, null, 2), 'application/json');
        } else {
            // CSV: one row per driver per lap with telemetry snapshot
            const rows = ['Driver,Lap,LapTime,Compound,TyreLife,Position'];
            for (const driver of this.drivers) {
                const laps = this.driverLapTimes[driver.code] || {};
                const stints = this.driverStints[driver.code] || [];

                for (const [lap, data] of Object.entries(laps)) {
                    const stint = stints.find(s => +lap >= s.startLap && +lap <= s.endLap);
                    const compound = stint ? stint.compound : '';
                    const tyreLife = stint ? (+lap - stint.startLap + 1) : '';

                    // Find position at this lap from position_history
                    let pos = '';
                    const history = this.sessionData.results?.position_history;
                    if (history) {
                        for (let i = history.length - 1; i >= 0; i--) {
                            if (history[i].lap <= +lap) {
                                const entry = history[i].standings?.find(s => s.driver === driver.code);
                                if (entry) pos = entry.position;
                                break;
                            }
                        }
                    }

                    rows.push(`${driver.code},${lap},${data.duration.toFixed(3)},${compound},${tyreLife},${pos}`);
                }
            }
            this.downloadFile(`${filename}.csv`, rows.join('\n'), 'text/csv');
        }
    }

    // Trigger file download in browser
    downloadFile(filename, content, mimeType) {
        const blob = new Blob([content], { type: mimeType });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
    }

    // Format lap time from seconds to M:SS.mmm
    formatLapTime(seconds) {
        if (!seconds || seconds <= 0) return '-';
        const mins = Math.floor(seconds / 60);
        const secs = (seconds % 60).toFixed(3).padStart(6, '0');
        return mins > 0 ? `${mins}:${secs}` : secs;
    }

    // Map tyre compound to wall color
    getTireColor(compound) {
        const c = (compound || '').toUpperCase();
        if (c === 'SOFT') return '#FF3333';
        if (c === 'MEDIUM') return '#FFD700';
        if (c === 'HARD') return '#FFFFFF';
        if (c === 'INTERMEDIATE') return '#43B02A';
        if (c === 'WET') return '#0066FF';
        return '#888888';
    }

    // Generate tire SVG icon
    tireIcon(color = '#888888', spokes = '#2D2D32', cap = '#141416', size = 14) {
        const maskId = 'tireMask' + Math.random().toString(36).substr(2, 9);
        return `<svg width="${size}" height="${size}" viewBox="0 0 200 200" xmlns="http://www.w3.org/2000/svg">
            <defs>
                <mask id="${maskId}">
                    <circle cx="100" cy="100" r="90" fill="white"/>
                    <circle cx="100" cy="100" r="55" fill="black"/>
                </mask>
            </defs>
            <rect x="90" y="45" width="20" height="55" fill="${spokes}"/>
            <rect x="90" y="45" width="20" height="55" fill="${spokes}" transform="rotate(72 100 100)"/>
            <rect x="90" y="45" width="20" height="55" fill="${spokes}" transform="rotate(144 100 100)"/>
            <rect x="90" y="45" width="20" height="55" fill="${spokes}" transform="rotate(216 100 100)"/>
            <rect x="90" y="45" width="20" height="55" fill="${spokes}" transform="rotate(288 100 100)"/>
            <circle cx="100" cy="100" r="90" fill="${color}" stroke="${spokes}" stroke-width="20" mask="url(#${maskId})"/>
            <circle cx="100" cy="100" r="55" fill="none" stroke="${spokes}" stroke-width="10"/>
            <circle cx="100" cy="100" r="20" fill="${cap}"/>
        </svg>`;
    }

    // Render tire info for a driver
    renderTireInfo(pos, isDNF) {
        if (isDNF) {
            return `<div class="driver-tire"><span class="tire-laps">DNF</span></div>`;
        }

        const inPit = pos.status === 'pit';

        // Get compound and tire life directly from position data
        const compound = pos.compound ? pos.compound.toUpperCase() : null;
        const tyreLife = pos.tyreLife;
        const displayLife = (tyreLife !== null && tyreLife !== undefined) ? Math.round(tyreLife) : '?';

        const tireColor = this.getTireColor(compound);

        // Brighter text color when in pit
        const textColor = inPit ? '#FFFFFF' : '#AAAAAA';

        return `<div class="driver-tire">
            ${this.tireIcon(tireColor)}
            <span class="tire-laps" style="color: ${textColor}">${displayLife}</span>
        </div>`;
    }

    updateRaceMessages() {
        // Detect scrubbing (time went backwards) - reset indices
        const isScrubbing = this.currentTime < this.lastProcessedStatusTime;
        if (isScrubbing) {
            // Reset and rebuild silently
            this.activeEvents = { rain: false };
            this.rebuildActiveEventsSilently();
            return;
        }

        // Process race control messages through RaceControl manager (only during forward playback)
        for (let i = this.raceControl.lastLoggedEventIndex + 1; i < this.raceControlEvents.length; i++) {
            const event = this.raceControlEvents[i];
            if (event && event.session_time <= this.currentTime) {
                this.raceControl.addMessage(event.session_time, event.message);
                this.raceControl.logMessage(event.session_time, event.message);
                this.raceControl.lastLoggedEventIndex = i;
            } else {
                break;
            }
        }

        // Update pill notifications (rain check + use TrackStatus for SC/VSC/Red)
        this.updateActivePillNotifications();
    }

    // Rebuild active events state silently (for scrubbing)
    rebuildActiveEventsSilently() {
        // Process all track status events up to current time (SC, VSC, Red, Yellow, etc.)
        // This updates TrackStatus which is the single source of truth
        this.processTrackStatusForward(true);  // silent = true

        // Update pill displays based on TrackStatus state
        this.updateActivePillNotifications();
    }

    formatLapTime(seconds) {
        const minutes = Math.floor(seconds / 60);
        const secs = (seconds % 60).toFixed(1);
        return `${minutes}m ${secs}s`;
    }

    updateFastestLapDisplay() {
        // Process fastest lap events
        if (!this.sessionData || !this.sessionData.results || !this.sessionData.results.fastest_laps) {
            return;
        }

        const fastestLaps = this.sessionData.results.fastest_laps;
        if (fastestLaps.length === 0) return;

        // Find the fastest lap that has occurred up to the current time
        let applicableFastestLap = null;
        for (const lap of fastestLaps) {
            if (lap.session_time <= this.currentTime) {
                applicableFastestLap = lap;
            } else {
                break;  // Since they're chronological, stop at first future lap
            }
        }

        if (!applicableFastestLap) {
            // If no laps have occurred yet, don't show any indicator
            document.querySelectorAll('.fastest-lap-indicator-item').forEach(indicator => {
                indicator.classList.remove('active');
            });
            return;
        }

        // Check if this is a new fastest lap (changed since last update)
        const isNewFastestLap = applicableFastestLap.driver !== this.currentFastestLapDriver;

        // Deactivate other indicators (preserve current driver's state)
        document.querySelectorAll('.fastest-lap-indicator-item').forEach(indicator => {
            if (indicator.dataset.driver !== applicableFastestLap.driver) {
                indicator.classList.remove('active', 'showing-time');
                const timeEl = indicator.querySelector('.fastest-lap-time');
                if (timeEl) timeEl.remove();
            }
        });

        const driverIndicator = document.querySelector(`.fastest-lap-indicator-item[data-driver="${applicableFastestLap.driver}"]`);
        if (driverIndicator) {
            driverIndicator.classList.add('active');

            // If it's a new fastest lap, show the time (hide icon)
            if (isNewFastestLap) {
                const formattedTime = this.formatLapTime(applicableFastestLap.time);

                // Remove any existing time element
                const existingTime = driverIndicator.querySelector('.fastest-lap-time');
                if (existingTime) {
                    existingTime.remove();
                }

                // Add time element and show-time state
                const timeElement = document.createElement('span');
                timeElement.className = 'fastest-lap-time';
                timeElement.textContent = formattedTime;
                driverIndicator.appendChild(timeElement);
                driverIndicator.classList.add('showing-time');

                // After 3s (real time), hide time and show icon
                setTimeout(() => {
                    driverIndicator.classList.remove('showing-time');
                    timeElement.remove();
                }, 3000);
            }

            this.currentFastestLapDriver = applicableFastestLap.driver;
        }
    }

    updateActivePillNotifications() {
        // All status pills (including Rain) are now handled by track_status
        // via updateTrackFromStatuses() - single source of truth
        this.updateStatusPills(this.trackStatus.getGlobalStatus());
    }

    formatTime(seconds) {
        const mins = Math.floor(seconds / 60);
        const secs = Math.floor(seconds % 60);
        return `${mins}:${secs.toString().padStart(2, '0')}`;
    }

    formatCountdown(seconds) {
        const mins = Math.floor(seconds / 60);
        const secs = Math.floor(seconds % 60);
        return `${mins}:${secs.toString().padStart(2, '0')}`;
    }

    // Smooth a path using Catmull-Rom spline interpolation
    smoothPath(points, tension = 0.5) {
        if (points.length < 3) return points;

        const smoothed = [];
        const segments = 10; // Number of curve segments per point

        for (let i = 0; i < points.length - 1; i++) {
            const p0 = points[Math.max(0, i - 1)];
            const p1 = points[i];
            const p2 = points[i + 1];
            const p3 = points[Math.min(points.length - 1, i + 2)];

            for (let t = 0; t < 1; t += 1 / segments) {
                const t2 = t * t;
                const t3 = t2 * t;

                const q = 0.5 * (
                    (2 * p1.x) +
                    (-p0.x + p2.x) * t +
                    (2 * p0.x - 5 * p1.x + 4 * p2.x - p3.x) * t2 +
                    (-p0.x + 3 * p1.x - 3 * p2.x + p3.x) * t3
                );

                const r = 0.5 * (
                    (2 * p1.y) +
                    (-p0.y + p2.y) * t +
                    (2 * p0.y - 5 * p1.y + 4 * p2.y - p3.y) * t2 +
                    (-p0.y + 3 * p1.y - 3 * p2.y + p3.y) * t3
                );

                smoothed.push({x: q, y: r});
            }
        }

        smoothed.push(points[points.length - 1]);
        return smoothed;
    }

    render() {
        const width = this.canvas.width / (window.devicePixelRatio || 1);
        const height = this.canvas.height / (window.devicePixelRatio || 1);

        this.ctx.fillStyle = '#000';
        this.ctx.fillRect(0, 0, width, height);

        // Early return if no track data - show loading or error message
        if (!this.trackData) {
            this.ctx.textAlign = 'center';
            this.ctx.textBaseline = 'middle';
            if (this.tier2Error) {
                // Error state handled by showTrackError()
            } else if (!this.hasTrackData) {
                this.ctx.fillStyle = '#666';
                this.ctx.font = '16px Arial';
                this.ctx.fillText('Loading track...', width / 2, height / 2);
            }
            return;
        }

        // Update pulsing track color every frame for smooth animation
        if (this.trackPulsing && this.baseTrackColor) {
            this.trackColor = this.getPulsingColor(this.baseTrackColor);
        }

        // Use cached bounds or calculate if not available
        if (!this.rotBounds) {
            this.calculateBaseScale();
        }
        if (!this.rotBounds) return; // Still no bounds, can't render

        const centerX = this.trackCenterX;
        const centerY = this.trackCenterY;
        const rotRad = this.rotation;
        const cos = Math.cos(rotRad);
        const sin = Math.sin(rotRad);

        const transform = (px, py) => {
            const dx = px - centerX;
            const dy = py - centerY;
            const rotX = dx * cos - dy * sin + centerX;
            const rotY = dx * sin + dy * cos + centerY;
            return { x: rotX, y: rotY };
        };

        const centerCanvasX = width / 2;
        const centerCanvasY = height / 2;

        let chaseCenterX = null;
        let chaseCenterY = null;

        // In chase mode, find the chased driver's position
        if (this.chaseMode && this.hasSessionData) {
            const positions = this.getDriversAtTime();
            const chasingDriver = positions.find(p => p.code === this.chaseMode);
            if (chasingDriver && !this.isDriverRetired(this.chaseMode)) {
                chaseCenterX = chasingDriver.x;
                chaseCenterY = chasingDriver.y;
            }
        }

        // Calculate scale and offset based on mode
        if (chaseCenterX !== null && chaseCenterY !== null) {
            // Chase mode: zoom centered on driver
            this.scale = this.baseScale * this.currentZoom;
            const chasedPos = transform(chaseCenterX, chaseCenterY);
            this.offsetX = centerCanvasX - chasedPos.x * this.scale;
            this.offsetY = centerCanvasY + chasedPos.y * this.scale;
        } else {
            // Overview mode: apply user zoom and pan
            this.scale = this.baseScale * this.userZoom;
            // Base centering + user pan offset
            this.offsetX = centerCanvasX - (this.rotBounds.centerX - this.panX) * this.scale;
            this.offsetY = centerCanvasY + (this.rotBounds.centerY + this.panY) * this.scale;
        }

        const screenTransform = (px, py) => {
            const p = transform(px, py);
            return {
                x: p.x * this.scale + this.offsetX,
                y: -p.y * this.scale + this.offsetY
            };
        };

        // Draw pit lane (skip in chase mode to reduce visual clutter)
        if (this.pitLaneData && !this.chaseMode) {
            this.ctx.strokeStyle = this.trackColor;
            this.ctx.globalAlpha = 0.3;
            this.ctx.lineWidth = 3;
            this.ctx.lineCap = 'round';
            this.ctx.lineJoin = 'round';
            this.ctx.shadowColor = this.trackColor;
            this.ctx.shadowBlur = 10;
            this.ctx.beginPath();
            let first = true;
            for (let i = 0; i < this.pitLaneData.x.length; i++) {
                const p = screenTransform(this.pitLaneData.x[i], this.pitLaneData.y[i]);
                if (first) {
                    this.ctx.moveTo(p.x, p.y);
                    first = false;
                } else {
                    this.ctx.lineTo(p.x, p.y);
                }
            }
            this.ctx.stroke();
        }

        // Reset context state after pit lane
        this.ctx.globalAlpha = 1.0;
        this.ctx.shadowColor = 'transparent';
        this.ctx.shadowBlur = 0;

        // Draw track with glow (handle sector-specific statuses)
        this.ctx.lineWidth = 3;
        this.ctx.lineCap = 'round';
        this.ctx.lineJoin = 'round';

        if (this.trackStatus.sectorStatuses && this.trackStatus.sectorStatuses.size > 0 && this.trackSectorMap) {
            // Track has sector data - draw with sector-based coloring
            let currentPath = [];
            let currentColor = this.trackColor;
            const firstPoint = screenTransform(this.trackData.x[0], this.trackData.y[0]);

            for (let i = 0; i < this.trackData.x.length; i++) {
                // O(1) lookup using pre-computed sector map
                const sectorNum = this.trackSectorMap[i];
                let newColor = this.trackColor;
                if (sectorNum && this.trackStatus.sectorStatuses.has(sectorNum)) {
                    const sectorStatus = this.trackStatus.sectorStatuses.get(sectorNum);
                    newColor = SECTOR_STATUS_COLORS[sectorStatus] || '#FFD700';
                }

                // Add point to current path
                const p = screenTransform(this.trackData.x[i], this.trackData.y[i]);

                // If color changed, draw the previous path and start new one
                if (newColor !== currentColor && currentPath.length > 0) {
                    this.ctx.strokeStyle = currentColor;
                    this.ctx.shadowColor = currentColor;
                    this.ctx.shadowBlur = 15;
                    this.ctx.beginPath();
                    for (let j = 0; j < currentPath.length; j++) {
                        const pt = currentPath[j];
                        if (j === 0) {
                            this.ctx.moveTo(pt.x, pt.y);
                        } else {
                            this.ctx.lineTo(pt.x, pt.y);
                        }
                    }
                    this.ctx.stroke();
                    // Start new path with the last point to avoid gaps
                    currentPath = [currentPath[currentPath.length - 1]];
                    currentColor = newColor;
                }

                currentPath.push(p);
            }

            // Close the loop: add first point to connect back
            currentPath.push(firstPoint);

            // Draw final path
            if (currentPath.length > 0) {
                this.ctx.strokeStyle = currentColor;
                this.ctx.shadowColor = currentColor;
                this.ctx.shadowBlur = 15;
                this.ctx.beginPath();
                for (let j = 0; j < currentPath.length; j++) {
                    const pt = currentPath[j];
                    if (j === 0) {
                        this.ctx.moveTo(pt.x, pt.y);
                    } else {
                        this.ctx.lineTo(pt.x, pt.y);
                    }
                }
                this.ctx.stroke();
            }
        } else {
            // No yellow sectors - draw entire track in one color
            this.ctx.shadowColor = this.trackColor;
            this.ctx.shadowBlur = 15;
            this.ctx.strokeStyle = this.trackColor;
            this.ctx.beginPath();

            // Collect track points
            let trackPoints = [];
            for (let i = 0; i < this.trackData.x.length; i++) {
                const p = screenTransform(this.trackData.x[i], this.trackData.y[i]);
                trackPoints.push(p);
            }

            // Apply spline smoothing for smoother curves at all zoom levels
            trackPoints = this.smoothPath(trackPoints);

            // Draw the track path
            let first = true;
            for (let i = 0; i < trackPoints.length; i++) {
                const p = trackPoints[i];
                if (first) {
                    this.ctx.moveTo(p.x, p.y);
                    first = false;
                } else {
                    this.ctx.lineTo(p.x, p.y);
                }
            }
            this.ctx.closePath();
            this.ctx.stroke();
        }

        this.ctx.shadowColor = 'transparent';

        // Draw start/finish line marker
        if (this.trackData && this.trackData.x.length > 0) {
            // Get first and second point to calculate perpendicular direction
            const p0 = screenTransform(this.trackData.x[0], this.trackData.y[0]);
            const p1 = screenTransform(this.trackData.x[1] !== undefined ? this.trackData.x[1] : this.trackData.x[0],
                                       this.trackData.y[1] !== undefined ? this.trackData.y[1] : this.trackData.y[0]);

            // Calculate direction vector
            const dx = p1.x - p0.x;
            const dy = p1.y - p0.y;
            const length = Math.sqrt(dx * dx + dy * dy);

            if (length > 0) {
                // Perpendicular vector (rotated 90 degrees)
                const perpX = -dy / length;
                const perpY = dx / length;
                const lineLength = 30;

                // Draw start/finish line (solid semi-transparent white)
                this.ctx.strokeStyle = 'rgba(255, 255, 255, 0.6)';
                this.ctx.lineWidth = 3;
                this.ctx.beginPath();
                this.ctx.moveTo(p0.x - perpX * lineLength / 2, p0.y - perpY * lineLength / 2);
                this.ctx.lineTo(p0.x + perpX * lineLength / 2, p0.y + perpY * lineLength / 2);
                this.ctx.stroke();
            }
        }

        // Draw drivers with glow (only if session data available)
        if (this.hasSessionData && this.drivers.length > 0) {
            const positions = this.getDriversAtTime();
            for (const pos of positions) {
                // Skip if driver is retired
                if (this.isDriverRetired(pos.code)) continue;

                const p = screenTransform(pos.x, pos.y);

                // Blue flag outline (before main glow so it's behind)
                if (this.blueFlagDrivers.has(pos.number)) {
                    this.ctx.strokeStyle = '#3399FF';
                    this.ctx.lineWidth = 3;
                    this.ctx.shadowColor = '#3399FF';
                    this.ctx.shadowBlur = 8;
                    this.ctx.beginPath();
                    this.ctx.arc(p.x, p.y, 12, 0, Math.PI * 2);
                    this.ctx.stroke();
                }

                // Driver glow effect
                this.ctx.shadowColor = pos.color;
                this.ctx.shadowBlur = 15;
                this.ctx.fillStyle = pos.color;
                this.ctx.beginPath();
                this.ctx.arc(p.x, p.y, 8, 0, Math.PI * 2);
                this.ctx.fill();

                // Inner dark circle for contrast
                this.ctx.shadowColor = 'transparent';
                this.ctx.fillStyle = 'rgba(0, 0, 0, 0.3)';
                this.ctx.beginPath();
                this.ctx.arc(p.x, p.y, 3, 0, Math.PI * 2);
                this.ctx.fill();

                // Driver number
                this.ctx.fillStyle = '#FFF';
                this.ctx.font = 'bold 9px Arial';
                this.ctx.textAlign = 'center';
                this.ctx.textBaseline = 'middle';
                this.ctx.fillText(pos.number, p.x, p.y);
            }
        }
    }

    formatTime(sec) {
        const h = Math.floor(sec / 3600);
        const m = Math.floor((sec % 3600) / 60);
        const s = Math.floor(sec % 60);
        return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
    }

    // Convert session_time to local time string (HH:MM:SS)
    sessionTimeToLocalTime(sessionTime) {
        const t0 = this.sessionData?.metadata?.t0;
        if (!t0?.utc) return '--:--:--';

        // t0.utc is when session_time = 0, add sessionTime seconds
        const t0Date = new Date(t0.utc);
        const targetUtc = new Date(t0Date.getTime() + sessionTime * 1000);

        // Add UTC offset to get local time
        const utcOffsetMs = (t0.utc_offset_hours || 0) * 3600 * 1000;
        const localTime = new Date(targetUtc.getTime() + utcOffsetMs);

        const h = localTime.getUTCHours();
        const m = localTime.getUTCMinutes();
        const s = localTime.getUTCSeconds();
        return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
    }

    startKnobDrag(e) {
        this.isDraggingKnob = true;
        document.getElementById('raceProgressKnob').classList.add('dragging');
        this.handleKnobDrag(e);
    }

    endKnobDrag() {
        if (this.isDraggingKnob) {
            this.isDraggingKnob = false;
            document.getElementById('raceProgressKnob').classList.remove('dragging');
        }
    }

    handleKnobDrag(e) {
        const duration = this.maxTime - this.minTime;
        if (!this.isDraggingKnob || duration <= 0) return;

        const track = document.getElementById('raceProgressTrack');
        const rect = track.getBoundingClientRect();
        const x = Math.max(0, Math.min(e.clientX - rect.left, rect.width));
        const fraction = x / rect.width;
        this.currentTime = this.minTime + fraction * duration;

        this.updateProgressBar();
        // Always rebuild track status from scratch when scrubbing
        this.rebuildTrackStatusSilently();
    }

    seekToClick(e) {
        const duration = this.maxTime - this.minTime;
        if (duration <= 0) return;

        const track = document.getElementById('raceProgressTrack');
        const rect = track.getBoundingClientRect();
        const x = Math.max(0, Math.min(e.clientX - rect.left, rect.width));
        const fraction = x / rect.width;
        this.currentTime = this.minTime + fraction * duration;

        this.updateProgressBar();
        // Always rebuild track status from scratch when seeking
        this.rebuildTrackStatusSilently();
    }

    updateProgressBar() {
        const duration = this.maxTime - this.minTime;
        if (duration <= 0) return;

        const fraction = Math.min(1, Math.max(0, (this.currentTime - this.minTime) / duration));
        const fillEl = document.getElementById('raceProgressFill');
        const knobEl = document.getElementById('raceProgressKnob');

        const percentage = fraction * 100;
        fillEl.style.width = percentage + '%';
        knobEl.style.left = percentage + '%';
    }

    // Rain animation system
    initRainSystem() {
        this.rainCanvas = document.getElementById('rainCanvas');
        if (this.rainCanvas) {
            this.rainCtx = this.rainCanvas.getContext('2d');
            this.resizeRainCanvas();
        }
    }

    resizeRainCanvas() {
        if (!this.rainCanvas || !this.rainCanvas.parentElement) return;
        const rect = this.rainCanvas.parentElement.getBoundingClientRect();
        const dpr = window.devicePixelRatio || 1;
        this.rainCanvas.width = rect.width * dpr;
        this.rainCanvas.height = rect.height * dpr;
        this.rainCanvas.style.width = rect.width + 'px';
        this.rainCanvas.style.height = rect.height + 'px';
        if (this.rainCtx) {
            this.rainCtx.scale(dpr, dpr);
        }
    }

    createRainDrop() {
        const width = this.rainCanvas ? this.rainCanvas.width / (window.devicePixelRatio || 1) : 800;
        return {
            x: Math.random() * (width + 150),  // Start across full width + buffer
            y: Math.random() * -150,  // Start above screen
            length: 12 + Math.random() * 18,  // Drop length 12-30px
            speed: 6 + Math.random() * 5,  // Fall speed
            opacity: 0.15 + Math.random() * 0.25  // Subtle opacity 0.15-0.4
        };
    }

    updateRain() {
        if (!this.rainCanvas || !this.rainCtx) return;

        if (!this.rainActive) {
            this.rainCanvas.classList.remove('active');
            return;
        }

        this.rainCanvas.classList.add('active');

        const width = this.rainCanvas.width / (window.devicePixelRatio || 1);
        const height = this.rainCanvas.height / (window.devicePixelRatio || 1);

        // Maintain ~80 drops
        while (this.rainDrops.length < 80) {
            this.rainDrops.push(this.createRainDrop());
        }

        // Clear canvas
        this.rainCtx.clearRect(0, 0, width, height);

        // Draw and update drops
        for (let i = this.rainDrops.length - 1; i >= 0; i--) {
            const drop = this.rainDrops[i];

            // Draw drop (diagonal line with subtle shine)
            this.rainCtx.beginPath();
            this.rainCtx.strokeStyle = `rgba(180, 200, 230, ${drop.opacity})`;
            this.rainCtx.lineWidth = 1;
            this.rainCtx.lineCap = 'round';
            this.rainCtx.moveTo(drop.x, drop.y);
            this.rainCtx.lineTo(drop.x - drop.length * 0.4, drop.y + drop.length);
            this.rainCtx.stroke();

            // Update position (diagonal: down and slightly left)
            drop.x -= drop.speed * 0.4;
            drop.y += drop.speed;

            // Reset if off screen
            if (drop.y > height + 20 || drop.x < -50) {
                this.rainDrops[i] = this.createRainDrop();
            }
        }
    }

    animate() {
        const now = Date.now();
        const deltaTime = (now - this.lastFrameTime) / 1000;
        this.lastFrameTime = now;

        // Session-dependent operations (only when Tier 3 loaded)
        if (this.hasSessionData) {
            if (this.isPlaying) {
                this.previousTime = this.currentTime;
                this.currentTime += deltaTime * this.playSpeed;
                if (this.currentTime > this.maxTime) {
                    this.currentTime = this.maxTime;
                    this.isPlaying = false;
                    document.getElementById('playPauseBtn').textContent = '▶';
                }
            } else {
                // Even when paused, track previousTime for selector changes
                if (this.previousTime === -Infinity) {
                    this.previousTime = this.currentTime;
                }
            }

            // Show timer: countdown for qualifying, count-up for race
            const timerEl = document.getElementById('raceTimer');
            if (this.isQualifying && this.qualifyingManager) {
                const qm = this.qualifyingManager;
                document.getElementById('lapCounter').textContent = qm.getPhaseLabel(this.currentTime);
                if (qm.isIntermission(this.currentTime)) {
                    timerEl.textContent = '--:--';
                    timerEl.style.color = '';
                } else {
                    const countdown = qm.getCountdown(this.currentTime);
                    timerEl.textContent = this.formatCountdown(Math.max(0, countdown));
                    if (qm.isChequered(this.currentTime)) {
                        timerEl.style.color = '#FFD700';
                    } else if (countdown <= 60) {
                        timerEl.style.color = '#FF4444';
                    } else {
                        timerEl.style.color = '';
                    }
                }
            } else if (this.currentTime < this.lightsOutTime) {
                // Pre-race: show local time
                timerEl.textContent = this.sessionTimeToLocalTime(this.currentTime);
            } else {
                timerEl.textContent = this.formatTime(this.currentTime - this.lightsOutTime);
            }

            // Update progress bar (only when not dragging)
            if (!this.isDraggingKnob) {
                this.updateProgressBar();
            }

            // Update track status (logs only when status changes)
            this.updateTrackStatus();
            this.updateStartingLights();

            this.updateStandings();
            this.updateTrackColor();

            // Update strategy markers if visible
            if (this.strategyView) this.updateStrategyMarkers();

            // Update lap chart if visible (throttled)
            if (this.lapChartVisible) {
                if (!this._lastLapChartUpdate || now - this._lastLapChartUpdate > 500) {
                    this.renderLapChart();
                    this._lastLapChartUpdate = now;
                }
            }
        }

        // Always render (track-only or full)
        this.render();

        // Update rain animation
        this.updateRain();

        requestAnimationFrame(() => this.animate());
    }
}
