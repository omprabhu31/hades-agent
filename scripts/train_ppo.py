"""Warm-start PPO from a combat checkpoint and train between recorded rooms."""

import argparse
import json
from dataclasses import asdict

from agent.learn.live import add_live_arguments, run_live, validate_live_arguments
from agent.learn.network import load_checkpoint, resolve_device, save_checkpoint, seed_training
from agent.learn.ppo import PPOConfig, PPOTrainer
from agent.learn.records import checkpoint_reference, require_episode_clip


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    add_live_arguments(parser, name="ppo")
    parser.add_argument("--rollout-steps", type=int, default=256, help="maximum GAE segment length")
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--epochs", type=int, default=4, help="passes over each room's transitions")
    parser.add_argument("--learning-rate", type=float, default=0.0003)
    parser.add_argument("--checkpoint-every", type=int, default=5, help="save after this many PPO updates")
    args = parser.parse_args(argv)
    try:
        validate_live_arguments(args)
        if args.checkpoint_every < 1:
            raise ValueError("Checkpoint interval must be positive")
        config = PPOConfig(learning_rate=args.learning_rate, rollout_steps=args.rollout_steps,
                           batch_size=args.batch_size, epochs=args.epochs)
        device = resolve_device(args.device)
        reference = checkpoint_reference(args.checkpoint)
        seed_training(args.seed)
        policy, _ = load_checkpoint(args.checkpoint, device)
    except (OSError, ValueError) as error:
        parser.error(str(error))

    trainer = PPOTrainer(policy, config, seed=args.seed)
    pending = None
    last_completed = None

    def collect_episode(env, observation, _info, after_step):
        nonlocal pending
        pending, info = trainer.collect_episode(env, observation, after_step)
        return info, sum(pending.rewards), len(pending.rewards)

    def update_after_recording(record, recorder):
        nonlocal pending, last_completed
        if pending is None:
            return  # A failed reset can be recorded without an action to learn from.
        require_episode_clip(record, recorder)
        # The macro runner has released inputs and stopped the room clip.
        metrics = trainer.update(pending)
        pending = None
        update = {"kind": "update", "episode": record["episode"], **metrics}
        with (recorder.dir / "train.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(update) + "\n")
        print("ppo update", json.dumps(update), flush=True)
        metadata = {"kind": "ppo", "seed": args.seed, "ppo": asdict(config),
                    "warm_start": reference, **metrics}
        directory = recorder.dir / "checkpoints"
        last_completed = directory, metadata
        if metrics["update"] % args.checkpoint_every == 0:
            save_checkpoint(directory / f"update_{metrics['update']:06d}.pt", policy, metadata)

    status = run_live(
        args, episode_fn=collect_episode, on_episode_end=update_after_recording, policy_name="actor-critic-ppo",
        extra_meta={**reference, "device": str(device), "checkpoint_every": args.checkpoint_every,
                    "dataset": {"source": "online", "unit": "combat room", "on_policy": True}},
        extra_configs={"policy": asdict(policy.config), "ppo": asdict(config)},
    )
    if last_completed is not None:
        directory, metadata = last_completed
        final = directory / "final.pt"
        save_checkpoint(final, policy, metadata)
        print("checkpoint", final, flush=True)
    return status


if __name__ == "__main__":
    raise SystemExit(main())
