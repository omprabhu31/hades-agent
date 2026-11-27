"""Combat environment tests with a fake bridge, controller and clock."""

from copy import deepcopy

import gymnasium as gym
import numpy as np
import pytest
from gymnasium.utils.env_checker import check_env

from agent.bridge import BridgeMessage
from agent.env import CombatConfig, HadesCombatEnv, RewardConfig, combat
from agent.env.actions import decode_action
from agent.env.observations import BASE_SIZE, encode_observation
from agent.input import Action, Bounds, FakeBackend
from agent.policy import HeuristicPolicy
from scripts import run_baseline


def scene(*, hp=40, active=True, dead=False, enemies=(), name="RoomA", depth=2):
    return {
        "hero": {"x": 100, "y": 200, "hp": hp, "maxHp": 50, "angle": 0, "dead": dead},
        "room": {"name": name, "depth": depth, "combat": active},
        "enemies": list(enemies),
    }


class FakeBridge:
    latest_obs = None

    def __init__(self):
        self.commands = []

    def publish(self, frame, obs, hidden=None):
        self.latest_obs = BridgeMessage("obs", frame, {"obs": obs, "info": hidden or {}}, 0.0)

    def policy_obs(self):
        return self.latest_obs.data["obs"] if self.latest_obs else None

    def command(self, cmd, **kwargs):
        self.commands.append((cmd, kwargs))
        return {"value": kwargs["value"]}


class FakeController:
    def __init__(self):
        self.actions = []
        self.releases = 0
        self.on_apply = None

    def apply(self, action):
        self.actions.append(action)
        if self.on_apply is not None:
            self.on_apply()

    def release_all(self):
        self.releases += 1


class FakeClock:
    def __init__(self):
        self.now = 0.0
        self.callbacks = []

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds
        while self.callbacks and self.callbacks[0][0] <= self.now:
            _, callback = self.callbacks.pop(0)
            callback()

    def after(self, seconds, callback):
        self.callbacks.append((self.now + seconds, callback))
        self.callbacks.sort(key=lambda scheduled: scheduled[0])


@pytest.fixture
def harness(monkeypatch):
    clock, bridge, controller = FakeClock(), FakeBridge(), FakeController()
    monkeypatch.setattr(combat, "time", clock)
    return bridge, controller, clock


def test_observation_layout_encodes_nearest_units_and_padding():
    obs = scene(enemies=[
        {"id": 2, "x": 800, "y": 200, "hpFrac": 0.2},
        {"id": 1, "x": 70, "y": 240, "armorFrac": 0.75, "shields": 3, "boss": True, "elite": True},
    ])
    obs["hero"].update(castAmmo=2, lastStands=1, callPips=1, callPipPartial=0.5)
    obs["traps"] = [{"x": 100, "y": 200, "disabled": True}]
    obs["breakables"] = [{"x": 400, "y": -1400}]

    vector = encode_observation(obs)
    assert vector.shape == (117,)
    assert vector.dtype == np.float32
    np.testing.assert_allclose(vector[:4], [0.8, 2 / 3, 0.5, 0.6])
    np.testing.assert_allclose(vector[4:13], [-0.03, 0.04, 0.05, 0, 0.75, 0.75, 1, 1, 1])
    np.testing.assert_allclose(vector[13:22], [0.7, 0, 0.7, 0.2, 0, 0, 0, 0, 1])
    np.testing.assert_array_equal(vector[22:76], np.zeros(54))
    np.testing.assert_array_equal(vector[76:92], [0, 0, 1, 1] + [0] * 12)
    np.testing.assert_allclose(vector[92:], [0.3, -1, 1] + [0] * 21 + [1])


def test_units_are_capped_and_world_coordinates_are_not_assumed(harness):
    bridge, controller, _ = harness
    # Farthest units come first in the source arrays.
    units = [{"id": i, "x": 100 + i, "y": 200} for i in range(10, 0, -1)]
    obs = scene(enemies=units)
    obs.update(traps=units, breakables=units)
    bridge.publish(1, obs)
    env = HadesCombatEnv(bridge, controller)
    vector, _ = env.reset()
    assert env.observation_space.contains(vector)
    np.testing.assert_allclose(vector[4:76:9], np.arange(1, 9) / 1000)
    np.testing.assert_allclose(vector[76:92:4], np.arange(1, 5) / 1000)
    np.testing.assert_allclose(vector[92:116:3], np.arange(1, 9) / 1000)
    del obs["hero"]["x"]
    assert not encode_observation(obs)[4:-1].any()


def test_hidden_bridge_data_never_reaches_observation_or_info(harness):
    bridge, controller, _ = harness
    obs = scene(enemies=[{"id": 1, "x": 110, "y": 200, "hpFrac": 0.5}])
    bridge.publish(1, obs, {"heroHealth": 39.9, "enemyHealth": [{"id": 1, "hp": 15}]})
    env = HadesCombatEnv(bridge, controller)
    first, first_info = env.reset()
    bridge.publish(2, deepcopy(obs), {
        "heroHealth": -9, "enemyHealth": [{"id": 1, "hp": 5000}],
        "hero": {"dead": True, "hp": 0}, "room": {"combat": False}, "remainingSpawns": 17,
    })
    second, second_info = env.reset()
    np.testing.assert_array_equal(first, second)
    assert first_info == second_info == {"raw_obs": obs}
    second_info["raw_obs"]["hero"]["hp"] = 5
    assert bridge.policy_obs()["hero"]["hp"] == 40


def test_hidden_hud_values_are_blank_in_vector():
    obs = scene(hp=47)
    obs["hero"].update(castAmmo=3, lastStands=1, callPips=4)
    obs["hud"] = False
    np.testing.assert_array_equal(encode_observation(obs)[:4], [0, 0, 0, 0])


def test_action_decoding_uses_all_aim_sectors_and_window_aspect():
    env = HadesCombatEnv(FakeBridge(), FakeController())
    np.testing.assert_array_equal(env.action_space.nvec, [9, 5, 8])
    dx = 0.25 * 600 / 1200
    assert decode_action([1, 1, 0], (1200, 600)) == Action("right", (0.5 + dx, 0.5), frozenset({"attack"}))
    directions = ["right", "up_right", "up", "up_left", "left", "down_left", "down", "down_right"]
    for sector, direction in enumerate(directions):
        action = decode_action([sector + 1, 4, sector], (1200, 600))
        assert action.movement == direction
        assert action.buttons == {"dash"}
        x, y = (action.aim[0] - 0.5) * 1200, (action.aim[1] - 0.5) * 600
        angle = np.deg2rad(sector * 45)
        np.testing.assert_allclose([x, y], [150 * np.cos(angle), -150 * np.sin(angle)], atol=1e-12)
    assert decode_action([0, 0, 0], (1200, 600)).buttons == set()
    assert decode_action([0, 2, 0], (1200, 600)).buttons == {"special"}
    assert decode_action([0, 3, 0], (1200, 600)).buttons == {"cast"}


def test_step_waits_for_two_frames_after_apply(harness):
    bridge, controller, clock = harness
    bridge.publish(40, scene())
    env = HadesCombatEnv(bridge, controller)
    env.reset()
    bridge.publish(44, scene())

    def apply():
        bridge.publish(45, scene())
        clock.after(0.01, lambda: bridge.publish(46, scene(hp=39)))
        clock.after(0.02, lambda: bridge.publish(47, scene(hp=38)))
        clock.after(0.03, lambda: bridge.publish(48, scene(hp=37)))

    controller.on_apply = apply
    vector, _, terminated, truncated, info = env.step(np.array([3, 1, 2]))
    assert clock.now == pytest.approx(0.02)
    assert bridge.latest_obs.frame == 47
    assert info["raw_obs"]["hero"]["hp"] == 38
    assert vector[0] == pytest.approx(0.76)
    assert not (terminated or truncated)
    assert controller.actions == [Action("up", (0.5, 0.25), frozenset({"attack"}))]


def test_reset_waits_for_active_room_and_sets_requested_speed_once(harness):
    bridge, controller, clock = harness
    bridge.publish(1, {"screen": "LoadScreen", "loading": True})
    clock.after(0.01, lambda: bridge.publish(2, scene(active=False)))
    clock.after(0.02, lambda: bridge.publish(3, scene()))
    env = HadesCombatEnv(bridge, controller, config=CombatConfig(game_speed=3.0))
    vector, _ = env.reset(seed=3)
    assert vector[BASE_SIZE - 1] == 1  # combat flag ends the base frame
    assert clock.now == pytest.approx(0.02)
    assert bridge.commands[0][0] == "speed"
    assert bridge.commands[0][1]["value"] == 3.0
    env.reset(seed=3)
    assert len(bridge.commands) == 1
    assert controller.actions == []


def test_reset_timeout_leaves_no_episode(harness):
    bridge, controller, clock = harness
    env = HadesCombatEnv(bridge, controller, config=CombatConfig(reset_timeout=0.03))
    with pytest.raises(TimeoutError, match="No active combat"):
        env.reset()
    assert clock.now == pytest.approx(0.03)
    with pytest.raises(gym.error.ResetNeeded):
        env.step(np.array([0, 0, 0]))
    assert not controller.actions


def test_publication_race_retries_until_frame_and_policy_view_match(harness, monkeypatch):
    bridge, controller, _ = harness
    bridge.publish(10, scene(hp=48))
    read = bridge.policy_obs

    def advance_once():
        bridge.publish(11, scene(hp=47))
        monkeypatch.setattr(bridge, "policy_obs", read)
        return read()

    monkeypatch.setattr(bridge, "policy_obs", advance_once)
    env = HadesCombatEnv(bridge, controller)
    _, info = env.reset()
    assert info["raw_obs"]["hero"]["hp"] == 47


def test_stalled_step_truncates_and_releases_input(harness):
    bridge, controller, clock = harness
    bridge.publish(1, scene())
    env = HadesCombatEnv(bridge, controller, config=CombatConfig(step_timeout=0.03))
    env.reset()
    _, reward, terminated, truncated, info = env.step(np.array([1, 1, 0]))
    assert clock.now == pytest.approx(0.03)
    assert reward == -RewardConfig().time_penalty
    assert not terminated and truncated
    assert info["outcome"] == "timeout"
    assert controller.releases == 2  # reset and truncation
    env.close()
    assert controller.releases == 3


def test_pause_and_loading_frames_do_not_fake_a_clear(harness):
    bridge, controller, clock = harness
    bridge.publish(1, scene())
    env = HadesCombatEnv(bridge, controller)
    env.reset()

    def apply():
        clock.after(0.01, lambda: bridge.publish(3, {**scene(active=False), "screen": "PauseScreen"}))
        clock.after(0.02, lambda: bridge.publish(4, {"loading": True}))
        clock.after(0.03, lambda: bridge.publish(5, scene()))

    controller.on_apply = apply
    _, _, terminated, truncated, info = env.step(np.array([1, 0, 0]))
    assert not (terminated or truncated)
    assert info["outcome"] is None
    assert bridge.latest_obs.frame == 5


def test_room_change_before_apply_truncates_without_input(harness):
    bridge, controller, _ = harness
    bridge.publish(1, scene())
    env = HadesCombatEnv(bridge, controller)
    env.reset()
    bridge.publish(2, scene(name="RoomB", depth=3))
    _, _, terminated, truncated, info = env.step(np.array([0, 1, 0]))
    assert not terminated and truncated and info["outcome"] == "room_changed"
    assert controller.actions == []


@pytest.mark.parametrize(
    ("after", "hidden", "outcome", "expected_reward"),
    [
        (scene(), {"enemyHealth": [{"id": 1, "hp": 17, "armor": 4}, {"id": 99, "hp": 500}]}, None, 0.08),
        (scene(), {"heroHealth": 38.5}, None, -0.05),
        (scene(), {"heroHealth": 45}, None, -0.01),
        (scene(), {"enemyHealth": []}, None, 0.54),
        (scene(active=False), {"enemyHealth": []}, "cleared", 2.54),
        (scene(hp=0, active=False, dead=True), {"heroHealth": 0, "enemyHealth": []}, "dead", -3.59),
        (scene(hp=0), {"heroHealth": 0}, None, -1.59),
    ],
)
def test_reward_and_episode_outcome(harness, after, hidden, outcome, expected_reward):
    bridge, controller, clock = harness
    bridge.publish(1, scene(), {"heroHealth": 39.5, "enemyHealth": [{"id": 1, "hp": 20, "armor": 10}]})
    controller.on_apply = lambda: clock.after(0.01, lambda: bridge.publish(3, after, hidden))
    env = HadesCombatEnv(bridge, controller)
    env.reset()
    _, reward, terminated, truncated, info = env.step(np.array([1, 1, 0]))
    assert reward == pytest.approx(expected_reward)
    assert info == {"raw_obs": after, "outcome": outcome}
    assert terminated == (outcome is not None)
    assert not truncated


def test_step_limit_and_gymnasium_check_env(harness):
    bridge, controller, clock = harness
    bridge.publish(1, scene())

    def apply():
        frame = bridge.latest_obs.frame + 2
        clock.after(0.01, lambda: bridge.publish(frame, scene()))

    controller.on_apply = apply
    env = HadesCombatEnv(bridge, controller)
    check_env(env, skip_render_check=True)

    env = HadesCombatEnv(bridge, controller, config=CombatConfig(max_steps=1))
    env.reset()
    _, _, terminated, truncated, info = env.step(np.array([0, 0, 0]))
    assert not terminated and truncated and info["outcome"] == "step_limit"


def test_runner_executes_heuristic_with_only_fake_events(harness, monkeypatch, tmp_path):
    bridge, _, clock = harness
    enemy = {"id": 1, "x": 225, "y": 200, "hpFrac": 1}
    bridge.publish(1, scene(enemies=[enemy]), {"enemyHealth": [{"id": 1, "hp": 30}]})
    bounds = Bounds(0, 0, 1200, 600)

    class EpisodeBackend(FakeBackend):
        def mouse_button(self, button, pressed, point):
            super().mouse_button(button, pressed, point)
            if pressed:
                clock.after(0.01, lambda: bridge.publish(3, scene(active=False), {"enemyHealth": []}))

    backend = EpisodeBackend(bounds)
    slots = []
    monkeypatch.setattr(run_baseline, "wait_for_window", lambda _: (99, bounds))
    monkeypatch.setattr(run_baseline, "QuartzBackend", lambda _: backend)
    monkeypatch.setattr(run_baseline, "require_training_slot", slots.append)
    controller_class = run_baseline.Controller
    monkeypatch.setattr(run_baseline, "Controller", lambda fake: controller_class(fake, stop_file=tmp_path / "STOP"))

    result = run_baseline.run_episode(bridge, CombatConfig(), HeuristicPolicy(), slot=2, seed=5)

    assert slots == [2]
    assert result == {"room": "RoomA", "depth": 2, "steps": 1, "return": 2.54, "outcome": "cleared"}
    assert [event[0] for event in backend.events] == ["move", "mouse_down", "mouse_up"]


def test_whiff_penalty_charges_attacks_without_damage_after_the_window(harness):
    bridge, controller, clock = harness
    hidden = {"enemyHealth": [{"id": 1, "hp": 20}]}
    bridge.publish(1, scene(), hidden)
    health = [20]

    def apply():
        frame = bridge.latest_obs.frame + 2
        clock.after(0.01, lambda: bridge.publish(frame, scene(), {"enemyHealth": [{"id": 1, "hp": health[0]}]}))

    controller.on_apply = apply
    config = CombatConfig(reward=RewardConfig(time_penalty=0.0, whiff_penalty=0.1, whiff_window_steps=2))
    env = HadesCombatEnv(bridge, controller, config=config)
    env.reset()
    attack, idle = np.array([0, 1, 0]), np.array([0, 0, 0])
    rewards = [env.step(attack)[1], env.step(idle)[1], env.step(idle)[1]]
    assert rewards == pytest.approx([0.0, 0.0, -0.1])  # charged once two decisions pass without a hit

    env.step(attack)
    health[0] = 10  # the next swing lands: no charge, damage reward only
    assert env.step(idle)[1] == pytest.approx(0.1)
    assert env.step(idle)[1] == pytest.approx(0.0)


def test_whiff_penalty_is_off_by_default():
    assert RewardConfig().whiff_penalty == 0.0
    with pytest.raises(ValueError):
        RewardConfig(whiff_penalty=-1)
