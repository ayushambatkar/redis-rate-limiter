import asyncio

from redis.asyncio import Redis

from app.models.schemas import StatsResponse, UserStats
from app.services.rate_limiter import RateLimiter


class StatsService:
    def __init__(self, redis: Redis, rate_limiter: RateLimiter) -> None:
        self._redis = redis
        self._rate_limiter = rate_limiter

    async def get_stats(self, user_id: str | None) -> StatsResponse:
        if user_id is not None:
            users = [user_id]
        else:
            users = sorted(await self._rate_limiter.get_known_users())
        if not users:
            return StatsResponse(users={})

        pipeline = self._redis.pipeline(transaction=False)
        for user_id in users:
            pipeline.get(self._rate_limiter.total_requests_key(user_id))
        raw_totals = await pipeline.execute()

        window_snapshots = await asyncio.gather(
            *(self._rate_limiter.get_window_snapshot(user_id) for user_id in users)
        )

        per_user: dict[str, UserStats] = {}
        for user_id, raw_total, window_snapshot in zip(
            users, raw_totals, window_snapshots, strict=True
        ):
            total = int(raw_total) if raw_total is not None else 0
            remaining_quota = max(
                self._rate_limiter.max_requests - window_snapshot.requests_in_window,
                0,
            )
            per_user[user_id] = UserStats(
                total_requests=total,
                requests_in_current_window=window_snapshot.requests_in_window,
                remaining_quota=remaining_quota,
                window_reset_in_seconds=window_snapshot.window_reset_in_seconds,
                last_request_ts=window_snapshot.last_request_ts,
            )

        return StatsResponse(users=per_user)
