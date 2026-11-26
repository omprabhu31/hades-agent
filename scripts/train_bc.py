"""Train an offline combat policy by labelling saved bridge observations."""

import argparse
import json
from dataclasses import asdict
from pathlib import Path
from uuid import uuid4

import numpy as np

from agent.learn.bc import BCConfig, train_bc
from agent.learn.dataset import build_dataset, split_dataset
from agent.learn.network import ActorCritic, resolve_device, save_checkpoint, seed_training
from agent.learn.records import validate_run_name
from agent.policy import HeuristicConfig, UnstickConfig
from agent.runs import RunRecorder


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("logs", type=Path, nargs="+", help="bridge JSONL files from heuristic play")
    parser.add_argument("--epochs", type=int, default=15)
    parser.add_argument("--batch-size", type=int, default=128)
    parser.add_argument("--learning-rate", type=float, default=0.001)
    parser.add_argument("--validation-fraction", type=float, default=0.2)
    parser.add_argument("--frames-per-step", type=int, default=2)
    parser.add_argument("--max-samples", type=int, help="cap the number of labelled examples")
    parser.add_argument("--device", choices=("auto", "cpu", "mps"), default="auto")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--name", default="bc")
    args = parser.parse_args(argv)
    try:
        validate_run_name(args.name)
        if not 0 <= args.seed < 2**32:
            raise ValueError("Seed must be a 32-bit unsigned integer")
        config = BCConfig(args.epochs, args.batch_size, args.learning_rate, args.validation_fraction)
        device = resolve_device(args.device)
        data = build_dataset(args.logs, frames_per_step=args.frames_per_step, max_samples=args.max_samples)
        train, validation = split_dataset(data.episode_ids, config.validation_fraction, args.seed)
    except (OSError, ValueError) as error:
        parser.error(str(error))

    seed_training(args.seed)
    policy = ActorCritic().to(device)
    dataset = {
        "sources": data.sources,
        "episodes": data.episodes,
        "frames_per_step": args.frames_per_step,
        "train_samples": len(train),
        "validation_samples": len(validation),
        "validation_episodes": np.unique(data.episode_ids[validation]).tolist(),
        "split": "room" if len(data.episodes) > 1 else "final_time_block",
    }
    configs = {"policy": asdict(policy.config), "bc": asdict(config),
               "teacher": asdict(HeuristicConfig()), "unstick": asdict(UnstickConfig())}
    meta = {**vars(args), "logs": [str(path.resolve()) for path in args.logs], "device": str(device),
            "dataset": dataset, "recording": "offline"}
    bridge_log = data.sources[0]["path"] if len(data.sources) == 1 else None
    try:
        recorder = RunRecorder(args.name, meta, configs, args.seed, bridge_log, clips=False)
    except FileExistsError:
        # RunRecorder uses second-resolution timestamps. Concurrent offline
        # cycles with the same name still need separate output directories.
        recorder = RunRecorder(f"{args.name}-{uuid4().hex[:8]}", meta, configs, args.seed, bridge_log, clips=False)

    print("run dir", recorder.dir, flush=True)
    try:
        with (recorder.dir / "train.jsonl").open("w", encoding="utf-8", buffering=1) as handle:
            def record(row: dict) -> None:
                handle.write(json.dumps(row) + "\n")
                if row["kind"] == "validation":
                    print(json.dumps(row), flush=True)

            result = train_bc(policy, data, train, validation, config, seed=args.seed, on_record=record)
        checkpoint = recorder.dir / "checkpoints" / "bc.pt"
        save_checkpoint(checkpoint, policy, {"kind": "bc", "seed": args.seed, "bc": asdict(config),
                                             "validation": result})
        recorder.write_summary()
    finally:
        recorder.close()
    print("checkpoint", checkpoint, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
