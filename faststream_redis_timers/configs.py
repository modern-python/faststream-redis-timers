import codecs
import typing
from dataclasses import dataclass
from typing import TypeAlias

from faststream._internal.configs import BrokerConfig
from faststream.exceptions import IncorrectState

from faststream_redis_timers.store import TimerStore


if typing.TYPE_CHECKING:
    from redis.asyncio import Redis


# Accepts a client created with either default (bytes) or ``decode_responses=True`` (str).
# The CLAIM Lua reply is forced through ``NEVER_DECODE`` so the binary envelope stays
# intact regardless of which mode the user picked.
RedisClient: TypeAlias = "Redis[bytes] | Redis[str]"


class ConnectionState:
    def __init__(self, client: "RedisClient | None" = None) -> None:
        if client is not None:
            encoder = client.connection_pool.get_encoder()
            if codecs.lookup(encoder.encoding).name != "utf-8" or encoder.encoding_errors != "strict":
                msg = "TimersBroker requires UTF-8 Redis encoding with strict encoding errors."
                raise ValueError(msg)
        self._client = client

    @property
    def client(self) -> "RedisClient":
        if self._client is None:
            msg = "TimersBroker has no Redis client; pass one to TimersBroker(client)."
            raise IncorrectState(msg)
        return self._client

    async def connect(self) -> "RedisClient":
        return self.client

    async def disconnect(self) -> None:
        pass  # caller owns the client


@dataclass(kw_only=True)
class TimersBrokerConfig(BrokerConfig):
    connection: ConnectionState
    start_timeout: float = 3.0
    store: TimerStore

    async def connect(self) -> None:
        await self.connection.connect()

    async def disconnect(self) -> None:
        await self.connection.disconnect()
