"""Replay the visible bridge observations to label imitation examples."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from agent.env.observations import HistoryEncoder
from agent.policy import HeuristicPolicy, UnstickPolicy


@dataclass(frozen=True)
class Demonstrations:
    observations: np.ndarray
    actions: np.ndarray
    episode_ids: np.ndarray
    sources: list[dict]
    episodes: list[dict]


def build_dataset(
    paths: list[Path], *, frames_per_step: int = 2, max_samples: int | None = None,
) -> Demonstrations:
    if frames_per_step < 1 or (max_samples is not None and max_samples < 1):
        raise ValueError("Frame stride and sample limit must be positive")

    observations, actions, episode_ids = [], [], []
    sources, episodes = [], []
    teacher = UnstickPolicy(HeuristicPolicy())
    # Replays the env's history features with the teacher's own actions.
    encoder = HistoryEncoder()
    for path in paths:
        path = Path(path).resolve()
        start_count = len(observations)
        digest = hashlib.sha256()
        last_frame = last_decision = None
        room_key = episode = None
        bytes_read = 0
        with path.open("rb") as stream:
            # Take a fixed prefix even if the game is still writing this log.
            remaining = os.fstat(stream.fileno()).st_size
            line_number = 0
            while remaining > 0:
                line = stream.readline(remaining)
                if not line:
                    break
                line_number += 1
                try:
                    row = json.loads(line) if line.strip() else {}
                except (UnicodeDecodeError, json.JSONDecodeError) as error:
                    if not line.endswith(b"\n"):
                        break  # A writer can be in the middle of appending this row.
                    raise ValueError(f"{path}:{line_number}: invalid bridge JSON") from error
                remaining -= len(line)
                bytes_read += len(line)
                digest.update(line)
                frame = row.get("f")
                if row.get("k") != "obs" or type(frame) is not int:
                    continue
                # Select the policy view explicitly. Reward-only data is never
                # passed to either the encoder or the teacher.
                visible = (row.get("d") or {}).get("obs")
                if not isinstance(visible, dict):
                    continue
                room = visible.get("room") or {}
                new_key = (room.get("name"), room.get("depth"))
                if new_key != room_key or (last_frame is not None and frame < last_frame):
                    episode = None
                last_frame, room_key = frame, new_key
                combat = room.get("combat")
                dead = (visible.get("hero") or {}).get("dead") is True
                if combat is False or dead:
                    episode = None
                if combat is not True or dead:
                    continue
                if visible.get("screen") not in (None, "InGameUI"):
                    continue
                if episode is None:
                    teacher.reset()
                    encoder.reset()
                    last_decision = None
                    episode = {"source": len(sources), "room": new_key[0], "depth": new_key[1],
                               "first_frame": frame, "samples": 0}
                    episodes.append(episode)
                if last_decision is not None and frame < last_decision + frames_per_step:
                    continue
                observations.append(encoder.encode(visible, frame))
                action = teacher.act(visible)
                encoder.record_action(action)
                actions.append(action)
                episode_ids.append(len(episodes) - 1)
                episode["samples"] += 1
                last_decision = frame
                if max_samples is not None and len(observations) == max_samples:
                    break
        sources.append({"path": str(path), "bytes_read": bytes_read, "sha256_prefix": digest.hexdigest(),
                        "samples": len(observations) - start_count})
        if max_samples is not None and len(observations) == max_samples:
            break
    if not observations:
        raise ValueError("No visible combat observations in the selected bridge logs")
    return Demonstrations(np.stack(observations), np.stack(actions), np.asarray(episode_ids), sources, episodes)


def split_dataset(episode_ids: np.ndarray, validation_fraction: float, seed: int) -> tuple[np.ndarray, np.ndarray]:
    """Keep rooms together, or hold out the final time block of a single room."""
    if not 0 < validation_fraction < 1 or len(episode_ids) < 2:
        raise ValueError("A split needs at least two examples and a validation fraction in (0, 1)")
    episodes = np.unique(episode_ids)
    if len(episodes) == 1:
        count = min(len(episode_ids) - 1, max(1, round(len(episode_ids) * validation_fraction)))
        return np.arange(len(episode_ids) - count), np.arange(len(episode_ids) - count, len(episode_ids))
    order = np.random.default_rng(seed).permutation(episodes)
    count = min(len(episodes) - 1, max(1, round(len(episodes) * validation_fraction)))
    validation = np.isin(episode_ids, order[:count])
    return np.flatnonzero(~validation), np.flatnonzero(validation)
