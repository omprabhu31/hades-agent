import numpy as np
import pytest
import torch

from agent.env.observations import OBSERVATION_SIZE
from agent.learn.network import ActorCritic, seed_training
from agent.learn.ppo import PPOConfig, PPOTrainer, Rollout, generalised_advantages


class FakeCombat:
    def __init__(self, *, steps=32, outcome="cleared", hidden=0, move_observation=False):
        self.limit = steps
        self.outcome = outcome
        self.hidden = hidden
        self.move_observation = move_observation
        self.actions = []
        self.closed = True

    def reset(self):
        self.actions.clear()
        self.closed = False
        self.observation = np.zeros(OBSERVATION_SIZE, dtype=np.float32)
        return self.observation, {"info": {"hidden": self.hidden}}

    def step(self, action):
        assert not self.closed
        self.actions.append(action.copy())
        if self.move_observation:
            self.observation[0] += 0.1
        finished = len(self.actions) == self.limit
        terminated = finished and self.outcome in ("cleared", "dead")
        truncated = finished and not terminated
        return self.observation, float(action[0] == 2), terminated, truncated, {
            "outcome": self.outcome if finished else None,
            "info": {"hidden": self.hidden, "observation": np.full_like(self.observation, self.hidden)},
        }

    def close(self):
        self.closed = True


def test_ppo_improves_toy_objective():
    seed_training(31)
    policy = ActorCritic()
    trainer = PPOTrainer(policy, PPOConfig(learning_rate=0.012, gamma=0, rollout_steps=8, batch_size=16), seed=31)
    env = FakeCombat()

    @torch.no_grad()
    def success_probability():
        heads, _ = policy(torch.zeros(OBSERVATION_SIZE))
        return float(heads[0].softmax(-1)[2])

    before = success_probability()
    for update in range(1, 5):
        observation, _ = env.reset()
        info, _, steps, metrics = trainer.train_step(env, observation)
        assert info["outcome"] == "cleared"
        assert env.closed
        assert steps == metrics["steps"] == 32
        assert metrics["update"] == update
        assert np.isfinite(metrics["loss"])
    assert success_probability() > before + 0.35


def test_gae_bootstraps_short_rollout_cuts():
    rollout = Rollout(rewards=[1, 2, 3], values=[0.5, 0.25, 0.75], bootstrap_value=1)
    advantages, returns = generalised_advantages(rollout, PPOConfig(gamma=0.5, gae_lambda=1, rollout_steps=2))
    np.testing.assert_allclose(advantages, [1.6875, 2.125, 2.75])
    np.testing.assert_allclose(returns, [2.1875, 2.375, 3.5])


@pytest.mark.parametrize("outcome, expected", [("step_limit", 0.8), ("timeout", 0), ("room_changed", 0), ("dead", 0)])
def test_ppo_bootstrapping_and_input_release(outcome, expected):
    policy = ActorCritic()
    with torch.no_grad():
        policy.critic.weight.zero_()
        policy.critic.bias.fill_(0.8)
    trainer = PPOTrainer(policy, PPOConfig(), seed=0)
    env = FakeCombat(steps=2, outcome=outcome)
    observation, _ = env.reset()
    rollout, info = trainer.collect_episode(env, observation)
    assert rollout.bootstrap_value == pytest.approx(expected)
    assert info["outcome"] == outcome
    assert env.closed


def test_ppo_info_isolation_and_observation_copy():
    policy = ActorCritic()
    config = PPOConfig()
    clean, polluted = FakeCombat(steps=3, move_observation=True), FakeCombat(steps=3, hidden=99, move_observation=True)
    clean_obs, _ = clean.reset()
    polluted_obs, _ = polluted.reset()
    one, _ = PPOTrainer(policy, config, seed=2).collect_episode(clean, clean_obs)
    callbacks = []
    two, _ = PPOTrainer(policy, config, seed=2).collect_episode(polluted, polluted_obs, callbacks.append)
    np.testing.assert_array_equal(one.observations, two.observations)
    np.testing.assert_array_equal(one.actions, two.actions)
    np.testing.assert_allclose(np.stack(two.observations)[:, 0], [0, 0.1, 0.2])
    assert [info["info"]["hidden"] for info in callbacks] == [99, 99, 99]


def test_ppo_releases_input_when_a_step_callback_fails():
    trainer = PPOTrainer(ActorCritic(), PPOConfig(), seed=0)
    env = FakeCombat()
    observation, _ = env.reset()

    def fail(_info):
        raise RuntimeError("logging failed")

    with pytest.raises(RuntimeError, match="logging failed"):
        trainer.collect_episode(env, observation, fail)
    assert env.closed
