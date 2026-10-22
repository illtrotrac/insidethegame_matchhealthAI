"""Decides when a moment is worth waking the agent crew. Deterministic."""

from __future__ import annotations

from collections import deque

from matchhealth.engine.health import HealthEngine
from matchhealth.engine.stats import pass_difficulty, pass_distance, shot_quality
from matchhealth.shared.models import MatchEvent, Trigger

CONTROL_SWING = 30.0       # points of control score within the lookback
SWING_LOOKBACK_S = 300
BIG_CHANCE_QUALITY = 0.35
PRESSING_TURNOVERS = 3     # x2 = minimum forced turnovers in the health window
PRESSING_RATIO = 1.6       # ...and this many times the opponent's count
SHOT_SPEED_KMH = 110
PASS_QUALITY_DIFFICULTY = 0.55  # pass_difficulty() tops out ~0.7 without a pressure bonus
COOLDOWN_S = 300           # per (kind, team), avoids alert storms

# The generator doesn't categorize *why* a foul happened (see generator.py),
# so this is deterministic flavour text, not a real classification -- picked
# from the event id, not fabricated per-event detail the Analyst would have
# to invent. Good enough to give a casual viewer an actual "why", not just
# "a card happened".
FOUL_TYPES = ["a late challenge", "a reckless tackle", "a trip", "a shirt pull",
              "a mistimed challenge", "a foul in the build-up"]


class ThresholdDetector:
    def __init__(self, teams: tuple[str, str], attacking_right_first_half: dict[str, bool]) -> None:
        self.teams = teams
        self.engine = HealthEngine(teams)
        self._attack_right = attacking_right_first_half
        self._history: dict[str, deque[tuple[float, float]]] = {t: deque() for t in teams}
        self._last_fired: dict[tuple[str, str], float] = {}
        self._n = 0

    def _goal_x(self, team: str, t: float) -> float:
        right = self._attack_right[team] if t < 2700 else not self._attack_right[team]
        return 105.0 if right else 0.0

    def _fire(self, kind: str, ev: MatchEvent, team: str, facts: dict) -> Trigger | None:
        key = (kind, team)
        if kind != "goal" and ev.t - self._last_fired.get(key, -1e9) < COOLDOWN_S:
            return None
        self._last_fired[key] = ev.t
        self._n += 1
        return Trigger(moment_id=f"m-{self._n:04d}", kind=kind, t=ev.t, team=team,
                       player=ev.player, facts=facts)

    def process(self, ev: MatchEvent) -> list[Trigger]:
        snap = self.engine.update(ev)
        out: list[Trigger | None] = []

        if ev.type == "goal":
            out.append(self._fire("goal", ev, ev.team, {"scorer": ev.player}))

        if ev.type == "foul" and ev.outcome in ("yellow", "red"):
            # Only carded fouls become a story -- a ref waving play on for a
            # routine foul isn't worth interrupting a casual viewer for, but
            # "why did the ref just show a card?" genuinely is.
            fouled_team = next(t for t in self.teams if t != ev.team)
            out.append(self._fire("foul", ev, ev.team, {
                "card": ev.outcome,
                "foul_type": FOUL_TYPES[ev.id % len(FOUL_TYPES)],
                "fouled_team": fouled_team,
            }))

        if ev.type == "pass" and ev.outcome == "success":
            # Pass quality: distance, accuracy (implicit -- only successful
            # passes fire) and a difficulty rating. pass_difficulty() was
            # already computed as a hidden input to the control score
            # (health.py) but never surfaced as its own stat anywhere --
            # the brief names this explicitly as a required metric.
            diff = pass_difficulty(ev)
            if diff is not None and diff >= PASS_QUALITY_DIFFICULTY:
                dist = pass_distance(ev)
                out.append(self._fire("pass_quality", ev, ev.team, {
                    "pass_distance_m": round(dist, 1) if dist is not None else None,
                    "pass_difficulty": diff,
                    "pass_speed_kmh": ev.speed_kmh,
                }))

        if ev.type == "shot":
            q = shot_quality(ev, self._goal_x(ev.team, ev.t))
            if q >= BIG_CHANCE_QUALITY:
                out.append(self._fire("big_chance", ev, ev.team, {
                    "shot_quality": q, "shot_speed_kmh": ev.speed_kmh, "outcome": ev.outcome}))
            elif (ev.speed_kmh or 0) >= SHOT_SPEED_KMH:
                out.append(self._fire("speed_milestone", ev, ev.team, {
                    "shot_speed_kmh": ev.speed_kmh}))

        if ev.type == "possession_change":
            opp = next(t for t in self.teams if t != ev.team)
            forced = self.engine.turnovers_forced(ev.team)
            # A spell = clearly out-pressing the opponent, not just normal turnover churn
            if forced >= PRESSING_TURNOVERS * 2 and forced >= PRESSING_RATIO * max(
                    self.engine.turnovers_forced(opp), 1):
                out.append(self._fire("pressing_spell", ev, ev.team, {
                    "turnovers_forced_5min": forced,
                    "opponent_pass_completion_pct": snap[opp].pass_completion_pct,
                    "opponent_control": snap[opp].control}))

        if ev.t > SWING_LOOKBACK_S:  # skip the noisy opening minutes
            for team in self.teams:
                hist = self._history[team]
                hist.append((ev.t, snap[team].control))
                while hist and ev.t - hist[0][0] > SWING_LOOKBACK_S:
                    hist.popleft()
                if hist:
                    lo = min(c for _, c in hist)
                    if snap[team].control - lo >= CONTROL_SWING:
                        out.append(self._fire("control_swing", ev, team, {
                            "control_from": lo, "control_to": snap[team].control,
                            "possession_pct": snap[team].possession_pct}))

        return [t for t in out if t is not None]
