"""
Flask app factory for F1 Race Viewer API.

Creates Flask app with 3 main endpoints matching 3-tier backend architecture:
- GET /api/seasons          - Season catalog
- GET /api/weekend/<year>/<round>  - Weekend metadata + circuit geometry
- GET /api/session/<year>/<round>/<session_type> - Complete session data
"""

from flask import Flask, jsonify, request, render_template, Response
from typing import Optional
from datetime import datetime
import math

try:
    import orjson
    HAS_ORJSON = True
except ImportError:
    HAS_ORJSON = False

try:
    from flask_cors import CORS
    HAS_CORS = True
except ImportError:
    HAS_CORS = False


def fast_jsonify(data: dict, status: int = 200) -> Response:
    """Fast JSON response using orjson if available."""
    if HAS_ORJSON:
        # OPT_SERIALIZE_NUMPY handles numpy int64/float64 natively (fastest)
        return Response(
            orjson.dumps(data, option=orjson.OPT_SERIALIZE_NUMPY),
            status=status,
            mimetype='application/json'
        )
    else:
        return jsonify(data), status

from f1_replay.managers import DataLoader
from f1_replay.wrappers import RaceWeekend, Session, create_session
from f1_replay.api.serializers import to_json_safe, serialize_telemetry


def _get_scheduled_session_info(data_loader: DataLoader, year: int, round_num: int, session_type: str) -> Optional[dict]:
    """
    Get scheduled session info for a future race.

    Returns dict with scheduled date/time if race is in the future, None otherwise.
    """
    try:
        # Get event schedule from FastF1
        import fastf1
        event = fastf1.get_event(year, round_num)
        if event is None:
            return None

        # Map session type to session number (Session1-5)
        session_map = {
            'FP1': 'Session1', 'FP2': 'Session2', 'FP3': 'Session3',
            'Q': 'Session4', 'R': 'Session5',
            'S': 'Session4',  # Sprint is usually Session4 on sprint weekends
            'SQ': 'Session3',  # Sprint Qualifying
        }

        # Also handle user-friendly names
        friendly_map = {
            'Practice1': 'FP1', 'Practice2': 'FP2', 'Practice3': 'FP3',
            'Qualifying': 'Q', 'Race': 'R', 'Sprint': 'S', 'SprintQualifying': 'SQ'
        }

        # Normalize session type
        normalized = friendly_map.get(session_type, session_type)
        session_key = session_map.get(normalized)

        if not session_key:
            return None

        # Get session date
        date_key = f"{session_key}Date"
        session_date = event.get(date_key)

        if session_date is None:
            # Try to find session by name in the schedule
            for i in range(1, 6):
                if event.get(f'Session{i}') == normalized:
                    session_date = event.get(f'Session{i}Date')
                    break

        if session_date is None:
            return None

        # Check if session is in the future
        now = datetime.now(session_date.tzinfo) if session_date.tzinfo else datetime.now()
        if session_date <= now:
            return None  # Session already happened, let normal error handling proceed

        # Format the date nicely
        # e.g., "Sun 15th September at 16:00"
        day_suffix = lambda d: 'th' if 11 <= d <= 13 else {1: 'st', 2: 'nd', 3: 'rd'}.get(d % 10, 'th')
        formatted_date = session_date.strftime(f"%a {session_date.day}{day_suffix(session_date.day)} %B at %H:%M")

        # Get event name from seasons catalog
        seasons = data_loader.load_seasons()
        event_name = ""
        if seasons and year in seasons:
            for r in seasons[year]:
                if r.round_number == round_num:
                    event_name = r.name
                    break

        return {
            'scheduled': True,
            'name': event_name or event.get('EventName', ''),
            'session_type': session_type,
            'scheduled_date': session_date.isoformat(),
            'scheduled_date_formatted': formatted_date,
            'message': f"The {session_type} is scheduled for {formatted_date}"
        }

    except Exception as e:
        print(f"Could not get scheduled info: {e}")
        return None


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
    app.config['WEEKEND_CACHE'] = {}  # key: (year, round) -> F1Weekend

    # Pre-cache data from current session (from Manager.race())
    if current_session is not None:
        # Cache the session
        session_key = (current_session.year, current_session.round_number, current_session.session_type)
        app.config['SESSION_CACHE'][session_key] = current_session

        # Cache the weekend data from the session's RaceWeekend wrapper
        if hasattr(current_session, 'weekend') and current_session.weekend is not None:
            weekend_key = (current_session.year, current_session.round_number)
            app.config['WEEKEND_CACHE'][weekend_key] = current_session.weekend._data

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

            # Build response - seasons is Dict[int, List[EventInfo]]
            # Direct serialization of EventInfo dataclass
            seasons_dict = {}
            for year, events in seasons.items():
                seasons_dict[str(year)] = {
                    'total_rounds': len(events),
                    'rounds': [to_json_safe(event) for event in events]
                }

            return jsonify({
                'seasons': seasons_dict
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
                "event": {...},
                "circuit": {
                    "track": {marshal_sectors: [{number, start_distance, end_distance}, ...]},
                    "pit_lane": {...},
                    "circuit_length": float,
                    "rotation": float,
                    "corners": [{number, distance, angle, letter}, ...]
                }
            }
        """
        try:
            cache_key = (year, round_num)

            # Check in-memory cache first
            if cache_key in app.config['WEEKEND_CACHE']:
                weekend_data = app.config['WEEKEND_CACHE'][cache_key]
            else:
                # Get event info first
                event = data_loader.get_event(year, round_num)
                if event is None:
                    return jsonify({'error': f'Round {year}/{round_num} not found in seasons'}), 404

                weekend_data = data_loader.load_weekend(year, round_num, event, force_reprocess=app.config.get('FORCE_UPDATE', False))
                if weekend_data is None:
                    return jsonify({'error': f'Weekend {year}/{round_num} not found'}), 404
                # Cache for future requests
                app.config['WEEKEND_CACHE'][cache_key] = weekend_data

            # Direct serialization of F1Weekend (EventInfo + CircuitData)
            return fast_jsonify({
                'event': to_json_safe(weekend_data.event),
                'circuit': to_json_safe(weekend_data.circuit),
            })

        except Exception as e:
            import traceback
            traceback.print_exc()
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
                force_reprocess = app.config.get('FORCE_UPDATE', False)

                # Get event info from seasons catalog
                event = data_loader.get_event(year, round_num)
                if event is None:
                    return jsonify({'error': f'Round {year}/{round_num} not found'}), 404

                weekend_data = data_loader.load_weekend(year, round_num, event, force_reprocess=force_reprocess)
                if weekend_data is None:
                    return jsonify({'error': f'Weekend {year}/{round_num} not found'}), 404

                weekend = RaceWeekend(data=weekend_data)

                result = data_loader.load_session(
                    year, round_num, session_type,
                    event=event,
                    circuit_length=weekend.circuit_length,
                    force_reprocess=force_reprocess
                )
                if result is None:
                    # Check if this is a future race - return scheduled date
                    scheduled_info = _get_scheduled_session_info(data_loader, year, round_num, session_type)
                    if scheduled_info:
                        return jsonify(scheduled_info), 200
                    return jsonify({'error': f'Session {year}/{round_num}/{session_type} not found'}), 404

                session = create_session(data=result.data, weekend=weekend, raw_session=result.raw_session)
                # Cache for future requests
                app.config['SESSION_CACHE'][cache_key] = session

                # Print tier 3 session summary
                print(f"\n{'='*60}")
                print(f"TIER 3 SESSION DATA LOADED: {year} R{round_num} {session_type}")
                print(f"{'='*60}")
                print(f"Metadata:")
                print(f"  session_type: {session.session_type}")
                print(f"  year: {session.year}")
                print(f"  round_number: {session.round_number}")
                print(f"  event_name: {session.event_name}")
                print(f"  drivers: {session.drivers}")
                print(f"  track_length: {session.track_length}")
                print(f"  total_laps: {session.total_laps}")
                print(f"  t0_utc: {session.t0_utc}")
                print(f"  start_time_local: {session.start_time_local}")
                print(f"Telemetry: {len(session.telemetry)} drivers")
                for drv, df in list(session.telemetry.items())[:3]:
                    print(f"  {drv}: {len(df)} rows, columns={list(df.columns)[:8]}...")
                print(f"Events:")
                print(f"  track_status: {len(session.track_status) if session.track_status is not None else 0} events")
                print(f"  race_control: {len(session.race_control) if session.race_control is not None else 0} events")
                print(f"  weather: {len(session.weather) if session.weather is not None else 0} events")
                print(f"{'='*60}\n")

            # Get optional telemetry fields from query params
            telemetry_fields = None
            if 'telemetry_fields' in request.args:
                telemetry_fields = request.args.get('telemetry_fields').split(',')

            # Direct serialization of SessionData dataclass
            # Telemetry uses column-format for efficiency (via serialize_telemetry)
            session_data = session._data
            return fast_jsonify({
                'metadata': to_json_safe(session_data.metadata),
                'telemetry': serialize_telemetry(session_data.telemetry, fields=telemetry_fields),
                'events': to_json_safe(session_data.events),
                'results': to_json_safe(session_data.results),
            })

        except Exception as e:
            import traceback
            traceback.print_exc()
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
