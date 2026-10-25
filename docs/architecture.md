# Architecture and cost notes

## Flow

1. **Replay job** (`replay/`)
   - Picks a fixture from a fictional eight-club league. In `league.py`, each club has a playing style (press, tempo, directness, strength) that shapes its event stream, and managers rotate 0–3 starters per matchweek.
   - `season.py` simulates the season so far: table, form, top scorers, and each live club's last two games (line-up, substitutes, passing).
   - Generates the seeded live match (passes, shots, tackles, pressure, fouls, goals, substitutions) and streams it at a configurable speed (1× = real time).
   - Rates are tuned to real football: about 23 shots, 3 goals and 24 fouls per match.
2. **Engine** (`engine/`), deterministic with no AI. It updates rolling stats per event:
   - *Control*, per team over a 5-minute window: possession share × pass completion, adjusted for pass difficulty (pressure counts).
   - *Chaos*: the opponent's turnovers plus pressure per minute.
   - `analytics.py`: PPDA and field tilt per 15 minutes, touch zones, and per-player passing, pressure, progressive passes, tackles, shots and xG.
3. **Thresholds** (`engine/thresholds.py`) emit a `Trigger`, carrying the moment's pitch position, for:
   - goals and carded fouls
   - a control swing of 40 points or more
   - a big chance (shot quality ≥ 0.35)
   - a pressing spell (≥ 6 forced turnovers in 5 minutes, and ≥ 1.6× the opponent's)
   - shot speed ≥ 110 km/h
   - pass quality (difficulty ≥ 0.75: in practice a hard pass completed under pressure)

   That's about 25–35 triggers per match, each with a cooldown per kind and team.
4. **Orchestrator** (`agents/orchestrator.py`) runs one Microsoft Agent Framework workflow per trigger: `narrator_context` → Spotter → Analyst → Producer → Personaliser, with conditional recovery edges to a stats-only fallback ([graph](agent-workflow.md)). Every handoff is written to shared state.
5. **Narrator** (`agents/narrator.py`) tells the match-long story from shared state:
   - storylines before kick-off
   - check-ins at 15', half-time and 60'
   - chart briefings for analyst mode at the same points and at full time
   - the full-time recap

   That's about 9 calls per match. Every persona is written in one call, with template fallback text if a call fails.
6. **Grounding guard** (`agents/grounding.py`) checks that every number in AI-written text comes from the facts that agent was given. Text with an invented number is replaced by its template and the rejection is recorded.
7. **Publisher** pushes overlays, health ticks (with the ball's path), Spotter decisions and narratives to Web PubSub; viewers pick their version in the browser. Every minute a **catch-up snapshot** is broadcast and saved to Cosmos. The negotiate service hands the latest snapshot to each new viewer with their connection token, so the page fills in at once.
8. **Audit** (`audit.py`) at full time reads Cosmos back and checks that every confirmed moment went through every agent (or recorded a recovery) and reached viewers. The result is saved and shown on the page.

## Why each Azure service

| Need | Service | Why not the alternative |
|---|---|---|
| Run the match and agents | Container Apps jobs (scale to zero) | AKS has a fixed cluster cost |
| Event hand-off | In-process | Event Hubs bills hourly; one process per match needs no broker |
| Shared agent state, audit, live snapshot | Cosmos DB free tier (1,000 RU/s) | None needed |
| Push to viewers | Web PubSub Standard (the free tier's 20,000 messages a day ran out with a few viewers) | Polling adds latency |
| Catch-up for late joiners | Blob Storage: `snapshot.json`, saved every minute | None needed |
| Browser tokens | A small Container App (`negotiate_service.py`), scale to zero | No keys in the browser |
| Frontend | Static Web Apps free | None needed |
| Models | Foundry: `gpt-4.1-mini` (nano requests routed to mini until nano quota is granted) | Bigger models aren't needed for formatting |

Not yet wired: Application Insights tracing (provisioned in Bicep, not emitted by the code).

## Cost

- **Real-model match:** about 25–35 triggers × (Spotter + Analyst + Producer + one Personaliser call) + 9 Narrator calls, roughly **US$0.10–0.25** per match with mini. This is an estimate.
- **Public demo:** mock mode, so $0 model cost. Compute is about US$3–5 for the whole judging window at 0.25 vCPU after the free grants (also an estimate).
- Web PubSub Standard is about US$1.60 a day, roughly US$26 for the judging window. Cosmos DB, Static Web Apps and the negotiate service stay in free tiers.
- If sends are refused anyway, the match carries on: each send fails fast and the next catch-up fills the gap.

## Avoid

Fabric capacity, Azure AI Search, Event Hubs Standard, and always-on replicas: they bill whether used or not. Keep the US$20 budget alert on the subscription.
