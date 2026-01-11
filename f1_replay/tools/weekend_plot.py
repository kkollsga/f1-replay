"""
Weekend Plot - Poster-style circuit map visualization.

Extracted from RaceWeekend.plot() for cleaner separation of concerns.
"""

import numpy as np

from f1_replay.models import CircuitData, EventInfo
from f1_replay.services import TrackTransformer


def _format_date_range(start_date: str, end_date: str) -> str:
    """Format event date range like '23-26 May'."""
    from datetime import datetime
    try:
        end = datetime.strptime(end_date[:10], "%Y-%m-%d")
        start = datetime.strptime(start_date[:10], "%Y-%m-%d") if start_date else None

        if start and start.month == end.month:
            return f"{start.day}-{end.day} {end.strftime('%b')}"
        elif start:
            return f"{start.day} {start.strftime('%b')} - {end.day} {end.strftime('%b')}"
        else:
            return f"{end.day} {end.strftime('%b')}"
    except (ValueError, TypeError):
        return end_date[:10] if end_date else ""


def plot_weekend(
    circuit: CircuitData,
    event: EventInfo,
    figsize: tuple = (12, 10),
    color_mode: str = 'white',
    save_path: str = None,
    dpi: int = 150,
    track_width: float = 4,
):
    """
    Generate poster-style circuit map.

    Args:
        circuit: CircuitData with track geometry (rotation and pit_lane from here)
        event: EventInfo with name, location, dates, sessions, timezone
        figsize: Figure size (width, height)
        color_mode: Track coloring - 'white', 'sectors', 'speed', 'throttle', 'height'
        save_path: Save to file instead of displaying
        dpi: Resolution for saved file
        track_width: Line width for track (default 4)

    Returns:
        matplotlib Figure
    """
    import matplotlib.pyplot as plt
    import matplotlib.patheffects as pe
    from matplotlib.collections import LineCollection
    from datetime import datetime

    # Extract data from event
    year = event.year
    timezone = event.timezone_offset or 'Local'

    # Colors
    BG_COLOR = '#1a1a2e'
    TRACK_COLOR = '#ffffff'
    TEXT_COLOR = '#ffffff'
    DIM_COLOR = '#ffffff'
    # Vibrant sector colors - sequential rainbow
    SECTOR_COLORS = [
        '#F93822', '#FF6A13', '#F2A900', '#FEDD00', '#C4D600', '#78BE20',
        '#26D07C', '#00C1D5', '#009CDE', '#0072CE', '#685BC7', '#9063CD',
        '#C724B1', '#E40046'
    ]

    raw_track_x = circuit.track.x
    raw_track_y = circuit.track.y

    if raw_track_x is None or len(raw_track_x) == 0:
        print("No track data available")
        return None

    fig = plt.figure(figsize=figsize, facecolor=BG_COLOR)
    ax = fig.add_axes([0.01, 0.27, 0.84, 0.59])
    ax.set_facecolor(BG_COLOR)

    # Apply rotation using TrackTransformer
    rot_deg = circuit.rotation
    transformer = TrackTransformer(
        raw_track_x, raw_track_y,
        rotation_deg=rot_deg or 0.0,
        pit_x=circuit.pit_lane.x if circuit.pit_lane else None,
        pit_y=circuit.pit_lane.y if circuit.pit_lane else None
    )
    track_x, track_y = transformer.get_rotated()

    # Shadow effect
    shadow_offset = 30
    shadow_x = track_x + shadow_offset
    shadow_y = track_y - shadow_offset
    ax.plot(shadow_x, shadow_y, color='black', linewidth=track_width * 1.6, alpha=0.3,
           solid_capstyle='round', zorder=1)

    # Plot track based on color mode
    if color_mode == 'sectors' and circuit.track.marshal_sectors:
        for sector_num, sx, sy in circuit.track.get_all_sectors():
            if rot_deg:
                sx, sy = transformer.rotate_points(sx, sy)
            color_idx = ((sector_num - 1) * 3) % len(SECTOR_COLORS)
            ax.plot(sx, sy, color=SECTOR_COLORS[color_idx], linewidth=track_width,
                   solid_capstyle='round', zorder=4)

    elif color_mode == 'speed' and circuit.track.speed is not None:
        track_x_closed = np.append(track_x, track_x[0])
        track_y_closed = np.append(track_y, track_y[0])
        points = np.array([track_x_closed, track_y_closed]).T.reshape(-1, 1, 2)
        segments = np.concatenate([points[:-1], points[1:]], axis=1)
        speed = circuit.track.speed
        norm = plt.Normalize(speed.min(), speed.max())
        lc = LineCollection(segments, cmap='plasma', norm=norm, linewidth=track_width,
                           capstyle='round', zorder=4)
        lc.set_array(speed)
        ax.add_collection(lc)

        max_idx = np.argmax(speed)
        min_idx = np.argmin(speed)

        def get_label_params(idx, distance=400):
            n = len(track_x)
            i_prev = (idx - 1) % n
            i_next = (idx + 1) % n
            dx = track_x[i_next] - track_x[i_prev]
            dy = track_y[i_next] - track_y[i_prev]
            length = np.sqrt(dx*dx + dy*dy)
            if length == 0:
                return track_x[idx] + distance, track_y[idx], 0
            tx, ty = dx / length, dy / length
            perp_left = (ty, -tx)
            perp_right = (-ty, tx)

            def min_track_distance(lx, ly):
                dists = (track_x - lx)**2 + (track_y - ly)**2
                return np.sqrt(np.min(dists))

            best_pos = None
            best_clearance = -1
            for perp_x, perp_y in [perp_left, perp_right]:
                for tang_offset in [50, -50, 100, -100, 0]:
                    lx = track_x[idx] + perp_x * distance + tx * tang_offset
                    ly = track_y[idx] + perp_y * distance + ty * tang_offset
                    clearance = min_track_distance(lx, ly)
                    if clearance > best_clearance:
                        best_clearance = clearance
                        best_pos = (lx, ly, tang_offset)

            label_x, label_y, _ = best_pos
            angle = np.degrees(np.arctan2(dy, dx))
            if angle > 90:
                angle -= 180
            elif angle < -90:
                angle += 180
            return label_x, label_y, angle

        label_x, label_y, angle = get_label_params(max_idx)
        ax.plot([track_x[max_idx], label_x], [track_y[max_idx], label_y],
               color='white', linewidth=0.8, alpha=0.5, zorder=10)
        ax.text(label_x, label_y, f'{speed[max_idx]:.0f} km/h',
               fontsize=11, color='white', fontweight='light',
               ha='center', va='center', rotation=angle, zorder=11)

        label_x, label_y, angle = get_label_params(min_idx)
        ax.plot([track_x[min_idx], label_x], [track_y[min_idx], label_y],
               color='white', linewidth=0.8, alpha=0.5, zorder=10)
        ax.text(label_x, label_y, f'{speed[min_idx]:.0f} km/h',
               fontsize=11, color='white', fontweight='light',
               ha='center', va='center', rotation=angle, zorder=11)

    elif color_mode == 'throttle' and circuit.track.brake is not None:
        brake = circuit.track.brake
        throttle = circuit.track.throttle if circuit.track.throttle is not None else np.ones_like(brake) * 100

        track_x_closed = np.append(track_x, track_x[0])
        track_y_closed = np.append(track_y, track_y[0])
        points = np.array([track_x_closed, track_y_closed]).T.reshape(-1, 1, 2)
        segments = np.concatenate([points[:-1], points[1:]], axis=1)

        brake_max = brake.max() if brake.max() > 0 else 1
        brake_norm = np.clip(brake / brake_max, 0, 1) if brake_max <= 1 else np.clip(brake / 100.0, 0, 1)
        brake_colors = np.zeros((len(segments), 4))
        brake_colors[:, 0] = 1.0
        brake_colors[:, 3] = brake_norm

        lc_brake = LineCollection(segments, colors=brake_colors, linewidth=track_width,
                                 capstyle='round', zorder=3)
        ax.add_collection(lc_brake)

        throttle_norm = np.clip(throttle / 100.0, 0, 1)
        throttle_colors = np.zeros((len(segments), 4))
        throttle_colors[:, :3] = 1.0
        throttle_colors[:, 3] = throttle_norm

        lc_throttle = LineCollection(segments, colors=throttle_colors, linewidth=track_width,
                                    capstyle='round', zorder=4)
        ax.add_collection(lc_throttle)

    elif color_mode == 'height' and circuit.track.z is not None:
        from matplotlib.colors import LinearSegmentedColormap

        contour_settings = {
            'enabled': True,
            'interval': 1,
            'major_every': 10,
            'width': 100,
            'linewidth': 1,
            'linewidth_major': 2,
            'color': 'black',
            'alpha': 0.5,
            'alpha_major': 0.8,
        }

        z_dm = circuit.track.z
        z_m = z_dm / 10.0
        ref_z = z_m[0]
        z_normalized = 0.5 + (z_m - ref_z) / 200.0
        z_normalized = np.clip(z_normalized, 0, 1)

        colors = [
            (0.0, '#22c55e'),
            (0.25, '#3b82f6'),
            (0.5, '#ffffff'),
            (0.75, '#ef4444'),
            (1.0, '#eab308'),
        ]
        cmap = LinearSegmentedColormap.from_list('elevation',
            [(pos, color) for pos, color in colors])

        track_x_closed = np.append(track_x, track_x[0])
        track_y_closed = np.append(track_y, track_y[0])
        points = np.array([track_x_closed, track_y_closed]).T.reshape(-1, 1, 2)
        segments = np.concatenate([points[:-1], points[1:]], axis=1)

        lc = LineCollection(segments, cmap=cmap, norm=plt.Normalize(0, 1),
                           linewidth=track_width, capstyle='round', zorder=4)
        lc.set_array(z_normalized)
        ax.add_collection(lc)

        max_idx = np.argmax(z_m)
        min_idx = np.argmin(z_m)
        max_diff = z_m[max_idx] - ref_z
        min_diff = z_m[min_idx] - ref_z

        def get_label_params(idx, distance=400):
            n = len(track_x)
            i_prev = (idx - 1) % n
            i_next = (idx + 1) % n
            dx = track_x[i_next] - track_x[i_prev]
            dy = track_y[i_next] - track_y[i_prev]
            length = np.sqrt(dx*dx + dy*dy)
            if length == 0:
                return track_x[idx] + distance, track_y[idx], 0
            tx, ty = dx / length, dy / length
            perp_left = (ty, -tx)
            perp_right = (-ty, tx)

            def min_track_distance(lx, ly):
                dists = (track_x - lx)**2 + (track_y - ly)**2
                return np.sqrt(np.min(dists))

            best_pos = None
            best_clearance = -1
            for perp_x, perp_y in [perp_left, perp_right]:
                for tang_offset in [50, -50, 100, -100, 0]:
                    lx = track_x[idx] + perp_x * distance + tx * tang_offset
                    ly = track_y[idx] + perp_y * distance + ty * tang_offset
                    clearance = min_track_distance(lx, ly)
                    if clearance > best_clearance:
                        best_clearance = clearance
                        best_pos = (lx, ly, tang_offset)

            label_x, label_y, _ = best_pos
            angle = np.degrees(np.arctan2(dy, dx))
            if angle > 90:
                angle -= 180
            elif angle < -90:
                angle += 180
            return label_x, label_y, angle

        track_dist = circuit.track.distance
        lap_dist = circuit.track.lap_distance
        min_dist_from_sf = 100

        def far_from_start_finish(idx):
            d = track_dist[idx]
            return d > min_dist_from_sf and d < (lap_dist - min_dist_from_sf)

        abs_max = abs(max_diff)
        abs_min = abs(min_diff)
        show_max = True
        show_min = True
        if abs_max > abs_min:
            if abs_min < 1:
                show_min = False
        elif abs_min > abs_max:
            if abs_max < 1:
                show_max = False

        if show_max and far_from_start_finish(max_idx):
            label_x, label_y, angle = get_label_params(max_idx)
            ax.plot([track_x[max_idx], label_x], [track_y[max_idx], label_y],
                   color='white', linewidth=0.8, alpha=0.5, zorder=10)
            ax.text(label_x, label_y, f'+{max_diff:.0f}m',
                   fontsize=11, color='white', fontweight='light',
                   ha='center', va='center', rotation=angle, zorder=11)

        if show_min and far_from_start_finish(min_idx):
            label_x, label_y, angle = get_label_params(min_idx)
            ax.plot([track_x[min_idx], label_x], [track_y[min_idx], label_y],
                   color='white', linewidth=0.8, alpha=0.5, zorder=10)
            ax.text(label_x, label_y, f'{min_diff:.0f}m',
                   fontsize=11, color='white', fontweight='light',
                   ha='center', va='center', rotation=angle, zorder=11)

        # Contour lines
        if contour_settings['enabled']:
            contour_interval = contour_settings['interval']
            major_every = contour_settings.get('major_every')
            z_min_rounded = np.floor(z_m.min() / contour_interval) * contour_interval
            z_max_rounded = np.ceil(z_m.max() / contour_interval) * contour_interval
            contour_levels = np.arange(z_min_rounded, z_max_rounded + contour_interval, contour_interval)

            minor_lines = []
            major_lines = []
            track_half_width = contour_settings['width']
            major_interval = contour_interval * major_every if major_every else None
            crossing_threshold = 20
            hill_threshold = 2
            n_pts = len(z_m)

            track_x_next = np.roll(track_x, -1)
            track_y_next = np.roll(track_y, -1)
            seg_dx = track_x_next - track_x
            seg_dy = track_y_next - track_y
            seg_len = np.sqrt(seg_dx**2 + seg_dy**2)
            seg_len[seg_len == 0] = 1

            z1 = z_m
            z2 = np.roll(z_m, -1)
            z_diff = z2 - z1
            z_diff[z_diff == 0] = 1e-10

            for level in contour_levels:
                is_major = major_interval and abs(level % major_interval) < 0.01
                ascending = (z1 <= level) & (level < z2)
                descending = (z2 <= level) & (level < z1)
                crossing_mask = ascending | descending

                if not np.any(crossing_mask):
                    continue

                crossing_idx = np.where(crossing_mask)[0]
                t_values = (level - z1[crossing_idx]) / z_diff[crossing_idx]
                is_ascending = ascending[crossing_idx]

                if len(crossing_idx) == 0:
                    continue

                gaps = np.diff(crossing_idx)
                gaps = np.minimum(gaps, n_pts - gaps)
                group_breaks = np.where(gaps > crossing_threshold)[0] + 1
                groups = np.split(np.arange(len(crossing_idx)), group_breaks)

                for group in groups:
                    if len(group) == 0:
                        continue

                    group_crossing_idx = crossing_idx[group]
                    group_t = t_values[group]
                    group_dirs = is_ascending[group]

                    if len(group) == 1:
                        draw_idx = [0]
                    elif len(group) == 2:
                        if group_dirs[0] != group_dirs[-1]:
                            draw_idx = [0, -1]
                        else:
                            draw_idx = [0]
                    else:
                        first_dir = group_dirs[0]
                        last_dir = group_dirs[-1]
                        first_idx = group_crossing_idx[0]
                        last_idx = group_crossing_idx[-1]

                        if first_idx <= last_idx:
                            range_z = z_m[first_idx:last_idx+1]
                        else:
                            range_z = np.concatenate([z_m[first_idx:], z_m[:last_idx+1]])

                        peak_above = range_z.max() - level
                        valley_below = level - range_z.min()
                        is_hill = (first_dir != last_dir and
                                  (peak_above > hill_threshold or valley_below > hill_threshold))

                        if is_hill:
                            draw_idx = [0, -1]
                        else:
                            draw_idx = [len(group) // 2]

                    for di in draw_idx:
                        i = group_crossing_idx[di]
                        t = group_t[di]
                        cont_x = track_x[i] + t * seg_dx[i]
                        cont_y = track_y[i] + t * seg_dy[i]
                        perp_x = -seg_dy[i] / seg_len[i]
                        perp_y = seg_dx[i] / seg_len[i]
                        x1 = cont_x - perp_x * track_half_width
                        y1 = cont_y - perp_y * track_half_width
                        x2 = cont_x + perp_x * track_half_width
                        y2 = cont_y + perp_y * track_half_width

                        if is_major:
                            major_lines.append([(x1, y1), (x2, y2)])
                        else:
                            minor_lines.append([(x1, y1), (x2, y2)])

            if minor_lines:
                lc_minor = LineCollection(minor_lines, colors=contour_settings['color'],
                    linewidth=contour_settings['linewidth'], alpha=contour_settings['alpha'], zorder=6)
                ax.add_collection(lc_minor)

            if major_lines:
                lc_major = LineCollection(major_lines, colors=contour_settings['color'],
                    linewidth=contour_settings.get('linewidth_major', contour_settings['linewidth']),
                    alpha=contour_settings.get('alpha_major', contour_settings['alpha']), zorder=7)
                ax.add_collection(lc_major)

    else:
        ax.plot(track_x, track_y, color=TRACK_COLOR, linewidth=track_width,
               solid_capstyle='round', zorder=4)

    # Pit lane (always show if available)
    if circuit.pit_lane and circuit.pit_lane.x is not None:
        pit_rotated = transformer.get_rotated_pit()
        if pit_rotated:
            pit_x, pit_y = pit_rotated
        else:
            pit_x, pit_y = circuit.pit_lane.x, circuit.pit_lane.y
        ax.plot(pit_x, pit_y, color=TRACK_COLOR, linewidth=track_width * 0.5, alpha=0.4,
               solid_capstyle='round', zorder=3)

    # Start/finish line
    if len(track_x) > 1:
        dx, dy = track_x[1] - track_x[0], track_y[1] - track_y[0]
        length = np.sqrt(dx*dx + dy*dy)
        if length > 0:
            perp_x, perp_y = -dy / length, dx / length
            x0, y0 = track_x[0], track_y[0]
            ax.plot([x0 - perp_x * 80, x0 + perp_x * 80],
                   [y0 - perp_y * 80, y0 + perp_y * 80],
                   color=TEXT_COLOR, linewidth=3, zorder=10)

    # Direction arrow
    if circuit.direction_arrow is not None:
        arrow = circuit.direction_arrow
        arrow_x, arrow_y = arrow.x, arrow.y
        ax_dir, ay_dir = arrow.dx, arrow.dy
        if rot_deg:
            # Rotate position using transformer
            pos_x, pos_y = transformer.rotate_points(np.array([arrow.x]), np.array([arrow.y]))
            arrow_x, arrow_y = float(pos_x[0]), float(pos_y[0])
            # Rotate direction vector (pure rotation, no translation)
            angle_rad = np.radians(rot_deg)
            cos_a, sin_a = np.cos(angle_rad), np.sin(angle_rad)
            ax_dir = cos_a * arrow.dx - sin_a * arrow.dy
            ay_dir = sin_a * arrow.dx + cos_a * arrow.dy

        perp_offset = 200
        start_offset = 40
        arrow_length = 200
        perp_x, perp_y = -ay_dir, ax_dir
        to_arrow_x = arrow_x - track_x[0]
        to_arrow_y = arrow_y - track_y[0]
        side = np.sign(to_arrow_x * perp_x + to_arrow_y * perp_y)
        if side == 0:
            side = 1

        arrow_start_x = track_x[0] + ax_dir * start_offset + perp_x * perp_offset * side
        arrow_start_y = track_y[0] + ay_dir * start_offset + perp_y * perp_offset * side
        arrow_end_x = arrow_start_x + ax_dir * arrow_length
        arrow_end_y = arrow_start_y + ay_dir * arrow_length

        ax.plot([arrow_start_x, arrow_end_x], [arrow_start_y, arrow_end_y],
               color=TEXT_COLOR, linewidth=1.5, solid_capstyle='butt', zorder=11)

        head_size = 70
        head_angle = 25
        angle_rad = np.radians(head_angle)
        cos_h, sin_h = np.cos(angle_rad), np.sin(angle_rad)
        left_dx = -(cos_h * ax_dir - sin_h * ay_dir)
        left_dy = -(sin_h * ax_dir + cos_h * ay_dir)
        right_dx = -(cos_h * ax_dir + sin_h * ay_dir)
        right_dy = -(-sin_h * ax_dir + cos_h * ay_dir)

        ax.plot([arrow_end_x, arrow_end_x + left_dx * head_size],
               [arrow_end_y, arrow_end_y + left_dy * head_size],
               color=TEXT_COLOR, linewidth=1.5, solid_capstyle='round', zorder=11)
        ax.plot([arrow_end_x, arrow_end_x + right_dx * head_size],
               [arrow_end_y, arrow_end_y + right_dy * head_size],
               color=TEXT_COLOR, linewidth=1.5, solid_capstyle='round', zorder=11)

    ax.set_aspect('equal')
    ax.axis('off')

    # Axis limits with centering
    axes_width = 0.84 * figsize[0]
    axes_height = 0.59 * figsize[1]
    axes_aspect = axes_width / axes_height

    x_range = track_x.max() - track_x.min()
    y_range = track_y.max() - track_y.min()
    track_aspect = x_range / y_range if y_range > 0 else 1

    x_center = (track_x.max() + track_x.min()) / 2
    y_center = (track_y.max() + track_y.min()) / 2

    margin = 0.005
    x_range *= (1 + margin)
    y_range *= (1 + margin)

    if track_aspect < axes_aspect:
        x_range = y_range * axes_aspect
    else:
        y_range = x_range / axes_aspect

    ax.set_xlim(x_center - x_range / 2, x_center + x_range / 2)
    ax.set_ylim(y_center - y_range / 2, y_center + y_range / 2)

    # === HEADER ===
    fig.text(0.04, 0.96, f"{year} {event.name}".upper(),
            fontsize=24, fontweight='bold', color=TEXT_COLOR,
            ha='left', va='top', fontfamily='sans-serif',
            path_effects=[pe.withStroke(linewidth=2, foreground=BG_COLOR)])

    length_str = f"{circuit.circuit_length:,.0f}".replace(',', ' ')
    date_str = _format_date_range(event.start_date, event.end_date)
    subtitle = f"{event.circuit_name}  |  {length_str} m"
    if date_str:
        subtitle += f"  |  {date_str}"
    fig.text(0.04, 0.915, subtitle,
            fontsize=12, color=TEXT_COLOR, alpha=0.9,
            ha='left', va='top', fontfamily='sans-serif')

    if color_mode:
        mode_labels = {
            'speed': 'Colored by speed',
            'throttle': 'Colored by throttle',
            'height': 'Colored by elevation'
        }
        mode_label = mode_labels.get(color_mode, f'Colored by {color_mode}')
        fig.text(0.04, 0.885, mode_label,
                fontsize=10, color=DIM_COLOR, alpha=0.5,
                ha='left', va='top', fontfamily='sans-serif',
                style='italic')

    # === SCHEDULE ===
    schedule_x = 0.86
    fig.text(schedule_x, 0.86, "Schedule",
            fontsize=12, fontweight='bold', color=TEXT_COLOR,
            ha='left', va='top', fontfamily='sans-serif')
    fig.text(schedule_x, 0.835, timezone,
            fontsize=9, color=DIM_COLOR, alpha=0.4,
            ha='left', va='top', fontfamily='sans-serif')

    schedule_y = 0.79
    for session in event.sessions:
        session_name = session.name
        session_date = session.date
        if session_name and session_date:
            try:
                dt = datetime.fromisoformat(session_date.replace(' ', 'T'))
                day_abbr = dt.strftime('%a')
                time_str = dt.strftime('%H:%M')
                fig.text(schedule_x, schedule_y, session_name,
                        fontsize=10, color=TEXT_COLOR, alpha=0.9,
                        ha='left', va='top', fontfamily='sans-serif')
                fig.text(schedule_x, schedule_y - 0.018, f"{day_abbr} {time_str}",
                        fontsize=9, color=DIM_COLOR, alpha=0.4,
                        ha='left', va='top', fontfamily='sans-serif')
                schedule_y -= 0.042
            except (ValueError, TypeError):
                pass

    # Footer
    if circuit.corners > 0:
        fig.text(0.04, 0.02, f"{circuit.corners} turns",
                fontsize=10, color=DIM_COLOR, alpha=0.4,
                ha='left', va='bottom', fontfamily='sans-serif')
    plt.close(fig)

    if save_path:
        fig.savefig(save_path, dpi=dpi, facecolor=BG_COLOR,
                   edgecolor='none', bbox_inches='tight')
        print(f"Saved to {save_path}")

    return fig
