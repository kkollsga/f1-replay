"""
Visualization Utilities - PLOTTING AND ANIMATION HELPERS

Helper functions for visualizing F1 race data using matplotlib.
Supports plotting driver trajectories, positions, and comparative analysis.
"""

from typing import Optional, List, Dict, Tuple
import numpy as np

try:
    import matplotlib.pyplot as plt
    import matplotlib.patches as patches
    from matplotlib.collections import LineCollection
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False


def plot_track_with_drivers(
    circuit_data,
    position_interpolation,
    distance_snapshot: Optional[float] = None,
    drivers: Optional[List[str]] = None,
    figsize: Tuple[int, int] = (14, 10),
    show_pit_lane: bool = True,
    title: Optional[str] = None
) -> Optional[plt.Figure]:
    """
    Plot the track circuit with all drivers positioned at a specific distance.

    Perfect for visualizing the race at a specific moment (e.g., "standings after 1000m").

    Args:
        circuit_data: CircuitData object with track geometry
        position_interpolation: DataFrame from get_position_interpolation()
        distance_snapshot: Distance to snapshot (meters). If None, uses max distance
        drivers: List of drivers to plot (default: all)
        figsize: Figure size (width, height)
        show_pit_lane: Whether to draw pit lane on track
        title: Custom title for the plot

    Returns:
        matplotlib Figure object (or None if matplotlib not available)
    """
    if not MATPLOTLIB_AVAILABLE:
        print("Matplotlib not available. Install with: pip install matplotlib")
        return None

    if distance_snapshot is None:
        distance_snapshot = position_interpolation["Distance"].max()

    if drivers is None:
        drivers = [col.split("_")[0] for col in position_interpolation.columns
                  if col.endswith("_X")]
        drivers = sorted(list(set(drivers)))

    # Get track data
    track = circuit_data.circuit.track
    pit_lane = circuit_data.circuit.pit_lane if show_pit_lane else None

    # Create figure
    fig, ax = plt.subplots(figsize=figsize)

    # Plot track
    ax.plot(track.x, track.y, "k-", linewidth=2, label="Track", zorder=1)

    # Plot pit lane
    if pit_lane is not None:
        ax.plot(pit_lane.x, pit_lane.y, "r--", linewidth=1.5, label="Pit Lane", zorder=1, alpha=0.7)

    # Find the closest distance snapshot
    distances = position_interpolation["Distance"].to_list()
    closest_idx = min(range(len(distances)), key=lambda i: abs(distances[i] - distance_snapshot))
    snapshot_distance = distances[closest_idx]

    # Plot drivers
    colors = plt.cm.tab20(np.linspace(0, 1, len(drivers)))

    for driver, color in zip(drivers, colors):
        x_col = f"{driver}_X"
        y_col = f"{driver}_Y"
        on_track_col = f"{driver}_OnTrack"

        if x_col not in position_interpolation.columns:
            continue

        x = position_interpolation[x_col][closest_idx]
        y = position_interpolation[y_col][closest_idx]

        if x != x or y != y:  # NaN check
            continue

        # Check if on track
        on_track = True
        if on_track_col in position_interpolation.columns:
            on_track = position_interpolation[on_track_col][closest_idx]

        # Plot driver position
        marker_size = 200
        marker = "o" if on_track else "s"  # Circle for track, square for pit
        ax.scatter(x, y, s=marker_size, c=[color], edgecolors="black", linewidth=2,
                  marker=marker, label=driver, zorder=10)

        # Add driver label
        ax.text(x + 50, y + 50, driver, fontsize=10, fontweight="bold")

    # Formatting
    ax.set_aspect("equal")
    ax.grid(True, alpha=0.3)
    ax.legend(loc="upper left", fontsize=9, ncol=2)

    if title is None:
        title = f"Race Position at {snapshot_distance:.0f}m"
    ax.set_title(title, fontsize=14, fontweight="bold")

    ax.set_xlabel("X (meters)")
    ax.set_ylabel("Y (meters)")

    return fig


def plot_driver_trajectories(
    circuit_data,
    session_data,
    drivers: Optional[List[str]] = None,
    lap_number: Optional[int] = None,
    figsize: Tuple[int, int] = (14, 10),
    title: Optional[str] = None
) -> Optional[plt.Figure]:
    """
    Plot driver trajectories on the track for comparison.

    Shows the actual path each driver took, useful for analyzing lines and
    performance through corners.

    Args:
        circuit_data: CircuitData object
        session_data: SessionData object with telemetry
        drivers: List of drivers to plot (default: all)
        lap_number: If specified, plot only this lap
        figsize: Figure size
        title: Custom title

    Returns:
        matplotlib Figure object
    """
    if not MATPLOTLIB_AVAILABLE:
        print("Matplotlib not available")
        return None

    if drivers is None:
        drivers = sorted(session_data.telemetry.keys())

    track = circuit_data.circuit.track

    fig, ax = plt.subplots(figsize=figsize)

    # Plot track baseline
    ax.plot(track.x, track.y, "k-", linewidth=2, alpha=0.5, label="Track centerline", zorder=1)

    colors = plt.cm.tab20(np.linspace(0, 1, len(drivers)))

    for driver, color in zip(drivers, colors):
        if driver not in session_data.telemetry:
            continue

        tel = session_data.telemetry[driver]

        # Filter by lap if specified
        if lap_number is not None:
            tel = tel.filter(tel["LapNumber"] == lap_number)

        if "X" not in tel.columns or "Y" not in tel.columns:
            continue

        x = tel["X"].to_numpy()
        y = tel["Y"].to_numpy()

        if len(x) > 1:
            ax.plot(x, y, color=color, linewidth=2, alpha=0.7, label=driver, zorder=5)

            # Mark start
            ax.scatter(x[0], y[0], c=[color], s=100, marker="o", edgecolors="green",
                      linewidth=2, zorder=10)

            # Mark end
            ax.scatter(x[-1], y[-1], c=[color], s=100, marker="X", edgecolors="red",
                      linewidth=2, zorder=10)

    ax.set_aspect("equal")
    ax.grid(True, alpha=0.3)
    ax.legend(loc="upper left", fontsize=9, ncol=2)

    if title is None:
        if lap_number is not None:
            title = f"Driver Trajectories - Lap {lap_number}"
        else:
            title = "Driver Trajectories (All Data)"

    ax.set_title(title, fontsize=14, fontweight="bold")
    ax.set_xlabel("X (meters)")
    ax.set_ylabel("Y (meters)")

    return fig


def plot_speed_comparison(
    session_data,
    circuit_data,
    distance_range: Tuple[float, float] = (0, 1000),
    drivers: Optional[List[str]] = None,
    figsize: Tuple[int, int] = (14, 6)
) -> Optional[plt.Figure]:
    """
    Compare driver speeds across a distance range on the track.

    Useful for identifying where drivers gain/lose time relative to competitors.

    Args:
        session_data: SessionData with telemetry
        circuit_data: CircuitData with track info
        distance_range: (start, end) distance in meters to analyze
        drivers: List of drivers to compare
        figsize: Figure size

    Returns:
        matplotlib Figure object
    """
    if not MATPLOTLIB_AVAILABLE:
        return None

    if drivers is None:
        drivers = sorted(session_data.telemetry.keys())[:5]  # Top 5 by default

    fig, ax = plt.subplots(figsize=figsize)

    start_dist, end_dist = distance_range
    colors = plt.cm.tab20(np.linspace(0, 1, len(drivers)))

    for driver, color in zip(drivers, colors):
        if driver not in session_data.telemetry:
            continue

        tel = session_data.telemetry[driver]

        if "Distance" not in tel.columns or "Speed" not in tel.columns:
            continue

        # Filter to distance range
        mask = (tel["Distance"] >= start_dist) & (tel["Distance"] <= end_dist)
        filtered = tel.filter(mask)

        if len(filtered) > 0:
            distances = filtered["Distance"].to_numpy()
            speeds = filtered["Speed"].to_numpy()

            ax.plot(distances, speeds, color=color, linewidth=2, label=driver, marker=".", markersize=2)

    ax.set_xlabel("Distance along track (m)")
    ax.set_ylabel("Speed (km/h)")
    ax.set_title(f"Speed Comparison ({start_dist:.0f}m - {end_dist:.0f}m)")
    ax.grid(True, alpha=0.3)
    ax.legend(fontsize=10)

    return fig


def plot_standings_timeline(
    race_timeline: Dict[float, List[Tuple[int, str, float]]],
    figsize: Tuple[int, int] = (14, 8)
) -> Optional[plt.Figure]:
    """
    Plot how standings changed throughout the race (lap-by-lap).

    Shows driver position changes over time as an animated timeline.

    Args:
        race_timeline: Dict from get_race_timeline()
        figsize: Figure size

    Returns:
        matplotlib Figure object
    """
    if not MATPLOTLIB_AVAILABLE:
        return None

    if not race_timeline:
        print("No race timeline data")
        return None

    # Extract data
    laps = sorted(race_timeline.keys())
    all_drivers = set()
    for standings in race_timeline.values():
        for pos, driver, gap in standings:
            all_drivers.add(driver)

    all_drivers = sorted(all_drivers)

    # Create position history for each driver
    driver_positions = {driver: [] for driver in all_drivers}
    driver_gaps = {driver: [] for driver in all_drivers}

    for lap in laps:
        standings = race_timeline[lap]
        for position, driver, gap in standings:
            driver_positions[driver].append(position)
            driver_gaps[driver].append(gap)

    # Plot
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=figsize)

    colors = plt.cm.tab20(np.linspace(0, 1, len(all_drivers)))

    # Positions subplot
    for driver, color in zip(all_drivers, colors):
        if len(driver_positions[driver]) > 0:
            ax1.plot(laps, driver_positions[driver], marker="o", label=driver,
                    color=color, linewidth=2, markersize=4)

    ax1.set_ylabel("Position")
    ax1.set_title("Race Standings Timeline")
    ax1.invert_yaxis()  # Position 1 at top
    ax1.grid(True, alpha=0.3)
    ax1.legend(loc="upper left", fontsize=8, ncol=3)

    # Gap subplot
    for driver, color in zip(all_drivers, colors):
        if len(driver_gaps[driver]) > 0:
            ax2.plot(laps, driver_gaps[driver], marker="o", label=driver,
                    color=color, linewidth=2, markersize=4, alpha=0.7)

    ax2.set_xlabel("Lap Number")
    ax2.set_ylabel("Gap to Leader (m)")
    ax2.set_title("Gap to Leader Timeline")
    ax2.grid(True, alpha=0.3)
    ax2.axhline(y=0, color="black", linestyle="--", linewidth=1, alpha=0.5)

    plt.tight_layout()
    return fig


def plot_lap_performance(
    session_data,
    drivers: Optional[List[str]] = None,
    figsize: Tuple[int, int] = (14, 6)
) -> Optional[plt.Figure]:
    """
    Compare lap times across all drivers.

    Shows each driver's lap time progression through the race.

    Args:
        session_data: SessionData with telemetry
        drivers: List of drivers to compare
        figsize: Figure size

    Returns:
        matplotlib Figure object
    """
    if not MATPLOTLIB_AVAILABLE:
        return None

    if drivers is None:
        drivers = sorted(session_data.telemetry.keys())[:8]

    fig, ax = plt.subplots(figsize=figsize)

    colors = plt.cm.tab20(np.linspace(0, 1, len(drivers)))

    for driver, color in zip(drivers, colors):
        if driver not in session_data.telemetry:
            continue

        tel = session_data.telemetry[driver]

        if "LapNumber" not in tel.columns:
            continue

        # Get unique lap numbers and their max distance
        laps = []
        lap_times = []

        try:
            # Group by lap and get distance progression
            for lap_num in sorted(tel["LapNumber"].unique()):
                lap_data = tel.filter(tel["LapNumber"] == lap_num)
                if len(lap_data) > 1:
                    # Estimate lap time from distance progression
                    distances = lap_data["Distance"].to_list()
                    if len(distances) > 1:
                        lap_distance = max(distances) - min(distances)
                        # Rough estimate: lap distance / avg speed
                        speeds = lap_data["Speed"].to_list()
                        avg_speed = np.mean([s for s in speeds if s > 0])
                        if avg_speed > 0:
                            lap_time = (lap_distance / avg_speed) * 3.6  # Convert to seconds
                            laps.append(lap_num)
                            lap_times.append(lap_time)
        except:
            pass

        if len(laps) > 0:
            ax.plot(laps, lap_times, marker="o", label=driver, color=color,
                   linewidth=2, markersize=4)

    ax.set_xlabel("Lap Number")
    ax.set_ylabel("Estimated Lap Time (s)")
    ax.set_title("Lap Time Progression")
    ax.grid(True, alpha=0.3)
    ax.legend(fontsize=10, ncol=2)

    return fig


def create_race_summary_figure(
    session_data,
    circuit_data,
    position_interpolation,
    race_timeline,
    figsize: Tuple[int, int] = (16, 12)
) -> Optional[plt.Figure]:
    """
    Create a comprehensive race summary figure with multiple subplots.

    Args:
        session_data: SessionData
        circuit_data: CircuitData
        position_interpolation: DataFrame from get_position_interpolation()
        race_timeline: Dict from get_race_timeline()
        figsize: Figure size

    Returns:
        matplotlib Figure object
    """
    if not MATPLOTLIB_AVAILABLE:
        return None

    fig = plt.figure(figsize=figsize)
    gs = fig.add_gridspec(3, 2, hspace=0.3, wspace=0.3)

    # Track map with drivers at final position
    ax1 = fig.add_subplot(gs[0, :])
    track = circuit_data.circuit.track
    ax1.plot(track.x, track.y, "k-", linewidth=2)
    ax1.set_aspect("equal")
    ax1.set_title("Track Layout")
    ax1.grid(True, alpha=0.3)

    # Standings timeline
    ax2 = fig.add_subplot(gs[1, :])
    laps = sorted(race_timeline.keys())
    if laps:
        all_drivers = set()
        for standings in race_timeline.values():
            for pos, driver, gap in standings:
                all_drivers.add(driver)

        for driver in sorted(all_drivers):
            positions = []
            for lap in laps:
                standings = race_timeline[lap]
                for pos, d, gap in standings:
                    if d == driver:
                        positions.append(pos)
                        break

            if positions:
                ax2.plot(laps, positions, marker="o", label=driver, markersize=3, linewidth=1)

        ax2.set_ylabel("Position")
        ax2.set_title("Race Standings Timeline")
        ax2.invert_yaxis()
        ax2.grid(True, alpha=0.3)
        ax2.legend(fontsize=8, ncol=4)

    # Speed comparison (first 5 drivers)
    ax3 = fig.add_subplot(gs[2, 0])
    drivers = sorted(session_data.telemetry.keys())[:5]
    for driver in drivers:
        if driver in session_data.telemetry:
            tel = session_data.telemetry[driver]
            if "Distance" in tel.columns and "Speed" in tel.columns:
                # Sample every 10th point for clarity
                distances = tel["Distance"].to_list()[::10]
                speeds = tel["Speed"].to_list()[::10]
                ax3.plot(distances, speeds, marker=".", markersize=2, label=driver, linewidth=1)

    ax3.set_xlabel("Distance (m)")
    ax3.set_ylabel("Speed (km/h)")
    ax3.set_title("Speed Profile")
    ax3.grid(True, alpha=0.3)
    ax3.legend(fontsize=8)

    # Lap times
    ax4 = fig.add_subplot(gs[2, 1])
    for driver in drivers:
        if driver in session_data.telemetry:
            tel = session_data.telemetry[driver]
            if "LapNumber" in tel.columns:
                lap_nums = sorted(tel["LapNumber"].unique())[::3]  # Every 3rd lap
                ax4.scatter(lap_nums, [0] * len(lap_nums), label=driver, s=50)

    ax4.set_xlabel("Lap Number")
    ax4.set_title("Lap Completion")
    ax4.grid(True, alpha=0.3)
    ax4.legend(fontsize=8)

    plt.suptitle("F1 Race Analysis Summary", fontsize=16, fontweight="bold")

    return fig
