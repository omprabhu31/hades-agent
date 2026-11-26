import pytest

from agent.macro import choose_boon_option, choose_door, ui_to_window, world_dir_to_movement


@pytest.mark.parametrize("dx,dy,want", [
    (1, 0, "right"), (-1, 0, "left"), (0, -1, "up"), (0, 1, "down"),
    (1, -1, "up_right"), (-1, 1, "down_left"), (0, 0, None), (10, -3, "right")])
def test_world_dir_to_movement(dx, dy, want):
    assert world_dir_to_movement(dx, dy) == want


def test_ui_to_window_letterbox():
    u, v = ui_to_window(960, 540, 1512, 982)
    assert u == pytest.approx(0.5) and v == pytest.approx(0.5)
    u, v = ui_to_window(0, 0, 1512, 982)
    assert u == pytest.approx(0) and v == pytest.approx(65.75 / 982)


def test_choose_door_prefers_reward_then_distance():
    obs = {"hero": {"x": 0, "y": 0}, "doors": [
        {"id": 1, "x": 10, "y": 0, "lit": True, "reward": "RoomRewardMoneyDrop"},
        {"id": 2, "x": 500, "y": 0, "lit": True, "reward": "Boon"},
        {"id": 3, "x": 5, "y": 0, "lit": False, "reward": None},
        {"id": 4, "x": 100, "y": 0, "lit": True, "reward": "Boon"}]}
    assert choose_door(obs)["id"] == 4
    assert choose_door({"doors": []}) is None


def test_choose_boon_rarity_first():
    menu = {"options": [
        {"index": 1, "name": "ZeusWeaponTrait", "rarity": "Common"},
        {"index": 2, "name": "ZeusShoutTrait", "rarity": "Rare"},
        {"index": 3, "name": "ZeusSecondaryTrait", "rarity": "Common"}]}
    assert choose_boon_option(menu)["index"] == 2
    menu["options"][1]["rarity"] = "Common"
    assert choose_boon_option(menu)["index"] == 1


def test_locked_boon_cards_skipped():
    menu = {"options": [{"index": 1, "name": "A", "rarity": "Epic", "locked": True},
                        {"index": 2, "name": "B", "rarity": "Common"}]}
    assert choose_boon_option(menu)["index"] == 2
