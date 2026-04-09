import typing
from dataclasses import dataclass

from faststream._internal.configs import SubscriberSpecificationConfig, SubscriberUsecaseConfig
from faststream._internal.constants import EMPTY
from faststream.middlewares import AckPolicy

from faststream_redis_timers.schemas import TimerSub


if typing.TYPE_CHECKING:
    from faststream_redis_timers.configs import TimersBrokerConfig


@dataclass(kw_only=True)
class TimersSubscriberConfig(SubscriberUsecaseConfig):
    _outer_config: "TimersBrokerConfig"
    timer_sub: TimerSub

    @property
    def full_topic(self) -> str:
        return f"{self._outer_config.prefix}{self.timer_sub.topic}"

    @property
    def topic_timeline_key(self) -> str:
        return f"{self._outer_config.timeline_key}:{self.full_topic}"

    @property
    def topic_payloads_key(self) -> str:
        return f"{self._outer_config.payloads_key}:{self.full_topic}"

    @property
    def lock_prefix(self) -> str:
        return self._outer_config.lock_prefix

    @property
    def ack_policy(self) -> AckPolicy:
        if self._ack_policy is EMPTY:
            return AckPolicy.REJECT_ON_ERROR
        return self._ack_policy  # pragma: no cover


@dataclass(kw_only=True)
class TimersSubscriberSpecificationConfig(SubscriberSpecificationConfig):
    topic: str
