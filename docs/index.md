# faststream-redis-timers

Welcome to the `faststream-redis-timers` documentation!

`faststream-redis-timers` is a [FastStream](https://faststream.airt.ai) broker integration for Redis-backed distributed timer scheduling.

Schedule messages to be delivered to subscribers at a future point in time, with **at-least-once** delivery across multiple workers.

!!! tip "Already using Postgres? Prefer `faststream-outbox`"
    [`faststream-outbox`](https://github.com/modern-python/faststream-outbox) also supports
    [timers](https://faststream-outbox.readthedocs.io/en/latest/usage/timers/) and lets you schedule a timer in the
    **same SQLAlchemy transaction** as the domain write — no dual-write between your DB and Redis. Reach for
    `faststream-redis-timers` when your stack doesn't include Postgres, or when you want timer scheduling decoupled
    from your relational store.

---

- [Installation](introduction/installation.md)
- [How it works](introduction/how-it-works.md)
- [Basic usage](usage/basic.md)
- [Subscriber](usage/subscriber.md)
- [Publisher](usage/publisher.md)
- [Router](usage/router.md)
- [Testing](usage/testing.md)
