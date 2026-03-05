"""Tests for logging module."""

import logging

from f1_replay.log import logger, setup_logging


class TestSetupLogging:
    """Test logging configuration."""

    def test_logger_name(self):
        assert logger.name == "f1_replay"

    def test_setup_logging_default(self):
        # Remove existing handlers for clean test
        logger.handlers.clear()
        setup_logging()
        assert len(logger.handlers) == 1
        assert logger.level == logging.INFO

    def test_setup_logging_custom_level(self):
        logger.handlers.clear()
        setup_logging(level="WARNING")
        assert logger.level == logging.WARNING

    def test_setup_logging_idempotent(self):
        """Calling setup_logging twice doesn't add duplicate handlers."""
        logger.handlers.clear()
        setup_logging()
        setup_logging()
        assert len(logger.handlers) == 1

    def test_setup_logging_env(self, monkeypatch):
        logger.handlers.clear()
        monkeypatch.setenv("F1_REPLAY_LOG_LEVEL", "DEBUG")
        setup_logging()
        assert logger.level == logging.DEBUG

    def test_message_format(self, capfd):
        """Messages should be plain (no timestamps)."""
        logger.handlers.clear()
        setup_logging()
        logger.info("test message")
        captured = capfd.readouterr()
        assert "test message" in captured.err
        # No timestamp prefix
        assert "INFO" not in captured.err
