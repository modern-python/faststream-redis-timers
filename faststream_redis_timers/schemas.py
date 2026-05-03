from dataclasses import dataclass


@dataclass(kw_only=True, slots=True, frozen=True)
class TimerSub:
    """Configuration for a single timer topic subscription."""

    topic: str
    polling_interval: float = 0.05
    # Cap for adaptive backoff when the queue is idle; doubles from polling_interval up to this value.
    max_polling_interval: float = 5.0
    # Maximum concurrent handler invocations; also bounds fetch batch size per poll.
    max_concurrent: int = 5
    lease_ttl: int = 30
