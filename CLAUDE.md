# CLAUDE.md — context for AI coding assistants

## Project
Match Health AI: entry for the Microsoft x Premier League "Inside the Game" hackathon.
- Submission deadline: **27 Oct 2026, 11:59 pm PT**. Repo must be public; demo video < 2 minutes.
- Data must be **synthetic**; no real footage or data, no real team/player names, no PL trademarks.
- Framing: **observability for football.** The match has a "health score" (control vs chaos); thresholds raise alerts; an agent crew explains and renders them like a TV production team.
- Target prizes: Grand Prize + **Best Multi-Agent System** (alt: Best Azure Cloud Native Integration).

## Architecture decisions (agreed — don't change without asking)
1. **Code before AI.** `engine/` is deterministic Python and never calls an LLM. Agents run only when `engine/thresholds.py` fires (~30–50 chains per match).
2. **Four agents, distinct roles:** Spotter (confirm/dedupe/priority, nano) → Analyst (explain *why*, mini) → Producer (overlay spec, nano) → Personaliser (all variants in ONE structured call, nano).
3. **Producer output must validate** against `schemas/overlay.schema.json`. On validation failure or Analyst timeout → stats-only fallback overlay. Never a blank broadcast.
4. **Personaliser never changes template, timing or priority** — only copy, language, `focus_player`, mode.
5. **Shared state** in Cosmos DB (free tier); `shared/state.py` has an in-memory implementation for local runs and tests.
6. **Cost:** scale-to-zero Container Apps, free tiers everywhere, no Event Hubs/Fabric/AI Search unless asked. Budget target < US$15 for the whole hackathon.
7. Orchestration should use **Microsoft Agent Framework** with models deployed in **Microsoft Foundry**. `agents/orchestrator.py` currently uses a plain async pipeline behind the `LLMClient` protocol — check the current Agent Framework docs before wiring it in.

## Conventions
- Python 3.11+, type hints, pydantic models in `shared/models.py`, pytest.
- `MATCHHEALTH_MOCK_LLM=1` (default) runs the whole pipeline with no Azure calls. Keep this working; tests depend on it.
- Prompts live in `agents/prompts/*.md`, not inline strings.
- Keep overlay headlines ≤ 10 words, sublines ≤ 12 words.

## Deployed resources (resource group `matchhealth-rg`, region `eastus2`)
- **Foundry** `matchhealth-foundry`: `gpt-4.1-mini` deployed. `gpt-4.1-nano` has 0 default
  GlobalStandard quota on this subscription (quota increase requested); `FOUNDRY_DEPLOYMENT_NANO`
  is routed to the mini deployment as a workaround until that's approved — swap it back once it is.
- **Cosmos DB** `matchhealth-cosmos` (free tier), database `matchhealth`, container `moments`
  (partition key `/match_id`). Validated: 45/45 moments persisted with full agent-stage history.
- **Web PubSub** `matchhealth-pubsub` (free tier), hub `overlays`.
- **Container Apps** env `matchhealth-env`:
  - `matchhealth-negotiate` (scale-to-zero, external ingress, issues Web PubSub client tokens at
    `/negotiate`) — live.
  - `matchhealth-replay` (the actual replay+crew job, image from GHCR, `replica-timeout` 6000s to
    cover a full real-time 90-minute match) — live. Triggered manually with `az containerapp job
    start --name matchhealth-replay --resource-group matchhealth-rg`; watch logs with
    `az containerapp job logs show --name matchhealth-replay --resource-group matchhealth-rg
    --container matchhealth-replay --execution <name>`.
- **Static Web App** `matchhealth-web`: `https://polite-wave-086f2900f.2.azurestaticapps.net` —
  live, publicly serves `web/index.html`. Deployed by `.github/workflows/swa-deploy.yml` on every
  push to `web/` (token in the `AZURE_STATIC_WEB_APPS_API_TOKEN` repo secret).
- **Docker image**: `ghcr.io/illtrotrac/matchhealthai:latest`, built by `.github/workflows/docker-publish.yml`
  on every push to `main` (public package — deliberately not ACR, which bills a flat daily fee
  just for existing; GHCR is free for a public repo). Set `PYTHONUNBUFFERED=1` in the Dockerfile —
  without it, `print()` output sits in an 8KB buffer and never reaches container logs for a
  90-minute real-time run.
- Everything above is $0 at idle (pay-per-token Foundry, free-tier Cosmos/Web PubSub/Static Web
  App, scale-to-zero Container Apps). `infra/main.bicep` is still the Day-1 skeleton and does not
  reflect any of this yet — everything was provisioned ad hoc via `az` CLI for speed; rewriting the
  Bicep to match (using `existing` resource refs where appropriate) is still open, see below.

## Full deployed path, validated
Local or deployed replay → deterministic engine fires a `Trigger` → agent crew calls real
Microsoft Foundry → writes every stage to Cosmos DB → publishes the overlay to Web PubSub → a
browser (served from the public Static Web App or anywhere else over http/https) negotiates a
client token from `matchhealth-negotiate` and renders it live. Confirmed with the actual deployed
`matchhealth-replay` Container Apps Job (not just local CLI runs): it authenticated to Foundry,
Cosmos and Web PubSub purely via **managed identity** (no API keys anywhere) and produced a real
LLM-generated headline from inside Azure.

## Next steps
- [x] Wire `LLMClient` to Foundry deployments (mini + nano\*). Validated end to end: 45 real
      moments, 0 schema fallbacks after fixing the Producer's stats-shape prompt and a rate-limit
      timeout. Also fixed a Web PubSub double-JSON-encoding bug in `publisher.py` along the way.
- [x] Web overlay: subscribe to Web PubSub via a deployed negotiate endpoint, persona picker.
      Validated with a real browser over the real cloud path, now publicly hosted.
      Still TODO: distinct visual treatment per template (`big_chance`, `momentum_chart`,
      `stat_compare`, `player_tag` all render identically right now — only `headline`/`subline`/
      `stats` are shown).
- [x] Create `matchhealth-replay` Container Apps Job pointed at the GHCR image. Triggered for
      real, confirmed a real Foundry-backed overlay produced inside Azure, then stopped (no need
      to burn the full 90 minutes just to prove it works).
- [x] Static Web App hosting `web/index.html` publicly.
- [ ] Rewrite `infra/main.bicep` to match what's actually deployed (negotiate + replay Container
      Apps, Static Web App, GHCR image, Cosmos/Web PubSub as `existing` resources where already
      provisioned, all role assignments) so the whole thing is reproducible from one
      `az deployment group create` instead of the ad hoc CLI sequence used today.
- [ ] Port orchestrator to Agent Framework; add tracing to App Insights. (Lower priority: the
      multi-agent *behavior* — distinct roles, timeouts, fallback — is already real regardless of
      which SDK orchestrates it.)
- [ ] Full-time recap generation (one call over stored moments).
- [ ] Record the < 2 min demo video.
