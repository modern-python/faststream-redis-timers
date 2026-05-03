import typing

from faststream.message import decode_message

from faststream_redis_timers.envelope import TimerMessageFormat
from faststream_redis_timers.message import TimerStreamMessage


if typing.TYPE_CHECKING:
    from faststream_redis_timers.message import TimerMessage
    from faststream_redis_timers.subscriber.config import TimersSubscriberConfig


class TimerParser:
    def __init__(self, config: "TimersSubscriberConfig") -> None:
        self._config = config

    async def parse_message(self, msg: "TimerMessage") -> TimerStreamMessage:
        body, headers = TimerMessageFormat.parse(msg["data"])
        timer_id = msg["timer_id"]
        return TimerStreamMessage(
            raw_message=msg,
            body=body,
            headers=headers,
            content_type=headers.get("content-type"),
            message_id=timer_id,
            correlation_id=headers.get("correlation_id", timer_id),
            reply_to=headers.get("reply_to", ""),
            client=self._config._outer_config.connection.client,  # noqa: SLF001
            timeline_key=self._config.topic_timeline_key,
            payloads_key=self._config.topic_payloads_key,
            timer_id=timer_id,
        )

    async def decode_message(self, msg: TimerStreamMessage) -> typing.Any:
        return decode_message(msg)
