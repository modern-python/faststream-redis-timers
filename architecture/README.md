# Architecture

The living truth about what `faststream-redis-timers` does **now** — one file
per capability, updated by hand whenever a change ships. The *why* and *how it
got here* live in [`../planning/changes/`](../planning/changes/), and decisions
deliberately taken (including options rejected) in
[`../planning/decisions/`](../planning/decisions/); this directory is the present.

These files carry **no frontmatter** — they are prose, dated by git.

## Capabilities

Capability files (`architecture/<capability>.md`) are authored over time as the
system's behavior is documented.

- [`timer-store.md`](timer-store.md) — the `TimerStore`: the single module that
  owns the Redis timer protocol (timeline sorted-set, payloads hash, Lua claim/
  remove) and topic-key derivation across every topic.

## Promotion rule

Shipping a change hand-edits the affected capability file(s) here to match the
new reality, in the same PR as the code. When a change alters a capability's
behavior, update the matching `architecture/<capability>.md` in the same PR. The
change bundle stays in place under
[`../planning/changes/`](../planning/changes/) — no folder move.
