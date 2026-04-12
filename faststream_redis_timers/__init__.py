from faststream_redis_timers.broker import TimersBroker
from faststream_redis_timers.router import TimersRoute, TimersRoutePublisher, TimersRouter
from faststream_redis_timers.schemas import TimerSub
from faststream_redis_timers.testing import TestTimersBroker


__all__ = [
    "TestTimersBroker",
    "TimerSub",
    "TimersBroker",
    "TimersRoute",
    "TimersRoutePublisher",
    "TimersRouter",
]

try:
    import functools
    import typing

    import faststream.asgi.factories.asyncapi.try_it_out
    from faststream._internal.broker import BrokerUsecase
    from faststream._internal.testing.broker import TestBroker

    original_get_broker_registry = faststream.asgi.factories.asyncapi.try_it_out._get_broker_registry  # noqa: SLF001

    @functools.lru_cache(maxsize=1)
    def get_broker_registry() -> dict[type[BrokerUsecase[typing.Any, typing.Any]], type[TestBroker[typing.Any]]]:
        return {**original_get_broker_registry(), TimersBroker: TestTimersBroker}

    faststream.asgi.factories.asyncapi.try_it_out._get_broker_registry = get_broker_registry  # noqa: SLF001
except Exception:  # noqa: BLE001, S110  # pragma: no cover
    pass
