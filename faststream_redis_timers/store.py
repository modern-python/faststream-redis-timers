"""Redis timer protocol — one module that owns all sorted-set/hash/Lua operations.

Every caller (producer, subscriber, message, broker inspection) crosses this
interface; the raw Redis key derivation and Lua dispatch stay behind it.
"""

import hashlib
import typing
import uuid
from dataclasses import dataclass

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
    redis.call('HDEL', KEYS[3], ARGV[1])
    return nil
end
redis.call('ZADD', KEYS[1], ARGV[3], ARGV[1])
redis.call('HSET', KEYS[3], ARGV[1], ARGV[4])
return payload
"""

_REMOVE_LUA = """\
redis.call('ZREM', KEYS[1], ARGV[1])
redis.call('HDEL', KEYS[2], ARGV[1])
redis.call('HDEL', KEYS[3], ARGV[1])
"""

_COMMIT_LUA = (
    """\
if redis.call('HGET', KEYS[3], ARGV[1]) ~= ARGV[2] then return 0 end
"""
    + _REMOVE_LUA
    + "return 1\n"
)

_REMOVE_SHA = hashlib.sha1(_REMOVE_LUA.encode(), usedforsecurity=False).hexdigest()


@dataclass(frozen=True, slots=True)
class TimerClaim:
    payload: bytes
    token: str


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

    def __init__(
        self,
        connection: "ConnectionState",
        timeline_key: str,
        payloads_key: str,
        claims_key: str | None = None,
    ) -> None:
        self._connection = connection
        self._timeline_key = timeline_key
        self._payloads_key = payloads_key
        self._claims_key_prefix = claims_key

    @property
    def timeline_key(self) -> str:
        return self._timeline_key

    @property
    def payloads_key(self) -> str:
        return self._payloads_key

    def _keys(self, full_topic: str) -> tuple[str, str]:
        """Return (timeline_key, payloads_key) for the given topic."""
        return f"{self._timeline_key}:{full_topic}", f"{self._payloads_key}:{full_topic}"

    def _claims_key(self, full_topic: str) -> str:
        if self._claims_key_prefix is not None:
            return f"{self._claims_key_prefix}:{full_topic}"
        encoder = self._connection.client.connection_pool.get_encoder()
        keys = [encoder.encode(key) for key in self._keys(full_topic)]
        identity = b"".join(len(key).to_bytes(8, "big") + key for key in keys)
        return f"timers_claims:{hashlib.sha256(identity).hexdigest()}"

    def _protocol_keys(self, full_topic: str) -> tuple[str, str, str]:
        keys = (*self._keys(full_topic), self._claims_key(full_topic))
        encoder = self._connection.client.connection_pool.get_encoder()
        if len({encoder.encode(key) for key in keys}) != len(keys):
            msg = "Timeline, payloads, and claims keys must be distinct after Redis encoding."
            raise ValueError(msg)
        return keys

    async def schedule(self, full_topic: str, timer_id: str, payload: bytes, activation_ts: float) -> None:
        """Add a timer to the timeline and store its payload atomically."""
        tl_key, pl_key, cl_key = self._protocol_keys(full_topic)
        client = self._connection.client
        async with client.pipeline(transaction=True) as pipe:
            pipe.zadd(tl_key, {timer_id: activation_ts})
            pipe.hset(pl_key, timer_id, payload)
            pipe.hdel(cl_key, timer_id)
            await pipe.execute()

    async def due(self, full_topic: str, now: float, limit: int) -> list[str]:
        """Return up to *limit* timer IDs whose activation_ts <= *now*.

        Fetches raw IDs regardless of response decoding. IDs that cannot round-trip
        through the client's encoder are conditionally removed using their original bytes.
        """
        tl_key, _ = self._keys(full_topic)
        client = self._connection.client
        raw_ids: list[bytes] = await client.execute_command(
            "ZRANGEBYSCORE",
            tl_key,
            "-inf",
            now,
            "LIMIT",
            0,
            limit,
            **{NEVER_DECODE: []},
        )
        encoder = client.connection_pool.get_encoder()
        result: list[str] = []
        for raw_id in raw_ids:
            try:
                timer_id = raw_id.decode(encoder.encoding, encoder.encoding_errors)
            except UnicodeDecodeError:
                timer_id = None
            if timer_id is not None and encoder.encode(timer_id) == raw_id:
                result.append(timer_id)
            else:
                claim = await self.claim(full_topic, raw_id, now, 1)
                if claim is not None:
                    await self.commit(full_topic, raw_id, claim.token)
        return result

    async def claim(self, full_topic: str, timer_id: str | bytes, now: float, lease_ttl: int) -> TimerClaim | None:
        """Atomically lease a due timer and return its payload and ownership token.

        The timer's score is pushed forward by *lease_ttl* so other workers skip
        it while the handler runs.  Returns ``None`` if the timer is already
        leased, canceled, or scheduled for the future.
        """
        tl_key, pl_key, cl_key = self._protocol_keys(full_topic)
        client = self._connection.client
        claim_score = now + lease_ttl
        token = uuid.uuid4().hex
        result: bytes | None = await _eval_cached(
            client,
            _CLAIM_LUA,
            _CLAIM_SHA,
            3,
            tl_key,
            pl_key,
            cl_key,
            timer_id,
            now,
            claim_score,
            token,
        )
        return TimerClaim(result, token) if result is not None else None

    async def commit(self, full_topic: str, timer_id: str | bytes, token: str) -> None:
        """Remove only the currently owned claim; stale completion is a no-op."""
        tl_key, pl_key, cl_key = self._protocol_keys(full_topic)
        await _eval_cached(
            self._connection.client,
            _COMMIT_LUA,
            _COMMIT_SHA,
            3,
            tl_key,
            pl_key,
            cl_key,
            timer_id,
            token,
        )

    async def remove(self, full_topic: str, timer_id: str) -> None:
        """Remove a timer from both the timeline and the payloads hash atomically.

        Explicit cancellation is unconditional, unlike claim completion.
        """
        tl_key, pl_key, cl_key = self._protocol_keys(full_topic)
        await _eval_cached(
            self._connection.client,
            _REMOVE_LUA,
            _REMOVE_SHA,
            3,
            tl_key,
            pl_key,
            cl_key,
            timer_id,
        )

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
        encoder = client.connection_pool.get_encoder()
        return [r.decode(encoder.encoding, encoder.encoding_errors) if isinstance(r, bytes) else r for r in raw_ids]

    async def is_pending(self, full_topic: str, timer_id: str) -> bool:
        """Return True if a timer with this ID is still in the timeline."""
        tl_key, _ = self._keys(full_topic)
        client = self._connection.client
        score = await client.zscore(tl_key, timer_id)
        return score is not None

    async def cancel_all(self, full_topic: str) -> int:
        """Atomically remove every timer on this topic. Returns the count removed."""
        tl_key, pl_key, cl_key = self._protocol_keys(full_topic)
        client = self._connection.client
        async with client.pipeline(transaction=True) as pipe:
            pipe.zcard(tl_key)
            pipe.unlink(tl_key)
            pipe.unlink(pl_key)
            pipe.unlink(cl_key)
            results = await pipe.execute()
        return int(results[0])
