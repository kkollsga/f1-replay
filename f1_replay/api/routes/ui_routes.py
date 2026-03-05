"""UI routes blueprint - serves the race viewer frontend."""

from flask import Blueprint, current_app, render_template, request

ui_bp = Blueprint("ui", __name__)


@ui_bp.route("/", methods=["GET"])
def index():
    """Serve main viewer page with current session context."""
    year = request.args.get("year", type=int)
    round_num = request.args.get("round", type=int)

    if not year or not round_num:
        current_session = current_app.config.get("CURRENT_SESSION")
        if current_session:
            year = current_session.year
            round_num = current_session.round_number

    return render_template("index.html", year=year, round=round_num)
