from datetime import UTC, datetime, timedelta
from typing import Any

from faststream.response.publish_type import PublishType
from faststream.response.response import BatchPublishCommand, PublishCommand


def resolve_activate_at(activate_in: timedelta, activate_at: datetime | None) -> datetime:
    """
    Resolve ``(activate_in, activate_at)`` into a single absolute UTC datetime.

    Raises ``ValueError`` if both are non-default, or if ``activate_at`` is naive.
    A past ``activate_at`` is returned unchanged — fires immediately, same as
    a negative ``activate_in``.
    """
    if activate_at is None:
        return datetime.now(tz=UTC) + activate_in
    if activate_in != timedelta(0):
        msg = "Pass either activate_in or activate_at, not both"
        raise ValueError(msg)
    if activate_at.tzinfo is None:
        msg = "activate_at must be timezone-aware (e.g., datetime.now(tz=UTC))"
        raise ValueError(msg)
    return activate_at


class TimerPublishCommand(BatchPublishCommand):
    def __init__(  # noqa: PLR0913
        self,
        message: Any,
        /,
        *messages: Any,
        _publish_type: PublishType,
        timer_id: str = "",
        activate_at: datetime | None = None,
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
        self.activate_at = activate_at if activate_at is not None else datetime.now(tz=UTC)

    @classmethod
    def from_cmd(
        cls,
        cmd: "PublishCommand",
        *,
        timer_id: str = "",
        activate_at: datetime | None = None,
        batch: bool = False,
    ) -> "TimerPublishCommand":
        body, extra_bodies = cls._parse_bodies(cmd.body, batch=batch)
        return cls(
            body,
            *extra_bodies,
            _publish_type=cmd.publish_type,
            timer_id=timer_id,
            activate_at=activate_at,
            correlation_id=cmd.correlation_id,
            destination=cmd.destination,
            headers=cmd.headers,
            reply_to=cmd.reply_to,
        )
