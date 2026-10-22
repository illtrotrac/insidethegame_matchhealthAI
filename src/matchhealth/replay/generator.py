"""Seeded synthetic match generator.

Produces a football-realistic event stream (~1,500-1,900 events) with a
narrative arc: team strengths drift over time and pressing phases are
injected so the engine has real momentum swings to detect.

All team and player names are fictional.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

from matchhealth.shared.models import MatchEvent

PITCH_X, PITCH_Y = 105.0, 68.0


@dataclass
class Team:
    name: str
    players: list[str]
    attacking_right: bool  # first half direction
    strength: float = 0.5


@dataclass
class Phase:
    """A period where one team presses hard (raises turnovers against the other)."""

    start: float
    end: float
    pressing_team: str
    intensity: float = 0.25


DEFAULT_TEAMS = (
    Team("Riverside FC", [
        "A. Okafor", "L. Brandt", "M. Silva", "J. Kowalski", "T. Reyes", "K. Haddad",
        "S. Lindqvist", "D. Mensah", "R. Takeda", "E. Novak", "C. Duarte",
    ], attacking_right=True, strength=0.55),
    Team("Northgate United", [
        "P. Varga", "H. Osei", "N. Petrov", "G. Moreau", "I. Santos", "B. Achterberg",
        "F. Kamara", "O. Castillo", "Y. Park", "V. Ricci", "Z. Adeyemi",
    ], attacking_right=False, strength=0.45),
)


@dataclass
class MatchConfig:
    seed: int = 7
    teams: tuple[Team, Team] = DEFAULT_TEAMS
    phases: list[Phase] = field(default_factory=lambda: [
        Phase(1500, 1860, "Northgate United", 0.22),
        Phase(3600, 3960, "Riverside FC", 0.30),
    ])


def generate_match(cfg: MatchConfig | None = None) -> list[MatchEvent]:
    cfg = cfg or MatchConfig()
    rng = random.Random(cfg.seed)
    home, away = cfg.teams
    events: list[MatchEvent] = []
    eid = 0

    def emit(**kw) -> None:
        nonlocal eid
        eid += 1
        events.append(MatchEvent(id=eid, **kw))

    def attack_x(team: Team, t: float, x: float) -> float:
        """Distance toward the opponent goal, 0..105, regardless of half."""
        right = team.attacking_right if t < 2700 else not team.attacking_right
        return x if right else PITCH_X - x

    def pressing_against(team: Team, t: float) -> float:
        return sum(p.intensity for p in cfg.phases
                   if p.start <= t < p.end and p.pressing_team != team.name)

    for half_start, half_end in ((0.0, 2700.0), (2700.0, 5400.0)):
        t = half_start
        in_poss = home if half_start == 0 else away
        emit(t=t, type="kickoff", team=in_poss.name)
        x, y = PITCH_X / 2, PITCH_Y / 2

        while t < half_end:
            press = pressing_against(in_poss, t)
            opp = away if in_poss is home else home
            carrier = rng.choice(in_poss.players[1:])

            if rng.random() < 0.18 + press:
                t += rng.uniform(0.5, 2)
                emit(t=t, type="pressure", team=opp.name, player=rng.choice(opp.players[1:]),
                     x=round(x, 1), y=round(y, 1))

            depth = attack_x(in_poss, t, x)
            # Shot when deep in the final third
            if depth > 82 and rng.random() < 0.22:
                t += rng.uniform(1, 3)
                dist = math.hypot(PITCH_X - depth, y - PITCH_Y / 2)
                r = rng.random()
                outcome = "on_target" if r < 0.35 else "blocked" if r < 0.55 else "off_target"
                emit(t=t, type="shot", team=in_poss.name, player=carrier, x=round(x, 1),
                     y=round(y, 1), outcome=outcome,
                     speed_kmh=round(rng.gauss(95, 15) - dist * 0.6, 1))
                if outcome == "on_target" and rng.random() < 0.28 + 0.1 * in_poss.strength:
                    emit(t=t + 1, type="goal", team=in_poss.name, player=carrier)
                    in_poss, x, y = opp, PITCH_X / 2, PITCH_Y / 2
                    t += 45
                    emit(t=t, type="kickoff", team=in_poss.name)
                    continue
                in_poss, x, y = opp, (5 if depth > 52 else 100), PITCH_Y / 2
                continue

            # Pass
            length = max(3.0, rng.gauss(16, 8))
            angle = rng.uniform(-1.1, 1.1)
            right = in_poss.attacking_right if t < 2700 else not in_poss.attacking_right
            forward = 1 if right else -1
            nx = min(max(x + forward * length * math.cos(angle), 1), PITCH_X - 1)
            ny = min(max(y + length * math.sin(angle), 1), PITCH_Y - 1)
            p_success = 0.84 + 0.1 * (in_poss.strength - 0.5) - 0.004 * max(0, length - 15) - press
            t += rng.uniform(2, 5)
            ok = rng.random() < p_success
            emit(t=t, type="pass", team=in_poss.name, player=carrier, x=round(x, 1),
                 y=round(y, 1), end_x=round(nx, 1), end_y=round(ny, 1),
                 outcome="success" if ok else "fail",
                 speed_kmh=round(max(20, rng.gauss(45 + length, 8)), 1))
            if ok:
                x, y = nx, ny
                continue

            # Turnover: sometimes via a tackle
            if rng.random() < 0.4:
                emit(t=t + 0.5, type="tackle", team=opp.name, player=rng.choice(opp.players[1:]),
                     x=round(nx, 1), y=round(ny, 1), outcome="won")
            emit(t=t + 0.6, type="possession_change", team=opp.name, x=round(nx, 1), y=round(ny, 1))
            in_poss, x, y = opp, nx, ny

        emit(t=half_end, type="half_time" if half_end < 5400 else "full_time", team=home.name)

    return events
