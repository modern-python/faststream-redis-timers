from dataclasses import dataclass


@dataclass(kw_only=True, slots=True, frozen=True)
class TimerSub:
    """Configuration for a single timer topic subscription."""

    topic: str
    polling_interval: float = 0.05
    # Maximum concurrent handler invocations; also bounds fetch batch size per poll.
    max_concurrent: int = 5
    lease_ttl: int = 30
