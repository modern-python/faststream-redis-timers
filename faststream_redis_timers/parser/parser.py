import logging
import typing
from functools import partial

import anyio
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
        timer_id = msg["timer_id"]
        discard_corrupt = None
        try:
            body, headers = TimerMessageFormat.parse(msg["data"])
        except ValueError as e:
            body, headers = msg["data"], {}
            discard_corrupt = partial(self._discard_corrupt, msg, e)
        return TimerStreamMessage(
            raw_message=msg,
            body=body,
            headers=headers,
            content_type=headers.get("content-type"),
            message_id=timer_id,
            correlation_id=headers.get("correlation_id", timer_id),
            reply_to=headers.get("reply_to", ""),
            _remove=partial(self._remove, timer_id),
            _discard_corrupt=discard_corrupt,
        )

    async def _remove(self, timer_id: str) -> None:
        store = self._config._outer_config.store  # noqa: SLF001
        with anyio.fail_after(self._config.timer_sub.effective_command_timeout):
            await store.remove(self._config.full_topic, timer_id)

    async def _discard_corrupt(self, msg: "TimerMessage", error: ValueError) -> typing.NoReturn:
        outer_config = self._config._outer_config  # noqa: SLF001
        await self._remove(msg["timer_id"])
        outer_config.logger.log(
            f"Timer {msg['timer_id']!r} on {self._config.full_topic!r} removed: "
            f"its {len(msg['data'])}-byte payload cannot be parsed",
            logging.ERROR,
            exc_info=error,
        )
        raise error

    async def decode_message(self, msg: TimerStreamMessage) -> typing.Any:
        return decode_message(msg)
