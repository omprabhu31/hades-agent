"""Live smoke test of the whole loop in the first chambers (needs Hades frontmost).

1. take the lit door; 2. fight with a crude scripted loop (aim at nearest
enemy, attack in range, dash away when hit at close range); 3. collect the
reward and pick a boon. Prints what the bridge sees at each stage and saves
screenshots of menus. Not a policy: just a check that every piece works live.
"""
import math
import subprocess
import time

from agent.bridge import LogTailBridge
from agent.input import Action, Controller
from agent.input.quartz import QuartzBackend, focus_game
from agent.macro.driver import Macro


def shot(name):
    subprocess.run(["/opt/miniconda3/envs/hades/bin/python", "-m", "scripts.shot", f"runtime/{name}.png"],
                   capture_output=True)


def aim_at(bounds, hx, hy, tx, ty, r_frac=0.25):
    theta = math.atan2(-(ty - hy), tx - hx)
    r = r_frac * bounds.height
    return (0.5 + r * math.cos(theta) / bounds.width, 0.5 - r * math.sin(theta) / bounds.height)


def fight(bridge, c, bounds, limit_s=90):
    t0 = time.monotonic()
    last_hp = None
    while time.monotonic() - t0 < limit_s:
        o = bridge.policy_obs()
        if not o or not o.get("inRun"):
            time.sleep(0.05)
            continue
        room, hero = o.get("room") or {}, o.get("hero") or {}
        if hero.get("dead"):
            print("hero died", flush=True)
            return "dead"
        enemies = o.get("enemies") or []
        if not room.get("combat") and not enemies:
            return "cleared"
        if not enemies:
            c.apply(Action())
            time.sleep(0.05)
            continue
        hx, hy = hero["x"], hero["y"]
        e = min(enemies, key=lambda e: math.hypot(e["x"] - hx, e["y"] - hy))
        d = math.hypot(e["x"] - hx, e["y"] - hy)
        aim = aim_at(bounds, hx, hy, e["x"], e["y"])
        hit = last_hp is not None and hero["hp"] < last_hp
        last_hp = hero["hp"]
        if hit and d < 180:
            away = math.atan2(hy - e["y"], hx - e["x"])
            from agent.macro.rules import world_dir_to_movement
            c.apply(Action(movement=world_dir_to_movement(math.cos(away), math.sin(away)), aim=aim,
                           buttons=frozenset({"dash"})))
        elif d < 220:
            c.apply(Action(aim=aim, buttons=frozenset({"attack"})))
        else:
            from agent.macro.rules import world_dir_to_movement
            c.apply(Action(movement=world_dir_to_movement(e["x"] - hx, e["y"] - hy), aim=aim))
        time.sleep(0.05)
    return "timeout"


def main():
    bridge = LogTailBridge()
    wid, bounds = focus_game()
    time.sleep(0.4)
    with Controller(QuartzBackend(wid)) as c:
        m = Macro(bridge, c, bounds)
        o = m.obs()
        print("start room", o.get("room"), "doors", o.get("doors"), flush=True)
        door = m.take_door()
        print("took door", door, flush=True)
        start = o["room"]["name"]
        t0 = time.monotonic()
        while time.monotonic() - t0 < 20:
            o = bridge.policy_obs() or {}
            if (o.get("room") or {}).get("name") not in (None, start) and o.get("hud"):
                break
            time.sleep(0.2)
        print("now in", o.get("room"), "enemies", len(o.get("enemies") or []), flush=True)
        time.sleep(1.0)
        o = bridge.policy_obs()
        print("enemies sample", (o.get("enemies") or [])[:3], flush=True)
        result = fight(bridge, c, bounds)
        c.apply(Action())
        print("fight result", result, "hp", (bridge.policy_obs() or {}).get("hero", {}).get("hp"), flush=True)
        if result != "cleared":
            return
        time.sleep(1.5)
        o = bridge.policy_obs()
        print("pickups", o.get("pickups"), flush=True)
        m.collect_pickups()
        time.sleep(1.0)
        o = bridge.policy_obs()
        print("screens", o.get("screens"), "boonMenu", o.get("boonMenu"), flush=True)
        if o.get("boonMenu"):
            shot("boonmenu")
            print("picked", m.pick_boon(), flush=True)
            time.sleep(1.5)
            o = bridge.policy_obs()
            print("after pick: screens", o.get("screens"), "traits", o["hero"].get("traits"), flush=True)
        shot("after_room")


if __name__ == "__main__":
    main()
