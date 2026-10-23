"""Rolling 'match health' per team: control vs chaos over a sliding window."""

from __future__ import annotations

from collections import deque

from matchhealth.engine.stats import pass_difficulty
from matchhealth.shared.models import HealthSnapshot, MatchEvent

WINDOW_S = 300  # 5 minutes


class HealthEngine:
    def __init__(self, teams: tuple[str, str], window_s: float = WINDOW_S) -> None:
        self.teams = teams
        self.window_s = window_s
        self._events: deque[MatchEvent] = deque()
        # A pressure event (team = the pressing side) applies to the pressed
        # team's next pass -- the generator emits it immediately before that
        # pass in the same possession step (see generator.py).
        self._pressed: dict[str, bool] = {t: False for t in teams}
        self._pressured_pass_ids: set[int] = set()

    def update(self, ev: MatchEvent) -> dict[str, HealthSnapshot]:
        self._events.append(ev)
        while self._events and ev.t - self._events[0].t > self.window_s:
            self._pressured_pass_ids.discard(self._events.popleft().id)
        if ev.type == "pressure":
            pressed = self.teams[1] if ev.team == self.teams[0] else self.teams[0]
            self._pressed[pressed] = True
        elif ev.type == "pass" and ev.team in self._pressed:
            if self._pressed[ev.team]:
                self._pressured_pass_ids.add(ev.id)
            self._pressed[ev.team] = False
        elif ev.type == "possession_change":
            self._pressed = {t: False for t in self.teams}
        return self.snapshot()

    def under_pressure(self, ev: MatchEvent) -> bool:
        """Whether this pass (already passed to update()) was played under pressure."""
        return ev.id in self._pressured_pass_ids

    def snapshot(self) -> dict[str, HealthSnapshot]:
        passes = {t: [] for t in self.teams}
        turnovers_won = {t: 0 for t in self.teams}
        pressure = {t: 0 for t in self.teams}
        for e in self._events:
            if e.type == "pass" and e.team in passes:
                passes[e.team].append(e)
            elif e.type == "possession_change" and e.team in turnovers_won:
                turnovers_won[e.team] += 1
            elif e.type == "pressure" and e.team in pressure:
                pressure[e.team] += 1

        total_passes = sum(len(p) for p in passes.values()) or 1
        minutes = max(self.window_s / 60, 1)
        out = {}
        for team in self.teams:
            opp = self.teams[1] if team == self.teams[0] else self.teams[0]
            ps = passes[team]
            done = [p for p in ps if p.outcome == "success"]
            completion = len(done) / len(ps) if ps else 0.0
            avg_diff = (sum(pass_difficulty(p, p.id in self._pressured_pass_ids) or 0
                            for p in done) / len(done)) if done else 0.0
            possession = len(ps) / total_passes
            control = 100 * possession * (0.7 * completion + 0.3 * (0.5 + avg_diff))
            chaos = (turnovers_won[opp] + pressure[opp]) / minutes
            out[team] = HealthSnapshot(
                team=team,
                control=round(min(control * 1.6, 100), 1),
                chaos=round(chaos, 2),
                possession_pct=round(100 * possession, 1),
                pass_completion_pct=round(100 * completion, 1),
            )
        return out

    def turnovers_forced(self, team: str) -> int:
        return sum(1 for e in self._events if e.type == "possession_change" and e.team == team)
