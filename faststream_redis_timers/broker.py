import logging
import typing
from collections.abc import Iterable, Sequence
from datetime import datetime, timedelta

from fast_depends.dependencies import Dependant
from faststream import BaseMiddleware
from faststream._internal.basic_types import LoggerProto, SendableMessage
from faststream._internal.broker import BrokerUsecase
from faststream._internal.broker.registrator import Registrator
from faststream._internal.configs import BrokerConfig
from faststream._internal.constants import EMPTY
from faststream._internal.di import FastDependsConfig
from faststream._internal.logger import DefaultLoggerStorage, make_logger_state
from faststream._internal.logger.logging import get_broker_logger
from faststream._internal.types import BrokerMiddleware, CustomCallable
from faststream.message import gen_cor_id
from faststream.response.publish_type import PublishType
from faststream.specification.schema import BrokerSpec
from faststream.specification.schema.extra import Tag, TagDict

from faststream_redis_timers.configs import ConnectionState, TimersBrokerConfig
from faststream_redis_timers.message import TimerMessage
from faststream_redis_timers.publisher.producer import TimersProducer
from faststream_redis_timers.publisher.usecase import TimersPublisher
from faststream_redis_timers.registrator import TimersRegistrator
from faststream_redis_timers.response import TimerPublishCommand, resolve_activate_at
from faststream_redis_timers.subscriber.usecase import TimersSubscriber


if typing.TYPE_CHECKING:
    from faststream._internal.context.repository import ContextRepo
    from redis.asyncio import Redis


class TimersParamsStorage(DefaultLoggerStorage):
    __max_msg_id_ln = -1
    _max_channel_name = 7

    def get_logger(self, *, context: "ContextRepo") -> LoggerProto:
        if logger := self._get_logger_ref():
            return logger
        logger = get_broker_logger(
            name="timers",
            default_context={"channel": "", "message_id": ""},
            message_id_ln=self.__max_msg_id_ln,
            fmt=(
                "%(asctime)s %(levelname)-8s - "
                f"%(channel)-{self._max_channel_name}s | "
                f"%(message_id)-{self.__max_msg_id_ln}s "
                "- %(message)s"
            ),
            context=context,
            log_level=self.logger_log_level,
        )
        self._logger_ref.add(logger)
        return logger


class TimersBroker(
    TimersRegistrator,
    BrokerUsecase[
        TimerMessage,
        "Redis[bytes]",
        BrokerConfig,  # Use BrokerConfig to avoid typing issues when passing to FastStream app
    ],
):
    _subscribers: list[TimersSubscriber]
    _publishers: list[TimersPublisher]

    def __init__(  # noqa: PLR0913
        self,
        client: "Redis[bytes] | None" = None,
        *,
        timeline_key: str = "timers_timeline",
        payloads_key: str = "timers_payloads",
        decoder: CustomCallable | None = None,
        parser: CustomCallable | None = None,
        dependencies: Iterable[Dependant] = (),
        middlewares: Sequence[type[BaseMiddleware] | BrokerMiddleware[TimerMessage]] = (),
        graceful_timeout: float | None = 15.0,
        routers: Sequence[Registrator[TimerMessage]] = (),
        # Logging args
        logger: LoggerProto | None = EMPTY,
        log_level: int = logging.INFO,
        # FastDepends args
        apply_types: bool = True,
        # AsyncAPI args
        description: str | None = None,
        tags: Iterable[Tag | TagDict] = (),
    ) -> None:
        fd_config = FastDependsConfig(use_fastdepends=apply_types)
        connection = ConnectionState(client)
        broker_config = TimersBrokerConfig(
            connection=connection,
            timeline_key=timeline_key,
            payloads_key=payloads_key,
            broker_middlewares=middlewares,
            broker_parser=parser,
            broker_decoder=decoder,
            logger=make_logger_state(
                logger=logger,
                log_level=log_level,
                default_storage_cls=TimersParamsStorage,
            ),
            fd_config=fd_config,
            broker_dependencies=dependencies,
            graceful_timeout=graceful_timeout,
            extra_context={"broker": self},
            producer=TimersProducer(
                connection=connection,
                timeline_key=timeline_key,
                payloads_key=payloads_key,
                serializer=fd_config._serializer,  # noqa: SLF001
            ),
        )
        specification = BrokerSpec(
            url=[],
            protocol="redis",
            protocol_version="5.0",
            description=description,
            tags=tags,
            security=None,
        )
        super().__init__(config=broker_config, specification=specification, routers=routers)  # ty: ignore[unknown-argument]

    @typing.override
    async def _connect(self) -> "Redis[bytes]":
        return self.config.broker_config.connection.client

    @typing.override
    async def __aenter__(self) -> typing.Self:
        await self.start()
        return self

    @typing.override
    async def start(self) -> None:
        await self.connect()
        await super().start()

    @typing.override
    async def ping(self, timeout: float | None = None) -> bool:
        try:
            client = self.config.broker_config.connection.client
        except Exception:  # noqa: BLE001
            return False
        try:
            if not typing.cast("bool", await client.ping()):
                return False
        except Exception:  # noqa: BLE001
            return False
        for subscriber in self._subscribers:
            for task in subscriber.tasks:
                if task.done():
                    return False
        return True

    async def publish(  # noqa: PLR0913
        self,
        message: "SendableMessage" = None,
        topic: str = "",
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
            destination=f"{self.config.broker_config.prefix}{topic}",
            timer_id=timer_id,
            activate_at=resolve_activate_at(activate_in, activate_at),
            correlation_id=correlation_id or timer_id,
            headers=headers,
        )
        await self._basic_publish(cmd, producer=self.config.producer)
        return timer_id

    async def cancel_timer(self, topic: str, timer_id: str) -> None:
        """Cancel a pending timer. No-op if the timer has already fired or does not exist."""
        full_topic = f"{self.config.broker_config.prefix}{topic}"
        producer = typing.cast("TimersProducer", self.config.broker_config.producer)
        await producer.cancel(full_topic, timer_id)

    async def request(self, *args: typing.Any, **kwargs: typing.Any) -> typing.Any:
        msg = "TimersBroker does not support request-reply"
        raise NotImplementedError(msg)

    async def publish_batch(self, *args: typing.Any, **kwargs: typing.Any) -> None:
        msg = "Use multiple publish() calls for multiple timers"
        raise NotImplementedError(msg)
