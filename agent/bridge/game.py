"""Python side of the AgentBridge mod.

The mod prints "AGB1 <json>" lines to the game's stdout, so the game must be
launched by this process to read them. Commands go the other way through
runtime/cmd.lua, which the mod polls with loadfile().
"""
from __future__ import annotations

import collections
import fcntl
import json
import os
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
GAME_BIN = Path.home() / (
    "Library/Application Support/Steam/steamapps/common/Hades/"
    "Game.macOS.app/Contents/MacOS/Game.macOS"
)
# The installed mod reads exactly this path; it is not configurable.
CMD_PATH = ROOT / "runtime" / "cmd.lua"
LOCK_PATH = ROOT / "runtime" / "launch.lock"
PREFIX = "AGB1 "


@dataclass
class BridgeMessage:
    kind: str
    frame: int | None
    data: Any
    t: float  # wall-clock receive time


def parse_line(line: str, t: float | None = None) -> BridgeMessage | None:
    """Parse one stdout line; returns None for the game's own log lines."""
    if not line.startswith(PREFIX):
        return None
    t = t or time.time()
    try:
        msg = json.loads(line[len(PREFIX):])
    except json.JSONDecodeError:
        return BridgeMessage("bad_json", None, line, t)
    if not isinstance(msg, dict) or not isinstance(msg.get("k"), str):
        return BridgeMessage("bad_json", None, line, t)
    return BridgeMessage(msg["k"], msg.get("f"), msg.get("d"), t)


def lua_literal(value: Any) -> str:
    """Encode simple Python data as a Lua table constructor."""
    if value is None:
        return "nil"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise ValueError("non-finite number")
        return repr(value)
    if isinstance(value, str):
        return json.dumps(value)  # JSON string escapes are valid Lua escapes for ASCII
    if isinstance(value, dict):
        items = []
        for k, v in value.items():
            if not str(k).isidentifier():
                raise ValueError(f"unsupported key {k!r}")
            items.append(f"{k} = {lua_literal(v)}")
        return "{ " + ", ".join(items) + " }"
    if isinstance(value, (list, tuple)):
        return "{ " + ", ".join(lua_literal(v) for v in value) + " }"
    raise TypeError(f"cannot encode {type(value).__name__}")


def running_game_pids() -> list[int]:
    r = subprocess.run(["pgrep", "-x", "Game.macOS"], capture_output=True, text=True)
    if r.returncode == 1:
        return []
    if r.returncode != 0:  # fail closed: unknown means "maybe running"
        raise RuntimeError(f"pgrep failed ({r.returncode}): {r.stderr.strip()}")
    return [int(x) for x in r.stdout.split()]


def send_command(cmd: str, seq: int | None = None, **fields: Any) -> int:
    """Publish one command for the mod; returns its sequence number.

    Sequence numbers are milliseconds since the epoch, so they increase across
    processes and game restarts. The mod keeps one mailbox: wait for the ack
    before sending the next command.
    """
    seq = seq if seq is not None else time.time_ns() // 1_000_000
    body = {"seq": seq, "cmd": cmd, **fields}
    CMD_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=CMD_PATH.parent, prefix=".cmd-", suffix=".tmp")
    with os.fdopen(fd, "w") as f:
        f.write("return " + lua_literal(body) + "\n")
    os.replace(tmp, CMD_PATH)  # atomic: the mod never sees half a file
    return seq


class GameBridge:
    """Launches the single Hades instance, collects messages, sends commands."""

    def __init__(self, log_path: Path | None = None, max_messages: int = 10_000) -> None:
        self.log_path = log_path
        self.proc: subprocess.Popen | None = None
        # Bounded: if nobody drains events, the oldest are dropped, never the game.
        self.messages: collections.deque[BridgeMessage] = collections.deque(maxlen=max_messages)
        self._cv = threading.Condition()
        self.latest_obs: BridgeMessage | None = None
        self.reader_error: BaseException | None = None
        self._reader: threading.Thread | None = None
        self._lock_fd: int | None = None

    # -- process -----------------------------------------------------------
    def launch(self, start_reader: bool = True) -> None:
        # Hard rule: only one Hades instance at a time (AGENTS.md). The file
        # lock serialises our own launchers; pgrep catches manual launches.
        LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(LOCK_PATH, os.O_CREAT | os.O_RDWR, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(fd)
            raise RuntimeError("another launcher holds the game lock")
        try:
            if running_game_pids():
                raise RuntimeError("Hades is already running; stop it before launching another")
            CMD_PATH.unlink(missing_ok=True)  # never replay an old command
            self.proc = subprocess.Popen(
                [str(GAME_BIN)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, errors="replace", bufsize=1,
            )
        except BaseException:
            os.close(fd)
            raise
        self._lock_fd = fd  # held for the life of the game
        if start_reader:
            self._reader = threading.Thread(target=self._read, daemon=True)
            self._reader.start()

    def close(self, force: bool = False, timeout: float = 10.0) -> None:
        """Release the game. Killing it needs force=True: the game ignores
        SIGTERM, and a kill during a run can interrupt a save write. Prefer the
        in-game Quit; force only at the main menu or in an emergency."""
        if self.proc is not None and self.proc.poll() is None:
            if not force:
                raise RuntimeError("game still running; quit it in-game or use force=True")
            self.proc.kill()
            self.proc.wait(timeout)
        self.proc = None
        if self._lock_fd is not None:
            os.close(self._lock_fd)
            self._lock_fd = None

    def _read(self) -> None:
        # Keep draining stdout whatever happens, so the game can never block on
        # a full pipe; logging failures are recorded, not fatal.
        assert self.proc is not None and self.proc.stdout is not None
        log = None
        if self.log_path:
            try:
                log = open(self.log_path, "a")
            except OSError as e:
                self.reader_error = e
        for line in self.proc.stdout:
            if log is not None:
                try:
                    log.write(line)
                except OSError as e:
                    self.reader_error, log = e, None
            msg = parse_line(line)
            if msg is None:
                continue
            with self._cv:
                if msg.kind == "obs":
                    self.latest_obs = msg
                else:
                    self.messages.append(msg)
                self._cv.notify_all()
        if log is not None:
            log.close()

    # -- observations --------------------------------------------------------
    def policy_obs(self) -> dict | None:
        """Only the on-screen part of the latest observation (hard rule 5)."""
        m = self.latest_obs
        return None if m is None else m.data.get("obs")

    # -- commands ----------------------------------------------------------
    def wait_for(self, kind: str, timeout: float = 10.0, pred=None) -> BridgeMessage:
        """Wait for a non-obs message of a kind; consumed messages are removed."""
        deadline = time.monotonic() + timeout
        with self._cv:
            while True:
                for m in list(self.messages):
                    if m.kind == kind and (pred is None or pred(m)):
                        self.messages.remove(m)
                        return m
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(f"no {kind!r} message within {timeout}s")
                self._cv.wait(remaining)

    def command(self, cmd: str, timeout: float = 10.0, **fields: Any) -> dict:
        seq = send_command(cmd, **fields)
        reply = "pong" if cmd == "ping" else "ack"
        msg = self.wait_for(reply, timeout, lambda m: (m.data or {}).get("seq") == seq)
        if "error" in msg.data:
            raise RuntimeError(msg.data["error"])
        return msg.data

    def set_speed(self, fraction: float, timeout: float = 10.0) -> float:
        return self.command("speed", timeout, value=float(fraction))["value"]
