"""Metadata shared by offline and live learning runs."""

import hashlib
import re
from pathlib import Path

from agent.runs import RunRecorder


def validate_run_name(name: str) -> None:
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", name):
        raise ValueError("Run name must be 1-64 letters, digits, dots, underscores or hyphens")


def checkpoint_reference(path: Path) -> dict:
    path = path.resolve()
    with path.open("rb") as handle:
        digest = hashlib.file_digest(handle, "sha256").hexdigest()
    return {"checkpoint": str(path), "checkpoint_sha256": digest}


def require_episode_clip(record: dict, recorder: RunRecorder) -> None:
    # The existing recorder provides a path even if ffmpeg exited early.
    clip = record.get("clip")
    if clip:
        path = recorder.dir / clip
        if path.is_file() and path.stat().st_size > 0:
            return
    raise RuntimeError(f"Episode {record['episode']} has no recorded clip in {recorder.dir}")
