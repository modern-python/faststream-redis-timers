# Timer store — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract a deep `TimerStore` that owns the Redis timer protocol behind
one interface, rewiring the producer, subscriber, message, and broker to it and
deleting `subscriber/lua.py` plus the duplicated key derivation — without
changing observable behavior (except the cancel-path pipeline→Lua upgrade).

**Architecture:** One concrete broker-wide `TimerStore` in
`faststream_redis_timers/store.py` (seven methods; `full_topic` and clock passed
in; payloads opaque `bytes`; ids out as `str`; lease math and Lua internal).
Constructed once on `TimersBrokerConfig`, reached by every caller. See the spec
([`design.md`](./design.md)) for the nine decisions.

**Tech Stack:** Python 3.13, FastStream 0.7.x, `redis.asyncio`, `uv`, `ruff`,
`ty`, `pytest` (Redis-backed suites under docker compose).

**Spec:** [`design.md`](./design.md)

**Branch:** `feat/timer-store`

**Commit strategy:** Per-task commits. The rewire is behavior-preserving, so the
existing integration suites (`test_delivery`/`test_cancel`/`test_isolation`/
`test_at_least_once`) are the regression net at every step — keep them green
task-by-task, never edit them to match new code.

---

### Task 1: Create `store.py` with `TimerStore` (absorb the Lua)

**Files:**
- Create: `faststream_redis_timers/store.py`
- Reference (not yet deleted): `faststream_redis_timers/subscriber/lua.py`

Stand up the deep module with all seven methods and the private Lua/`eval_cached`
moved in. Nothing wired to it yet.

- [ ] **Step 1 (RED): Unit-test the pure surface**

  In `tests/test_unit.py`, add tests for the parts that need no Redis: key
  derivation (`{timeline_key}:{full_topic}` / `{payloads_key}:{full_topic}`) and
  bytes→str normalization of ids. Assert against a `TimerStore` built with a
  dummy `ConnectionState`. Run — expect failure (module absent).

- [ ] **Step 2 (GREEN): Write `TimerStore`**

  Implement the seven methods from the spec. Move `CLAIM_LUA`, `COMMIT_LUA`,
  their SHAs, and `eval_cached` in as module-private (`_CLAIM_LUA`, `_eval_cached`,
  …). `claim` computes `claim_score = now + lease_ttl`. `due`/`pending` return
  `list[str]`, normalizing bytes and self-healing non-UTF-8 members via an
  internal `remove`. `remove` uses `COMMIT_LUA`. Keep `NEVER_DECODE` internal.

- [ ] **Step 3: Run the new unit tests**

  `uv run pytest tests/test_unit.py -v` → pass.

- [ ] **Step 4: Commit**

  ```bash
  git add faststream_redis_timers/store.py tests/test_unit.py
  git commit -m "feat: add TimerStore owning the Redis timer protocol"
  ```

---

### Task 2: Construct the store; rewire the producer

**Files:**
- Modify: `faststream_redis_timers/configs.py`, `faststream_redis_timers/broker.py`,
  `faststream_redis_timers/publisher/producer.py`,
  `faststream_redis_timers/publisher/factory.py` (if it threads keys)

- [ ] **Step 1: Hold the store on `TimersBrokerConfig`**

  Add a `store: TimerStore` field; remove the now-unused raw key fields once
  Task 5 lands (keep them this task if the subscriber/broker still read them).
  Build one `TimerStore(connection, timeline_key, payloads_key)` in
  `broker.py.__init__` beside the producer.

- [ ] **Step 2: Shrink the producer to the envelope adapter**

  `publish` = encode → `store.schedule(full_topic, timer_id, payload, activation_ts)`;
  `cancel` = `store.remove(full_topic, timer_id)`. Constructor takes `store` +
  `serializer`, not `connection`/keys.

- [ ] **Step 3: Lean on the integration net**

  `just test` (or at minimum `test_delivery` + `test_cancel`) → green.

- [ ] **Step 4: Commit** (`feat: route the producer through TimerStore`)

---

### Task 3: Rewire the subscriber poll/claim loop

**Files:**
- Modify: `faststream_redis_timers/subscriber/usecase.py`

- [ ] **Step 1: Replace `_get_msgs` Redis calls**

  `due = await store.due(full_topic, now, free)` → `list[str]`. Delete the
  `isinstance(bytes)` decode, the `UnicodeDecodeError` branch, and the orphan
  `ZREM`+`HDEL` (the store self-heals now). `_claim_and_consume` calls
  `store.claim(full_topic, timer_id, now, lease_ttl)`; drop the inline
  `claim_score`/`eval_cached`/`CLAIM_LUA` import.

- [ ] **Step 2: Integration net**

  `just test` → green (delivery + at-least-once exercise this path).

- [ ] **Step 3: Commit** (`refactor: drive the subscriber loop through TimerStore`)

---

### Task 4: Rewire the delivered message + parser

**Files:**
- Modify: `faststream_redis_timers/message.py`, `faststream_redis_timers/parser/parser.py`

- [ ] **Step 1: Bound-thunk removal**

  `TimerStreamMessage` drops `client`/`timeline_key`/`payloads_key`/`timer_id`
  for `_remove: Callable[[], Awaitable[None]] | None`; `_commit` becomes
  `if self._remove is None: return` else `await self._remove()`. Drop the
  `subscriber/lua` import.

- [ ] **Step 2: Parser builds the thunk**

  `TimerParser` constructs `TimerStreamMessage(_remove=partial(store.remove,
  full_topic, timer_id), ...)`, reaching the store via the subscriber config.

- [ ] **Step 3: Integration net** — `just test` (cancel/at-least-once cover
  ack/reject/nack) → green.

- [ ] **Step 4: Commit** (`refactor: message removes itself via a store thunk`)

---

### Task 5: Rewire broker inspection; delete the derived-key duplication

**Files:**
- Modify: `faststream_redis_timers/broker.py`,
  `faststream_redis_timers/subscriber/config.py`,
  `faststream_redis_timers/configs.py`

- [ ] **Step 1: Inspection through the store**

  `has_pending` → `store.is_pending`; `get_pending_timers` → `store.pending`;
  `cancel_all` → `store.cancel_all`. Delete `TimersBroker._topic_timeline_key`/
  `._topic_payloads_key` and `TimersSubscriberConfig.topic_timeline_key`/
  `.topic_payloads_key`. Move the raw keys off `TimersBrokerConfig` into the store.

- [ ] **Step 2: Integration net** — `just test` (`test_isolation`,
  `test_inspection`) → green.

- [ ] **Step 3: Commit** (`refactor: broker inspection + key derivation own-by TimerStore`)

---

### Task 6: Delete `subscriber/lua.py`

**Files:**
- Delete: `faststream_redis_timers/subscriber/lua.py`

- [ ] **Step 1: Confirm no importers remain**

  `git grep -n "subscriber.lua\|subscriber/lua\|CLAIM_LUA\|COMMIT_LUA\|eval_cached" faststream_redis_timers/`
  → only `store.py` (its private copies). Delete the file.

- [ ] **Step 2: Full suite + lint** — `just test`, `just lint` → green.

- [ ] **Step 3: Commit** (`chore: drop subscriber/lua.py (folded into store.py)`)

---

### Task 7: Promote — author the capability page

**Files:**
- Create: `architecture/timer-store.md`

- [ ] **Step 1: Write the capability page**

  Living prose (no frontmatter) describing the timer-store capability as it now
  is: the seven operations, the lease/at-least-once semantics, the key scheme,
  the self-heal. Use the glossary terms (Schedule, Due, Claim, Lease, Commit,
  Cancel, Pending). Cross-reference `architecture/glossary.md`.

- [ ] **Step 2: Finalize the bundle summary**

  Edit this bundle's `design.md` `summary:` to the realized result.

- [ ] **Step 3: Commit** (`docs: promote timer-store capability to architecture/`)

---

### Task 8: Final validation

- [ ] **Step 1: `just lint`** — ruff + `ty` clean (`ty: ignore`, never `type: ignore`).
- [ ] **Step 2: `just test`** — full suite under docker compose, all green.
- [ ] **Step 3: `just check-planning`** — `planning: OK`.
- [ ] **Step 4: Review the diff** — `subscriber/`/`publisher/` contain no raw
  Redis or Lua; key derivation appears once (in `store.py`).
- [ ] **Step 5: Open the PR** per `CLAUDE.md` (push, open, watch CI).

---

## Validation summary (post-implementation)

- `faststream_redis_timers/store.py` exists; owns all `ZADD`/`HSET`/
  `ZRANGEBYSCORE`/`ZSCORE`/`ZCARD`/`UNLINK`/`CLAIM_LUA`/`COMMIT_LUA`.
- `subscriber/lua.py` is gone; no raw Redis in `subscriber/`/`publisher/`.
- `commit`/`cancel`/orphan all route through `store.remove` (one Lua round-trip).
- Derived keys (`topic_*_key`, `_topic_*_key`) are deleted; derivation lives
  once in the store.
- All existing integration suites pass unedited; `architecture/timer-store.md`
  is authored.

## Risks & mitigations

- **Behavior drift.** The integration suites are the contract and stay unedited;
  any red is a real regression, not a test to "fix."
- **`store` reachability via `_outer_config` after router inclusion.** The store
  sits on `TimersBrokerConfig` exactly like `connection`/`producer` do today, so
  it resolves through the same merge — `test_isolation` (multi-broker) guards it.
- **Docker required for `just test`.** If unavailable, run
  `uv run pytest tests/test_unit.py tests/test_fake.py` as a partial check and
  note in the PR that the Redis suites were not run locally.
