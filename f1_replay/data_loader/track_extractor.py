"""
Track Extractor - Extract track and pit lane geometry from FastF1

Adapted from legacy_f1_viewer track extraction logic.
Extracts track outline, pit lane, and segments from session telemetry.
"""

from typing import Optional, List
import numpy as np
import pandas as pd
from f1_replay.data_loader.data_models import TrackGeometry, TrackSegment


class TrackExtractor:
    """Extract and process track geometry from FastF1 session."""

    @staticmethod
    def extract_track_geometry(session) -> Optional[TrackGeometry]:
        """
        Extract track geometry from fastest lap telemetry.

        Determines circuit length using median distance from completed laps,
        ensuring robust handling of incomplete or anomalous laps.

        Args:
            session: FastF1 session object

        Returns:
            TrackGeometry object or None if extraction fails
        """
        try:
            fastest_lap = session.laps.pick_fastest()
            if fastest_lap is None:
                print("  ⚠ No fastest lap found")
                return None

            telemetry = fastest_lap.get_telemetry()
            if telemetry is None or telemetry.empty:
                print("  ⚠ No telemetry for fastest lap")
                return None

            # Extract coordinates
            x = telemetry['X'].astype(np.float32).values
            y = telemetry['Y'].astype(np.float32).values
            distance = None

            # Determine circuit length from session laps
            lap_distance = TrackExtractor._get_circuit_length(session)
            if lap_distance is None:
                # Fallback: use fastest lap distance if available
                if 'Distance' in telemetry.columns:
                    distance = telemetry['Distance'].astype(np.float32).values
                    lap_distance = float(distance[-1])
                else:
                    # Last resort: calculate from coordinates
                    diffs = np.sqrt(np.diff(x)**2 + np.diff(y)**2)
                    lap_distance = float(np.sum(diffs))

            # Keep Distance array if available
            if 'Distance' in telemetry.columns:
                distance = telemetry['Distance'].astype(np.float32).values

            track = TrackGeometry(x=x, y=y, distance=distance, lap_distance=lap_distance)

            print(f"  ✓ Track: {len(x)} points, {lap_distance:.0f}m")
            return track

        except Exception as e:
            print(f"  ✗ Error extracting track: {e}")
            return None

    @staticmethod
    def _get_circuit_length(session) -> Optional[float]:
        """
        Determine circuit length from median distance of completed laps.

        Args:
            session: FastF1 session object

        Returns:
            Circuit length in meters, or None if cannot be determined
        """
        try:
            laps = session.laps
            if laps is None or len(laps) == 0:
                return None

            # Get completed lap distances (filter out incomplete/pit stop laps)
            lap_distances = []
            for _, lap in laps.iterrows():
                try:
                    # Check if lap has valid Distance data
                    if pd.notna(lap.get('LapTime')) and lap['LapTime'].total_seconds() > 60:
                        tel = lap.get_telemetry()
                        if tel is not None and not tel.empty and 'Distance' in tel.columns:
                            final_distance = tel['Distance'].iloc[-1]
                            if pd.notna(final_distance) and final_distance > 1000:  # Filter anomalies
                                lap_distances.append(float(final_distance))
                except:
                    continue

            # Return median of valid lap distances
            if lap_distances:
                return float(np.median(lap_distances))
            return None

        except Exception:
            return None

    @staticmethod
    def extract_pit_lane(session) -> Optional[TrackGeometry]:
        """
        Extract pit lane geometry from in-lap and out-lap telemetry.

        Args:
            session: FastF1 session object

        Returns:
            TrackGeometry for pit lane or None if unavailable
        """
        try:
            in_laps = session.laps.pick_box_laps(which='in')
            out_laps = session.laps.pick_box_laps(which='out')

            if len(in_laps) == 0 and len(out_laps) == 0:
                print("  ℹ No pit stops - no pit lane data")
                return None

            all_pit_points = []

            # Extract from in-laps
            for _, lap in in_laps.iterrows():
                try:
                    tel = lap.get_telemetry()
                    if tel is not None and len(tel) > 100:
                        points = list(zip(tel['X'].values, tel['Y'].values))
                        all_pit_points.extend(points)
                        print(f"    In-lap: {len(tel)} points")
                        break
                except:
                    continue

            # Extract from out-laps
            for _, lap in out_laps.iterrows():
                try:
                    tel = lap.get_telemetry()
                    if tel is not None and len(tel) > 100:
                        points = list(zip(tel['X'].values, tel['Y'].values))
                        all_pit_points.extend(points)
                        print(f"    Out-lap: {len(tel)} points")
                        break
                except:
                    continue

            if len(all_pit_points) < 10:
                print(f"  ℹ Not enough pit lane points ({len(all_pit_points)})")
                return None

            # Deduplicate consecutive points (keep if moved >1m)
            x_vals, y_vals = [], []
            for x, y in all_pit_points:
                if not x_vals or np.sqrt((x - x_vals[-1])**2 + (y - y_vals[-1])**2) > 1.0:
                    x_vals.append(x)
                    y_vals.append(y)

            # Clip first and last 500 points (on-track sections)
            if len(x_vals) > 1000:
                x_vals = x_vals[500:-500]
                y_vals = y_vals[500:-500]
                print(f"    Clipped: {len(x_vals)} points (from {len(all_pit_points)})")

            pit_distance = np.sqrt(np.sum(np.diff(x_vals)**2 + np.diff(y_vals)**2))
            pit_lane = TrackGeometry(
                x=np.array(x_vals, dtype=np.float32),
                y=np.array(y_vals, dtype=np.float32),
                distance=None,
                lap_distance=pit_distance
            )

            print(f"  ✓ Pit lane: {len(x_vals)} points, {pit_distance:.0f}m")
            return pit_lane

        except Exception as e:
            print(f"  ✗ Error extracting pit lane: {e}")
            return None

    @staticmethod
    def extract_marshal_sectors(circuit_info) -> List[TrackSegment]:
        """
        Extract actual FIA marshal sectors from FastF1 circuit_info.

        These are the real sectors referenced in track status messages.
        Stores minimal data: sector number and position distance.
        Sector boundaries are defined by consecutive sector positions.

        Args:
            circuit_info: FastF1 circuit_info object with marshal_sectors

        Returns:
            List of TrackSegment objects (one per marshal sector)
        """
        segments = []

        try:
            if not hasattr(circuit_info, 'marshal_sectors') or circuit_info.marshal_sectors is None:
                return segments

            marshal_df = circuit_info.marshal_sectors
            if marshal_df.empty:
                return segments

            # Extract sector numbers and positions (minimal data)
            # Each row is a marshal sector marker at a specific track distance
            for idx, row in marshal_df.iterrows():
                sector_num = int(row['Number'])
                distance = float(row['Distance'])

                # Compute segment boundaries: from this sector to next sector
                next_distance = float(marshal_df.iloc[(idx + 1) % len(marshal_df)]['Distance'])

                segment = TrackSegment(
                    name=f"Sector {sector_num}",
                    start_distance=distance,
                    end_distance=next_distance,
                    segment_type="marshal_sector",
                    metadata={"sector_number": sector_num}
                )
                segments.append(segment)

        except Exception as e:
            print(f"  ⚠ Could not extract marshal sectors: {e}")

        return segments

    @staticmethod
    def create_track_segments(track_distance: float,
                             num_sectors: int = 4) -> List[TrackSegment]:
        """
        Create track segments (equal divisions).

        This is a fallback when marshal sectors are not available.

        Args:
            track_distance: Total track distance (meters)
            num_sectors: Number of segments (default 4)

        Returns:
            List of TrackSegment objects
        """
        segments = []
        segment_length = track_distance / num_sectors

        for i in range(num_sectors):
            start_dist = i * segment_length
            end_dist = (i + 1) * segment_length

            segment = TrackSegment(
                name=f"Sector {i+1}",
                start_distance=start_dist,
                end_distance=end_dist,
                segment_type="sector",
                metadata={"index": i}
            )
            segments.append(segment)

        return segments
