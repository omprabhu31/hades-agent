"""Compare policies across runs at the room level (the evidence of improvement).

Groups runs by name suffix (after the timestamp), applies each run's
notes.json (invalid runs dropped, exclude_episodes removed), and reports per
group: combat rooms (opening room excluded: it has 1-3 weak enemies), clear
rate, damage taken/dealt and kills per room, and the depth of each death.
Writes runs/cycles.json for the report. Small samples: treat differences of a
few rooms as noise until there are dozens of rooms per group.
Usage: python -m scripts.compare_cycles [GROUP ...]
"""
import json
import sys
from collections import defaultdict

from agent.runs import RUNS


def load_groups():
    groups = defaultdict(list)
    for d in sorted(RUNS.glob("*-*")):
        if not (d / "episodes.jsonl").exists():
            continue
        notes = json.loads((d / "notes.json").read_text()) if (d / "notes.json").exists() else {}
        if notes.get("valid") is False:
            continue
        excluded = set(notes.get("exclude_episodes", []))
        name = d.name.split("-", 1)[1]
        group = name.rstrip("0123456789").rstrip("-") if name.startswith("baseline-heuristic-eval") else name
        meta = json.loads((d / "meta.json").read_text())
        for line in (d / "episodes.jsonl").read_text().splitlines():
            e = json.loads(line)
            if e["episode"] not in excluded:
                groups[group].append({**e, "_speed": meta.get("args", {}).get("speed")})
    return groups


def summarise(eps):
    core = [e for e in eps if e["room"] != "RoomOpening"]
    if not core:
        return None
    mean = lambda k: round(sum(e[k] or 0 for e in core) / len(core), 2)
    return {"episodes": len(eps), "combat_rooms": len(core),
            "clear_rate": round(sum(e["outcome"] == "cleared" for e in core) / len(core), 3),
            "damage_taken_per_room": mean("damage_taken"), "damage_dealt_per_room": mean("damage_dealt"),
            "kills_per_room": mean("kills"), "death_depths": [e["depth"] for e in eps if e["outcome"] == "dead"],
            "speeds": sorted({e["_speed"] for e in eps if e["_speed"] is not None})}


def main():
    groups = load_groups()
    wanted = sys.argv[1:] or sorted(groups)
    out = {g: summarise(groups[g]) for g in wanted if g in groups}
    out = {g: s for g, s in out.items() if s}
    (RUNS / "cycles.json").write_text(json.dumps(out, indent=1))
    head = f"{'group':30s} {'speed':6s} {'rooms':>5s} {'clear':>6s} {'taken':>6s} {'dealt':>6s} {'kills':>6s}  deaths at depth"
    print(head)
    for g, s in out.items():
        print(f"{g:30s} {','.join(map(str, s['speeds'])):6s} {s['combat_rooms']:5d} {s['clear_rate']:6.2f} "
              f"{s['damage_taken_per_room']:6.1f} {s['damage_dealt_per_room']:6.0f} {s['kills_per_room']:6.1f}  {s['death_depths']}")


if __name__ == "__main__":
    main()
