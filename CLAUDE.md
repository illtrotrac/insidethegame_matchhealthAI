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

## Next steps
- [ ] Wire `LLMClient` to Foundry deployments (mini + nano).
- [ ] Port orchestrator to Agent Framework; add tracing to App Insights.
- [ ] Web overlay: subscribe to Web PubSub, render the 6 templates, persona picker.
- [ ] Bicep in `infra/`, GitHub Actions deploy.
- [ ] Full-time recap generation (one call over stored moments).
- [ ] Record the < 2 min demo video.
