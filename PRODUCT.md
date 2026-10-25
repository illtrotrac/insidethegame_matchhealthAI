# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Football fans watching a match on a second screen. Two kinds share one page:

- **Casual fans** want the story: what just happened and why it matters, in plain words.
- **Data-hungry analysts** want the numbers behind it: xG, pressing, territory, passing.

Hackathon judges evaluate the product by using it as one of these fans would, often arriving mid-match and staying a few minutes.

## Product Purpose

Match Health turns a stream of football events into explained, personalised match intelligence while the match is live. A deterministic engine tracks each team's control, raises an alert when a moment matters, and a crew of AI agents explains why, renders it as a broadcast overlay, and rewrites it for each viewer's mode and language.

Success: a fan who opens the page at any minute understands the match so far, and the reason behind each big moment, within seconds.

## Positioning

"Observability for football": the match is monitored like a production system. Plain code computes every number and decides when something is worth explaining. The AI only explains facts it was given, and every number it writes is checked against those facts before it reaches the screen. One crew produces two genuinely different experiences, casual and analyst, in five languages from a single pass.

## Operating Context

- **Live public demo:** a new fictional match starts every 20 minutes, replayed at 6× speed (about 15 minutes), followed by a full-time recap and a pipeline audit. Viewers can open the page at any moment and see everything so far immediately.
- **Viewer controls:** mode (Casual / Analyst), language (English, Español, Français, Português, Deutsch), follow a player, pin one metric, and, in analyst mode, a club filter.
- **"On air":** shows the overlay exactly as a broadcast would, and can go full screen.
- **Live demo vs video:** the demo runs in mock mode (template text, no model calls) to stay free during judging. The real Microsoft Foundry-backed crew runs on demand and appears in the demo video.

## Capabilities and Constraints

- **Hackathon entry:** Microsoft × Premier League "Inside the Game".
  - Submission deadline: 27 Oct 2026, 11:59 pm PT.
  - The live demo must stay testable, free of charge, until 10 Nov 2026.
  - No long-term roadmap beyond judging.
- **Synthetic data only:**
  - A fictional eight-club league with invented player names.
  - No real teams, players, footage or data, and no Premier League trademarks, in the product or the video.
- **Capabilities:**
  - Live overlays, and the Narrator's storylines, check-ins, chart briefings and recap.
  - Line-ups with benches, substitutions and changes since the last two games.
  - Analyst charts: xG race, win probability, pressing (PPDA), field tilt, zones, player profile, hard passes and shot map.
  - Win/draw/loss estimate, and a full-time pipeline audit.
- **Terminology:**
  - "Control" is each team's own 0–100 index. It is not possession.
  - Use "moment", "overlay", "On air", "Match story", "Narrator", "Spotter / Analyst / Producer / Personaliser".
- **Technical:**
  - The frontend is a single static page served by Azure Static Web Apps.
  - It receives live data over Azure Web PubSub. There is no user login and no stored user data.

## Brand Commitments

- Name: **Match Health AI**.
- Voice: plain, sentence case, specific. Explains rather than hypes. Neutral between clubs.
- Every number shown must come from the match data. Never invent statistics, history or quotes.

## Evidence on Hand

- Live demo: https://polite-wave-086f2900f.2.azurestaticapps.net
- Code and docs: `README.md`, `docs/architecture.md`, `docs/agent-workflow.md`, `docs/submission.md`
- 33 automated tests, including accuracy tests against the raw events (`tests/`).
- No real users, testimonials, press, benchmarks or customers exist. Do not fabricate any.

## Product Principles

1. **Explain, don't just report.** Every moment shown answers "why does this matter?".
2. **Numbers come from code, words from agents.** No figure on screen that the match data can't back.
3. **Two experiences, one truth.** Casual and analyst differ in depth and tone, never in facts.
4. **Never a blank screen.** A late arrival, a failed agent or a gap between matches still shows something true and useful.
5. **Free to run, honest about limits.** Design within free tiers, and say plainly what is simulated or mocked.
