const STANDINGS_SETTINGS = {
    // Font sizes
    positionSize: '10px',
    driverNameSize: '13px',
    driverNumberSize: '9px',
    timeSize: '11px',

    // Color bar sizing
    driverColorWidth: '3px',
    driverColorHeight: '14px',

    // Spacing (margins)
    driverColorMargin: '0px',
    driverColorMarginRight: '8px',
    driverNameMargin: '0px',
    driverNumberMargin: '2px',
    driverPositionMargin: '8px',
};

// Sector status colors for track rendering
const SECTOR_STATUS_COLORS = {
    'Yellow': '#FFFF00',        // Pure yellow
    'DoubleYellow': '#FFA500',  // Orange (more urgent)
};

// Starting Lights Settings
const STARTING_LIGHTS_SETTINGS = {
    enabled: true,
    // Timing (in seconds)
    appearDelay: 3.0,        // Delay after lights appear before first light
    lightInterval: 1.0,      // Delay between each light turning on
    randomDelayMin: 1.0,     // Min random delay before lights out (after 5th light)
    randomDelayMax: 3.0,     // Max random delay before lights out
    // Styling
    lightOffColor: '#1a1a1a',
    lightOnColor: '#ff0000',
    lightGlowColor: 'rgba(255, 0, 0, 1)',
    lightGlowSize: 15
};
