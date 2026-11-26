"""Gift Nectar and equip keepsakes using visible House observations."""
from __future__ import annotations

import time
from collections.abc import Collection

from .driver import MacroError

_COLLAR = "MaxHealthKeepsakeTrait"
# GiftData.lua:326-338. Add recipients in priority order as they become useful.
_GIFT_PRIORITY = {"Cerberus": ("NPC_Cerberus_01", _COLLAR)}
# GiftData.lua:1-32. An equipped or first available keepsake is the fallback.
_KEEPSAKE_PRIORITY = (_COLLAR, "ReincarnationTrait", "DirectionalArmorTrait")
_POLL = 0.05
_PROMPT_TIMEOUT = 2.5
_MENU_TIMEOUT = 5.0
_UPDATE_TIMEOUT = 3.0
_TALK_TIMEOUT = 18.0
_GIFT_TIMEOUT = 25.0
# Gifting can have a post-dialogue unlock animation before movement resumes.
# GiftScripts.lua:66-101 and UIPresentation.lua:100-113, 196-213.
_GIFT_SETTLE = 5.5


def choose_gift_target(
    house: dict, known_keepsakes: Collection[str] | None, target: str | None = None,
) -> dict | None:
    """Choose a visible NPC whose keepsake was absent from the last rack survey."""
    if known_keepsakes is None:
        return None
    characters = {row["name"]: row for row in house.get("characters") or ()}
    for label, (name, keepsake) in _GIFT_PRIORITY.items():
        if target in (None, label, name) and name in characters and keepsake not in known_keepsakes:
            if house.get("equippedKeepsake") != keepsake:
                return characters[name]
    return None


def choose_keepsake(menu: dict | None, choice: str | None = None) -> dict | None:
    """Pick a selectable icon by trait name, or use the survivability priorities."""
    if not menu:
        return None
    available = [row for row in menu.get("keepsakes") or ()
                 if row.get("available") and not row.get("locked") and row.get("name")
                 and (row.get("equipped") or (row.get("x") is not None and row.get("y") is not None))]
    by_name = {row["name"]: row for row in available}
    if choice is not None:
        return by_name.get(choice)
    for name in (*_KEEPSAKE_PRIORITY, menu.get("equipped")):
        if name in by_name:
            return by_name[name]
    return next(iter(available), None)


def _world(obs: dict) -> bool:
    return obs.get("screen") != "PauseScreen" and not obs.get("screens")


def _only_screen(obs: dict, name: str) -> bool:
    return obs.get("screen") != "PauseScreen" and list(obs.get("screens") or ()) == [name]


def _wait(bridge, map_name: str, condition, timeout: float, *, dialogue_macro=None) -> dict | None:
    deadline = time.monotonic() + timeout
    next_click = 0.0
    while True:
        now = time.monotonic()
        obs = bridge.policy_obs()
        if obs:
            if (obs.get("house") or {}).get("map") != map_name or obs.get("screen") == "PauseScreen":
                return None
            if condition(obs):
                return obs
            if dialogue_macro is not None and now >= next_click and _only_screen(obs, "Dialog"):
                dialogue_macro.click_ui(1150, 850)  # The same text box used by run_agent.
                next_click = now + 0.6
        if now >= deadline:
            return None
        time.sleep(_POLL)


def _walk(macro, target: dict) -> bool:
    try:
        return target.get("usePrompt") or macro.walk_to(target["x"], target["y"], radius=90, timeout=10)
    except MacroError:
        return False


def _active_character(obs: dict, npc_id: int) -> dict:
    if _world(obs):
        for row in obs["house"].get("characters") or ():
            if row["id"] == npc_id and row.get("promptTarget"):
                return row
    return {}


def gift_nectar(
    macro, bridge, target: str | None = "Cerberus", *, known_keepsakes: Collection[str] | None = None,
) -> dict:
    """Give one Nectar gift, using the unlocked names from a completed rack survey."""
    result = {"target": target}
    obs = bridge.policy_obs() or {}
    house = obs.get("house") or {}
    map_name = house.get("map")
    if not map_name or not _world(obs):
        return dict(result, status="house_unavailable")
    if known_keepsakes is None:
        return dict(result, status="ownership_unknown")
    npc = choose_gift_target(house, known_keepsakes, target)
    if npc is None:
        return dict(result, status="no_eligible_target")
    result["target"] = npc["name"]
    if house.get("nectar") == 0:
        return dict(result, status="no_nectar")
    if not _walk(macro, npc):
        return dict(result, status="target_unreachable")
    npc_id = npc["id"]
    obs = _wait(bridge, map_name, lambda obs: _active_character(obs, npc_id), _PROMPT_TIMEOUT)
    if obs is None:
        return dict(result, status="prompt_unavailable")

    def nectar_prompt(obs: dict) -> bool:
        prompt = _active_character(obs, npc_id).get("giftPrompt") or {}
        return prompt.get("resource") == "GiftPoints"

    # The first Nectar gift normally needs a prior conversation
    # (GiftScripts.lua:153-164, Interactables.lua:288-313).
    if (not nectar_prompt(obs) and _active_character(obs, npc_id).get("talkPrompt")
            and (obs["house"].get("nectar") or 0) > 0):
        macro.interact()
        obs = _wait(bridge, map_name, nectar_prompt, _TALK_TIMEOUT, dialogue_macro=macro)
    if obs is None or not nectar_prompt(obs):
        return dict(result, status="nectar_prompt_unavailable")
    before = obs["house"].get("nectar")
    if before is None:
        return dict(result, status="nectar_count_unavailable")
    amount = _active_character(obs, npc_id)["giftPrompt"]["amount"]
    if not 0 < amount <= before:
        return dict(result, status="no_nectar")
    macro.c.tap("gift")

    after = None
    quiet_since = None

    def gift_finished(obs: dict) -> bool:
        nonlocal after, quiet_since
        count = obs["house"].get("nectar")
        if count == before - amount:
            after = count
        if after is None or not _world(obs):
            quiet_since = None
            return False
        now = time.monotonic()
        if quiet_since is None:
            quiet_since = now
        return now - quiet_since >= _GIFT_SETTLE

    finished = _wait(bridge, map_name, gift_finished, _GIFT_TIMEOUT, dialogue_macro=macro)
    return dict(result, status="gifted" if after is not None else "unconfirmed",
                nectar_before=before, nectar_after=after, settled=finished is not None)


def _close_rack(macro, bridge, map_name: str) -> dict | None:
    obs = bridge.policy_obs() or {}
    if _only_screen(obs, "AwardMenu") and obs.get("awardMenu") is not None:
        close = obs["awardMenu"].get("close")
        if close:
            macro.click_ui(close["x"], close["y"])
        else:
            macro.c.tap("escape")  # AwardMenuScripts.lua:155-158 binds Cancel.
    return _wait(bridge, map_name, _world, _UPDATE_TIMEOUT)


def equip_keepsake(macro, bridge, choice: str | None = None) -> dict:
    """Survey the courtyard rack, select one icon, then close to apply the choice."""
    obs = bridge.policy_obs() or {}
    house = obs.get("house") or {}
    map_name = house.get("map")
    if map_name != "RoomPreRun" or not (_world(obs) or _only_screen(obs, "AwardMenu")):
        return {"status": "rack_unavailable"}
    if not _only_screen(obs, "AwardMenu"):
        rack = house.get("keepsakeRack")
        if not rack or not _walk(macro, rack):
            return {"status": "rack_unreachable"}
        obs = _wait(bridge, map_name, lambda obs: _world(obs) and
                    (obs["house"].get("keepsakeRack") or {}).get("promptTarget"), _PROMPT_TIMEOUT)
        if obs is None:
            return {"status": "rack_prompt_unavailable"}
        macro.interact()

    obs = _wait(bridge, map_name, lambda obs: _only_screen(obs, "AwardMenu") and
                obs.get("awardMenu") is not None, _MENU_TIMEOUT)
    if obs is None:
        return {"status": "menu_unavailable"}
    menu = obs["awardMenu"]
    result = {"owned": [row["name"] for row in menu.get("keepsakes") or () if row.get("name")]}
    selected = choose_keepsake(menu, choice)
    status = "no_available_choice"
    try:
        if selected is not None:
            name = selected["name"]
            result["choice"] = name
            if selected.get("equipped"):
                status = "already_equipped"
            else:
                macro.click_ui(selected["x"], selected["y"])
                obs = _wait(bridge, map_name, lambda obs: (obs.get("awardMenu") or {}).get("equipped") == name,
                            _UPDATE_TIMEOUT)
                status = "selected" if obs is not None else "unconfirmed"
    finally:
        closed = _close_rack(macro, bridge, map_name)
    if closed is None:
        return dict(result, status="close_timeout")
    if status == "selected":
        # The rack applies the selection on close (AwardMenuScripts.lua:704-706).
        obs = _wait(bridge, map_name, lambda obs: _world(obs) and
                    obs["house"].get("equippedKeepsake") == result["choice"], _UPDATE_TIMEOUT)
        status = "equipped" if obs is not None else "unconfirmed"
    return dict(result, status=status)
