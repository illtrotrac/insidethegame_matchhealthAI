import json
from collections import Counter
from pathlib import Path

import jsonschema
import pytest

from matchhealth.agents.crew import Producer
from matchhealth.agents.narrator import Narrator
from matchhealth.agents.orchestrator import DEFAULT_PERSONAS, Orchestrator
from matchhealth.engine.health import HealthEngine
from matchhealth.engine.stats import pass_difficulty
from matchhealth.engine.thresholds import ThresholdDetector
from matchhealth.replay.generator import MatchConfig, generate_match
from matchhealth.replay.league import LEAGUE, schedule
from matchhealth.replay.season import season_context
from matchhealth.run import main
from matchhealth.shared.models import MatchEvent, Trigger
from matchhealth.shared.state import InMemoryStore

SCHEMA = json.loads((Path(__file__).parents[1] / "schemas/overlay.schema.json").read_text())


def test_generator_is_deterministic_and_realistic():
    a, b = generate_match(MatchConfig(seed=3)), generate_match(MatchConfig(seed=3))
    assert [e.model_dump() for e in a] == [e.model_dump() for e in b]
    assert 1000 < len(a) < 2600
    assert a[-1].type == "full_time"


def test_engine_triggers_are_sparse():
    cfg = MatchConfig(seed=7)
    home, away = cfg.teams
    det = ThresholdDetector((home.name, away.name),
                            {home.name: home.attacking_right, away.name: away.attacking_right})
    triggers = [t for ev in generate_match(cfg) for t in det.process(ev)]
    assert 5 <= len(triggers) <= 80, len(triggers)


async def test_full_match_overlays_match_schema(monkeypatch):
    monkeypatch.setenv("MATCHHEALTH_MOCK_LLM", "1")
    store = await main(seed=7, speed=0)
    assert store.moments()
    for m in store.moments():
        jsonschema.validate(m["producer"], SCHEMA)
        for v in m["personaliser"]:
            jsonschema.validate(v, SCHEMA)
            assert v["show_at"] == m["producer"]["show_at"]


async def test_analyst_failure_falls_back_to_stats_only(monkeypatch):
    monkeypatch.setenv("MATCHHEALTH_MOCK_LLM", "1")
    published = []

    async def publish(base, variants):
        published.append(base)

    crew = Orchestrator(InMemoryStore(), publish)

    async def boom(_trig):
        raise TimeoutError

    crew.analyst.run = boom
    trig = Trigger(moment_id="m-1", kind="big_chance", t=600, team="Riverside FC",
                   player="D. Mensah", facts={"shot_quality": 0.41})
    base = await crew.handle(trig)
    assert base.template == "stats_only_fallback"
    assert crew.store.get("m-1")["recovery"]["analyst"]["reason"] == "TimeoutError"
    jsonschema.validate(base.to_wire(), SCHEMA)


def test_pressure_applies_to_pressed_teams_next_pass_only():
    eng = HealthEngine(("A", "B"))
    pass_kw = dict(type="pass", team="A", x=10, y=10, end_x=30, end_y=20, outcome="success")
    eng.update(MatchEvent(id=1, t=0, type="pressure", team="B"))
    first, second = MatchEvent(id=2, t=3, **pass_kw), MatchEvent(id=3, t=6, **pass_kw)
    eng.update(first)
    eng.update(second)
    assert eng.under_pressure(first) and not eng.under_pressure(second)
    assert pass_difficulty(first, True) > pass_difficulty(first)


async def test_workflow_routes_failures_and_rejections(monkeypatch):
    monkeypatch.setenv("MATCHHEALTH_MOCK_LLM", "1")
    published = []

    async def publish(base, variants):
        published.append(base)

    crew = Orchestrator(InMemoryStore(), publish)
    trig = lambda mid: Trigger(moment_id=mid, kind="big_chance", t=600, team="Riverside FC",  # noqa: E731
                               player="D. Mensah", facts={"shot_quality": 0.41})

    async def bad_overlay(*_a):
        raise ValueError("schema violation")
    crew.producer.run = bad_overlay  # Producer fails -> fallback edge
    base = await crew.handle(trig("m-1"))
    assert base.template == "stats_only_fallback"
    assert crew.store.get("m-1")["recovery"]["producer"]["reason"] == "ValueError"

    async def spotter_down(*_a, **_k):
        raise TimeoutError
    crew.spotter.run = spotter_down  # Spotter fails open with engine priority
    assert await crew.handle(trig("m-2")) is not None
    assert set(crew.store.get("m-2")["recovery"]) == {"spotter", "producer"}

    async def reject(*_a, **_k):
        return {"confirm": False, "priority": 3, "reason": "Repeat"}
    crew.spotter.run = reject  # rejected: nothing produced or published
    assert await crew.handle(trig("m-3")) is None
    assert "producer" not in crew.store.get("m-3") and len(published) == 2


def test_fallback_is_valid():
    trig = Trigger(moment_id="m-2", kind="pressing_spell", t=1700, team="Northgate United",
                   facts={"turnovers_forced_5min": 6})
    jsonschema.validate(Producer.fallback(trig, 2).to_wire(), SCHEMA)


def test_league_rosters_are_complete_and_unique():
    names = [p for c in LEAGUE for p in c.players]
    assert all(len(c.players) == 11 for c in LEAGUE)
    assert len(names) == len(set(names))


def test_schedule_is_a_double_round_robin():
    weeks = schedule()
    pairs = [f for w in weeks for f in w]
    assert len(weeks) == 14 and len(pairs) == len(set(pairs)) == 56
    for w in weeks:
        assert len({t for f in w for t in f}) == 8  # everyone plays once per week


def test_season_table_is_consistent():
    cfg = MatchConfig(seed=11)
    assert cfg.matchweek >= 2
    s = season_context(11, cfg.matchweek)
    assert s == season_context(11, cfg.matchweek)  # deterministic
    for r in s["table"]:
        assert r["p"] == cfg.matchweek - 1 == r["w"] + r["d"] + r["l"]
        assert r["pts"] == 3 * r["w"] + r["d"]
    assert sum(r["gf"] for r in s["table"]) == sum(r["ga"] for r in s["table"])


def test_chosen_fixture_by_partial_name():
    cfg = MatchConfig(seed=5, home="kingsmere", away="port calder")
    assert [t.name for t in cfg.teams] == ["Kingsmere City", "Port Calder Town"]
    assert (cfg.teams[0].name, cfg.teams[1].name) in schedule()[cfg.matchweek - 1]
    for bad in ({"home": "kingsmere", "away": "kingsmere"}, {"home": "zzz", "away": "riverside"},
                {"home": "kingsmere"}):
        with pytest.raises(ValueError):
            MatchConfig(seed=5, **bad)


def test_goal_and_shot_rates_are_football_realistic():
    from statistics import mean
    stats = [Counter(e.type for e in generate_match(MatchConfig(seed=s))) for s in range(30)]
    assert 1.8 <= mean(c["goal"] for c in stats) <= 4.0
    assert 15 <= mean(c["shot"] for c in stats) <= 32


async def test_narrator_tells_the_whole_story(monkeypatch):
    monkeypatch.setenv("MATCHHEALTH_MOCK_LLM", "1")
    store = await main(seed=7, speed=0)
    personas = {f"{p['mode']}-{p['language']}" for p in DEFAULT_PERSONAS}
    for doc in ("n-pre-match", "n-15", "n-halftime", "n-60", "n-recap"):
        item = store.get(doc)["narrator"]
        assert set(item["variants"]) == personas
        assert all(v["title"] and v["lines"] for v in item["variants"].values())
        assert store.get(doc)["facts"]  # what the story was allowed to cite
    goals = [m for m in store.moments() if m["trigger"]["kind"] == "goal"]
    assert all(m["trigger"]["facts"]["scorer_season_goals"] >= 1 for m in goals)


async def test_mock_mode_is_translated_in_every_language(monkeypatch):
    monkeypatch.setenv("MATCHHEALTH_MOCK_LLM", "1")
    store = await main(seed=7, speed=0)
    langs = {p["language"] for p in DEFAULT_PERSONAS}
    recap = store.get("n-recap")["narrator"]["variants"]
    titles = {lang: recap[f"casual-{lang}"]["title"] for lang in langs}
    assert len(set(titles.values())) == len(langs)  # no language falls back to English
    for m in store.moments():
        heads = {v["language"]: v["headline"] for v in m["personaliser"] if v["mode"] == "casual"}
        assert len(set(heads.values())) == len(langs), heads
        assert not any(h.startswith("[") for h in heads.values())


async def test_narrator_falls_back_when_the_model_fails(monkeypatch):
    monkeypatch.setenv("MATCHHEALTH_MOCK_LLM", "0")

    class BrokenLLM:
        async def complete_json(self, system, user, tier):
            return {"variants": {"casual-en": {"title": "Only one", "lines": ["ok"]}}}

    cfg = MatchConfig(seed=7)
    fixture = {"home": cfg.teams[0].name, "away": cfg.teams[1].name,
               "matchweek": cfg.matchweek}
    store = InMemoryStore()
    narrator = Narrator(store, BrokenLLM(), DEFAULT_PERSONAS, fixture,
                        season_context(7, cfg.matchweek))
    item = await narrator.pre_match()
    assert item["variants"]["casual-en"]["title"] == "Only one"  # model output kept
    assert len(item["variants"]) == len(DEFAULT_PERSONAS)  # the rest filled from the facts
    assert store.get("n-pre-match")["recovery"]["reason"] == "incomplete"
    assert store.moments() == []  # narrative docs aren't moments


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_other_seeds_run(seed):
    assert generate_match(MatchConfig(seed=seed))
