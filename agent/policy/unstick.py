"""Wrap a policy so the hero sidesteps when walking into an obstacle.

Live run 2026-11-26 (A_Combat24): the heuristic walked straight at enemies
behind a block and stood still for three minutes. The policy cannot see room
geometry, so detect "trying to move but not moving" from visible positions and
sidestep at +/-90 degrees, alternating sides on repeated sticks.
"""
from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass

import numpy as np



@dataclass(frozen=True)
class UnstickConfig:
    window: int = 6          # decisions to look back
    min_travel: float = 40.0  # world units over the window while moving
    escape_steps: int = 8


class UnstickPolicy:
    def __init__(self, base, config: UnstickConfig | None = None) -> None:
        self.base = base
        self.config = config or UnstickConfig()
        self.reset()

    def reset(self) -> None:
        self.base.reset()
        self._trail: deque = deque(maxlen=self.config.window)
        self._escape = 0
        self._escape_move = 0
        self._side = 1

    def act(self, raw_obs: dict) -> np.ndarray:
        action = self.base.act(raw_obs)
        hero = raw_obs.get("hero") or {}
        pos = (hero.get("x"), hero.get("y"))
        if None in pos:
            return action
        if self._escape > 0:
            self._escape -= 1
            action = action.copy()
            action[0] = self._escape_move
            self._trail.clear()
            return action
        moving = int(action[0]) != 0
        self._trail.append((pos, moving))
        if len(self._trail) == self._trail.maxlen and all(m for _, m in self._trail):
            (x0, y0), _ = self._trail[0]
            if math.hypot(pos[0] - x0, pos[1] - y0) < self.config.min_travel:
                # Rotate the intended direction by 90 degrees (2 of 8 sectors).
                sector = int(action[0]) - 1
                self._escape_move = (sector + 2 * self._side) % 8 + 1
                self._side = -self._side
                self._escape = self.config.escape_steps
                self._trail.clear()
                action = action.copy()
                action[0] = self._escape_move
        return action
