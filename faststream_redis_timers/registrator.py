import warnings
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
        max_polling_interval: float = 5.0,
        max_concurrent: int = 5,
        lease_ttl: int = 30,
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
            max_polling_interval=max_polling_interval,
            max_concurrent=max_concurrent,
            lease_ttl=lease_ttl,
            config=self.config,  # ty: ignore[invalid-argument-type]
            title_=title_,
            description_=description_,
            include_in_schema=include_in_schema,
        )
        full_topic = subscriber._config.full_topic  # noqa: SLF001
        if any(
            isinstance(s, TimersSubscriber) and s._config.full_topic == full_topic  # noqa: SLF001
            for s in self._subscribers
        ):
            warnings.warn(
                f"Duplicate subscriber registered for topic {topic!r}: pollers will compete "
                f"for the same Redis keys. Use multiple decorated handlers on a single function "
                f"or separate topics if you need isolated processing.",
                stacklevel=2,
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
