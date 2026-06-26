---
status: accepted
summary: Keep publisher/subscriber create_*() factories despite their shallowness; do not inline them into the registrator (architecture-review candidate 4).
supersedes: null
superseded_by: null
---

# Keep the construction factories; don't inline them into the registrator

**Decision:** `publisher/factory.py` (`create_publisher`) and
`subscriber/factory.py` (`create_subscriber`) stay as-is. We do **not** inline
their construction into `TimersRegistrator.publisher()` / `.subscriber()`.

## Context

Architecture-review candidate 4 ("shallow construction factories") observed that
both factories are pure constructor-bundling — no validation, no branching, no
logic — and each has exactly one caller (the matching registrator method, which
already forwards nearly all the same arguments). By the deletion test they are
pass-throughs: inlining them *moves* the construction lines into the registrator
rather than *concentrating* complexity. The option weighed was to inline both and
delete the two files (a small locality win, two fewer files, one fewer hop).

## Decision & rationale

Keep them. The factories are shallow **because our domain is simple**, not because
the structure is wrong:

- FastStream's own Redis broker carries the same `publisher/factory.py` +
  `subscriber/factory.py` shape, where `create_subscriber` validates options and
  selects among ~9 subscriber types (Channel/List/Stream × Batch/Concurrent).
  This project deliberately mirrors FastStream's Redis structure. We have one
  subscriber type and one publisher type today, so there is nothing to validate
  or select — but the seam is the natural place that logic would live if it
  arrived, and keeping it preserves structural parity with the framework a
  contributor already knows.
- The inlining win is genuinely small (locality + two deleted files), and it
  buys that by *diverging* from the upstream structure. The trade isn't worth it
  while the factories cost essentially nothing to keep.

This is the opposite call from candidate 2 (which was rejected because its
premises were false): candidate 4's premise — the factories are shallow — is
*true*; we simply judge the cleanup not worth the divergence.

## Revisit trigger

A second timer subscriber or publisher type appears (e.g. batch timers, an
alternative polling strategy) — at that point the factory becomes the place that
validates/selects and starts to earn its keep, so revisit nothing (it's already
right). Conversely, if structural parity with FastStream stops being a goal and
the factories are still single-type, reconsider inlining them then.
