"""Evaluate a saved combat policy through the regular recorded macro runner."""

import argparse
from dataclasses import asdict

import torch

from agent.learn.live import add_live_arguments, run_live, validate_live_arguments
from agent.learn.network import load_checkpoint, resolve_device, seed_training
from agent.learn.records import checkpoint_reference, require_episode_clip


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    add_live_arguments(parser, name="learned-eval")
    parser.add_argument("--greedy", action="store_true", help="take each head's argmax instead of seeded sampling")
    args = parser.parse_args(argv)
    try:
        validate_live_arguments(args)
        device = resolve_device(args.device)
        reference = checkpoint_reference(args.checkpoint)
        seed_training(args.seed)
        policy, _ = load_checkpoint(args.checkpoint, device)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    generator = torch.Generator().manual_seed(args.seed)

    def evaluate_episode(env, observation, _info, after_step):
        total, steps = 0.0, 0
        try:
            while True:
                action, _, _ = policy.decide(observation, deterministic=args.greedy, generator=generator)
                observation, reward, terminated, truncated, info = env.step(action)
                after_step(info)
                total += reward
                steps += 1
                if terminated or truncated:
                    return info, total, steps
        finally:
            env.close()

    return run_live(args, episode_fn=evaluate_episode, on_episode_end=require_episode_clip, policy_name="actor-critic",
                    extra_meta={**reference, "device": str(device), "greedy": args.greedy},
                    extra_configs={"policy": asdict(policy.config)})


if __name__ == "__main__":
    raise SystemExit(main())
