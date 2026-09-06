# No per-call `middlewares=` on subscribers, publishers and routes

**Decision:** `TimersRegistrator.subscriber()`, `TimersRegistrator.publisher()`, `TimersRoute` and
`TimersRoutePublisher` take no `middlewares=` keyword. Middleware is configured at broker or router
scope only.

## Context

The package exposed a per-call `middlewares=` kwarg that forwarded to FastStream's
`add_call(middlewares_=…)`. FastStream 0.7 removed that parameter upstream, so the forwarding target
no longer exists. Migrating to 0.7 forced a choice, and the kwarg was dropped rather than preserved.
Two alternatives were weighed and both lose:

- **Keep the kwarg, route it to broker scope internally.** Semantically wrong: broker-scope
  middleware runs for every Topic, not the one the kwarg was attached to. A silent change of meaning
  is worse for a user than a hard break they see at import time.
- **Re-implement per-subscriber middleware locally.** This reproduces behaviour upstream had just
  removed, and carries the ongoing cost of tracking a framework internal we had deliberately stopped
  depending on.

The package was at version `"0"` with no stability promise when this landed, so a hard break was in
policy provided it was stated in the release.

## Decision & rationale

Follow upstream. This package is a FastStream broker integration and its value is behaving exactly
like the brokers FastStream ships; carrying a call-scoped middleware feature the framework no longer
has would make it the odd one out for every contributor and every user reading FastStream's own
documentation. `middlewares=` on `TimersBroker` and `TimersRouter` is unaffected — those are the
broker- and router-scope hooks FastStream still supports, and they remain the way to wrap timer
handling.

**Revisit trigger:** FastStream reintroduces call-scoped middleware, under any spelling. At that
point the kwarg returns as a thin forward to whatever upstream provides — never as a local
re-implementation.
