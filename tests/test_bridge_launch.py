"""Launcher safety checks with the game process mocked out."""
import subprocess

import pytest

from agent.bridge import game


class FakeProc:
    def __init__(self):
        self.killed = False
        self.stdout = iter(())
        self.pid = 1

    def poll(self):
        return 1 if self.killed else None

    def kill(self):
        self.killed = True

    def wait(self, timeout=None):
        return 0


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(game, "LOCK_PATH", tmp_path / "launch.lock")
    monkeypatch.setattr(game, "CMD_PATH", tmp_path / "cmd.lua")
    spawned = []
    monkeypatch.setattr(game.subprocess, "Popen", lambda *a, **k: spawned.append(FakeProc()) or spawned[-1])
    return spawned


def test_refuses_when_game_running(env, monkeypatch):
    monkeypatch.setattr(game, "running_game_pids", lambda: [123])
    with pytest.raises(RuntimeError, match="already running"):
        game.GameBridge().launch(start_reader=False)
    assert env == []


def test_second_launcher_blocked_by_lock(env, monkeypatch):
    monkeypatch.setattr(game, "running_game_pids", lambda: [])
    first = game.GameBridge()
    first.launch(start_reader=False)
    with pytest.raises(RuntimeError, match="lock"):
        game.GameBridge().launch(start_reader=False)
    assert len(env) == 1
    first.close(force=True)


def test_close_requires_force(env, monkeypatch):
    monkeypatch.setattr(game, "running_game_pids", lambda: [])
    b = game.GameBridge()
    b.launch(start_reader=False)
    with pytest.raises(RuntimeError, match="force"):
        b.close()
    assert not env[0].killed
    b.close(force=True)
    assert env[0].killed


def test_pgrep_failure_fails_closed(monkeypatch):
    monkeypatch.setattr(game.subprocess, "run",
                        lambda *a, **k: subprocess.CompletedProcess(a, 2, "", "err"))
    with pytest.raises(RuntimeError, match="pgrep"):
        game.running_game_pids()


def test_send_command_is_atomic_and_unique(tmp_path, monkeypatch):
    monkeypatch.setattr(game, "CMD_PATH", tmp_path / "cmd.lua")
    s1 = game.send_command("ping")
    text = (tmp_path / "cmd.lua").read_text()
    assert text.startswith("return {") and f"seq = {s1}" in text
    assert not list(tmp_path.glob(".cmd-*"))
    with pytest.raises(ValueError):
        game.send_command("speed", value=float("nan"))
