"""Playback clock for recorded MQTT pushes: time-compressed and looping."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any, cast

from ecoflow_twin.recording import Recording


async def play(
    recording: Recording, speed: float
) -> AsyncIterator[tuple[str, dict[str, Any]]]:
    """Yield ``(sn, raw payload)`` in recorded order at ``speed``× real time.

    Loops forever, one recorded second past the recording's end, so "wait for
    the next push" always resolves. An empty timeline never yields (a silent
    device): the caller cancels it.
    """
    if not recording.mqtt:
        await asyncio.Event().wait()
    loop = asyncio.get_running_loop()
    period = recording.duration_s + 1.0
    while True:
        start = loop.time()
        for push in recording.mqtt:
            delay = start + float(push["t"]) / speed - loop.time()
            if delay > 0:
                await asyncio.sleep(delay)
            yield str(push["sn"]), cast(dict[str, Any], push["payload"])
        await asyncio.sleep(max(start + period / speed - loop.time(), 0.0))
