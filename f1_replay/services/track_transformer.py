"""
Track Transformer - Coordinate transformations for track visualization.

Provides rotation, scaling, and normalization of track coordinates.
Can be used by Python visualization tools and to generate transform
parameters for client-side rendering.
"""

from dataclasses import dataclass
from typing import Optional, Tuple
import numpy as np


@dataclass
class TransformParams:
    """Parameters for coordinate transformation (can be sent to client)."""
    rotation_deg: float  # Rotation angle in degrees
    center_x: float  # Center point for rotation
    center_y: float  # Center point for rotation
    scale: float  # Scale factor to fit bounds
    offset_x: float  # Translation after scaling
    offset_y: float  # Translation after scaling
    bounds: Tuple[float, float, float, float]  # (min_x, min_y, max_x, max_y)


class TrackTransformer:
    """
    Transform track coordinates for visualization.

    Handles rotation, centering, and scaling of track geometry.
    Works with numpy arrays from TrackGeometry.

    Usage:
        transformer = TrackTransformer(track.x, track.y, rotation_deg=90)

        # Get rotated coordinates
        rx, ry = transformer.get_rotated()

        # Get normalized to viewport
        nx, ny = transformer.get_normalized(width=800, height=600)

        # Get transform params for client-side rendering
        params = transformer.get_transform_params(width=800, height=600)
    """

    def __init__(
        self,
        x: np.ndarray,
        y: np.ndarray,
        rotation_deg: float = 0.0,
        pit_x: Optional[np.ndarray] = None,
        pit_y: Optional[np.ndarray] = None,
    ):
        """
        Initialize transformer with track coordinates.

        Args:
            x: Track X coordinates (decimeters)
            y: Track Y coordinates (decimeters)
            rotation_deg: Rotation angle in degrees (clockwise)
            pit_x: Optional pit lane X coordinates
            pit_y: Optional pit lane Y coordinates
        """
        self.raw_x = np.asarray(x, dtype=np.float32)
        self.raw_y = np.asarray(y, dtype=np.float32)
        self.rotation_deg = rotation_deg
        self.pit_x = np.asarray(pit_x, dtype=np.float32) if pit_x is not None else None
        self.pit_y = np.asarray(pit_y, dtype=np.float32) if pit_y is not None else None

        # Calculate center point
        self.center_x = float(self.raw_x.mean())
        self.center_y = float(self.raw_y.mean())

        # Cache rotated coordinates
        self._rotated_x: Optional[np.ndarray] = None
        self._rotated_y: Optional[np.ndarray] = None
        self._rotated_pit_x: Optional[np.ndarray] = None
        self._rotated_pit_y: Optional[np.ndarray] = None

    def _rotate_points(
        self,
        x: np.ndarray,
        y: np.ndarray,
        angle_deg: float,
        cx: float,
        cy: float
    ) -> Tuple[np.ndarray, np.ndarray]:
        """Rotate points around center."""
        if angle_deg == 0:
            return x.copy(), y.copy()

        angle_rad = np.radians(angle_deg)
        cos_a = np.cos(angle_rad)
        sin_a = np.sin(angle_rad)

        # Translate to origin, rotate, translate back
        rx = cos_a * (x - cx) - sin_a * (y - cy) + cx
        ry = sin_a * (x - cx) + cos_a * (y - cy) + cy

        return rx.astype(np.float32), ry.astype(np.float32)

    def get_rotated(self) -> Tuple[np.ndarray, np.ndarray]:
        """
        Get track coordinates rotated to canonical orientation.

        Returns:
            Tuple of (x, y) rotated coordinate arrays
        """
        if self._rotated_x is None:
            self._rotated_x, self._rotated_y = self._rotate_points(
                self.raw_x, self.raw_y,
                self.rotation_deg,
                self.center_x, self.center_y
            )
        return self._rotated_x, self._rotated_y

    def get_rotated_pit(self) -> Optional[Tuple[np.ndarray, np.ndarray]]:
        """Get rotated pit lane coordinates if available."""
        if self.pit_x is None:
            return None

        if self._rotated_pit_x is None:
            self._rotated_pit_x, self._rotated_pit_y = self._rotate_points(
                self.pit_x, self.pit_y,
                self.rotation_deg,
                self.center_x, self.center_y
            )
        return self._rotated_pit_x, self._rotated_pit_y

    def rotate_points(
        self,
        x: np.ndarray,
        y: np.ndarray
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        Rotate arbitrary points using same transformation.

        Useful for rotating sector boundaries, labels, etc.

        Args:
            x: X coordinates to rotate
            y: Y coordinates to rotate

        Returns:
            Tuple of rotated (x, y) arrays
        """
        return self._rotate_points(
            np.asarray(x), np.asarray(y),
            self.rotation_deg,
            self.center_x, self.center_y
        )

    def get_normalized(
        self,
        width: float = 1.0,
        height: float = 1.0,
        padding: float = 0.1,
        preserve_aspect: bool = True
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        Get coordinates scaled and centered to fit within bounds.

        Args:
            width: Target width
            height: Target height
            padding: Padding ratio (0.1 = 10% padding on each side)
            preserve_aspect: Maintain aspect ratio

        Returns:
            Tuple of (x, y) normalized coordinate arrays
        """
        rx, ry = self.get_rotated()

        # Calculate bounds
        min_x, max_x = rx.min(), rx.max()
        min_y, max_y = ry.min(), ry.max()

        track_width = max_x - min_x
        track_height = max_y - min_y

        # Available space after padding
        avail_width = width * (1 - 2 * padding)
        avail_height = height * (1 - 2 * padding)

        # Calculate scale
        if preserve_aspect:
            scale_x = avail_width / track_width if track_width > 0 else 1
            scale_y = avail_height / track_height if track_height > 0 else 1
            scale = min(scale_x, scale_y)
        else:
            scale = (avail_width / track_width, avail_height / track_height)

        # Apply scale and center
        if isinstance(scale, tuple):
            nx = (rx - min_x) * scale[0] + width * padding
            ny = (ry - min_y) * scale[1] + height * padding
        else:
            # Center in viewport
            scaled_width = track_width * scale
            scaled_height = track_height * scale
            offset_x = (width - scaled_width) / 2
            offset_y = (height - scaled_height) / 2

            nx = (rx - min_x) * scale + offset_x
            ny = (ry - min_y) * scale + offset_y

        return nx.astype(np.float32), ny.astype(np.float32)

    def get_bounds(self) -> Tuple[float, float, float, float]:
        """Get bounding box of rotated track (min_x, min_y, max_x, max_y)."""
        rx, ry = self.get_rotated()
        return float(rx.min()), float(ry.min()), float(rx.max()), float(ry.max())

    def get_transform_params(
        self,
        width: float = 800,
        height: float = 600,
        padding: float = 0.1
    ) -> TransformParams:
        """
        Get transformation parameters for client-side rendering.

        Returns parameters that can be serialized and sent to a JS client
        to apply the same transformation.

        Args:
            width: Target viewport width
            height: Target viewport height
            padding: Padding ratio

        Returns:
            TransformParams dataclass with all transform values
        """
        rx, ry = self.get_rotated()

        min_x, max_x = float(rx.min()), float(rx.max())
        min_y, max_y = float(ry.min()), float(ry.max())

        track_width = max_x - min_x
        track_height = max_y - min_y

        avail_width = width * (1 - 2 * padding)
        avail_height = height * (1 - 2 * padding)

        scale_x = avail_width / track_width if track_width > 0 else 1
        scale_y = avail_height / track_height if track_height > 0 else 1
        scale = min(scale_x, scale_y)

        scaled_width = track_width * scale
        scaled_height = track_height * scale
        offset_x = (width - scaled_width) / 2 - min_x * scale
        offset_y = (height - scaled_height) / 2 - min_y * scale

        return TransformParams(
            rotation_deg=self.rotation_deg,
            center_x=self.center_x,
            center_y=self.center_y,
            scale=scale,
            offset_x=offset_x,
            offset_y=offset_y,
            bounds=(min_x, min_y, max_x, max_y)
        )

    def to_dict(self, width: float = 800, height: float = 600) -> dict:
        """
        Get transform as dictionary for JSON serialization.

        Args:
            width: Target viewport width
            height: Target viewport height

        Returns:
            Dict with transform parameters
        """
        params = self.get_transform_params(width, height)
        return {
            'rotation_deg': params.rotation_deg,
            'center_x': params.center_x,
            'center_y': params.center_y,
            'scale': params.scale,
            'offset_x': params.offset_x,
            'offset_y': params.offset_y,
            'bounds': {
                'min_x': params.bounds[0],
                'min_y': params.bounds[1],
                'max_x': params.bounds[2],
                'max_y': params.bounds[3]
            }
        }
