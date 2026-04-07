from collections.abc import Iterable
from datetime import timedelta
from typing import TYPE_CHECKING, Any, NoReturn

from faststream._internal.endpoint.publisher import PublisherSpecification, PublisherUsecase
from faststream.message import gen_cor_id
from faststream.response.publish_type import PublishType
from faststream.specification.asyncapi.utils import resolve_payloads
from faststream.specification.schema import Message, Operation, PublisherSpec

from faststream_redis_timers.publisher.config import TimersPublisherConfig, TimersPublisherSpecificationConfig
from faststream_redis_timers.response import TimerPublishCommand


if TYPE_CHECKING:
    from faststream._internal.basic_types import SendableMessage
    from faststream._internal.types import PublisherMiddleware
    from faststream.response.response import PublishCommand


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
        super().__init__(config, specification)  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]
        self.config = config

    async def publish(
        self,
        message: "SendableMessage" = None,
        *,
        timer_id: str = "",
        activate_in: timedelta = timedelta(0),
        correlation_id: str | None = None,
    ) -> None:
        if not timer_id:
            timer_id = gen_cor_id()

        cmd = TimerPublishCommand(
            message,
            _publish_type=PublishType.PUBLISH,
            destination=self.config.full_topic,
            timer_id=timer_id,
            activate_in=activate_in,
            correlation_id=correlation_id or gen_cor_id(),
        )
        await self._basic_publish(
            cmd,
            producer=self.config._outer_config.producer,  # noqa: SLF001
            _extra_middlewares=(),
        )

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

    async def request(self, *args: Any, **kwargs: Any) -> NoReturn:
        msg = "Timers do not support request-reply"
        raise NotImplementedError(msg)
