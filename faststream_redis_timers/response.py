from datetime import timedelta
from typing import Any

from faststream.response.publish_type import PublishType
from faststream.response.response import BatchPublishCommand, PublishCommand


class TimerPublishCommand(BatchPublishCommand):
    def __init__(  # noqa: PLR0913
        self,
        message: Any,
        /,
        *messages: Any,
        _publish_type: PublishType,
        timer_id: str = "",
        activate_in: timedelta = timedelta(0),
        correlation_id: str | None = None,
        destination: str = "",
        headers: dict[str, Any] | None = None,
        reply_to: str = "",
    ) -> None:
        super().__init__(
            message,
            *messages,
            _publish_type=_publish_type,
            correlation_id=correlation_id,
            destination=destination,
            headers=headers,
            reply_to=reply_to,
        )
        self.timer_id = timer_id
        self.activate_in = activate_in

    @classmethod
    def from_cmd(
        cls,
        cmd: "PublishCommand",
        *,
        timer_id: str = "",
        activate_in: timedelta = timedelta(0),
        batch: bool = False,
    ) -> "TimerPublishCommand":
        body, extra_bodies = cls._parse_bodies(cmd.body, batch=batch)
        return cls(
            body,
            *extra_bodies,
            _publish_type=cmd.publish_type,
            timer_id=timer_id,
            activate_in=activate_in,
            correlation_id=cmd.correlation_id,
            destination=cmd.destination,
            headers=cmd.headers,
            reply_to=cmd.reply_to,
        )
