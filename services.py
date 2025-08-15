# File: services.py
import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Optional, Dict, Any, Tuple, List
import requests
import json
import math

from r2r_bo.graphhopper.config import GraphHopperConfig
from r2r_bo.graphhopper.custom_profile_generator import generate_profile
from r2r_bo.database.base import session_scope

from models import RouteResponse, RouteGeometry, RouteMetrics, ElevationPoint, RouteSegment

# Global thread pool
thread_pool = ThreadPoolExecutor(max_workers=10)


def get_custom_model(custom_profile_id: int, parameters: Dict[str, Any]) -> Dict[str, Any]:
    """Generate custom model from database."""
    with session_scope() as session:
        return generate_profile(custom_profile_id, parameters, session)


def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate distance between two points in meters using Haversine formula."""
    R = 6371000  # Earth's radius in meters

    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    delta_lat = math.radians(lat2 - lat1)
    delta_lon = math.radians(lon2 - lon1)

    a = (math.sin(delta_lat / 2) ** 2 +
         math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(delta_lon / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return R * c


def calculate_cumulative_distances(coordinates: List[List[float]]) -> List[float]:
    """Calculate cumulative distance for each coordinate point."""
    distances = [0.0]
    for i in range(1, len(coordinates)):
        dist = haversine_distance(
            coordinates[i - 1][1], coordinates[i - 1][0],  # lat, lon
            coordinates[i][1], coordinates[i][0]
        )
        distances.append(distances[-1] + dist)
    return distances


def create_elevation_profile_from_coordinates(
    coordinates: List[List[float]],
    coordinate_distances: List[float]
) -> List[ElevationPoint]:
    """
    Create elevation profile from coordinates with elevation data.
    Coordinates format: [lon, lat, elevation]
    Now includes coordinate_index for mapping back to route coordinates.
    """
    if len(coordinates) < 2:
        return []

    elevation_points = []

    for i, coord in enumerate(coordinates):
        lon, lat, elevation = coord[0], coord[1], coord[2] if len(coord) > 2 else 0.0

        elevation_points.append(ElevationPoint(
            distance=coordinate_distances[i],
            elevation=elevation,
            coordinate_index=i  # NEW: Direct mapping to coordinate array
        ))

    return elevation_points


def merge_detail_segments(
        coordinates: List[List[float]],
        details_data: Dict[str, List],  # Dict of detail_type -> [[start, end, value], ...]
        coordinate_distances: List[float]
) -> List[RouteSegment]:
    """
    Merge multiple path details into a single list of non-overlapping segments.

    GraphHopper returns details as [start_idx, end_idx, value] with 'end_idx' being
    EXCLUSIVE. Different detail types (surface, smoothness, etc.) usually break at
    different indices. We therefore:
      1) Collect all unique cut points from EVERY detail list (all starts & ends),
      2) Create atomic segments between consecutive cut points,
      3) For each atomic segment, assign each detail attribute by coverage:
         a detail (a,b,val) covers [s,e) if s >= a and e <= b.
      4) For any missing attribute, set 'unknown'.

    This guarantees that the sum of per-attribute lengths equals the total route length.
    """
    n_coords = len(coordinates)
    if n_coords < 2:
        return []

    # --- 1) Collect all unique boundary indices ("cuts") ---
    # Always include the very first and the very last usable index.
    # We treat GraphHopper 'end' as exclusive, but clamp to n_coords-1 for distances.
    cuts = {0, n_coords - 1}

    for detail_list in (details_data or {}).values():
        if not detail_list:
            continue
        for a, b, _ in detail_list:
            # Clamp to bounds; guard against bad data
            a = max(0, min(a, n_coords - 1))
            b = max(0, min(b, n_coords - 1))
            cuts.add(a)
            cuts.add(b)

    sorted_cuts = sorted(cuts)

    # Ensure we have at least two distinct cuts
    if len(sorted_cuts) < 2:
        return []

    # --- 2) Create atomic, non-overlapping segments ---
    raw_segments: List[Tuple[int, int]] = []
    for i in range(len(sorted_cuts) - 1):
        s = sorted_cuts[i]
        e = sorted_cuts[i + 1]
        if s < e:
            raw_segments.append((s, e))

    if not raw_segments:
        return []

    # --- 3) For each atomic segment, assign attribute values by coverage ---
    segments: List[RouteSegment] = []

    # Helper to get the value of a detail type for [s, e)
    def value_for_segment(detail_list: List[List[Any]], s: int, e: int) -> str:
        """
        Return the value whose [a,b) interval fully covers [s,e).
        If none covers the range, return 'unknown'.
        """
        if not detail_list:
            return "unknown"

        for a, b, v in detail_list:
            # Clamp to bounds in case original data is off
            a = max(0, min(a, n_coords - 1))
            b = max(0, min(b, n_coords - 1))
            # GraphHopper details are [a, b) (end exclusive). Our atomic segment is [s, e).
            if s >= a and e <= b:
                return v if v not in (None, "", "missing", "null", "undefined") else "unknown"
        return "unknown"

    for s, e in raw_segments:
        # Distances are indexed by coordinate; end distance uses e
        start_idx = s
        end_idx = e

        # Build attributes dict for all requested detail types
        attrs: Dict[str, Any] = {}
        for dtype, dlist in (details_data or {}).items():
            attrs[dtype] = value_for_segment(dlist, s, e)

        segments.append(
            RouteSegment(
                start_index=start_idx,
                end_index=end_idx,
                start_distance=coordinate_distances[start_idx],
                end_distance=coordinate_distances[end_idx],
                attributes=attrs,
            )
        )

    return segments


def execute_route_request(
        start: Tuple[float, float],
        end: Tuple[float, float],
        profile: str,
        custom_model: Optional[Dict[str, Any]],
        config: GraphHopperConfig,
        include_elevation: bool = True,
        details: Optional[List[str]] = None  # List of detail types
) -> RouteResponse:
    """Execute route request with unencoded points and elevation."""
    try:
        # Create payload for GraphHopper with unencoded points and elevation
        payload = {
            "points": [[start[1], start[0]], [end[1], end[0]]],  # [lat, lon] format for GraphHopper
            "profile": profile,
            "points_encoded": False,  # Request unencoded points
            "elevation": include_elevation,  # Request elevation data
            "instructions": False,
            "calc_points": True,
        }

        # Add details request if provided
        if details:
            payload["details"] = details

        if custom_model:
            payload["ch.disable"] = True
            payload["custom_model"] = custom_model

        # Make request to GraphHopper
        url = f"{config.base_url.rstrip('/')}/route"

        response = requests.post(
            url,
            data=json.dumps(payload),
            headers={"Content-Type": "application/json"},
            timeout=config.timeout
        )

        if response.status_code != 200:
            error_data = response.json() if response.headers.get('content-type') == 'application/json' else {}
            error_msg = error_data.get("message", f"HTTP {response.status_code}")
            return RouteResponse(
                geometry=RouteGeometry(coordinates=[]),
                metrics=RouteMetrics(distance_meters=0, time_ms=0),
                profile=profile,
                success=False,
                error=error_msg
            )

        data = response.json()

        if not data.get("paths"):
            return RouteResponse(
                geometry=RouteGeometry(coordinates=[]),
                metrics=RouteMetrics(distance_meters=0, time_ms=0),
                profile=profile,
                success=False,
                error="No route found"
            )

        path = data["paths"][0]

        # Extract coordinates
        points_data = path.get("points", {})

        if isinstance(points_data, dict) and points_data.get("type") == "LineString":
            # GeoJSON format with elevation: [[lon, lat, elevation], ...]
            coordinates = points_data.get("coordinates", [])
        else:
            # Fallback to simple array format
            coordinates = points_data if isinstance(points_data, list) else []

        # Convert coordinates to [lon, lat] format for frontend (remove elevation)
        frontend_coordinates = [[coord[0], coord[1]] for coord in coordinates]

        # NEW: Calculate cumulative distances for all coordinates
        coordinate_distances = calculate_cumulative_distances(frontend_coordinates)
        print(f"Calculated distances for {len(coordinate_distances)} coordinates")

        # Create elevation profile from actual coordinate elevation data
        elevation_profile = None
        if include_elevation and coordinates:
            elevation_profile = create_elevation_profile_from_coordinates(
                coordinates,
                coordinate_distances
            )
            print(f"Created elevation profile with {len(elevation_profile)} points from coordinate data")

        # Process details into segments
        segments = None
        if details and "details" in path:
            details_data = path["details"]
            segments = merge_detail_segments(
                frontend_coordinates,
                details_data,
                coordinate_distances  # NEW: Pass coordinate distances
            )
            print(f"Processed {len(segments)} segments with details: {', '.join(details)}")

        return RouteResponse(
            geometry=RouteGeometry(
                coordinates=frontend_coordinates,
                elevation_profile=elevation_profile,
                coordinate_distances=coordinate_distances  # NEW: Include coordinate distances
            ),
            metrics=RouteMetrics(
                distance_meters=path["distance"],
                time_ms=path["time"]
            ),
            profile=profile,
            segments=segments,
            success=True
        )

    except requests.exceptions.RequestException as e:
        return RouteResponse(
            geometry=RouteGeometry(coordinates=[]),
            metrics=RouteMetrics(distance_meters=0, time_ms=0),
            profile=profile,
            success=False,
            error=f"Connection failed: {str(e)}"
        )
    except Exception as e:
        return RouteResponse(
            geometry=RouteGeometry(coordinates=[]),
            metrics=RouteMetrics(distance_meters=0, time_ms=0),
            profile=profile,
            success=False,
            error=f"Unexpected error: {str(e)}"
        )


async def get_route_async(
        start: Tuple[float, float],
        end: Tuple[float, float],
        profile: str,
        custom_model: Optional[Dict[str, Any]],
        config: GraphHopperConfig,
        include_elevation: bool = True,
        details: Optional[List[str]] = None
) -> RouteResponse:
    """Execute route request asynchronously."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        thread_pool,
        execute_route_request,
        start, end, profile, custom_model, config, include_elevation, details
    )