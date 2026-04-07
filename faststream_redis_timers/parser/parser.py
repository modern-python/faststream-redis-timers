import json
from typing import TYPE_CHECKING, Any

from faststream.message import decode_message

from faststream_redis_timers.message import TIMER_SEPARATOR, TimerStreamMessage


if TYPE_CHECKING:
    from faststream_redis_timers.message import TimerMessage
    from faststream_redis_timers.subscriber.config import TimersSubscriberConfig


class TimerParser:
    def __init__(self, config: "TimersSubscriberConfig") -> None:
        self._config = config

    async def parse_message(self, msg: "TimerMessage") -> TimerStreamMessage:
        timer_key = f"{msg['channel']}{TIMER_SEPARATOR}{msg['timer_id']}"
        raw_data = msg["data"]
        try:
            envelope = json.loads(raw_data)
            body = bytes.fromhex(envelope["b"])
            content_type: str | None = envelope.get("ct")
        except (json.JSONDecodeError, KeyError, ValueError):
            # Fallback: treat raw bytes as-is with no content_type
            body = raw_data if isinstance(raw_data, bytes) else raw_data.encode()
            content_type = None
        return TimerStreamMessage(
            raw_message=msg,
            body=body,
            headers={},
            content_type=content_type,
            message_id=msg["timer_id"],
            correlation_id=msg["timer_id"],
            _redis_client=self._config._outer_config.connection.client,  # noqa: SLF001
            _timer_key=timer_key,
            _timeline_key=self._config.timeline_key,
            _payloads_key=self._config.payloads_key,
        )

    async def decode_message(self, msg: TimerStreamMessage) -> Any:
        return decode_message(msg)
