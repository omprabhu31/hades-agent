from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from agent.macro import choose_gift_target, choose_keepsake, equip_keepsake, gift_nectar, house
from agent.macro.driver import MacroError


COLLAR = "MaxHealthKeepsakeTrait"
TOOTH = "ReincarnationTrait"
CERBERUS = {"id": 10, "name": "NPC_Cerberus_01", "x": 480, "y": 360}
RACK = {"id": 20, "x": 210, "y": 650}
ACTIVE = {"usePrompt": True, "promptTarget": True}
NECTAR = {"resource": "GiftPoints", "amount": 1}


def hall(nectar=1, npc=CERBERUS, screens=()):
    return {"house": {"map": "DeathArea", "nectar": nectar, "characters": [npc]}, "screens": screens}


def courtyard(rack=RACK, *, equipped=None):
    return {"house": {"map": "RoomPreRun", "keepsakeRack": rack, "equippedKeepsake": equipped}}


def button(name, x=300, *, locked=False, equipped=False):
    return {"name": name, "x": x, "y": 280, "available": not locked, "locked": locked, "equipped": equipped}


def rack_menu(*rows, equipped=None, close=True):
    menu = {"keepsakes": rows, "equipped": equipped}
    if close:
        menu["close"] = {"x": 960, "y": 1030}
    return {**courtyard(), "screens": ["AwardMenu"], "awardMenu": menu}


@pytest.fixture
def clock(monkeypatch):
    elapsed = 0.0

    def sleep(seconds):
        nonlocal elapsed
        elapsed += seconds

    clock = SimpleNamespace(monotonic=lambda: elapsed, sleep=sleep)
    monkeypatch.setattr(house, "time", clock)
    return clock


def test_gift_priority_uses_surveyed_ownership_and_visible_characters():
    room = hall()["house"]
    assert choose_gift_target(room, []) is CERBERUS
    assert choose_gift_target(room, [TOOTH], target="Cerberus") is CERBERUS
    assert choose_gift_target(room, None) is None
    assert choose_gift_target(room, [COLLAR]) is None
    assert choose_gift_target({**room, "equippedKeepsake": COLLAR}, []) is None
    assert choose_gift_target({"characters": []}, []) is None
    assert choose_gift_target(room, [], target="Hades") is None


def test_keepsake_rules_prioritise_available_survivability_and_respect_explicit_choice():
    tooth = button(TOOTH, equipped=True)
    collar = button(COLLAR, 400)
    blocked = button("DirectionalArmorTrait", locked=True)
    menu = rack_menu(tooth, blocked, collar, equipped=TOOTH)["awardMenu"]
    assert choose_keepsake(menu) is collar
    assert choose_keepsake(menu, TOOTH) is tooth
    assert choose_keepsake(menu, "DirectionalArmorTrait") is None
    menu["keepsakes"] = (tooth, blocked, dict(collar, x=None))
    assert choose_keepsake(menu) is tooth
    assert choose_keepsake(None) is None


def test_gift_walks_talks_and_verifies_one_nectar_with_dialogue(clock):
    bridge, macro = Mock(), Mock()
    bridge.policy_obs.return_value = hall()
    talking = {**CERBERUS, **ACTIVE, "talkPrompt": True}
    ready = {**talking, "giftPrompt": NECTAR}
    state = "approach"
    gift_time = None

    def walk(*args, **kwargs):
        bridge.policy_obs.return_value = hall(npc=talking)
        return True

    def interact():
        nonlocal state
        state = "meeting"
        bridge.policy_obs.return_value = hall(nectar=None, screens=["Dialog"])

    def gift(key):
        nonlocal state, gift_time
        assert key == "gift"
        state = "thanking"
        gift_time = clock.monotonic()

    def obs():
        if state == "thanking":
            # The count may disappear while the dialogue is open.
            if clock.monotonic() - gift_time < 0.15:
                return hall(nectar=0)
            return hall(nectar=None, screens=["Dialog"])
        return bridge.policy_obs.return_value

    def click(x, y):
        nonlocal state
        assert (x, y) == (1150, 850)
        if state == "meeting":
            bridge.policy_obs.return_value = hall(npc=ready)
            state = "ready"
        else:
            assert state == "thanking"
            bridge.policy_obs.return_value = hall(nectar=None)
            state = "complete"

    macro.walk_to.side_effect = walk
    macro.interact.side_effect = interact
    macro.click_ui.side_effect = click
    macro.c.tap.side_effect = gift
    bridge.policy_obs.side_effect = obs

    assert gift_nectar(macro, bridge, known_keepsakes=[]) == {
        "target": CERBERUS["name"], "status": "gifted", "nectar_before": 1, "nectar_after": 0, "settled": True,
    }
    macro.walk_to.assert_called_once_with(480, 360, radius=90, timeout=10)
    macro.interact.assert_called_once_with()
    macro.c.tap.assert_called_once_with("gift")
    assert macro.click_ui.call_count == 2


@pytest.mark.parametrize(("obs", "known", "status"), [
    (hall(), None, "ownership_unknown"),
    (hall(), [COLLAR], "no_eligible_target"),
    (hall(nectar=0), [], "no_nectar"),
    (hall(screens=["TraitTrayScreen"]), [], "house_unavailable"),
    (hall(npc={**CERBERUS, "usePrompt": True, "giftPrompt": NECTAR}), [], "prompt_unavailable"),
    (hall(npc={**CERBERUS, **ACTIVE, "giftPrompt": {"resource": "SuperGiftPoints", "amount": 1}}),
     [], "nectar_prompt_unavailable"),
    (hall(nectar=None, npc={**CERBERUS, **ACTIVE, "giftPrompt": NECTAR}), [], "nectar_count_unavailable"),
])
def test_gift_skips_unverified_spends(obs, known, status, clock):
    bridge, macro = Mock(), Mock()
    bridge.policy_obs.return_value = obs
    assert gift_nectar(macro, bridge, known_keepsakes=known)["status"] == status
    macro.interact.assert_not_called()
    macro.c.tap.assert_not_called()
    macro.click_ui.assert_not_called()


def test_gift_does_not_repeat_an_unconfirmed_press(clock):
    bridge, macro = Mock(), Mock()
    bridge.policy_obs.return_value = hall(npc={**CERBERUS, **ACTIVE, "giftPrompt": NECTAR})
    result = gift_nectar(macro, bridge, known_keepsakes=[])
    assert result["status"] == "unconfirmed" and result["nectar_after"] is None
    macro.c.tap.assert_called_once_with("gift")
    assert clock.monotonic() >= house._GIFT_TIMEOUT


def test_gift_returns_when_walking_fails(clock):
    bridge, macro = Mock(), Mock()
    bridge.policy_obs.return_value = hall()
    macro.walk_to.side_effect = MacroError("no observation")
    assert gift_nectar(macro, bridge, known_keepsakes=[])["status"] == "target_unreachable"
    macro.c.tap.assert_not_called()


def test_equip_walks_through_rack_prompt_selects_and_confirms_hud_icon(clock):
    bridge, macro = Mock(), Mock()
    bridge.policy_obs.return_value = courtyard()

    def walk(*args, **kwargs):
        bridge.policy_obs.return_value = courtyard({**RACK, **ACTIVE})
        return True

    def interact():
        bridge.policy_obs.return_value = rack_menu(button(TOOTH, equipped=True), button(COLLAR, 400), equipped=TOOTH)

    def click(x, y):
        if (x, y) == (400, 280):
            bridge.policy_obs.return_value = rack_menu(button(TOOTH), button(COLLAR, 400, equipped=True), equipped=COLLAR)
        else:
            assert (x, y) == (960, 1030)
            bridge.policy_obs.return_value = courtyard(equipped=COLLAR)

    macro.walk_to.side_effect = walk
    macro.interact.side_effect = interact
    macro.click_ui.side_effect = click
    assert equip_keepsake(macro, bridge) == {"status": "equipped", "owned": [TOOTH, COLLAR], "choice": COLLAR}
    macro.walk_to.assert_called_once_with(210, 650, radius=90, timeout=10)
    macro.interact.assert_called_once_with()
    assert [call.args for call in macro.click_ui.call_args_list] == [(400, 280), (960, 1030)]


def test_equip_returns_complete_ownership_even_when_rack_has_only_unknown_slots(clock):
    bridge, macro = Mock(), Mock()
    bridge.policy_obs.return_value = rack_menu(button(None, locked=True), close=False)
    macro.c.tap.side_effect = lambda _: setattr(bridge.policy_obs, "return_value", courtyard())

    assert equip_keepsake(macro, bridge) == {"status": "no_available_choice", "owned": []}
    macro.walk_to.assert_not_called()
    macro.c.tap.assert_called_once_with("escape")
    macro.click_ui.assert_not_called()


def test_equip_does_not_click_unrelated_screen_when_rack_never_opens(clock):
    bridge, macro = Mock(), Mock()
    bridge.policy_obs.return_value = courtyard({**RACK, **ACTIVE})
    macro.interact.side_effect = lambda: setattr(
        bridge.policy_obs, "return_value", {**courtyard(), "screens": ["TraitTrayScreen"]},
    )

    assert equip_keepsake(macro, bridge) == {"status": "menu_unavailable"}
    macro.interact.assert_called_once_with()
    macro.click_ui.assert_not_called()
    macro.c.tap.assert_not_called()


def test_equip_distinguishes_selected_from_applied(clock):
    bridge, macro = Mock(), Mock()
    bridge.policy_obs.return_value = rack_menu(button(COLLAR))

    def click(x, y):
        if (x, y) == (300, 280):
            bridge.policy_obs.return_value = rack_menu(button(COLLAR, equipped=True), equipped=COLLAR)
        else:
            bridge.policy_obs.return_value = courtyard(equipped=TOOTH)

    macro.click_ui.side_effect = click
    assert equip_keepsake(macro, bridge) == {"status": "unconfirmed", "owned": [COLLAR], "choice": COLLAR}
    assert clock.monotonic() >= house._UPDATE_TIMEOUT
