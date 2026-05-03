import typing
from dataclasses import dataclass

from faststream._internal.configs import BrokerConfig
from faststream.exceptions import IncorrectState


if typing.TYPE_CHECKING:
    from redis.asyncio import Redis


class ConnectionState:
    def __init__(self, client: "Redis[bytes] | None" = None) -> None:
        self._client = client

    @property
    def client(self) -> "Redis[bytes]":
        if self._client is None:
            msg = "Connection not available. Connect the broker first."
            raise IncorrectState(msg)
        return self._client

    async def connect(self) -> "Redis[bytes]":
        return self.client

    async def disconnect(self) -> None:
        pass  # caller owns the client


@dataclass(kw_only=True)
class TimersBrokerConfig(BrokerConfig):
    connection: ConnectionState
    timeline_key: str = "timers_timeline"
    payloads_key: str = "timers_payloads"
    start_timeout: float = 3.0

    async def connect(self) -> None:
        await self.connection.connect()

    async def disconnect(self) -> None:
        await self.connection.disconnect()


@dataclass(kw_only=True)
class TimersRouterConfig(BrokerConfig):
    @property
    def connection(self) -> None:  # pragma: no cover
        raise IncorrectState
