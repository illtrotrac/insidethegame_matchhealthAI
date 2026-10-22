# Architecture and cost notes

## Flow
1. **Replay job** (`replay/`) generates a seeded synthetic match and streams events at a configurable speed (1× = real time).
2. **Engine** (`engine/`) updates rolling stats per event and computes the **match health score** per team over a 5-minute window:
   - *Control* = possession share × pass completion, adjusted for pass difficulty.
   - *Chaos* = turnovers + pressure events + duels per minute.
3. **Thresholds** (`engine/thresholds.py`) emit a `Trigger` for: control swing ≥ 25 points, big chance (shot quality ≥ 0.3), pressing spell (≥ 3 forced turnovers in 5 min), speed milestones.
4. **Orchestrator** runs Spotter → Analyst → Producer → Personaliser and writes each handoff to shared state.
5. **Publisher** pushes base + variant overlays to Web PubSub; viewers choose a variant client-side.

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
