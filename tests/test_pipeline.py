import json
from pathlib import Path

import jsonschema
import pytest

from matchhealth.agents.crew import Producer
from matchhealth.agents.orchestrator import Orchestrator
from matchhealth.engine.thresholds import ThresholdDetector
from matchhealth.replay.generator import MatchConfig, generate_match
from matchhealth.run import main
from matchhealth.shared.models import Trigger
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
    assert crew.store.get("m-1")["recovery"]["reason"] == "TimeoutError"
    jsonschema.validate(base.to_wire(), SCHEMA)


def test_fallback_is_valid():
    trig = Trigger(moment_id="m-2", kind="pressing_spell", t=1700, team="Northgate United",
                   facts={"turnovers_forced_5min": 6})
    jsonschema.validate(Producer.fallback(trig, 2).to_wire(), SCHEMA)


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_other_seeds_run(seed):
    assert generate_match(MatchConfig(seed=seed))
