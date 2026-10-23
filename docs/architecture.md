# Architecture and cost notes

## Flow
1. **Replay job** (`replay/`) picks a fixture from a fictional eight-club league (`league.py`: each club has a playing style — press, tempo, directness, strength — that shapes its event stream), simulates the season so far for table/form/top-scorer context (`season.py`), then generates the seeded live match and streams events at a configurable speed (1× = real time). Rates are tuned to real football: ~23 shots, ~3 goals, ~24 fouls per match.
2. **Engine** (`engine/`) updates rolling stats per event and computes the **match health score** per team over a 5-minute window:
   - *Control* = possession share × pass completion, adjusted for pass difficulty.
   - *Chaos* = turnovers + pressure events + duels per minute.
3. **Thresholds** (`engine/thresholds.py`) emit a `Trigger` for: goals, carded fouls, control swing ≥ 40 points, big chance (shot quality ≥ 0.35), pressing spell (≥ 6 forced turnovers in 5 min and ≥ 1.6× the opponent's), shot speed ≥ 110 km/h, and pass quality (difficulty ≥ 0.75 — in practice a hard pass completed under pressure). ~25–35 triggers per match, each with a per-(kind, team) cooldown.
4. **Orchestrator** runs Spotter → Analyst → Producer → Personaliser and writes each handoff to shared state. Before the Spotter, the **Narrator** enriches the trigger with season facts (e.g. a scorer's season tally) so the Analyst can cite them.
5. **Narrator** tells the match-long story from shared state: storylines before kick-off, checkpoints at 15'/half-time/60', and the full-time recap (~5 calls per match, every persona in one call, deterministic fallback text if a call fails).
6. **Publisher** pushes base + variant overlays to Web PubSub; viewers choose a variant client-side.

## Why each Azure service

| Need | Service | Why not the alternative |
|---|---|---|
| Run replay + agents | Container Apps (scale to zero) | AKS has a fixed cluster cost |
| Event hand-off | In-process / Storage Queue | Event Hubs bills hourly |
| Shared agent state | Cosmos DB free tier (1,000 RU/s) | — |
| Push to viewers | Web PubSub free tier | Polling adds latency |
| Frontend | Static Web Apps free | — |
| Models | Foundry: one mini, one nano deployment | Bigger models aren't needed for formatting |
| Telemetry | Application Insights (5 GB/month free) | — |

## Token budget (per 90-minute match, approx.)
- ~40 triggers × (Spotter + Analyst + Producer) + 40 Personaliser calls (all variants at once).
- ≈ 0.5M input / 0.06M output tokens → **US$0.10–0.25** with mini on Analyst only.

## Avoid
Fabric capacity, Azure AI Search, Event Hubs Standard, and always-on replicas: they bill whether used or not. Set a US$20 budget alert on the subscription.
