"""Run the combat baseline after quitting any existing Hades instance.

From the repository root, run ``python -m scripts.run_baseline --episodes 3``.
Select the designated training slot in Hades before the session. Manually
enter combat and handle rewards and doors between episodes. Quit Hades in-game
when the script reports that the baseline has finished.
"""

import argparse
import json
import shutil
import subprocess
import sys
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import TextIO

from agent.bridge import GameBridge, running_game_pids
from agent.bridge.game import ROOT
from agent.env import CombatConfig, HadesCombatEnv
from agent.input import Bounds, Controller, GameWindowNotFound, QuartzBackend, focus_game
from agent.policy import HeuristicConfig, HeuristicPolicy

SAVE_DIR = Path.home() / "Library/Application Support/Supergiant Games/Hades"


def require_training_slot(slot: int) -> None:
    # macOS stores the default slot as an SGB1 string. Check it before launch
    # as well as before driving, in case the operator switched slots in-game.
    if slot not in (2, 3, 4):
        raise RuntimeError("Baseline requires training slot 2, 3 or 4")
    expected = b"SGB1\x08\x00\x00\x00" + f"Profile{slot}".encode("ascii")
    if (SAVE_DIR / "activeProfile").read_bytes() != expected:
        raise RuntimeError(f"Select training slot {slot} in Hades and quit it in-game before starting")


def git_metadata() -> dict:
    head = subprocess.run(["git", "rev-parse", "--verify", "HEAD"], cwd=ROOT, capture_output=True, text=True)
    dirty = subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True)
    return {"git_sha": head.stdout.strip() if head.returncode == 0 else None, "git_dirty": bool(dirty.strip())}


def wait_for_window(bridge: GameBridge) -> tuple[int, Bounds]:
    deadline = time.monotonic() + 30.0
    while bridge.proc.poll() is None:
        try:
            return focus_game()
        except GameWindowNotFound:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.1)
    raise RuntimeError("Hades exited before opening a game window")


def run_episode(bridge: GameBridge, config: CombatConfig, policy: HeuristicPolicy, slot: int, seed: int) -> dict:
    window_id, bounds = wait_for_window(bridge)
    controller = Controller(QuartzBackend(window_id))
    env = HadesCombatEnv(bridge, controller, window_size=(bounds.width, bounds.height), config=config)
    try:
        _, info = env.reset(seed=seed)
        room = info["raw_obs"]["room"]
        policy.reset()
        total_reward = 0.0
        steps = 0
        # Start the mouse override check once the operator has entered the
        # room. A new controller lets them navigate manually between rooms.
        with controller:
            while True:
                require_training_slot(slot)
                action = policy.act(info["raw_obs"])
                _, reward, terminated, truncated, info = env.step(action)
                total_reward += reward
                steps += 1
                if terminated or truncated:
                    return {
                        "room": room.get("name"), "depth": room.get("depth"), "steps": steps,
                        "return": total_reward, "outcome": info["outcome"],
                    }
    finally:
        env.close()


def run_episodes(
    bridge: GameBridge, config: CombatConfig, policy: HeuristicPolicy,
    args: argparse.Namespace, metadata: dict, episode_log: TextIO,
) -> None:
    rooms_cleared = deaths = 0
    for index in range(args.episodes):
        number = index + 1
        seed = args.seed + index
        print(f"Episode {number}/{args.episodes}. Enter combat in training slot {args.slot}.", flush=True)
        result = run_episode(bridge, config, policy, args.slot, seed)
        outcome = result["outcome"]
        rooms_cleared += outcome == "cleared"
        deaths += outcome == "dead"
        record = {
            **metadata, **result, "time": datetime.now(timezone.utc).isoformat(),
            "episode": number, "seed": seed, "rooms_cleared": rooms_cleared, "deaths": deaths,
        }
        episode_log.write(json.dumps(record) + "\n")
        episode_log.flush()
        print(f"{outcome} | return {result['return']:.3f} | {rooms_cleared} clears | {deaths} deaths", flush=True)
        if outcome not in ("cleared", "dead"):
            # A truncated chamber may still be active. Leave it to the operator.
            break


def finish(bridge: GameBridge, speed: float) -> None:
    if bridge.proc.poll() is None:
        if speed != 1.0 and bridge.latest_obs is not None:
            try:
                bridge.command("speed", timeout=2.0, value=1.0)
            except (RuntimeError, OSError) as error:
                print(f"Could not restore normal game speed before quit ({error})", file=sys.stderr)
        print("Baseline finished. Quit Hades in-game to end the session.", flush=True)
        # Keep draining stdout until the game exits. A forced quit can interrupt
        # a save write.
        bridge.proc.wait()
    bridge.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--episodes", type=int, default=1)
    parser.add_argument("--slot", type=int, choices=(2, 3, 4), default=2)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--speed", type=float, default=1.0, help="use 1.0 for milestone runs")
    parser.add_argument("--frames-per-step", type=int, default=2)
    parser.add_argument("--max-steps", type=int, default=1800)
    parser.add_argument("--reset-timeout", type=float, default=180.0, help="wall seconds to enter combat")
    args = parser.parse_args(argv)
    if args.episodes < 1 or args.seed < 0:
        parser.error("--episodes must be positive and --seed must be non-negative")
    try:
        config = CombatConfig(
            frames_per_step=args.frames_per_step, max_steps=args.max_steps,
            game_speed=args.speed, reset_timeout=args.reset_timeout,
        )
    except ValueError as error:
        parser.error(str(error))

    if running_game_pids():
        raise RuntimeError("Hades is running. Quit it in-game before starting the baseline")
    require_training_slot(args.slot)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    backup = ROOT / "backups" / f"baseline-{stamp}"
    shutil.copytree(SAVE_DIR, backup)
    run_dir = ROOT / "runtime" / "runs" / stamp
    run_dir.mkdir(parents=True)
    policy_config = HeuristicConfig()
    policy = HeuristicPolicy(policy_config)
    metadata = {
        **git_metadata(), "slot": args.slot,
        "config": {"combat": asdict(config), "policy": asdict(policy_config)},
    }
    print(f"Save backup at {backup}\nEpisode log at {run_dir / 'episodes.jsonl'}", flush=True)

    bridge = GameBridge()
    bridge.launch()  # Rechecks the single-instance rule under the bridge launch lock.
    try:
        with (run_dir / "episodes.jsonl").open("a", encoding="utf-8") as episode_log:
            run_episodes(bridge, config, policy, args, metadata, episode_log)
    finally:
        finish(bridge, args.speed)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, OSError) as error:
        raise SystemExit(str(error)) from None
    except KeyboardInterrupt:
        raise SystemExit(130) from None
