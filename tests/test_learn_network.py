import numpy as np
import pytest
import torch

from agent.env.observations import OBSERVATION_SIZE
from agent.learn.network import ACTION_SIZES, ActorCritic, PolicyConfig, load_checkpoint, save_checkpoint, seed_training


def test_actor_critic_shapes_and_unmasked_sampling():
    seed_training(1)
    policy = ActorCritic()
    features = torch.zeros((4, OBSERVATION_SIZE))
    logits, values = policy(features)
    assert [tuple(head.shape) for head in logits] == [(4, 9), (4, 5), (4, 8)]
    assert values.shape == (4,)

    observation = features[0].numpy()
    rng = torch.Generator().manual_seed(25)
    replay = torch.Generator().manual_seed(25)
    sampled = []
    for _ in range(150):
        action, log_prob, value = policy.decide(observation, generator=rng)
        reference, _, _ = policy.decide(observation, generator=replay)
        np.testing.assert_array_equal(action, reference)
        sampled.append(action)
    for axis, size in enumerate(ACTION_SIZES):
        assert set(np.stack(sampled)[:, axis]) == set(range(size))

    new_log_prob, entropy, estimated_value = policy.evaluate_actions(features[0], torch.from_numpy(action))
    assert float(new_log_prob.detach()) == pytest.approx(log_prob, abs=1e-6)
    assert float(estimated_value.detach()) == pytest.approx(value, abs=1e-6)
    assert float(entropy.detach()) > 0


def test_checkpoint_round_trip_and_obs_size_check(tmp_path):
    path = tmp_path / "checkpoints" / "policy.pt"
    policy = ActorCritic(PolicyConfig(hidden_sizes=(16,)))
    observation = np.linspace(-1, 1, OBSERVATION_SIZE, dtype=np.float32)
    save_checkpoint(path, policy, {"kind": "bc", "seed": 7})
    restored, metadata = load_checkpoint(path)
    assert metadata == {"kind": "bc", "seed": 7}
    assert restored.config == policy.config
    expected = policy.decide(observation, deterministic=True)
    actual = restored.decide(observation, deterministic=True)
    np.testing.assert_array_equal(actual[0], expected[0])
    assert actual[1:] == expected[1:]

    payload = torch.load(path, weights_only=True)
    payload["policy_config"]["observation_size"] += 1
    torch.save(payload, path)
    with pytest.raises(ValueError, match="observation size"):
        load_checkpoint(path)
