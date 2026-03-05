"""API routes blueprint - /api/* endpoints for F1 data."""

from datetime import datetime

from flask import Blueprint, current_app, jsonify, request

from f1_replay.api.app import fast_jsonify
from f1_replay.api.serializers import serialize_telemetry, to_json_safe
from f1_replay.log import logger
from f1_replay.wrappers import RaceWeekend, create_session

api_bp = Blueprint("api", __name__, url_prefix="/api")


def _get_scheduled_session_info(data_loader, year: int, round_num: int, session_type: str):
    """Get scheduled session info for a future race. Returns dict or None."""
    try:
        import fastf1

        event = fastf1.get_event(year, round_num)
        if event is None:
            return None

        session_map = {
            "FP1": "Session1",
            "FP2": "Session2",
            "FP3": "Session3",
            "Q": "Session4",
            "R": "Session5",
            "S": "Session4",
            "SQ": "Session3",
        }
        friendly_map = {
            "Practice1": "FP1",
            "Practice2": "FP2",
            "Practice3": "FP3",
            "Qualifying": "Q",
            "Race": "R",
            "Sprint": "S",
            "SprintQualifying": "SQ",
        }

        normalized = friendly_map.get(session_type, session_type)
        session_key = session_map.get(normalized)
        if not session_key:
            return None

        date_key = f"{session_key}Date"
        session_date = event.get(date_key)

        if session_date is None:
            for i in range(1, 6):
                if event.get(f"Session{i}") == normalized:
                    session_date = event.get(f"Session{i}Date")
                    break

        if session_date is None:
            return None

        now = datetime.now(session_date.tzinfo) if session_date.tzinfo else datetime.now()
        if session_date <= now:
            return None

        def day_suffix(d):
            return "th" if 11 <= d <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(d % 10, "th")

        formatted_date = session_date.strftime(
            f"%a {session_date.day}{day_suffix(session_date.day)} %B at %H:%M"
        )

        seasons = data_loader.load_seasons()
        event_name = ""
        if seasons and year in seasons:
            for r in seasons[year]:
                if r.round_number == round_num:
                    event_name = r.name
                    break

        return {
            "scheduled": True,
            "name": event_name or event.get("EventName", ""),
            "session_type": session_type,
            "scheduled_date": session_date.isoformat(),
            "scheduled_date_formatted": formatted_date,
            "message": f"The {session_type} is scheduled for {formatted_date}",
        }

    except Exception as e:
        logger.warning(f"Could not get scheduled info: {e}")
        return None


@api_bp.route("/seasons", methods=["GET"])
def get_seasons():
    """Get complete season catalog."""
    try:
        data_loader = current_app.config["DATA_LOADER"]
        seasons = data_loader.load_seasons()
        if seasons is None:
            return jsonify({"error": "Could not load seasons"}), 500

        seasons_dict = {}
        for year, events in seasons.items():
            seasons_dict[str(year)] = {
                "total_rounds": len(events),
                "rounds": [to_json_safe(event) for event in events],
            }

        return jsonify({"seasons": seasons_dict}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@api_bp.route("/weekend/<int:year>/<int:round_num>", methods=["GET"])
def get_weekend(year: int, round_num: int):
    """Get weekend metadata + circuit geometry."""
    try:
        data_loader = current_app.config["DATA_LOADER"]
        cache_key = (year, round_num)

        if cache_key in current_app.config["WEEKEND_CACHE"]:
            weekend_data = current_app.config["WEEKEND_CACHE"][cache_key]
        else:
            event = data_loader.get_event(year, round_num)
            if event is None:
                return jsonify({"error": f"Round {year}/{round_num} not found in seasons"}), 404

            weekend_data = data_loader.load_weekend(
                year,
                round_num,
                event,
                force_reprocess=current_app.config.get("FORCE_UPDATE", False),
            )
            if weekend_data is None:
                return jsonify({"error": f"Weekend {year}/{round_num} not found"}), 404
            current_app.config["WEEKEND_CACHE"][cache_key] = weekend_data

        return fast_jsonify(
            {
                "event": to_json_safe(weekend_data.event),
                "circuit": to_json_safe(weekend_data.circuit),
            }
        )

    except Exception as e:
        logger.error(f"API error: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@api_bp.route("/session/<int:year>/<int:round_num>/<session_type>", methods=["GET"])
def get_session(year: int, round_num: int, session_type: str):
    """Get complete session data (optimized payload)."""
    try:
        data_loader = current_app.config["DATA_LOADER"]
        cache_key = (year, round_num, session_type)

        # Check pre-loaded session from Manager.race()
        current_session = current_app.config["CURRENT_SESSION"]
        if (
            current_session is not None
            and current_session.year == year
            and current_session.round_number == round_num
            and current_session.session_type == session_type
        ):
            session = current_session
        elif cache_key in current_app.config["SESSION_CACHE"]:
            session = current_app.config["SESSION_CACHE"][cache_key]
        else:
            force_reprocess = current_app.config.get("FORCE_UPDATE", False)

            event = data_loader.get_event(year, round_num)
            if event is None:
                return jsonify({"error": f"Round {year}/{round_num} not found"}), 404

            weekend_data = data_loader.load_weekend(
                year, round_num, event, force_reprocess=force_reprocess
            )
            if weekend_data is None:
                return jsonify({"error": f"Weekend {year}/{round_num} not found"}), 404

            weekend = RaceWeekend(data=weekend_data)

            result = data_loader.load_session(
                year,
                round_num,
                session_type,
                event=event,
                circuit_length=weekend.circuit_length,
                force_reprocess=force_reprocess,
            )
            if result is None:
                scheduled_info = _get_scheduled_session_info(
                    data_loader, year, round_num, session_type
                )
                if scheduled_info:
                    return jsonify(scheduled_info), 200
                return (
                    jsonify({"error": f"Session {year}/{round_num}/{session_type} not found"}),
                    404,
                )

            session = create_session(
                data=result.data, weekend=weekend, raw_session=result.raw_session
            )
            current_app.config["SESSION_CACHE"][cache_key] = session

            logger.info(
                f"Session loaded via API: {session.event_name} {session_type}"
                f" ({len(session.drivers)} drivers)"
            )

        # Get optional telemetry fields from query params
        telemetry_fields = None
        if "telemetry_fields" in request.args:
            telemetry_fields = request.args.get("telemetry_fields").split(",")

        session_data = session._data
        return fast_jsonify(
            {
                "metadata": to_json_safe(session_data.metadata),
                "telemetry": serialize_telemetry(session_data.telemetry, fields=telemetry_fields),
                "events": to_json_safe(session_data.events),
                "results": to_json_safe(session_data.results),
            }
        )

    except Exception as e:
        logger.error(f"API error: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500
