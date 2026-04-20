import inspect
import time
from collections.abc import Awaitable
from dataclasses import dataclass
from typing import TypeVar, cast

from redis.asyncio import Redis
from redis.exceptions import NoScriptError


T = TypeVar("T")


async def _resolve_redis_result(value: T | Awaitable[T]) -> T:
    if inspect.isawaitable(value):
        return await cast(Awaitable[T], value)
    return value


def _to_text(value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, bytes):
        return value.decode()
    if isinstance(value, bytearray):
        return bytes(value).decode()
    if isinstance(value, memoryview):
        return value.tobytes().decode()
    return str(value)


ALLOW_REQUEST_LUA = """
local rate_key = KEYS[1]
local total_key = KEYS[2]
local users_key = KEYS[3]
local seq_key = KEYS[4]

local now_ms = tonumber(ARGV[1])
local window_ms = tonumber(ARGV[2])
local max_requests = tonumber(ARGV[3])
local user_id = ARGV[4]
local ttl_seconds = tonumber(ARGV[5])

local min_score = now_ms - window_ms
redis.call('ZREMRANGEBYSCORE', rate_key, 0, min_score)

local current_count = redis.call('ZCARD', rate_key)
local total_count = redis.call('INCR', total_key)
redis.call('SADD', users_key, user_id)

local oldest = redis.call('ZRANGE', rate_key, 0, 0, 'WITHSCORES')
local reset_in_seconds = 0
if oldest[2] then
    local oldest_ms = tonumber(oldest[2])
    local reset_ms = (oldest_ms + window_ms) - now_ms
    if reset_ms < 0 then
        reset_ms = 0
    end
    reset_in_seconds = math.ceil(reset_ms / 1000)
end

if current_count >= max_requests then
    return {0, current_count, total_count, reset_in_seconds, 0}
end

local seq = redis.call('INCR', seq_key)
local member = tostring(now_ms) .. '-' .. tostring(seq)
redis.call('ZADD', rate_key, now_ms, member)
redis.call('EXPIRE', rate_key, ttl_seconds)
redis.call('EXPIRE', seq_key, ttl_seconds)

local new_count = current_count + 1
local oldest_after_add = redis.call('ZRANGE', rate_key, 0, 0, 'WITHSCORES')
local reset_in_seconds_after_add = 0
if oldest_after_add[2] then
    local oldest_ms_after_add = tonumber(oldest_after_add[2])
    local reset_ms_after_add = (oldest_ms_after_add + window_ms) - now_ms
    if reset_ms_after_add < 0 then
        reset_ms_after_add = 0
    end
    reset_in_seconds_after_add = math.ceil(reset_ms_after_add / 1000)
end

local requests_left = max_requests - new_count
if requests_left < 0 then
    requests_left = 0
end

return {1, new_count, total_count, reset_in_seconds_after_add, requests_left}
"""


WINDOW_COUNT_LUA = """
local rate_key = KEYS[1]
local now_ms = tonumber(ARGV[1])
local window_ms = tonumber(ARGV[2])

local min_score = now_ms - window_ms
redis.call('ZREMRANGEBYSCORE', rate_key, 0, min_score)
return redis.call('ZCARD', rate_key)
"""


WINDOW_SNAPSHOT_LUA = """
local rate_key = KEYS[1]
local now_ms = tonumber(ARGV[1])
local window_ms = tonumber(ARGV[2])

local min_score = now_ms - window_ms
redis.call('ZREMRANGEBYSCORE', rate_key, 0, min_score)

local current_count = redis.call('ZCARD', rate_key)
if current_count == 0 then
    return {0, 0, 0}
end

local oldest = redis.call('ZRANGE', rate_key, 0, 0, 'WITHSCORES')
local newest = redis.call('ZREVRANGE', rate_key, 0, 0, 'WITHSCORES')

local oldest_ms = tonumber(oldest[2])
local newest_ms = tonumber(newest[2])

local reset_ms = (oldest_ms + window_ms) - now_ms
if reset_ms < 0 then
    reset_ms = 0
end

local reset_in_seconds = math.ceil(reset_ms / 1000)
local last_request_ts = math.floor(newest_ms / 1000)

return {current_count, reset_in_seconds, last_request_ts}
"""


@dataclass(frozen=True)
class RateLimitResult:
    allowed: bool
    requests_in_window: int
    total_requests: int
    reset_in_seconds: int
    requests_left_in_window: int


@dataclass(frozen=True)
class WindowSnapshot:
    requests_in_window: int
    window_reset_in_seconds: int
    last_request_ts: int


class RateLimiter:
    def __init__(
        self, redis: Redis, max_requests: int = 5, window_seconds: int = 60
    ) -> None:
        self._redis = redis
        self._max_requests = max_requests
        self._window_seconds = window_seconds
        self._allow_script_sha: str | None = None
        self._window_count_script_sha: str | None = None
        self._window_snapshot_script_sha: str | None = None
        self.users_set_key = "rate_limit:users"

    @property
    def max_requests(self) -> int:
        return self._max_requests

    async def initialize(self) -> None:
        self._allow_script_sha = await _resolve_redis_result(
            self._redis.script_load(ALLOW_REQUEST_LUA)
        )
        self._window_count_script_sha = await _resolve_redis_result(
            self._redis.script_load(WINDOW_COUNT_LUA)
        )
        self._window_snapshot_script_sha = await _resolve_redis_result(
            self._redis.script_load(WINDOW_SNAPSHOT_LUA)
        )

    def _rate_limit_key(self, user_id: str) -> str:
        return f"rate_limit:{user_id}"

    def _seq_key(self, user_id: str) -> str:
        return f"rate_limit:{user_id}:seq"

    def total_requests_key(self, user_id: str) -> str:
        return f"rate_total:{user_id}"

    async def allow_request(self, user_id: str) -> RateLimitResult:
        now_ms = int(time.time() * 1000)
        window_ms = self._window_seconds * 1000
        ttl_seconds = self._window_seconds + 1

        keys = [
            self._rate_limit_key(user_id),
            self.total_requests_key(user_id),
            self.users_set_key,
            self._seq_key(user_id),
        ]
        args = [now_ms, window_ms, self._max_requests, user_id, ttl_seconds]

        raw_result = await self._run_allow_script(keys, args)
        allowed = int(raw_result[0]) == 1
        requests_in_window = int(raw_result[1])
        total_requests = int(raw_result[2])
        reset_in_seconds = int(raw_result[3])
        requests_left_in_window = int(raw_result[4])

        return RateLimitResult(
            allowed=allowed,
            requests_in_window=requests_in_window,
            total_requests=total_requests,
            reset_in_seconds=reset_in_seconds,
            requests_left_in_window=requests_left_in_window,
        )

    async def get_current_window_count(self, user_id: str) -> int:
        now_ms = int(time.time() * 1000)
        window_ms = self._window_seconds * 1000

        key = self._rate_limit_key(user_id)
        raw_count = await self._run_window_count_script([key], [now_ms, window_ms])
        return int(raw_count)

    async def get_window_snapshot(self, user_id: str) -> WindowSnapshot:
        now_ms = int(time.time() * 1000)
        window_ms = self._window_seconds * 1000

        key = self._rate_limit_key(user_id)
        raw_result = await self._run_window_snapshot_script([key], [now_ms, window_ms])

        return WindowSnapshot(
            requests_in_window=int(raw_result[0]),
            window_reset_in_seconds=int(raw_result[1]),
            last_request_ts=int(raw_result[2]),
        )

    async def get_total_requests(self, user_id: str) -> int:
        value = await _resolve_redis_result(
            self._redis.get(self.total_requests_key(user_id))
        )
        return int(_to_text(value)) if value is not None else 0

    async def get_known_users(self) -> list[str]:
        users = await _resolve_redis_result(self._redis.smembers(self.users_set_key))
        return [_to_text(user) for user in users]

    async def _run_allow_script(
        self, keys: list[str], args: list[int | str]
    ) -> list[int]:
        if self._allow_script_sha is None:
            await self.initialize()

        if self._allow_script_sha is None:
            raise RuntimeError("Allow-request Lua script is not loaded")
        allow_sha = self._allow_script_sha

        try:
            result = await _resolve_redis_result(
                self._redis.evalsha(allow_sha, len(keys), *keys, *args)
            )
            return cast(list[int], result)
        except NoScriptError:
            allow_sha = cast(
                str,
                await _resolve_redis_result(self._redis.script_load(ALLOW_REQUEST_LUA)),
            )
            self._allow_script_sha = allow_sha
            result = await _resolve_redis_result(
                self._redis.evalsha(allow_sha, len(keys), *keys, *args)
            )
            return cast(list[int], result)

    async def _run_window_count_script(self, keys: list[str], args: list[int]) -> int:
        if self._window_count_script_sha is None:
            await self.initialize()

        if self._window_count_script_sha is None:
            raise RuntimeError("Window-count Lua script is not loaded")
        window_count_sha = self._window_count_script_sha

        result = await _resolve_redis_result(
            self._redis.evalsha(
                window_count_sha,
                len(keys),
                *keys,
                *args,
            )
        )
        return cast(int, result)

    async def _run_window_snapshot_script(
        self, keys: list[str], args: list[int]
    ) -> list[int]:
        if self._window_snapshot_script_sha is None:
            await self.initialize()

        if self._window_snapshot_script_sha is None:
            raise RuntimeError("Window-snapshot Lua script is not loaded")
        window_snapshot_sha = self._window_snapshot_script_sha

        result = await _resolve_redis_result(
            self._redis.evalsha(
                window_snapshot_sha,
                len(keys),
                *keys,
                *args,
            )
        )
        return cast(list[int], result)
    