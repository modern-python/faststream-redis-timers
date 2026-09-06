import inspect
import typing

from faststream_redis_timers.registrator import TimersRegistrator
from faststream_redis_timers.router import TimersRoute
from faststream_redis_timers.schemas import TimerSub
from faststream_redis_timers.subscriber.factory import create_subscriber


PUBLISHED_DEFAULTS: typing.Final = {
    "polling_interval": 0.05,
    "max_polling_interval": 5.0,
    "max_concurrent": 5,
    "lease_ttl": 30,
}

DECLARATION_SITES: typing.Final = (
    TimerSub,
    create_subscriber,
    TimersRegistrator.subscriber,
    TimersRoute.__init__,
)


def _declared_defaults(site: typing.Any) -> dict[str, typing.Any]:
    parameters = inspect.signature(site).parameters
    return {name: parameters[name].default for name in PUBLISHED_DEFAULTS}


def test_every_declaration_of_a_subscriber_tuning_knob_carries_the_published_default() -> None:
    """INVARIANT: the four poll-loop knobs default the same at every site that declares them.

    Broken by adding a knob, or retuning one, at fewer than all four sites. Each of
    ``TimerSub``, ``create_subscriber``, ``TimersRegistrator.subscriber`` and ``TimersRoute``
    repeats the same defaults in its own signature, so a knob raised in one place and not the
    others gives ``broker.subscriber(...)`` and ``TimersRoute(...)`` different poll behaviour
    for identical user code — a divergence nothing else notices, because every path still
    constructs a valid ``TimerSub``. The values are also a published contract: they are the
    tables in ``docs/usage/subscriber.md`` and ``docs/introduction/how-it-works.md``, and
    ``lease_ttl`` in particular is the redelivery window a user sizes their handlers against.
    Retuning one on purpose is a user-visible change and should trip this test.
    """
    for site in DECLARATION_SITES:
        assert _declared_defaults(site) == PUBLISHED_DEFAULTS, site
