import typing
from typing import TypedDict

from faststream.message import StreamMessage


class TimerMessage(TypedDict):
    type: typing.Literal["timer"]
    channel: str
    timer_id: str
    data: bytes


# Timer cleanup (ZREM/HDEL) happens atomically in _get_msgs() before consume(),
# so no ack/nack/reject overrides are needed here.
class TimerStreamMessage(StreamMessage["TimerMessage"]):
    pass
