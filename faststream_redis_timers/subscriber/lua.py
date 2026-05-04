"""
Lua scripts for atomic timer claim/commit.

`CLAIM_LUA`: lease a due timer. Atomically checks the timer is still due
(score <= now) and pushes its score forward by `lease_ttl`. Returns the
payload bytes, or nil if the timer is not due (already leased, canceled,
or scheduled for the future).

`COMMIT_LUA`: remove a timer after successful processing. Always succeeds.

Both scripts are dispatched via :func:`eval_cached`, which uses ``EVALSHA``
with a ``NOSCRIPT`` fallback to ``SCRIPT LOAD`` so the script body only
crosses the wire once per Redis instance lifetime.
"""

import hashlib
import typing

from redis.client import NEVER_DECODE
from redis.exceptions import NoScriptError


if typing.TYPE_CHECKING:
    from faststream_redis_timers.configs import RedisClient


CLAIM_LUA = """\
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

COMMIT_LUA = """\
redis.call('ZREM', KEYS[1], ARGV[1])
redis.call('HDEL', KEYS[2], ARGV[1])
"""

CLAIM_SHA = hashlib.sha1(CLAIM_LUA.encode(), usedforsecurity=False).hexdigest()
COMMIT_SHA = hashlib.sha1(COMMIT_LUA.encode(), usedforsecurity=False).hexdigest()


async def eval_cached(
    client: "RedisClient",
    script: str,
    sha: str,
    num_keys: int,
    *args: typing.Any,
) -> typing.Any:
    """
    Run a script via EVALSHA, falling back to SCRIPT LOAD + EVALSHA on NOSCRIPT.

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
