# Wire format

How a Timer's message becomes bytes for storage and bytes back into a handler
argument. The bytes are stored as the opaque payload in the
[TimerStore](timer-store.md); this page is the envelope around them.

## The envelope

`TimerMessageFormat` extends FastStream's `BinaryMessageFormatV1` — the same
binary envelope FastStream's Redis broker uses, so a timer payload is wire-
compatible with the rest of the ecosystem. It packs the message body together
with its headers: `content-type` (which drives decoding), `correlation_id`, and
`reply_to`.

## The round trip

- **Schedule** ([scheduling](scheduling.md)): the producer encodes the message
  once at publish time — body + headers → envelope bytes — and hands those bytes
  to the store. Encoding happens exactly once, not per delivery attempt.
- **Store**: the envelope bytes are an **opaque payload**. The store and Redis
  never interpret them; the claim Lua returns them verbatim (forced binary, so a
  `decode_responses=True` client can't corrupt the bytes). The store layer is
  deliberately envelope-agnostic.
- **Deliver** ([delivery](delivery.md)): the parser reads the envelope back into
  `(body, headers)`, then decodes the body by its `content-type` into the
  argument the handler receives. `correlation_id` defaults to the `timer_id` when
  the envelope doesn't carry one.

## Backward compatibility

Versions before the binary format wrote a different envelope: a JSON object of
hex-encoded body, `{"b": "<hex>", "ct": "<content-type>"}`. Timers persisted by
those versions can still be sitting in Redis when a process upgrades, so the
**read** path detects that shape (a payload beginning with `{`) and decodes it,
while the **write** path only ever emits the current binary envelope. The effect
is a one-way migration on read: old timers keep firing after an upgrade, and once
re-scheduled they move to the current format. No migration step is required.
