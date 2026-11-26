"""The learned combat policy consumes only the environment's numeric vector."""

from __future__ import annotations

import os
import random
from dataclasses import asdict, dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile

import numpy as np
import torch
from torch import nn
from torch.distributions import Categorical

from agent.env.actions import AIM_SECTORS, BUTTONS, MOVEMENTS
from agent.env.observations import OBSERVATION_SIZE

ACTION_SIZES = (len(MOVEMENTS), len(BUTTONS), AIM_SECTORS)
CHECKPOINT_VERSION = 1


@dataclass(frozen=True)
class PolicyConfig:
    observation_size: int = OBSERVATION_SIZE
    hidden_sizes: tuple[int, ...] = (64, 64)
    action_sizes: tuple[int, ...] = ACTION_SIZES

    def __post_init__(self) -> None:
        if self.observation_size != OBSERVATION_SIZE:
            raise ValueError(f"Expected observation size {OBSERVATION_SIZE}, got {self.observation_size}")
        if self.action_sizes != ACTION_SIZES:
            raise ValueError(f"Expected action head sizes {ACTION_SIZES}, got {self.action_sizes}")
        if not self.hidden_sizes or any(type(size) is not int or size < 1 for size in self.hidden_sizes):
            raise ValueError("Hidden layer widths must be positive integers")


def seed_training(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)


def resolve_device(device: str = "auto") -> torch.device:
    if device == "auto":
        device = "mps" if torch.backends.mps.is_available() else "cpu"
    if device not in ("cpu", "mps"):
        raise ValueError("Device must be auto, cpu or mps")
    if device == "mps" and not torch.backends.mps.is_available():
        raise ValueError("MPS is unavailable")
    return torch.device(device)


class ActorCritic(nn.Module):
    def __init__(self, config: PolicyConfig = PolicyConfig()) -> None:
        super().__init__()
        self.config = config
        layers = []
        width = config.observation_size
        for size in config.hidden_sizes:
            layers.extend((nn.Linear(width, size), nn.Tanh()))
            width = size
        self.encoder = nn.Sequential(*layers)
        self.actor = nn.ModuleList(nn.Linear(width, size) for size in config.action_sizes)
        self.critic = nn.Linear(width, 1)

    @property
    def device(self) -> torch.device:
        return self.critic.weight.device

    def forward(self, observations: torch.Tensor) -> tuple[tuple[torch.Tensor, ...], torch.Tensor]:
        if observations.ndim not in (1, 2) or observations.shape[-1] != self.config.observation_size:
            raise ValueError(f"Expected vectors of length {self.config.observation_size}")
        features = self.encoder(observations)
        return tuple(head(features) for head in self.actor), self.critic(features).squeeze(-1)

    @torch.no_grad()
    def decide(
        self,
        observation: np.ndarray,
        *,
        deterministic: bool = False,
        generator: torch.Generator | None = None,
    ) -> tuple[np.ndarray, float, float]:
        """Return the action, joint log probability and value of one observation."""
        if observation.shape != (self.config.observation_size,):
            raise ValueError(f"Expected one vector of length {self.config.observation_size}")
        tensor = torch.as_tensor(observation, dtype=torch.float32, device=self.device)
        logits, value = self(tensor)
        actions = []
        joint_log_prob = 0.0
        for head in logits:
            # A seeded CPU generator works for sampling with either model device.
            log_probs = head.cpu().log_softmax(dim=-1)
            if deterministic:
                action = int(log_probs.argmax())
            else:
                action = int(torch.multinomial(log_probs.exp(), 1, generator=generator).item())
            actions.append(action)
            joint_log_prob += float(log_probs[action])
        return np.asarray(actions, dtype=np.int64), joint_log_prob, float(value)

    @torch.no_grad()
    def value(self, observation: np.ndarray) -> float:
        tensor = torch.as_tensor(observation, dtype=torch.float32, device=self.device)
        return float(self(tensor)[1])

    def evaluate_actions(
        self, observations: torch.Tensor, actions: torch.Tensor,
    ) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        """The independent heads form one joint policy for the PPO ratio."""
        logits, values = self(observations)
        distributions = [Categorical(logits=head, validate_args=False) for head in logits]
        log_prob = sum(dist.log_prob(actions[..., i]) for i, dist in enumerate(distributions))
        entropy = sum(dist.entropy() for dist in distributions)
        return log_prob, entropy, values


def save_checkpoint(path: Path, policy: ActorCritic, metadata: dict) -> None:
    """Publish a fully written checkpoint, including a portable policy configuration."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}-", delete=False) as handle:
        temporary = Path(handle.name)
        try:
            torch.save({
                "version": CHECKPOINT_VERSION,
                "policy_config": asdict(policy.config),
                "state_dict": policy.state_dict(),
                "metadata": metadata,
            }, handle)
            handle.flush()
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


def load_checkpoint(path: Path, device: torch.device | str = "cpu") -> tuple[ActorCritic, dict]:
    payload = torch.load(path, map_location="cpu", weights_only=True)
    if not isinstance(payload, dict) or payload.get("version") != CHECKPOINT_VERSION:
        raise ValueError(f"Unsupported combat checkpoint format: {path}")
    config = PolicyConfig(**payload["policy_config"])
    policy = ActorCritic(config)
    policy.load_state_dict(payload["state_dict"])
    return policy.to(device).eval(), payload["metadata"]
