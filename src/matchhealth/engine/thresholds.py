"""Decides when a moment is worth waking the agent crew. Deterministic."""

from __future__ import annotations

from collections import deque

from matchhealth.engine.health import HealthEngine
from matchhealth.engine.stats import pass_difficulty, pass_distance, shot_quality
from matchhealth.shared.models import MatchEvent, Trigger

CONTROL_SWING = 40.0       # points of control score within the lookback (30 fired ~12x/match once
                           # realistic shot rates made possession spells longer)
SWING_LOOKBACK_S = 300
BIG_CHANCE_QUALITY = 0.35
PRESSING_TURNOVERS = 3     # x2 = minimum forced turnovers in the health window
PRESSING_RATIO = 1.6       # ...and this many times the opponent's count
SHOT_SPEED_KMH = 110
# pass_difficulty() tops out ~0.7 without the +0.3 pressure bonus, so in
# practice this fires only for hard passes completed under pressure (~6-12
# per match; 0.55 fired on nearly every pressured pass once pressure counted).
PASS_QUALITY_DIFFICULTY = 0.75
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
        self._last_xy: tuple[float | None, float | None] = (None, None)  # goals carry no x/y
        # Cumulative, match-long (not sliding-window) tallies for the
        # analyst-mode "Statistical Models" layer: attack/defense ratings and
        # win/draw/loss. xG here is literally sum(shot_quality) -- genuinely
        # the same idea as a real expected-goals model, just this project's
        # own quality proxy rather than a trained one.
        self._xg_for: dict[str, float] = {t: 0.0 for t in teams}
        self._shots_for: dict[str, int] = {t: 0 for t in teams}
        self._fouls_committed: dict[str, int] = {t: 0 for t in teams}
        # Shot map (analyst mode): every shot's real location, normalized so
        # "attacking goal" is always display_x=105 regardless of which half
        # or which actual end the team was shooting at -- lets both teams'
        # shots sit on one comparable diagram instead of split across a full
        # pitch by kickoff direction.
        self._shot_log: list[dict] = []

    def _goal_x(self, team: str, t: float) -> float:
        right = self._attack_right[team] if t < 2700 else not self._attack_right[team]
        return 105.0 if right else 0.0

    def _fire(self, kind: str, ev: MatchEvent, team: str, facts: dict) -> Trigger | None:
        key = (kind, team)
        if kind != "goal" and ev.t - self._last_fired.get(key, -1e9) < COOLDOWN_S:
            return None
        self._last_fired[key] = ev.t
        self._n += 1
        x, y = (ev.x, ev.y) if ev.x is not None else self._last_xy
        # Momentum and pressing are team stories: naming whoever happened to
        # touch the ball on the triggering event would mislead viewers.
        player = None if kind in ("control_swing", "pressing_spell") else ev.player
        return Trigger(moment_id=f"m-{self._n:04d}", kind=kind, t=ev.t, team=team,
                       player=player, facts=facts, x=x, y=y)

    def process(self, ev: MatchEvent) -> list[Trigger]:
        snap = self.engine.update(ev)
        out: list[Trigger | None] = []
        if ev.x is not None and ev.type != "goal":
            self._last_xy = (ev.x, ev.y)

        if ev.type == "goal":
            out.append(self._fire("goal", ev, ev.team, {"scorer": ev.player}))
            # Correlate to the shot that scored it (same team/player, within
            # a couple seconds -- the generator emits the goal event right
            # after its shot, see generator.py) so the shot map can mark it.
            for rec in reversed(self._shot_log):
                if (rec["team"] == ev.team and rec["player"] == ev.player
                        and 0 <= ev.t - rec["t"] <= 3):
                    rec["is_goal"] = True
                    break

        if ev.type == "foul":
            self._fouls_committed[ev.team] += 1
            if ev.outcome in ("yellow", "red"):
                # Only carded fouls become a story -- a ref waving play on
                # for a routine foul isn't worth interrupting a casual
                # viewer for, but "why did the ref just show a card?"
                # genuinely is. (Discipline still counts every foul above,
                # carded or not, for the defense rating.)
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
            pressured = self.engine.under_pressure(ev)
            diff = pass_difficulty(ev, pressured)
            if diff is not None and diff >= PASS_QUALITY_DIFFICULTY:
                dist = pass_distance(ev)
                out.append(self._fire("pass_quality", ev, ev.team, {
                    "pass_distance_m": round(dist, 1) if dist is not None else None,
                    "pass_difficulty": diff,
                    "pass_speed_kmh": ev.speed_kmh,
                    "under_pressure": pressured,
                }))

        if ev.type == "shot":
            goal_x = self._goal_x(ev.team, ev.t)
            q = shot_quality(ev, goal_x)
            self._xg_for[ev.team] += q
            self._shots_for[ev.team] += 1
            display_x = ev.x if goal_x == 105.0 else (105.0 - (ev.x or 0))
            self._shot_log.append({
                "team": ev.team, "player": ev.player, "t": ev.t,
                "display_x": display_x, "y": ev.y, "outcome": ev.outcome,
                "xg": q, "is_goal": False,
            })
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

    def shots(self) -> list[dict]:
        return list(self._shot_log)

    def match_stats(self, t: float) -> dict[str, dict]:
        """Cumulative (whole-match, not sliding-window) attack/defense ratings
        for analyst mode. Deterministic heuristic from accumulated xG created
        (attack) and xG conceded + fouls committed (defense), prorated to a
        per-90 basis so the ratings are comparable throughout the match, not
        just at full time.
        """
        minutes = max(t / 60, 1.0)
        # Capped at 4x: projecting straight to "per 90" from the first few
        # minutes of a match wildly amplifies small-sample noise (a couple of
        # early shots can swing a rating to the extreme) -- the cap keeps
        # early-match ratings directionally meaningful without that whiplash.
        scale = min(90 / minutes, 4.0)
        out = {}
        for team in self.teams:
            opp = next(t2 for t2 in self.teams if t2 != team)
            xg_for_90 = self._xg_for[team] * scale
            xg_against_90 = self._xg_for[opp] * scale
            fouls_90 = self._fouls_committed[team] * scale
            out[team] = {
                "xg": round(self._xg_for[team], 2),
                "shots": self._shots_for[team],
                "attack": round(min(100, 10 * xg_for_90), 1),
                "defense": round(max(0, 100 - 10 * xg_against_90 - 0.4 * fouls_90), 1),
            }
        return out
