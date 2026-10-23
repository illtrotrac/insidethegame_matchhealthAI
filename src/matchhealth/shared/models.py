"""Core data models shared by the replay, engine and agents."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

EventType = Literal[
    "kickoff", "pass", "shot", "tackle", "pressure", "possession_change",
    "foul", "goal", "half_time", "full_time", "substitution",
]

TriggerKind = Literal[
    "control_swing", "big_chance", "pressing_spell", "speed_milestone", "goal", "foul",
    "pass_quality",
]

Template = Literal[
    "lower_third_stat", "player_tag", "stat_compare", "momentum_chart",
    "big_chance", "stats_only_fallback",
]


class MatchEvent(BaseModel):
    id: int
    t: float  # seconds since kick-off
    type: EventType
    team: str
    player: str | None = None
    x: float | None = None
    y: float | None = None
    end_x: float | None = None
    end_y: float | None = None
    outcome: str | None = None
    speed_kmh: float | None = None
    player_off: str | None = None  # substitution: who came off (player = who came on)


class HealthSnapshot(BaseModel):
    """Rolling match health for one team over the engine's window."""

    team: str
    control: float = Field(ge=0, le=100)
    chaos: float = Field(ge=0)
    possession_pct: float
    pass_completion_pct: float


class Trigger(BaseModel):
    moment_id: str
    kind: TriggerKind
    t: float
    team: str
    player: str | None = None
    facts: dict  # numbers the agents may cite; agents must not invent others
    x: float | None = None  # where it happened, pitch metres (105 x 68)
    y: float | None = None


class Explanation(BaseModel):
    moment_id: str
    why: str
    key_stats: list[dict] = Field(default_factory=list)


class OverlayStat(BaseModel):
    label: str
    value: float | str | None = None
    from_: float | None = Field(default=None, alias="from")
    to: float | None = None
    unit: str | None = None

    model_config = {"populate_by_name": True}


class Overlay(BaseModel):
    moment_id: str
    template: Template
    show_at: str
    duration_s: int = Field(ge=4, le=12)
    priority: int = Field(ge=1, le=3)
    headline: str = Field(max_length=80)
    subline: str | None = Field(default=None, max_length=90)
    stats: list[OverlayStat] = Field(default_factory=list, max_length=3)
    focus_player: str | None = None
    mode: Literal["base", "analyst", "casual"] = "base"
    language: str = "en"

    def to_wire(self) -> dict:
        return self.model_dump(by_alias=True, exclude_none=False)


def clock(t: float) -> str:
    """Seconds -> 'MM:SS' match clock."""
    return f"{int(t // 60)}:{int(t % 60):02d}"
