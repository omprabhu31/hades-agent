"""Scripted decisions on synthetic scenes with visible values only."""

import numpy as np

from agent.env.actions import ATTACK, CAST, DASH, IDLE
from agent.policy import HeuristicPolicy


def scene(*targets, facing=0, hp=40, ammo=0):
    return {
        "hero": {"x": 100, "y": 200, "angle": facing, "hp": hp, "castAmmo": ammo},
        "enemies": [{"x": 100 + dx, "y": 200 + dy} for dx, dy in targets],
    }


def test_attacks_nearest_enemy_when_in_band_and_facing_it():
    policy = HeuristicPolicy()
    action = policy.act(scene((-250, 0), (0, -125), facing=90))
    np.testing.assert_array_equal(action, [0, ATTACK, 2])
    assert action.dtype == np.int64


def test_turns_towards_enemy_and_handles_angle_wrap():
    policy = HeuristicPolicy()
    np.testing.assert_array_equal(policy.act(scene((120, 0), facing=180)), [1, IDLE, 0])
    np.testing.assert_array_equal(policy.act(scene((120, 0), facing=350)), [0, ATTACK, 0])


def test_approaches_at_range_and_casts_only_with_ammo_in_its_band():
    policy = HeuristicPolicy()
    np.testing.assert_array_equal(policy.act(scene((-700, 0), ammo=3)), [5, IDLE, 4])
    np.testing.assert_array_equal(policy.act(scene((-400, 0), ammo=0)), [5, IDLE, 4])
    np.testing.assert_array_equal(policy.act(scene((-400, 0), ammo=3)), [5, CAST, 4])
    np.testing.assert_array_equal(policy.act(scene((-400, 0), ammo=3)), [5, IDLE, 4])
    np.testing.assert_array_equal(policy.act(scene((-400, 0), ammo=2)), [5, CAST, 4])


def test_dashes_away_on_recent_visible_damage_and_then_lets_memory_expire():
    policy = HeuristicPolicy()
    np.testing.assert_array_equal(policy.act(scene((50, 0))), [5, ATTACK, 0])
    np.testing.assert_array_equal(policy.act(scene((50, 0), hp=38)), [5, DASH, 0])
    np.testing.assert_array_equal(policy.act(scene((50, 0), hp=38)), [5, IDLE, 0])
    np.testing.assert_array_equal(policy.act(scene((50, 0), hp=38)), [5, DASH, 0])
    np.testing.assert_array_equal(policy.act(scene((50, 0), hp=38)), [5, ATTACK, 0])


def test_reset_clears_damage_memory_and_hidden_hud_cannot_trigger_cast_or_dash():
    policy = HeuristicPolicy()
    policy.act(scene((50, 0)))
    assert policy.act(scene((50, 0), hp=30))[1] == DASH
    policy.reset()
    assert policy.act(scene((50, 0), hp=29))[1] == ATTACK
    obs = {**scene((400, 0), hp=20, ammo=2), "hud": False}
    np.testing.assert_array_equal(policy.act(obs), [1, IDLE, 0])
    obs = {**scene((50, 0), hp=19, ammo=2), "hud": False}
    np.testing.assert_array_equal(policy.act(obs), [5, ATTACK, 0])


def test_waits_and_keeps_facing_when_no_target_is_visible():
    policy = HeuristicPolicy()
    np.testing.assert_array_equal(policy.act(scene(facing=270)), [0, IDLE, 6])
