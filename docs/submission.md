# Submission text

## Project name
Match Health AI

## One-line pitch
Observability for football: a deterministic engine spots the moments that matter, and a five-agent crew on Microsoft Foundry and Agent Framework explains why, live, as broadcast overlays personalised for every fan in five languages.

## Elevator pitch (what, which Microsoft tech, what it does, what problem it solves)
Football coverage reports what happened; fans want to know why it mattered. Match Health treats a match like a production system:

- **A deterministic engine** reads synthetic match events, tracks each team's control, and raises an alert when something important happens: a goal, a pressing spell, a momentum swing.
- **Five AI agents** then work like a TV production crew. A Spotter judges whether it's a story, an Analyst explains why it matters, a Producer renders a timed broadcast overlay, and a Personaliser rewrites it for casual fans and data-hungry analysts in five languages. Across the whole match, a Narrator writes storylines, check-ins, chart briefings and the full-time recap.
- **Microsoft stack:** the crew runs as a **Microsoft Agent Framework** workflow on **Microsoft Foundry** (`gpt-4.1-mini`), with every handoff stored in **Azure Cosmos DB**. Overlays reach viewers through **Azure Web PubSub** and an **Azure Static Web App**. Matches run as scale-to-zero **Azure Container Apps** jobs, and everything uses managed identity.
- **Trust:** every number the agents write is checked in code against the facts they were given, so invented numbers never reach the screen. A full-time audit confirms every moment went through every agent.

## Testing instructions
- **Live demo (no login):** https://polite-wave-086f2900f.2.azurestaticapps.net
  - A new fictional match starts every 20 minutes, replayed at 6× speed (about 15 minutes), followed by its full-time recap and audit. Opening the page mid-match shows everything so far immediately.
  - Try **Casual / Analyst** at the top, **Language** (English, Español, Français, Português, Deutsch), **Follow** a player, and **Your metric**.
  - In Analyst mode, click the chart tabs and **Summarise these charts**.
  - **On air → Full screen** shows the broadcast view.
- **The public demo runs in mock mode** (template text instead of model calls) so it stays free for the whole judging window. The demo video shows the same pipeline with the real Foundry-backed agents.
- **Run locally without Azure:** follow "Run it locally" in the README:

  ```
  pip install -e ".[dev,preview]"
  python -m matchhealth.run --offline --preview --speed 20
  ```

  Then open `web/index.html`. Tests: `pytest` (33 tests, including accuracy tests against the raw events).
- **Code:** https://github.com/illtrotrac/insidethegame_matchhealthAI

## Category
Grand Prize, and **Best Multi-Agent System**. The alternative would be Best Azure Cloud Native Integration.
