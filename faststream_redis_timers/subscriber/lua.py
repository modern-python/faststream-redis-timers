"""
Lua scripts for atomic timer claim/commit.

`CLAIM_LUA`: lease a due timer. Atomically checks the timer is still due
(score <= now) and pushes its score forward by `lease_ttl`. Returns the
payload bytes, or nil if the timer is not due (already leased, canceled,
or scheduled for the future).

`COMMIT_LUA`: remove a timer after successful processing. Always succeeds.
"""

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
