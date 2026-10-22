"""Streams a generated match in (accelerated) real time."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterable

from matchhealth.shared.models import MatchEvent


async def replay(events: Iterable[MatchEvent], speed: float = 1.0) -> AsyncIterator[MatchEvent]:
    """Yield events spaced by match time / speed. speed=0 means as fast as possible."""
    last_t = None
    for ev in events:
        if speed > 0 and last_t is not None:
            await asyncio.sleep(max(0.0, (ev.t - last_t) / speed))
        last_t = ev.t
        yield ev
