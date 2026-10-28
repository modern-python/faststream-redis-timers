import asyncio
import logging
import uuid
from collections import Counter

from redis.asyncio import Redis

from faststream_redis_timers import TimersBroker


class _RecordCollector(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


async def test_received_and_processed_logs_name_each_timer(redis_client: Redis) -> None:
    suffix = uuid.uuid4().hex
    broker = TimersBroker(
        redis_client,
        timeline_key=f"logctx_tl_{suffix}",
        payloads_key=f"logctx_pl_{suffix}",
    )
    timer_ids = [f"t-{n}" for n in range(12)]
    handled: list[str] = []
    all_done = asyncio.Event()

    @broker.subscriber("topic", max_concurrent=4)
    async def handler(body: str) -> None:
        handled.append(body)
        await asyncio.sleep(0.01)
        if len(handled) == len(timer_ids):
            all_done.set()

    collector = _RecordCollector()
    access_logger = logging.getLogger("faststream.access.timers")
    access_logger.addHandler(collector)
    try:
        async with broker:
            for timer_id in timer_ids:
                await broker.publish(timer_id, topic="topic", timer_id=timer_id)
            await asyncio.wait_for(all_done.wait(), timeout=5.0)
    finally:
        access_logger.removeHandler(collector)

    assert sorted(handled) == sorted(timer_ids)
    for event in ("Received", "Processed"):
        logged = Counter(r.message_id for r in collector.records if r.getMessage() == event)  # ty: ignore[unresolved-attribute]
        assert logged == Counter(timer_ids), event
