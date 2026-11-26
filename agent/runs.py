"""Per-run records: parameters, results and a video clip of every episode.

Every training or evaluation run gets its own directory, runs/<stamp>-<name>/:
  meta.json            command, all configs, seed, date, hardware, git state,
                       game build, mod hash, bridge log path
  code.tar.gz          snapshot of agent/, scripts/, mod/ as run (no git history yet)
  episodes.jsonl       one line per episode with outcome and metrics
  summary.json         aggregates, rewritten after every episode
  clips/ep_NNNN.mp4    screen recording of each episode
`python -m scripts.compare_runs` tabulates runs side by side.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
import sys
import tarfile
import time
from datetime import datetime, timezone
from pathlib import Path

from agent.bridge.game import ROOT

RUNS = ROOT / "runs"
GAME_RES = Path.home() / ("Library/Application Support/Steam/steamapps/common/Hades/"
                          "Game.macOS.app/Contents/Resources")


def _git() -> dict:
    def run(*args):
        r = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)
        return r.stdout.strip() if r.returncode == 0 else None
    return {"sha": run("rev-parse", "--verify", "HEAD"), "dirty": bool(run("status", "--porcelain")),
            "branch": run("branch", "--show-current")}


def _hardware() -> dict:
    mem = subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True).stdout.strip()
    cpu = subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string"], capture_output=True, text=True).stdout.strip()
    return {"machine": platform.machine(), "cpu": cpu, "ram_bytes": int(mem or 0),
            "macos": platform.mac_ver()[0], "python": sys.version.split()[0]}


def _sha256(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


class ClipRecorder:
    """Records the screen with ffmpeg while Hades is frontmost.

    The whole display is captured (the game covers it during a run), the
    menu bar cropped off, downscaled to 960 px wide at 15 fps.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self.proc: subprocess.Popen | None = None

    def start(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.proc = subprocess.Popen(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
             "-f", "avfoundation", "-capture_cursor", "1", "-framerate", "30",
             "-i", "Capture screen 0:none",
             "-vf", "crop=iw:ih-66:0:66,scale=960:-2,fps=15",
             "-c:v", "libx264", "-preset", "ultrafast", "-crf", "30", "-pix_fmt", "yuv420p",
             str(self.path)],
            stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def stop(self) -> None:
        if self.proc is None:
            return
        try:
            self.proc.communicate(b"q", timeout=10)  # 'q' lets ffmpeg finalise the mp4
        except subprocess.TimeoutExpired:
            self.proc.kill()
        self.proc = None


class RunRecorder:
    def __init__(self, name: str, args: dict, configs: dict, seed: int, bridge_log: str | None,
                 clips: bool = True) -> None:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        self.dir = RUNS / f"{stamp}-{name}"
        self.dir.mkdir(parents=True)
        self.clips = clips
        self.episodes: list[dict] = []
        build = GAME_RES / "Content" / "buildinfo.txt"
        meta = {
            "name": name, "started": datetime.now(timezone.utc).isoformat(),
            "command": [sys.executable, *sys.argv], "cwd": os.getcwd(), "args": args,
            "configs": configs, "seed": seed, "git": _git(), "hardware": _hardware(),
            "game_build": build.read_text().strip()[:200] if build.exists() else None,
            "mod_sha256": _sha256(GAME_RES / "Content" / "Scripts" / "AgentBridge.lua"),
            "mod_source_sha256": _sha256(ROOT / "mod" / "AgentBridge.lua"),
            "bridge_log": bridge_log,
        }
        (self.dir / "meta.json").write_text(json.dumps(meta, indent=1))
        with tarfile.open(self.dir / "code.tar.gz", "w:gz") as tar:
            for sub in ("agent", "scripts", "mod", "environment.yml"):
                tar.add(ROOT / sub, arcname=sub,
                        filter=lambda ti: None if "__pycache__" in ti.name else ti)
        self._clip: ClipRecorder | None = None

    def start_episode(self, index: int) -> None:
        if self.clips:
            self._clip = ClipRecorder(self.dir / "clips" / f"ep_{index:04d}.mp4")
            self._clip.start()
            self._t0 = time.time()

    def end_episode(self, record: dict) -> None:
        if self._clip is not None:
            self._clip.stop()
            record["clip"] = str(self._clip.path.relative_to(self.dir))
            self._clip = None
        self.episodes.append(record)
        with open(self.dir / "episodes.jsonl", "a") as f:
            f.write(json.dumps(record) + "\n")
        self.write_summary()

    def write_summary(self) -> None:
        eps = self.episodes
        n = len(eps)

        def mean(key):
            vals = [e[key] for e in eps if isinstance(e.get(key), (int, float))]
            return round(sum(vals) / len(vals), 3) if vals else None

        summary = {
            "episodes": n,
            "cleared": sum(e.get("outcome") == "cleared" for e in eps),
            "deaths": sum(e.get("outcome") == "dead" for e in eps),
            "clear_rate": round(sum(e.get("outcome") == "cleared" for e in eps) / n, 3) if n else None,
            "mean_return": mean("return"), "mean_damage_dealt": mean("damage_dealt"),
            "mean_damage_taken": mean("damage_taken"), "mean_game_seconds": mean("game_seconds"),
            "mean_kills": mean("kills"), "updated": datetime.now(timezone.utc).isoformat(),
        }
        (self.dir / "summary.json").write_text(json.dumps(summary, indent=1))

    def close(self) -> None:
        if self._clip is not None:
            self._clip.stop()
            self._clip = None
