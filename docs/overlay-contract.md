# Overlay contract

The Producer emits one **base overlay** per moment; the Personaliser emits **variants** of it. The frontend renders both from `schemas/overlay.schema.json`.

## Templates

| Template | Use |
|---|---|
| `lower_third_stat` | One insight plus 1–3 stats (default) |
| `player_tag` | Name tag, optional speed/distance when a threshold is hit |
| `stat_compare` | Team vs team bar (e.g. control score) |
| `momentum_chart` | Short match health sparkline pop-up |
| `big_chance` | Shot card: shot speed, quality, angle |
| `stats_only_fallback` | Used when the Analyst fails or validation fails |

## Rules
- `priority`: 1 (highest) to 3. A higher-priority overlay may interrupt a lower one, never the reverse.
- `duration_s`: 4–12.
- Variants may change `headline`, `subline`, `language`, `mode`, `focus_player` only.
