# FastAPI Redis Rate Limiter

Backend service using FastAPI and Redis with a Lua-based sliding window rate limiter for accurate limits under concurrent requests.

## What it does

- `POST /request`
  - Input: `{ "user_id": string }`
  - Enforces: max 5 requests per user per 60 seconds
  - Returns `429` when the limit is exceeded
  - Returns 
  ```
    { 
      "status": "ok", 
      "reset_in_seconds": int, 
      "requests_left_in_window": int 
    }
    ``` 
    when allowed
      
- `GET /stats`
  - Returns per-user stats:
    - `total_requests`
    - `requests_in_current_window`
    - `remaining_quota`
    - `window_reset_in_seconds`
    - `last_request_ts`

## Project structure

```text
app/
  main.py
  api/routes.py
  core/config.py
  services/rate_limiter.py
  services/stats.py
  models/schemas.py
```

## Run with Docker

1. Start Redis:

```bash
docker compose up
```

2. Start fastAPI app:
```cmd
uvicorn app.main:app
```

3. API base URL:

```text
http://localhost:8000
```

4. Example requests:

```bash
curl -X POST http://localhost:8000/request \
  -H "Content-Type: application/json" \
  -d '{"user_id":"u1"}'

curl http://localhost:8000/stats?user_id=u1
```

Sample `GET /stats?user_id=u1` response:

```json
{
  "users": {
    "u1": {
      "total_requests": 12,
      "requests_in_current_window": 3,
      "remaining_quota": 2,
      "window_reset_in_seconds": 25,
      "last_request_ts": 1713540000
    }
  }
}
```

## Design decisions

- Each user has a Redis sorted set (`rate_limit:{user_id}`) that stores request timestamps.
- A Lua script handles everything in one step: remove old requests, count current ones, check limit, and add new request.
- This makes the rate limiting safe under concurrent requests (no race conditions).
- A separate counter (`rate_total:{user_id}`) keeps track of total requests per user.
- A global Redis set (`rate_limit:users`) stores all users for the `/stats` endpoint.
- FastAPI and async Redis are used for non-blocking performance.

## Limitations

- Data can grow in memory since there is no cleanup for old users or counters.
- Only a single Redis instance is used (no backup or failover).
- Not designed for very large scale (no sharding).
- No authentication or security added (kept simple on purpose).

## Notes on concurrency and correctness

- The Lua script runs atomically inside Redis, so multiple requests don’t interfere with each other.
- This ensures correct rate limiting even under heavy parallel requests.
- Returns proper HTTP status (`429`) when limit is exceeded.
- Includes `Retry-After` to indicate when the client can retry.
- Input is validated using FastAPI/Pydantic.

## Deployment

- Deployed on Render
- API docs: https://redis-rate-limiter-7nhz.onrender.com/docs
- A cron job is configured to keep the service awake (prevents cold starts)