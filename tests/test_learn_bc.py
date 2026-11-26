import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

from agent.env.actions import ATTACK
from agent.env.observations import BASE_SIZE, OBSERVATION_SIZE, encode_observation
from agent.learn.bc import BCConfig, train_bc
from agent.learn.dataset import Demonstrations, build_dataset, split_dataset
from agent.learn.network import ActorCritic, load_checkpoint, seed_training
from agent.policy import HeuristicPolicy, UnstickPolicy
from agent import runs
from scripts import train_bc as bc_script


def test_cloning_reaches_high_held_out_accuracy():
    seed_training(2)
    labels = np.tile(np.arange(9), 12)
    features = np.zeros((len(labels), OBSERVATION_SIZE), dtype=np.float32)
    features[np.arange(len(labels)), labels] = 1
    targets = np.column_stack([labels, labels % 5, labels % 8])
    rooms = np.repeat(np.arange(12), 9)
    data = Demonstrations(features, targets, rooms, [], [])
    train, validation = split_dataset(rooms, 0.25, 8)
    replay_train, replay_validation = split_dataset(rooms, 0.25, 8)
    np.testing.assert_array_equal(train, replay_train)
    np.testing.assert_array_equal(validation, replay_validation)
    assert not set(rooms[train]).intersection(rooms[validation])

    records = []
    metrics = train_bc(ActorCritic(), data, train, validation,
                       BCConfig(epochs=15, batch_size=24, learning_rate=0.008),
                       seed=2, on_record=records.append)
    assert set(metrics["accuracy"]) == {"movement", "button", "aim"}
    assert min(metrics["accuracy"].values()) >= 0.99
    assert metrics["validation_loss"] < next(row["validation_loss"] for row in records if row["kind"] == "validation")


def write_log(path, hidden):
    rows = []
    for frame in range(9):
        visible = {
            "hero": {"x": 0, "y": 0, "hp": 25, "maxHp": 50},
            "room": {"name": "fake", "depth": 1, "combat": frame != 4},
            "enemies": [{"x": 120, "y": 0, "hpFrac": 0.25}],
            "screen": "Pause" if frame == 2 else "InGameUI",
        }
        rows.append({"f": frame, "k": "obs", "d": {"obs": visible, "info": hidden}})
    path.write_text("\n".join(map(json.dumps, rows)) + "\n", encoding="utf-8")
    return rows


def test_dataset_only_uses_visible_fields_and_resets_at_room_boundaries(tmp_path):
    clean, polluted = tmp_path / "clean.jsonl", tmp_path / "polluted.jsonl"
    rows = write_log(clean, {})
    write_log(polluted, {"hero": {"x": 999, "hp": 0, "dead": True}, "room": {"combat": False},
                         "enemies": [{"x": -500, "y": 0}], "heroHealth": 5000})
    dataset = build_dataset([clean], frames_per_step=2)
    altered = build_dataset([polluted], frames_per_step=2)
    np.testing.assert_array_equal(dataset.observations, altered.observations)
    np.testing.assert_array_equal(dataset.actions, altered.actions)
    np.testing.assert_array_equal(dataset.episode_ids, [0, 0, 1, 1])
    assert [episode["first_frame"] for episode in dataset.episodes] == [0, 5]
    assert dataset.actions[0, 1] == dataset.actions[2, 1] == ATTACK
    expected_obs = [encode_observation(rows[index]["d"]["obs"]) for index in (0, 3, 5, 7)]
    # The base frame matches the stateless encoder; history columns follow.
    np.testing.assert_array_equal(dataset.observations[:, :BASE_SIZE], expected_obs)


def test_dataset_from_captured_agent3_log():
    path = Path(__file__).resolve().parents[1] / "runtime" / "logs" / "agent3.jsonl"
    if not path.is_file():
        pytest.skip("The locally recorded agent3 bridge log is unavailable")
    dataset = build_dataset([path], max_samples=20)
    assert dataset.observations.shape == (20, OBSERVATION_SIZE)
    assert dataset.observations.dtype == np.float32
    assert dataset.actions.shape == (20, 3)
    assert dataset.episodes[0]["room"] == "RoomSimple01"
    source = dataset.sources[0]
    with path.open("rb") as handle:
        prefix = handle.read(source["bytes_read"])
    assert hashlib.sha256(prefix).hexdigest() == source["sha256_prefix"]
    first_frame = dataset.episodes[0]["first_frame"]
    for line in prefix.splitlines():
        entry = json.loads(line)
        if entry.get("k") == "obs" and entry.get("f") == first_frame:
            raw_obs = entry["d"]["obs"]
            break
    np.testing.assert_array_equal(dataset.observations[0, :BASE_SIZE], encode_observation(raw_obs))
    np.testing.assert_array_equal(dataset.actions[0], UnstickPolicy(HeuristicPolicy()).act(raw_obs))


def test_bc_cli_records_configuration_and_metrics(tmp_path, monkeypatch):
    path = tmp_path / "bridge.jsonl"
    write_log(path, {})
    monkeypatch.setattr(runs, "RUNS", tmp_path / "runs")
    assert bc_script.main([str(path), "--epochs", "2", "--device", "cpu"]) == 0
    run, = (tmp_path / "runs").iterdir()
    meta = json.loads((run / "meta.json").read_text())
    assert meta["args"]["recording"] == "offline"
    assert meta["args"]["dataset"]["split"] == "room"
    assert meta["configs"]["bc"]["epochs"] == 2
    assert meta["bridge_log"] == str(path)
    assert (run / "code.tar.gz").is_file()
    assert (run / "summary.json").is_file()
    assert not (run / "clips").exists()
    records = [json.loads(line) for line in (run / "train.jsonl").read_text().splitlines()]
    assert [record["kind"] for record in records] == ["update", "validation", "update", "validation"]
    _, checkpoint = load_checkpoint(run / "checkpoints" / "bc.pt")
    # The saved weights are the best held-out epoch; the last epoch is kept for reference.
    assert checkpoint["validation"]["final"] == records[-1]
    best = min((r for r in records if r["kind"] == "validation"), key=lambda r: r["validation_loss"])
    assert checkpoint["validation"]["best_epoch"] == best["epoch"]
