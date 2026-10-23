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
from matchhealth.agents.mock_text import KINDS, NARRATIVE, POINTS, SEP, lang_of, ordinal
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

    async def brief(self, label: str, t: float, live: dict) -> dict:
        """Analyst chart briefing: the numbers behind the charts, in words.
        Analyst personas only; shown behind the Charts panel's summary button."""
        slug = label.lower().replace("'", "").replace("-", "").replace(" ", "")
        return await self._write(f"n-brief-{slug}", "brief", label, t,
                                 self._brief_facts(label, t, live), "nano",
                                 keys=[k for k in self.keys if k.startswith("analyst-")])

    async def recap(self, live: dict) -> dict:
        facts = self._live_facts(5400.0, live, full=True)
        return await self._write("n-recap", "recap", "Full time", 5400.0, facts, "mini")

    async def _write(self, doc_id: str, kind: str, label: str, t: float, facts: dict,
                     tier: str, keys: list[str] | None = None) -> dict:
        keys = keys or self.keys
        variants = {k: RENDER[kind](facts, *k.split("-", 1)) for k in keys}
        recovery = None
        if not (mock_enabled() or self.llm is None):
            try:
                data = await asyncio.wait_for(self.llm.complete_json(
                    load_prompt("narrator"),
                    {"task": kind, "personas": keys, "facts": facts}, tier),
                    NARRATOR_TIMEOUT_S)
                got = _validated(data, keys)
                missing = [k for k in keys if k not in got]
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

    def _brief_facts(self, label: str, t: float, live: dict) -> dict:
        home, away = self.fixture["home"], self.fixture["away"]
        an, players = live["analytics"], live["players"]

        def done(vals: list) -> list:
            return [v for v in vals if v is not None]

        def lead(key: str) -> dict | None:
            if not players:
                return None
            name, p = max(players.items(), key=lambda kv: kv[1][key])
            return {"player": name, "team": p["team"], "completions": p["completions"],
                    "attempts": p["attempts"], "progressive": p["progressive"]}

        return {
            "label": label, "clock": clock(t), "home": home, "away": away,
            "score": {n: live["score"][n] for n in (home, away)},
            "xg": {n: live["ratings"][n]["xg"] for n in (home, away)},
            "shots": {n: live["ratings"][n]["shots"] for n in (home, away)},
            "ppda_avg": {n: round(sum(done(an["ppda"][n])) / len(done(an["ppda"][n])), 1)
                         if done(an["ppda"][n]) else None for n in (home, away)},
            # The last *completed* 15-minute block: the current one may hold a few passes.
            "field_tilt_last_15": {n: an["tilt"][n][max(0, min(5, int(t // 900) - 1))]
                                   for n in (home, away)},
            "top_passer": lead("completions"), "top_progressive": lead("progressive"),
        }

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
            # Keyed by team, not [home, away] pairs: the model swapped pair order.
            "score": {n: live["score"][n] for n in (home, away)},
            "control_score_0_100": {n: live["control"][n] for n in (home, away)},
            "xg": {n: live["ratings"][n]["xg"] for n in (home, away)},
            "shots": {n: live["ratings"][n]["shots"] for n in (home, away)},
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
                self.season["table"], home, away, *_pair(facts, "score"))
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


def _pair(f: dict, key: str) -> tuple:
    return f[key][f["home"]], f[key][f["away"]]


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
# language from the hand-written templates in mock_text.py.


def _pre_match_text(f: dict, mode: str, lang: str) -> dict:
    lang = lang_of(lang)
    T, analyst = NARRATIVE[lang], mode == "analyst"
    H, A = f["home"], f["away"]
    gap = abs(H["points"] - A["points"])
    lines = []
    if analyst:
        lines.append(" ".join(T["pm_team"].format(
            team=X["team"], pos=ordinal(X["position"], lang), posn=X["position"], pts=X["points"],
            xf=f"{X['xg_for']:.1f}", xa=f"{X['xg_against']:.1f}") for X in (H, A)))
    else:
        lines.append(T["pm_table"].format(
            h=H["team"], hp=ordinal(H["position"], lang), a=A["team"],
            ap=ordinal(A["position"], lang), hpn=H["position"], apn=A["position"], gap=gap,
            points=POINTS[lang][gap != 1]))

    runs = [(X["unbeaten_run"], "unbeaten", X) for X in (H, A) if X["unbeaten_run"] >= 3]
    runs += [(X["winless_run"], "winless", X) for X in (H, A) if X["winless_run"] >= 3]
    if runs:
        n, what, X = max(runs, key=lambda r: r[0])
        lines.append(T[what + ("_a" if analyst else "")].format(team=X["team"], n=n,
                                                                 form=X["form"]))
    else:
        lines.append(T["form"].format(h=H["team"], hf=H["form"], a=A["team"], af=A["form"]))

    scorers = [X["top_scorer"] for X in (H, A) if X["top_scorer"]]
    best = max(scorers, key=lambda s: s["goals"]) if scorers else None
    if best and best["goals"] >= 2:
        lines.append(T["scorer_a" if analyst else "scorer"].format(
            p=best["player"], g=best["goals"], team=best["team"]))
    else:
        lines.append(T["clash"].format(h=H["team"], a=A["team"], hs=H["style"].lower(),
                                       as_=A["style"].lower()))

    prev = f["previous_meeting"]
    if prev:
        lines.append(T["prev"].format(home=prev["home"], away=prev["away"], s0=prev["score"][0],
                                      s1=prev["score"][1], sep=SEP[lang]))
    return {"title": T["pm_title"].format(mw=f["matchweek"]), "lines": lines}


def _checkpoint_text(f: dict, mode: str, lang: str) -> dict:
    lang = lang_of(lang)
    T, analyst, sep = NARRATIVE[lang], mode == "analyst", SEP[lang]
    H, A, (h, a) = f["home"], f["away"], _pair(f, "score")
    if h == a:
        lines = [T["level"].format(h=h, a=a, sep=sep)]
    else:
        lead, (x, y) = (H, (h, a)) if h > a else (A, (a, h))
        lines = [T["lead"].format(team=lead, x=x, y=y, sep=sep)]
    goals = [m for m in f["moments"] if m["kind"] == "goal"]
    if goals:
        g = goals[-1]
        lines.append(T["latest_goal"].format(p=g["player"], team=g["team"], clock=g["clock"]))
    elif f["moments"]:
        m = f["moments"][-1]
        lines.append(T["latest_moment"].format(kind=KINDS[lang][m["kind"]], team=m["team"],
                                               clock=m["clock"]))
    else:
        lines.append(T["quiet"])
    (hc, ac), (hx, ax), (hs, as_) = (_pair(f, k) for k in ("control_score_0_100", "xg", "shots"))
    if analyst:
        lines.append(T["control_a"].format(hc=f"{hc:.0f}", ac=f"{ac:.0f}", hx=f"{hx:.2f}",
                                           ax=f"{ax:.2f}", hs=hs, as_=as_))
    elif abs(hc - ac) >= 10:
        lines.append(T["on_top"].format(team=H if hc > ac else A))
    else:
        lines.append(T["even"])
    label = T["labels"].get(f["label"], f["label"])
    return {"title": T["cp_title"].format(label=label, h=H, a=A, hg=h, ag=a, sep=sep),
            "lines": lines}


def _recap_text(f: dict, mode: str, lang: str) -> dict:
    lang = lang_of(lang)
    T, analyst, sep = NARRATIVE[lang], mode == "analyst", SEP[lang]
    H, A, (h, a) = f["home"], f["away"], _pair(f, "score")
    (hc, ac), (hx, ax), (hs, as_) = (_pair(f, k) for k in ("control_score_0_100", "xg", "shots"))
    v = dict(h=H, a=A, hg=h, ag=a, sep=sep, hx=f"{hx:.2f}", ax=f"{ax:.2f}", hs=hs, as_=as_,
             hc=f"{hc:.0f}", ac=f"{ac:.0f}")
    if analyst:
        lines = [T["ft_a"].format(**v)]
    else:
        lines = [T["home_win" if h > a else "away_win" if a > h else "draw"].format(**v)]
    if f["goals"]:
        lines.append(T["goals"].format(
            list=", ".join(f"{g['player']} {g['clock']}" for g in f["goals"])))
    else:
        lines.append(T["no_goals"])
    if analyst:
        lines.append(T["ft_stats"].format(**v))
    elif f["standout_player"]:
        s = f["standout_player"]
        lines.append(T["standout"].format(p=s["player"], team=s["team"]))
    pos = f["table_position_after"]
    lines.append(T["table"].format(h=H, a=A, hp=ordinal(pos[H], lang), ap=ordinal(pos[A], lang),
                                    hpn=pos[H], apn=pos[A]))
    return {"title": T["ft_title"].format(**v), "lines": lines}


def _brief_text(f: dict, mode: str, lang: str) -> dict:
    lang = lang_of(lang)
    T = NARRATIVE[lang]
    H, A = f["home"], f["away"]
    lines = []
    (hx, ax), (hs, as_) = _pair(f, "xg"), _pair(f, "shots")
    if abs(hx - ax) >= 0.3:
        team, x, y, s = (H, hx, ax, hs) if hx > ax else (A, ax, hx, as_)
        lines.append(T["brief_xg_lead"].format(team=team, x=f"{x:.2f}", y=f"{y:.2f}", s=s))
    else:
        lines.append(T["brief_xg_level"].format(x=f"{hx:.2f}", y=f"{ax:.2f}"))
    hp, ap = _pair(f, "ppda_avg")
    if hp is not None and ap is not None:
        team, other, p, q = (H, A, hp, ap) if hp <= ap else (A, H, ap, hp)
        lines.append(T["brief_press"].format(team=team, other=other, p=p, q=q))
    ht = f["field_tilt_last_15"][H]
    if ht is not None:
        team, v = (H, ht) if ht >= 50 else (A, 100 - ht)
        lines.append(T["brief_tilt"].format(team=team, v=v))
    tp = f["top_passer"]
    if tp:
        lines.append(T["brief_passer"].format(p=tp["player"], team=tp["team"], c=tp["completions"],
                                              a=tp["attempts"], prog=tp["progressive"]))
    label = T["labels"].get(f["label"], f["label"])
    return {"title": T["brief_title"].format(label=label), "lines": lines}


RENDER = {"pre_match": _pre_match_text, "checkpoint": _checkpoint_text, "recap": _recap_text,
          "brief": _brief_text}
