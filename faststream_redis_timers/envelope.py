"""
Wire format for timer payloads.

Wraps FastStream's :class:`BinaryMessageFormatV1` with a one-shot reader for
the legacy v0.x JSON-of-hex envelope (``{"b": "<hex>", "ct": "..."}``) so
timers persisted by older versions continue to fire after upgrade.
"""

import json
from typing import Any

from faststream.redis.parser import BinaryMessageFormatV1


class TimerMessageFormat(BinaryMessageFormatV1):
    @classmethod
    def parse(cls, data: bytes) -> tuple[bytes, dict[str, Any]]:
        if data[:1] == b"{":
            try:
                d = json.loads(data)
            except (json.JSONDecodeError, ValueError):  # pragma: no cover
                d = None
            if isinstance(d, dict) and "b" in d:
                try:
                    body = bytes.fromhex(d["b"])
                except (TypeError, ValueError):  # pragma: no cover
                    body = b""
                headers: dict[str, Any] = {}
                if d.get("ct"):
                    headers["content-type"] = d["ct"]
                return body, headers
        return super().parse(data)
