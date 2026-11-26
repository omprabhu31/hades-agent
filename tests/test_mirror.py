from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from agent.macro import choose_mirror_upgrade, mirror, spend_darkness


def row(name, *, rank=0, cost=10, can_buy=True, locked=False, y=372):
    return {"name": name, "rank": rank, "nextCost": cost, "canBuy": can_buy,
            "locked": locked, "x": 1155, "y": y}


def test_mirror_priority_is_applied_to_visible_rows():
    names = [
        "ExtraChanceMetaUpgrade", "HealthMetaUpgrade", "DoorHealMetaUpgrade",
        "StaminaMetaUpgrade", "AmmoMetaUpgrade", "BackstabMetaUpgrade",
        "StoredAmmoVulnerabilityMetaUpgrade", "MoneyMetaUpgrade",
    ]
    menu = {"darkness": 100, "upgrades": [row(name) for name in reversed(names)]}
    for name in names:
        choice = choose_mirror_upgrade(menu)
        assert choice["name"] == name
        menu["upgrades"].remove(choice)
    assert choose_mirror_upgrade(menu) is None


def test_mirror_skips_unavailable_upgrades_and_uses_row_order_for_other_upgrades():
    alternatives = [row("FirstStrikeMetaUpgrade"), row("MoneyMetaUpgrade")]
    menu = {"darkness": 20, "upgrades": [
        row("ExtraChanceMetaUpgrade", cost=30),
        row("HealthMetaUpgrade", locked=True),
        row("DoorHealMetaUpgrade", can_buy=False),
        row("StaminaMetaUpgrade", cost=None),
        dict(row("AmmoMetaUpgrade"), x=None),
        *alternatives,
    ]}
    assert choose_mirror_upgrade(menu) is alternatives[0]
    assert choose_mirror_upgrade(None) is None
    assert choose_mirror_upgrade({"upgrades": alternatives}) is None


BEDROOM = {"house": {"map": "DeathAreaBedroom", "mirror": {"x": 480, "y": 190}}}
CLOSE = {"x": 954, "y": 996}


def open_mirror(darkness, *upgrades):
    return {**BEDROOM, "screens": ["MetaUpgrade"],
            "mirror": {"darkness": darkness, "upgrades": upgrades, "close": CLOSE}}


@pytest.fixture
def clock(monkeypatch):
    elapsed = 0.0

    def sleep(seconds):
        nonlocal elapsed
        elapsed += seconds

    clock = SimpleNamespace(monotonic=lambda: elapsed, sleep=sleep)
    monkeypatch.setattr(mirror, "time", clock)
    return clock


def test_spend_waits_for_each_rank_and_uses_refreshed_menu(clock):
    before = open_mirror(40, row("ExtraChanceMetaUpgrade", cost=30), row("DoorHealMetaUpgrade", y=417))
    after_defiance = open_mirror(10, row("ExtraChanceMetaUpgrade", rank=1, cost=500, can_buy=False),
                                row("DoorHealMetaUpgrade", y=417))
    after_heal = open_mirror(0, row("DoorHealMetaUpgrade", rank=1, cost=20, can_buy=False, y=417))
    bridge = Mock()
    bridge.policy_obs.side_effect = [
        BEDROOM, BEDROOM, {**BEDROOM, "screens": ["MetaUpgrade"]}, before,
        before, after_defiance, after_defiance, after_heal, after_heal, BEDROOM,
    ]
    macro = Mock()

    assert spend_darkness(macro, bridge) == [
        {"name": "ExtraChanceMetaUpgrade", "rank": 1, "cost": 30},
        {"name": "DoorHealMetaUpgrade", "rank": 1, "cost": 10},
    ]
    macro.walk_to.assert_called_once_with(480, 190, radius=90, timeout=10)
    macro.interact.assert_called_once_with()
    assert [call.args for call in macro.click_ui.call_args_list] == [(1155, 372), (1155, 417), (954, 996)]


def test_spend_stops_at_purchase_limit_and_can_continue_an_open_mirror(clock):
    before = open_mirror(100, row("DoorHealMetaUpgrade"))
    after = open_mirror(90, row("DoorHealMetaUpgrade", rank=1, cost=20))
    bridge = Mock()
    bridge.policy_obs.side_effect = [before, before, after, after, BEDROOM]
    macro = Mock()

    assert spend_darkness(macro, bridge, max_purchases=1) == [
        {"name": "DoorHealMetaUpgrade", "rank": 1, "cost": 10},
    ]
    macro.walk_to.assert_not_called()
    macro.interact.assert_not_called()
    assert [call.args for call in macro.click_ui.call_args_list] == [(1155, 372), (954, 996)]


def test_spend_times_out_without_clicking_when_mirror_does_not_open(clock):
    macro = Mock()
    bridge = Mock()
    bridge.policy_obs.return_value = BEDROOM

    assert spend_darkness(macro, bridge) == []
    macro.interact.assert_called_once_with()
    macro.click_ui.assert_not_called()
    assert clock.monotonic() >= mirror._OPEN_TIMEOUT


def test_spend_closes_without_retrying_an_unconfirmed_purchase(clock):
    before = open_mirror(100, row("DoorHealMetaUpgrade"))
    bridge = Mock()
    bridge.policy_obs.return_value = before
    macro = Mock()

    def click(x, y):
        if (x, y) == (954, 996):
            bridge.policy_obs.return_value = BEDROOM

    macro.click_ui.side_effect = click
    assert spend_darkness(macro, bridge) == []
    assert [call.args for call in macro.click_ui.call_args_list] == [(1155, 372), (954, 996)]
    assert clock.monotonic() >= mirror._PURCHASE_TIMEOUT


def test_spend_skips_non_bedroom():
    bridge = Mock()
    bridge.policy_obs.return_value = {"house": {"map": "DeathArea"}}
    macro = Mock()
    assert spend_darkness(macro, bridge) == []
    assert not macro.mock_calls


def test_spend_skips_interaction_when_walk_times_out():
    bridge = Mock()
    bridge.policy_obs.return_value = BEDROOM
    macro = Mock()
    macro.walk_to.return_value = False

    assert spend_darkness(macro, bridge) == []
    macro.interact.assert_not_called()
    macro.click_ui.assert_not_called()


def test_spend_uses_cancel_when_close_coordinates_are_unavailable(clock):
    obs = open_mirror(0)
    del obs["mirror"]["close"]
    bridge = Mock()
    bridge.policy_obs.side_effect = [obs, obs, obs, BEDROOM]
    macro = Mock()

    assert spend_darkness(macro, bridge) == []
    macro.c.tap.assert_called_once_with("escape")
    macro.click_ui.assert_not_called()
