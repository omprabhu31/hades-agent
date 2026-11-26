"""Supervised warm start for the three action heads."""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
import torch
from torch.nn import functional as F

from .dataset import Demonstrations
from .network import ActorCritic

HEAD_NAMES = ("movement", "button", "aim")


@dataclass(frozen=True)
class BCConfig:
    epochs: int = 15
    batch_size: int = 128
    learning_rate: float = 0.001
    validation_fraction: float = 0.2

    def __post_init__(self) -> None:
        if self.epochs < 1 or self.batch_size < 1:
            raise ValueError("Epoch and batch counts must be positive")
        if not math.isfinite(self.learning_rate) or self.learning_rate <= 0:
            raise ValueError("Learning rate must be positive and finite")
        if not 0 < self.validation_fraction < 1:
            raise ValueError("Validation fraction must be in (0, 1)")


def _head_losses(logits: tuple[torch.Tensor, ...], actions: torch.Tensor) -> list[torch.Tensor]:
    return [F.cross_entropy(head, actions[:, index]) for index, head in enumerate(logits)]


@torch.no_grad()
def score_bc(policy: ActorCritic, observations: torch.Tensor, actions: torch.Tensor, batch_size: int) -> dict:
    loss = 0.0
    correct = dict.fromkeys(HEAD_NAMES, 0)
    for features, labels in zip(observations.split(batch_size), actions.split(batch_size), strict=True):
        logits, _ = policy(features)
        loss += len(labels) * float(sum(_head_losses(logits, labels)))
        for index, name in enumerate(HEAD_NAMES):
            correct[name] += int((logits[index].argmax(dim=-1) == labels[:, index]).sum())
    return {"validation_loss": loss / len(actions),
            "accuracy": {name: hits / len(actions) for name, hits in correct.items()}}


def train_bc(
    policy: ActorCritic,
    data: Demonstrations,
    train_indices: np.ndarray,
    validation_indices: np.ndarray,
    config: BCConfig,
    *,
    seed: int,
    on_record: Callable[[dict], None] | None = None,
) -> dict:
    """Fit the actor and report held-out cross-entropy and accuracy per head."""
    device = policy.device
    train_obs = torch.as_tensor(data.observations[train_indices], device=device)
    train_actions = torch.as_tensor(data.actions[train_indices], device=device)
    val_obs = torch.as_tensor(data.observations[validation_indices], device=device)
    val_actions = torch.as_tensor(data.actions[validation_indices], device=device)
    optimizer = torch.optim.Adam(policy.parameters(), lr=config.learning_rate)
    generator = torch.Generator().manual_seed(seed)
    update = 0
    # Keep the weights with the lowest held-out loss: with ~14k samples the
    # validation loss bottoms out well before the last epoch (seen 2026-11-26).
    best_result, best_state = None, None
    for epoch in range(1, config.epochs + 1):
        policy.train()
        order = torch.randperm(len(train_obs), generator=generator).to(device)
        for batch in order.split(config.batch_size):
            logits, _ = policy(train_obs[batch])
            loss = sum(_head_losses(logits, train_actions[batch]))
            if not bool(torch.isfinite(loss)):
                raise FloatingPointError("Non-finite cloning loss")
            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            optimizer.step()
            update += 1
            if on_record is not None:
                on_record({"kind": "update", "epoch": epoch, "update": update, "loss": float(loss.detach())})
        policy.eval()
        result = {"kind": "validation", "epoch": epoch, "update": update,
                  **score_bc(policy, val_obs, val_actions, config.batch_size)}
        if on_record is not None:
            on_record(result)
        if best_result is None or result["validation_loss"] < best_result["validation_loss"]:
            best_result = result
            best_state = {k: v.detach().clone() for k, v in policy.state_dict().items()}
    if best_state is not None:
        policy.load_state_dict(best_state)
    return {**best_result, "best_epoch": best_result["epoch"], "final": result}
