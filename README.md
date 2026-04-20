# FastAPI Redis Rate Limiter

Minimal backend service using FastAPI and Redis with an atomic Lua-scripted sliding-window rate limiter.

## What it does

- `POST /request`
  - Input: `{ "user_id": string, "payload": any }`
  - Enforces: max 5 requests per user per 60 seconds
  - Returns `429` when the limit is exceeded
  - Returns `{ "status": "ok" }` when allowed
- `GET /stats`
  - Returns per-user stats:
    - `total_requests`
    - `requests_in_current_window`

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
- Input is validated using FastAPI/Pydantic.