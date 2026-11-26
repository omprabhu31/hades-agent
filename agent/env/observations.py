"""Fixed-size observation encoding using the bridge's visible fields."""

import math
from collections import deque

import numpy as np

POSITION_SCALE = 1000.0  # world units per normalised unit, clipped to the Box bounds
MAX_ENEMIES = 8
MAX_TRAPS = 4
MAX_BREAKABLES = 8

HERO_FIELDS = ("hp_fraction", "cast_ammo", "last_stands", "call_pips")
ENEMY_FIELDS = ("dx", "dy", "distance", "hpFrac", "armorFrac", "shields", "boss", "elite", "present")
TRAP_FIELDS = ("dx", "dy", "disabled", "present")
BREAKABLE_FIELDS = ("dx", "dy", "present")
BASE_SIZE = (
    len(HERO_FIELDS)
    + MAX_ENEMIES * len(ENEMY_FIELDS)
    + MAX_TRAPS * len(TRAP_FIELDS)
    + MAX_BREAKABLES * len(BREAKABLE_FIELDS)
    + 1  # combat active
)

# History features (task 009). Behaviour cloning reached only ~40% movement
# accuracy because the teacher's choices depend on recent motion and button
# history that a single frame does not show. Everything here is visible to a
# player: facing and motion on screen, the HP bar dropping, their own inputs.
ACTION_SIZES = (9, 5, 8)          # movement, button, aim (agent.env.actions)
PREVIOUS_ACTIONS = 2
# Motion is measured per bridge frame (0.05 s of game time), not per decision:
# decisions are ~2 frames apart in BC data, 2-3 live at speed 1 and ~6 at speed
# 3 (review 012). With 50 units/frame, a 2-frame step gives the old values.
VELOCITY_PER_FRAME = 50.0         # world units per frame per normalised unit
TRAIL_FRAMES = 12                 # 0.6 s window for the "am I stuck?" travel feature
DEFAULT_FRAME_STEP = 2            # assumed spacing when callers pass no frame number
HISTORY_SIZE = (
    2                              # facing sin, cos
    + 2                            # hero velocity dx, dy
    + 1                            # hero travel over the trail window
    + 1                            # recency of the last HP drop
    + PREVIOUS_ACTIONS * sum(ACTION_SIZES)
    + MAX_ENEMIES * 2              # velocity of each enemy slot
)
# Enemy attacks (task 014): which of the visible enemy and trap slots just
# attacked (the swing or shot is drawn on the attacker). Projectile launches are
# logging-only until a drawn cue can be verified (review 016). Kept as a
# separate block so the base layout is stable.
ATTACK_MEMORY_S = 2.0             # matches the mod's AttackMemory (seconds of world time)
ATTACK_SIZE = MAX_ENEMIES + MAX_TRAPS
HISTORY_START = BASE_SIZE + ATTACK_SIZE
OBSERVATION_SIZE = BASE_SIZE + ATTACK_SIZE + HISTORY_SIZE


def _position(unit: dict) -> tuple[float, float] | None:
    x, y = unit.get("x"), unit.get("y")
    if x is None or y is None:
        return None
    return x, y


def nearest_units(hero: dict, units: list[dict]) -> list[tuple[float, float, float, dict]]:
    """Return (distance, dx, dy, unit) rows. World Y increases downwards."""
    origin = _position(hero)
    if origin is None:
        return []
    rows = []
    for unit in units:
        location = _position(unit)
        if location is not None:
            dx, dy = location[0] - origin[0], location[1] - origin[1]
            rows.append((math.hypot(dx, dy), dx, dy, unit))
    # ActiveEnemies comes from a Lua hash table. Break distance ties by object ID.
    return sorted(rows, key=lambda row: (row[0], row[3].get("id", 0)))


def _offset(value: float) -> float:
    return max(-1.0, min(1.0, value / POSITION_SCALE))


def _fraction(value: float | None) -> float:
    return max(0.0, min(1.0, value or 0.0))


def _count(value: float | None) -> float:
    # Compress variable pip/ammo counts into [0, 1] while preserving order.
    count = max(0.0, value or 0.0)
    return count / (1.0 + count)


def visible_hud(obs: dict) -> dict:
    """Return the hero's HUD values when it is drawn (missing flag is allowed)."""
    return {} if obs.get("hud") is False else obs.get("hero", {})


def encode_observation(obs: dict) -> np.ndarray:
    """Encode hero, eight enemies, four traps, eight breakables, then combat.

    Positions and distances are divided by POSITION_SCALE and clipped to the
    bounds. Health and armour are fractions. Counts use n / (1 + n), with
    partial call fill added to full pips first. Missing values and vacant slots
    are zero. The present bit distinguishes vacant slots from overlapping units.
    """
    hero = obs.get("hero", {})
    hud = visible_hud(obs)
    max_hp = hud.get("maxHp") or 0
    hp_fraction = (hud.get("hp") or 0) / max_hp if max_hp > 0 else 0
    call_pips = (hud.get("callPips") or 0) + (hud.get("callPipPartial") or 0)
    vector = np.zeros(BASE_SIZE, dtype=np.float32)
    vector[:len(HERO_FIELDS)] = (
        _fraction(hp_fraction), _count(hud.get("castAmmo")), _count(hud.get("lastStands")), _count(call_pips),
    )
    offset = len(HERO_FIELDS)
    for index, (distance, dx, dy, enemy) in enumerate(nearest_units(hero, obs.get("enemies", []))[:MAX_ENEMIES]):
        start = offset + index * len(ENEMY_FIELDS)
        vector[start:start + len(ENEMY_FIELDS)] = (
            _offset(dx), _offset(dy), _offset(distance), _fraction(enemy.get("hpFrac")),
            _fraction(enemy.get("armorFrac")), _count(enemy.get("shields")),
            bool(enemy.get("boss")), bool(enemy.get("elite")), 1,
        )
    offset += MAX_ENEMIES * len(ENEMY_FIELDS)
    for index, (_, dx, dy, trap) in enumerate(nearest_units(hero, obs.get("traps", []))[:MAX_TRAPS]):
        start = offset + index * len(TRAP_FIELDS)
        vector[start:start + len(TRAP_FIELDS)] = (_offset(dx), _offset(dy), bool(trap.get("disabled")), 1)
    offset += MAX_TRAPS * len(TRAP_FIELDS)
    for index, (_, dx, dy, _) in enumerate(nearest_units(hero, obs.get("breakables", []))[:MAX_BREAKABLES]):
        start = offset + index * len(BREAKABLE_FIELDS)
        vector[start:start + len(BREAKABLE_FIELDS)] = (_offset(dx), _offset(dy), 1)
    vector[-1] = bool(obs.get("room", {}).get("combat"))
    return vector


def _recency(seconds_ago) -> float:
    """1 = attacked just now, falling linearly to 0 at ATTACK_MEMORY_S; 0 if not recent."""
    if seconds_ago is None:
        return 0.0
    return max(0.0, 1.0 - float(seconds_ago) / ATTACK_MEMORY_S)


def encode_attacks(obs: dict) -> np.ndarray:
    """Recent attacks by the enemy and trap slots of the base frame."""
    vector = np.zeros(ATTACK_SIZE, dtype=np.float32)
    hero = obs.get("hero", {})
    for index, (_, _, _, enemy) in enumerate(nearest_units(hero, obs.get("enemies", []))[:MAX_ENEMIES]):
        vector[index] = _recency(enemy.get("firedAgo"))
    for index, (_, _, _, trap) in enumerate(nearest_units(hero, obs.get("traps", []))[:MAX_TRAPS]):
        vector[MAX_ENEMIES + index] = _recency(trap.get("firedAgo"))
    return vector


class HistoryEncoder:
    """Stateful encoder: the base frame plus recent visible context.

    Call reset() at the start of a combat episode, encode(obs) on every
    decision frame, and record_action(action) with the action taken after it.
    """

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self._trail: deque = deque(maxlen=64)  # (frame, position)
        self._last_frame: int | None = None
        self._last_hp: float | None = None
        self._hit_frame: int | None = None
        self._enemy_positions: dict = {}
        self._actions: deque = deque(maxlen=PREVIOUS_ACTIONS)
        self._cached: np.ndarray | None = None

    def record_action(self, action) -> None:
        self._actions.append(tuple(int(a) for a in action))
        self._cached = None

    def encode(self, obs: dict, frame: int | None = None) -> np.ndarray:
        """Encode one decision frame. `frame` is the bridge frame number (game
        time); without it, frames are assumed DEFAULT_FRAME_STEP apart."""
        if frame is None:
            frame = 0 if self._last_frame is None else self._last_frame + DEFAULT_FRAME_STEP
        if frame == self._last_frame and self._cached is not None:
            return self._cached  # same frame again (e.g. a step timeout): nothing new to add
        elapsed = None if self._last_frame is None else max(1, frame - self._last_frame)
        base = encode_observation(obs)
        history = np.zeros(HISTORY_SIZE, dtype=np.float32)
        hero = obs.get("hero", {})
        angle = hero.get("angle")
        if angle is not None:
            history[0], history[1] = math.sin(math.radians(angle)), math.cos(math.radians(angle))
        position = _position(hero)
        if position is not None and self._trail and elapsed is not None:
            _, (px, py) = self._trail[-1]
            history[2] = max(-1.0, min(1.0, (position[0] - px) / elapsed / VELOCITY_PER_FRAME))
            history[3] = max(-1.0, min(1.0, (position[1] - py) / elapsed / VELOCITY_PER_FRAME))
        if position is not None and self._trail:
            # Oldest remembered position inside the window (or the oldest at all).
            window = [p for f, p in self._trail if f >= frame - TRAIL_FRAMES] or [self._trail[-1][1]]
            ox, oy = window[0]
            history[4] = _fraction(math.hypot(position[0] - ox, position[1] - oy) / POSITION_SCALE)
        if position is not None:
            self._trail.append((frame, position))
        hp = visible_hud(obs).get("hp")
        if hp is not None:
            if self._last_hp is not None and hp < self._last_hp:
                self._hit_frame = frame
            self._last_hp = hp
        if self._hit_frame is not None:
            # 1 = hit this frame; halves after 2 frames (the old per-decision decay).
            history[5] = 1.0 / (1.0 + (frame - self._hit_frame) / DEFAULT_FRAME_STEP)
        i = 6
        for action in list(self._actions)[::-1]:  # most recent first
            for size, value in zip(ACTION_SIZES, action):
                if 0 <= value < size:
                    history[i + value] = 1.0
                i += size
        i = 6 + PREVIOUS_ACTIONS * sum(ACTION_SIZES)
        positions = {}
        for slot, (_, _, _, enemy) in enumerate(nearest_units(hero, obs.get("enemies", []))[:MAX_ENEMIES]):
            location = _position(enemy)
            key = enemy.get("id")
            if key is not None and location is not None:
                positions[key] = location
                previous = self._enemy_positions.get(key)
                if previous is not None and elapsed is not None:
                    start = i + slot * 2
                    history[start] = max(-1.0, min(1.0, (location[0] - previous[0]) / elapsed / VELOCITY_PER_FRAME))
                    history[start + 1] = max(-1.0, min(1.0, (location[1] - previous[1]) / elapsed / VELOCITY_PER_FRAME))
        self._enemy_positions = positions
        self._last_frame = frame
        self._cached = np.concatenate([base, encode_attacks(obs), history])
        return self._cached
