"""Click a point in the Hades window (normalised u, v), then screenshot it.

Usage: python -m scripts.menu_click U V [U V ...] [--key NAME] [--wait S]
Used for menu navigation while the bridge cannot yet read menus.
"""
import argparse
import subprocess
import time

from agent.input import Action, Controller
from agent.input.quartz import QuartzBackend, focus_game

p = argparse.ArgumentParser()
p.add_argument("points", nargs="*", type=float)
p.add_argument("--key", action="append", default=[])
p.add_argument("--wait", type=float, default=0.6)
p.add_argument("--shot", default="runtime/shot.png")
a = p.parse_args()

wid, _ = focus_game()
time.sleep(0.3)
with Controller(QuartzBackend(wid)) as c:
    pts = list(zip(a.points[::2], a.points[1::2]))
    for u, v in pts:
        c.apply(Action(aim=(u, v)))
        time.sleep(0.15)
        c.tap("attack", hold_s=0.08)
        time.sleep(a.wait)
    for k in a.key:
        c.tap(k)
        time.sleep(a.wait)
subprocess.run(["screencapture", "-x", "-o", "-l", str(wid), a.shot], check=True)
subprocess.run(["sips", "-Z", "900", a.shot, "--out", a.shot.replace(".png", "_small.png")],
               check=True, capture_output=True)
print("done")
