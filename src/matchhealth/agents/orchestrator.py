"""Runs the crew for each trigger, records every handoff, recovers from failures."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

from matchhealth.agents.crew import Analyst, Personaliser, Producer, Spotter
from matchhealth.agents.llm import LLMClient
from matchhealth.shared.models import Overlay, Trigger
from matchhealth.shared.state import StateStore

log = logging.getLogger(__name__)

ANALYST_TIMEOUT_S = 15.0

DEFAULT_PERSONAS = [
    {"mode": "analyst", "language": "en"},
    {"mode": "casual", "language": "en"},
    {"mode": "casual", "language": "es"},
]

Publish = Callable[[Overlay, list[Overlay]], Awaitable[None]]


class Orchestrator:
    def __init__(self, store: StateStore, publish: Publish, llm: LLMClient | None = None,
                 personas: list[dict] | None = None) -> None:
        self.store = store
        self.publish = publish
        self.personas = personas or DEFAULT_PERSONAS
        self.spotter, self.analyst = Spotter(llm), Analyst(llm)
        self.producer, self.personaliser = Producer(llm), Personaliser(llm)

    async def handle(self, trig: Trigger) -> Overlay | None:
        self.store.put(trig.moment_id, "trigger", trig.model_dump())

        verdict = await self.spotter.run(trig, recent=self.store.moments()[-5:])
        self.store.put(trig.moment_id, "spotter", verdict)
        if not verdict.get("confirm", False):
            return None
        priority = int(verdict.get("priority", 2))

        try:
            expl = await asyncio.wait_for(self.analyst.run(trig), ANALYST_TIMEOUT_S)
            self.store.put(trig.moment_id, "analyst", expl.model_dump())
            base = await self.producer.run(trig, expl, priority)
        except Exception as exc:  # timeout, bad JSON, schema violation
            log.warning("moment %s: falling back to stats-only (%s)", trig.moment_id, exc)
            base = Producer.fallback(trig, priority)
            self.store.put(trig.moment_id, "recovery", {"reason": type(exc).__name__})
        self.store.put(trig.moment_id, "producer", base.to_wire())

        try:
            variants = await self.personaliser.run(base, self.personas)
        except Exception as exc:
            log.warning("moment %s: personaliser failed (%s); base only", trig.moment_id, exc)
            variants = []
        self.store.put(trig.moment_id, "personaliser", [v.to_wire() for v in variants])

        await self.publish(base, variants)
        return base
