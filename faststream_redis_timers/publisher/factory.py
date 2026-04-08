import typing
from collections.abc import Sequence

from faststream_redis_timers.publisher.config import TimersPublisherConfig, TimersPublisherSpecificationConfig
from faststream_redis_timers.publisher.usecase import TimersPublisher, TimersPublisherSpecification


if typing.TYPE_CHECKING:
    from faststream._internal.types import PublisherMiddleware

    from faststream_redis_timers.configs import TimersBrokerConfig


def create_publisher(  # noqa: PLR0913
    *,
    topic: str,
    config: "TimersBrokerConfig",
    middlewares: Sequence["PublisherMiddleware"] = (),
    title_: str | None = None,
    description_: str | None = None,
    schema_: typing.Any | None = None,
    include_in_schema: bool = True,
) -> TimersPublisher:
    usecase_config = TimersPublisherConfig(
        _outer_config=config,
        topic=topic,
        middlewares=middlewares,
    )
    specification_config = TimersPublisherSpecificationConfig(
        topic=topic,
        title_=title_,
        description_=description_,
        schema_=schema_,
        include_in_schema=include_in_schema,
    )
    specification = TimersPublisherSpecification(
        _outer_config=config,
        specification_config=specification_config,
    )
    return TimersPublisher(config=usecase_config, specification=specification)
