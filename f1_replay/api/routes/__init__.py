"""Flask route blueprints."""

from f1_replay.api.routes.api_routes import api_bp
from f1_replay.api.routes.ui_routes import ui_bp

__all__ = ["api_bp", "ui_bp"]
