"""Screenshot the Hades window (works while it is behind other windows)."""
import subprocess
import sys

import Quartz as q

out = sys.argv[1] if len(sys.argv) > 1 else "runtime/shot.png"
ws = [w for w in q.CGWindowListCopyWindowInfo(q.kCGWindowListOptionAll, q.kCGNullWindowID)
      if w.get("kCGWindowOwnerName") == "Hades" and w.get("kCGWindowLayer") == 0
      and w["kCGWindowBounds"]["Width"] > 200]
if not ws:
    sys.exit("no Hades window")
# Several same-sized windows can exist; the titled, on-screen one is the game.
w = max(ws, key=lambda w: (w.get("kCGWindowName") == "Hades", bool(w.get("kCGWindowIsOnscreen")),
                           w["kCGWindowBounds"]["Width"] * w["kCGWindowBounds"]["Height"]))
subprocess.run(["screencapture", "-x", "-o", "-l", str(w["kCGWindowNumber"]), out], check=True)
subprocess.run(["sips", "-Z", "900", out, "--out", out.replace(".png", "_small.png")],
               check=True, capture_output=True)
print(w["kCGWindowNumber"], dict(w["kCGWindowBounds"]))
