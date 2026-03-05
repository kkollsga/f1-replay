"""
Schedule utilities - ScheduleList and schedule formatting helpers.

Extracted from race_manager.py to reduce file size.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional


class ScheduleList(list):
    """
    List of schedule items with pretty printing support.

    Each item is a dict with: title, start, end, session_type, round, location
    """

    def __init__(self, items: List[Dict[str, Any]], schedule_type: str = "Schedule"):
        super().__init__(items)
        self.schedule_type = schedule_type

    def __getitem__(self, key):
        result = super().__getitem__(key)
        if isinstance(key, slice):
            return ScheduleList(result, self.schedule_type)
        return result

    def __repr__(self) -> str:
        return self._format_table()

    def __str__(self) -> str:
        return self._format_table()

    def _format_table(self) -> str:
        if not self:
            return f"\n  No {self.schedule_type.lower()} events found.\n"

        # Build formatted output
        lines = [f"\n  {self.schedule_type}", "  " + "=" * 70]

        for item in self:
            # Parse start time
            start = item.get("start")
            if isinstance(start, str):
                try:
                    start = datetime.fromisoformat(start.replace("Z", "+00:00"))
                except (ValueError, TypeError):
                    pass

            # Format date/time
            if isinstance(start, datetime):
                date_str = start.strftime("%a %d %b")
                time_str = start.strftime("%H:%M")
            else:
                date_str = str(start)[:10] if start else "TBD"
                time_str = ""

            title = item.get("title", "Unknown")
            location = item.get("location", "")
            round_num = item.get("round", "")

            # Format: "  R01  Sun 16 Mar  15:00  Bahrain Grand Prix (Sakhir)"
            round_str = f"R{round_num:02d}" if isinstance(round_num, int) else str(round_num)
            loc_str = f"({location})" if location else ""

            lines.append(f"  {round_str}  {date_str}  {time_str:>5}  {title} {loc_str}")

        lines.append("")
        return "\n".join(lines)


def format_date_range(start_date: str, end_date: str) -> str:
    """Format date range like '26 - 28 Feb' or '28 Feb - 2 Mar'."""

    def parse_date(s):
        if not s or "NaT" in str(s) or len(str(s)) < 10:
            return None
        try:
            return datetime.strptime(str(s)[:10], "%Y-%m-%d")
        except (ValueError, TypeError):
            return None

    start = parse_date(start_date)
    end = parse_date(end_date)

    if start is None and end is None:
        return "TBD"
    if start is None:
        return end.strftime("%d %b")
    if end is None:
        return start.strftime("%d %b")

    # Same month or different months - always use end month
    return f"{start.day:2d} - {end.day:2d} {end.strftime('%b')}"


def build_schedule_item(event, session_num: int, round_num: int) -> Optional[Dict[str, Any]]:
    """Build a schedule item dict from event row and session number."""
    session_name = event.get(f"Session{session_num}")
    session_date = event.get(f"Session{session_num}Date")

    if not session_name or session_date is None:
        return None

    # Get end time (estimate 2 hours for races, 1 hour for others)
    duration_hours = 2 if session_name in ["Race", "Sprint"] else 1
    try:
        end_time = session_date + __import__("datetime").timedelta(hours=duration_hours)
    except (ValueError, TypeError):
        end_time = None

    return {
        "title": f"{event.get('EventName', '')} - {session_name}",
        "start": (
            session_date.isoformat() if hasattr(session_date, "isoformat") else str(session_date)
        ),
        "end": end_time.isoformat() if end_time and hasattr(end_time, "isoformat") else None,
        "session_type": session_name,
        "round": round_num,
        "location": event.get("Location", ""),
        "country": event.get("Country", ""),
        "event_name": event.get("EventName", ""),
    }


def get_event_schedule(year: int):
    """Get FastF1 event schedule for a year."""
    import fastf1

    return fastf1.get_event_schedule(year)


def session_type_schedule(year: int, session_names: List[str], label: str) -> ScheduleList:
    """Generic schedule filter: find events with matching session type names."""
    schedule = get_event_schedule(year)
    if schedule is None:
        return ScheduleList([], f"{year} {label}")

    items = []
    for _, event in schedule.iterrows():
        round_num = event.get("RoundNumber", 0)
        if round_num == 0:
            continue

        for i in range(1, 6):
            if event.get(f"Session{i}") in session_names:
                item = build_schedule_item(event, i, round_num)
                if item:
                    item["title"] = event.get("EventName", "")
                    items.append(item)
                break

    return ScheduleList(items, f"{year} {label}")
