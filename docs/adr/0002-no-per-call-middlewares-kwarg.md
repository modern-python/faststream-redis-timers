# No per-call `middlewares=` on subscribers, publishers and routes

`TimersRegistrator.subscriber()`, `.publisher()`, `TimersRoute` and `TimersRoutePublisher` take no
`middlewares=` keyword; `TimersBroker` and `TimersRouter` keep theirs, and broker or router scope is
the only way to wrap timer handling. FastStream 0.7 removed `add_call(middlewares_=...)`, so the
forwarding target no longer exists. Routing the kwarg to broker scope internally would have been a
silent change of meaning, since broker middleware runs for every Topic, and re-implementing
per-subscriber middleware locally would reproduce what upstream had just deleted while binding us to
an internal we had stopped depending on. The package was at version `"0"` with no stability promise,
so a hard break users see at import time was in policy. Behaving exactly like the brokers FastStream
ships is this integration's value, which is also why the single-caller `create_publisher` and
`create_subscriber` factories stay rather than being inlined into the registrator: they mirror
FastStream's own Redis broker layout. If upstream restores call-scoped middleware the kwarg returns
as a thin forward.
