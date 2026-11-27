"""Shared arguments and save protection for the learned-policy macro runs."""

import argparse
import math
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

from agent.bridge import running_game_pids
from agent.bridge.game import ROOT
from agent.env import CombatConfig
from scripts import run_agent
from scripts.run_baseline import SAVE_DIR, require_training_slot

from .records import validate_run_name


def add_live_arguments(parser: argparse.ArgumentParser, *, name: str) -> None:
    parser.add_argument("checkpoint", type=Path)
    parser.add_argument("--episodes", type=int, default=5, help="maximum number of combat episodes")
    parser.add_argument("--runs", type=int, default=3, help="maximum new escape attempts from the House")
    parser.add_argument("--speed", type=float, default=1.0, help="use 1.0 for milestone evaluation")
    parser.add_argument("--max-minutes", type=float, default=30.0, help="stop between rooms after this long")
    parser.add_argument("--slot", type=int, choices=(2, 3, 4), default=2)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--device", choices=("auto", "cpu", "mps"), default="auto")
    parser.add_argument("--name", default=name)
    parser.add_argument("--whiff-penalty", type=float, default=0.0,
                        help="reward cost per attack with no enemy damage within 0.5 s (0 = off)")


def validate_live_arguments(args: argparse.Namespace) -> None:
    validate_run_name(args.name)
    CombatConfig(game_speed=args.speed)
    if args.episodes < 1 or args.runs < 0 or not 0 <= args.seed < 2**32:
        raise ValueError("Use a positive episode budget, non-negative run budget and 32-bit unsigned seed")
    if not math.isfinite(args.max_minutes) or args.max_minutes <= 0:
        raise ValueError("Maximum minutes must be positive and finite")


def run_live(args: argparse.Namespace, *, extra_meta: dict, **options) -> int:
    if len(running_game_pids()) != 1:
        raise RuntimeError("Attach to exactly one running Hades instance started by scripts.run_game")
    require_training_slot(args.slot)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    backup = ROOT / "backups" / f"learn-{stamp}"
    shutil.copytree(SAVE_DIR, backup)
    require_training_slot(args.slot)
    return run_agent.main(
        ["--max-episodes", str(args.episodes), "--rooms", str(sys.maxsize), "--runs", str(args.runs),
         "--speed", str(args.speed), "--max-minutes", str(args.max_minutes), "--seed", str(args.seed),
         "--name", args.name, "--whiff-penalty", str(args.whiff_penalty)],
        extra_meta={"slot": args.slot, "save_backup": str(backup), **extra_meta},
        **options,
    )
