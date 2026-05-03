from collections.abc import Awaitable, Callable, Iterable, Sequence
from typing import Any

from fast_depends.dependencies import Dependant
from faststream._internal.basic_types import SendableMessage
from faststream._internal.broker.router import ArgsContainer, BrokerRouter, SubscriberRoute
from faststream._internal.configs import BrokerConfig
from faststream._internal.types import BrokerMiddleware, CustomCallable, PublisherMiddleware, SubscriberMiddleware

from faststream_redis_timers.message import TimerMessage
from faststream_redis_timers.registrator import TimersRegistrator


class TimersRoutePublisher(ArgsContainer):
    """Delayed TimersPublisher registration object."""

    def __init__(  # noqa: PLR0913
        self,
        topic: str,
        *,
        middlewares: Sequence[PublisherMiddleware] = (),
        schema_: Any | None = None,
        title_: str | None = None,
        description_: str | None = None,
        include_in_schema: bool = True,
    ) -> None:
        super().__init__(
            topic=topic,
            middlewares=middlewares,
            schema_=schema_,
            title_=title_,
            description_=description_,
            include_in_schema=include_in_schema,
        )


class TimersRoute(SubscriberRoute):
    """Class to store delayed TimersBroker subscriber registration."""

    def __init__(  # noqa: PLR0913
        self,
        call: Callable[..., SendableMessage] | Callable[..., Awaitable[SendableMessage]],
        topic: str,
        *,
        polling_interval: float = 0.05,
        max_concurrent: int = 5,
        lease_ttl: int = 30,
        publishers: Iterable[TimersRoutePublisher] = (),
        dependencies: Iterable[Dependant] = (),
        parser: CustomCallable | None = None,
        decoder: CustomCallable | None = None,
        middlewares: Sequence[SubscriberMiddleware[TimerMessage]] = (),
        title_: str | None = None,
        description_: str | None = None,
        include_in_schema: bool = True,
    ) -> None:
        super().__init__(
            call=call,
            topic=topic,
            polling_interval=polling_interval,
            max_concurrent=max_concurrent,
            lease_ttl=lease_ttl,
            publishers=publishers,
            dependencies=dependencies,
            parser=parser,
            decoder=decoder,
            middlewares=middlewares,
            title_=title_,
            description_=description_,
            include_in_schema=include_in_schema,
        )


class TimersRouter(TimersRegistrator, BrokerRouter[TimerMessage, BrokerConfig]):
    """Includable to TimersBroker router."""

    def __init__(  # noqa: PLR0913
        self,
        prefix: str = "",
        handlers: Iterable[TimersRoute] = (),
        *,
        dependencies: Iterable[Dependant] = (),
        middlewares: Sequence[BrokerMiddleware[TimerMessage]] = (),
        parser: CustomCallable | None = None,
        decoder: CustomCallable | None = None,
        include_in_schema: bool | None = None,
        routers: Sequence[TimersRegistrator] = (),
    ) -> None:
        super().__init__(
            config=BrokerConfig(
                broker_middlewares=middlewares,
                broker_dependencies=dependencies,
                broker_parser=parser,
                broker_decoder=decoder,
                include_in_schema=include_in_schema,
                prefix=prefix,
            ),
            handlers=handlers,  # ty: ignore[unknown-argument]
            routers=routers,
        )
