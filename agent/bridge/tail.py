"""Read the bridge stream from scripts/run_game.py's JSONL log.

This lets tools attach to the one running game (launched by run_game.py)
instead of launching it themselves. It offers the same read/command methods
as GameBridge that consumers use: policy_obs(), latest_obs, command().
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from .game import ROOT, BridgeMessage, send_command

LOGS = ROOT / "runtime" / "logs"


class LogTailBridge:
    def __init__(self, path: Path | None = None) -> None:
        if path is None:
            path = LOGS / ((LOGS / "CURRENT").read_text().strip() + ".jsonl")
        self.path = Path(path)
        self._f = open(self.path, "rb")
        self._f.seek(0, os.SEEK_END)
        # Start from the most recent observation already in the file.
        self._f.seek(max(0, self._f.tell() - 200_000))
        self._f.readline()
        self._buf = b""
        self._latest: BridgeMessage | None = None
        self.messages: list[BridgeMessage] = []
        self.poll()

    def poll(self) -> None:
        """Read whatever has been appended since the last call."""
        chunk = self._f.read()
        if not chunk:
            return
        self._buf += chunk
        *lines, self._buf = self._buf.split(b"\n")
        for raw in lines:
            if not raw.strip():
                continue
            try:
                m = json.loads(raw)
            except json.JSONDecodeError:
                continue
            msg = BridgeMessage(m.get("k", "?"), m.get("f"), m.get("d"), m.get("t", 0.0))
            if msg.kind == "obs":
                self._latest = msg
            else:
                self.messages.append(msg)
                del self.messages[:-1000]

    @property
    def latest_obs(self) -> BridgeMessage | None:
        self.poll()  # always fresh, so callers can read it like GameBridge's
        return self._latest

    def policy_obs(self) -> dict | None:
        m = self.latest_obs
        return None if m is None else m.data.get("obs")

    def wait_new_obs(self, after_frame: int | None, timeout: float = 2.0) -> BridgeMessage:
        deadline = time.monotonic() + timeout
        while True:
            m = self.latest_obs
            if m is not None and (after_frame is None or (m.frame or 0) > after_frame):
                return m
            if time.monotonic() > deadline:
                raise TimeoutError("no new observation")
            time.sleep(0.01)

    def command(self, cmd: str, timeout: float = 10.0, **fields) -> dict:
        seq = send_command(cmd, **fields)
        reply = "pong" if cmd == "ping" else "ack"
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.poll()
            for m in self.messages:
                if m.kind == reply and (m.data or {}).get("seq") == seq:
                    if "error" in m.data:
                        raise RuntimeError(m.data["error"])
                    return m.data
            time.sleep(0.05)
        raise TimeoutError(f"no {reply} for {cmd}")
