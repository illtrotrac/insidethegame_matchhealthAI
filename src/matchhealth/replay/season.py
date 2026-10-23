"""Season-so-far context for the live match: simulates every fixture before
the live matchweek with the same generator, then summarises it into a
league table, form guide and top scorers. Deterministic, no LLM, ~1s.

This is the factual ground truth that storylines may cite ("unbeaten in
four", "six goals this season") -- agents never invent season history.
"""

from __future__ import annotations

from collections import Counter

from matchhealth.engine.analytics import MatchAnalytics
from matchhealth.engine.stats import shot_quality
from matchhealth.engine.thresholds import ThresholdDetector
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


def _recent_entry(events, club: Team, opp: Team, venue: str, week: int, xi: list[str],
                  score: list[int], players: dict) -> dict:
    """One past game from the club's side: line-up, who came on, passing."""
    return {"matchweek": week, "opponent": opp.name, "venue": venue, "score": score,
            "xi": xi, "subs_on": [e.player for e in events
                                  if e.type == "substitution" and e.team == club.name],
            "players": {n: {k: p[k] for k in ("attempts", "completions", "progressive")}
                        for n, p in players.items() if p["team"] == club.name}}


def season_context(seed: int, matchweek: int, focus: tuple[str, ...] = ()) -> dict:
    """Table, form and top scorers after matchweeks 1..matchweek-1, plus each
    focus club's last two games (line-ups and passing) for comparisons."""
    recent: dict[str, list] = {c: [] for c in focus}
    table = {c.name: {"team": c.name, "style": c.style, "p": 0, "w": 0, "d": 0, "l": 0,
                      "gf": 0, "ga": 0, "xg_for": 0.0, "xg_against": 0.0, "pts": 0, "form": []}
             for c in LEAGUE}
    scorers: Counter[tuple[str, str]] = Counter()
    results = []
    for week, fixtures in enumerate(schedule()[:matchweek - 1]):
        for idx, (h, a) in enumerate(fixtures):
            home = Team.from_club(CLUBS[h], True, week + 1)
            away = Team.from_club(CLUBS[a], False, week + 1)
            xis = {home.name: list(home.players), away.name: list(away.players)}
            cfg = MatchConfig(seed=_result_seed(seed, week, idx), teams=(home, away))
            events = generate_match(cfg)
            r = _summarise(events, home, away)
            if week >= matchweek - 3 and {h, a} & set(focus):  # the last two matchweeks
                ar = {home.name: home.attacking_right, away.name: away.attacking_right}
                det = ThresholdDetector((home.name, away.name), ar)
                an = MatchAnalytics((home.name, away.name), ar, det.engine)
                for ev in events:
                    det.process(ev)
                    an.update(ev)
                for club, opp, venue, sc in ((home, away, "H", r["score"]),
                                             (away, home, "A", r["score"][::-1])):
                    if club.name in recent:
                        recent[club.name].insert(0, _recent_entry(
                            events, club, opp, venue, week + 1, xis[club.name], sc,
                            an.player_payload()))
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
        "recent": recent,  # newest first
        "results": results,
    }
