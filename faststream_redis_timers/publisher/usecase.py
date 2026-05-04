import typing
from collections.abc import Iterable
from datetime import datetime, timedelta

from faststream._internal.endpoint.publisher import PublisherSpecification, PublisherUsecase
from faststream.message import gen_cor_id
from faststream.response.publish_type import PublishType
from faststream.specification.asyncapi.utils import resolve_payloads
from faststream.specification.schema import Message, Operation, PublisherSpec

from faststream_redis_timers.publisher.config import TimersPublisherConfig, TimersPublisherSpecificationConfig
from faststream_redis_timers.response import TimerPublishCommand, resolve_activate_at


if typing.TYPE_CHECKING:
    from faststream._internal.basic_types import SendableMessage
    from faststream._internal.types import PublisherMiddleware
    from faststream.response.response import PublishCommand

    from faststream_redis_timers.publisher.producer import TimersProducer


class TimersPublisherSpecification(PublisherSpecification["TimersBrokerConfig", TimersPublisherSpecificationConfig]):  # ty: ignore[unresolved-reference]
    @property
    def name(self) -> str:
        prefix = getattr(self._outer_config, "prefix", "")
        return f"{prefix}{self.config.topic}:Publisher"

    def get_schema(self) -> dict[str, PublisherSpec]:
        return {
            self.name: PublisherSpec(
                description=self.config.description_,
                operation=Operation(
                    message=Message(
                        title=f"{self.name}:Message",
                        payload=resolve_payloads(self.get_payloads(), "Publisher"),
                    ),
                    bindings=None,
                ),
                bindings=None,
            )
        }


class TimersPublisher(PublisherUsecase):
    def __init__(
        self,
        config: TimersPublisherConfig,
        specification: TimersPublisherSpecification,
    ) -> None:
        super().__init__(config, specification)  # ty: ignore[invalid-argument-type]
        self.config = config

    async def publish(  # noqa: PLR0913
        self,
        message: "SendableMessage" = None,
        *,
        timer_id: str = "",
        activate_in: timedelta = timedelta(0),
        activate_at: datetime | None = None,
        correlation_id: str | None = None,
        headers: dict[str, typing.Any] | None = None,
    ) -> str:
        if not timer_id:
            timer_id = gen_cor_id()

        cmd = TimerPublishCommand(
            message,
            _publish_type=PublishType.PUBLISH,
            destination=self.config.full_topic,
            timer_id=timer_id,
            activate_at=resolve_activate_at(activate_in, activate_at),
            correlation_id=correlation_id or timer_id,
            headers=headers,
        )
        await self._basic_publish(
            cmd,
            producer=self.config._outer_config.producer,  # noqa: SLF001
            _extra_middlewares=(),
        )
        return timer_id

    async def _publish(
        self,
        cmd: "PublishCommand",
        *,
        _extra_middlewares: Iterable["PublisherMiddleware"],
    ) -> None:
        timer_cmd = TimerPublishCommand.from_cmd(cmd)
        timer_cmd.destination = self.config.full_topic
        await self._basic_publish(
            timer_cmd,
            producer=self.config._outer_config.producer,  # noqa: SLF001
            _extra_middlewares=_extra_middlewares,
        )

    async def cancel(self, timer_id: str) -> None:
        """Cancel a pending timer by ID. No-op if the timer has already fired or does not exist."""
        producer = typing.cast("TimersProducer", self.config._outer_config.producer)  # noqa: SLF001
        await producer.cancel(self.config.full_topic, timer_id)

    async def fetch_redis_timers(self, dt: datetime) -> list[tuple[str, str]]:
        """Return (topic, timer_id) pairs for timers due by *dt* on this publisher's topic."""
        client = self.config._outer_config.connection.client  # noqa: SLF001
        timeline_key = f"{self.config._outer_config.timeline_key}:{self.config.full_topic}"  # noqa: SLF001
        timer_ids: list[bytes] | list[str] = await client.zrangebyscore(timeline_key, "-inf", dt.timestamp())
        return [(self.config.topic, raw_id.decode() if isinstance(raw_id, bytes) else raw_id) for raw_id in timer_ids]

    async def request(self, *args: typing.Any, **kwargs: typing.Any) -> typing.NoReturn:
        msg = "Timers do not support request-reply"
        raise NotImplementedError(msg)
