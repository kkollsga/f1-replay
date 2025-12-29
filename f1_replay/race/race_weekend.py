"""
RaceWeekend - Race weekend data wrapper

Placeholder for future implementation.
Will wrap F1Weekend and provide convenient access methods.
"""

from f1_replay.data_loader import F1Weekend


class RaceWeekend:
    """
    Race weekend wrapper providing convenient access to weekend data.

    TODO: Implement
    - Wrap F1Weekend data
    - Provide methods for track analysis
    - Session management (load/switch)
    """

    def __init__(self, f1_weekend: F1Weekend):
        """
        Initialize RaceWeekend.

        Args:
            f1_weekend: F1Weekend data object
        """
        self.f1_weekend = f1_weekend
        print(f"✓ RaceWeekend initialized: {f1_weekend.metadata.event_name} (placeholder)")

    def get_circuit(self):
        """Get circuit data."""
        return self.f1_weekend.circuit

    def get_track_geometry(self):
        """Get track geometry."""
        return self.f1_weekend.circuit.track

    def get_pit_lane(self):
        """Get pit lane geometry."""
        return self.f1_weekend.circuit.pit_lane

    def get_segments(self):
        """Get track segments."""
        return self.f1_weekend.circuit.track_segments
