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
from matchhealth.agents.narrator import CHECKPOINTS, Narrator
from matchhealth.agents.orchestrator import DEFAULT_PERSONAS, Orchestrator
from matchhealth.agents.publisher import console_publish
from matchhealth.engine.stats import win_draw_loss
from matchhealth.engine.thresholds import ThresholdDetector
from matchhealth.replay.generator import MatchConfig, generate_match
from matchhealth.replay.replayer import replay
from matchhealth.replay.season import season_context
from matchhealth.shared.models import clock
from matchhealth.shared.state import InMemoryStore, StateStore

HEALTH_TICK_EVERY = 5  # publish a live control/chaos snapshot every N events
SEASON_RESEND_EVERY = 300  # ~13 match-minutes; the ~2.5KB season context rarely changes


async def main(seed: int, speed: float, preview: bool = False,
               home_club: str | None = None, away_club: str | None = None) -> StateStore:
    cfg = MatchConfig(seed=seed, home=home_club, away=away_club)
    events = generate_match(cfg)
    home, away = cfg.teams
    season = season_context(seed, cfg.matchweek)
    season_msg = {"season": {k: v for k, v in season.items()
                             if k not in ("results", "player_goals")},
                  "fixture": {"home": home.name, "away": away.name, "matchweek": cfg.matchweek}}
    detector = ThresholdDetector((home.name, away.name),
                                 {home.name: home.attacking_right, away.name: away.attacking_right})

    if os.environ.get("COSMOS_ENDPOINT"):
        from matchhealth.shared.state import CosmosStore
        match_id = f"seed-{seed}"  # stable per seed: reruns overwrite rather than pile up
        if home_club:  # a chosen fixture is a different match from the seed's own
            match_id += "-" + f"{home.name}-v-{away.name}".lower().replace(" ", "-")
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

    narrator = Narrator(store, llm, list(DEFAULT_PERSONAS), season_msg["fixture"], season,
                        send=raw_send)
    crew = Orchestrator(store, publish, llm, personas=list(DEFAULT_PERSONAS),
                        activity_send=raw_send, narrator=narrator)
    print(f"Matchweek {cfg.matchweek}: {home.name} vs {away.name} — {len(events)} synthetic "
          f"events, mock={mock_enabled()}")

    score = {home.name: 0, away.name: 0}
    # Per-player pass attempts/completions -- "pass accuracy" is named
    # explicitly in the brief, but nothing tracked it per player before (only
    # a team-level completion % existed, in HealthSnapshot). Every pass
    # updates this, not just the rare high-difficulty ones that fire a
    # pass_quality trigger -- this is meant to be a genuine running stat.
    player_passes: dict[str, dict] = {}

    def record_pass(ev) -> None:
        if ev.type != "pass" or not ev.player:
            return
        entry = player_passes.setdefault(
            ev.player, {"team": ev.team, "attempts": 0, "completions": 0})
        entry["attempts"] += 1
        if ev.outcome == "success":
            entry["completions"] += 1

    async def send_health(t: float) -> None:
        snap = detector.engine.snapshot()
        ratings = detector.match_stats(t)
        xg = {t2: ratings[t2]["xg"] for t2 in (home.name, away.name)}
        await raw_send({
            "show_at": clock(t),
            "teams": {t2: snap[t2].model_dump() for t2 in (home.name, away.name)},
            "ratings": ratings,
            "win_draw_loss": win_draw_loss(home.name, away.name, score, xg, t),
            "score": dict(score),
            "player_passes": player_passes,
            "shots": detector.shots(),
        })

    if raw_send:
        # Team names/clock otherwise sit blank until the first periodic tick
        # (every HEALTH_TICK_EVERY events) -- send one immediately at kickoff
        # so a freshly-connected viewer isn't staring at placeholders.
        await raw_send(season_msg)
        await send_health(0.0)
    await narrator.pre_match()

    def live(t: float) -> dict:
        snap = detector.engine.snapshot()
        return {"score": dict(score), "ratings": detector.match_stats(t),
                "control": {n: snap[n].control for n in (home.name, away.name)}}

    # Checkpoints run alongside the replay rather than blocking it while the
    # model writes; the recap waits for them so the story stays in order.
    checkpoints = list(CHECKPOINTS)
    narrator_tasks: list[asyncio.Task] = []
    tick = 0
    async for ev in replay(events, speed=speed):
        record_pass(ev)
        if ev.type == "goal":
            score[ev.team] += 1
            if raw_send:
                await send_health(ev.t)  # don't wait for the next periodic tick on a goal
        for trig in detector.process(ev):
            await crew.handle(trig)
        if ev.type == "half_time":
            narrator_tasks.append(asyncio.create_task(
                narrator.checkpoint("Half-time", ev.t, live(ev.t))))
        elif checkpoints and ev.t >= checkpoints[0][0]:
            label = checkpoints.pop(0)[1]
            narrator_tasks.append(asyncio.create_task(
                narrator.checkpoint(label, ev.t, live(ev.t))))
        tick += 1
        if raw_send and tick % HEALTH_TICK_EVERY == 0:
            await send_health(ev.t)
        if raw_send and tick % SEASON_RESEND_EVERY == 0:
            await raw_send(season_msg)  # so viewers who join mid-match get it too
            if narrator.log:
                await raw_send({"narratives": narrator.log})
    await asyncio.gather(*narrator_tasks)
    await narrator.recap(live(5400.0))
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
    p.add_argument("--home", help="Home club, full or partial name (e.g. kingsmere); "
                                  "use with --away. Omit both to let the seed pick a fixture")
    p.add_argument("--away", help="Away club, full or partial name")
    p.add_argument("--list-clubs", action="store_true", help="Print the league's clubs and exit")
    args = p.parse_args()
    if args.list_clubs:
        from matchhealth.replay.league import LEAGUE
        for c in LEAGUE:
            print(f"{c.name:<22} {c.style}")
        return
    if bool(args.home) != bool(args.away):
        p.error("--home and --away must be used together")
    seed = args.seed if args.seed is not None else int(time.time()) % 1000
    if args.seed is None:
        print(f"No --seed given, using {seed} (changes every run, e.g. for the scheduled demo job)")
    try:
        asyncio.run(main(seed, args.speed, args.preview, args.home, args.away))
    except ValueError as exc:  # unknown/ambiguous club, or a club playing itself
        p.error(str(exc))


if __name__ == "__main__":
    cli()
