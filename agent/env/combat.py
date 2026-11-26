"""Gymnasium environment for a single combat encounter in a running game."""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass
from typing import Protocol

import gymnasium as gym
import numpy as np

from agent.bridge.game import BridgeMessage
from agent.input import Action

from .actions import AIM_SECTORS, BUTTONS, MOVEMENTS, decode_action
from .observations import OBSERVATION_SIZE, HistoryEncoder


class Bridge(Protocol):
    latest_obs: BridgeMessage | None

    def policy_obs(self) -> dict | None: ...
    def command(self, cmd: str, timeout: float = 10.0, **fields) -> dict: ...


class InputController(Protocol):
    def apply(self, action: Action) -> None: ...
    def release_all(self) -> None: ...


@dataclass(frozen=True)
class RewardConfig:
    enemy_damage_scale: float = 100.0  # HP and armour points per reward unit
    hero_damage_weight: float = 2.0    # per max HP lost
    kill_bonus: float = 0.25
    room_clear_bonus: float = 2.0
    death_penalty: float = 2.0
    time_penalty: float = 0.01         # per decision

    def __post_init__(self) -> None:
        if not math.isfinite(self.enemy_damage_scale) or self.enemy_damage_scale <= 0:
            raise ValueError("enemy_damage_scale must be positive and finite")


@dataclass(frozen=True)
class CombatConfig:
    frames_per_step: int = 2
    max_steps: int = 1800  # three minutes at two 0.05 s frames per step
    reset_timeout: float = 60.0  # wall seconds, including manual room entry
    step_timeout: float = 3.0    # wall seconds
    poll_interval: float = 0.005
    game_speed: float | None = None  # None leaves the bridge's current speed in place
    reward: RewardConfig = RewardConfig()

    def __post_init__(self) -> None:
        for value in (self.frames_per_step, self.max_steps):
            if not isinstance(value, int) or value < 1:
                raise ValueError("Frame and step counts must be positive integers")
        for value in (self.reset_timeout, self.step_timeout, self.poll_interval):
            if not math.isfinite(value) or value <= 0:
                raise ValueError("Timeouts and poll interval must be positive and finite")
        if self.game_speed is not None and not 0.1 <= self.game_speed <= 10.0:
            raise ValueError("Game speed must be between 0.1 and 10.0")


@dataclass(frozen=True)
class _Snapshot:
    frame: int
    visible: dict
    message: BridgeMessage


def _combat(snapshot: _Snapshot) -> bool | None:
    return snapshot.visible.get("room", {}).get("combat")


def _dead(snapshot: _Snapshot) -> bool:
    # A zero HP frame can precede Death Defiance. The visible death state wins.
    return snapshot.visible.get("hero", {}).get("dead") is True


def _paused(snapshot: _Snapshot) -> bool:
    # Any engine menu on top (pause, the corrupted-save notice seen live as
    # "ExitConfirmDialog", ...) swallows input, so it is not a decision frame.
    return snapshot.visible.get("screen") not in (None, "InGameUI")


def _room_changed(before: _Snapshot, after: _Snapshot) -> bool:
    old = before.visible.get("room", {})
    new = after.visible.get("room", {})
    return any(key in old and key in new and old[key] != new[key] for key in ("name", "depth"))


def _decision_frame(snapshot: _Snapshot) -> bool:
    return _dead(snapshot) or (_combat(snapshot) is not None and not _paused(snapshot))


def _outcome(before: _Snapshot, after: _Snapshot) -> str | None:
    if _dead(after):
        return "dead"
    if _room_changed(before, after):
        return "room_changed"
    if _combat(after) is False:
        return "cleared"
    return None


def _enemy_health(reward_data: dict) -> dict | None:
    rows = reward_data.get("enemyHealth")
    if not isinstance(rows, list):
        return None
    return {
        row["id"]: max(0, row["hp"]) + max(0, row.get("armor") or 0)
        for row in rows
        if "id" in row and row.get("hp") is not None
    }


def _combat_reward(before: _Snapshot, after: _Snapshot, outcome: str | None, config: RewardConfig) -> float:
    """Hidden bridge data is read here for reward calculation only."""
    old = before.message.data.get("info") or {}
    new = after.message.data.get("info") or {}
    reward = -config.time_penalty

    old_enemies, new_enemies = _enemy_health(old), _enemy_health(new)
    if old_enemies is not None and new_enemies is not None:
        for enemy_id, health in old_enemies.items():
            if enemy_id in new_enemies:
                reward += max(0, health - new_enemies[enemy_id]) / config.enemy_damage_scale
            elif outcome != "dead":
                # A removed enemy in the same room is the available kill proxy.
                # On death the room may unload all units, so skip removals then.
                reward += health / config.enemy_damage_scale + config.kill_bonus

    old_hp, new_hp = old.get("heroHealth"), new.get("heroHealth")
    max_hp = before.visible.get("hero", {}).get("maxHp") or 0
    if old_hp is not None and new_hp is not None and max_hp > 0:
        reward -= config.hero_damage_weight * max(0, old_hp - new_hp) / max_hp

    if outcome == "cleared":
        reward += config.room_clear_bonus
    if outcome == "dead":
        reward -= config.death_penalty
    return reward


class HadesCombatEnv(gym.Env):
    """Drive one combat room. The caller owns the bridge lifecycle.

    Reset waits for the operator or macro layer to enter combat. The reset seed
    covers Gymnasium's RNG only. The live game retains its own state and RNG.
    """

    metadata = {"render_modes": []}

    def __init__(
        self,
        bridge: Bridge,
        controller: InputController,
        *,
        window_size: tuple[float, float] = (1920, 1080),
        config: CombatConfig | None = None,
    ) -> None:
        if len(window_size) != 2 or any(not math.isfinite(side) or side <= 0 for side in window_size):
            raise ValueError("Window dimensions must be positive and finite")
        self.bridge = bridge
        self.controller = controller
        self.window_size = window_size
        self.config = config or CombatConfig()
        self.action_space = gym.spaces.MultiDiscrete([len(MOVEMENTS), len(BUTTONS), AIM_SECTORS])
        self.observation_space = gym.spaces.Box(-1.0, 1.0, (OBSERVATION_SIZE,), np.float32)
        self._snapshot: _Snapshot | None = None
        self._steps = 0
        self._speed_set = False
        # Per-episode visible history (previous actions, motion), task 009.
        self._encoder = HistoryEncoder()

    def _latest_snapshot(self) -> _Snapshot | None:
        message = self.bridge.latest_obs
        if message is None or message.frame is None:
            return None
        visible = self.bridge.policy_obs()
        # The reader can publish a new message between these reads. Retry so
        # the vector and reward always describe the same frame.
        if visible is None or self.bridge.latest_obs is not message:
            return None
        return _Snapshot(message.frame, visible, message)

    def _await_snapshot(
        self, predicate: Callable[[_Snapshot], bool], deadline: float,
    ) -> _Snapshot | None:
        while True:
            snapshot = self._latest_snapshot()
            if snapshot is not None and predicate(snapshot):
                return snapshot
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            time.sleep(min(self.config.poll_interval, remaining))

    def reset(self, *, seed: int | None = None, options: dict | None = None) -> tuple[np.ndarray, dict]:
        super().reset(seed=seed)
        self.close()
        self._steps = 0
        deadline = time.monotonic() + self.config.reset_timeout

        def active(snapshot: _Snapshot) -> bool:
            return _combat(snapshot) is True and not _dead(snapshot) and not _paused(snapshot)

        snapshot = self._await_snapshot(active, deadline)
        speed = self.config.game_speed
        if snapshot is not None and speed is not None and not self._speed_set:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("No time left to set game speed")
            self.bridge.command("speed", timeout=remaining, value=speed)
            self._speed_set = True
            snapshot = self._await_snapshot(active, deadline)
        if snapshot is None:
            raise TimeoutError(f"No active combat within {self.config.reset_timeout:g} wall seconds")
        self._snapshot = snapshot
        self._encoder.reset()
        return self._encoder.encode(snapshot.visible, snapshot.frame), {"raw_obs": deepcopy(snapshot.visible)}

    def step(self, action: np.ndarray) -> tuple[np.ndarray, float, bool, bool, dict]:
        before = self._snapshot
        if before is None:
            raise gym.error.ResetNeeded("Call reset() before stepping into combat")
        try:
            return self._step(before, action)
        except BaseException as error:
            try:
                self.close()
            except BaseException as cleanup_error:
                error.add_note(f"Input cleanup failed: {cleanup_error!r}")
            raise

    def _step(self, before: _Snapshot, action: np.ndarray) -> tuple[np.ndarray, float, bool, bool, dict]:
        if not self.action_space.contains(action):
            raise ValueError(f"Invalid combat action: {action!r}")

        # The room may have ended while the caller was deciding. Read the
        # current scene before posting an attack that could land on a menu.
        after = self._await_snapshot(_decision_frame, time.monotonic() + self.config.step_timeout)
        outcome = None if after is None else _outcome(before, after)
        if after is not None and outcome is None:
            self.controller.apply(decode_action(action, self.window_size))
            self._encoder.record_action(action)

            # Count from the end of apply, so pre-action frames do not shorten
            # the decision interval when the game runs faster than the agent.
            message = self.bridge.latest_obs
            start_frame = after.frame if message is None or message.frame is None else message.frame
            target_frame = start_frame + self.config.frames_per_step

            after = self._await_snapshot(
                lambda snapshot: snapshot.frame >= target_frame and _decision_frame(snapshot),
                time.monotonic() + self.config.step_timeout,
            )
            outcome = None if after is None else _outcome(before, after)

        self._steps += 1
        if after is None:
            outcome = "timeout"
            after = before
            reward = -self.config.reward.time_penalty
        elif outcome == "room_changed":
            reward = -self.config.reward.time_penalty
        else:
            if outcome is None and self._steps >= self.config.max_steps:
                outcome = "step_limit"
            reward = _combat_reward(before, after, outcome, self.config.reward)

        terminated = outcome in ("cleared", "dead")
        truncated = outcome in ("timeout", "step_limit", "room_changed")
        self._snapshot = after
        if terminated or truncated:
            self.close()
        info = {"raw_obs": deepcopy(after.visible), "outcome": outcome}
        return self._encoder.encode(after.visible, after.frame), float(reward), terminated, truncated, info

    def close(self) -> None:
        self._snapshot = None
        self.controller.release_all()
