"""Launch the single Hades instance and log bridge messages until it exits.

Usage: python -m scripts.run_game [--session NAME] [--obs-every N]
Writes runtime/logs/<session>.jsonl (bridge messages with wall-clock receive
time; every event/ack, and every Nth observation to bound disk use) and
runtime/logs/<session>.stdout.log (the game's own log lines, no bridge lines).
Other processes tail the JSONL and send commands with agent.bridge.send_command.
"""
import argparse
import json
import re
import time

from agent.bridge import GameBridge, parse_line
from agent.bridge.game import ROOT

p = argparse.ArgumentParser()
p.add_argument("--session", default=time.strftime("session-%Y%m%d-%H%M%S"))
p.add_argument("--obs-every", type=int, default=4, help="log every Nth observation (20 Hz / N)")
a = p.parse_args()
if not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", a.session):
    raise SystemExit("bad session name")

logs = ROOT / "runtime" / "logs"
logs.mkdir(parents=True, exist_ok=True)
b = GameBridge()
b.launch(start_reader=False)  # raises before any log changes if a game is running
cur_tmp = logs / ".CURRENT.tmp"
cur_tmp.write_text(a.session)
cur_tmp.replace(logs / "CURRENT")
jsonl = open(logs / f"{a.session}.jsonl", "a", buffering=1)
raw = open(logs / f"{a.session}.stdout.log", "a", buffering=1)
print(f"pid {b.proc.pid} session {a.session}", flush=True)

n_obs = 0
for line in b.proc.stdout:  # always drain, even if logging fails
    try:
        m = parse_line(line)
        if m is None:
            raw.write(line)
            continue
        if m.kind == "obs":
            n_obs += 1
            if n_obs % a.obs_every:
                continue
        jsonl.write(json.dumps({"t": round(m.t, 3), "k": m.kind, "f": m.frame, "d": m.data}) + "\n")
    except OSError:
        pass
print("game exited", b.proc.wait(), flush=True)
b.close()
