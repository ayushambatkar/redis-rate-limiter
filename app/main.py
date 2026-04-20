from contextlib import asynccontextmanager

from fastapi import FastAPI
from redis.asyncio import Redis

from app.api.routes import router
from app.core.config import settings
from app.services.rate_limiter import RateLimiter
from app.services.stats import StatsService


@asynccontextmanager
async def lifespan(app: FastAPI):
    redis = Redis.from_url(settings.redis_url, decode_responses=True)

    rate_limiter = RateLimiter(
        redis=redis,
        max_requests=settings.max_requests,
        window_seconds=settings.window_seconds,
    )
    await rate_limiter.initialize()

    app.state.redis = redis
    app.state.rate_limiter = rate_limiter
    app.state.stats_service = StatsService(redis=redis, rate_limiter=rate_limiter)

    try:
        yield
    finally:
        await redis.aclose()


app = FastAPI(title="Rate Limiter Service", lifespan=lifespan)
app.include_router(router)
