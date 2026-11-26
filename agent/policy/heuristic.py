"""Scripted, sword-oriented baseline using only visible observations."""

import math
from dataclasses import dataclass

import numpy as np

from agent.env.actions import AIM_SECTORS, ATTACK, CAST, DASH, IDLE, aim_sector
from agent.env.observations import nearest_units, visible_hud


@dataclass(frozen=True)
class HeuristicConfig:
    # Initial values in world units. Calibrate against the actual weapon and room.
    preferred_min: float = 90.0
    preferred_max: float = 180.0
    attack_range: float = 200.0
    facing_tolerance: float = 45.0  # degrees
    dash_range: float = 95.0
    cast_min: float = 160.0
    cast_max: float = 550.0
    recent_damage_steps: int = 3  # includes the decision that sees the HP drop


class HeuristicPolicy:
    def __init__(self, config: HeuristicConfig | None = None) -> None:
        self.config = config or HeuristicConfig()
        self.reset()

    def reset(self) -> None:
        self._previous_hp: float | None = None
        self._damage_steps = 0
        self._previous_button = IDLE

    def act(self, raw_obs: dict) -> np.ndarray:
        """Choose [movement, button, aim] from the env's visible raw_obs."""
        hero = raw_obs.get("hero", {})
        hud = visible_hud(raw_obs)
        hp = hud.get("hp")
        if hp is not None and self._previous_hp is not None and hp < self._previous_hp:
            self._damage_steps = self.config.recent_damage_steps
        self._previous_hp = hp
        movement, button, aim = self._choose(hero, hud, raw_obs.get("enemies", []))
        self._damage_steps = max(0, self._damage_steps - 1)

        # Consecutive held buttons emit one down event. Insert a release so
        # the next decision can trigger a fresh attack, cast or dash.
        if button == self._previous_button:
            button = IDLE
        self._previous_button = button
        return np.array([movement, button, aim], dtype=np.int64)

    def _choose(self, hero: dict, hud: dict, enemies: list[dict]) -> tuple[int, int, int]:
        config = self.config
        facing = math.radians(hero.get("angle") or 0.0)
        targets = nearest_units(hero, enemies)
        if not targets:
            return 0, IDLE, aim_sector(facing)

        distance, dx, dy, _ = targets[0]
        angle = math.atan2(-dy, dx) if distance else facing
        aim = aim_sector(angle)
        toward = aim + 1
        away = (aim + AIM_SECTORS // 2) % AIM_SECTORS + 1
        facing_delta = math.remainder(angle - facing, math.tau)
        facing_target = abs(facing_delta) <= math.radians(config.facing_tolerance)
        if distance < config.dash_range and self._damage_steps:
            return away, DASH, aim

        movement = 0
        if distance < config.preferred_min:
            movement = away
        elif distance > config.preferred_max or not facing_target:
            # Movement turns Zagreus if his body is still facing away.
            movement = toward

        if (hud.get("castAmmo") or 0) > 0 and config.cast_min <= distance <= config.cast_max:
            return movement, CAST, aim
        if distance <= config.attack_range and facing_target:
            return movement, ATTACK, aim
        return movement, IDLE, aim
