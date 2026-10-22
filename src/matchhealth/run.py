"""Local end-to-end run: generate a match, replay it, detect moments, run the crew.

    python -m matchhealth.run --seed 7 --speed 0
"""

from __future__ import annotations

import argparse
import asyncio
import os
import time

from dotenv import load_dotenv

from matchhealth.agents.llm import mock_enabled
from matchhealth.agents.orchestrator import DEFAULT_PERSONAS, Orchestrator
from matchhealth.agents.publisher import console_publish
from matchhealth.engine.thresholds import ThresholdDetector
from matchhealth.replay.generator import MatchConfig, generate_match
from matchhealth.replay.replayer import replay
from matchhealth.shared.models import clock
from matchhealth.shared.state import InMemoryStore, StateStore

HEALTH_TICK_EVERY = 5  # publish a live control/chaos snapshot every N events


async def main(seed: int, speed: float, preview: bool = False,
                favourite_player: str | None = None) -> StateStore:
    cfg = MatchConfig(seed=seed)
    events = generate_match(cfg)
    home, away = cfg.teams
    detector = ThresholdDetector((home.name, away.name),
                                 {home.name: home.attacking_right, away.name: away.attacking_right})

    if os.environ.get("COSMOS_ENDPOINT"):
        from matchhealth.shared.state import CosmosStore
        match_id = f"seed-{seed}"  # stable per seed: reruns overwrite rather than pile up
        store = CosmosStore(match_id)
        print(f"Using Cosmos DB shared state (match_id={match_id})")
    else:
        store = InMemoryStore()

    llm = None
    if not mock_enabled():
        from matchhealth.agents.llm import FoundryLLM
        llm = FoundryLLM()

    preview_server = None
    publishers = [console_publish]
    raw_send = None  # carries health ticks, score updates, agent activity -- all {"...": ...} dicts
    if preview:
        from matchhealth.agents.local_preview import LocalPreviewServer
        preview_server = LocalPreviewServer()
        await preview_server.start()
        print("Open web/index.html in your browser now (file:// is fine).")
        print("Waiting up to 120s for it to connect...")
        if not await preview_server.wait_for_a_client():
            print("No browser connected in time; continuing without live preview.")
            preview_server = None
        else:
            print("Browser connected — starting the match.")
            publishers.append(preview_server.publish)
            raw_send = preview_server.broadcast_raw
    elif os.environ.get("WEBPUBSUB_ENDPOINT"):
        from matchhealth.agents.publisher import webpubsub_health_sender, webpubsub_publisher
        publishers.append(webpubsub_publisher())
        raw_send = webpubsub_health_sender()

    async def publish(base, variants) -> None:
        for p in publishers:
            await p(base, variants)

    personas = list(DEFAULT_PERSONAS)
    if favourite_player:
        # "Favourite club(s), favourite player(s), player focused mode" is an
        # explicit required capability in the hackathon brief's Personalize
        # stage -- this is the whole viewer-configurable end of it. Variants
        # for every persona are still computed once per moment and broadcast
        # to everyone (cost doesn't scale with audience size); this is one
        # more precomputed variant, not a per-viewer request.
        personas.append({"mode": "fan", "language": "en", "favourite_player": favourite_player})
        print(f"Fan mode following: {favourite_player}")
    crew = Orchestrator(store, publish, llm, personas=personas, activity_send=raw_send)
    print(f"{home.name} vs {away.name} — {len(events)} synthetic events, mock={mock_enabled()}")

    score = {home.name: 0, away.name: 0}

    async def send_health(t: float) -> None:
        snap = detector.engine.snapshot()
        await raw_send({
            "show_at": clock(t),
            "teams": {t2: snap[t2].model_dump() for t2 in (home.name, away.name)},
            "score": dict(score),
        })

    if raw_send:
        # Team names/clock otherwise sit blank until the first periodic tick
        # (every HEALTH_TICK_EVERY events) -- send one immediately at kickoff
        # so a freshly-connected viewer isn't staring at placeholders.
        await send_health(0.0)

    tick = 0
    async for ev in replay(events, speed=speed):
        if ev.type == "goal":
            score[ev.team] += 1
            if raw_send:
                await send_health(ev.t)  # don't wait for the next periodic tick on a goal
        for trig in detector.process(ev):
            await crew.handle(trig)
        tick += 1
        if raw_send and tick % HEALTH_TICK_EVERY == 0:
            await send_health(ev.t)
    print(f"Full time. {len(store.moments())} moments produced. Final score: {score}")
    if preview_server:
        await preview_server.close()
    return store


def cli() -> None:
    load_dotenv()
    p = argparse.ArgumentParser()
    p.add_argument("--seed", type=int, default=None,
                    help="Fixed seed for a reproducible match; omit for a fresh one each run "
                         "(e.g. the scheduled judging-period demo job)")
    p.add_argument("--speed", type=float, default=0, help="1 = real time, 0 = as fast as possible")
    p.add_argument("--preview", action="store_true",
                    help="Serve overlays to web/index.html over a local WebSocket (no Azure)")
    p.add_argument("--favourite-player", default="E. Novak",
                    help="Adds a 'fan' persona following this player; empty string disables it")
    args = p.parse_args()
    seed = args.seed if args.seed is not None else int(time.time()) % 1000
    if args.seed is None:
        print(f"No --seed given, using {seed} (changes every run, e.g. for the scheduled demo job)")
    asyncio.run(main(seed, args.speed, args.preview, args.favourite_player or None))


if __name__ == "__main__":
    cli()
