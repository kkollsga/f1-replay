"""
Race - Race session data wrapper

Placeholder for future implementation.
Will wrap SessionData and provide convenient access and Flask app integration.
"""

from f1_replay.data_loader import SessionData


class Race:
    """
    Race session wrapper providing convenient access to session data and Flask integration.

    TODO: Implement
    - Wrap SessionData
    - Provide methods for telemetry analysis
    - Flask app integration
    """

    def __init__(self, session_data: SessionData):
        """
        Initialize Race.

        Args:
            session_data: SessionData object
        """
        self.session_data = session_data
        print(f"✓ Race initialized: {session_data.metadata.session_type} (placeholder)")

    def get_drivers(self):
        """Get list of drivers."""
        return self.session_data.metadata.drivers

    def get_telemetry(self, driver: str):
        """Get telemetry for specific driver."""
        if driver in self.session_data.telemetry:
            return self.session_data.telemetry[driver]
        return None

    def get_events(self):
        """Get session events."""
        return self.session_data.events

    def get_results(self):
        """Get session results."""
        return self.session_data.results

    def create_flask_app(self):
        """Create Flask app for visualization."""
        # TODO: Implement Flask app creation
        raise NotImplementedError("Race.create_flask_app() not yet implemented")
