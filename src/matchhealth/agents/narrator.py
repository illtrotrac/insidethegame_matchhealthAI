"""The Narrator: the crew's fifth agent. Owns the match-long story.

The other four agents each see one moment. The Narrator works across all of
them, reading the shared state they write:
  - pre-match storylines from the season-so-far facts (season.py),
  - enrich(): adds season context to triggers *before* the Analyst sees them
    (e.g. a scorer's season tally), so callbacks are facts, never invented,
  - "story so far" checkpoints at 15', half-time and 60',
  - the full-time recap.

Every piece is written for all personas in ONE call (like the Personaliser).
A deterministic text is always built from the same facts first: it's the
mock-mode output and the fallback if the model times out or returns a bad
shape -- the story panel is never blank.
"""

from __future__ import annotations

import asyncio
import logging
from collections import Counter
from collections.abc import Awaitable, Callable

from matchhealth.agents.llm import LLMClient, load_prompt, mock_enabled
from matchhealth.shared.models import Trigger, clock
from matchhealth.shared.state import StateStore

log = logging.getLogger(__name__)

NARRATOR_TIMEOUT_S = 20.0
CHECKPOINTS = [(900, "15'"), (3600, "60'")]  # half-time is driven by the half_time event
STANDOUT_WEIGHT = {"goal": 3, "big_chance": 2, "pass_quality": 1, "speed_milestone": 1}

Send = Callable[[dict], Awaitable[None]]


class Narrator:
    def __init__(self, store: StateStore, llm: LLMClient | None, personas: list[dict],
                 fixture: dict, season: dict, send: Send | None = None) -> None:
        self.store, self.llm, self.send = store, llm, send
        self.keys = [f"{p.get('mode', 'base')}-{p.get('language', 'en')}" for p in personas]
        self.fixture, self.season = fixture, season
        self.log: list[dict] = []  # everything published, for viewers who join late
        self._live_goals: Counter[str] = Counter()

    # --- enrichment: deterministic handoff into the crew's shared state ----

    def enrich(self, trig: Trigger) -> None:
        """Add season context to a trigger in place, before the Analyst runs."""
        if trig.kind == "goal" and trig.facts.get("scorer"):
            scorer = trig.facts["scorer"]
            self._live_goals[scorer] += 1
            trig.facts["scorer_season_goals"] = (
                self.season.get("player_goals", {}).get(scorer, 0) + self._live_goals[scorer])

    # --- the three narrative tasks ------------------------------------------

    async def pre_match(self) -> dict:
        return await self._write("n-pre-match", "pre_match", "Pre-match", 0.0,
                                 self._pre_match_facts(), "mini")

    async def checkpoint(self, label: str, t: float, live: dict) -> dict:
        facts = {"label": label, **self._live_facts(t, live)}
        slug = label.lower().replace("'", "").replace("-", "")
        return await self._write(f"n-{slug}", "checkpoint", label, t, facts, "nano")

    async def recap(self, live: dict) -> dict:
        facts = self._live_facts(5400.0, live, full=True)
        return await self._write("n-recap", "recap", "Full time", 5400.0, facts, "mini")

    async def _write(self, doc_id: str, kind: str, label: str, t: float, facts: dict,
                     tier: str) -> dict:
        variants = {k: RENDER[kind](facts, *k.split("-", 1)) for k in self.keys}
        recovery = None
        if not (mock_enabled() or self.llm is None):
            try:
                data = await asyncio.wait_for(self.llm.complete_json(
                    load_prompt("narrator"),
                    {"task": kind, "personas": self.keys, "facts": facts}, tier),
                    NARRATOR_TIMEOUT_S)
                got = _validated(data, self.keys)
                missing = [k for k in self.keys if k not in got]
                variants.update(got)
                if missing:
                    recovery = {"reason": "incomplete", "missing": missing}
            except Exception as exc:  # timeout, bad JSON
                recovery = {"reason": type(exc).__name__}
            if recovery:
                log.warning("narrative %s: using fallback text (%s)", doc_id, recovery)

        item = {"id": doc_id, "kind": kind, "label": label, "show_at": clock(t),
                "variants": variants}
        self.store.put(doc_id, "facts", facts)
        self.store.put(doc_id, "narrator", item)
        if recovery:
            self.store.put(doc_id, "recovery", recovery)
        self.log.append(item)
        if self.send:
            await self.send({"narrative": item})
        return item

    # --- facts: the only numbers the model may cite ------------------------

    def _pre_match_facts(self) -> dict:
        rows = {r["team"]: r for r in self.season["table"]}
        home, away = self.fixture["home"], self.fixture["away"]

        def team(name: str) -> dict:
            r = rows[name]
            scorer = next((s for s in self.season["top_scorers"] if s["team"] == name), None)
            return {"team": name, "style": r["style"], "position": r["pos"], "points": r["pts"],
                    "form": "".join(r["form"]), "goals_for": r["gf"], "goals_against": r["ga"],
                    "xg_for": r["xg_for"], "xg_against": r["xg_against"],
                    "unbeaten_run": _trailing(r["form"], "WD"),
                    "winless_run": _trailing(r["form"], "DL"), "top_scorer": scorer}

        prev = next((r for r in self.season.get("results", [])
                     if r["home"] == away and r["away"] == home), None)
        return {"matchweek": self.fixture["matchweek"], "home": team(home), "away": team(away),
                "previous_meeting": prev and {"home": prev["home"], "away": prev["away"],
                                              "score": prev["score"]}}

    def _live_facts(self, t: float, live: dict, full: bool = False) -> dict:
        home, away = self.fixture["home"], self.fixture["away"]
        moments = sorted(
            ({"t": m["trigger"]["t"], "clock": m["producer"]["show_at"],
              "kind": m["trigger"]["kind"], "team": m["trigger"]["team"],
              "player": m["trigger"].get("player"), "headline": m["producer"]["headline"]}
             for m in self.store.moments() if "producer" in m and m["trigger"]["t"] <= t),
            key=lambda m: m["t"])
        facts = {
            "clock": clock(t), "home": home, "away": away,
            "score": [live["score"][home], live["score"][away]],
            "control": [live["control"][home], live["control"][away]],
            "xg": [live["ratings"][home]["xg"], live["ratings"][away]["xg"]],
            "shots": [live["ratings"][home]["shots"], live["ratings"][away]["shots"]],
            "moments": [{k: v for k, v in m.items() if k != "t"}
                        for m in (moments if full else moments[-10:])],
            "storylines": next((i["variants"].get("casual-en", {}).get("lines")
                                for i in self.log if i["kind"] == "pre_match"), None),
        }
        if full:
            facts["goals"] = [{"player": m["player"], "team": m["team"], "clock": m["clock"]}
                              for m in moments if m["kind"] == "goal"]
            weights: Counter[tuple[str, str]] = Counter()
            for m in moments:
                if m["player"] and m["kind"] in STANDOUT_WEIGHT:
                    weights[(m["player"], m["team"])] += STANDOUT_WEIGHT[m["kind"]]
            facts["standout_player"] = (
                {"player": weights.most_common(1)[0][0][0], "team": weights.most_common(1)[0][0][1]}
                if weights else None)
            facts["table_position_after"] = _positions_after(
                self.season["table"], home, away, *facts["score"])
        return facts


# --- validation ---------------------------------------------------------------

def _validated(data: dict, keys: list[str]) -> dict:
    out = {}
    variants = data.get("variants") if isinstance(data, dict) else None
    for k in keys:
        v = (variants or {}).get(k)
        if (isinstance(v, dict) and isinstance(v.get("title"), str)
                and isinstance(v.get("lines"), list) and v["lines"]
                and all(isinstance(line, str) for line in v["lines"])):
            out[k] = {"title": v["title"][:80], "lines": [line[:240] for line in v["lines"][:4]]}
    return out


def _trailing(form: list[str], allowed: str) -> int:
    n = 0
    for result in reversed(form):
        if result not in allowed:
            break
        n += 1
    return n


def _positions_after(table: list[dict], home: str, away: str, h: int, a: int) -> dict:
    rows = {r["team"]: dict(r) for r in table}
    for team, gf, ga in ((home, h, a), (away, a, h)):
        rows[team]["pts"] += 3 if gf > ga else 1 if gf == ga else 0
        rows[team]["gf"] += gf
        rows[team]["ga"] += ga
    ranked = sorted(rows.values(), key=lambda r: (-r["pts"], -(r["gf"] - r["ga"]), -r["gf"]))
    pos = {r["team"]: i for i, r in enumerate(ranked, 1)}
    return {home: pos[home], away: pos[away]}


# --- deterministic texts (mock mode + fallback) ---------------------------------
# Same facts as the model gets, rendered per mode ("casual" | "analyst") and
# language ("en" | "es"). Other languages fall back to English.

def _ord(n: int, lang: str) -> str:
    return f"{n}.º" if lang == "es" else {1: "1st", 2: "2nd", 3: "3rd"}.get(n, f"{n}th")


KIND_TEXT = {
    "en": {"goal": "goal", "big_chance": "big chance", "control_swing": "momentum swing",
           "pressing_spell": "pressing spell", "speed_milestone": "thunderbolt shot",
           "foul": "card", "pass_quality": "pass under pressure"},
    "es": {"goal": "gol", "big_chance": "gran ocasión", "control_swing": "cambio de dominio",
           "pressing_spell": "fase de presión", "speed_milestone": "disparo potentísimo",
           "foul": "tarjeta", "pass_quality": "pase bajo presión"},
}
CHECKPOINT_LABEL_ES = {"15'": "Minuto 15", "Half-time": "Descanso", "60'": "Minuto 60"}


def _pre_match_text(f: dict, mode: str, lang: str) -> dict:
    es, analyst = lang == "es", mode == "analyst"
    H, A = f["home"], f["away"]
    gap = abs(H["points"] - A["points"])
    lines = []
    if analyst:
        def table_line(T: dict) -> str:
            if es:
                return (f"{T['team']}: {_ord(T['position'], lang)} con {T['points']} pts "
                        f"(xG {T['xg_for']:.1f} a favor, {T['xg_against']:.1f} en contra).")
            return (f"{T['team']}: {_ord(T['position'], lang)} on {T['points']} pts "
                    f"(xG {T['xg_for']:.1f} for, {T['xg_against']:.1f} against).")
        lines.append(f"{table_line(H)} {table_line(A)}")
    elif es:
        lines.append(f"{H['team']} ({_ord(H['position'], lang)}) recibe a {A['team']} "
                     f"({_ord(A['position'], lang)}); les separa{'n' if gap != 1 else ''} "
                     f"{gap} punto{'s' if gap != 1 else ''}.")
    else:
        lines.append(f"{H['team']} ({_ord(H['position'], lang)}) host {A['team']} "
                     f"({_ord(A['position'], lang)}), {gap} point{'s' if gap != 1 else ''} "
                     f"apart in the table.")

    runs = [(T["unbeaten_run"], "unbeaten", T) for T in (H, A) if T["unbeaten_run"] >= 3]
    runs += [(T["winless_run"], "winless", T) for T in (H, A) if T["winless_run"] >= 3]
    if runs:
        n, what, T = max(runs, key=lambda r: r[0])
        lines.append({
            ("en", "unbeaten", False): f"{T['team']} are unbeaten in {n}. Can they keep it going?",
            ("en", "winless", False): f"{T['team']} haven't won in {n}. Something has to give.",
            ("en", "unbeaten", True): f"{T['team']}: unbeaten in {n} (form {T['form']}).",
            ("en", "winless", True): f"{T['team']}: winless in {n} (form {T['form']}).",
            ("es", "unbeaten", False): f"{T['team']} lleva {n} partidos sin perder. "
                                       f"¿Seguirá la racha?",
            ("es", "winless", False): f"{T['team']} suma {n} partidos sin ganar.",
            ("es", "unbeaten", True): f"{T['team']}: {n} sin perder (forma {T['form']}).",
            ("es", "winless", True): f"{T['team']}: {n} sin ganar (forma {T['form']}).",
        }[("es" if es else "en", what, analyst)])
    else:
        lines.append(f"{'Forma reciente' if es else 'Recent form'}: "
                     f"{H['team']} {H['form']}, {A['team']} {A['form']}.")

    scorers = [T["top_scorer"] for T in (H, A) if T["top_scorer"]]
    best = max(scorers, key=lambda s: s["goals"]) if scorers else None
    if best and best["goals"] >= 2:
        p, g, team = best["player"], best["goals"], best["team"]
        lines.append({
            ("en", False): f"Watch {p}: {g} goals this season for {team}.",
            ("en", True): f"{p} ({team}): {g} league goals so far.",
            ("es", False): f"Atención a {p}: {g} goles esta temporada con {team}.",
            ("es", True): f"{p} ({team}): {g} goles en liga.",
        }[("es" if es else "en", analyst)])
    elif es:
        lines.append(f"Choque de estilos entre {H['team']} y {A['team']}.")
    else:
        lines.append(f"Style clash: {H['style'].lower()} vs {A['style'].lower()}.")

    prev = f["previous_meeting"]
    if prev:
        s = prev["score"]
        lines.append(f"{'En la ida' if es else 'Earlier this season'}: "
                     f"{prev['home']} {s[0]}-{s[1]} {prev['away']}.")
    title = (f"Jornada {f['matchweek']}: las claves" if es
             else f"Matchweek {f['matchweek']}: the storylines")
    return {"title": title, "lines": lines}


def _score_line(f: dict, es: bool) -> str:
    (H, A), (h, a) = (f["home"], f["away"]), f["score"]
    if h == a:
        return f"Empate a {h}." if es else f"Still level at {h}-{a}."
    lead, (x, y) = (H, (h, a)) if h > a else (A, (a, h))
    return f"{lead} gana {x}-{y}." if es else f"{lead} lead {x}-{y}."


def _checkpoint_text(f: dict, mode: str, lang: str) -> dict:
    es, analyst = lang == "es", mode == "analyst"
    H, A, (h, a) = f["home"], f["away"], f["score"]
    kinds = KIND_TEXT["es" if es else "en"]
    lines = [_score_line(f, es)]
    goals = [m for m in f["moments"] if m["kind"] == "goal"]
    if goals:
        g = goals[-1]
        lines.append(f"Último gol: {g['player']} ({g['team']}) en el {g['clock']}." if es
                     else f"Latest goal: {g['player']} for {g['team']} at {g['clock']}.")
    elif f["moments"]:
        m = f["moments"][-1]
        lines.append(f"Última jugada clave: {kinds[m['kind']]} de {m['team']} en el {m['clock']}."
                     if es else
                     f"Latest key moment: {kinds[m['kind']]} for {m['team']} at {m['clock']}.")
    else:
        lines.append("Inicio tranquilo: aún sin jugadas clave." if es
                     else "A quiet start: no key moments yet.")
    (hc, ac), (hx, ax), (hs, as_) = f["control"], f["xg"], f["shots"]
    if analyst:
        lines.append(f"Control {hc:.0f}–{ac:.0f}, xG {hx:.2f}–{ax:.2f}, "
                     f"{'tiros' if es else 'shots'} {hs}–{as_}.")
    elif abs(hc - ac) >= 10:
        top = H if hc > ac else A
        lines.append(f"{top} domina el juego." if es else f"{top} have had more control.")
    else:
        lines.append("Ningún equipo se ha hecho con el control." if es
                     else "Neither side has taken control yet.")
    label = CHECKPOINT_LABEL_ES.get(f["label"], f["label"]) if es else f["label"]
    return {"title": f"{label}: {H} {h}-{a} {A}", "lines": lines}


def _recap_text(f: dict, mode: str, lang: str) -> dict:
    es, analyst = lang == "es", mode == "analyst"
    H, A, (h, a) = f["home"], f["away"], f["score"]
    (hc, ac), (hx, ax), (hs, as_) = f["control"], f["xg"], f["shots"]
    if analyst:
        lines = [f"{H} {h}-{a} {A}, xG {hx:.2f}–{ax:.2f}."]
    elif h > a:
        lines = [f"{H} se lleva los tres puntos." if es else f"{H} take all three points."]
    elif a > h:
        lines = [f"{A} gana a domicilio." if es else f"{A} win away from home."]
    else:
        lines = ["Reparto de puntos." if es else "The points are shared."]
    if f["goals"]:
        scorers = ", ".join(f"{g['player']} {g['clock']}" for g in f["goals"])
        lines.append(f"{'Goles' if es else 'Goals'}: {scorers}.")
    else:
        lines.append("Sin goles." if es else "No goals.")
    if analyst:
        lines.append(f"{'Tiros' if es else 'Shots'} {hs}–{as_}, "
                     f"{'control al final' if es else 'control at the whistle'} {hc:.0f}–{ac:.0f}.")
    elif f["standout_player"]:
        s = f["standout_player"]
        lines.append(f"{'Destacado' if es else 'Standout'}: {s['player']} ({s['team']}).")
    pos = f["table_position_after"]
    lines.append(f"Clasificación: {H} queda {_ord(pos[H], lang)}, {A} {_ord(pos[A], lang)}."
                 if es else
                 f"Table: {H} now {_ord(pos[H], lang)}, {A} {_ord(pos[A], lang)}.")
    return {"title": f"{'Final' if es else 'Full time'}: {H} {h}-{a} {A}", "lines": lines}


RENDER = {"pre_match": _pre_match_text, "checkpoint": _checkpoint_text, "recap": _recap_text}
