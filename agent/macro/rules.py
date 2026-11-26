"""Pure decision rules for everything outside combat (no I/O, unit-tested).

Inputs are the bridge's policy observation (on-screen information only).
"""
from __future__ import annotations

import math

# World angles equal screen angles (calibration 2026-11-26): 0 = right,
# counter-clockwise, world y grows downwards.
_SECTORS = ["right", "up_right", "up", "up_left", "left", "down_left", "down", "down_right"]


def world_dir_to_movement(dx: float, dy: float) -> str | None:
    """Nearest of the 8 movement directions for a world-space displacement."""
    if dx == 0 and dy == 0:
        return None
    theta = math.degrees(math.atan2(-dy, dx)) % 360
    return _SECTORS[int((theta + 22.5) // 45) % 8]


def ui_to_window(x: float, y: float, win_w: float, win_h: float) -> tuple[float, float]:
    """Map the game's 1920x1080 UI layout to window-normalised (u, v).

    The game letterboxes a 16:9 picture into the window (black bars seen on
    the 1512x982 window), so scale by the limiting side and centre.
    """
    scale = min(win_w / 1920, win_h / 1080)
    ox = (win_w - 1920 * scale) / 2
    oy = (win_h - 1080 * scale) / 2
    return (ox + x * scale) / win_w, (oy + y * scale) / win_h


# Door preference while learning the game: survivability and power first.
# Values are rewards as the bridge reports them (ChosenRewardType).
DOOR_PRIORITY = {
    "Boon": 10, "StackUpgrade": 8, "WeaponUpgrade": 9, "RoomRewardMaxHealthDrop": 7,
    "HermesUpgrade": 6, "Devotion": 5, "Shop": 6, "RoomRewardMoneyDrop": 4,
    "RoomRewardMetaPointDrop": 3, "Story": 2, "Hidden": 3, "BiomeExit": 1,
}


def choose_door(obs: dict) -> dict | None:
    """Pick a lit exit door, preferring higher-value rewards, then nearer ones."""
    hero = obs.get("hero") or {}
    lit = [d for d in obs.get("doors") or [] if d.get("lit")]
    if not lit:
        return None

    def key(d):
        dist = math.hypot(d["x"] - hero.get("x", 0), d["y"] - hero.get("y", 0))
        return (-DOOR_PRIORITY.get(d.get("reward"), 0), dist)

    return min(lit, key=key)


RARITY_RANK = {"Common": 0, "Rare": 1, "Epic": 2, "Heroic": 3, "Legendary": 4}
# Slot preference for a first build: a strong attack and special come first.
NAME_HINTS = (("Weapon", 3), ("Secondary", 2), ("Rush", 1))


def choose_boon_option(menu: dict) -> dict | None:
    """Pick a boon card: rarity first, then attack/special/dash boons."""
    options = [o for o in (menu or {}).get("options") or [] if not o.get("locked")]
    if not options:
        return None

    def score(o):
        name = o.get("name") or ""
        hint = max((v for k, v in NAME_HINTS if k in name), default=0)
        return (RARITY_RANK.get(o.get("rarity"), 0), hint, -o.get("index", 0))

    return max(options, key=score)
