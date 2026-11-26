"""Live check: input moves the hero, and the speed command scales game time.

Holds each direction for a fixed wall-clock time at speed 1 and speed 2 and
reports the hero displacement measured by the bridge.
"""
import json
import time
from pathlib import Path

from agent.bridge import send_command
from agent.input import Action, Controller
from agent.input.quartz import QuartzBackend, focus_game

LOG = Path("runtime/logs") / (Path("runtime/logs/CURRENT").read_text().strip() + ".jsonl")


def last(kind="obs", pred=None):
    with open(LOG, "rb") as f:
        f.seek(0, 2)
        f.seek(max(0, f.tell() - 200_000))
        lines = f.read().decode(errors="replace").splitlines()[1:]
    for line in reversed(lines):
        m = json.loads(line)
        if m["k"] == kind and (pred is None or pred(m)):
            return m
    return None


def hero():
    h = last()["d"]["obs"]["hero"]
    return h["x"], h["y"]


def wait_ack(seq, timeout=5):
    t0 = time.time()
    while time.time() - t0 < timeout:
        m = last("ack", lambda m: m["d"].get("seq") == seq)
        if m:
            return m["d"]
        time.sleep(0.1)
    return None



wid, _ = focus_game()
time.sleep(0.3)
results = []
with Controller(QuartzBackend(wid)) as c:
    for speed in (1.0, 2.0):
        seq = send_command("speed", value=speed)
        print("speed ack", wait_ack(seq), flush=True)
        for d in ("right", "left"):
            x0, y0 = hero()
            c.apply(Action(movement=d))
            time.sleep(1.0)
            c.apply(Action())
            time.sleep(0.3)
            x1, y1 = hero()
            results.append((speed, d, round(x1 - x0, 1), round(y1 - y0, 1)))
            print(results[-1], flush=True)
    seq = send_command("speed", value=1.0)
    print("reset ack", wait_ack(seq), flush=True)
