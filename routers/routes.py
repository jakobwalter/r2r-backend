from fastapi import APIRouter, HTTPException, Depends
import asyncio

from models import RouteRequest, RouteResponse
from dependencies import get_graphhopper_config
from services import get_custom_model, get_route_async
from r2r_bo.graphhopper.config import GraphHopperConfig

router = APIRouter()


@router.post("/route", response_model=RouteResponse)
async def get_route(
        request: RouteRequest,
        config: GraphHopperConfig = Depends(get_graphhopper_config)
):
    """Calculate a route between two points."""

    # Use default profile if none provided
    profile = request.profile or config.default_profile

    # Use default details if none provided
    details = request.details or ['surface', 'smoothness']  # Default details

    # Generate custom model if needed
    custom_model = None
    if request.custom_profile_id and request.parameters:
        try:
            loop = asyncio.get_event_loop()
            custom_model = await loop.run_in_executor(
                None, get_custom_model, request.custom_profile_id, request.parameters
            )
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Custom profile error: {str(e)}")

    # Execute route request
    start = (request.start.lat, request.start.lon)
    end = (request.end.lat, request.end.lon)

    return await get_route_async(
        start, end, profile, custom_model, config,
        request.include_elevation,
        details  # Pass the details list
    )