# faststream-redis-timers

FastStream broker integration for Redis-backed distributed timer scheduling.

## Commands

- `just test` — run full test suite (spins up Redis via docker-compose)
- `just lint` — format and lint
- `just install` — install deps

## Tests

- `test_faststream_redis_timers/test_main.py` — unit tests using `TestTimersBroker` (no Redis required)
- `test_faststream_redis_timers/test_integration.py` — integration tests (requires Redis via `REDIS_URL` env var)
