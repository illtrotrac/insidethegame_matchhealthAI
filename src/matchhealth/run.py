"""Local end-to-end run: generate a match, replay it, detect moments, run the crew.

    python -m matchhealth.run --seed 7 --speed 0
"""

from __future__ import annotations

import argparse
import asyncio
import os

from dotenv import load_dotenv

from matchhealth.agents.llm import mock_enabled
from matchhealth.agents.orchestrator import Orchestrator
from matchhealth.agents.publisher import console_publish
from matchhealth.engine.thresholds import ThresholdDetector
from matchhealth.replay.generator import MatchConfig, generate_match
from matchhealth.replay.replayer import replay
from matchhealth.shared.state import InMemoryStore


async def main(seed: int, speed: float) -> InMemoryStore:
    cfg = MatchConfig(seed=seed)
    events = generate_match(cfg)
    home, away = cfg.teams
    detector = ThresholdDetector((home.name, away.name),
                                 {home.name: home.attacking_right, away.name: away.attacking_right})
    store = InMemoryStore()

    llm = None
    if not mock_enabled():
        from matchhealth.agents.llm import FoundryLLM
        llm = FoundryLLM()
    publish = console_publish
    if os.environ.get("WEBPUBSUB_ENDPOINT"):
        from matchhealth.agents.publisher import webpubsub_publisher
        publish = webpubsub_publisher()

    crew = Orchestrator(store, publish, llm)
    print(f"{home.name} vs {away.name} — {len(events)} synthetic events, mock={mock_enabled()}")
    async for ev in replay(events, speed=speed):
        for trig in detector.process(ev):
            await crew.handle(trig)
    print(f"Full time. {len(store.moments())} moments produced.")
    return store


def cli() -> None:
    load_dotenv()
    p = argparse.ArgumentParser()
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--speed", type=float, default=0, help="1 = real time, 0 = as fast as possible")
    args = p.parse_args()
    asyncio.run(main(args.seed, args.speed))


if __name__ == "__main__":
    cli()
