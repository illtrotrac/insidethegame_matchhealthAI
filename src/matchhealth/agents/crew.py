"""The four agents. Each has a real (LLM) path and a deterministic mock path."""

from __future__ import annotations

import re

from matchhealth.agents.llm import LLMClient, load_prompt, mock_enabled
from matchhealth.shared.models import Explanation, Overlay, Trigger, clock

PRIORITY = {"goal": 1, "big_chance": 1, "control_swing": 2, "pressing_spell": 2,
            "speed_milestone": 3}


class Spotter:
    """Confirms the trigger is a story worth telling and sets priority. Tier: nano."""

    def __init__(self, llm: LLMClient | None) -> None:
        self.llm = llm

    async def run(self, trig: Trigger, recent: list[dict]) -> dict:
        if mock_enabled() or self.llm is None:
            return {"confirm": True, "priority": PRIORITY[trig.kind]}
        return await self.llm.complete_json(
            load_prompt("spotter"), {"trigger": trig.model_dump(), "recent": recent}, "nano")


class Analyst:
    """Explains WHY the moment matters, citing only facts it was given. Tier: mini."""

    def __init__(self, llm: LLMClient | None) -> None:
        self.llm = llm

    async def run(self, trig: Trigger) -> Explanation:
        if mock_enabled() or self.llm is None:
            return Explanation(moment_id=trig.moment_id, why=_mock_why(trig),
                               key_stats=_facts_to_stats(trig))
        data = await self.llm.complete_json(load_prompt("analyst"), trig.model_dump(), "mini")
        return Explanation(moment_id=trig.moment_id, **data)


class Producer:
    """Turns an explanation into a timed overlay spec. Tier: nano."""

    def __init__(self, llm: LLMClient | None) -> None:
        self.llm = llm

    async def run(self, trig: Trigger, expl: Explanation, priority: int) -> Overlay:
        if mock_enabled() or self.llm is None:
            return Overlay(
                moment_id=trig.moment_id, template=_template_for(trig), show_at=clock(trig.t),
                duration_s=8 if priority == 1 else 7, priority=priority,
                headline=re.split(r"(?<=[a-z0-9])\.\s", expl.why)[0].rstrip(".")[:80],
                subline=None,
                stats=expl.key_stats[:3], focus_player=trig.player,
            )
        data = await self.llm.complete_json(
            load_prompt("producer"),
            {"trigger": trig.model_dump(), "explanation": expl.model_dump(),
             "priority": priority, "show_at": clock(trig.t)}, "nano")
        return Overlay.model_validate(data)  # raises -> orchestrator falls back

    @staticmethod
    def fallback(trig: Trigger, priority: int) -> Overlay:
        """Stats-only overlay used when the Analyst or validation fails."""
        return Overlay(
            moment_id=trig.moment_id, template="stats_only_fallback", show_at=clock(trig.t),
            duration_s=6, priority=priority,
            headline=f"{trig.team}: {trig.kind.replace('_', ' ')}",
            stats=_facts_to_stats(trig)[:3], focus_player=trig.player,
        )


class Personaliser:
    """Produces every variant in ONE call; never changes template/timing/priority. Tier: nano."""

    def __init__(self, llm: LLMClient | None) -> None:
        self.llm = llm

    async def run(self, base: Overlay, personas: list[dict]) -> list[Overlay]:
        if mock_enabled() or self.llm is None:
            variants = []
            for p in personas:
                head = base.headline
                if p.get("mode") == "casual":
                    head = head.replace("control score", "grip on the game")
                if p.get("language", "en") != "en":
                    head = f"[{p['language']}] {head}"
                variants.append(base.model_copy(update={
                    "headline": head[:80], "mode": p.get("mode", "base"),
                    "language": p.get("language", "en"),
                    "focus_player": p.get("favourite_player") or base.focus_player}))
            return variants
        data = await self.llm.complete_json(
            load_prompt("personaliser"),
            {"base": base.to_wire(), "personas": personas}, "nano")
        locked = {"moment_id", "template", "show_at", "duration_s", "priority", "stats"}
        return [Overlay.model_validate({**v, **{k: base.to_wire()[k] for k in locked}})
                for v in data.get("variants", [])]


# --- helpers ---------------------------------------------------------------

def _template_for(trig: Trigger) -> str:
    return {"big_chance": "big_chance", "goal": "big_chance",
            "control_swing": "momentum_chart", "pressing_spell": "lower_third_stat",
            "speed_milestone": "player_tag"}[trig.kind]


def _facts_to_stats(trig: Trigger) -> list[dict]:
    f = trig.facts
    if "control_from" in f:
        return [{"label": "Control score", "from": f["control_from"], "to": f["control_to"]}]
    return [{"label": k.replace("_", " ").capitalize(), "value": v}
            for k, v in f.items() if isinstance(v, (int, float))]


def _mock_why(trig: Trigger) -> str:
    f = trig.facts
    return {
        "goal": f"{f.get('scorer')} scores for {trig.team}.",
        "big_chance": f"Big chance for {trig.team}: shot quality {f.get('shot_quality')}.",
        "control_swing": (f"{trig.team} have seized control. Control score up from "
                          f"{f.get('control_from')} to {f.get('control_to')}."),
        "pressing_spell": (f"{trig.team}'s press is breaking the opponent's rhythm. "
                           f"{f.get('turnovers_forced_5min')} turnovers in 5 minutes."),
        "speed_milestone": f"Rocket from {trig.player}: {f.get('shot_speed_kmh')} km/h.",
    }[trig.kind]
