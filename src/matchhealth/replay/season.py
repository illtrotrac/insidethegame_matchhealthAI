"""Season-so-far context for the live match: simulates every fixture before
the live matchweek with the same generator, then summarises it into a
league table, form guide and top scorers. Deterministic, no LLM, ~1s.

This is the factual ground truth that storylines may cite ("unbeaten in
four", "six goals this season") -- agents never invent season history.
"""

from __future__ import annotations

from collections import Counter

from matchhealth.engine.stats import shot_quality
from matchhealth.replay.generator import MatchConfig, Team, generate_match
from matchhealth.replay.league import CLUBS, LEAGUE, schedule


def _result_seed(seed: int, week: int, idx: int) -> int:
    return seed * 1000 + week * 10 + idx


def _summarise(events, home: Team, away: Team) -> dict:
    goals: Counter[str] = Counter()
    scorers: Counter[tuple[str, str]] = Counter()
    xg: dict[str, float] = {home.name: 0.0, away.name: 0.0}
    attack_right = {home.name: home.attacking_right, away.name: away.attacking_right}
    for ev in events:
        if ev.type == "goal":
            goals[ev.team] += 1
            scorers[(ev.player, ev.team)] += 1
        elif ev.type == "shot":
            right = attack_right[ev.team] if ev.t < 2700 else not attack_right[ev.team]
            xg[ev.team] += shot_quality(ev, 105.0 if right else 0.0)
    return {"home": home.name, "away": away.name,
            "score": [goals[home.name], goals[away.name]],
            "xg": [round(xg[home.name], 2), round(xg[away.name], 2)], "scorers": scorers}


def season_context(seed: int, matchweek: int) -> dict:
    """Table, form and top scorers after matchweeks 1..matchweek-1."""
    table = {c.name: {"team": c.name, "style": c.style, "p": 0, "w": 0, "d": 0, "l": 0,
                      "gf": 0, "ga": 0, "xg_for": 0.0, "xg_against": 0.0, "pts": 0, "form": []}
             for c in LEAGUE}
    scorers: Counter[tuple[str, str]] = Counter()
    results = []
    for week, fixtures in enumerate(schedule()[:matchweek - 1]):
        for idx, (h, a) in enumerate(fixtures):
            home, away = Team.from_club(CLUBS[h], True), Team.from_club(CLUBS[a], False)
            cfg = MatchConfig(seed=_result_seed(seed, week, idx), teams=(home, away))
            r = _summarise(generate_match(cfg), home, away)
            scorers.update(r.pop("scorers"))
            results.append({**r, "matchweek": week + 1})
            for side, gf, ga, xf, xa in ((h, *r["score"], *r["xg"]),
                                         (a, *r["score"][::-1], *r["xg"][::-1])):
                row = table[side]
                outcome = "W" if gf > ga else "D" if gf == ga else "L"
                row["p"] += 1
                row[outcome.lower()] += 1
                row["gf"] += gf
                row["ga"] += ga
                row["xg_for"] = round(row["xg_for"] + xf, 2)
                row["xg_against"] = round(row["xg_against"] + xa, 2)
                row["pts"] += {"W": 3, "D": 1, "L": 0}[outcome]
                row["form"].append(outcome)

    ranked = sorted(table.values(), key=lambda r: (-r["pts"], -(r["gf"] - r["ga"]), -r["gf"]))
    for pos, row in enumerate(ranked, 1):
        row["pos"] = pos
        row["form"] = row["form"][-5:]  # most recent last
    return {
        "matchweek": matchweek,
        "table": ranked,
        "top_scorers": [{"player": p, "team": t, "goals": g}
                        for (p, t), g in scorers.most_common(10)],
        "player_goals": {p: g for (p, _t), g in scorers.items()},  # Narrator callbacks
        "results": results,
    }
