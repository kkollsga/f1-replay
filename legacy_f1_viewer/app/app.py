"""
F1 Viewer - Flask Application

App factory pattern for creating Flask app instances with race data.
No global state - app is fully configured at creation time.
"""

import json
import numpy as np
from datetime import timedelta


def convert_to_json_safe(obj):
    """Convert numpy arrays, timedelta, and NaN values to JSON-safe types."""
    if isinstance(obj, dict):
        return {k: convert_to_json_safe(v) for k, v in obj.items()}
    elif isinstance(obj, (list, tuple)):
        return [convert_to_json_safe(item) for item in obj]
    elif isinstance(obj, np.ndarray):
        return convert_to_json_safe(obj.tolist())
    elif isinstance(obj, timedelta):
        return obj.total_seconds()  # Convert timedelta to seconds
    elif isinstance(obj, (np.floating, float)):
        if np.isnan(obj):
            return None
        elif np.isinf(obj):
            return None
        return float(obj)
    elif isinstance(obj, np.integer):
        return int(obj)
    elif isinstance(obj, bool):
        return bool(obj)
    return obj


def create_app(race_instance, manager=None):
    """
    App factory that creates a Flask app instance.

    Args:
        race_instance: Race object with preprocessed data
        manager: RaceManager instance for accessing catalog (optional)

    Returns:
        Configured Flask app (not running)
    """
    from flask import Flask, render_template, jsonify

    app = Flask(__name__, template_folder='templates', static_folder='static')

    # Store race data and manager in app config (accessible in all routes)
    app.config['RACE'] = race_instance
    app.config['MANAGER'] = manager

    # =========================================================================
    # Routes
    # =========================================================================

    @app.route('/')
    def index():
        """Main page - render the track viewer."""
        race = app.config['RACE']

        race_info = {
            'year': race.year,
            'race_name': race.metadata['event_name'],
            'event_name': race.metadata['event_name'],
        }

        return render_template('index.html', race=race_info)

    @app.route('/api/track')
    def get_track():
        """API endpoint to get track outline data."""
        race = app.config['RACE']
        track = race.track_data

        # Convert numpy arrays to lists for JSON serialization
        track_data = {
            'x': track.get('X', []).tolist() if hasattr(track.get('X'), 'tolist') else [],
            'y': track.get('Y', []).tolist() if hasattr(track.get('Y'), 'tolist') else [],
        }

        # Include distance data for sector highlighting
        if track.get('Distance') is not None:
            track_data['distance'] = track['Distance'].tolist()

        return jsonify(track_data)

    @app.route('/api/race_info')
    def get_race_info():
        """API endpoint to get race information."""
        try:
            race = app.config['RACE']
            print(f"✓ DEBUG: Got race: {race.event_name}")
            print(f"  Metadata keys: {race.metadata.keys()}")
            print(f"  Drivers: {race.drivers}")

            # Get actual race start time (t0_date_utc) and local time
            t0_date_utc = race.t0_date_utc
            start_time_local = race.metadata.get('start_time_local', '')
            print(f"  t0_date_utc: {t0_date_utc}")
            print(f"  start_time_local: {start_time_local}")

            # Calculate GMT offset from UTC and local time
            gmt_offset = 0
            if t0_date_utc and start_time_local:
                try:
                    import pandas as pd
                    # Parse UTC time
                    if isinstance(t0_date_utc, str):
                        t0_utc = pd.Timestamp(t0_date_utc)
                    else:
                        t0_utc = t0_date_utc

                    # Parse local time
                    local_hours, local_minutes = int(start_time_local.split(':')[0]), int(start_time_local.split(':')[1])

                    # Calculate offset: local hours - UTC hours
                    gmt_offset = local_hours - t0_utc.hour
                    if gmt_offset > 12:
                        gmt_offset -= 24
                    elif gmt_offset < -12:
                        gmt_offset += 24
                except Exception as e:
                    print(f"  ⚠ Error calculating GMT offset: {e}")
                    gmt_offset = 0

            info = {
                'year': race.year,
                'race_name': race.event_name,
                'event_name': race.event_name,
                'location': race.location,
                'track_length': race.track_length,
                'fastest_lap': race.fastest_laps[0].get('lap') if race.fastest_laps else None,
                'total_laps': race.total_laps,
                'race_start_time': race.metadata.get('start_time', 0),
                't0_date': t0_date_utc,
                't0_time_local': start_time_local,
                't0_time_formatted': race.t0_time(),
                'gmt_offset': gmt_offset * 3600,  # Convert hours to seconds for frontend
                'global_min_time': race.metadata.get('time_range', {}).get('start', 0),
                'rotation': race.metadata.get('rotation', 0.0),
                'marshal_sectors': race.metadata.get('marshal_sectors', []),
            }

            print(f"✓ DEBUG: Returning race info")
            return jsonify(info)

        except Exception as e:
            print(f"✗ DEBUG: Exception in /api/race_info: {e}")
            import traceback
            traceback.print_exc()
            return jsonify({'error': str(e)}), 500

    @app.route('/api/pit_lane')
    def get_pit_lane():
        """API endpoint to get pit lane data."""
        race = app.config['RACE']
        pit_lane = race.pit_lane_data

        if pit_lane is None:
            return jsonify({'available': False, 'x': [], 'y': []})

        # Convert numpy arrays to lists for JSON serialization
        pit_lane_data = {
            'available': True,
            'x': pit_lane['X'].tolist(),
            'y': pit_lane['Y'].tolist(),
        }

        return jsonify(pit_lane_data)

    @app.route('/api/telemetry')
    def get_telemetry():
        """API endpoint to get telemetry data for all drivers."""
        try:
            race = app.config['RACE']
            telemetry = race.telemetry_data

            if not telemetry:
                print("⚠ DEBUG: telemetry_data is empty!")
                return jsonify({'error': 'No telemetry data available'}), 500

            print(f"✓ DEBUG: Found {len(telemetry)} drivers: {list(telemetry.keys())}")

            # Convert Polars DataFrames to lists for JSON serialization
            telemetry_data = {}

            # Get team colors from race metadata (extracted from FastF1)
            driver_colors = race.metadata.get('driver_colors', {})
            print(f"  Driver colors from metadata: {len(driver_colors)} drivers")

            for driver, df in telemetry.items():
                try:
                    # Polars DataFrame -> dict
                    if hasattr(df, 'to_dict'):
                        tel_dict = df.to_dict(as_series=False)
                        print(f"  ✓ {driver}: {len(tel_dict)} columns, {df.height} rows")
                    else:
                        print(f"  ⚠ {driver}: Not a Polars DataFrame, type={type(df)}")
                        tel_dict = {}

                    # Get driver color from metadata (extracted from FastF1)
                    driver_color = driver_colors.get(driver, '#CCCCCC')  # Default gray
                    driver_info = {
                        'abbreviation': driver,
                        'color': driver_color,
                    }

                    telemetry_data[driver] = {
                        'info': driver_info,
                        'telemetry': convert_to_json_safe(tel_dict)
                    }
                except Exception as e:
                    print(f"  ✗ {driver}: Error converting - {e}")
                    return jsonify({'error': f'Failed to convert {driver}: {str(e)}'}), 500

            # Use convert_to_json_safe to handle any remaining non-JSON-serializable objects
            safe_data = convert_to_json_safe(telemetry_data)
            print(f"✓ DEBUG: Returning telemetry for {len(safe_data)} drivers")
            return jsonify(safe_data)

        except Exception as e:
            print(f"✗ DEBUG: Exception in /api/telemetry: {e}")
            import traceback
            traceback.print_exc()
            return jsonify({'error': str(e)}), 500

    @app.route('/api/schedule/<int:year>')
    def get_schedule(year):
        """API endpoint to get F1 season schedule."""
        manager = app.config.get('MANAGER')

        if not manager:
            return jsonify({'error': 'Manager not available'}), 500

        try:
            season_info = manager.get_season(year)
            if not season_info:
                return jsonify({'error': f'Season {year} not found'}), 404

            races = []
            for race_info in season_info.races:
                race = {
                    'round': race_info.round_number,
                    'name': race_info.event_name,
                    'event_name': race_info.event_name,
                    'location': race_info.location,
                    'country': race_info.country,
                    'date': race_info.date,
                }
                races.append(race)

            return jsonify({'races': races})
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @app.route('/api/track_status')
    def get_track_status():
        """API endpoint to get track status timeline."""
        race = app.config['RACE']
        track_status = race.track_status_events
        safe_data = convert_to_json_safe(track_status)

        return jsonify(safe_data)

    @app.route('/api/race_control')
    def get_race_control():
        """API endpoint to get race control messages."""
        race = app.config['RACE']
        race_control = race.race_control_messages
        safe_data = convert_to_json_safe(race_control)

        return jsonify(safe_data)

    @app.route('/api/weather')
    def get_weather():
        """API endpoint to get weather data."""
        race = app.config['RACE']
        weather = race.weather_data
        safe_data = convert_to_json_safe(weather)

        return jsonify(safe_data)

    @app.route('/api/fastest_lap_history')
    def get_fastest_lap_history():
        """API endpoint to get fastest lap history."""
        race = app.config['RACE']
        fastest_laps = race.fastest_laps
        safe_data = convert_to_json_safe(fastest_laps)

        return jsonify(safe_data)

    @app.route('/api/intervals')
    def get_intervals():
        """API endpoint to get interval data (gap to leader per lap)."""
        race = app.config['RACE']
        intervals = race.intervals_per_lap
        safe_data = convert_to_json_safe(intervals)

        return jsonify(safe_data)

    @app.route('/api/sector_crossings')
    def get_sector_crossings():
        """API endpoint to get sector crossing times."""
        # Sector crossings endpoint for future use
        # Currently not requested by frontend, returns empty dict
        return jsonify({})

    @app.route('/api/position_history')
    def get_position_history():
        """API endpoint to get position history (standings at intervals)."""
        race = app.config['RACE']
        position_history = race.position_history
        safe_data = convert_to_json_safe(position_history)

        return jsonify(safe_data)

    return app
