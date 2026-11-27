import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from agent import runs
from agent.env.observations import OBSERVATION_SIZE
from agent.learn import live
from agent.learn.network import ActorCritic, load_checkpoint, save_checkpoint
from scripts import eval_policy, run_agent, train_ppo


class FakeClip:
    def __init__(self, path):
        self.path = path

    def start(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def stop(self):
        self.path.write_bytes(b"fake recording")


@pytest.fixture
def macro_fakes(monkeypatch, tmp_path):
    events = []
    raw_obs = {"hero": {"hp": 40, "maxHp": 50}, "room": {"name": "RoomFake", "depth": 2, "combat": True}}

    class Bridge:
        path = tmp_path / "bridge.jsonl"
        latest_obs = SimpleNamespace(frame=0, data={"info": {"heroHealth": 40}})

        def policy_obs(self):
            return raw_obs

        def command(self, command, **fields):
            events.append((command, fields["value"]))

    class Controller:
        def __init__(self, _backend):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            pass

        def apply(self, action):
            assert action.movement is None and not action.buttons

        def ensure_safe(self):
            pass

    class Env:
        def __init__(self, bridge, _controller, *, window_size, config):
            self.bridge = bridge
            self.obs = np.zeros(OBSERVATION_SIZE, dtype=np.float32)

        def reset(self, *, seed):
            self.steps = 0
            self.closed = False
            return self.obs, {"raw_obs": raw_obs}

        def step(self, action):
            assert not self.closed
            assert action.shape == (3,)
            self.steps += 1
            self.bridge.latest_obs.frame += 2
            done = self.steps == 3
            return self.obs, 1.0, done, False, {"raw_obs": raw_obs, "outcome": "cleared" if done else None}

        def close(self):
            self.closed = True

    monkeypatch.setattr(runs, "RUNS", tmp_path / "runs")
    monkeypatch.setattr(runs, "ClipRecorder", FakeClip)
    monkeypatch.setattr(live, "running_game_pids", lambda: [42])
    monkeypatch.setattr(live, "require_training_slot", lambda slot: events.append(("slot", slot)))
    monkeypatch.setattr(live, "shutil", SimpleNamespace(copytree=lambda _src, dst: events.append(("backup", dst))))
    monkeypatch.setattr(run_agent, "LogTailBridge", Bridge)
    monkeypatch.setattr(run_agent, "running_game_pids", lambda: [42])
    monkeypatch.setattr(run_agent, "focus_game", lambda: (42, SimpleNamespace(width=1920, height=1080)))
    monkeypatch.setattr(run_agent, "QuartzBackend", lambda _wid: None)
    monkeypatch.setattr(run_agent, "Controller", Controller)
    monkeypatch.setattr(run_agent, "HadesCombatEnv", Env)
    monkeypatch.setattr(run_agent, "Macro", lambda *_args: None)
    monkeypatch.setattr(run_agent, "subprocess", SimpleNamespace(run=lambda *_args, **_kwargs: None))
    checkpoint = tmp_path / "bc.pt"
    save_checkpoint(checkpoint, ActorCritic(), {"kind": "bc"})
    return checkpoint, events


def read_rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_eval_runs_and_records_exact_episode_budget_with_fake_macro(tmp_path, macro_fakes):
    checkpoint, events = macro_fakes
    assert eval_policy.main([str(checkpoint), "--episodes", "2", "--device", "cpu"]) == 0
    run, = (tmp_path / "runs").iterdir()
    meta = json.loads((run / "meta.json").read_text())
    assert meta["args"]["checkpoint"] == str(checkpoint)
    assert meta["args"]["speed"] == 1.0
    assert meta["args"]["slot"] == 2
    assert events[0] == events[2] == ("slot", 2)
    assert events[1][0] == "backup"
    records = read_rows(run / "episodes.jsonl")
    assert [record["episode"] for record in records] == [1, 2]
    assert all(record["return"] == 3 and record["game_seconds"] == 0.3 for record in records)
    assert all((run / record["clip"]).is_file() for record in records)


def test_ppo_cli_updates_records_and_checkpoints_through_fake_macro(tmp_path, macro_fakes):
    checkpoint, events = macro_fakes
    assert train_ppo.main([str(checkpoint), "--episodes", "2", "--device", "cpu", "--speed", "3",
                           "--checkpoint-every", "2", "--epochs", "1"]) == 0
    run, = (tmp_path / "runs").iterdir()
    meta = json.loads((run / "meta.json").read_text())
    assert meta["args"]["checkpoint"] == str(checkpoint)
    assert meta["configs"]["combat"]["game_speed"] == 3.0
    assert meta["configs"]["ppo"]["epochs"] == 1
    assert events[-1] == ("speed", 1.0)
    records = read_rows(run / "episodes.jsonl")
    training = read_rows(run / "train.jsonl")
    assert [row["update"] for row in training] == [1, 2]
    assert [row["episode"] for row in training] == [row["episode"] for row in records]
    assert all((run / row["clip"]).is_file() for row in records)
    saved = run / "checkpoints"
    assert {path.name for path in saved.iterdir()} == {"update_000002.pt", "final.pt"}
    _, metadata = load_checkpoint(saved / "final.pt")
    assert metadata["update"] == 2
    assert metadata["warm_start"]["checkpoint"] == str(checkpoint)


def test_live_ppo_stops_if_the_episode_clip_is_missing(tmp_path, macro_fakes, monkeypatch):
    checkpoint, events = macro_fakes
    monkeypatch.setattr(FakeClip, "stop", lambda _self: None)
    with pytest.raises(RuntimeError, match="no recorded clip"):
        train_ppo.main([str(checkpoint), "--episodes", "1", "--device", "cpu", "--speed", "3"])
    run, = (tmp_path / "runs").iterdir()
    assert (run / "episodes.jsonl").is_file()
    assert not (run / "train.jsonl").exists()
    assert events[-1] == ("speed", 1.0)
