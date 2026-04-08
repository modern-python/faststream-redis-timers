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
    _outer_config: "TimersBrokerConfig"  # type: ignore[assignment]
    timer_sub: TimerSub
    timeline_key: str = "timers_timeline"
    payloads_key: str = "timers_payloads"
    lock_prefix: str = "timers_lock:"

    @property
    def full_topic(self) -> str:
        return f"{self._outer_config.prefix}{self.timer_sub.topic}"

    @property
    def topic_timeline_key(self) -> str:
        return f"{self.timeline_key}:{self.full_topic}"

    @property
    def topic_payloads_key(self) -> str:
        return f"{self.payloads_key}:{self.full_topic}"

    @property
    def ack_policy(self) -> AckPolicy:
        if self._ack_policy is EMPTY:
            return AckPolicy.NACK_ON_ERROR
        return self._ack_policy  # type: ignore[return-value]  # pragma: no cover


@dataclass(kw_only=True)
class TimersSubscriberSpecificationConfig(SubscriberSpecificationConfig):
    topic: str
