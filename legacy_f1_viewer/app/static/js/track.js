/**
 * F1 Viewer - Track Renderer
 * Renders the race track on a full screen canvas
 */

class TrackRenderer {
    constructor() {
        this.canvas = document.getElementById('trackCanvas');
        this.ctx = this.canvas.getContext('2d');
        this.trackData = null;
        this.pitLaneData = null;  // Pit lane coordinates
        this.drivers = [];

        // Styling
        this.trackColor = '#FFFFFF';
        this.baseTrackColor = '#FFFFFF'; // Store original color
        this.trackWidth = 3;
        this.trackGlow = true;

        // Track status for flashing effect
        this.currentStatus = '1';
        this.flashState = true;
        this.flashInterval = null;

        // Transform data (for coordinate conversion)
        this.bounds = null;
        this.scale = 1;
        this.offsetX = 0;
        this.offsetY = 0;

        // Track rotation (degrees, clockwise)
        this.rotation = 0;
        this.allowRotation = false; // Fine rotation control with up/down keys
        this.rotationIndicatorTimeout = null;
        this.cachedRotation = null; // For caching rotated bounds
        this.cachedRotatedBounds = null;

        // Marshal sectors for sector-based yellow flag highlighting
        this.marshalSectors = [];
        this.sectorPointCache = {}; // Cached point indices per sector for performance

        // Yellow flag sectors currently active (sector numbers)
        this.yellowFlagSectors = new Set();
        this.doubleYellowSectors = new Set();

        // Fastest lap holder (driver code who currently has the fastest lap)
        this.fastestLapHolder = null;

        // Race info (for track name and rotation)
        this.raceInfo = null;

        // Initialize
        this.setupCanvas();
        this.loadInitialData();

        // Handle window resize
        window.addEventListener('resize', () => this.handleResize());

        // Keyboard controls for rotation
        window.addEventListener('keydown', (e) => this.handleKeyDown(e));
    }

    async loadInitialData() {
        try {
            // Load race info FIRST to get rotation and marshal sectors
            const infoResponse = await fetch('/api/race_info');
            this.raceInfo = await infoResponse.json();

            // Use rotation from circuit info (from FastF1)
            if (this.raceInfo.rotation !== undefined) {
                this.rotation = this.raceInfo.rotation;
                console.log(`Applied circuit rotation: ${this.rotation}°`);
            }

            // Store marshal sectors for sector-based yellow flag highlighting
            if (this.raceInfo.marshal_sectors) {
                this.marshalSectors = this.raceInfo.marshal_sectors;
                console.log(`Loaded ${this.marshalSectors.length} marshal sectors:`, this.marshalSectors.map(s => `${s.number}@${s.distance.toFixed(0)}m`).join(', '));
            } else {
                console.warn('No marshal sectors in race info!');
            }

            // Load track data and pit lane data in parallel
            await Promise.all([
                this.loadTrackData(),
                this.loadPitLaneData()
            ]);
        } catch (error) {
            console.error('Failed to load initial data:', error);
            // Fallback: try to load track data anyway
            this.loadTrackData();
        }
    }

    async loadPitLaneData() {
        try {
            const response = await fetch('/api/pit_lane');
            const data = await response.json();

            if (data.available) {
                this.pitLaneData = data;
                console.log(`Pit lane loaded: ${data.x.length} points`);
                // Re-render if track is already loaded to show pit lane immediately
                if (this.trackData) {
                    this.render();
                }
            } else {
                this.pitLaneData = null;
                console.log('Pit lane data not available for this race');
            }
        } catch (error) {
            console.error('Failed to load pit lane data:', error);
            this.pitLaneData = null;
        }
    }

    setTrackStatus(status) {
        // Only update if status changed
        if (this.currentStatus === status) return;

        this.currentStatus = status;

        // Clear any existing flash interval
        if (this.flashInterval) {
            clearInterval(this.flashInterval);
            this.flashInterval = null;
        }

        // Set track color based on status
        // Status codes: '1'=AllClear, '2'=Yellow, '4'=SafetyCar, '5'=Red, '6'=VSC, '7'=VSCEnding
        switch (status) {
            case '5': // RED FLAG
                this.trackColor = '#FF0000';
                // Clear sector flags on red flag (whole track is red)
                this.yellowFlagSectors.clear();
                this.doubleYellowSectors.clear();
                this.render();
                break;
            case '4': // Safety Car - solid yellow (whole track)
                this.trackColor = '#FFD700';
                this.yellowFlagSectors.clear();
                this.doubleYellowSectors.clear();
                this.render();
                break;
            case '6': // Virtual Safety Car - flashing yellow
                this.flashState = true;
                this.flashInterval = setInterval(() => {
                    this.flashState = !this.flashState;
                    this.trackColor = this.flashState ? '#FFD700' : '#FFFFFF';
                    this.render();
                }, 500); // Flash every 500ms
                break;
            case '7': // VSC Ending - slow flash back to normal
                this.flashState = true;
                this.flashInterval = setInterval(() => {
                    this.flashState = !this.flashState;
                    this.trackColor = this.flashState ? '#FFD700' : '#FFFFFF';
                    this.render();
                }, 250); // Faster flash for ending
                break;
            case '2': // Yellow flag - handled via sector flags now
                // Don't change whole track color for local yellows
                this.render();
                break;
            case '1': // All Clear (Green)
            default:
                this.trackColor = '#FFFFFF';
                // Clear all sector flags
                this.yellowFlagSectors.clear();
                this.doubleYellowSectors.clear();
                this.render();
                break;
        }
    }

    setYellowFlagSector(sectorNumber, isDouble = false) {
        // Set a sector as having yellow/double yellow flag
        if (isDouble) {
            this.doubleYellowSectors.add(sectorNumber);
            this.yellowFlagSectors.delete(sectorNumber); // Double replaces single
        } else {
            this.yellowFlagSectors.add(sectorNumber);
        }
        this.render();
    }

    clearYellowFlagSector(sectorNumber) {
        // Clear yellow flag from a sector
        this.yellowFlagSectors.delete(sectorNumber);
        this.doubleYellowSectors.delete(sectorNumber);
        this.render();
    }

    clearAllYellowFlags() {
        // Clear all sector yellow flags
        this.yellowFlagSectors.clear();
        this.doubleYellowSectors.clear();
        this.render();
    }

    setFastestLapHolder(driverCode) {
        // Set the driver who currently has the fastest lap
        if (this.fastestLapHolder !== driverCode) {
            this.fastestLapHolder = driverCode;
            this.render();
        }
    }

    updateDrivers(drivers) {
        this.drivers = drivers;
        this.render();
    }

    setupCanvas() {
        // Set canvas size to match window
        this.canvas.width = window.innerWidth;
        this.canvas.height = window.innerHeight;

        // Enable high DPI rendering
        const dpr = window.devicePixelRatio || 1;
        const rect = this.canvas.getBoundingClientRect();

        this.canvas.width = rect.width * dpr;
        this.canvas.height = rect.height * dpr;
        this.ctx.scale(dpr, dpr);

        // Set canvas display size
        this.canvas.style.width = rect.width + 'px';
        this.canvas.style.height = rect.height + 'px';
    }

    async loadTrackData() {
        try {
            const response = await fetch('/api/track');
            const data = await response.json();

            if (data.error) {
                console.error('Error loading track:', data.error);
                return;
            }

            this.trackData = data;
            console.log(`Track loaded: ${data.x.length} points, distance: ${data.distance ? `${Math.max(...data.distance).toFixed(0)}m` : 'NOT AVAILABLE'}`);

            // Pre-calculate sector point indices for yellow flag rendering
            this.cacheSectorPoints();

            this.render();

        } catch (error) {
            console.error('Failed to load track data:', error);
        }
    }

    cacheSectorPoints() {
        // Pre-calculate which track points belong to each marshal sector
        // This avoids expensive recalculation every frame
        this.sectorPointCache = {};

        if (!this.trackData || !this.trackData.distance || this.marshalSectors.length === 0) {
            return;
        }

        const distance = this.trackData.distance;
        const maxDistance = Math.max(...distance);

        // Sort marshal sectors by distance
        const sortedSectors = [...this.marshalSectors].sort((a, b) => a.distance - b.distance);

        for (let sectorIdx = 0; sectorIdx < sortedSectors.length; sectorIdx++) {
            const sector = sortedSectors[sectorIdx];
            const sectorStart = sector.distance;
            const sectorEnd = sectorIdx < sortedSectors.length - 1
                ? sortedSectors[sectorIdx + 1].distance
                : maxDistance + sortedSectors[0].distance; // Wrap around

            // Find point indices in this sector
            const pointIndices = [];
            for (let i = 0; i < distance.length; i++) {
                const d = distance[i];
                if (sectorEnd > maxDistance) {
                    // Handle wrap-around for last sector
                    if (d >= sectorStart || d <= (sectorEnd - maxDistance)) {
                        pointIndices.push(i);
                    }
                } else {
                    if (d >= sectorStart && d <= sectorEnd) {
                        pointIndices.push(i);
                    }
                }
            }

            // Sort by index to maintain track order
            pointIndices.sort((a, b) => a - b);
            this.sectorPointCache[sector.number] = pointIndices;
        }

        console.log(`Cached sector points for ${Object.keys(this.sectorPointCache).length} sectors`);
    }

    calculateBounds() {
        if (!this.trackData) return null;

        const x = this.trackData.x;
        const y = this.trackData.y;

        // Use loops instead of Math.max(...array) - much faster for large arrays
        let minX = x[0], maxX = x[0];
        let minY = y[0], maxY = y[0];
        for (let i = 1; i < x.length; i++) {
            if (x[i] < minX) minX = x[i];
            if (x[i] > maxX) maxX = x[i];
            if (y[i] < minY) minY = y[i];
            if (y[i] > maxY) maxY = y[i];
        }

        // Include pit lane in bounds calculation so it's always visible
        if (this.pitLaneData && this.pitLaneData.x && this.pitLaneData.x.length > 0) {
            const px = this.pitLaneData.x;
            const py = this.pitLaneData.y;
            for (let i = 0; i < px.length; i++) {
                if (px[i] < minX) minX = px[i];
                if (px[i] > maxX) maxX = px[i];
                if (py[i] < minY) minY = py[i];
                if (py[i] > maxY) maxY = py[i];
            }
        }

        const width = maxX - minX;
        const height = maxY - minY;

        return { minX, maxX, minY, maxY, width, height };
    }

    render() {
        if (!this.trackData) return;

        // Clear canvas
        this.ctx.fillStyle = '#000000';
        this.ctx.fillRect(0, 0, this.canvas.width, this.canvas.height);

        this.bounds = this.calculateBounds();
        if (!this.bounds) return;

        // Track center point (for rotation)
        const centerX = (this.bounds.minX + this.bounds.maxX) / 2;
        const centerY = (this.bounds.minY + this.bounds.maxY) / 2;

        // Rotation in radians (negative because we want clockwise rotation)
        const rotationRad = -this.rotation * Math.PI / 180;
        const cosR = Math.cos(rotationRad);
        const sinR = Math.sin(rotationRad);

        const x = this.trackData.x;
        const y = this.trackData.y;

        // Use cached rotated bounds if rotation hasn't changed (expensive to recalculate)
        let rotMinX, rotMaxX, rotMinY, rotMaxY;
        if (this.cachedRotation === this.rotation && this.cachedRotatedBounds) {
            ({ rotMinX, rotMaxX, rotMinY, rotMaxY } = this.cachedRotatedBounds);
        } else {
            // Calculate rotated bounds to properly fit the track (including pit lane)
            rotMinX = Infinity; rotMaxX = -Infinity;
            rotMinY = Infinity; rotMaxY = -Infinity;

            // Helper to update rotated bounds
            const updateRotatedBounds = (px, py) => {
                const dx = px - centerX;
                const dy = py - centerY;
                const rotX = dx * cosR - dy * sinR + centerX;
                const rotY = dx * sinR + dy * cosR + centerY;

                if (rotX < rotMinX) rotMinX = rotX;
                if (rotX > rotMaxX) rotMaxX = rotX;
                if (rotY < rotMinY) rotMinY = rotY;
                if (rotY > rotMaxY) rotMaxY = rotY;
            };

            // Include track points
            for (let i = 0; i < x.length; i++) {
                updateRotatedBounds(x[i], y[i]);
            }

            // Include pit lane points in rotated bounds
            if (this.pitLaneData && this.pitLaneData.x) {
                for (let i = 0; i < this.pitLaneData.x.length; i++) {
                    updateRotatedBounds(this.pitLaneData.x[i], this.pitLaneData.y[i]);
                }
            }

            // Cache the results
            this.cachedRotation = this.rotation;
            this.cachedRotatedBounds = { rotMinX, rotMaxX, rotMinY, rotMaxY };
        }

        const rotatedWidth = rotMaxX - rotMinX;
        const rotatedHeight = rotMaxY - rotMinY;

        // Calculate scaling to fit rotated track in viewport with padding
        // Account for sidebar (320px + 20px margin on left) and title at top
        const sidebarWidth = 360;
        const paddingX = 60;     // horizontal padding
        const paddingTop = 100;  // top padding for race title
        const paddingBottom = 60;
        const availableWidth = window.innerWidth - sidebarWidth - (paddingX * 2);
        const availableHeight = window.innerHeight - paddingTop - paddingBottom;

        const scaleX = availableWidth / rotatedWidth;
        const scaleY = availableHeight / rotatedHeight;
        this.scale = Math.min(scaleX, scaleY);

        // Calculate offset to center the rotated track in the available area
        const trackAreaCenterX = sidebarWidth + (window.innerWidth - sidebarWidth) / 2;
        const trackAreaCenterY = paddingTop + availableHeight / 2;
        this.offsetX = trackAreaCenterX - (rotMinX + rotatedWidth / 2) * this.scale;
        this.offsetY = trackAreaCenterY + (rotMaxY - rotatedHeight / 2) * this.scale;

        // Store rotation params for driver position transforms
        this.rotationParams = { centerX, centerY, cosR, sinR };

        // Transform function to convert track coordinates to canvas coordinates
        // Applies rotation around track center, then scales and translates
        const transform = (px, py) => {
            // Rotate around track center
            const dx = px - centerX;
            const dy = py - centerY;
            const rotX = dx * cosR - dy * sinR + centerX;
            const rotY = dx * sinR + dy * cosR + centerY;

            // Scale and translate (Y-axis flipped for canvas)
            return {
                x: rotX * this.scale + this.offsetX,
                y: -rotY * this.scale + this.offsetY
            };
        };

        // Draw pit lane first (so it appears behind the main track)
        this.drawPitLane(transform);

        // Draw the track with glow effect
        if (this.trackGlow) {
            // Draw glow (outer shadow)
            this.ctx.shadowColor = this.trackColor;
            this.ctx.shadowBlur = 15;
            this.ctx.shadowOffsetX = 0;
            this.ctx.shadowOffsetY = 0;
        }

        // Draw track outline
        this.ctx.strokeStyle = this.trackColor;
        this.ctx.lineWidth = this.trackWidth;
        this.ctx.lineCap = 'round';
        this.ctx.lineJoin = 'round';

        this.ctx.beginPath();

        // Start at first point (x, y already defined above)
        const firstPoint = transform(x[0], y[0]);
        this.ctx.moveTo(firstPoint.x, firstPoint.y);

        // Draw lines to all other points
        for (let i = 1; i < x.length; i++) {
            const point = transform(x[i], y[i]);
            this.ctx.lineTo(point.x, point.y);
        }

        // Close the path to connect back to start
        this.ctx.closePath();
        this.ctx.stroke();

        // Reset shadow for subsequent drawing
        this.ctx.shadowBlur = 0;

        // Draw yellow flag sectors on top of track
        this.drawYellowFlagSectors(transform);

        // Draw start/finish line indicator
        // Calculate track direction at start to draw perpendicular line
        const startPoint = transform(x[0], y[0]);
        const nextPoint = transform(x[1], y[1]);
        this.drawStartFinish(startPoint, nextPoint);

        // Draw drivers
        this.drawDrivers();
    }

    drawYellowFlagSectors(transform) {
        // Skip if no cached sector points
        if (!this.sectorPointCache || Object.keys(this.sectorPointCache).length === 0) {
            return;
        }

        // Skip if no yellow flags active
        if (this.yellowFlagSectors.size === 0 && this.doubleYellowSectors.size === 0) {
            return;
        }

        const x = this.trackData.x;
        const y = this.trackData.y;

        // Draw each flagged sector using cached point indices
        for (const sectorNum of this.yellowFlagSectors) {
            this.drawSectorOverlay(sectorNum, x, y, transform, false);
        }
        for (const sectorNum of this.doubleYellowSectors) {
            this.drawSectorOverlay(sectorNum, x, y, transform, true);
        }
    }

    drawSectorOverlay(sectorNum, x, y, transform, isDouble) {
        const pointIndices = this.sectorPointCache[sectorNum];
        if (!pointIndices || pointIndices.length < 2) {
            return;
        }

        // Draw yellow overlay using cached indices - no shadow for performance
        this.ctx.save();
        this.ctx.strokeStyle = isDouble ? '#FFAA00' : '#FFD700'; // Brighter orange for double
        this.ctx.lineWidth = this.trackWidth + 2;
        this.ctx.lineCap = 'round';
        this.ctx.lineJoin = 'round';

        this.ctx.beginPath();
        const firstIdx = pointIndices[0];
        const first = transform(x[firstIdx], y[firstIdx]);
        this.ctx.moveTo(first.x, first.y);

        // Use stride to reduce points drawn (every 2nd point is enough for visual)
        const stride = pointIndices.length > 100 ? 2 : 1;
        for (let i = stride; i < pointIndices.length; i += stride) {
            const idx = pointIndices[i];
            const pt = transform(x[idx], y[idx]);
            this.ctx.lineTo(pt.x, pt.y);
        }

        // Ensure we draw to the last point
        if (stride > 1) {
            const lastIdx = pointIndices[pointIndices.length - 1];
            const last = transform(x[lastIdx], y[lastIdx]);
            this.ctx.lineTo(last.x, last.y);
        }

        this.ctx.stroke();
        this.ctx.restore();
    }

    drawDrivers() {
        if (!this.drivers || this.drivers.length === 0) return;

        for (const driver of this.drivers) {
            // Don't draw DNF cars on track
            if (driver.isDNF) continue;

            if (!driver.x || !driver.y) continue;

            // Transform driver position to canvas coordinates with rotation
            let posX = driver.x;
            let posY = driver.y;

            // Apply rotation if we have rotation params
            if (this.rotationParams) {
                const { centerX, centerY, cosR, sinR } = this.rotationParams;
                const dx = driver.x - centerX;
                const dy = driver.y - centerY;
                posX = dx * cosR - dy * sinR + centerX;
                posY = dx * sinR + dy * cosR + centerY;
            }

            const pos = {
                x: posX * this.scale + this.offsetX,
                y: -posY * this.scale + this.offsetY
            };

            // Draw driver circle
            const radius = 8;

            // Outer glow with team color
            this.ctx.shadowColor = driver.color;
            this.ctx.shadowBlur = 15;

            // Circle with team color
            this.ctx.fillStyle = driver.color;
            this.ctx.beginPath();
            this.ctx.arc(pos.x, pos.y, radius, 0, Math.PI * 2);
            this.ctx.fill();

            // Inner circle (darker center for contrast)
            this.ctx.shadowBlur = 0;
            this.ctx.fillStyle = 'rgba(0, 0, 0, 0.3)';
            this.ctx.beginPath();
            this.ctx.arc(pos.x, pos.y, radius * 0.4, 0, Math.PI * 2);
            this.ctx.fill();
        }

        // Reset shadow
        this.ctx.shadowBlur = 0;
    }

    drawPitLane(transform) {
        if (!this.pitLaneData || !this.pitLaneData.x || this.pitLaneData.x.length < 2) {
            return;
        }

        const x = this.pitLaneData.x;
        const y = this.pitLaneData.y;

        // Draw pit lane with same style as track but 30% transparency
        this.ctx.save();
        this.ctx.globalAlpha = 0.3;  // 30% opacity

        // Same glow effect as main track
        if (this.trackGlow) {
            this.ctx.shadowColor = this.trackColor;
            this.ctx.shadowBlur = 15;
            this.ctx.shadowOffsetX = 0;
            this.ctx.shadowOffsetY = 0;
        }

        // Same styling as main track
        this.ctx.strokeStyle = this.trackColor;
        this.ctx.lineWidth = this.trackWidth;
        this.ctx.lineCap = 'round';
        this.ctx.lineJoin = 'round';

        this.ctx.beginPath();

        // Start at first point
        const firstPoint = transform(x[0], y[0]);
        this.ctx.moveTo(firstPoint.x, firstPoint.y);

        // Draw lines to all other points
        for (let i = 1; i < x.length; i++) {
            const point = transform(x[i], y[i]);
            this.ctx.lineTo(point.x, point.y);
        }

        this.ctx.stroke();

        // Reset context
        this.ctx.restore();
    }

    drawStartFinish(startPoint, nextPoint) {
        // Calculate track direction vector
        const dx = nextPoint.x - startPoint.x;
        const dy = nextPoint.y - startPoint.y;
        const length = Math.sqrt(dx * dx + dy * dy);

        // Normalize direction
        const dirX = dx / length;
        const dirY = dy / length;

        // Calculate perpendicular vector (rotate 90 degrees)
        const perpX = -dirY;
        const perpY = dirX;

        // Line length across track (12 pixels on each side - 60% of original)
        const lineLength = 12;

        // Calculate line endpoints
        const x1 = startPoint.x - perpX * lineLength;
        const y1 = startPoint.y - perpY * lineLength;
        const x2 = startPoint.x + perpX * lineLength;
        const y2 = startPoint.y + perpY * lineLength;

        // Draw white line with glow (reduced size)
        this.ctx.shadowColor = '#FFFFFF';
        this.ctx.shadowBlur = 10;
        this.ctx.strokeStyle = '#FFFFFF';
        this.ctx.lineWidth = 2.5;
        this.ctx.lineCap = 'round';

        this.ctx.beginPath();
        this.ctx.moveTo(x1, y1);
        this.ctx.lineTo(x2, y2);
        this.ctx.stroke();

        // Reset shadow
        this.ctx.shadowBlur = 0;
    }

    handleResize() {
        this.setupCanvas();
        this.render();
    }

    handleKeyDown(e) {
        // R = rotate clockwise 15°, Shift+R = rotate counter-clockwise 15°
        if (e.key === 'r' || e.key === 'R') {
            const delta = e.shiftKey ? -15 : 15;
            this.setRotation(this.rotation + delta, true);
        }

        // Fine rotation control with up/down arrows (only when allowRotation is enabled)
        if (this.allowRotation) {
            if (e.key === 'ArrowUp') {
                e.preventDefault();
                this.setRotation(this.rotation + 0.5, true);
            } else if (e.key === 'ArrowDown') {
                e.preventDefault();
                this.setRotation(this.rotation - 0.5, true);
            }
        }
    }

    setRotation(degrees, showIndicator = false) {
        this.rotation = degrees % 360;
        console.log(`Track rotation: ${this.rotation}°`);
        this.render();

        // Show brief rotation indicator
        if (showIndicator) {
            this.showRotationIndicator();
        }
    }

    showRotationIndicator() {
        // Clear any existing timeout
        if (this.rotationIndicatorTimeout) {
            clearTimeout(this.rotationIndicatorTimeout);
        }

        // Get or create the indicator element
        let indicator = document.getElementById('rotationIndicator');
        if (!indicator) {
            indicator = document.createElement('div');
            indicator.id = 'rotationIndicator';
            indicator.className = 'rotation-indicator';
            document.body.appendChild(indicator);
        }

        // Update and show
        indicator.textContent = `${this.rotation.toFixed(1)}°`;
        indicator.classList.add('visible');

        // Hide after 1.5 seconds
        this.rotationIndicatorTimeout = setTimeout(() => {
            indicator.classList.remove('visible');
        }, 1500);
    }

    setRotation(rotation) {
        // Set rotation directly (from API circuit info)
        this.rotation = rotation;
        console.log(`Applied circuit rotation: ${rotation}°`);
        if (this.trackData) {
            this.render();
        }
    }
}

/**
 * Race Controller - Manages race timing, standings, and live updates
 */
class RaceController {
    constructor(trackRenderer) {
        this.trackRenderer = trackRenderer;
        this.telemetryData = null;
        this.raceInfo = null;
        this.currentTime = 0;
        this.isPlaying = false;
        this.startTime = null;

        // Playback speed (1x = real time)
        this.playbackSpeed = 1;

        // Delta-based timing
        this.lastFrameTime = null;

        // DOM elements
        this.raceTimerEl = document.getElementById('raceTimer');
        this.lapCounterEl = document.getElementById('lapCounter');
        this.standingsEl = document.getElementById('standings');
        this.raceMessagesEl = document.getElementById('raceMessages');
        this.speedSelectorEl = document.getElementById('speedSelector');
        this.speedDropdownEl = document.getElementById('speedDropdown');
        this.speedValueEl = this.speedSelectorEl.querySelector('.speed-value');
        this.playPauseBtnEl = document.getElementById('playPauseBtn');

        // Track status and messages
        this.trackStatus = [];
        this.raceControlMessages = [];
        this.currentTrackStatus = '1'; // Default to AllClear
        this.displayedMessageIds = new Set();
        this.previousTime = 0; // Track previous frame time for message detection

        // Playback state
        this.isPaused = false;

        // Input state
        this.isEditingTime = false;
        this.isEditingLap = false;

        // Click handlers for timer and lap counter
        this.raceTimerEl.addEventListener('click', () => this.showTimeInput());
        this.lapCounterEl.addEventListener('click', () => this.showLapInput());

        // Play/pause handler
        this.playPauseBtnEl.addEventListener('click', () => this.togglePlayPause());

        // Speed selector handlers
        this.speedSelectorEl.addEventListener('click', (e) => this.toggleSpeedDropdown(e));
        this.speedDropdownEl.addEventListener('click', (e) => this.selectSpeed(e));
        document.addEventListener('click', (e) => this.closeSpeedDropdown(e));

        // Load data and start
        this.init();
    }

    async init() {
        try {
            // Load race info
            const infoResponse = await fetch('/api/race_info');
            this.raceInfo = await infoResponse.json();

            // Set track rotation from circuit info (provided by FastF1)
            if (this.trackRenderer && this.raceInfo.rotation !== undefined) {
                this.trackRenderer.setRotation(this.raceInfo.rotation);
            }

            // Enable fine rotation control if allowed
            if (this.trackRenderer && this.raceInfo.allow_rotation) {
                this.trackRenderer.allowRotation = true;
                console.log('Fine rotation control enabled (use Up/Down arrow keys for 0.5° adjustments)');
            }

            // Parse t0_date for local time conversion
            // t0_date from FastF1 is UTC, so we need to parse it as UTC
            if (this.raceInfo.t0_date) {
                // Convert "2024-05-26 12:08:05.389000" to ISO format with Z suffix for UTC
                const t0String = this.raceInfo.t0_date.replace(' ', 'T') + 'Z';
                this.t0Date = new Date(t0String);
                this.gmtOffset = this.raceInfo.gmt_offset || 0; // Timezone offset in seconds
                // global_min_time is the offset subtracted from telemetry times during processing
                // We need to add it back when converting normalized time to actual time
                this.globalMinTime = this.raceInfo.global_min_time || 0;
                console.log(`Time reference (UTC): ${this.t0Date.toISOString()}, Track GMT offset: ${this.gmtOffset / 3600}h, Global min time: ${this.globalMinTime}s`);
            }

            // Load telemetry
            const telemetryResponse = await fetch('/api/telemetry');
            this.telemetryData = await telemetryResponse.json();

            // Load track status
            const statusResponse = await fetch('/api/track_status');
            this.trackStatus = await statusResponse.json();
            // Normalize track status times by subtracting globalMinTime
            // This aligns them with the normalized telemetry timeline
            for (const status of this.trackStatus) {
                status.time -= (this.globalMinTime || 0);
            }

            // Load race control messages
            const messagesResponse = await fetch('/api/race_control');
            this.raceControlMessages = await messagesResponse.json();
            // Normalize race control message times
            for (const msg of this.raceControlMessages) {
                msg.time -= (this.globalMinTime || 0);
            }

            // Load weather data
            const weatherResponse = await fetch('/api/weather');
            this.weatherData = await weatherResponse.json();
            // Normalize weather data times
            for (const w of this.weatherData) {
                w.time -= (this.globalMinTime || 0);
            }

            // Load fastest lap history
            const fastestLapResponse = await fetch('/api/fastest_lap_history');
            this.fastestLapHistory = await fastestLapResponse.json();
            // Normalize fastest lap times
            for (const fl of this.fastestLapHistory) {
                fl.time -= (this.globalMinTime || 0);
            }

            // Load interval data (gaps to leader and car ahead)
            const intervalResponse = await fetch('/api/intervals');
            this.intervalData = await intervalResponse.json();
            // Normalize interval data times
            for (const iv of this.intervalData) {
                iv.time -= (this.globalMinTime || 0);
            }
            // Create a map for quick lookup by driver and lap
            this.intervalMap = new Map();
            for (const iv of this.intervalData) {
                const key = `${iv.driver}_${iv.lap_number}`;
                this.intervalMap.set(key, iv);
            }

            // Weather indicator element
            this.weatherIndicatorEl = document.getElementById('weatherIndicator');
            this.isRaining = false;

            // Current fastest lap holder
            this.currentFastestLapHolder = null;
            this.displayedFastestLaps = new Set();

            // Active fastest lap highlight (shows lap time and bold for 5 seconds)
            this.fastestLapHighlight = null; // { driver, lapTimeStr, timeoutId }

            // Position change tracking for UI indicators
            this.previousPositions = {}; // { driverCode: position }
            this.positionChanges = {}; // { driverCode: { direction: 'up'|'down', positions: number, time: timestamp } }

            // Load precalculated position history (includes standings and intervals)
            const positionHistoryResponse = await fetch('/api/position_history');
            this.positionHistory = await positionHistoryResponse.json();
            // Normalize position history times
            for (const snapshot of this.positionHistory) {
                snapshot.time -= (this.globalMinTime || 0);
            }
            console.log(`Loaded ${this.positionHistory.length} position history snapshots (with intervals)`);

            console.log('Race data loaded:', {
                drivers: Object.keys(this.telemetryData).length,
                totalLaps: this.raceInfo.total_laps,
                trackLength: this.raceInfo.track_length,
                trackStatusEvents: this.trackStatus.length,
                raceControlMessages: this.raceControlMessages.length
            });

            // Debug: Check if Distance is cumulative or per-lap
            const firstDriver = Object.keys(this.telemetryData)[0];
            const firstDriverData = this.telemetryData[firstDriver];
            if (firstDriverData.telemetry.Distance) {
                const maxDistance = Math.max(...firstDriverData.telemetry.Distance);
                console.log('Distance field info:', {
                    driver: firstDriver,
                    maxDistance: maxDistance,
                    trackLength: this.raceInfo.track_length,
                    isCumulative: maxDistance > this.raceInfo.track_length
                });
            }

            // Log track status events
            if (this.trackStatus.length > 0) {
                console.log('Track status events:', this.trackStatus);
            }

            // Log first few race control messages
            if (this.raceControlMessages.length > 0) {
                console.log('First 5 race control messages:', this.raceControlMessages.slice(0, 5));
            }

            // Start the race simulation
            this.start();

        } catch (error) {
            console.error('Failed to load race data:', error);
        }
    }

    start() {
        this.isPlaying = true;
        this.lastFrameTime = performance.now();
        this.animate();
    }

    showTimeInput() {
        if (this.isEditingTime) return;
        this.isEditingTime = true;

        const currentTimeStr = this.raceTimerEl.textContent;
        const input = document.createElement('input');
        input.type = 'text';
        input.className = 'time-input';
        input.value = currentTimeStr;
        input.placeholder = 'HH:MM:SS';

        this.raceTimerEl.textContent = '';
        this.raceTimerEl.appendChild(input);
        input.focus();
        input.select();

        const handleSubmit = () => {
            const value = input.value.trim();
            this.jumpToTime(value);
            this.isEditingTime = false;
        };

        const handleCancel = () => {
            this.isEditingTime = false;
            this.updateTimer();
        };

        input.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                handleSubmit();
            } else if (e.key === 'Escape') {
                handleCancel();
            }
        });

        input.addEventListener('blur', handleSubmit);
    }

    showLapInput() {
        if (this.isEditingLap) return;
        this.isEditingLap = true;

        // Extract current lap number from text like "Lap 5 / 78"
        const currentText = this.lapCounterEl.textContent;
        const match = currentText.match(/Lap\s+(\d+)/i);
        const currentLap = match ? match[1] : '1';

        const input = document.createElement('input');
        input.type = 'number';
        input.className = 'lap-input';
        input.value = currentLap;
        input.min = '1';
        input.max = this.raceInfo?.total_laps || '100';
        input.placeholder = '#';

        this.lapCounterEl.textContent = '';
        this.lapCounterEl.appendChild(input);
        input.focus();
        input.select();

        const handleSubmit = () => {
            const value = parseInt(input.value, 10);
            if (!isNaN(value) && value >= 1) {
                this.jumpToLap(value);
            }
            this.isEditingLap = false;
        };

        const handleCancel = () => {
            this.isEditingLap = false;
            this.updateStandings();
        };

        input.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                handleSubmit();
            } else if (e.key === 'Escape') {
                handleCancel();
            }
        });

        input.addEventListener('blur', handleSubmit);
    }

    toggleSpeedDropdown(e) {
        e.stopPropagation();
        this.speedDropdownEl.classList.toggle('open');
    }

    closeSpeedDropdown(e) {
        // Close dropdown when clicking outside
        if (!this.speedSelectorEl.contains(e.target)) {
            this.speedDropdownEl.classList.remove('open');
        }
    }

    selectSpeed(e) {
        e.stopPropagation(); // Prevent bubbling to speed selector toggle

        const option = e.target.closest('.speed-option');
        if (!option) return;

        const newSpeed = parseFloat(option.dataset.speed);
        if (isNaN(newSpeed)) return;

        // Update selected state
        this.speedDropdownEl.querySelectorAll('.speed-option').forEach(opt => {
            opt.classList.remove('selected');
        });
        option.classList.add('selected');

        // Update display
        this.speedValueEl.textContent = option.textContent;

        // Update playback speed (delta-based timing handles the rest)
        this.playbackSpeed = newSpeed;

        // Close dropdown
        this.speedDropdownEl.classList.remove('open');

        console.log(`Playback speed changed to ${newSpeed}x`);
    }

    jumpToTime(timeStr) {
        // Parse time string in HH:MM:SS format and convert to delta seconds
        const parts = timeStr.split(':').map(p => parseInt(p, 10));
        if (parts.length < 2 || parts.some(isNaN)) {
            console.warn('Invalid time format. Use HH:MM:SS');
            this.updateTimer();
            return;
        }

        let targetSeconds;
        if (this.t0Date) {
            // Calculate target time as delta from t0_date
            const hours = parts[0] || 0;
            const minutes = parts[1] || 0;
            const seconds = parts[2] || 0;

            // Create target local time on same day
            const targetLocal = new Date(this.t0Date);
            targetLocal.setUTCHours(hours);
            targetLocal.setUTCMinutes(minutes);
            targetLocal.setUTCSeconds(seconds);

            // Subtract GMT offset to get UTC, then calculate delta from t0
            const targetUTC = new Date(targetLocal.getTime() - (this.gmtOffset * 1000));
            targetSeconds = (targetUTC.getTime() - this.t0Date.getTime()) / 1000;
        } else {
            // Fallback: treat as MM:SS or HH:MM:SS delta
            if (parts.length === 2) {
                targetSeconds = parts[0] * 60 + parts[1];
            } else {
                targetSeconds = parts[0] * 3600 + parts[1] * 60 + parts[2];
            }
        }

        // Clamp to valid range
        targetSeconds = Math.max(0, targetSeconds);

        this.currentTime = targetSeconds;
        this.previousTime = targetSeconds;
        this.lastFrameTime = performance.now();

        this.updateTimer();
        this.updateStandings();
        this.updateTrackStatus();

        console.log(`Jumped to time: ${timeStr} (${targetSeconds.toFixed(1)}s)`);
    }

    jumpToLap(lapNumber) {
        if (!this.telemetryData) {
            console.warn('Telemetry data not loaded');
            return;
        }

        // Find the time when the leader starts the specified lap
        let targetTime = null;

        for (const data of Object.values(this.telemetryData)) {
            const laps = data.telemetry.LapNumber;
            const times = data.telemetry.Time;

            // Find the first occurrence of this lap number
            for (let i = 0; i < laps.length; i++) {
                if (laps[i] === lapNumber) {
                    if (targetTime === null || times[i] < targetTime) {
                        targetTime = times[i];
                    }
                    break;
                }
            }
        }

        if (targetTime === null) {
            console.warn(`Lap ${lapNumber} not found in telemetry`);
            return;
        }

        this.currentTime = targetTime;
        this.previousTime = targetTime;
        this.lastFrameTime = performance.now();

        this.updateTimer();
        this.updateStandings();
        this.updateTrackStatus();

        console.log(`Jumped to lap ${lapNumber} at ${targetTime.toFixed(1)}s`);
    }

    togglePlayPause() {
        this.isPaused = !this.isPaused;
        this.playPauseBtnEl.classList.toggle('paused', this.isPaused);

        if (!this.isPaused) {
            // Resuming - reset frame time to avoid time jump
            this.lastFrameTime = performance.now();
        }

        console.log(this.isPaused ? '⏸️ Paused' : '▶️ Playing');
    }

    animate() {
        if (!this.isPlaying) return;

        // Calculate real time delta since last frame
        const now = performance.now();
        const deltaMs = now - this.lastFrameTime;
        this.lastFrameTime = now;

        // Skip time advancement if paused (but keep animation loop running)
        if (!this.isPaused) {
            // Cap delta to prevent huge jumps (e.g., when tab is inactive)
            const cappedDeltaMs = Math.min(deltaMs, 100);

            // Convert to seconds and apply playback speed
            const deltaSeconds = (cappedDeltaMs / 1000) * this.playbackSpeed;

            // Save previous time for message detection
            this.previousTime = this.currentTime;

            // Advance current time (delta-based for smooth playback)
            this.currentTime += deltaSeconds;

            // Update UI
            this.updateTimer();
            this.updateStandings();
            this.updateTrackStatus();
            this.updateRaceMessages();
            this.updateWeather();
            this.updateFastestLap();
        }

        // Continue animation
        requestAnimationFrame(() => this.animate());
    }

    /**
     * Convert normalized telemetry time to local time string
     * @param {number} normalizedTime - Normalized time from telemetry (starts at 0)
     * @returns {string} Local time in HH:MM:SS format
     */
    toLocalTime(normalizedTime) {
        if (!this.t0Date) {
            // Fallback to delta time if no t0_date available
            const minutes = Math.floor(normalizedTime / 60);
            const seconds = Math.floor(normalizedTime % 60);
            return `${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`;
        }

        // Add globalMinTime to convert normalized time back to actual time from t0_date
        const actualDelta = normalizedTime + (this.globalMinTime || 0);

        // Calculate UTC time by adding delta to t0_date
        const utcTime = new Date(this.t0Date.getTime() + (actualDelta * 1000));

        // Add GMT offset for local time
        const localTime = new Date(utcTime.getTime() + (this.gmtOffset * 1000));

        // Format as HH:MM:SS
        const hours = localTime.getUTCHours().toString().padStart(2, '0');
        const minutes = localTime.getUTCMinutes().toString().padStart(2, '0');
        const seconds = localTime.getUTCSeconds().toString().padStart(2, '0');

        return `${hours}:${minutes}:${seconds}`;
    }

    updateTimer() {
        // Don't update if user is editing the time
        if (this.isEditingTime) return;

        // Display local time
        const timeStr = this.toLocalTime(this.currentTime);
        this.raceTimerEl.textContent = timeStr;
    }

    updateStandings() {
        if (!this.telemetryData) return;

        // Build driver data map for position/color info
        const driverDataMap = {};
        for (const [driverCode, data] of Object.entries(this.telemetryData)) {
            const position = this.getDriverPositionAtTime(data, this.currentTime);
            if (position) {
                driverDataMap[driverCode] = {
                    code: driverCode,
                    lastName: this.getLastName(driverCode),
                    color: data.info.color,
                    team: data.info.team,
                    lapNumber: position.lapNumber,
                    distanceCovered: position.distanceCovered,
                    x: position.x,
                    y: position.y,
                    isDNF: position.isDNF
                };
            }
        }

        // Get precalculated standings (with intervals) for current time using binary search
        let precalcStandings = [];
        if (this.positionHistory && this.positionHistory.length > 0) {
            let low = 0, high = this.positionHistory.length - 1;
            let idx = 0;
            while (low <= high) {
                const mid = Math.floor((low + high) / 2);
                if (this.positionHistory[mid].time <= this.currentTime) {
                    idx = mid;
                    low = mid + 1;
                } else {
                    high = mid - 1;
                }
            }
            precalcStandings = this.positionHistory[idx].standings;
        }

        let drivers = [];

        if (precalcStandings.length > 0) {
            // Use precalculated order with intervals
            for (const s of precalcStandings) {
                if (driverDataMap[s.code]) {
                    const driver = driverDataMap[s.code];
                    const interval = s.interval;
                    if (typeof interval === 'number') {
                        driver.interval = `+${interval.toFixed(3)}`;
                    } else {
                        driver.interval = interval; // 'LEADER', 'DNF', '---'
                    }
                    drivers.push(driver);
                }
            }
            // Add any drivers not in standings
            const standingsCodes = precalcStandings.map(s => s.code);
            for (const driverCode of Object.keys(driverDataMap)) {
                if (!standingsCodes.includes(driverCode)) {
                    driverDataMap[driverCode].interval = '---';
                    drivers.push(driverDataMap[driverCode]);
                }
            }
        } else {
            // Fallback: sort by distance if no precalculated data
            drivers = Object.values(driverDataMap);
            drivers.sort((a, b) => {
                if (a.isDNF && !b.isDNF) return 1;
                if (!a.isDNF && b.isDNF) return -1;
                return b.distanceCovered - a.distanceCovered;
            });
            // Set basic intervals
            drivers.forEach((d, i) => {
                if (d.isDNF) d.interval = 'DNF';
                else if (i === 0) d.interval = 'LEADER';
                else d.interval = '---';
            });
        }

        // Update lap counter (use first active driver's lap)
        // Don't update if user is editing the lap
        if (!this.isEditingLap && drivers.length > 0) {
            // Find first non-DNF driver
            const leader = drivers.find(d => !d.isDNF);
            if (leader) {
                const leaderLap = leader.lapNumber;
                const totalLaps = this.raceInfo.total_laps || '?';
                this.lapCounterEl.textContent = `Lap ${leaderLap} / ${totalLaps}`;
            }
        }

        // Update track renderer with driver positions
        if (this.trackRenderer) {
            this.trackRenderer.updateDrivers(drivers);
        }

        // Render standings
        this.renderStandings(drivers);
    }

    getDriverPositionAtTime(driverData, raceTime) {
        const times = driverData.telemetry.Time;
        const laps = driverData.telemetry.LapNumber;
        const xCoords = driverData.telemetry.X;
        const yCoords = driverData.telemetry.Y;
        const distances = driverData.telemetry.Distance; // May be undefined

        // Check if race hasn't started for this driver yet
        if (raceTime < times[0]) {
            // Driver hasn't started yet - return null to not display them
            return null;
        }

        // Check if driver has DNF'd (race time is past their last telemetry)
        const isDNF = raceTime > times[times.length - 1] + 5.0; // 5 second grace period

        // Find the two closest time points for interpolation
        let prevIndex = 0;
        let nextIndex = 0;

        for (let i = 0; i < times.length; i++) {
            if (times[i] <= raceTime) {
                prevIndex = i;
            } else {
                nextIndex = i;
                break;
            }
        }

        // If we're past the last point, use the last point
        if (nextIndex === 0 || nextIndex <= prevIndex) {
            nextIndex = prevIndex;
        }

        // Calculate interpolation factor (0 to 1)
        let t = 0;
        let interpX = xCoords[prevIndex];
        let interpY = yCoords[prevIndex];

        if (prevIndex !== nextIndex) {
            // Always interpolate for smooth movement (game clock ensures consistent timing)
            const timeDiff = times[nextIndex] - times[prevIndex];
            if (timeDiff > 0) {
                t = (raceTime - times[prevIndex]) / timeDiff;
                t = Math.max(0, Math.min(1, t)); // Clamp to [0, 1]

                // Linear interpolation of position
                interpX = xCoords[prevIndex] + t * (xCoords[nextIndex] - xCoords[prevIndex]);
                interpY = yCoords[prevIndex] + t * (yCoords[nextIndex] - yCoords[prevIndex]);
            }
        }

        // Calculate total distance covered (use prevIndex for lap/distance info)
        const lapNumber = laps[prevIndex];
        const currentTime = times[prevIndex];

        // Calculate cumulative distance across all laps
        let distanceCovered;
        let distanceInLap = 0;
        if (distances && distances.length > prevIndex && this.raceInfo.track_length) {
            const trackLength = this.raceInfo.track_length;
            const distanceValue = distances[prevIndex];

            // Detect if Distance is cumulative (across all laps) or per-lap (resets each lap)
            // If distance > track_length, it's cumulative
            // If distance < track_length, it resets each lap
            if (distanceValue > trackLength) {
                // Distance is cumulative - use directly
                distanceCovered = distanceValue;
            } else {
                // Distance resets each lap - calculate cumulative
                // Total distance = (completed laps * track length) + distance in current lap
                distanceCovered = (lapNumber - 1) * trackLength + distanceValue;
            }

            // Interpolate distance too if we're interpolating position
            if (prevIndex !== nextIndex && t > 0) {
                const nextDistance = distances[nextIndex];
                if (nextDistance > trackLength) {
                    distanceCovered = distanceCovered + t * (nextDistance - distanceValue);
                }
            }
            // Calculate distance within current lap for sector detection
            distanceInLap = distanceValue > trackLength
                ? distanceValue % trackLength
                : distanceValue;
        } else {
            // Fallback: use lap number and index as rough approximation
            distanceCovered = lapNumber * 10000 + prevIndex;
            distanceInLap = 0;
        }

        return {
            time: currentTime,
            lapNumber: lapNumber,
            distanceCovered: distanceCovered,
            distanceInLap: distanceInLap,
            x: interpX,
            y: interpY,
            index: prevIndex,
            isDNF: isDNF
        };
    }

    getLastName(driverCode) {
        // Driver code mappings to last names
        const names = {
            'VER': 'Verstappen',
            'HAM': 'Hamilton',
            'LEC': 'Leclerc',
            'PER': 'Perez',
            'SAI': 'Sainz',
            'NOR': 'Norris',
            'RUS': 'Russell',
            'ALO': 'Alonso',
            'OCO': 'Ocon',
            'GAS': 'Gasly',
            'STR': 'Stroll',
            'TSU': 'Tsunoda',
            'ALB': 'Albon',
            'BOT': 'Bottas',
            'ZHO': 'Zhou',
            'MAG': 'Magnussen',
            'HUL': 'Hulkenberg',
            'RIC': 'Ricciardo',
            'SAR': 'Sargeant',
            'PIA': 'Piastri',
            'DEV': 'De Vries',
            'LAW': 'Lawson',
            'BEA': 'Bearman'
        };

        return names[driverCode] || driverCode;
    }

    renderStandings(drivers) {
        const now = performance.now();

        // Detect position changes
        for (let i = 0; i < drivers.length; i++) {
            const driver = drivers[i];
            const currentPos = i + 1;
            const prevPos = this.previousPositions[driver.code];

            if (prevPos !== undefined && prevPos !== currentPos) {
                const direction = currentPos < prevPos ? 'up' : 'down';
                const positionsChanged = Math.abs(currentPos - prevPos);
                const existing = this.positionChanges[driver.code];

                if (existing && existing.direction === direction) {
                    existing.positions += positionsChanged;
                    existing.time = now;
                } else {
                    this.positionChanges[driver.code] = { direction, positions: positionsChanged, time: now };
                }
            }
            this.previousPositions[driver.code] = currentPos;
        }

        // Clean up old position changes (older than 3 seconds)
        for (const code of Object.keys(this.positionChanges)) {
            if (now - this.positionChanges[code].time > 3000) {
                delete this.positionChanges[code];
            }
        }

        // Reuse existing DOM elements instead of recreating them
        const existingRows = this.standingsEl.children;

        for (let i = 0; i < drivers.length; i++) {
            const driver = drivers[i];
            let row = existingRows[i];

            // Create row if it doesn't exist
            if (!row) {
                row = document.createElement('div');
                row.innerHTML = '<div class="driver-position"></div><div class="driver-color"></div><div class="driver-name"></div><div class="driver-interval"></div>';
                this.standingsEl.appendChild(row);
            }

            // Build class name
            let className = 'driver-row';
            if (i === 0 && !driver.isDNF) className += ' leader';
            if (driver.isDNF) className += ' dnf';

            const hasActiveHighlight = this.fastestLapHighlight && driver.code === this.fastestLapHighlight.driver;
            if (hasActiveHighlight) className += ' fastest-lap-highlight';

            if (row.className !== className) row.className = className;

            // Use querySelector to find elements (indices shift when indicator is added)
            const posEl = row.querySelector('.driver-position');
            const colorEl = row.querySelector('.driver-color');
            const nameEl = row.querySelector('.driver-name');
            const intervalEl = row.querySelector('.driver-interval');

            // Update position
            const posText = String(i + 1);
            if (posEl.textContent !== posText) posEl.textContent = posText;

            // Update color bar
            if (colorEl.style.backgroundColor !== driver.color) {
                colorEl.style.backgroundColor = driver.color;
            }

            // Update name
            const nameText = driver.lastName.toUpperCase();
            if (nameEl.textContent !== nameText) nameEl.textContent = nameText;

            const isFastestLapHolder = this.currentFastestLapHolder === driver.code;
            const hasFastestClass = nameEl.classList.contains('fastest-lap');
            if (isFastestLapHolder && !hasFastestClass) {
                nameEl.className = 'driver-name fastest-lap';
            } else if (!isFastestLapHolder && hasFastestClass) {
                nameEl.className = 'driver-name';
            }

            // Update interval
            const intervalText = hasActiveHighlight ? this.fastestLapHighlight.lapTimeStr : driver.interval;
            if (intervalEl.textContent !== intervalText) intervalEl.textContent = intervalText;

            const intervalHasFastest = intervalEl.classList.contains('fastest-lap');
            if (hasActiveHighlight && !intervalHasFastest) {
                intervalEl.className = 'driver-interval fastest-lap';
            } else if (!hasActiveHighlight && intervalHasFastest) {
                intervalEl.className = 'driver-interval';
            }

            // Handle position change indicator
            const posChange = this.positionChanges[driver.code];
            let indicator = row.querySelector('.position-change');

            if (posChange) {
                if (!indicator) {
                    indicator = document.createElement('div');
                    indicator.innerHTML = '<span class="position-change-count"></span><span class="position-change-arrow"></span>';
                    row.appendChild(indicator); // Append instead of insertBefore to avoid shifting
                }

                indicator.className = `position-change ${posChange.direction}`;
                const elapsed = now - posChange.time;
                indicator.style.opacity = Math.max(0, 1 - (elapsed / 3000));

                const counter = indicator.children[0];
                const arrow = indicator.children[1];

                if (posChange.positions > 1) {
                    counter.textContent = posChange.positions;
                    counter.style.display = '';
                } else {
                    counter.style.display = 'none';
                }
                arrow.textContent = posChange.direction === 'up' ? '▲' : '▼';
            } else if (indicator) {
                indicator.remove();
            }
        }

        // Remove excess rows
        while (this.standingsEl.children.length > drivers.length) {
            this.standingsEl.lastChild.remove();
        }
    }

    updateTrackStatus() {
        // Find current track status based on race time
        // Track status times are normalized at load time to match telemetry timeline
        let newStatus = '1'; // Default to AllClear

        for (const status of this.trackStatus) {
            if (status.time <= this.currentTime) {
                newStatus = status.status;
            } else {
                break;
            }
        }

        // Update track visual and log status changes
        if (newStatus !== this.currentTrackStatus) {
            const statusNames = {
                '1': 'Green Flag',
                '2': 'Yellow Flag',
                '4': 'Safety Car',
                '5': 'RED FLAG',
                '6': 'Virtual Safety Car',
                '7': 'VSC Ending'
            };
            const statusName = statusNames[newStatus] || newStatus;
            console.log(`🚦 Track Status Changed: ${statusName} at ${this.toLocalTime(this.currentTime)}`);

            // Show track status message (skip Green Flag unless coming from red/SC)
            const showMessage = newStatus !== '1' ||
                               this.currentTrackStatus === '5' ||
                               this.currentTrackStatus === '4' ||
                               this.currentTrackStatus === '6';
            if (showMessage) {
                this.showTrackStatusMessage(statusName, newStatus);
            }

            this.currentTrackStatus = newStatus;

            // Update track renderer with new status
            if (this.trackRenderer) {
                this.trackRenderer.setTrackStatus(newStatus);
            }
        }
    }

    showTrackStatusMessage(statusName, statusCode) {
        // Create track status message element
        const messageEl = document.createElement('div');

        // Determine message class based on status
        let messageClass = 'flag';
        if (statusCode === '5') messageClass = 'redflag';
        else if (statusCode === '4' || statusCode === '6' || statusCode === '7') messageClass = 'safetycar';

        messageEl.className = `race-message ${messageClass}`;

        // Create header with time and category
        const headerEl = document.createElement('div');
        headerEl.className = 'race-message-header';

        const timeEl = document.createElement('div');
        timeEl.className = 'race-message-time';
        timeEl.textContent = this.toLocalTime(this.currentTime);

        const categoryEl = document.createElement('div');
        categoryEl.className = 'race-message-category';
        categoryEl.textContent = 'TRACK STATUS';

        headerEl.appendChild(timeEl);
        headerEl.appendChild(categoryEl);

        const textEl = document.createElement('div');
        textEl.className = 'race-message-text';
        textEl.textContent = statusName.toUpperCase();

        messageEl.appendChild(headerEl);
        messageEl.appendChild(textEl);

        // Add to container
        this.raceMessagesEl.appendChild(messageEl);

        // Fade out after 4.5 seconds, remove after 5 seconds
        setTimeout(() => {
            messageEl.classList.add('fading');
        }, 4500);

        setTimeout(() => {
            messageEl.remove();
        }, 5000);

        // Limit visible messages
        const messages = this.raceMessagesEl.querySelectorAll('.race-message');
        if (messages.length > 6) {
            messages[0].remove();
        }
    }

    updateRaceMessages() {
        // Only show messages that occurred between previous frame and current frame
        // This prevents all messages from appearing at once when jumping in time
        for (const msg of this.raceControlMessages) {
            // Show message if we just "passed through" its timestamp
            // Message time should be after previous frame but at or before current frame
            if (msg.time > this.previousTime && msg.time <= this.currentTime) {
                // Skip if already displayed (in case of time jumps backwards)
                const msgId = `${msg.time}_${msg.message}`;
                if (this.displayedMessageIds.has(msgId)) {
                    continue;
                }

                // Display new message
                this.showRaceMessage(msg);
                this.displayedMessageIds.add(msgId);

                // Handle yellow flag sector updates
                this.handleYellowFlagMessage(msg);

                // Log to console with local time
                console.log(`📢 Race Control [${this.toLocalTime(msg.time)}]: [${msg.category}] ${msg.message}`);
            }
        }
    }

    handleYellowFlagMessage(msg) {
        // Update track yellow flag sectors based on flag messages
        if (!this.trackRenderer || !msg.flag) return;

        const flag = msg.flag.toUpperCase();
        const sector = msg.sector;

        // Handle yellow flag messages with sector info
        if (sector && !isNaN(sector)) {
            const sectorNum = parseInt(sector);

            // Check for double yellow (may be "DOUBLE YELLOW" or contain "DOUBLE")
            if (flag.includes('DOUBLE') && flag.includes('YELLOW')) {
                this.trackRenderer.setYellowFlagSector(sectorNum, true);
                console.log(`🟡🟡 Double Yellow in sector ${sectorNum}`);
            } else if (flag.includes('YELLOW')) {
                this.trackRenderer.setYellowFlagSector(sectorNum, false);
                console.log(`🟡 Yellow in sector ${sectorNum}`);
            } else if (flag === 'CLEAR' || flag.includes('GREEN')) {
                this.trackRenderer.clearYellowFlagSector(sectorNum);
                console.log(`🟢 Clear in sector ${sectorNum}`);
            }
        }

        // Handle global flags (clear all sectors)
        if (flag.includes('GREEN') && !sector) {
            this.trackRenderer.clearAllYellowFlags();
            console.log('🟢 All clear - clearing all yellow flags');
        }
    }

    getMessageClass(msg) {
        // Determine CSS class based on message content
        const text = msg.message.toUpperCase();
        if (text.includes('CHEQUERED FLAG') || text.includes('CHECKERED FLAG')) return 'chequered';
        if (text.includes('RED FLAG')) return 'redflag';
        if (text.includes('SAFETY CAR') || text.includes('SC DEPLOYED')) return 'safetycar';
        if (text.includes('BLUE FLAG')) return 'blueflag';
        if (text.includes('DRS')) return 'drs';
        if (text.includes('FLAG') || text.includes('YELLOW') || text.includes('GREEN')) return 'flag';
        return 'other';
    }

    cleanMessageText(text) {
        // Remove "- Loss of xxxx" and similar timing suffixes
        // Pattern: " - timed at HH:MM:SS" or similar at end of message
        return text.replace(/\s*-?\s*timed at\s+\d{1,2}:\d{2}:\d{2}\.?\d*\s*$/i, '')
                   .replace(/\s*-?\s*loss of\s+\d+:\d{2}\.\d+\s*$/i, '')
                   .trim();
    }

    showRaceMessage(msg) {
        // Create message element
        const messageClass = this.getMessageClass(msg);
        const messageEl = document.createElement('div');
        messageEl.className = `race-message ${messageClass}`;

        // Create header with time and category
        const headerEl = document.createElement('div');
        headerEl.className = 'race-message-header';

        const timeEl = document.createElement('div');
        timeEl.className = 'race-message-time';
        timeEl.textContent = this.toLocalTime(msg.time);

        const categoryEl = document.createElement('div');
        categoryEl.className = 'race-message-category';
        categoryEl.textContent = msg.category || 'RACE CONTROL';

        headerEl.appendChild(timeEl);
        headerEl.appendChild(categoryEl);

        const textEl = document.createElement('div');
        textEl.className = 'race-message-text';
        textEl.textContent = this.cleanMessageText(msg.message);

        messageEl.appendChild(headerEl);
        messageEl.appendChild(textEl);

        // Add to container (with column-reverse, appendChild puts newest at visual top)
        this.raceMessagesEl.appendChild(messageEl);

        // Start fade out after 4.5 seconds, remove after 5 seconds
        setTimeout(() => {
            messageEl.classList.add('fading');
        }, 4500);

        setTimeout(() => {
            messageEl.remove();
        }, 5000);

        // Limit to max 6 visible messages - remove oldest (first in DOM = visual bottom with column-reverse)
        const messages = this.raceMessagesEl.querySelectorAll('.race-message');
        if (messages.length > 6) {
            messages[0].remove();
        }
    }

    updateWeather() {
        if (!this.weatherData || this.weatherData.length === 0) return;
        if (!this.weatherIndicatorEl) return;

        // Find the most recent weather data point at or before current time
        let currentWeather = null;
        for (let i = this.weatherData.length - 1; i >= 0; i--) {
            if (this.weatherData[i].time <= this.currentTime) {
                currentWeather = this.weatherData[i];
                break;
            }
        }

        if (!currentWeather) {
            currentWeather = this.weatherData[0]; // Use first data point if before all data
        }

        // Update rain indicator visibility
        const wasRaining = this.isRaining;
        this.isRaining = currentWeather.rainfall === true;

        if (this.isRaining && !wasRaining) {
            // Just started raining
            this.weatherIndicatorEl.classList.remove('hidden');
            console.log(`🌧️ Rain detected! Air: ${currentWeather.air_temp?.toFixed(1) || '?'}°C, Track: ${currentWeather.track_temp?.toFixed(1) || '?'}°C, Humidity: ${currentWeather.humidity?.toFixed(0) || '?'}%`);
        } else if (!this.isRaining && wasRaining) {
            // Rain stopped
            this.weatherIndicatorEl.classList.add('hidden');
            console.log(`☀️ Rain stopped. Air: ${currentWeather.air_temp?.toFixed(1) || '?'}°C, Track: ${currentWeather.track_temp?.toFixed(1) || '?'}°C, Humidity: ${currentWeather.humidity?.toFixed(0) || '?'}%`);
        }
    }

    updateFastestLap() {
        if (!this.fastestLapHistory || this.fastestLapHistory.length === 0) return;

        // Find the current fastest lap holder at this point in time
        let fastestLapHolder = null;
        for (let i = this.fastestLapHistory.length - 1; i >= 0; i--) {
            if (this.fastestLapHistory[i].time <= this.currentTime) {
                fastestLapHolder = this.fastestLapHistory[i];
                break;
            }
        }

        // Update current fastest lap holder
        const previousHolder = this.currentFastestLapHolder;
        this.currentFastestLapHolder = fastestLapHolder ? fastestLapHolder.driver : null;

        // Highlight new fastest lap in standings
        for (const fl of this.fastestLapHistory) {
            // Check if this fastest lap just happened (between previous and current time)
            if (fl.time > this.previousTime && fl.time <= this.currentTime) {
                const flId = `fastestlap_${fl.driver}_${fl.lap_number}`;
                if (this.displayedFastestLaps.has(flId)) continue;

                // Highlight driver in standings (shows lap time and bold for 5 seconds)
                this.highlightFastestLap(fl);
                this.displayedFastestLaps.add(flId);

                console.log(`🟣 FASTEST LAP: ${fl.driver} - ${fl.lap_time_str} (Lap ${fl.lap_number})`);
            }
        }

        // Notify track renderer about fastest lap holder change
        if (this.trackRenderer && this.currentFastestLapHolder !== previousHolder) {
            this.trackRenderer.setFastestLapHolder(this.currentFastestLapHolder);
        }
    }

    highlightFastestLap(fl) {
        // Clear any existing highlight timeout
        if (this.fastestLapHighlight && this.fastestLapHighlight.timeoutId) {
            clearTimeout(this.fastestLapHighlight.timeoutId);
        }

        // Set the highlight (shows lap time instead of interval, makes row bold)
        this.fastestLapHighlight = {
            driver: fl.driver,
            lapTimeStr: fl.lap_time_str
        };

        // Re-render standings to show the highlight
        this.updateStandings();

        // Clear the highlight after 5 seconds (but keep purple via currentFastestLapHolder)
        this.fastestLapHighlight.timeoutId = setTimeout(() => {
            this.fastestLapHighlight = null;
            this.updateStandings();
        }, 5000);
    }
}

/**
 * Track Selector - Handles year and track selection UI
 */
class TrackSelector {
    constructor(trackRenderer) {
        this.trackRenderer = trackRenderer;

        // Current values (from loaded race)
        this.currentYear = null;
        this.currentRaceName = null;
        this.currentRound = null;

        // Selected values (may differ from current)
        this.selectedYear = null;
        this.selectedRound = null;
        this.selectedRaceName = null;

        // Cached schedules
        this.scheduleCache = {};

        // DOM elements
        this.yearSelectorEl = document.getElementById('yearSelector');
        this.trackNameSelectorEl = document.getElementById('trackNameSelector');
        this.trackActionsEl = document.getElementById('trackActions');
        this.yearDropdownEl = document.getElementById('yearDropdown');
        this.trackDropdownEl = document.getElementById('trackDropdown');
        this.cancelBtnEl = document.getElementById('cancelBtn');
        this.loadBtnEl = document.getElementById('loadBtn');

        // Set up event handlers
        this.yearSelectorEl.addEventListener('click', (e) => this.toggleYearDropdown(e));
        this.trackNameSelectorEl.addEventListener('click', (e) => this.toggleTrackDropdown(e));
        this.cancelBtnEl.addEventListener('click', () => this.cancelSelection());
        this.loadBtnEl.addEventListener('click', () => this.loadSelectedRace());
        document.addEventListener('click', (e) => this.closeDropdowns(e));

        // Initialize
        this.init();
    }

    async init() {
        // Wait for trackRenderer to load race info
        await this.waitForRaceInfo();

        if (this.trackRenderer.raceInfo) {
            const info = this.trackRenderer.raceInfo;
            this.currentYear = info.year;
            this.currentRaceName = info.event_name || info.race_name;
            this.selectedYear = this.currentYear;
            this.selectedRaceName = this.currentRaceName;

            // Update display
            this.yearSelectorEl.textContent = this.currentYear;
            this.trackNameSelectorEl.textContent = this.currentRaceName;

            // Preload schedule for current year
            await this.loadSchedule(this.currentYear);

            // Find current round number
            const schedule = this.scheduleCache[this.currentYear];
            if (schedule) {
                const race = schedule.races.find(r => r.name === this.currentRaceName);
                if (race) {
                    this.currentRound = race.round;
                    this.selectedRound = race.round;
                }
            }
        }

        // Populate year dropdown (2018-current year)
        this.populateYearDropdown();
    }

    async waitForRaceInfo() {
        // Wait up to 5 seconds for race info to load
        for (let i = 0; i < 50; i++) {
            if (this.trackRenderer.raceInfo) return;
            await new Promise(r => setTimeout(r, 100));
        }
    }

    populateYearDropdown() {
        const currentYear = new Date().getFullYear();
        this.yearDropdownEl.innerHTML = '';

        for (let year = currentYear; year >= 2018; year--) {
            const item = document.createElement('div');
            item.className = 'dropdown-item';
            if (year === this.selectedYear) item.classList.add('selected');
            item.textContent = year;
            item.dataset.year = year;
            item.addEventListener('click', (e) => this.selectYear(year, e));
            this.yearDropdownEl.appendChild(item);
        }
    }

    async loadSchedule(year) {
        if (this.scheduleCache[year]) return this.scheduleCache[year];

        try {
            const response = await fetch(`/api/schedule/${year}`);
            const data = await response.json();
            this.scheduleCache[year] = data;
            return data;
        } catch (error) {
            console.error(`Failed to load schedule for ${year}:`, error);
            return null;
        }
    }

    populateTrackDropdown(schedule) {
        this.trackDropdownEl.innerHTML = '';

        if (!schedule || !schedule.races) return;

        for (const race of schedule.races) {
            const item = document.createElement('div');
            item.className = 'dropdown-item';
            if (race.round === this.selectedRound && this.selectedYear === schedule.year) {
                item.classList.add('selected');
            }
            item.textContent = race.name;
            item.dataset.round = race.round;
            item.dataset.name = race.name;
            item.addEventListener('click', (e) => this.selectTrack(race, e));
            this.trackDropdownEl.appendChild(item);
        }
    }

    toggleYearDropdown(e) {
        e.stopPropagation();
        this.trackDropdownEl.classList.remove('open');
        this.yearDropdownEl.classList.toggle('open');
        this.yearSelectorEl.classList.toggle('active');
        this.trackNameSelectorEl.classList.remove('active');

        // Position dropdown below selector
        if (this.yearDropdownEl.classList.contains('open')) {
            const rect = this.yearSelectorEl.getBoundingClientRect();
            this.yearDropdownEl.style.left = rect.left + 'px';
            this.yearDropdownEl.style.top = (rect.bottom + 4) + 'px';
        }
    }

    async toggleTrackDropdown(e) {
        e.stopPropagation();
        this.yearDropdownEl.classList.remove('open');
        this.yearSelectorEl.classList.remove('active');

        // Load schedule if not cached
        const schedule = await this.loadSchedule(this.selectedYear);
        this.populateTrackDropdown(schedule);

        this.trackDropdownEl.classList.toggle('open');
        this.trackNameSelectorEl.classList.toggle('active');

        // Position dropdown below selector
        if (this.trackDropdownEl.classList.contains('open')) {
            const rect = this.trackNameSelectorEl.getBoundingClientRect();
            this.trackDropdownEl.style.left = rect.left + 'px';
            this.trackDropdownEl.style.top = (rect.bottom + 4) + 'px';
        }
    }

    async selectYear(year, e) {
        e.stopPropagation();
        this.selectedYear = year;
        this.yearSelectorEl.textContent = year;

        // Update selected state in dropdown
        this.yearDropdownEl.querySelectorAll('.dropdown-item').forEach(item => {
            item.classList.toggle('selected', parseInt(item.dataset.year) === year);
        });

        // Close year dropdown
        this.yearDropdownEl.classList.remove('open');
        this.yearSelectorEl.classList.remove('active');

        // If year changed, reset track selection to first race
        if (year !== this.currentYear || this.selectedRound !== this.currentRound) {
            const schedule = await this.loadSchedule(year);
            if (schedule && schedule.races.length > 0) {
                // Keep same track name if it exists in new year, otherwise use first race
                const sameTrack = schedule.races.find(r => r.name === this.selectedRaceName);
                if (sameTrack) {
                    this.selectedRound = sameTrack.round;
                } else {
                    this.selectedRound = schedule.races[0].round;
                    this.selectedRaceName = schedule.races[0].name;
                    this.trackNameSelectorEl.textContent = this.selectedRaceName;
                }
            }
        }

        this.updateActionButtons();
    }

    selectTrack(race, e) {
        e.stopPropagation();
        this.selectedRound = race.round;
        this.selectedRaceName = race.name;
        this.trackNameSelectorEl.textContent = race.name;

        // Update selected state in dropdown
        this.trackDropdownEl.querySelectorAll('.dropdown-item').forEach(item => {
            item.classList.toggle('selected', parseInt(item.dataset.round) === race.round);
        });

        // Close track dropdown
        this.trackDropdownEl.classList.remove('open');
        this.trackNameSelectorEl.classList.remove('active');

        this.updateActionButtons();
    }

    closeDropdowns(e) {
        if (!this.yearSelectorEl.contains(e.target) && !this.yearDropdownEl.contains(e.target)) {
            this.yearDropdownEl.classList.remove('open');
            this.yearSelectorEl.classList.remove('active');
        }
        if (!this.trackNameSelectorEl.contains(e.target) && !this.trackDropdownEl.contains(e.target)) {
            this.trackDropdownEl.classList.remove('open');
            this.trackNameSelectorEl.classList.remove('active');
        }
    }

    updateActionButtons() {
        // Show buttons if selection differs from current
        const hasChanged = this.selectedYear !== this.currentYear ||
                          this.selectedRound !== this.currentRound;

        if (hasChanged) {
            this.trackActionsEl.classList.add('visible');
        } else {
            this.trackActionsEl.classList.remove('visible');
        }
    }

    cancelSelection() {
        // Reset to current values
        this.selectedYear = this.currentYear;
        this.selectedRound = this.currentRound;
        this.selectedRaceName = this.currentRaceName;

        this.yearSelectorEl.textContent = this.currentYear;
        this.trackNameSelectorEl.textContent = this.currentRaceName;

        this.trackActionsEl.classList.remove('visible');
    }

    async loadSelectedRace() {
        // Show loading overlay while keeping current race running
        this.showLoadingOverlay(`Loading ${this.selectedYear} Round ${this.selectedRound}...`);

        try {
            // Start loading the new race
            const response = await fetch(`/api/load/${this.selectedYear}/${this.selectedRound}`);
            const data = await response.json();

            if (data.status === 'already_loading') {
                this.updateLoadingMessage(data.message);
            }

            // Poll for status
            this.pollLoadStatus();
        } catch (error) {
            console.error('Failed to start loading:', error);
            this.hideLoadingOverlay();
            alert('Failed to start loading race');
        }
    }

    pollLoadStatus() {
        const poll = setInterval(async () => {
            try {
                const response = await fetch('/api/load_status');
                const data = await response.json();

                this.updateLoadingMessage(data.message || data.status);

                if (data.status === 'ready') {
                    clearInterval(poll);
                    this.updateLoadingMessage('Reloading...');
                    // Reload the page to get the new race
                    window.location.reload();
                } else if (data.status === 'error') {
                    clearInterval(poll);
                    this.hideLoadingOverlay();
                    alert(`Failed to load race: ${data.message}`);
                    // Reset selection
                    this.cancelSelection();
                }
            } catch (error) {
                console.error('Failed to poll status:', error);
            }
        }, 1000);
    }

    showLoadingOverlay(message) {
        // Create toast notification if it doesn't exist
        let toast = document.getElementById('loadingToast');
        if (!toast) {
            toast = document.createElement('div');
            toast.id = 'loadingToast';
            toast.className = 'loading-toast';
            toast.innerHTML = `
                <div class="loading-toast-spinner"></div>
                <div class="loading-toast-message" id="loadingMessage">${message}</div>
            `;
            document.body.appendChild(toast);
        } else {
            document.getElementById('loadingMessage').textContent = message;
        }
        toast.classList.add('visible');
    }

    updateLoadingMessage(message) {
        const msgEl = document.getElementById('loadingMessage');
        if (msgEl) {
            msgEl.textContent = message;
        }
    }

    hideLoadingOverlay() {
        const toast = document.getElementById('loadingToast');
        if (toast) {
            toast.classList.remove('visible');
        }
    }
}

// Initialize when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    const trackRenderer = new TrackRenderer();
    const trackSelector = new TrackSelector(trackRenderer);
    new RaceController(trackRenderer);
});
