# Installation

## Install `faststream-redis-timers`

=== "uv"

    ```bash
    uv add faststream-redis-timers
    ```

=== "pip"

    ```bash
    pip install faststream-redis-timers
    ```

=== "poetry"

    ```bash
    poetry add faststream-redis-timers
    ```

## Requirements

- Python 3.13+
- Redis 5.0+
- A running Redis instance

## Redis

If you don't have a Redis instance, you can start one with Docker:

```bash
docker run -d -p 6379:6379 redis:latest
```
