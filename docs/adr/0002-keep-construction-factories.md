# Keep the construction factories; don't inline them into the registrator

**Decision:** `publisher/factory.py` (`create_publisher`) and `subscriber/factory.py`
(`create_subscriber`) stay as-is. We do **not** inline their construction into
`TimersRegistrator.publisher()` / `.subscriber()`.

## Context

An architecture review observed that both factories are pure constructor-bundling — no validation,
no branching, no logic — and each has exactly one caller (the matching registrator method, which
already forwards nearly all the same arguments). By the deletion test they are pass-throughs:
inlining them *moves* the construction lines into the registrator rather than *concentrating*
complexity. The option weighed was to inline both and delete the two files: a small locality win,
two fewer files, one fewer hop.

## Decision & rationale

Keep them. The factories are shallow **because our domain is simple**, not because the structure is
wrong:

- FastStream's own Redis broker carries the same `publisher/factory.py` + `subscriber/factory.py`
  shape, where `create_subscriber` validates options and selects among roughly nine subscriber types
  (Channel / List / Stream × Batch / Concurrent). This project deliberately mirrors FastStream's
  Redis structure. We have one subscriber type and one publisher type today, so there is nothing to
  validate or select — but the seam is the natural place that logic would live if it arrived, and
  keeping it preserves structural parity with the framework a contributor already knows.
- The inlining win is genuinely small (locality plus two deleted files), and it buys that by
  *diverging* from the upstream structure. The trade isn't worth it while the factories cost
  essentially nothing to keep.

This is the opposite call from the fake-broker proposal in
[ADR-0001](0001-fake-broker-keeps-immediate-delivery.md), which was rejected because its premises
were false. Here the premise — the factories are shallow — is *true*; we simply judge the cleanup
not worth the divergence.

**Revisit trigger:** structural parity with FastStream stops being a goal while the factories are
still single-type — then inlining them is worth reconsidering. A second timer subscriber or
publisher type (batch timers, an alternative polling strategy) is *not* a revisit trigger in the
other direction: at that point the factory starts validating and selecting, and this decision is
simply confirmed.
