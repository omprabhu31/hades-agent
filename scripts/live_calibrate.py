"""Live calibration in a quiet room (needs the game in a run, Hades frontmost).

Measures and writes to runtime/calib/<time>.json:
1. movement: world displacement for each of the 8 movement directions;
2. aim: hero facing (GetAngle, degrees) after an attack aimed at a cursor
   placed at screen angle theta around the window centre;
3. speed: hero displacement and bridge frame rate per wall-clock second at
   game speeds 1 and 3.
Run scripts/run_game.py with --obs-every 1 first.
"""
import json
import math
import time
from pathlib import Path

from agent.bridge import send_command
from agent.input import Action, Controller
from agent.input.controller import DIRECTIONS
from agent.input.quartz import QuartzBackend, focus_game

LOGS = Path("runtime/logs")
LOG = LOGS / (LOGS.joinpath("CURRENT").read_text().strip() + ".jsonl")


def tail(n_bytes=400_000):
    with open(LOG, "rb") as f:
        f.seek(0, 2)
        f.seek(max(0, f.tell() - n_bytes))
        lines = f.read().decode(errors="replace").splitlines()[1:]
    return [json.loads(x) for x in lines if x.strip()]


def last_obs():
    for m in reversed(tail()):
        if m["k"] == "obs" and m["d"]["obs"].get("hero"):
            return m
    raise RuntimeError("no in-run observation")


def hero():
    h = last_obs()["d"]["obs"]["hero"]
    return h["x"], h["y"], h.get("angle")


def wait_reply(seq, kind="ack", timeout=5.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        for m in reversed(tail(50_000)):
            if m["k"] == kind and (m["d"] or {}).get("seq") == seq:
                return m["d"]
        time.sleep(0.1)
    raise TimeoutError(f"no {kind} for {seq}")


def set_speed(v):
    return wait_reply(send_command("speed", value=float(v)))


def main():
    out = {"time": time.strftime("%Y-%m-%dT%H:%M:%S"), "log": str(LOG)}
    wid, bounds = focus_game()
    time.sleep(0.4)
    with Controller(QuartzBackend(wid)) as c:
        set_speed(1.0)
        # 1. movement directions, out and back so the hero stays near the start
        moves = {}
        for d in [k for k in DIRECTIONS if k]:
            x0, y0, _ = hero()
            c.apply(Action(movement=d))
            time.sleep(0.5)
            c.apply(Action())
            time.sleep(0.3)
            x1, y1, _ = hero()
            moves[d] = [round(x1 - x0, 1), round(y1 - y0, 1)]
            print("move", d, moves[d], flush=True)
            back = {"up": "down", "down": "up", "left": "right", "right": "left"}
            opposite = "_".join(back[p] for p in d.split("_"))
            c.apply(Action(movement=opposite))
            time.sleep(0.5)
            c.apply(Action())
            time.sleep(0.3)
        out["movement"] = moves

        # 2. aim: cursor at screen angle theta (0 = right, counter-clockwise)
        aims = []
        radius_px = 0.25 * bounds.height
        for theta in range(0, 360, 45):
            px = radius_px * math.cos(math.radians(theta))
            py = -radius_px * math.sin(math.radians(theta))
            u = 0.5 + px / bounds.width
            v = 0.5 + py / bounds.height
            c.apply(Action(aim=(u, v)))
            time.sleep(0.15)
            c.tap("attack", hold_s=0.06)
            time.sleep(0.6)
            hx, hy, ang = hero()
            aims.append({"screen_deg": theta, "u": round(u, 4), "v": round(v, 4),
                         "hero_angle": ang, "hero": [hx, hy]})
            print("aim", aims[-1], flush=True)
        out["aim"] = aims

        # 3. speed: displacement and bridge frame rate per wall-clock second
        speeds = []
        for s in (1.0, 3.0):
            set_speed(s)
            time.sleep(0.3)
            for d in ("right", "left"):
                m0 = last_obs()
                x0 = m0["d"]["obs"]["hero"]["x"]
                c.apply(Action(movement=d))
                time.sleep(0.6)
                c.apply(Action())
                time.sleep(0.4)
                m1 = last_obs()
                wall = m1["t"] - m0["t"]
                speeds.append({"speed": s, "dir": d,
                               "dx": round(m1["d"]["obs"]["hero"]["x"] - x0, 1),
                               "frames_per_wall_s": round((m1["f"] - m0["f"]) / wall, 1) if wall > 0 else None})
                print("speed", speeds[-1], flush=True)
        set_speed(1.0)
        out["speed"] = speeds
    path = Path("runtime/calib")
    path.mkdir(parents=True, exist_ok=True)
    f = path / (time.strftime("%Y%m%d-%H%M%S") + ".json")
    f.write_text(json.dumps(out, indent=1))
    print("wrote", f)


if __name__ == "__main__":
    main()
