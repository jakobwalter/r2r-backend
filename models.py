from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any


class RoutePoint(BaseModel):
    lat: float = Field(..., ge=-90, le=90)
    lon: float = Field(..., ge=-180, le=180)


class RouteSegment(BaseModel):
    """Flexible segment with any detail attributes from GraphHopper"""
    start_index: int
    end_index: int
    start_distance: float  # Distance from start in meters
    end_distance: float  # Distance from start in meters
    attributes: Dict[str, Any]  # Flexible dict for any detail type

    # Helper properties for common attributes
    @property
    def surface(self) -> Optional[str]:
        return self.attributes.get('surface')

    @property
    def smoothness(self) -> Optional[str]:
        return self.attributes.get('smoothness')

    @property
    def track_type(self) -> Optional[str]:
        return self.attributes.get('track_type')

    @property
    def average_slope(self) -> Optional[float]:
        return self.attributes.get('average_slope')

    @property
    def max_speed(self) -> Optional[float]:
        return self.attributes.get('max_speed')

    @property
    def road_class(self) -> Optional[str]:
        return self.attributes.get('road_class')


class RouteRequest(BaseModel):
    start: RoutePoint
    end: RoutePoint
    profile: Optional[str] = None
    custom_profile_id: Optional[int] = None
    parameters: Optional[Dict[str, Any]] = None
    include_elevation: bool = True
    details: Optional[List[str]] = None  # List of detail types to request
    # Common options: ['surface', 'smoothness', 'track_type', 'average_slope',
    #                  'max_speed', 'road_class', 'road_environment', 'road_access']


class RouteMetrics(BaseModel):
    distance_meters: float
    time_ms: int


class ElevationPoint(BaseModel):
    distance: float  # Distance along route in meters
    elevation: float  # Elevation in meters
    coordinate_index: int


class RouteGeometry(BaseModel):
    coordinates: List[List[float]]  # [lon, lat] pairs
    elevation_profile: Optional[List[ElevationPoint]] = None
    coordinate_distances: Optional[List[float]] = None


class RouteResponse(BaseModel):
    geometry: RouteGeometry
    metrics: RouteMetrics
    profile: str
    segments: Optional[List[RouteSegment]] = None  # Processed segments with details
    success: bool = True
    error: Optional[str] = None