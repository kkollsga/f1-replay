"""
Session Type Mapping - Map user-friendly session names to FastF1 codes and vice versa

Provides bidirectional mapping between user-friendly names and FastF1 API codes.
"""

# Mapping from user-friendly names to FastF1 codes
USER_TO_FASTF1 = {
    "Practice1": "FP1",
    "Practice2": "FP2",
    "Practice3": "FP3",
    "Qualifying": "Q",
    "Sprint": "S",
    "Race": "R",
}

# Mapping from FastF1 codes to user-friendly names
FASTF1_TO_USER = {v: k for k, v in USER_TO_FASTF1.items()}

# Allow both formats
USER_TO_FASTF1.update({
    "FP1": "FP1",
    "FP2": "FP2",
    "FP3": "FP3",
    "Q": "Q",
    "S": "S",
    "R": "R",
})


def to_fastf1_code(session_type: str) -> str:
    """
    Convert user-friendly session type to FastF1 API code.

    Args:
        session_type: "Practice1", "Practice2", "Practice3", "Qualifying", "Sprint", "Race"
                     or FastF1 codes: "FP1", "FP2", "FP3", "Q", "S", "R"

    Returns:
        FastF1 API code ("FP1", "FP2", "FP3", "Q", "S", "R")
    """
    if session_type not in USER_TO_FASTF1:
        raise ValueError(f"Unknown session type: {session_type}. "
                        f"Valid types: {list(set(USER_TO_FASTF1.keys()))}")
    return USER_TO_FASTF1[session_type]


def to_user_friendly(fastf1_code: str) -> str:
    """
    Convert FastF1 API code to user-friendly session type.

    Args:
        fastf1_code: "FP1", "FP2", "FP3", "Q", "S", "R"

    Returns:
        User-friendly name ("Practice1", "Practice2", "Practice3", "Qualifying", "Sprint", "Race")
    """
    return FASTF1_TO_USER.get(fastf1_code, fastf1_code)
