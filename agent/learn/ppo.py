"""Single-environment PPO that lets the macro runner own room transitions."""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np
import torch
from torch.nn import functional as F

from agent.env import HadesCombatEnv

from .network import ActorCritic


@dataclass(frozen=True)
class PPOConfig:
    learning_rate: float = 0.0003
    gamma: float = 0.99
    gae_lambda: float = 0.95
    clip_ratio: float = 0.2
    entropy_coefficient: float = 0.01
    value_coefficient: float = 0.5
    max_grad_norm: float = 0.5
    rollout_steps: int = 256
    batch_size: int = 64
    epochs: int = 4

    def __post_init__(self) -> None:
        if min(self.rollout_steps, self.batch_size, self.epochs) < 1:
            raise ValueError("Rollout size, batch size and epochs must be positive")
        if not (0 <= self.gamma <= 1 and 0 <= self.gae_lambda <= 1 and 0 < self.clip_ratio < 1):
            raise ValueError("Invalid PPO discount, GAE lambda or clipping ratio")
        positive = (self.learning_rate, self.max_grad_norm)
        nonnegative = (self.entropy_coefficient, self.value_coefficient)
        if any(not math.isfinite(x) or x <= 0 for x in positive):
            raise ValueError("Learning rate and gradient norm limit must be positive and finite")
        if any(not math.isfinite(x) or x < 0 for x in nonnegative):
            raise ValueError("Entropy and value coefficients must be non-negative and finite")


@dataclass
class Rollout:
    observations: list[np.ndarray] = field(default_factory=list)
    actions: list[np.ndarray] = field(default_factory=list)
    rewards: list[float] = field(default_factory=list)
    log_probs: list[float] = field(default_factory=list)
    values: list[float] = field(default_factory=list)
    bootstrap_value: float = 0.0


def generalised_advantages(rollout: Rollout, config: PPOConfig) -> tuple[np.ndarray, np.ndarray]:
    """GAE over short segments, bootstrapping at each internal rollout cut."""
    values = np.asarray(rollout.values, dtype=np.float32)
    advantages = np.empty_like(values)
    for start in range(0, len(values), config.rollout_steps):
        end = min(start + config.rollout_steps, len(values))
        next_value = float(values[end]) if end < len(values) else rollout.bootstrap_value
        trace = 0.0
        for index in range(end - 1, start - 1, -1):
            delta = rollout.rewards[index] + config.gamma * next_value - float(values[index])
            trace = delta + config.gamma * config.gae_lambda * trace
            advantages[index] = trace
            next_value = float(values[index])
    return advantages, advantages + values


class PPOTrainer:
    def __init__(self, policy: ActorCritic, config: PPOConfig, *, seed: int) -> None:
        self.policy = policy
        self.config = config
        self.optimizer = torch.optim.Adam(policy.parameters(), lr=config.learning_rate)
        self.sampling = torch.Generator().manual_seed(seed)
        self.shuffle = torch.Generator().manual_seed(seed)
        self.updates = 0

    def collect_episode(
        self, env: HadesCombatEnv, observation: np.ndarray, after_step: Callable[[dict], None] | None = None,
    ) -> tuple[Rollout, dict]:
        """Collect one room from an already reset env. Release input before returning."""
        rollout = Rollout()
        self.policy.eval()
        try:
            while True:
                # Copy before stepping because a Gym environment may reuse its
                # observation array. Info never contributes policy features.
                rollout.observations.append(observation.copy())
                action, log_prob, value = self.policy.decide(observation, generator=self.sampling)
                observation, reward, terminated, truncated, info = env.step(action)
                rollout.actions.append(action)
                rollout.rewards.append(reward)
                rollout.log_probs.append(log_prob)
                rollout.values.append(value)
                if after_step is not None:
                    after_step(info)
                if terminated or truncated:
                    break
        finally:
            env.close()

        # A step-limit observation still describes the chamber. A bridge
        # timeout repeats the previous frame, and a room change crosses tasks.
        if truncated and not terminated and info.get("outcome") not in ("timeout", "room_changed"):
            rollout.bootstrap_value = self.policy.value(observation)
        return rollout, info

    def train_step(
        self, env: HadesCombatEnv, observation: np.ndarray, after_step: Callable[[dict], None] | None = None,
    ) -> tuple[dict, float, int, dict]:
        """Collect and update for one already reset combat episode."""
        rollout, info = self.collect_episode(env, observation, after_step)
        return info, sum(rollout.rewards), len(rollout.rewards), self.update(rollout)

    def update(self, rollout: Rollout) -> dict:
        """Update after the room so optimisation never leaves active inputs held."""
        cfg = self.config
        device = self.policy.device
        observations = torch.as_tensor(np.stack(rollout.observations), device=device)
        actions = torch.as_tensor(np.stack(rollout.actions), device=device)
        old_log_probs = torch.tensor(rollout.log_probs, dtype=torch.float32, device=device)
        advantages, returns = generalised_advantages(rollout, cfg)
        advantages = torch.as_tensor(advantages, device=device)
        returns = torch.as_tensor(returns, device=device)
        if len(advantages) > 1:
            advantages = (advantages - advantages.mean()) / (advantages.std(unbiased=False) + 1e-8)

        totals = dict.fromkeys(("loss", "policy_loss", "value_loss", "entropy", "approx_kl", "clip_fraction"), 0.0)
        self.policy.train()
        for _ in range(cfg.epochs):
            order = torch.randperm(len(actions), generator=self.shuffle).to(device)
            for batch in order.split(cfg.batch_size):
                log_probs, entropy, values = self.policy.evaluate_actions(observations[batch], actions[batch])
                log_ratio = log_probs - old_log_probs[batch]
                ratio = log_ratio.exp()
                clipped_ratio = ratio.clamp(1.0 - cfg.clip_ratio, 1.0 + cfg.clip_ratio)
                advantage = advantages[batch]
                policy_loss = -torch.minimum(ratio * advantage, clipped_ratio * advantage).mean()
                value_loss = F.mse_loss(values, returns[batch])
                entropy = entropy.mean()
                loss = policy_loss + cfg.value_coefficient * value_loss - cfg.entropy_coefficient * entropy
                if not bool(torch.isfinite(loss)):
                    raise FloatingPointError("Non-finite PPO loss")

                self.optimizer.zero_grad(set_to_none=True)
                loss.backward()
                torch.nn.utils.clip_grad_norm_(self.policy.parameters(), cfg.max_grad_norm)
                self.optimizer.step()

                with torch.no_grad():
                    approx_kl = (ratio - 1.0 - log_ratio).mean()
                    clip_fraction = ((ratio - 1.0).abs() > cfg.clip_ratio).float().mean()
                    metrics = (loss, policy_loss, value_loss, entropy, approx_kl, clip_fraction)
                    for key, value in zip(totals, metrics, strict=True):
                        totals[key] += len(batch) * float(value)
        self.policy.eval()
        self.updates += 1
        count = cfg.epochs * len(actions)
        return {"update": self.updates, "steps": len(actions), **{key: val / count for key, val in totals.items()}}
