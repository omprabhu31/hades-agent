"""Choose and buy permanent Mirror of Night upgrades from the visible menu."""
from __future__ import annotations

import time

from .driver import MacroError

# In-game identifiers in MetaUpgradeData.lua:882-896, in purchase order.
_PRIORITY = {
    "ExtraChanceMetaUpgrade": 0,  # Death Defiance
    "HealthMetaUpgrade": 1,  # Thick Skin
    "DoorHealMetaUpgrade": 2,  # Chthonic Vitality
    "StaminaMetaUpgrade": 3,  # Greater Reflex
    "AmmoMetaUpgrade": 4,  # Infernal Soul
    "BackstabMetaUpgrade": 5,  # Shadow Presence
    "StoredAmmoVulnerabilityMetaUpgrade": 6,  # Boiling Blood
}
# The Mirror stands against the bedroom wall: live on 2026-11-26 the hero
# could get no closer than about 122 units to its anchor, so a 90-unit walk
# radius never arrived. Doors interact from up to 260, so 160 is assumed to
# be inside the Mirror's use range (to be confirmed by a live purchase).
_REACH = 160.0
_OPEN_TIMEOUT = 5.0
_PURCHASE_TIMEOUT = 3.0
_CLOSE_TIMEOUT = 3.0
_POLL_INTERVAL = 0.05


def choose_mirror_upgrade(menu: dict | None) -> dict | None:
    """Pick the highest-priority enabled plus button, using row order for ties."""
    if not menu or menu.get("darkness") is None:
        return None
    choices = [
        row for row in menu.get("upgrades", [])
        if row.get("canBuy") and not row.get("locked")
        and row.get("nextCost") is not None and row["nextCost"] <= menu["darkness"]
        and row.get("x") is not None and row.get("y") is not None
    ]
    return min(choices, key=lambda row: _PRIORITY.get(row["name"], len(_PRIORITY)), default=None)


def _wait_for(bridge, condition, timeout: float) -> dict | None:
    deadline = time.monotonic() + timeout
    while True:
        obs = bridge.policy_obs()
        if obs is not None and condition(obs):
            return obs
        if time.monotonic() >= deadline:
            return None
        time.sleep(_POLL_INTERVAL)


def _mirror_open(obs: dict) -> bool:
    return "MetaUpgrade" in (obs.get("screens") or ())


def _in_bedroom(obs: dict) -> bool:
    return (obs.get("house") or {}).get("map") == "DeathAreaBedroom"


def _confirm_purchase(obs: dict, choice: dict) -> dict | None:
    for row in (obs.get("mirror") or {}).get("upgrades", []):
        if row["name"] == choice["name"] and row["rank"] > choice["rank"]:
            return row
    return None


def _close_mirror(macro, bridge) -> None:
    obs = bridge.policy_obs() or {}
    if not _mirror_open(obs) or obs.get("screen") == "PauseScreen":
        return
    close = (obs.get("mirror") or {}).get("close")
    if close:
        macro.click_ui(close["x"], close["y"])
    else:
        # The game also binds the close button to Cancel (MetaUpgrades.lua:267-272).
        macro.c.tap("escape")
    _wait_for(bridge, lambda obs: not _mirror_open(obs), _CLOSE_TIMEOUT)


def spend_darkness(macro, bridge, max_purchases: int = 10) -> list[dict]:
    """Visit the bedroom Mirror, then return the name, new rank and cost of each confirmed purchase."""
    obs = bridge.policy_obs() or {}
    if max_purchases <= 0 or not _in_bedroom(obs) or obs.get("screen") == "PauseScreen":
        return []
    if not _mirror_open(obs):
        target = obs["house"].get("mirror")
        if target is None or obs.get("screens"):
            return []
        try:
            arrived = macro.walk_to(target["x"], target["y"], radius=_REACH, timeout=10)
        except MacroError:
            return []
        obs = bridge.policy_obs() or {}
        if not arrived or not _in_bedroom(obs) or obs.get("screens") or obs.get("screen") == "PauseScreen":
            return []
        macro.interact()

    purchases = []
    try:
        obs = _wait_for(bridge, lambda obs: obs.get("mirror") is not None, _OPEN_TIMEOUT)
        for _ in range(max_purchases):
            choice = choose_mirror_upgrade((obs or {}).get("mirror"))
            if choice is None:
                break
            macro.click_ui(choice["x"], choice["y"])
            obs = _wait_for(bridge, lambda obs: not _mirror_open(obs) or _confirm_purchase(obs, choice),
                            _PURCHASE_TIMEOUT)
            confirmed = _confirm_purchase(obs or {}, choice)
            if confirmed is None:
                break
            purchases.append({"name": choice["name"], "rank": confirmed["rank"], "cost": choice["nextCost"]})
    finally:
        _close_mirror(macro, bridge)
    return purchases
