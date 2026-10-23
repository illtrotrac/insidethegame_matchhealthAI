"""Per-event football metrics. Deterministic; no LLM."""

from __future__ import annotations

import math

from matchhealth.shared.models import MatchEvent


def pass_distance(ev: MatchEvent) -> float | None:
    if None in (ev.x, ev.y, ev.end_x, ev.end_y):
        return None
    return math.hypot(ev.end_x - ev.x, ev.end_y - ev.y)


def pass_difficulty(ev: MatchEvent, under_pressure: bool = False) -> float | None:
    """0 (trivial) .. 1 (very hard). Length, lateral angle and pressure raise difficulty."""
    d = pass_distance(ev)
    if d is None:
        return None
    lateral = abs(ev.end_y - ev.y) / max(d, 1e-6)
    score = 0.5 * min(d / 40, 1) + 0.2 * lateral + (0.3 if under_pressure else 0)
    return round(min(score, 1.0), 2)


def shot_quality(ev: MatchEvent, attacking_goal_x: float) -> float:
    """Crude expected-goals proxy from distance and angle to goal centre (0..1)."""
    dx = abs(attacking_goal_x - (ev.x or 0))
    dy = abs((ev.y or 34) - 34)
    dist = math.hypot(dx, dy)
    angle = math.atan2(7.32 * dx, dx**2 + dy**2 - (7.32 / 2) ** 2) if dx else math.pi / 2
    return round(max(0.0, min(1.0, 0.9 * angle / (math.pi / 2) * math.exp(-dist / 25))), 2)


def win_draw_loss(home: str, away: str, score: dict[str, int],
                   xg: dict[str, float], t: float) -> dict[str, float]:
    """Simple deterministic win/draw/loss split -- a heuristic blend of goal
    difference and cumulative xG differential, NOT a trained model (no Poisson/
    Dixon-Coles fit here, just something directionally honest for a live
    broadcast). Compressed toward an even split early in the match (more time
    left = more uncertainty) and sharpens toward the actual scoreline as full
    time approaches.
    """
    edge = (score[home] - score[away]) + 0.15 * (xg[home] - xg[away])
    time_left_frac = max(0.0, min(1.0, (5400 - t) / 5400))
    temperature = 1.0 + 3.0 * time_left_frac
    home_s = math.exp(edge / temperature)
    away_s = math.exp(-edge / temperature)
    draw_s = math.exp(-abs(edge) / (temperature * 0.8)) * (0.9 + 0.6 * time_left_frac)
    total = home_s + away_s + draw_s
    return {
        "home_win_pct": round(100 * home_s / total, 1),
        "draw_pct": round(100 * draw_s / total, 1),
        "away_win_pct": round(100 * away_s / total, 1),
    }
