"""Fixed-size observation encoding using the bridge's visible fields."""

import math

import numpy as np

POSITION_SCALE = 1000.0  # world units per normalised unit, clipped to the Box bounds
MAX_ENEMIES = 8
MAX_TRAPS = 4
MAX_BREAKABLES = 8

HERO_FIELDS = ("hp_fraction", "cast_ammo", "last_stands", "call_pips")
ENEMY_FIELDS = ("dx", "dy", "distance", "hpFrac", "armorFrac", "shields", "boss", "elite", "present")
TRAP_FIELDS = ("dx", "dy", "disabled", "present")
BREAKABLE_FIELDS = ("dx", "dy", "present")
OBSERVATION_SIZE = (
    len(HERO_FIELDS)
    + MAX_ENEMIES * len(ENEMY_FIELDS)
    + MAX_TRAPS * len(TRAP_FIELDS)
    + MAX_BREAKABLES * len(BREAKABLE_FIELDS)
    + 1  # combat active
)


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
    vector = np.zeros(OBSERVATION_SIZE, dtype=np.float32)
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
