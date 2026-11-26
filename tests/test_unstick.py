import numpy as np

from agent.policy import UnstickConfig, UnstickPolicy


class Always:
    def __init__(self, move):
        self.move = move

    def reset(self):
        pass

    def act(self, obs):
        return np.array([self.move, 0, 0])


def obs(x, y):
    return {"hero": {"x": x, "y": y}}


def test_sidesteps_when_stuck_then_alternates():
    p = UnstickPolicy(Always(1), UnstickConfig(window=3, min_travel=10, escape_steps=2))  # 1 = right
    acts = [int(p.act(obs(0, 0))[0]) for _ in range(3)]
    assert acts[:2] == [1, 1] and acts[2] == 3  # right -> up (+90 degrees)
    assert int(p.act(obs(0, 0))[0]) == 3 and int(p.act(obs(0, 0))[0]) == 3  # escape steps
    later = [int(p.act(obs(0, 0))[0]) for _ in range(3)]
    assert later[-1] == 7  # next stick goes the other way: right -> down


def test_no_sidestep_when_moving():
    p = UnstickPolicy(Always(1), UnstickConfig(window=3, min_travel=10))
    assert [int(p.act(obs(i * 50, 0))[0]) for i in range(6)] == [1] * 6


def test_no_sidestep_when_standing_still_on_purpose():
    p = UnstickPolicy(Always(0), UnstickConfig(window=3, min_travel=10))
    assert [int(p.act(obs(0, 0))[0]) for _ in range(6)] == [0] * 6
