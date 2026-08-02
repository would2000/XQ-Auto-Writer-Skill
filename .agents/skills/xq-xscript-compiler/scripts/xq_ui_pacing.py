#!/usr/bin/env python3
"""Shared, safety-bounded pacing profiles for XQ desktop input."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


DEFAULT_UI_PACE_LEVEL = 5
PACE_LEVEL_MULTIPLIERS = {
    1: 2.00,
    2: 1.75,
    3: 1.50,
    4: 1.25,
    5: 1.00,
    6: 0.80,
    7: 2.0 / 3.0,
    8: 0.55,
    9: 0.50,
    10: 0.45,
}


class UiPacingError(ValueError):
    """An invalid pacing preference that must not reach desktop input."""


@dataclass(frozen=True)
class UiPacing:
    level: int
    multiplier: float
    action_interval_floor_seconds: float
    keyboard_pause_floor_seconds: float

    def scale(self, seconds: float, *, floor_seconds: float = 0.0) -> float:
        if isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or seconds < 0:
            raise UiPacingError("Pacing input must be a non-negative number")
        return max(float(floor_seconds), float(seconds) * self.multiplier)

    def action_interval(self, baseline_seconds: float) -> float:
        return self.scale(
            baseline_seconds,
            floor_seconds=self.action_interval_floor_seconds,
        )

    def keyboard_pause(self, baseline_seconds: float) -> float:
        return self.scale(
            baseline_seconds,
            floor_seconds=self.keyboard_pause_floor_seconds,
        )

    def evidence(self) -> dict[str, float | int]:
        return asdict(self)


def _number(value: Any, label: str, minimum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or float(value) < minimum:
        raise UiPacingError(f"{label} must be at least {minimum:g}")
    return float(value)


def load_ui_pacing(config: dict[str, Any] | None, requested_level: int | None = None) -> UiPacing:
    """Resolve a requested profile without allowing a safety-floor bypass."""
    root = (config or {}).get("ui_pacing", {})
    if not isinstance(root, dict):
        raise UiPacingError("ui_pacing must be an object")
    configured_level = root.get("default_level", DEFAULT_UI_PACE_LEVEL)
    level = configured_level if requested_level is None else requested_level
    if isinstance(level, bool) or not isinstance(level, int) or level not in PACE_LEVEL_MULTIPLIERS:
        raise UiPacingError("UI pace level must be an integer from 1 to 10")
    return UiPacing(
        level=level,
        multiplier=PACE_LEVEL_MULTIPLIERS[level],
        action_interval_floor_seconds=_number(
            root.get("action_interval_floor_seconds", 1.0),
            "ui_pacing.action_interval_floor_seconds",
            1.0,
        ),
        keyboard_pause_floor_seconds=_number(
            root.get("keyboard_pause_floor_seconds", 0.02),
            "ui_pacing.keyboard_pause_floor_seconds",
            0.0,
        ),
    )
