import math

import numpy as np

from agent.env.observations import (ACTION_SIZES, ATTACK_SIZE, BASE_SIZE, HISTORY_SIZE, HISTORY_START,
                                    MAX_ENEMIES, MAX_TRAPS, OBSERVATION_SIZE, PREVIOUS_ACTIONS,
                                    HistoryEncoder, encode_attacks)

HIST = HISTORY_START  # first history column
ACTIONS_AT = HIST + 6
ENEMY_VEL_AT = HIST + 6 + PREVIOUS_ACTIONS * sum(ACTION_SIZES)


def frame(x, y, hp=50, angle=90.0, enemies=()):
    return {"hero": {"x": x, "y": y, "hp": hp, "maxHp": 50, "angle": angle}, "hud": True,
            "room": {"combat": True}, "enemies": list(enemies)}


def test_sizes():
    assert OBSERVATION_SIZE == BASE_SIZE + ATTACK_SIZE + HISTORY_SIZE
    assert ENEMY_VEL_AT + 2 * MAX_ENEMIES == OBSERVATION_SIZE


def test_facing_velocity_and_travel():
    enc = HistoryEncoder()
    v0 = enc.encode(frame(0, 0))
    assert v0[HIST] == np.float32(math.sin(math.radians(90))) and abs(v0[HIST + 1]) < 1e-6
    assert not v0[HIST + 2:HIST + 5].any()  # no motion on the first frame
    v1 = enc.encode(frame(50, -20))
    assert v1[HIST + 2] == np.float32(0.5) and v1[HIST + 3] == np.float32(-0.2)
    assert v1[HIST + 4] > 0


def test_hit_recency_decays():
    enc = HistoryEncoder()
    enc.encode(frame(0, 0, hp=50))
    assert enc.encode(frame(0, 0, hp=40))[HIST + 5] == 1.0
    assert enc.encode(frame(0, 0, hp=40))[HIST + 5] == 0.5


def test_previous_actions_one_hot_most_recent_first():
    enc = HistoryEncoder()
    enc.record_action([3, 1, 7])
    enc.record_action([0, 4, 2])
    v = enc.encode(frame(0, 0))
    first = v[ACTIONS_AT:ACTIONS_AT + sum(ACTION_SIZES)]
    assert first[0] == 1 and first[9 + 4] == 1 and first[14 + 2] == 1 and first.sum() == 3
    second = v[ACTIONS_AT + sum(ACTION_SIZES):ENEMY_VEL_AT]
    assert second[3] == 1 and second[9 + 1] == 1 and second[14 + 7] == 1


def test_enemy_velocity_tracked_by_id():
    enc = HistoryEncoder()
    enc.encode(frame(0, 0, enemies=[{"id": 7, "x": 100, "y": 0}]))
    v = enc.encode(frame(0, 0, enemies=[{"id": 7, "x": 80, "y": 10}]))
    assert v[ENEMY_VEL_AT] == np.float32(-0.2) and v[ENEMY_VEL_AT + 1] == np.float32(0.1)


def test_reset_clears_history():
    enc = HistoryEncoder()
    enc.encode(frame(0, 0, hp=50))
    enc.record_action([1, 1, 1])
    enc.reset()
    assert not enc.encode(frame(100, 100, hp=10))[HIST + 2:].any()


def test_hud_hidden_hp_not_used():
    enc = HistoryEncoder()
    enc.encode(frame(0, 0, hp=50))
    hidden = frame(0, 0, hp=10)
    hidden["hud"] = False
    assert enc.encode(hidden)[HIST + 5] == 0  # a hidden HUD cannot reveal a hit


def test_attack_block_recency_and_shots():
    obs = frame(0, 0, enemies=[{"id": 1, "x": 50, "y": 0, "firedAgo": 0.5}, {"id": 2, "x": 900, "y": 0}])
    obs["traps"] = [{"x": 10, "y": 0, "firedAgo": 0.0}]
    obs["shots"] = [{"owner": 1, "name": "BoneShot", "x": 50, "y": 0, "angle": 180.0, "age": 1.0}]
    v = encode_attacks(obs)
    assert v[0] == np.float32(0.75) and v[1] == 0           # nearest enemy attacked 0.5 s ago
    assert v[MAX_ENEMIES] == 1.0                              # trap fired just now
    shot = v[MAX_ENEMIES + MAX_TRAPS:MAX_ENEMIES + MAX_TRAPS + 6]
    np.testing.assert_allclose(shot, [0.05, 0, -1, 0, 0.5, 1], atol=1e-6)  # flying left, half-way through memory
    full = HistoryEncoder().encode(obs)
    np.testing.assert_array_equal(full[BASE_SIZE:HISTORY_START], v)
