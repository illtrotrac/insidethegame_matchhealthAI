"""The four agents. Each has a real (LLM) path and a deterministic mock path."""

from __future__ import annotations

import re

from matchhealth.agents.llm import LLMClient, load_prompt, mock_enabled
from matchhealth.agents.mock_text import overlay_text
from matchhealth.shared.models import Explanation, Overlay, Trigger, clock

PRIORITY = {"goal": 1, "big_chance": 1, "control_swing": 2, "pressing_spell": 2,
            "speed_milestone": 3, "foul": 2, "pass_quality": 3}

MOCK_REASON = {
    "goal": "Goal: always the story",
    "big_chance": "High-quality chance created",
    "control_swing": "Clear momentum shift",
    "pressing_spell": "Sustained pressing spell",
    "speed_milestone": "Notable speed/power moment",
    "foul": "Card shown: real consequence",
    "pass_quality": "Defense-splitting pass",
}


class Spotter:
    """Confirms the trigger is a story worth telling and sets priority. Tier: nano."""

    def __init__(self, llm: LLMClient | None) -> None:
        self.llm = llm

    async def run(self, trig: Trigger, recent: list[dict]) -> dict:
        if mock_enabled() or self.llm is None:
            # Always confirms, by design: the engine's per-(kind, team) cooldown
            # (see thresholds.py) already filters near-duplicate stories before
            # a Trigger ever reaches the Spotter, so there's nothing left to
            # reject deterministically here. The real LLM Spotter (prompts/
            # spotter.md) does genuinely reject repeats with its own reasoning
            # -- this mock path is a stand-in, not a claim that confirm=True
            # is the real decision logic.
            priority = PRIORITY[trig.kind]
            if trig.kind == "foul" and trig.facts.get("card") == "red":
                priority = 1  # a red card is a game-changing moment, not routine
            return {"confirm": True, "priority": priority, "reason": MOCK_REASON[trig.kind]}
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
            # expl.why is "<insight>. <evidence/consequence>." (see
            # prompts/analyst.md). Only the first sentence was ever used --
            # subline was hardcoded to None -- so any second sentence (e.g.
            # a foul's "Free kick to the opposition") was silently dropped
            # for every trigger kind, not just fouls.
            sentences = re.split(r"(?<=[a-z0-9])\.\s", expl.why)
            subline = " ".join(sentences[1:]).rstrip(".").strip()[:90] or None
            return Overlay(
                moment_id=trig.moment_id, template=_template_for(trig), show_at=clock(trig.t),
                duration_s=8 if priority == 1 else 7, priority=priority,
                headline=sentences[0].rstrip(".")[:80],
                subline=subline,
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

    async def run(self, base: Overlay, personas: list[dict],
                  trig: Trigger | None = None) -> list[Overlay]:
        if mock_enabled() or self.llm is None:
            # Hand-written templates per language (mock_text.py), built from
            # the moment's facts -- real translations, not word swaps.
            variants = []
            for p in personas:
                mode, lang = p.get("mode", "base"), p.get("language", "en")
                head, sub = base.headline, base.subline
                if trig is not None:
                    head, sub = overlay_text(trig.kind, trig.team, trig.player, trig.facts,
                                             mode, lang)
                variants.append(base.model_copy(update={
                    "headline": head[:80], "subline": sub[:90] if sub else None,
                    "mode": mode, "language": lang}))
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
            "speed_milestone": "player_tag", "foul": "lower_third_stat",
            "pass_quality": "player_tag"}[trig.kind]


def _facts_to_stats(trig: Trigger) -> list[dict]:
    f = trig.facts
    if "control_from" in f:
        return [{"label": "Control score", "from": f["control_from"], "to": f["control_to"]}]
    if "card" in f:
        return [{"label": "Card shown", "value": f["card"].capitalize()}]
    if "pass_difficulty" in f:
        return [{"label": "Pass distance", "value": f.get("pass_distance_m"), "unit": "m"},
                {"label": "Difficulty rating", "value": f["pass_difficulty"]},
                {"label": "Ball speed", "value": f.get("pass_speed_kmh"), "unit": "km/h"}]
    return [{"label": k.replace("_", " ").capitalize(), "value": v}
            for k, v in f.items() if isinstance(v, (int, float))]


def _mock_why(trig: Trigger) -> str:
    f = trig.facts
    return {
        "goal": f"{f.get('scorer')} scores for {trig.team}." + (
            "" if not f.get("scorer_season_goals") else
            " First goal of the season." if f["scorer_season_goals"] == 1 else
            f" Goal number {f['scorer_season_goals']} this season."),
        "big_chance": f"Big chance for {trig.team}: shot quality {f.get('shot_quality')}.",
        "control_swing": (f"{trig.team} have seized control. Control score up from "
                          f"{f.get('control_from')} to {f.get('control_to')}."),
        "pressing_spell": (f"{trig.team}'s press is breaking the opponent's rhythm. "
                           f"{f.get('turnovers_forced_5min')} turnovers in 5 minutes."),
        "speed_milestone": f"Rocket from {trig.player}: {f.get('shot_speed_kmh')} km/h.",
        "foul": (f"{trig.player} is shown a {f.get('card')} card for {f.get('foul_type')} "
                f"against {trig.team}. Free kick to {f.get('fouled_team')}."),
        "pass_quality": (f"{trig.player} threads a {f.get('pass_distance_m')}m pass for "
                         f"{trig.team}{' under pressure' if f.get('under_pressure') else ''} "
                         f"(difficulty {f.get('pass_difficulty')})."),
    }[trig.kind]
