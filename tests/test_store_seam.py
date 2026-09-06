import ast
import pathlib


PACKAGE_ROOT = pathlib.Path(__file__).resolve().parent.parent / "faststream_redis_timers"

# The Redis calls that make up the timer protocol: the timeline sorted set, the
# payloads hash, and the Lua dispatch. `ping` is deliberately absent — it is
# connection health, not the protocol, and the broker and subscriber both call it.
PROTOCOL_COMMANDS = frozenset(
    {
        "eval",
        "evalsha",
        "execute_command",
        "hdel",
        "hget",
        "hset",
        "pipeline",
        "script_load",
        "unlink",
        "zadd",
        "zcard",
        "zrangebyscore",
        "zrem",
        "zscore",
    }
)


def _modules_issuing_protocol_commands() -> set[str]:
    issuers = set()
    for path in PACKAGE_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in PROTOCOL_COMMANDS
            ):
                issuers.add(str(path.relative_to(PACKAGE_ROOT)))
    return issuers


def test_the_redis_timer_protocol_is_issued_only_from_the_store() -> None:
    """INVARIANT: no module outside ``store.py`` issues a Redis timer-protocol command.

    Broken by reaching for the Redis client anywhere else: a subscriber that ZREMs a timer
    it just handled, broker inspection that ZSCOREs the timeline directly, a fake that
    writes the timeline itself. The key pair ``{timeline_key}:{full_topic}`` /
    ``{payloads_key}:{full_topic}`` and the claim/commit Lua are defined in exactly one
    place, so a second issuer is a second, silently divergent definition of the wire
    protocol — and the lease rule (a claim *advances* the score, it does not remove the
    timer) is the kind of thing a second definition gets subtly wrong. The store's seven
    methods are the only vocabulary a caller gets.
    """
    assert _modules_issuing_protocol_commands() == {"store.py"}
