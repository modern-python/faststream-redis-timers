---
summary: Extract a deep TimerStore that owns the Redis timer protocol (timeline + payloads + lease Lua) and topic-key derivation, collapsing five scattered Redis touch-points behind one interface.
---

# Timer store — design

## Goal

Give the Redis timer protocol a **module**. Today the sorted-set + hash +
lease-Lua contract has no interface, so its rules are spread across five files
and the `{key}:{full_topic}` derivation is spelled three times. Collapse all of
it behind one deep `TimerStore` whose small interface every caller crosses —
producer, subscriber, the delivered message, and broker inspection.

This is **candidate 1** of the architecture review. It is the root the in-memory
test adapter (candidate 2) and the poll-schedule extraction (candidate 3) branch
from; both are explicitly out of scope here.

## Background

The protocol is scattered (file:line at time of writing):

- **`publisher/producer.py:49–61`** — `ZADD`+`HSET` (publish), `ZREM`+`HDEL`
  (cancel), each via a `pipeline(transaction=True)`.
- **`subscriber/usecase.py:135–137, 161–164, 171–181`** — `ZRANGEBYSCORE`
  (poll), the non-UTF-8 orphan `ZREM`+`HDEL`, and `CLAIM_LUA` via `eval_cached`.
- **`message.py:44–55`** — `COMMIT_LUA` via `eval_cached` on `ack`/`reject`.
- **`broker.py:219, 232–234, 248–250`** — `ZSCORE` (`has_pending`),
  `ZRANGEBYSCORE` (`get_pending_timers`), `ZCARD`+`UNLINK` (`cancel_all`).
- **`subscriber/lua.py`** — the `CLAIM_LUA`/`COMMIT_LUA` bodies + `eval_cached`,
  imported by *both* `message.py` and `subscriber/usecase.py` (a shared seam).

Two consequences:

1. **No locality.** Understanding "how a timer is stored" means reading five
   files; a protocol change touches all of them. The key derivation
   `f"{timeline_key}:{full_topic}"` is recomputed in `producer.py:45`,
   `subscriber/config.py:26`, and `broker.py:256`.
2. **Three spellings of one effect.** `commit` (Lua), `cancel` (pipeline), and
   the orphan cleanup (pipeline) all do the same thing — remove an id from the
   timeline and the payloads hash.

The deletion test passes: delete the (hypothetical) store and the complexity
reappears in four callers. It earns its keep.

## Design

One concrete, broker-wide `TimerStore` in a new top-level module
`faststream_redis_timers/store.py`. Nine decisions, each settled in design
review:

1. **Broker-wide, `full_topic` passed in.** One instance per broker; topic is a
   method argument, not bound at construction. Matches all three callers (the
   broker-wide producer, the per-topic subscriber, ad-hoc broker inspection)
   without a registry of per-topic instances. `full_topic` (prefix already
   applied) crosses the seam; the store never sees `prefix`.

2. **Concrete now; no `Protocol` yet.** The seam lives at the class's public
   methods. The `TimerStore` `Protocol` + an `InMemoryTimerStore` adapter belong
   to candidate 2 — *two* adapters make the seam real; one would be speculative.

3. **Seven methods, with `remove` collapsing three call paths:**

   | Method | Replaces | Effect |
   |---|---|---|
   | `schedule(full_topic, timer_id, payload, activation_ts)` | `producer.publish` | `ZADD` + `HSET` |
   | `due(full_topic, now, limit) -> list[str]` | `subscriber._get_msgs` | `ZRANGEBYSCORE` |
   | `claim(full_topic, timer_id, now, lease_ttl) -> bytes \| None` | `subscriber._claim_and_consume` | `CLAIM_LUA` |
   | `remove(full_topic, timer_id)` | `message._commit` + `producer.cancel` + orphan cleanup | `COMMIT_LUA` |
   | `pending(full_topic, before=None) -> list[str]` | `broker.get_pending_timers` | `ZRANGEBYSCORE` |
   | `is_pending(full_topic, timer_id) -> bool` | `broker.has_pending` | `ZSCORE` |
   | `cancel_all(full_topic) -> int` | `broker.cancel_all` | `ZCARD` + `UNLINK` |

   `commit`, `cancel`, and orphan cleanup all become `remove`, implemented with
   `COMMIT_LUA` — one atomic `EVALSHA` round-trip, replacing the two
   `MULTI`/`EXEC` cancel pipelines. Public intent is preserved at the call sites
   (`broker.cancel_timer`, the message's `ack`/`reject`); they all funnel to
   `store.remove`.

4. **Ids cross as `str`; the store absorbs the non-UTF-8 self-heal.** `due` and
   `pending` return `list[str]`; the store owns all bytes↔str normalization
   regardless of the client's `decode_responses` mode. A non-decodable member is
   garbage the store removes inside `due` to maintain its own invariant — the
   subscriber loses the decode + `UnicodeDecodeError` + orphan-cleanup branch
   entirely.

5. **Envelope-agnostic.** Payloads cross as opaque `bytes` (`schedule` takes
   `bytes`, `claim` returns `bytes | None`, `NEVER_DECODE` kept internal).
   Encoding stays in the producer, decoding in `TimerParser`. Two clean seams:
   `TimerStore` = Redis protocol, `TimerMessageFormat` = wire format.

6. **The delivered message removes itself via a bound thunk.**
   `TimerStreamMessage` drops its `client`/`timeline_key`/`payloads_key`/
   `timer_id` fields for a single `_remove: Callable[[], Awaitable[None]] |
   None`, built by the parser as `partial(store.remove, full_topic, timer_id)`.
   The message decouples from both Redis and the store type; its guard collapses
   to `if self._remove is None: return`.

7. **One construction site; derived-key duplication deleted.** The broker
   `__init__` builds one `TimerStore(connection, timeline_key, payloads_key)`,
   held on `TimersBrokerConfig` where `producer` lives now. The subscriber
   reaches it via `_outer_config.store`; broker inspection via
   `config.broker_config.store`. The raw `timeline_key`/`payloads_key` move off
   the config into the store. Deleted:
   `TimersSubscriberConfig.topic_timeline_key`/`.topic_payloads_key` and
   `TimersBroker._topic_timeline_key`/`._topic_payloads_key`.

8. **Clock passed in; store owns the lease math.** `due`/`claim`/`pending` take
   `now`/`before` as data (no `time.time()` inside — keeps the store a pure
   function of its inputs, which candidate 2's in-memory adapter needs for
   deterministic tests). `claim` takes `lease_ttl` and computes
   `claim_score = now + lease_ttl` internally — the lease *rule* stays hidden.

9. **Top-level `store.py` absorbs the Lua.** `CLAIM_LUA`, `COMMIT_LUA`, their
   SHAs, and `eval_cached` become module-private in `store.py`;
   `subscriber/lua.py` is **deleted**. `subscriber/` and `publisher/` end with
   zero raw Redis or Lua.

The producer survives as the FastStream-facing envelope adapter: `publish` =
encode → `store.schedule`, `cancel` = `store.remove`. It takes `store` +
`serializer`, no longer `connection`/keys.

## Scope

### In scope
- New `faststream_redis_timers/store.py` (`TimerStore` + private Lua/`eval_cached`).
- Rewire `producer.py`, `subscriber/usecase.py`, `message.py`, `parser/parser.py`,
  `broker.py`, and the config classes to the store.
- Delete `subscriber/lua.py` and the four derived-key properties/methods.
- Behavior-preserving, except the deliberate cancel-path upgrade
  (`MULTI`/`EXEC` pipeline → single-round-trip `COMMIT_LUA`).
- Promote: author `architecture/timer-store.md` in the implementing PR.

### Out of scope
- **Candidate 2** — the `TimerStore` `Protocol`, `InMemoryTimerStore`, and the
  fake-broker rewrite. This change deliberately keeps the store concrete.
- **Candidate 3** — the `PollSchedule` extraction from `_consume`.
- **Candidate 4** — the shallow publisher/subscriber factories.
- Any change to the wire format, ack policy, or public broker API.

## Detailed changes

Authored as the plan ([`plan.md`](./plan.md)) executes; the per-file shape is
fixed by the nine decisions above. Key signatures:

```python
# faststream_redis_timers/store.py
class TimerStore:
    def __init__(self, connection: ConnectionState, timeline_key: str, payloads_key: str) -> None: ...
    async def schedule(self, full_topic: str, timer_id: str, payload: bytes, activation_ts: float) -> None: ...
    async def due(self, full_topic: str, now: float, limit: int) -> list[str]: ...
    async def claim(self, full_topic: str, timer_id: str, now: float, lease_ttl: int) -> bytes | None: ...
    async def remove(self, full_topic: str, timer_id: str) -> None: ...
    async def pending(self, full_topic: str, before: float | None = None) -> list[str]: ...
    async def is_pending(self, full_topic: str, timer_id: str) -> bool: ...
    async def cancel_all(self, full_topic: str) -> int: ...
```

## Testing

- **Unit (no Redis):** key derivation and bytes→str normalization are pure
  enough to test directly; `tests/test_unit.py`.
- **Integration (Redis):** the existing `test_delivery` / `test_cancel` /
  `test_isolation` / `test_at_least_once` suites are the regression net — they
  exercise the protocol end-to-end and must pass unchanged, proving the rewire
  is behavior-preserving. The cancel suites additionally confirm the
  pipeline→Lua `remove` upgrade is transparent.
- `just lint` (ruff + `ty`) and `just test` (full suite under docker compose).

## Risks

- **Behavior drift during the rewire.** Mitigated by leaning on the untouched
  integration suites as the contract; no test is rewritten to match new code.
- **`remove` semantics vs the old cancel pipeline.** `COMMIT_LUA` removes from
  both keys unconditionally, exactly as the pipeline did; the only change is
  atomicity (one round-trip). `test_cancel` covers it.
- **`full_topic` vs `prefix`.** The store never applies `prefix`; every caller
  passes an already-composed `full_topic`. Decision 1 + 7 keep that derivation
  at the config edge — `test_isolation` (prefix/topic isolation) guards it.

## Rollout

- Implementation is a **separate** PR following [`plan.md`](./plan.md), on a
  branch like `feat/timer-store`, promoting `architecture/timer-store.md` in the
  same diff.
- Follows the project workflow: this spec → plan → subagent-driven-development
  (TDD per task) → requesting-code-review → finishing-a-development-branch.
