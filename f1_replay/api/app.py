"""
Flask app factory for F1 Race Viewer API.

Creates Flask app with 3 main endpoints matching 3-tier backend architecture:
- GET /api/seasons          - Season catalog
- GET /api/weekend/<year>/<round>  - Weekend metadata + circuit geometry
- GET /api/session/<year>/<round>/<session_type> - Complete session data
"""

from flask import Flask, Response, jsonify

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
        return Response(
            orjson.dumps(data, option=orjson.OPT_SERIALIZE_NUMPY),
            status=status,
            mimetype="application/json",
        )
    else:
        return jsonify(data), status


def create_app(data_loader, current_session=None, force_update: bool = False) -> Flask:
    """
    Create and configure Flask app.

    Args:
        data_loader: DataLoader instance for accessing cached data
        current_session: Optional Session to pre-load (used by Manager.race())
        force_update: If True, force reprocessing of all race data (ignore cache)

    Returns:
        Configured Flask app
    """
    app = Flask(
        __name__, template_folder="templates", static_folder="static", static_url_path="/static"
    )

    # Configuration
    app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0
    app.config["JSON_SORT_KEYS"] = False
    app.config["TEMPLATES_AUTO_RELOAD"] = True

    # Store data loader and session state
    app.config["DATA_LOADER"] = data_loader
    app.config["CURRENT_SESSION"] = current_session
    app.config["FORCE_UPDATE"] = force_update

    # In-memory caches
    app.config["SESSION_CACHE"] = {}
    app.config["WEEKEND_CACHE"] = {}

    # Pre-cache data from current session (from Manager.race())
    if current_session is not None:
        session_key = (
            current_session.year,
            current_session.round_number,
            current_session.session_type,
        )
        app.config["SESSION_CACHE"][session_key] = current_session

        if hasattr(current_session, "weekend") and current_session.weekend is not None:
            weekend_key = (current_session.year, current_session.round_number)
            app.config["WEEKEND_CACHE"][weekend_key] = current_session.weekend._data

    # Enable CORS for development (if available)
    if HAS_CORS:
        CORS(app)

    # Register blueprints
    from f1_replay.api.routes import api_bp, ui_bp

    app.register_blueprint(api_bp)
    app.register_blueprint(ui_bp)

    # Error handlers
    @app.errorhandler(404)
    def not_found(error):
        return jsonify({"error": "Not found"}), 404

    @app.errorhandler(500)
    def internal_error(error):
        return jsonify({"error": "Internal server error"}), 500

    return app
