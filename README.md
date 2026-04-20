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

1. Build and start:

```bash
docker compose up --build
```

2. API base URL:

```text
http://localhost:8000
```

3. Example requests:

```bash
curl -X POST http://localhost:8000/request \
  -H "Content-Type: application/json" \
  -d '{"user_id":"u1","payload":{"msg":"hello"}}'

curl http://localhost:8000/stats
```

## Design decisions

- Redis sorted set per user (`rate_limit:{user_id}`) stores request timestamps.
- Lua script performs cleanup, count, limit-check, and insert atomically to avoid race conditions under concurrency.
- A per-user total counter (`rate_total:{user_id}`) is incremented in the same Lua script.
- A global Redis set (`rate_limit:users`) tracks known users for `GET /stats`.
- Async FastAPI + async Redis client for non-blocking I/O.

## Limitations

- In-memory growth: user set and total counters can grow without TTL.
- Single Redis instance: no replication/failover configured.
- No sharding/partitioning for very high cardinality workloads.
- No authentication/authorization (intentionally minimal).

## Notes on concurrency and correctness

- The rate-limiting critical section is implemented in Lua and executed atomically by Redis.
- This prevents race conditions when many requests from the same user arrive simultaneously.
- HTTP status handling is explicit (`429` on limit exceeded).
- Request schema uses FastAPI/Pydantic validation.
