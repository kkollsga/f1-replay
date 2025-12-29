"""
Flask app factory for F1 Race Viewer API.

Creates Flask app with 3 main endpoints matching 3-tier backend architecture:
- GET /api/seasons          - Season catalog
- GET /api/weekend/<year>/<round>  - Weekend metadata + circuit geometry
- GET /api/session/<year>/<round>/<session_type> - Complete session data
"""

from flask import Flask, jsonify, request, render_template
from typing import Optional
import math

try:
    from flask_cors import CORS
    HAS_CORS = True
except ImportError:
    HAS_CORS = False

from f1_replay.data_loader import DataLoader
from f1_replay.session import Session
from f1_replay.api.serializers import (
    to_json_safe,
    serialize_telemetry,
    serialize_track_geometry,
    serialize_events,
    serialize_rain_events,
    serialize_position_history,
    serialize_fastest_laps,
)


def create_app(data_loader: DataLoader, current_session: Optional[Session] = None, force_update: bool = False) -> Flask:
    """
    Create and configure Flask app.

    Args:
        data_loader: DataLoader instance for accessing cached data
        current_session: Optional Session to pre-load (used by Manager.race())
        force_update: If True, force reprocessing of all race data (ignore cache)

    Returns:
        Configured Flask app
    """
    app = Flask(__name__,
                template_folder='templates',
                static_folder='static',
                static_url_path='/static')

    # Configuration
    app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0  # Disable caching for development
    app.config['JSON_SORT_KEYS'] = False

    # Store data loader in config
    app.config['DATA_LOADER'] = data_loader
    app.config['CURRENT_SESSION'] = current_session
    app.config['FORCE_UPDATE'] = force_update

    # In-memory cache for loaded sessions (avoids repeated pickle loading)
    app.config['SESSION_CACHE'] = {}  # key: (year, round, session_type) -> Session
    app.config['WEEKEND_CACHE'] = {}  # key: (year, round) -> (F1Weekend, RaceWeekend)

    # Enable CORS for development (if available)
    if HAS_CORS:
        CORS(app)

    # =========================================================================
    # API Routes
    # =========================================================================

    @app.route('/api/seasons', methods=['GET'])
    def get_seasons():
        """
        Get complete season catalog.

        Returns:
            {
                "seasons": {
                    "2024": {
                        "total_rounds": 24,
                        "rounds": [...]
                    }
                },
                "last_updated": "2024-12-21T..."
            }
        """
        try:
            seasons = data_loader.load_seasons()
            if seasons is None:
                return jsonify({'error': 'Could not load seasons'}), 500

            # Build response
            seasons_dict = {}
            for year, f1_year in seasons.years.items():
                rounds = []
                for round_info in f1_year.rounds:
                    rounds.append({
                        'round': round_info.round_number,
                        'event_name': round_info.event_name,
                        'location': round_info.location,
                        'country': round_info.country,
                        'circuit_name': round_info.circuit_name,
                        'date': round_info.date,
                        'available_sessions': round_info.available_sessions
                    })

                seasons_dict[str(year)] = {
                    'total_rounds': f1_year.total_rounds,
                    'rounds': rounds
                }

            return jsonify({
                'seasons': seasons_dict,
                'last_updated': seasons.last_updated
            }), 200

        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @app.route('/api/weekend/<int:year>/<int:round_num>', methods=['GET'])
    def get_weekend(year: int, round_num: int):
        """
        Get weekend metadata + circuit geometry.

        Args:
            year: Season year
            round_num: Round number

        Returns:
            {
                "metadata": {...},
                "circuit": {
                    "track": {...},
                    "pit_lane": {...},
                    "circuit_length": float,
                    "rotation": float,
                    "corners": int,
                    "track_segments": [...]
                }
            }
        """
        try:
            cache_key = (year, round_num)

            # Check in-memory cache first
            if cache_key in app.config['WEEKEND_CACHE']:
                weekend_data = app.config['WEEKEND_CACHE'][cache_key]
            else:
                weekend_data = data_loader.load_weekend(year, round_num, force_reprocess=app.config.get('FORCE_UPDATE', False))
                if weekend_data is None:
                    return jsonify({'error': f'Weekend {year}/{round_num} not found'}), 404
                # Cache for future requests
                app.config['WEEKEND_CACHE'][cache_key] = weekend_data

            metadata = weekend_data.metadata

            # Build response
            return jsonify({
                'metadata': {
                    'year': metadata.year,
                    'round': metadata.round_number,
                    'event_name': metadata.event_name,
                    'location': metadata.location,
                    'country': metadata.country,
                    'circuit_name': metadata.circuit_name,
                    'timezone': metadata.timezone,
                    'event_date': metadata.event_date,
                    'available_sessions': metadata.available_sessions
                },
                'circuit': {
                    'track': serialize_track_geometry(weekend_data.circuit.track),
                    'pit_lane': (
                        serialize_track_geometry(weekend_data.circuit.pit_lane)
                        if weekend_data.circuit.pit_lane is not None
                        else None
                    ),
                    'circuit_length': weekend_data.circuit.circuit_length,
                    'rotation': weekend_data.circuit.rotation,  # In degrees (from FastF1)
                    'corners': weekend_data.circuit.corners,
                    'track_segments': [
                        {
                            'name': seg.name,
                            'start_distance': seg.start_distance,
                            'end_distance': seg.end_distance,
                            'segment_type': seg.segment_type,
                            'metadata': seg.metadata
                        }
                        for seg in weekend_data.circuit.track_segments
                    ]
                }
            }), 200

        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @app.route('/api/session/<int:year>/<int:round_num>/<session_type>', methods=['GET'])
    def get_session(year: int, round_num: int, session_type: str):
        """
        Get complete session data (optimized payload).

        Args:
            year: Season year
            round_num: Round number
            session_type: Session type ('R', 'Q', 'FP1', etc.)

        Query parameters:
            - telemetry_fields: Comma-separated list of telemetry fields (optional)
              Default: session_time, LapNumber, X, Y, Distance, progress, TimeToDriverAhead

        Returns:
            {
                "metadata": {...},
                "telemetry": {driver: {field: [values]}},
                "events": {...},
                "results": {...},
                "order": [...],
                "rain_events": [...]
            }
        """
        try:
            cache_key = (year, round_num, session_type)

            # Check if we have pre-loaded session from Manager.race()
            if (app.config['CURRENT_SESSION'] is not None and
                app.config['CURRENT_SESSION'].year == year and
                app.config['CURRENT_SESSION'].round_number == round_num and
                app.config['CURRENT_SESSION'].session_type == session_type):
                session = app.config['CURRENT_SESSION']
            # Check in-memory cache
            elif cache_key in app.config['SESSION_CACHE']:
                session = app.config['SESSION_CACHE'][cache_key]
            else:
                # Load from data loader
                from f1_replay.race_weekend import RaceWeekend
                force_reprocess = app.config.get('FORCE_UPDATE', False)
                weekend_data = data_loader.load_weekend(year, round_num, force_reprocess=force_reprocess)
                if weekend_data is None:
                    return jsonify({'error': f'Weekend {year}/{round_num} not found'}), 404

                weekend = RaceWeekend(weekend_data)

                session_data = data_loader.load_session(year, round_num, session_type, force_reprocess=force_reprocess)
                if session_data is None:
                    return jsonify({'error': f'Session {year}/{round_num}/{session_type} not found'}), 404

                session = Session(session_data, weekend)
                # Cache for future requests
                app.config['SESSION_CACHE'][cache_key] = session

            # Get optional telemetry fields from query params
            telemetry_fields = None
            if 'telemetry_fields' in request.args:
                telemetry_fields = request.args.get('telemetry_fields').split(',')

            metadata = session._data.metadata

            # Build response
            return jsonify({
                'metadata': {
                    'session_type': session.session_type,
                    'year': session.year,
                    'round': session.round_number,
                    'event_name': session.event_name,
                    'drivers': session.drivers,
                    'driver_info': session.driver_info,
                    'dnf_drivers': metadata.dnf_drivers,
                    'track_length': session.track_length,
                    'total_laps': session.total_laps,
                    't0_date_utc': session.t0_date_utc,
                    'start_time_local': session.start_time_local
                },
                'telemetry': serialize_telemetry(session.telemetry, fields=telemetry_fields),
                'events': serialize_events(session._data.events),
                'results': {
                    'fastest_laps': serialize_fastest_laps(session.fastest_laps),
                    'position_history': serialize_position_history(session.position_history)
                },
                'order': to_json_safe(session.order),
                'rain_events': serialize_rain_events(session.rain_events)
            }), 200

        except Exception as e:
            return jsonify({'error': str(e)}), 500

    # =========================================================================
    # UI Routes
    # =========================================================================

    @app.route('/', methods=['GET'])
    def index():
        """Serve main viewer page with current session context."""
        # Check for year/round in URL params first (from frontend navigation)
        year = request.args.get('year', type=int)
        round_num = request.args.get('round', type=int)

        # Fall back to pre-loaded session if no URL params
        if not year or not round_num:
            current_session = app.config.get('CURRENT_SESSION')
            if current_session:
                year = current_session.year
                round_num = current_session.round_number

        return render_template('index.html', year=year, round=round_num)

    # =========================================================================
    # Error Handlers
    # =========================================================================

    @app.errorhandler(404)
    def not_found(error):
        return jsonify({'error': 'Not found'}), 404

    @app.errorhandler(500)
    def internal_error(error):
        return jsonify({'error': 'Internal server error'}), 500

    return app
