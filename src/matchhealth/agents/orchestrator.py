"""Runs the crew for each trigger as a Microsoft Agent Framework workflow.

One workflow run per moment. Each agent is an Executor; handoffs are typed
messages along the graph's edges, and every handoff is also written to
shared state (Cosmos DB in Azure). Recovery is part of the graph, not a
try/except around it: an Analyst or Producer failure routes to the Fallback
executor, which still reaches the viewer as a stats-only overlay.

    narrator_context -> spotter -> analyst -> producer -> personaliser
                                      \\          \\         ^
                                       +-> fallback -------+

See docs/agent-workflow.md for the rendered graph (WorkflowViz).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from agent_framework import Executor, WorkflowBuilder, WorkflowContext, handler

from matchhealth.agents.crew import PRIORITY, Analyst, Personaliser, Producer, Spotter
from matchhealth.agents.grounding import allowed_numbers, ungrounded
from matchhealth.agents.llm import LLMClient
from matchhealth.agents.mock_text import overlay_text
from matchhealth.agents.narrator import Narrator
from matchhealth.shared.models import Explanation, Overlay, Trigger, clock
from matchhealth.shared.state import StateStore

log = logging.getLogger(__name__)

ANALYST_TIMEOUT_S = 15.0
PRODUCER_TIMEOUT_S = 15.0
SPOTTER_TIMEOUT_S = 10.0

# Every mode x language is one persona. The Personaliser and Narrator write
# all of them in ONE call each, so a language adds output tokens, not calls.
# Real translations come from the model; mock mode uses the hand-written
# templates in mock_text.py, which cover all five languages.
LANGUAGES = ["en", "es", "fr", "pt", "de"]
DEFAULT_PERSONAS = [{"mode": m, "language": lang}
                    for lang in LANGUAGES for m in ("casual", "analyst")]

Publish = Callable[[Overlay, list[Overlay]], Awaitable[None]]
ActivitySend = Callable[[dict], Awaitable[None]]


# --- handoff messages (the edges carry these) ---------------------------------

@dataclass
class Confirmed:
    trig: Trigger
    priority: int


@dataclass
class Explained:
    trig: Trigger
    priority: int
    expl: Explanation


@dataclass
class Recovery:
    trig: Trigger
    priority: int
    stage: str
    reason: str


@dataclass
class Produced:
    trig: Trigger
    base: Overlay


def record_grounding(store: StateStore, moment_id: str, stage: str, numbers: list[str],
                     persona: str | None = None) -> None:
    """Numbers an agent wrote that its facts don't contain (agents/grounding.py)."""
    doc = dict(store.get(moment_id).get("grounding") or {"rejected": []})
    doc["rejected"] = [*doc["rejected"], {"stage": stage, "persona": persona, "numbers": numbers}]
    store.put(moment_id, "grounding", doc)


def trigger_numbers(trig: Trigger) -> set[str]:
    return allowed_numbers(trig.facts, clock(trig.t))


def record_recovery(store: StateStore, moment_id: str, stage: str, reason: str) -> None:
    """Recoveries are keyed by stage, so two failures in one moment both survive."""
    recovery = dict(store.get(moment_id).get("recovery") or {})
    recovery[stage] = {"reason": reason}
    store.put(moment_id, "recovery", recovery)


# --- executors: one per agent ---------------------------------------------------

class NarratorContext(Executor):
    """Entry node: the Narrator adds season context, then the trigger is
    recorded in shared state before any agent reasons about it."""

    def __init__(self, crew: Orchestrator) -> None:
        super().__init__(id="narrator_context")
        self.crew = crew

    @handler(input=Trigger, output=Trigger)
    async def run(self, trig: Trigger, ctx: WorkflowContext) -> None:
        if self.crew.narrator:
            self.crew.narrator.enrich(trig)
        self.crew.store.put(trig.moment_id, "trigger", trig.model_dump())
        await ctx.send_message(trig)


class SpotterExecutor(Executor):
    """Confirm/reject + priority. Fails open: if the model is down, the
    engine's own priority is used rather than dropping the moment."""

    def __init__(self, crew: Orchestrator) -> None:
        super().__init__(id="spotter")
        self.crew = crew

    @handler(input=Trigger, output=Confirmed)
    async def run(self, trig: Trigger, ctx: WorkflowContext) -> None:
        store = self.crew.store
        recent = [m for m in store.moments() if m.get("id") != trig.moment_id][-5:]
        try:
            verdict = await asyncio.wait_for(self.crew.spotter.run(trig, recent=recent),
                                             SPOTTER_TIMEOUT_S)
        except Exception as exc:
            log.warning("moment %s: spotter failed (%s); using engine priority",
                        trig.moment_id, exc)
            verdict = {"confirm": True, "priority": PRIORITY[trig.kind],
                       "reason": "Engine priority (Spotter unavailable)"}
            record_recovery(store, trig.moment_id, "spotter", type(exc).__name__)
        store.put(trig.moment_id, "spotter", verdict)
        confirmed = bool(verdict.get("confirm", False))
        if self.crew.activity_send:
            # Broadcasts every Spotter decision, confirmed or not -- this is
            # the real multi-agent decision, not a simplified summary of it.
            await self.crew.activity_send({
                "moment_id": trig.moment_id, "kind": trig.kind, "team": trig.team,
                "player": trig.player, "show_at": clock(trig.t),
                "priority": verdict.get("priority"), "confirmed": confirmed,
                "reason": verdict.get("reason"), "x": trig.x, "y": trig.y,
            })
        if confirmed:
            await ctx.send_message(Confirmed(trig, int(verdict.get("priority", 2))))


class AnalystExecutor(Executor):
    def __init__(self, crew: Orchestrator) -> None:
        super().__init__(id="analyst")
        self.crew = crew

    @handler(input=Confirmed, output=Explained | Recovery)
    async def run(self, msg: Confirmed, ctx: WorkflowContext) -> None:
        try:
            expl = await asyncio.wait_for(self.crew.analyst.run(msg.trig), ANALYST_TIMEOUT_S)
        except Exception as exc:  # timeout, bad JSON
            await ctx.send_message(Recovery(msg.trig, msg.priority, "analyst",
                                            type(exc).__name__))
            return
        # Grounding guard: the explanation may cite only numbers from the facts.
        stats = " ".join(str(s.get(k)) for s in expl.key_stats for k in ("value", "from", "to")
                         if s.get(k) is not None)
        bad = ungrounded(f"{expl.why} {stats}", trigger_numbers(msg.trig))
        if bad:
            record_grounding(self.crew.store, msg.trig.moment_id, "analyst", bad)
            await ctx.send_message(Recovery(msg.trig, msg.priority, "analyst", "ungrounded"))
            return
        self.crew.store.put(msg.trig.moment_id, "analyst", expl.model_dump())
        await ctx.send_message(Explained(msg.trig, msg.priority, expl))


class ProducerExecutor(Executor):
    def __init__(self, crew: Orchestrator) -> None:
        super().__init__(id="producer")
        self.crew = crew

    @handler(input=Explained, output=Produced | Recovery)
    async def run(self, msg: Explained, ctx: WorkflowContext) -> None:
        try:
            base = await asyncio.wait_for(
                self.crew.producer.run(msg.trig, msg.expl, msg.priority), PRODUCER_TIMEOUT_S)
        except Exception as exc:  # timeout, schema violation
            await ctx.send_message(Recovery(msg.trig, msg.priority, "producer",
                                            type(exc).__name__))
            return
        self.crew.store.put(msg.trig.moment_id, "producer", base.to_wire())
        await ctx.send_message(Produced(msg.trig, base))


class FallbackExecutor(Executor):
    """Never a blank broadcast: a stats-only overlay from the engine's facts."""

    def __init__(self, crew: Orchestrator) -> None:
        super().__init__(id="fallback")
        self.crew = crew

    @handler(input=Recovery, output=Produced)
    async def run(self, msg: Recovery, ctx: WorkflowContext) -> None:
        log.warning("moment %s: falling back to stats-only (%s)", msg.trig.moment_id, msg.reason)
        base = Producer.fallback(msg.trig, msg.priority)
        record_recovery(self.crew.store, msg.trig.moment_id, msg.stage, msg.reason)
        self.crew.store.put(msg.trig.moment_id, "producer", base.to_wire())
        await ctx.send_message(Produced(msg.trig, base))


class PersonaliserExecutor(Executor):
    def __init__(self, crew: Orchestrator) -> None:
        super().__init__(id="personaliser")
        self.crew = crew

    @handler(input=Produced, workflow_output=Overlay)
    async def run(self, msg: Produced, ctx: WorkflowContext) -> None:
        try:
            variants = await self.crew.personaliser.run(msg.base, self.crew.personas,
                                                          msg.trig)
        except Exception as exc:
            log.warning("moment %s: personaliser failed (%s); base only",
                        msg.trig.moment_id, exc)
            variants = []
        # Grounding guard per persona: an invented number swaps that persona's
        # copy for the template written from the same facts.
        allowed = trigger_numbers(msg.trig) | allowed_numbers(msg.base.to_wire())
        trig = msg.trig
        for i, v in enumerate(variants):
            bad = ungrounded(f"{v.headline} {v.subline or ''}", allowed)
            if bad:
                record_grounding(self.crew.store, trig.moment_id, "personaliser", bad,
                                 f"{v.mode}-{v.language}")
                head, sub = overlay_text(trig.kind, trig.team, trig.player, trig.facts,
                                         v.mode, v.language)
                variants[i] = v.model_copy(update={"headline": head[:80],
                                                   "subline": sub[:90] if sub else None})
        self.crew.store.put(msg.trig.moment_id, "personaliser", [v.to_wire() for v in variants])
        await self.crew.publish(msg.base, variants)
        await ctx.yield_output(msg.base)


# --- the crew -------------------------------------------------------------------

class Orchestrator:
    def __init__(self, store: StateStore, publish: Publish, llm: LLMClient | None = None,
                 personas: list[dict] | None = None,
                 activity_send: ActivitySend | None = None,
                 narrator: Narrator | None = None) -> None:
        self.store = store
        self.publish = publish
        self.personas = personas or DEFAULT_PERSONAS
        self.activity_send = activity_send
        self.narrator = narrator
        self.spotter, self.analyst = Spotter(llm), Analyst(llm)
        self.producer, self.personaliser = Producer(llm), Personaliser(llm)
        self.workflow = build_workflow(self)

    async def handle(self, trig: Trigger) -> Overlay | None:
        result = await self.workflow.run(trig)
        outputs = result.get_outputs()
        return outputs[0] if outputs else None  # None: the Spotter rejected it


def build_workflow(crew: Orchestrator):
    context, spotter = NarratorContext(crew), SpotterExecutor(crew)
    analyst, producer = AnalystExecutor(crew), ProducerExecutor(crew)
    fallback, personaliser = FallbackExecutor(crew), PersonaliserExecutor(crew)
    return (
        WorkflowBuilder(name="moment_crew", start_executor=context,
                        description="Per-moment crew: explain, render and personalise")
        .add_edge(context, spotter)
        .add_edge(spotter, analyst)
        .add_edge(analyst, producer, condition=lambda m: isinstance(m, Explained))
        .add_edge(analyst, fallback, condition=lambda m: isinstance(m, Recovery))
        .add_edge(producer, personaliser, condition=lambda m: isinstance(m, Produced))
        .add_edge(producer, fallback, condition=lambda m: isinstance(m, Recovery))
        .add_edge(fallback, personaliser)
        .build()
    )
