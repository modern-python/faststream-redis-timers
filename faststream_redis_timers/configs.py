from dataclasses import dataclass
from typing import TYPE_CHECKING

from faststream._internal.configs import BrokerConfig
from faststream.exceptions import IncorrectState


if TYPE_CHECKING:
    from redis.asyncio import Redis


class ConnectionState:
    def __init__(self, url: str) -> None:
        self._url = url
        self._client: Redis[bytes] | None = None

    @property
    def client(self) -> "Redis[bytes]":
        if not self._client:
            msg = "Connection not available. Connect the broker first."
            raise IncorrectState(msg)
        return self._client

    async def connect(self) -> "Redis[bytes]":
        from redis.asyncio import Redis  # noqa: PLC0415

        self._client = Redis.from_url(self._url)  # type: ignore[attr-defined]
        return self._client

    async def disconnect(self) -> None:
        if self._client:
            await self._client.aclose()  # type: ignore[attr-defined]
        self._client = None


@dataclass(kw_only=True)
class TimersBrokerConfig(BrokerConfig):
    connection: ConnectionState
    timeline_key: str = "timers_timeline"
    payloads_key: str = "timers_payloads"
    lock_prefix: str = "timers_lock:"

    async def connect(self) -> None:
        await self.connection.connect()

    async def disconnect(self) -> None:
        await self.connection.disconnect()


@dataclass(kw_only=True)
class TimersRouterConfig(BrokerConfig):
    @property  # type: ignore[override]
    def connection(self) -> None:
        raise IncorrectState
