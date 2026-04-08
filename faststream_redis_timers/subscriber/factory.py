import typing

from faststream._internal.endpoint.subscriber.call_item import CallsCollection

from faststream_redis_timers.schemas import TimerSub
from faststream_redis_timers.subscriber.config import TimersSubscriberConfig, TimersSubscriberSpecificationConfig
from faststream_redis_timers.subscriber.usecase import TimersSubscriber, TimersSubscriberSpecification


if typing.TYPE_CHECKING:
    from faststream_redis_timers.configs import TimersBrokerConfig


def create_subscriber(  # noqa: PLR0913
    *,
    topic: str,
    polling_interval: float = 0.05,
    max_concurrent: int = 5,
    lock_ttl: int = 30,
    config: "TimersBrokerConfig",
    title_: str | None = None,
    description_: str | None = None,
    include_in_schema: bool = True,
) -> TimersSubscriber:
    timer_sub = TimerSub(
        topic=topic,
        polling_interval=polling_interval,
        max_concurrent=max_concurrent,
        lock_ttl=lock_ttl,
    )
    usecase_config = TimersSubscriberConfig(
        _outer_config=config,
        timer_sub=timer_sub,
        timeline_key=config.timeline_key,
        payloads_key=config.payloads_key,
        lock_prefix=config.lock_prefix,
    )
    specification_config = TimersSubscriberSpecificationConfig(
        topic=topic,
        title_=title_,
        description_=description_,
        include_in_schema=include_in_schema,
    )
    calls: CallsCollection[typing.Any] = CallsCollection()
    specification = TimersSubscriberSpecification(
        _outer_config=config,
        specification_config=specification_config,
        calls=calls,
    )
    return TimersSubscriber(
        config=usecase_config,
        specification=specification,
        calls=calls,
    )
