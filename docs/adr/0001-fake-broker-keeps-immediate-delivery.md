# The fake broker delivers every Timer immediately

`FakeTimersProducer` encodes each published Timer and hands it straight to the matching subscriber's
`process_message`, ignoring the Activation time, and `_patch_broker` stubs the Redis client so
`has_pending` is False, `get_pending_timers` empty and `cancel_all` zero. Putting a real in-memory
store behind the `TimerStore` seam, so the fake exercised Claim, Lease and Commit, was rejected:
FastStream fakes every subscriber, its polling list subscriber included, by bypassing the poll loop,
and under immediate delivery a published Timer has already fired, so those inspection results are
truthful rather than canned. Driving the real `_consume` loop under `TestBroker` means skipping
`_fake_start` and running a 50 ms poll loop inside a unit test; a spike doing so hung at teardown.
Reporting a future Timer as Pending requires withholding it, which breaks every user test that
publishes one and expects its handler to fire, so it could only arrive as an opt-in flag.
