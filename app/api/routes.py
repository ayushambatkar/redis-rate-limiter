from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from app.models.schemas import RequestBody, RequestResponse, StatsResponse
from app.services.rate_limiter import RateLimiter
from app.services.stats import StatsService


router = APIRouter()


def get_rate_limiter(request: Request) -> RateLimiter:
    return request.app.state.rate_limiter


def get_stats_service(request: Request) -> StatsService:
    return request.app.state.stats_service


@router.post("/request", response_model=RequestResponse)
async def submit_request(
    body: RequestBody,
    rate_limiter: RateLimiter = Depends(get_rate_limiter),
) -> RequestResponse:
    result = await rate_limiter.allow_request(body.user_id)
    if not result.allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "message": "Rate limit exceeded",
                "reset_in_seconds": result.reset_in_seconds,
                "requests_left_in_window": result.requests_left_in_window,
            },
            headers={"Retry-After": str(result.reset_in_seconds)},
        )

    return RequestResponse(
        status="ok",
        reset_in_seconds=result.reset_in_seconds,
        requests_left_in_window=result.requests_left_in_window,
    )


@router.get("/stats", response_model=StatsResponse)
async def get_stats(
    stats_service: StatsService = Depends(get_stats_service),
    user_id: str | None = Query(
        None,
        description="Optional user_id to filter stats for a specific user",
    ),
) -> StatsResponse:
    return await stats_service.get_stats(user_id=user_id)
