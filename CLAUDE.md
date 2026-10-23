# CLAUDE.md — context for AI coding assistants

## Project
Match Health AI: entry for the Microsoft x Premier League "Inside the Game" hackathon.
- Submission deadline: **27 Oct 2026, 11:59 pm PT**. Repo must be public; demo video < 2 minutes.
- Data must be **synthetic**; no real footage or data, no real team/player names, no PL trademarks.
- Framing: **observability for football.** The match has a "health score" (control vs chaos); thresholds raise alerts; an agent crew explains and renders them like a TV production team.
- Target prizes: Grand Prize + **Best Multi-Agent System** (alt: Best Azure Cloud Native Integration).

## Architecture decisions (agreed — don't change without asking)
1. **Code before AI.** `engine/` is deterministic Python and never calls an LLM. Agents run only when `engine/thresholds.py` fires (~30–50 chains per match).
2. **Five agents, distinct roles:** per moment, Spotter (confirm/dedupe/priority, nano) → Analyst (explain *why*, mini) → Producer (overlay spec, nano) → Personaliser (all variants in ONE structured call, nano). Across the match, the **Narrator** (`agents/narrator.py`, added 23 Oct): pre-match storylines from season facts, enriches triggers with season context before the Analyst, checkpoints at 15'/HT/60', full-time recap — ~5 calls/match, all personas per call, deterministic fallback text on timeout/bad shape.
3. **Producer output must validate** against `schemas/overlay.schema.json`. On validation failure or Analyst timeout → stats-only fallback overlay. Never a blank broadcast.
4. **Personaliser never changes template, timing or priority** — only copy, language, `focus_player`, mode.
5. **Shared state** in Cosmos DB (free tier); `shared/state.py` has an in-memory implementation for local runs and tests.
6. **Cost:** scale-to-zero Container Apps, free tiers everywhere, no Event Hubs/Fabric/AI Search unless asked. Budget target < US$15 for the whole hackathon.
7. Orchestration uses **Microsoft Agent Framework** (`agent-framework-core` 1.23, ported 23 Oct): `agents/orchestrator.py` builds one `Workflow` per crew — each agent an `Executor`, typed handoff messages on edges, conditional `Recovery` edges to a `fallback` executor (graph in `docs/agent-workflow.md`). Model calls still go through the `LLMClient` protocol (Foundry via managed identity), so mock mode and tests are unchanged.

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
  - `matchhealth-demo` (same image, MATCHHEALTH_MOCK_LLM=1, **Schedule** trigger, cron
    `0 */2 * * *` — every 2 hours) — **currently deleted** (paused 22 Oct while iterating heavily
    during the day, to avoid matches auto-firing in the background during active dev). Exists so
    the public site isn't showing an idle page if a judge visits between manually-triggered
    real-mode runs during the Oct 27 - Nov 10 judging period (15 days; see official rules --
    judging doesn't end at submission). **Must be recreated before judging starts** (see the
    command below) -- it is not currently running.
    `--seed` and `--speed` are both omitted (random seed, real-time `--speed 1` from the image's
    default CMD), so every execution is a different ~90-minute match written to its own
    `seed-<n>` Cosmos document. Estimated cost for running the full judging window: **~$5-15**
    (Container Apps compute only -- mock mode means $0 LLM cost; Cosmos/Web PubSub/Static Web
    App/negotiate all stay in free tiers at this traffic level). Estimate, not a live quote --
    there's a $20 subscription budget alert as a backstop.
    - **Turn off:** `az containerapp job delete --name matchhealth-demo --resource-group
      matchhealth-rg --yes`
    - **Turn back on:**
      ```
      az containerapp job create --name matchhealth-demo --resource-group matchhealth-rg \
        --environment matchhealth-env --image ghcr.io/illtrotrac/matchhealthai:latest \
        --trigger-type Schedule --cron-expression "0 */2 * * *" --replica-timeout 6000 \
        --replica-retry-limit 1 --parallelism 1 --cpu 0.5 --memory 1Gi --mi-system-assigned \
        --env-vars MATCHHEALTH_MOCK_LLM=1 \
        COSMOS_ENDPOINT=https://matchhealth-cosmos.documents.azure.com:443/ \
        COSMOS_DATABASE=matchhealth COSMOS_CONTAINER=moments \
        WEBPUBSUB_ENDPOINT=https://matchhealth-pubsub.webpubsub.azure.com WEBPUBSUB_HUB=overlays
      ```
      then re-grant its new identity (gets a new principal ID each time the job is recreated) the
      Cosmos SQL role `00000000-0000-0000-0000-000000000002` via `az cosmosdb sql role assignment
      create` and the `Web PubSub Service Owner` role via `az role assignment create` -- see git
      history for the exact commands used the first time.
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
- [x] Port orchestrator to Agent Framework (Workflow + Executors, conditional recovery edges).
- [ ] Add Agent Framework tracing to App Insights.
- [x] Full-time recap generation — done by the Narrator agent, plus storylines and checkpoints.
- [ ] Record the < 2 min demo video.
