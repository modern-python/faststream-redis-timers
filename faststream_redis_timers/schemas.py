import math
from dataclasses import dataclass


@dataclass(kw_only=True, slots=True, frozen=True)
class TimerSub:
    """Configuration for a single timer topic subscription."""

    topic: str
    polling_interval: float = 0.05
    # Cap for adaptive backoff when the topic is idle; doubles from polling_interval up to this value.
    max_polling_interval: float = 5.0
    # Maximum concurrent handler invocations; also bounds fetch batch size per poll.
    max_concurrent: int = 5
    lease_ttl: int = 30
    command_timeout: float | None = None

    def __post_init__(self) -> None:
        if self.command_timeout is None:
            return
        if not math.isfinite(self.command_timeout):
            msg = f"command_timeout must be finite, got {self.command_timeout}"
            raise ValueError(msg)
        if self.command_timeout <= 0:
            msg = f"command_timeout must be > 0, got {self.command_timeout}"
            raise ValueError(msg)
        if self.command_timeout > self.lease_ttl:
            msg = f"command_timeout ({self.command_timeout}) must be <= lease_ttl ({self.lease_ttl})"
            raise ValueError(msg)

    @property
    def effective_command_timeout(self) -> float:
        return self.lease_ttl if self.command_timeout is None else self.command_timeout
