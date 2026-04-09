from collections.abc import Iterable, Sequence
from typing import Any, override

from fast_depends.dependencies import Dependant
from faststream._internal.broker.registrator import Registrator
from faststream._internal.types import CustomCallable, PublisherMiddleware, SubscriberMiddleware

from faststream_redis_timers.message import TimerMessage
from faststream_redis_timers.publisher.factory import create_publisher
from faststream_redis_timers.publisher.usecase import TimersPublisher
from faststream_redis_timers.subscriber.factory import create_subscriber
from faststream_redis_timers.subscriber.usecase import TimersSubscriber


class TimersRegistrator(Registrator[TimerMessage, "TimersBrokerConfig"]):  # ty: ignore[unresolved-reference]
    @override
    def subscriber(  # ty: ignore[invalid-method-override]
        self,
        topic: str,
        *,
        polling_interval: float = 0.05,
        max_concurrent: int = 5,
        lock_ttl: int = 30,
        dependencies: Iterable[Dependant] = (),
        parser: CustomCallable | None = None,
        decoder: CustomCallable | None = None,
        middlewares: Sequence[SubscriberMiddleware[TimerMessage]] = (),
        title_: str | None = None,
        description_: str | None = None,
        include_in_schema: bool = True,
    ) -> TimersSubscriber:
        subscriber = create_subscriber(
            topic=topic,
            polling_interval=polling_interval,
            max_concurrent=max_concurrent,
            lock_ttl=lock_ttl,
            config=self.config,  # ty: ignore[invalid-argument-type]
            title_=title_,
            description_=description_,
            include_in_schema=include_in_schema,
        )
        super().subscriber(subscriber)
        return subscriber.add_call(
            parser_=parser or self._parser,
            decoder_=decoder or self._decoder,
            dependencies_=dependencies,
            middlewares_=middlewares,
        )

    @override
    def publisher(  # ty: ignore[invalid-method-override]
        self,
        topic: str,
        *,
        middlewares: Sequence[PublisherMiddleware] = (),
        schema_: Any | None = None,
        title_: str | None = None,
        description_: str | None = None,
        include_in_schema: bool = True,
    ) -> TimersPublisher:
        publisher = create_publisher(
            topic=topic,
            config=self.config,  # ty: ignore[invalid-argument-type]
            middlewares=middlewares,
            title_=title_,
            description_=description_,
            schema_=schema_,
            include_in_schema=include_in_schema,
        )
        super().publisher(publisher)
        return publisher
