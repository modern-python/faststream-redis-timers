import random
from collections.abc import Callable


_MAX_EXPONENT: int = 30
_MAX_ERROR_DELAY: float = 30.0


def _default_jitter() -> float:
    return random.uniform(0.5, 1.5)  # noqa: S311


class PollSchedule:
    """Pure backoff schedule for the subscriber poll loop.

    Holds two counters (idle and error) and computes delays without doing I/O.
    The caller is responsible for sleeping.
    """

    def __init__(
        self,
        *,
        base: float,
        max_idle: float,
        jitter: Callable[[], float] = _default_jitter,
    ) -> None:
        self._base = base
        self._max_idle = max_idle
        self._jitter = jitter
        self._idle_count: int = 0
        self._error_attempt: int = 0

    def delay_after_fetch(self, count: int) -> float:
        """Return the delay (seconds) to apply after a fetch that returned *count* items.

        - ``count > 0``: busy — reset idle counter, return 0.0 (no sleep needed).
        - ``count == 0``: idle — increment idle counter and return exponential backoff
          capped at *max_idle*.
        - ``count < 0``: back-pressured (limiter saturated) — return *base* without
          touching the idle counter.

        Always resets the error-attempt counter.
        """
        self._error_attempt = 0
        if count > 0:
            self._idle_count = 0
            return 0.0
        if count == 0:
            self._idle_count = min(self._idle_count + 1, _MAX_EXPONENT)
            return min(self._base * 2 ** (self._idle_count - 1) * self._jitter(), self._max_idle)
        # count < 0: back-pressure — yield briefly without growing idle counter
        return self._base

    def delay_after_error(self) -> float:
        """Return the delay (seconds) to apply after a fetch raised an exception.

        Increments the error-attempt counter (capped at ``_MAX_EXPONENT``) and
        returns exponential backoff capped at ``_MAX_ERROR_DELAY``.
        Does not touch the idle counter.
        """
        self._error_attempt = min(self._error_attempt + 1, _MAX_EXPONENT)
        return min(2 ** (self._error_attempt - 1) * self._jitter(), _MAX_ERROR_DELAY)
