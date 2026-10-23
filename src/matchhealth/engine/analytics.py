"""Analyst-mode numbers: pressing (PPDA), field tilt, touch zones and
per-player passing, defending and shooting. Deterministic; no LLM.

Everything here is computed from the same synthetic events the engine
already sees, so the charts never show anything the match didn't produce.
"""

from __future__ import annotations

from matchhealth.engine.health import HealthEngine
from matchhealth.engine.stats import pass_difficulty, shot_quality
from matchhealth.shared.models import MatchEvent

BUCKET_S = 900          # 15-minute blocks
BUCKETS = 6
DEF_ACTIONS = {"tackle", "pressure", "foul"}
FINAL_THIRD_X = 70.0    # metres toward the opponent goal
PROGRESSIVE_M = 10.0    # a completed pass that gains this much ground toward goal
ZONE_COLS, ZONE_ROWS = 6, 3


class MatchAnalytics:
    def __init__(self, teams: tuple[str, str], attacking_right_first_half: dict[str, bool],
                 engine: HealthEngine) -> None:
        self.teams = teams
        self._right = attacking_right_first_half
        self._engine = engine  # for under_pressure(), so call update() after the engine has seen ev
        self.passes = {t: [0] * BUCKETS for t in teams}
        self.def_actions = {t: [0] * BUCKETS for t in teams}
        self.final_third = {t: [0] * BUCKETS for t in teams}
        self.zones = {t: [0] * (ZONE_COLS * ZONE_ROWS) for t in teams}
        self.players: dict[str, dict] = {}

    def _fwd(self, team: str, t: float, x: float) -> float:
        """Distance toward the opponent goal, whichever end the team attacks."""
        right = self._right[team] if t < 2700 else not self._right[team]
        return x if right else 105.0 - x

    def _player(self, ev: MatchEvent) -> dict:
        return self.players.setdefault(ev.player, {
            "team": ev.team, "attempts": 0, "completions": 0, "pressured_att": 0,
            "pressured_comp": 0, "progressive": 0, "difficulty": 0.0, "tackles": 0,
            "shots": 0, "xg": 0.0, "_diff_n": 0})

    def update(self, ev: MatchEvent) -> None:
        if ev.team not in self.passes:
            return
        b = min(int(ev.t // BUCKET_S), BUCKETS - 1)
        if ev.type in DEF_ACTIONS:
            self.def_actions[ev.team][b] += 1
        if ev.x is not None and ev.y is not None and ev.type in ("pass", "shot", "tackle"):
            col = min(int(self._fwd(ev.team, ev.t, ev.x) / (105 / ZONE_COLS)), ZONE_COLS - 1)
            row = min(int(ev.y / (68 / ZONE_ROWS)), ZONE_ROWS - 1)
            self.zones[ev.team][row * ZONE_COLS + col] += 1
        if ev.type == "pass":
            self.passes[ev.team][b] += 1
            if ev.end_x is not None and self._fwd(ev.team, ev.t, ev.end_x) > FINAL_THIRD_X:
                self.final_third[ev.team][b] += 1
        if not ev.player:
            return
        if ev.type == "pass":
            p = self._player(ev)
            ok = ev.outcome == "success"
            pressured = self._engine.under_pressure(ev)
            p["attempts"] += 1
            p["completions"] += ok
            p["pressured_att"] += pressured
            p["pressured_comp"] += pressured and ok
            diff = pass_difficulty(ev, pressured)
            if diff is not None:
                p["difficulty"] += diff
                p["_diff_n"] += 1
            if ok and ev.end_x is not None and (
                    self._fwd(ev.team, ev.t, ev.end_x) - self._fwd(ev.team, ev.t, ev.x)
                    >= PROGRESSIVE_M):
                p["progressive"] += 1
        elif ev.type == "tackle" and ev.outcome == "won":
            self._player(ev)["tackles"] += 1
        elif ev.type == "shot":
            p = self._player(ev)
            right = self._right[ev.team] if ev.t < 2700 else not self._right[ev.team]
            p["shots"] += 1
            p["xg"] += shot_quality(ev, 105.0 if right else 0.0)

    def player_payload(self) -> dict:
        out = {}
        for name, p in self.players.items():
            n = p["_diff_n"]
            out[name] = {**{k: v for k, v in p.items() if not k.startswith("_")},
                         "difficulty": round(p["difficulty"] / n, 2) if n else None,
                         "xg": round(p["xg"], 2)}
        return out

    def team_payload(self) -> dict:
        """Per 15-minute block: PPDA (opponent passes per defensive action,
        lower = fiercer press) and field tilt (share of final-third passes)."""
        a, b = self.teams
        opp = {a: b, b: a}
        ppda, tilt = {}, {}
        for t in self.teams:
            o = opp[t]
            ppda[t] = [round(self.passes[o][i] / self.def_actions[t][i], 1)
                       if self.def_actions[t][i] else None for i in range(BUCKETS)]
            tilt[t] = [round(100 * self.final_third[t][i]
                             / (self.final_third[t][i] + self.final_third[o][i]))
                       if self.final_third[t][i] + self.final_third[o][i] else None
                       for i in range(BUCKETS)]
        return {"ppda": ppda, "tilt": tilt, "zones": self.zones}
