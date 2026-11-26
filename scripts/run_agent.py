"""Play rooms end to end on the already-running game: combat + macro.

Attaches to the single Hades instance started by scripts/run_game.py
(use --obs-every 1), so it never launches or kills the game. Loop:
  combat active      -> one HadesCombatEnv episode driven by the heuristic
  boon menu open     -> pick a card
  pickups in room    -> collect them
  lit exit door      -> walk through it
  hero dead          -> stop (House handling is not implemented yet)
Episodes go to runtime/runs/<stamp>/episodes.jsonl with config and git state.

Usage: python -m scripts.run_agent [--rooms N] [--speed S]
Speed other than 1.0 is for training only (AGENTS.md rule 6).
"""
import argparse
import json
import subprocess
import time
from dataclasses import asdict
from datetime import datetime, timezone

from agent.bridge import LogTailBridge, running_game_pids
from agent.env import CombatConfig, HadesCombatEnv
from agent.input import Action, Controller
from agent.input.quartz import QuartzBackend, focus_game
from agent.macro.driver import Macro
from agent.macro.house import equip_keepsake, gift_nectar
from agent.macro.mirror import spend_darkness
from agent.policy import HeuristicConfig, HeuristicPolicy, UnstickConfig, UnstickPolicy
from agent.runs import RunRecorder


HOUSE_ROUTE = {"DeathArea": "DeathAreaBedroom", "DeathAreaBedroom": "RoomPreRun", "RoomPreRun": "run"}


class EpisodeMetrics:
    """Damage dealt/taken, kills and game time from the bridge's hidden info
    (used for measurement only, never as policy input)."""

    def __init__(self, msg):
        self.f0 = msg.frame
        self.frame = msg.frame
        info = msg.data.get("info") or {}
        self.enemies = {r["id"]: (r.get("hp") or 0) + (r.get("armor") or 0) for r in info.get("enemyHealth") or []}
        self.hp = info.get("heroHealth")
        self.dealt = self.taken = 0.0
        self.kills = 0

    def update(self, msg, dead=False):
        if msg is None or msg.frame == self.frame:
            return
        self.frame = msg.frame
        info = msg.data.get("info") or {}
        now = {r["id"]: (r.get("hp") or 0) + (r.get("armor") or 0) for r in info.get("enemyHealth") or []}
        for i, h in self.enemies.items():
            if i in now:
                self.dealt += max(0.0, h - now[i])
            elif not dead:
                self.dealt += h
                self.kills += 1
        self.enemies = now
        hp = info.get("heroHealth")
        if hp is not None and self.hp is not None:
            self.taken += max(0.0, self.hp - hp)
        self.hp = hp

    def as_dict(self):
        return {"damage_dealt": round(self.dealt, 1), "damage_taken": round(self.taken, 1),
                "kills": self.kills, "game_seconds": round((self.frame - self.f0) * 0.05, 2)}


def policy_episode(policy):
    """Default combat episode: step the env with a policy acting on raw_obs.

    An episode function receives (env, obs, info, after_step) right after
    env.reset(), must call after_step(info) after every env.step(), and
    returns (final_info, total_return, steps). PPO training plugs in its own
    function here (it can collect transitions and update between episodes).
    """
    def run(env, obs, info, after_step):
        policy.reset()
        total, steps = 0.0, 0
        while True:
            obs, r, term, trunc, info = env.step(policy.act(info["raw_obs"]))
            after_step(info)
            total += r
            steps += 1
            if term or trunc:
                return info, total, steps
    return run


def main(argv=None, *, policy=None, policy_name=None, episode_fn=None,
         extra_meta=None, extra_configs=None, on_episode_end=None) -> int:
    """Macro loop. Callers (eval, PPO) may inject a policy or a whole
    episode function, extra run metadata/configs, and a per-episode callback
    on_episode_end(record, recorder). Defaults reproduce the heuristic run."""
    p = argparse.ArgumentParser()
    p.add_argument("--rooms", type=int, default=3, help="stop after this many rooms left")
    p.add_argument("--runs", type=int, default=0, help="new runs to start from the House")
    p.add_argument("--speed", type=float, default=1.0)
    p.add_argument("--max-minutes", type=float, default=10.0)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--name", default="heuristic")
    p.add_argument("--no-clips", action="store_true")
    p.add_argument("--max-episodes", type=int, default=0, help="stop after this many combat episodes (0 = no limit)")
    a = p.parse_args(argv)

    bridge = LogTailBridge()
    if bridge.policy_obs() is None:
        raise SystemExit("no observations: start scripts.run_game --obs-every 1 first")
    combat_cfg = CombatConfig(reset_timeout=5.0, game_speed=a.speed)
    policy_cfg = HeuristicConfig()
    if policy is None and episode_fn is None:
        policy = UnstickPolicy(HeuristicPolicy(policy_cfg), UnstickConfig())
        policy_name = "heuristic+unstick"
        configs = {"policy": asdict(policy_cfg), "unstick": asdict(UnstickConfig())}
    else:
        configs = {}
    if episode_fn is None:
        episode_fn = policy_episode(policy)
    configs = {"combat": asdict(combat_cfg), **configs, **(extra_configs or {})}
    rec = RunRecorder(a.name, args={**vars(a), "policy": policy_name or "custom", **(extra_meta or {})},
                      configs=configs, seed=a.seed, bridge_log=str(bridge.path), clips=not a.no_clips)
    print("run dir", rec.dir, flush=True)

    try:
        return _loop(a, bridge, rec, combat_cfg, episode_fn, on_episode_end)
    finally:
        # Always: stop any clip, and never leave the game sped up (rule 6).
        rec.close()
        if a.speed != 1.0:
            try:
                bridge.command("speed", value=1.0, timeout=5.0)
            except Exception as e:  # game may already be gone
                print("could not restore speed 1.0:", e, flush=True)


def _house_log(rec, runs_started, **fields) -> None:
    """Append one House action (gift, keepsake, Mirror) to the run record."""
    with open(rec.dir / "house.jsonl", "a") as f:
        f.write(json.dumps({"time": datetime.now(timezone.utc).isoformat(), "runs_started": runs_started,
                            **fields}, default=list) + "\n")


def _loop(a, bridge, rec, combat_cfg, episode_fn, on_episode_end) -> int:
    # A macOS "Hades quit unexpectedly" report window sits above the game and
    # swallows mouse clicks aimed at it (seen in run clips 2026-11-26).
    subprocess.run(["pkill", "-x", "Problem Reporter"], capture_output=True)
    wid, bounds = focus_game()
    time.sleep(0.3)
    rooms_left = 0
    runs_started = 0
    mirror_visit = None  # run count at the last Mirror visit: spend once per House stay
    gift_visit = rack_visit = None  # same, for the Hall gift and the courtyard keepsake rack
    known_keepsakes = None  # from the last rack survey; gifting waits for one (task 013)
    deadline = time.monotonic() + a.max_minutes * 60
    episode = 0
    with Controller(QuartzBackend(wid)) as c:
        env = HadesCombatEnv(bridge, c, window_size=(bounds.width, bounds.height), config=combat_cfg)
        macro = Macro(bridge, c, bounds)
        while time.monotonic() < deadline and rooms_left < a.rooms:
            if not running_game_pids():
                print("Hades exited; stopping", flush=True)
                break
            o = bridge.policy_obs() or {}
            room, hero = o.get("room") or {}, o.get("hero") or {}
            if room.get("house"):
                if o.get("screens"):
                    pass  # dialogue in the House: handled by the overlay branch below
                elif runs_started >= a.runs:
                    print("in the House and run budget used; stopping", flush=True)
                    break
                else:
                    house = o.get("house") or {}
                    if house.get("map") == "DeathArea" and gift_visit != runs_started:
                        gift_visit = runs_started
                        gift = gift_nectar(macro, bridge, known_keepsakes=known_keepsakes)
                        print("gift", gift, flush=True)
                        if "nectar_before" in gift:
                            known_keepsakes = None  # re-survey before another gift
                        _house_log(rec, runs_started, gift=gift)
                        continue
                    if house.get("map") == "RoomPreRun" and rack_visit != runs_started:
                        rack_visit = runs_started
                        rack = equip_keepsake(macro, bridge)
                        print("keepsake", rack, flush=True)
                        if "owned" in rack:
                            known_keepsakes = set(rack["owned"])
                        _house_log(rec, runs_started, keepsake=rack)
                        continue
                    if house.get("map") == "DeathAreaBedroom" and mirror_visit != runs_started:
                        # Permanent upgrades before each run (docs/plan.md Stage A).
                        mirror_visit = runs_started
                        purchases = spend_darkness(macro, bridge)
                        print("mirror purchases", purchases, flush=True)
                        _house_log(rec, runs_started, mirror=purchases,
                                   darkness=(o.get("house") or {}).get("darkness"))
                        continue
                    # Route out of the House (DeathLoopData.lua): Great Hall ->
                    # Zagreus's bedroom -> courtyard (RoomPreRun) -> new-run door.
                    nxt = HOUSE_ROUTE.get(house.get("map"), "DeathArea")
                    want = "run" if nxt == "run" else "room"
                    exits = [e for e in house.get("exits") or []
                             if e.get("kind") == want and (want == "run" or e.get("to") == nxt)]
                    if not exits:
                        print("House: no exit of kind", want, house, flush=True)
                        time.sleep(1.0)
                        continue
                    hx, hy = macro.hero_xy()
                    ex = min(exits, key=lambda e: (e["x"] - hx) ** 2 + (e["y"] - hy) ** 2)
                    print("House:", house.get("map"), "->", want, flush=True)
                    macro.walk_to(ex["x"], ex["y"], radius=110, timeout=20)
                    macro.interact()
                    t0 = time.monotonic()
                    while time.monotonic() - t0 < 15:
                        h2 = (bridge.policy_obs() or {}).get("house") or {}
                        if h2.get("map") != house.get("map"):
                            break
                        time.sleep(0.2)
                    if want == "run" and not ((bridge.policy_obs() or {}).get("room") or {}).get("house"):
                        runs_started += 1
                        print("new run started", runs_started, flush=True)
                    continue
            if hero.get("dead"):
                time.sleep(0.5)  # death presentation, then the House loads
                continue
            if room.get("combat"):
                episode += 1
                rec.start_episode(episode)
                try:
                    try:
                        obs, info = env.reset(seed=a.seed + episode)
                    except TimeoutError:
                        # Combat flag flickered off before a decision frame; not an episode.
                        rec.close()
                        episode -= 1
                        print("combat reset timed out; continuing", flush=True)
                        continue
                    metrics = EpisodeMetrics(bridge.latest_obs)
                    info, total, steps = episode_fn(
                        env, obs, info,
                        lambda i: metrics.update(bridge.latest_obs, dead=i.get("outcome") == "dead"))
                finally:
                    c.apply(Action())
                record = {"episode": episode, "room": room.get("name"), "depth": room.get("depth"),
                          "outcome": info["outcome"], "return": round(total, 3), "steps": steps,
                          # Measurement only: the HUD (and so obs HP) hides when combat ends.
                          "hp_end": ((bridge.latest_obs.data.get("info") or {}).get("heroHealth")
                                     if bridge.latest_obs else None),
                          "max_hp": (info["raw_obs"].get("hero") or {}).get("maxHp"),
                          **metrics.as_dict(), "time": datetime.now(timezone.utc).isoformat()}
                rec.end_episode(record)
                print("episode", record, flush=True)
                if on_episode_end is not None:
                    on_episode_end(record, rec)
                if a.max_episodes and episode >= a.max_episodes:
                    print("episode budget used; stopping", flush=True)
                    break
                if info["outcome"] not in ("cleared", "dead"):
                    print("episode truncated; stopping so the scene can be checked", flush=True)
                    break
                continue
            if o.get("boonMenu"):
                print("boon menu", o["boonMenu"], flush=True)
                time.sleep(0.8)  # the menu ignores input for its first 0.5 s
                print("picked", macro.pick_boon(), flush=True)
                # The menu takes a moment to close after a pick; only click
                # again if it is still open after that (seen as double picks).
                t0 = time.monotonic()
                while time.monotonic() - t0 < 4.0 and (bridge.policy_obs() or {}).get("boonMenu"):
                    time.sleep(0.2)
                continue
            if o.get("screens"):
                # Dialogue advances with a left click (verified live); other
                # overlays are logged so they can be handled explicitly later.
                print("screen open", o["screens"], flush=True)
                if "Dialog" in o["screens"]:
                    macro.click_ui(1150, 850)  # on the text box, away from choices
                else:
                    macro.interact()
                time.sleep(0.8)
                continue
            if o.get("pickups"):
                print("collecting", [(p["kind"], p.get("name")) for p in o["pickups"]], flush=True)
                macro.collect_pickups()
                time.sleep(0.5)
                continue
            if any(d.get("lit") for d in o.get("doors") or []):
                start = room.get("name")
                door = macro.take_door()
                print("door", door and door.get("reward"), flush=True)
                t0 = time.monotonic()
                while time.monotonic() - t0 < 15:
                    if ((bridge.policy_obs() or {}).get("room") or {}).get("name") not in (None, start):
                        rooms_left += 1
                        break
                    time.sleep(0.2)
                continue
            c.apply(Action())
            time.sleep(0.2)
        c.apply(Action())
    print("done; rooms left", rooms_left, "episodes", episode, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
