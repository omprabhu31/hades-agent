"""Check baseline launch guards and episode logging without a game process."""

import json
from types import SimpleNamespace

import pytest

from scripts import run_baseline


def active_profile(slot):
    return b"SGB1\x08\x00\x00\x00" + f"Profile{slot}".encode("ascii")


@pytest.fixture
def runner_paths(monkeypatch, tmp_path):
    saves = tmp_path / "saves"
    saves.mkdir()
    monkeypatch.setattr(run_baseline, "SAVE_DIR", saves)
    monkeypatch.setattr(run_baseline, "ROOT", tmp_path)
    monkeypatch.setattr(run_baseline, "running_game_pids", lambda: [])
    return saves, tmp_path


def test_protected_slot_or_running_game_refuses_before_launch(runner_paths, monkeypatch):
    saves, root = runner_paths
    (saves / "activeProfile").write_bytes(active_profile(1))
    monkeypatch.setattr(run_baseline, "GameBridge", lambda: pytest.fail("Must not launch"))
    with pytest.raises(RuntimeError, match="Select training slot 2"):
        run_baseline.main([])
    assert not (root / "backups").exists()

    (saves / "activeProfile").write_bytes(active_profile(2))
    monkeypatch.setattr(run_baseline, "running_game_pids", lambda: [123])
    with pytest.raises(RuntimeError, match="Hades is running"):
        run_baseline.main([])
    assert not (root / "backups").exists()


def test_fake_session_backs_up_saves_and_logs_each_outcome(runner_paths, monkeypatch):
    saves, root = runner_paths
    (saves / "activeProfile").write_bytes(active_profile(2))
    (saves / "Profile1.sav").write_bytes(b"test save")
    lifecycle = []

    class FakeGame:
        latest_obs = object()

        def __init__(self):
            self.proc = SimpleNamespace(poll=lambda: None, wait=lambda: lifecycle.append("wait"))

        def launch(self):
            backup = next((root / "backups").iterdir())
            assert (backup / "Profile1.sav").read_bytes() == b"test save"
            lifecycle.append("launch")

        def command(self, cmd, **fields):
            lifecycle.append((cmd, fields["value"]))

        def close(self):
            lifecycle.append("close")

    def run_episode(bridge, config, policy, slot, seed):
        lifecycle.append(("episode", seed))
        assert config.game_speed == 3.0 and slot == 2
        outcome = {8: "cleared", 9: "dead", 10: "timeout"}[seed]
        return {"return": float(seed), "steps": 3, "room": "RoomA", "depth": 2, "outcome": outcome}

    monkeypatch.setattr(run_baseline, "GameBridge", FakeGame)
    monkeypatch.setattr(run_baseline, "run_episode", run_episode)
    monkeypatch.setattr(run_baseline, "git_metadata", lambda: {"git_sha": "abc", "git_dirty": True})
    assert run_baseline.main(["--episodes", "4", "--speed", "3", "--seed", "8"]) == 0
    assert lifecycle == ["launch", ("episode", 8), ("episode", 9), ("episode", 10), ("speed", 1.0), "wait", "close"]
    log_path = next((root / "runtime" / "runs").glob("*/episodes.jsonl"))
    logs = [json.loads(line) for line in log_path.read_text().splitlines()]
    assert [row["return"] for row in logs] == [8.0, 9.0, 10.0]
    assert [row["rooms_cleared"] for row in logs] == [1, 1, 1]
    assert [row["deaths"] for row in logs] == [0, 1, 1]
    assert [row["seed"] for row in logs] == [8, 9, 10]
    assert all(row["config"]["combat"]["game_speed"] == 3.0 and row["git_sha"] == "abc" for row in logs)
    assert (saves / "Profile1.sav").read_bytes() == b"test save"
