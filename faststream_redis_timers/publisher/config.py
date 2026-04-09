import typing
from dataclasses import dataclass

from faststream._internal.configs import PublisherSpecificationConfig, PublisherUsecaseConfig


if typing.TYPE_CHECKING:
    from faststream_redis_timers.configs import TimersBrokerConfig


@dataclass(kw_only=True)
class TimersPublisherConfig(PublisherUsecaseConfig):
    _outer_config: "TimersBrokerConfig"
    topic: str

    @property
    def full_topic(self) -> str:
        return f"{self._outer_config.prefix}{self.topic}"


@dataclass(kw_only=True)
class TimersPublisherSpecificationConfig(PublisherSpecificationConfig):
    topic: str
