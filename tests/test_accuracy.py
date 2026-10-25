"""Does what we report match what happened?

Each test replays the same seeded match the pipeline ran on and checks the
reported numbers (overlays, Narrator story, analytics, the audit) against
the raw synthetic events, so an inaccurate report fails the build.
"""

from collections import Counter

import pytest

from matchhealth.agents.grounding import allowed_numbers, ungrounded
from matchhealth.agents.narrator import Narrator
from matchhealth.agents.orchestrator import DEFAULT_PERSONAS, Orchestrator
from matchhealth.engine.analytics import MatchAnalytics
from matchhealth.engine.health import HealthEngine
from matchhealth.replay.generator import MatchConfig, generate_match
from matchhealth.replay.season import season_context
from matchhealth.run import main
from matchhealth.shared.models import Explanation, MatchEvent, Trigger, clock
from matchhealth.shared.state import InMemoryStore

SEED = 7


@pytest.fixture(scope="module")
def played():
    """One full mock match through the real pipeline, plus its raw events."""
    import asyncio
    import os
    os.environ["MATCHHEALTH_MOCK_LLM"] = "1"
    store = asyncio.run(main(seed=SEED, speed=0))
    cfg = MatchConfig(seed=SEED)
    return store, generate_match(cfg), cfg


def secs(clock_str: str) -> int:
    m, s = clock_str.split(":")
    return int(m) * 60 + int(s)


# --- reporting matches the events ---------------------------------------------

def test_every_goal_is_reported_with_the_right_scorer_and_minute(played):
    store, events, _ = played
    goals = [e for e in events if e.type == "goal"]
    reported = sorted((m for m in store.moments() if m["trigger"]["kind"] == "goal"),
                      key=lambda m: m["trigger"]["t"])
    assert [(m["trigger"]["facts"]["scorer"], m["producer"]["show_at"]) for m in reported] == \
        [(e.player, clock(e.t)) for e in goals]


def test_recap_score_and_scorers_match_the_events(played):
    store, events, cfg = played
    goals = [e for e in events if e.type == "goal"]
    facts = store.get("n-recap")["facts"]
    home, away = cfg.teams
    assert facts["score"] == {home.name: sum(e.team == home.name for e in goals),
                              away.name: sum(e.team == away.name for e in goals)}
    assert [(g["player"], g["clock"]) for g in facts["goals"]] == \
        [(e.player, clock(e.t)) for e in goals]


@pytest.mark.parametrize("doc", ["n-15", "n-halftime", "n-60"])
def test_checkpoint_score_is_the_score_at_that_minute(played, doc):
    store, events, cfg = played
    facts = store.get(doc)["facts"]
    upto = secs(facts["clock"]) + 1  # the clock rounds down to the second
    goals = Counter(e.team for e in events if e.type == "goal" and e.t < upto)
    assert facts["score"] == {t.name: goals[t.name] for t in cfg.teams}


def test_season_goal_tallies_are_season_plus_this_match(played):
    store, events, cfg = played
    season = season_context(SEED, cfg.matchweek)
    seen: Counter = Counter()
    for m in sorted(store.moments(), key=lambda m: m["trigger"]["t"]):
        if m["trigger"]["kind"] != "goal":
            continue
        scorer = m["trigger"]["facts"]["scorer"]
        seen[scorer] += 1
        assert m["trigger"]["facts"]["scorer_season_goals"] == \
            season["player_goals"].get(scorer, 0) + seen[scorer]


def test_every_overlay_shows_at_its_trigger_time(played):
    store, _, _ = played
    for m in store.moments():
        if "producer" in m:
            assert m["producer"]["show_at"] == clock(m["trigger"]["t"])
            assert all(v["show_at"] == m["producer"]["show_at"] for v in m["personaliser"])


# --- analytics are exact on hand-built events -----------------------------------

def test_analytics_exact_on_hand_built_events():
    """Team A attacks right. Expected numbers worked out by hand."""
    ev = [
        MatchEvent(id=1, t=10, type="pressure", team="B", player="b1", x=50, y=30),
        MatchEvent(id=2, t=12, type="pass", team="A", player="a1", x=50, y=30, end_x=75, end_y=30,
                   outcome="success"),   # pressured, final third, progressive (+25m)
        MatchEvent(id=3, t=15, type="pass", team="A", player="a1", x=75, y=30, end_x=80, end_y=40,
                   outcome="fail"),      # not pressured (pressure applies to one pass)
        MatchEvent(id=4, t=16, type="tackle", team="B", player="b2", x=80, y=40, outcome="won"),
        MatchEvent(id=5, t=18, type="pass", team="B", player="b2", x=80, y=40, end_x=60, end_y=40,
                   outcome="success"),   # B attacks left: 20m toward goal, progressive
        MatchEvent(id=6, t=1000, type="foul", team="A", player="a2", x=60, y=40, outcome="clean"),
    ]
    engine = HealthEngine(("A", "B"))
    an = MatchAnalytics(("A", "B"), {"A": True, "B": False}, engine)
    for e in ev:
        engine.update(e)
        an.update(e)
    p = an.player_payload()
    assert (p["a1"]["attempts"], p["a1"]["completions"]) == (2, 1)
    assert (p["a1"]["pressured_att"], p["a1"]["pressured_comp"]) == (1, 1)
    assert p["a1"]["progressive"] == 1 and p["b2"]["progressive"] == 1
    assert p["b2"]["tackles"] == 1
    team = an.team_payload()
    # Block 0-15': B made 2 defensive actions (pressure, tackle) against A's 2 passes.
    assert team["ppda"]["B"][0] == 1.0
    # A made no defensive action in block 0, one (the foul) in block 1 against B's 0 passes.
    assert team["ppda"]["A"][0] is None and team["ppda"]["A"][1] == 0.0
    # Final-third passes in block 0: A 2 (end_x 75, 80), B 0 (60m from x=0 is not > 70).
    assert team["tilt"]["A"][0] == 100 and team["tilt"]["B"][0] == 0


# --- grounding: no invented numbers reach viewers -----------------------------------

def test_grounding_guard_catches_invented_numbers():
    allowed = allowed_numbers({"scorer_season_goals": 6, "shot_quality": 0.41, "xg": 1.07},
                              "33:26")
    assert ungrounded("Castell's 7th goal of the season", allowed) == ["7"]
    assert ungrounded("Goal number 6, chance quality 0.41, xG 1,07 at 33:26", allowed) == []
    assert ungrounded("A 25-metre pass in 5 minutes", allowed) == ["25"]
    assert ungrounded("Two passes, 90 minutes, 100%", allowed) == []


def test_everything_shown_in_mock_mode_is_grounded(played):
    store, _, _ = played
    for m in store.moments():
        if "personaliser" not in m:
            continue
        allowed = allowed_numbers(m["trigger"]["facts"], clock(m["trigger"]["t"]),
                                  m["producer"])
        for v in m["personaliser"]:
            assert ungrounded(f"{v['headline']} {v['subline'] or ''}", allowed) == [], v
    for doc in ("n-pre-match", "n-15", "n-halftime", "n-60", "n-recap", "n-brief-60"):
        d = store.get(doc)
        allowed = allowed_numbers(d["facts"], d["narrator"]["label"], d["narrator"]["show_at"])
        for persona, v in d["narrator"]["variants"].items():
            assert ungrounded(" ".join([v["title"], *v["lines"]]), allowed) == [], (doc, persona)


async def test_invented_number_from_the_model_is_rejected(monkeypatch):
    monkeypatch.setenv("MATCHHEALTH_MOCK_LLM", "0")

    class Fabricator:
        async def complete_json(self, system, user, tier):
            return {"variants": {k: {"title": "Big night", "lines": ["Castell has 99 goals."]}
                                 for k in user["personas"]}}

    cfg = MatchConfig(seed=SEED)
    fixture = {"home": cfg.teams[0].name, "away": cfg.teams[1].name,
               "matchweek": cfg.matchweek}
    store = InMemoryStore()
    item = await Narrator(store, Fabricator(), DEFAULT_PERSONAS, fixture,
                          season_context(SEED, cfg.matchweek)).pre_match()
    assert all("99" not in " ".join(v["lines"]) for v in item["variants"].values())
    assert store.get("n-pre-match")["recovery"]["reason"] == "ungrounded"
    assert len(store.get("n-pre-match")["grounding"]["rejected"]) == len(DEFAULT_PERSONAS)


async def test_analyst_invented_number_falls_back_to_stats(monkeypatch):
    monkeypatch.setenv("MATCHHEALTH_MOCK_LLM", "1")

    async def publish(base, variants):
        pass

    crew = Orchestrator(InMemoryStore(), publish)

    async def fabricated(trig):
        return Explanation(moment_id=trig.moment_id, why="Mensah's 12th goal this season.")

    crew.analyst.run = fabricated
    trig = Trigger(moment_id="m-1", kind="goal", t=600, team="Riverside FC",
                   player="D. Mensah", facts={"scorer": "D. Mensah", "scorer_season_goals": 4})
    base = await crew.handle(trig)
    assert base.template == "stats_only_fallback"
    doc = crew.store.get("m-1")
    assert doc["recovery"]["analyst"]["reason"] == "ungrounded"
    assert doc["grounding"]["rejected"][0]["numbers"] == ["12"]


# --- the audit -----------------------------------------------------------------------

def test_full_time_audit_passes(played):
    store, _, _ = played
    audit = store.get("n-audit")["audit"]
    assert audit["passed"], audit["issues"]
    assert audit["complete"] == audit["confirmed"] > 0
    assert audit["ungrounded_rejected"] == 0
    assert set(audit["narratives"].values()) == {"written"}
