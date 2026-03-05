import logging
import os

logger = logging.getLogger("f1_replay")


def setup_logging(level=None):
    """Configure f1_replay logging. Called once at startup."""
    if logger.handlers:
        return
    if level is None:
        level = os.environ.get("F1_REPLAY_LOG_LEVEL", "INFO")
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
