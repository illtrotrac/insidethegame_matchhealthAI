"""Seeded synthetic match generator.

Produces a football-realistic event stream (~1,500-2,000 events, ~25 shots,
~2-4 goals) with a narrative arc: each club's playing style (see league.py)
shapes pressure, tempo and pass length, and pressing spells are injected so
the engine has real momentum swings to detect.

All team and player names are fictional.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

from matchhealth.replay.league import (
    CLUBS,
    Club,
    fixture_for,
    lineup_for,
    matchweek_of,
    resolve_club,
)
from matchhealth.shared.models import MatchEvent

PITCH_X, PITCH_Y = 105.0, 68.0
SHOT_CHANCE = 0.02  # per possession step deep in the final third; tuned to ~25 shots/match


@dataclass
class Team:
    name: str
    players: list[str]
    attacking_right: bool  # first half direction
    strength: float = 0.5
    press: float = 0.5
    tempo: float = 0.5
    directness: float = 0.5
    style: str = ""
    bench: list[str] = field(default_factory=list)

    @classmethod
    def from_club(cls, club: Club, attacking_right: bool, matchweek: int = 0) -> Team:
        """matchweek > 0: that week's rotated XI and bench (league.lineup_for)."""
        xi, bench = (lineup_for(club.name, matchweek) if matchweek
                     else (list(club.players), list(club.bench)))
        return cls(club.name, xi, attacking_right, club.strength, club.press,
                   club.tempo, club.directness, club.style, bench)


@dataclass
class Phase:
    """A period where one team presses hard (raises turnovers against the other)."""

    start: float
    end: float
    pressing_team: str
    intensity: float = 0.25


def _pressing_phases(rng: random.Random, teams: tuple[Team, Team]) -> list[Phase]:
    """One spell per team per half for genuine pressers, one per match otherwise."""
    phases = []
    for team in teams:
        halves = (0, 2700) if team.press >= 0.6 else (rng.choice((0, 2700)),)
        for half in halves:
            start = half + rng.uniform(600, 2100)
            phases.append(Phase(round(start), round(start + rng.uniform(300, 420)),
                                team.name, round(0.10 + 0.22 * team.press, 2)))
    return phases


@dataclass
class MatchConfig:
    seed: int = 7
    teams: tuple[Team, Team] | None = None  # None: the seed picks a league fixture
    phases: list[Phase] | None = None       # None: derived from the teams' press styles
    home: str | None = None  # pick a fixture by (partial) club name instead of by seed
    away: str | None = None
    matchweek: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        rng = random.Random(f"phases-{self.seed}")
        if self.teams is None:
            if self.home or self.away:
                if not (self.home and self.away):
                    raise ValueError("Choose both a home and an away club")
                home, away = resolve_club(self.home), resolve_club(self.away)
                self.matchweek = matchweek_of(home, away)
            else:
                self.matchweek, home, away = fixture_for(self.seed)
            self.teams = (Team.from_club(CLUBS[home], True, self.matchweek),
                          Team.from_club(CLUBS[away], False, self.matchweek))
        if self.phases is None:
            self.phases = _pressing_phases(rng, self.teams)


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

    # Three substitutions per team between 55' and 85' (outfield only),
    # drawn up front so the rest of the stream stays reproducible per seed.
    subs = sorted((rng.uniform(3300, 5100), team) for team in (home, away)
                  for _ in range(min(3, len(team.bench))))

    came_on: set[str] = set()

    def make_subs(t: float) -> None:
        while subs and subs[0][0] <= t:
            at, team = subs.pop(0)
            # Outfield starters only: a substitute is never taken back off.
            off_i = rng.choice([i for i in range(1, len(team.players))
                                if team.players[i] not in came_on])
            on = team.bench.pop(0)
            came_on.add(on)
            emit(t=round(at, 1), type="substitution", team=team.name, player=on,
                 player_off=team.players[off_i])
            team.players[off_i] = on

    for half_start, half_end in ((0.0, 2700.0), (2700.0, 5400.0)):
        t = half_start
        in_poss = home if half_start == 0 else away
        emit(t=t, type="kickoff", team=in_poss.name)
        x, y = PITCH_X / 2, PITCH_Y / 2

        while t < half_end:
            make_subs(t)
            opp = away if in_poss is home else home
            press = pressing_against(in_poss, t)
            carrier = rng.choice(in_poss.players[1:])

            if rng.random() < 0.08 + 0.18 * opp.press + press:
                t += rng.uniform(0.5, 2)
                emit(t=t, type="pressure", team=opp.name, player=rng.choice(opp.players[1:]),
                     x=round(x, 1), y=round(y, 1))

            depth = attack_x(in_poss, t, x)
            # Shot when deep in the final third
            if depth > 82 and rng.random() < SHOT_CHANCE + 0.03 * in_poss.strength:
                t += rng.uniform(1, 3)
                dist = math.hypot(PITCH_X - depth, y - PITCH_Y / 2)
                r = rng.random()
                outcome = "on_target" if r < 0.35 else "blocked" if r < 0.55 else "off_target"
                emit(t=t, type="shot", team=in_poss.name, player=carrier, x=round(x, 1),
                     y=round(y, 1), outcome=outcome,
                     speed_kmh=round(rng.gauss(95, 15) - dist * 0.6, 1))
                if outcome == "on_target" and rng.random() < 0.18 + 0.3 * in_poss.strength:
                    emit(t=t + 1, type="goal", team=in_poss.name, player=carrier)
                    in_poss, x, y = opp, PITCH_X / 2, PITCH_Y / 2
                    t += 45
                    emit(t=t, type="kickoff", team=in_poss.name)
                    continue
                in_poss, x, y = opp, (5 if depth > 52 else 100), PITCH_Y / 2
                continue

            # Pass: direct sides go longer, quick sides move it sooner
            length = max(3.0, rng.gauss(10 + 12 * in_poss.directness, 8))
            angle = rng.uniform(-1.1, 1.1)
            right = in_poss.attacking_right if t < 2700 else not in_poss.attacking_right
            forward = 1 if right else -1
            nx = min(max(x + forward * length * math.cos(angle), 1), PITCH_X - 1)
            ny = min(max(y + length * math.sin(angle), 1), PITCH_Y - 1)
            p_success = (0.84 + 0.1 * (in_poss.strength - 0.5) - 0.004 * max(0, length - 15)
                         - 0.04 * (opp.press - 0.5) - press)
            t += rng.uniform(2, 5) * (1.25 - 0.5 * in_poss.tempo)
            ok = rng.random() < p_success
            emit(t=t, type="pass", team=in_poss.name, player=carrier, x=round(x, 1),
                 y=round(y, 1), end_x=round(nx, 1), end_y=round(ny, 1),
                 outcome="success" if ok else "fail",
                 speed_kmh=round(max(20, rng.gauss(45 + length, 8)), 1))
            if ok:
                x, y = nx, ny
                continue

            # Foul: ref stops play. Fouled team (in_poss) keeps the ball via
            # a free kick -- no turnover this time. Occasionally a card.
            if rng.random() < 0.09:
                severity = rng.random()
                card = "red" if severity > 0.985 else "yellow" if severity > 0.85 else "clean"
                emit(t=t + 0.5, type="foul", team=opp.name, player=rng.choice(opp.players[1:]),
                     x=round(nx, 1), y=round(ny, 1), outcome=card)
                continue

            # Turnover: sometimes via a tackle
            if rng.random() < 0.4:
                emit(t=t + 0.5, type="tackle", team=opp.name, player=rng.choice(opp.players[1:]),
                     x=round(nx, 1), y=round(ny, 1), outcome="won")
            emit(t=t + 0.6, type="possession_change", team=opp.name, x=round(nx, 1), y=round(ny, 1))
            in_poss, x, y = opp, nx, ny

        emit(t=half_end, type="half_time" if half_end < 5400 else "full_time", team=home.name)

    return events
