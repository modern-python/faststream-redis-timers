"""Redis timer protocol — one module that owns all sorted-set/hash/Lua operations.

Every caller (producer, subscriber, message, broker inspection) crosses this
interface; the raw Redis key derivation and Lua dispatch stay behind it.

Lua scripts for atomic timer claim/commit
-----------------------------------------
``_CLAIM_LUA``: lease a due timer. Atomically checks the timer is still due
(score <= now) and pushes its score forward by ``lease_ttl``. Returns the
payload bytes, or nil if the timer is not due (already leased, canceled,
or scheduled for the future).

``_COMMIT_LUA``: remove a timer after successful processing. Always succeeds.

Both scripts are dispatched via :func:`_eval_cached`, which uses ``EVALSHA``
with a ``NOSCRIPT`` fallback to ``SCRIPT LOAD`` so the script body only
crosses the wire once per Redis instance lifetime.
"""

import hashlib
import typing

from redis.client import NEVER_DECODE
from redis.exceptions import NoScriptError


if typing.TYPE_CHECKING:
    from faststream_redis_timers.configs import ConnectionState, RedisClient


_CLAIM_LUA = """\
local score = redis.call('ZSCORE', KEYS[1], ARGV[1])
if not score or tonumber(score) > tonumber(ARGV[2]) then return nil end
local payload = redis.call('HGET', KEYS[2], ARGV[1])
if not payload then
    redis.call('ZREM', KEYS[1], ARGV[1])
    return nil
end
redis.call('ZADD', KEYS[1], ARGV[3], ARGV[1])
return payload
"""

_COMMIT_LUA = """\
redis.call('ZREM', KEYS[1], ARGV[1])
redis.call('HDEL', KEYS[2], ARGV[1])
"""

_CLAIM_SHA = hashlib.sha1(_CLAIM_LUA.encode(), usedforsecurity=False).hexdigest()
_COMMIT_SHA = hashlib.sha1(_COMMIT_LUA.encode(), usedforsecurity=False).hexdigest()


async def _eval_cached(
    client: "RedisClient",
    script: str,
    sha: str,
    num_keys: int,
    *args: typing.Any,
) -> typing.Any:
    """Run a script via EVALSHA, falling back to SCRIPT LOAD + EVALSHA on NOSCRIPT.

    Uses ``NEVER_DECODE`` so the script's reply is returned as raw bytes even when the
    Redis client was constructed with ``decode_responses=True``: the timer payload is
    a binary envelope (BinaryMessageFormatV1) and forcing UTF-8 decoding on it would
    fail at the first non-ASCII byte.
    """
    options = {NEVER_DECODE: []}
    try:
        return await client.execute_command("EVALSHA", sha, num_keys, *args, **options)
    except NoScriptError:
        await client.script_load(script)
        return await client.execute_command("EVALSHA", sha, num_keys, *args, **options)


class TimerStore:
    """Broker-wide store for the Redis timer protocol.

    One instance per broker; ``full_topic`` (prefix already applied) is passed
    as a method argument so the same store serves all topics without a per-topic
    registry.
    """

    def __init__(self, connection: "ConnectionState", timeline_key: str, payloads_key: str) -> None:
        self._connection = connection
        self._timeline_key = timeline_key
        self._payloads_key = payloads_key

    @property
    def timeline_key(self) -> str:
        return self._timeline_key

    @property
    def payloads_key(self) -> str:
        return self._payloads_key

    def _keys(self, full_topic: str) -> tuple[str, str]:
        """Return (timeline_key, payloads_key) for the given topic."""
        return f"{self._timeline_key}:{full_topic}", f"{self._payloads_key}:{full_topic}"

    async def schedule(self, full_topic: str, timer_id: str, payload: bytes, activation_ts: float) -> None:
        """Add a timer to the timeline and store its payload atomically."""
        tl_key, pl_key = self._keys(full_topic)
        client = self._connection.client
        async with client.pipeline(transaction=True) as pipe:
            pipe.zadd(tl_key, {timer_id: activation_ts})
            pipe.hset(pl_key, timer_id, payload)
            await pipe.execute()

    async def due(self, full_topic: str, now: float, limit: int) -> list[str]:
        """Return up to *limit* timer IDs whose activation_ts <= *now*.

        Handles both bytes-mode and str-mode Redis clients.  Any member whose
        bytes ID cannot be decoded as UTF-8 is atomically removed (self-heal)
        and excluded from the result.
        """
        tl_key, pl_key = self._keys(full_topic)
        client = self._connection.client
        raw_ids: list[bytes] | list[str] = await client.zrangebyscore(tl_key, "-inf", now, start=0, num=limit)
        result: list[str] = []
        for raw_id in raw_ids:
            if isinstance(raw_id, bytes):
                try:
                    result.append(raw_id.decode())
                except UnicodeDecodeError:
                    await _eval_cached(client, _COMMIT_LUA, _COMMIT_SHA, 2, tl_key, pl_key, raw_id)
            else:
                result.append(raw_id)
        return result

    async def claim(self, full_topic: str, timer_id: str, now: float, lease_ttl: int) -> bytes | None:
        """Atomically lease a due timer and return its payload, or None if contested.

        The timer's score is pushed forward by *lease_ttl* so other workers skip
        it while the handler runs.  Returns ``None`` if the timer is already
        leased, canceled, or scheduled for the future.
        """
        tl_key, pl_key = self._keys(full_topic)
        client = self._connection.client
        claim_score = now + lease_ttl
        result: bytes | None = await _eval_cached(
            client, _CLAIM_LUA, _CLAIM_SHA, 2, tl_key, pl_key, timer_id, now, claim_score
        )
        return result

    async def remove(self, full_topic: str, timer_id: str) -> None:
        """Remove a timer from both the timeline and the payloads hash atomically.

        Covers commit (after ack/reject), cancel, and orphan cleanup — all three
        paths produce the same effect via a single EVALSHA round-trip.
        """
        tl_key, pl_key = self._keys(full_topic)
        client = self._connection.client
        await _eval_cached(client, _COMMIT_LUA, _COMMIT_SHA, 2, tl_key, pl_key, timer_id)

    async def pending(self, full_topic: str, before: float | None = None) -> list[str]:
        """Return all pending timer IDs, optionally restricted to those due by *before*.

        Timers currently being processed have their score pushed ``lease_ttl``
        seconds forward, so they appear in the default (``before=None``) result
        but are excluded when *before* is the current wall time.
        """
        tl_key, _ = self._keys(full_topic)
        client = self._connection.client
        score_max: str | float = before if before is not None else "+inf"
        raw_ids: list[bytes] | list[str] = await client.zrangebyscore(tl_key, "-inf", score_max)
        return [r.decode() if isinstance(r, bytes) else r for r in raw_ids]

    async def is_pending(self, full_topic: str, timer_id: str) -> bool:
        """Return True if a timer with this ID is still in the timeline."""
        tl_key, _ = self._keys(full_topic)
        client = self._connection.client
        score = await client.zscore(tl_key, timer_id)
        return score is not None

    async def cancel_all(self, full_topic: str) -> int:
        """Atomically remove every timer on this topic. Returns the count removed."""
        tl_key, pl_key = self._keys(full_topic)
        client = self._connection.client
        async with client.pipeline(transaction=True) as pipe:
            pipe.zcard(tl_key)
            pipe.unlink(tl_key)
            pipe.unlink(pl_key)
            results = await pipe.execute()
        return int(results[0])
