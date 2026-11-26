"""Tabulate all recorded runs (runs/*/summary.json) for side-by-side comparison."""
import json

from agent.runs import RUNS

COLS = ["episodes", "cleared", "deaths", "clear_rate", "mean_return", "mean_damage_dealt",
        "mean_damage_taken", "mean_kills", "mean_game_seconds"]


def main():
    rows = []
    for d in sorted(RUNS.glob("*")):
        s, m = d / "summary.json", d / "meta.json"
        if not s.exists():
            continue
        meta = json.loads(m.read_text()) if m.exists() else {}
        rows.append([d.name, meta.get("args", {}).get("policy", "?")] + [json.loads(s.read_text()).get(c) for c in COLS])
    head = ["run", "policy"] + COLS
    widths = [max(len(str(x)) for x in col) for col in zip(head, *rows)] if rows else [len(h) for h in head]
    for r in [head] + rows:
        print("  ".join(str(x).ljust(w) for x, w in zip(r, widths)))


if __name__ == "__main__":
    main()
