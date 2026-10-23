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
from matchhealth.engine.analytics import MatchAnalytics
from matchhealth.engine.stats import win_draw_loss
from matchhealth.engine.thresholds import ThresholdDetector
from matchhealth.replay.generator import MatchConfig, generate_match
from matchhealth.replay.league import CLUBS, POSITIONS
from matchhealth.replay.replayer import replay
from matchhealth.replay.season import season_context
from matchhealth.shared.models import clock
from matchhealth.shared.state import InMemoryStore, StateStore

HEALTH_TICK_S = 30.0   # match-seconds between live control/chaos snapshots
HEAVY_EVERY = 4        # per-player passes + shot map ride on every 4th tick (message size)
CATCHUP_EVERY_S = 60.0  # real seconds between catch-up snapshots for viewers who join late
INTERMISSION_RESEND_S = 20.0


def squad(club: str) -> dict:
    """Shirt numbers and positions for the line-ups panel (from the club, so
    it's the starting XI even though the match mutates its Team on subs)."""
    c = CLUBS[club]
    return {"xi": [[i + 1, n, POSITIONS[i]] for i, n in enumerate(c.players)],
            "bench": [[12 + i, n] for i, n in enumerate(c.bench)]}


async def main(seed: int, speed: float, preview: bool = False,
               home_club: str | None = None, away_club: str | None = None,
               intermission_s: float = 0.0) -> StateStore:
    cfg = MatchConfig(seed=seed, home=home_club, away=away_club)
    events = generate_match(cfg)
    home, away = cfg.teams
    season = season_context(seed, cfg.matchweek)
    season_msg = {"season": {k: v for k, v in season.items()
                             if k not in ("results", "player_goals")},
                  "fixture": {"home": home.name, "away": away.name, "matchweek": cfg.matchweek,
                              "speed": speed,
                              "squads": {t.name: squad(t.name) for t in (home, away)}}}
    detector = ThresholdDetector((home.name, away.name),
                                 {home.name: home.attacking_right, away.name: away.attacking_right})

    if os.environ.get("COSMOS_ENDPOINT"):
        from matchhealth.shared.state import CosmosStore
        # One partition per run: reusing a seed's partition let a rerun's
        # Spotter and Narrator read the previous run's moments as this match's.
        slug = f"{home.name}-v-{away.name}".lower().replace(" ", "-")
        match_id = f"seed-{seed}-{slug}-{int(time.time())}"
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

    last_overlay: dict = {}

    async def publish(base, variants) -> None:
        last_overlay.update(base=base.to_wire(), variants=[v.to_wire() for v in variants])
        for p in publishers:
            await p(base, variants)

    narrator = Narrator(store, llm, list(DEFAULT_PERSONAS), season_msg["fixture"], season,
                        send=raw_send)
    crew = Orchestrator(store, publish, llm, personas=list(DEFAULT_PERSONAS),
                        activity_send=raw_send, narrator=narrator)
    print(f"Matchweek {cfg.matchweek}: {home.name} vs {away.name} — {len(events)} synthetic "
          f"events, mock={mock_enabled()}")

    score = {home.name: 0, away.name: 0}
    # Analyst-mode numbers (engine/analytics.py): per-player passing, pressure,
    # progressive passes, tackles, shots; per-15' PPDA and field tilt; zones.
    analytics = MatchAnalytics((home.name, away.name),
                               {home.name: home.attacking_right, away.name: away.attacking_right},
                               detector.engine)
    subs: list[list] = []  # [minute, team, on, off]

    # Everything a viewer who arrives late needs to see the whole match so far.
    pulse: list[list[float]] = []   # [minute, home control, away control] per tick
    path: list[list] = []           # ball path since the last tick: [x, y, team index]
    goals: list[list] = []          # [minute, team]
    health_count = 0
    last_health: dict = {}

    def health_payload(t: float, heavy: bool) -> dict:
        snap = detector.engine.snapshot()
        ratings = detector.match_stats(t)
        xg = {t2: ratings[t2]["xg"] for t2 in (home.name, away.name)}
        msg = {
            "show_at": clock(t),
            "teams": {t2: snap[t2].model_dump() for t2 in (home.name, away.name)},
            "ratings": ratings,
            "win_draw_loss": win_draw_loss(home.name, away.name, score, xg, t),
            "score": dict(score),
        }
        if heavy:
            msg.update(player_passes=analytics.player_payload(), shots=detector.shots(),
                       analytics=analytics.team_payload(), subs=subs)
        if path:  # the page replays this between ticks: real positions, not decoration
            msg["path"] = path[-16:]
            path.clear()
        return msg

    async def send_health(t: float) -> None:
        nonlocal health_count
        msg = health_payload(t, heavy=health_count % HEAVY_EVERY == 0)
        health_count += 1
        wdl = msg["win_draw_loss"]
        pulse.append([round(t / 60, 2), msg["teams"][home.name]["control"],
                      msg["teams"][away.name]["control"],
                      wdl["home_win_pct"], wdl["draw_pct"], wdl["away_win_pct"]])
        last_health.update(msg)
        await raw_send(msg)

    async def send_catchup(status: str, next_kickoff_in_s: float | None = None) -> None:
        t = pulse[-1][0] * 60 if pulse else 0.0
        await raw_send({"catchup": {
            **season_msg, "status": status, "next_kickoff_in_s": next_kickoff_in_s,
            "health": {**last_health, **health_payload(t, heavy=True)} if last_health else None,
            "pulse": pulse, "goals": goals, "narratives": narrator.log,
            "last_overlay": last_overlay or None,
        }})

    if raw_send:
        # Team names/clock otherwise sit blank until the first periodic tick
        # (every HEALTH_TICK_S match-seconds) -- send one immediately at kickoff
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
    next_tick_t = HEALTH_TICK_S
    last_catchup = time.monotonic()
    async for ev in replay(events, speed=speed):
        if ev.x is not None:
            path.append([round(ev.x, 1), round(ev.y, 1), 0 if ev.team == home.name else 1])
        if ev.type == "goal":
            score[ev.team] += 1
            goals.append([round(ev.t / 60, 2), ev.team])
            if raw_send:
                await send_health(ev.t)  # don't wait for the next periodic tick on a goal
        triggers = detector.process(ev)
        analytics.update(ev)  # after the engine has seen ev (pressure state)
        if ev.type == "substitution":
            subs.append([round(ev.t / 60), ev.team, ev.player, ev.player_off])
        for trig in triggers:
            await crew.handle(trig)
        if ev.type == "half_time":
            narrator_tasks.append(asyncio.create_task(
                narrator.checkpoint("Half-time", ev.t, live(ev.t))))
        elif checkpoints and ev.t >= checkpoints[0][0]:
            label = checkpoints.pop(0)[1]
            narrator_tasks.append(asyncio.create_task(
                narrator.checkpoint(label, ev.t, live(ev.t))))
        if raw_send and ev.t >= next_tick_t:
            await send_health(ev.t)
            next_tick_t = ev.t + HEALTH_TICK_S
        if raw_send and time.monotonic() - last_catchup >= CATCHUP_EVERY_S:
            await send_catchup("live")
            last_catchup = time.monotonic()
    await asyncio.gather(*narrator_tasks)
    await narrator.recap(live(5400.0))
    print(f"Full time. {len(store.moments())} moments produced. Final score: {score}")
    if raw_send:
        await send_health(5400.0)
        # Intermission: keep the finished match (recap, pulse, table) on screen
        # for anyone who opens the page before the next kickoff.
        end = time.monotonic() + intermission_s
        while True:
            remaining = end - time.monotonic()
            await send_catchup("full_time", max(0.0, remaining) if intermission_s else None)
            if remaining <= 0:
                break
            await asyncio.sleep(min(INTERMISSION_RESEND_S, remaining))
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
    p.add_argument("--intermission", type=float, default=0,
                   help="Seconds to keep re-broadcasting the finished match (recap, pulse, "
                        "table) with a countdown, e.g. until the scheduled demo's next kickoff")
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
        asyncio.run(main(seed, args.speed, args.preview, args.home, args.away,
                         args.intermission))
    except ValueError as exc:  # unknown/ambiguous club, or a club playing itself
        p.error(str(exc))


if __name__ == "__main__":
    cli()
