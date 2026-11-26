"""Once-per-visit bookkeeping for House actions (gift, Mirror, keepsake rack).

Review 016: keying actions on the run count skipped re-entered rooms, and a
failed walk used up the whole visit. A visit starts whenever a different
House map loads (the House has return doors, so the bedroom can be entered
twice before a run). Outcomes that prove nothing happened may be retried
once; anything that may have spent Nectar or Darkness latches the visit.
"""
from __future__ import annotations

MAX_ATTEMPTS = 2

# gift_nectar statuses after which no Gift press can have happened, and that
# might succeed on a second try (agent/macro/house.py).
GIFT_RETRYABLE = {"house_unavailable", "target_unreachable", "prompt_unavailable",
                  "nectar_prompt_unavailable", "nectar_count_unavailable"}
# equip_keepsake statuses where the menu was never opened.
RACK_RETRYABLE = {"rack_unavailable", "rack_unreachable", "rack_prompt_unavailable", "menu_unavailable"}


def ready_for_action(obs: dict) -> bool:
    """A stable, playable House frame: HUD drawn, no overlay, no engine menu."""
    return bool(obs.get("hud")) and not obs.get("screens") and obs.get("screen") in (None, "InGameUI")


class HouseVisits:
    def __init__(self) -> None:
        self.visit = 0
        self._map: str | None = None
        self._done: set = set()
        self._attempts: dict = {}

    def observe(self, house_map: str | None) -> None:
        """Call on every observation; None means not in the House."""
        if house_map != self._map:
            self._map = house_map
            if house_map is not None:
                self.visit += 1

    def pending(self, action: str) -> bool:
        key = (action, self.visit)
        return key not in self._done and self._attempts.get(key, 0) < MAX_ATTEMPTS

    def record(self, action: str, done: bool) -> None:
        key = (action, self.visit)
        self._attempts[key] = self._attempts.get(key, 0) + 1
        if done:
            self._done.add(key)


def gift_done(result: dict) -> bool:
    return result.get("status") not in GIFT_RETRYABLE


def rack_done(result: dict) -> bool:
    return result.get("status") not in RACK_RETRYABLE


def mirror_done(purchases: list) -> bool:
    # spend_darkness returns [] both when nothing was affordable and when the
    # mirror was not reached; a second attempt only buys what is affordable
    # and verifies each rank, so retrying an empty result is safe.
    return bool(purchases)
