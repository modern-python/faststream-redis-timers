---
summary: Adopt upstream FastStream 0.7.1 TestBroker typing fix; drop the TestTimersBroker __aenter__ workaround and align generics.
---

# FastStream 0.7.1 TestBroker typing alignment — design

## Goal

Adopt the upstream `TestBroker` typing fix shipped in FastStream 0.7.1
(ag2ai/faststream#2903) by deleting our `TestTimersBroker.__aenter__`
workaround and aligning our generics with upstream's new
`TestBroker[Broker, EnterType]` shape.

## Background

In FastStream 0.7.0, `TestBroker.__aenter__` was annotated
`Broker | list[Broker]`. That union made the natural usage shape fail
mypy:

```python
async with TestKafkaBroker(KafkaBroker()) as br:
    await br.publish(None, "test")
    # error: Item "list[KafkaBroker]" of "KafkaBroker | list[KafkaBroker]"
    #        has no attribute "publish"  [union-attr]
```

We worked around this in [`faststream_redis_timers/testing.py`][testing-py]
by overriding `__aenter__` in `TestTimersBroker` to return `TimersBroker`
directly, plus a defensive `assert not isinstance(result, list)` to satisfy
the type checker on the unreachable branch (our `__init__` accepts only a
single broker, so the multi-broker arm cannot fire).

FastStream 0.7.1 (PR ag2ai/faststream#2903) fixes the root cause:

1. `TestBroker` becomes `Generic[Broker, EnterType]`. `EnterType` uses
   `typing_extensions.TypeVar` with `default=Any` for backward compatibility.
2. `__aenter__` returns `EnterType` instead of `Broker | list[Broker]`.
3. Each concrete subclass adds two `@overload`s on `__init__` that bind
   `EnterType` to either `SomeBroker` (single) or `tuple[SomeBroker, ...]`
   (multi). **Note the multi case now returns a `tuple`, not a `list`.**
4. The ASGI registry annotation in `try_it_out.py` becomes
   `TestBroker[Any, Any]`.
5. The AST-inspection helper in `_internal/testing/ast.py` learns to walk
   past *any* number of `__init__` frames, so subclasses (like ours) that
   add their own `__init__` continue to work.

Because `EnterType` defaults to `Any`, our existing `TestBroker[TimersBroker]`
annotation still type-checks under 0.7.1 — but the workaround we wrote is
no longer needed. The right move is to bind `EnterType = TimersBroker`
and delete the override.

[testing-py]: ../../faststream_redis_timers/testing.py

## Scope

### In scope
- Drop the `__aenter__` override (and its `isinstance(list)` assert) in
  `faststream_redis_timers/testing.py`.
- Rebind the class generic: `TestBroker[TimersBroker]` →
  `TestBroker[TimersBroker, TimersBroker]`.
- Update the ASGI registry hook annotation in
  `faststream_redis_timers/__init__.py` to `TestBroker[typing.Any, typing.Any]`
  to match upstream's new registry signature.
- Bump the FastStream pin in `pyproject.toml`:
  `faststream>=0.7,<0.8` → `faststream>=0.7.1,<0.8`.
- Add one regression test ensuring `__aenter__` yields a single
  `TimersBroker` (not a list or tuple).

### Out of scope
- Multi-broker `TestTimersBroker` support (current `__init__` accepts a
  single broker; we have no use case for multi).
- Any behavioral or runtime change.
- Refactors elsewhere in the package.

## Detailed changes

### `faststream_redis_timers/testing.py`

Current (lines 34–45):

```python
class TestTimersBroker(TestBroker[TimersBroker]):
    scheduled_timers: list[ScheduledTimer]

    def __init__(self, broker: TimersBroker, **kwargs: typing.Any) -> None:
        super().__init__(broker, **kwargs)
        self.scheduled_timers = []

    async def __aenter__(self) -> TimersBroker:
        # __init__ enforces a single broker, so upstream's multi-broker list branch is unreachable.
        result = await super().__aenter__()
        assert not isinstance(result, list)  # noqa: S101
        return result
```

After:

```python
class TestTimersBroker(TestBroker[TimersBroker, TimersBroker]):
    scheduled_timers: list[ScheduledTimer]

    def __init__(self, broker: TimersBroker, **kwargs: typing.Any) -> None:
        super().__init__(broker, **kwargs)
        self.scheduled_timers = []
```

The base `__aenter__` now returns `EnterType`, which we bind to
`TimersBroker`, so the override and its assert serve no purpose.

### `faststream_redis_timers/__init__.py`

Current (line 28):

```python
def get_broker_registry() -> dict[type[BrokerUsecase[typing.Any, typing.Any]], type[TestBroker[typing.Any]]]:
```

After:

```python
def get_broker_registry() -> dict[type[BrokerUsecase[typing.Any, typing.Any]], type[TestBroker[typing.Any, typing.Any]]]:
```

Matches upstream's new `try_it_out._get_broker_registry` signature.

### `pyproject.toml`

Current (line 12): `"faststream>=0.7,<0.8",`
After:           `"faststream>=0.7.1,<0.8",`

### `tests/test_fake.py` — new regression test

Appended to `tests/test_fake.py` (not `tests/test_unit.py`): the test enters
the `TestTimersBroker` context manager, which is the established `test_fake.py`
pattern. `test_unit.py` is reserved for pure unit tests per `CLAUDE.md`.

```python
async def test_test_broker_aenter_returns_single_timers_broker() -> None:
    """0.7.1's EnterType binding means TestTimersBroker yields a single TimersBroker, not a list/tuple.

    Guards the contract through the upstream typing refactor: even if the base
    class signature changes again, our single-broker subclass must always hand
    back a single broker instance.
    """
    broker = TimersBroker()
    async with TestTimersBroker(broker) as tb:
        assert isinstance(tb, TimersBroker)
```

The single `isinstance(tb, TimersBroker)` assertion is sufficient: since
`TimersBroker` is not a `list` or `tuple` subclass, the redundant
`assert not isinstance(tb, (list, tuple))` originally proposed adds no
additional safety. The docstring covers the intent.

## Validation

Run in order:

1. `just install` — pull in `faststream==0.7.1`.
2. `just lint` — confirm ruff/format are clean after deletions.
3. `just test` — full suite. Of particular interest:
   - `tests/test_fake.py` — every test uses `async with TestTimersBroker(broker)`.
     If the base `__aenter__` is wired correctly through `EnterType`, these
     run unchanged. If not, `tb.publish(...)` on line 17 will fail.
   - The new regression test from `tests/test_fake.py`.
   - `tests/test_unit.py::test_create_publisher_fake_subscriber_is_instance_method`
     — independent existing guard, should still pass.
4. Type check (`ty check faststream_redis_timers/ tests/`) — the project
   uses `ty` per CLAUDE.md.

## Risks

- **Upstream AST helper walking past our `__init__` frame.** PR #2903
  explicitly handles arbitrary `__init__` depth via a `while … name ==
  "__init__"` walk in `_internal/testing/ast.py`. No action needed.
- **Fake-broker test path without Redis.** The new regression test runs
  the same `__aenter__` path that the existing `test_fake.py` suite
  exercises, so it does not introduce a new dependency.
- **Pinning out 0.7.0 consumers.** The previous release already required
  `>=0.7`; bumping to `>=0.7.1` is a trivial floor increment. No
  migration note needed.

## Rollout

- Single PR on branch `faststream-0.7.1-testbroker-typing`.
- Bundled commit (the pin bump and the workaround removal are tightly
  coupled — the removal is only safe once we require 0.7.1+).
- Follows the project workflow in `CLAUDE.md`:
  brainstorming → spec → writing-plans → plan →
  executing-plans / subagent-driven-development →
  requesting-code-review → finishing-a-development-branch.
