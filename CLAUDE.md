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
- **Container Apps** env `matchhealth-env`: `matchhealth-negotiate` (scale-to-zero, external
  ingress, issues Web PubSub client tokens at `/negotiate`) is live. `matchhealth-replay` (the
  actual job, pointed at the GHCR image) is not yet created — local CLI runs are still how the
  crew gets triggered.
- **Docker image**: `ghcr.io/illtrotrac/matchhealthai:latest`, built by `.github/workflows/docker-publish.yml`
  on every push to `main` (public package — deliberately not ACR, which bills a flat daily fee
  just for existing; GHCR is free for a public repo).
- Everything above is $0 at idle (pay-per-token Foundry, free-tier Cosmos/Web PubSub, scale-to-zero
  Container Apps). `infra/main.bicep` is still the Day-1 skeleton and does not yet reflect this —
  it needs updating to match what's actually deployed (see below).

## Next steps
- [x] Wire `LLMClient` to Foundry deployments (mini + nano\*). Validated end to end: 45 real
      moments, 0 schema fallbacks after fixing the Producer's stats-shape prompt and a rate-limit
      timeout. Also fixed a Web PubSub double-JSON-encoding bug in `publisher.py` along the way.
- [x] Web overlay: subscribe to Web PubSub via a deployed negotiate endpoint, persona picker.
      Validated with a real browser over the real cloud path. Still TODO: distinct visual treatment
      per template (`big_chance`, `momentum_chart`, `stat_compare`, `player_tag` all render
      identically right now — only `headline`/`subline`/`stats` are shown).
- [ ] Create `matchhealth-replay` Container Apps Job pointed at the GHCR image (currently only
      run locally via `python -m matchhealth.run`); update `infra/main.bicep` to match the real
      deployed topology (negotiate app, GHCR image, Cosmos/Web PubSub as `existing` resources,
      role assignments) so the whole thing is reproducible from one `az deployment group create`.
- [ ] Static Web App to host `web/index.html` for real (tested so far via a local `http.server`
      stand-in + the real deployed negotiate/Web PubSub — the mechanism is proven, just not hosted
      publicly yet).
- [ ] Port orchestrator to Agent Framework; add tracing to App Insights. (Lower priority: the
      multi-agent *behavior* — distinct roles, timeouts, fallback — is already real regardless of
      which SDK orchestrates it.)
- [ ] Full-time recap generation (one call over stored moments).
- [ ] Record the < 2 min demo video.
