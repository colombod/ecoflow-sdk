from __future__ import annotations

import asyncio

from ecoflow_twin.recording import Recording
from ecoflow_twin.timeline import play

REC = Recording.from_dict(
    {
        "rest": {"device_list": [], "quota": {}},
        "mqtt": [
            {"t": 0.0, "sn": "A", "payload": {"n": 1}},
            {"t": 0.5, "sn": "B", "payload": {"n": 2}},
        ],
    },
    name="t",
)


async def test_plays_in_order_and_loops() -> None:
    seen: list[tuple[str, int]] = []
    async for sn, payload in play(REC, speed=1000):
        seen.append((sn, payload["n"]))
        if len(seen) == 5:
            break
    assert seen == [("A", 1), ("B", 2), ("A", 1), ("B", 2), ("A", 1)]


async def test_empty_timeline_blocks_until_cancelled() -> None:
    empty = Recording.from_dict({"rest": {"device_list": [], "quota": {}}}, name="e")

    async def first() -> object:
        async for item in play(empty, speed=1000):
            return item
        return None

    task = asyncio.create_task(first())
    await asyncio.sleep(0.05)
    assert not task.done()
    task.cancel()
