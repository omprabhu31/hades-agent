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
TRAIL_STEPS = 6                   # decisions used for the "am I stuck?" travel feature
VELOCITY_SCALE = 100.0            # world units per decision per normalised unit
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
        self._trail: deque = deque(maxlen=TRAIL_STEPS)
        self._last_hp: float | None = None
        self._steps_since_hit: int | None = None
        self._enemy_positions: dict = {}
        self._actions: deque = deque(maxlen=PREVIOUS_ACTIONS)

    def record_action(self, action) -> None:
        self._actions.append(tuple(int(a) for a in action))

    def encode(self, obs: dict) -> np.ndarray:
        base = encode_observation(obs)
        history = np.zeros(HISTORY_SIZE, dtype=np.float32)
        hero = obs.get("hero", {})
        angle = hero.get("angle")
        if angle is not None:
            history[0], history[1] = math.sin(math.radians(angle)), math.cos(math.radians(angle))
        i = 2
        position = _position(hero)
        if position is not None and self._trail:
            px, py = self._trail[-1]
            history[i] = max(-1.0, min(1.0, (position[0] - px) / VELOCITY_SCALE))
            history[i + 1] = max(-1.0, min(1.0, (position[1] - py) / VELOCITY_SCALE))
        i += 2
        if position is not None and self._trail:
            ox, oy = self._trail[0]
            history[i] = _fraction(math.hypot(position[0] - ox, position[1] - oy) / POSITION_SCALE)
        i += 1
        if position is not None:
            self._trail.append(position)
        hp = visible_hud(obs).get("hp")
        if hp is not None:
            if self._last_hp is not None and hp < self._last_hp:
                self._steps_since_hit = 0
            elif self._steps_since_hit is not None:
                self._steps_since_hit += 1
            self._last_hp = hp
        if self._steps_since_hit is not None:
            history[i] = 1.0 / (1.0 + self._steps_since_hit)  # 1 = hit this step, decays
        i += 1
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
                if previous is not None:
                    start = i + slot * 2
                    history[start] = max(-1.0, min(1.0, (location[0] - previous[0]) / VELOCITY_SCALE))
                    history[start + 1] = max(-1.0, min(1.0, (location[1] - previous[1]) / VELOCITY_SCALE))
        self._enemy_positions = positions
        return np.concatenate([base, encode_attacks(obs), history])
