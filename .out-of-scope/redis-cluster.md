# Redis Cluster

`TimersBroker` does not support Redis Cluster. Constructing it with a `RedisCluster` client
raises `TypeError` with a message pointing at single-primary Redis, and Sentinel-managed
primary/replica setups remain the supported high-availability option.

## Why this is out of scope

Every timer topic is stored as a pair of keys built by `TimerStore`:

```python
f"{timeline_key}:{full_topic}"  # sorted set: timer id -> activation time
f"{payloads_key}:{full_topic}"  # hash: timer id -> envelope
```

Several operations touch both keys of a pair at once, and on Cluster that only works when both
keys hash to the same slot:

- the claim and commit Lua scripts, which take both keys as `KEYS[1]` and `KEYS[2]`
- `schedule()`, which writes the sorted set and the hash in one `MULTI`
- `cancel_all()`, which counts and unlinks both keys in one transaction

With the current key names the two keys of a topic land in different slots, so publishing,
consuming and cancelling would all fail with cross-slot errors. Fixing that means reshaping the
key derivation with hash tags. That changes the storage layout for anyone with timers already in
Redis, so it needs either a read-side migration path for existing keys or a hard break in a major
version. That is a design project of its own, and nobody has asked for it: no user has reported
running Cluster and being unable to adopt the package. Until then a clear error at construction
is better than partial support.

## If this is reopened

- Users already choose `timeline_key` and `payloads_key`. If both prefixes share one hash tag
  (for example `{timers}:tl` and `{timers}:pl`), every key hashes to the same slot, which might
  make Cluster work with no storage change, at the cost of putting all timers on one shard.
  Unverified: check that redis-py's `RedisCluster` routes the raw `EVALSHA` calls and
  `transaction=True` pipelines correctly before relying on this.
- Per-topic hash tags (`{full_topic}` inside both keys) would spread topics across shards but
  change the key layout for existing deployments.
- Revisit when a user reports running Redis Cluster and being blocked by this, or when
  FastStream's `RedisClusterBroker` becomes the usual way its Redis integrations are deployed.

## Prior requests

- #66: "Decide whether to support Redis Cluster"
