"""Build runs/report.html: every run side by side, with per-episode clips.

Open the file in a browser (videos are referenced by relative path, so the
page must stay in runs/). Regenerate after each run:
    python -m scripts.make_report
"""
import html
import json

from agent.runs import RUNS

SUMMARY_COLS = [("episodes", "Episodes"), ("cleared", "Cleared"), ("deaths", "Deaths"),
                ("clear_rate", "Clear rate"), ("mean_return", "Mean return"),
                ("mean_damage_dealt", "Dmg dealt"), ("mean_damage_taken", "Dmg taken"),
                ("mean_kills", "Kills"), ("mean_game_seconds", "Game s")]
EP_COLS = ["episode", "room", "depth", "outcome", "return", "damage_dealt", "damage_taken",
           "kills", "game_seconds", "hp_end", "max_hp"]

CSS = """
:root { --bg:#fbfaf7; --fg:#1f1d1a; --muted:#6b665e; --line:#e4e0d8; --card:#fff; --ok:#1d7a46; --bad:#b3261e; }
@media (prefers-color-scheme: dark) { :root { --bg:#16140f; --fg:#ece8e0; --muted:#a39d92; --line:#2e2a23; --card:#1e1b16; --ok:#5cc98a; --bad:#f08a80; } }
body { background:var(--bg); color:var(--fg); font:15px/1.5 system-ui, sans-serif; margin:0; padding:24px 16px; }
main { max-width:1100px; margin:0 auto; }
h1 { font-size:22px; margin:0 0 4px; } h2 { font-size:17px; margin:32px 0 8px; }
p.muted, .muted { color:var(--muted); font-size:13px; }
table { border-collapse:collapse; width:100%; font-variant-numeric:tabular-nums; font-size:13px; }
th, td { text-align:left; padding:6px 8px; border-bottom:1px solid var(--line); white-space:nowrap; }
.wrap { overflow-x:auto; }
.cleared { color:var(--ok); font-weight:600; } .dead { color:var(--bad); font-weight:600; }
.clips { display:grid; grid-template-columns:repeat(auto-fill, minmax(300px, 1fr)); gap:12px; margin-top:12px; }
.clip { background:var(--card); border:1px solid var(--line); border-radius:8px; padding:8px; }
.clip video { width:100%; border-radius:4px; background:#000; }
details { margin-top:8px; } pre { font-size:12px; overflow-x:auto; }
"""


def fmt(v):
    if isinstance(v, float):
        return f"{v:.3g}" if abs(v) < 1000 else f"{v:.0f}"
    return "" if v is None else str(v)


def main():
    runs = []
    for d in sorted(RUNS.glob("*")):
        if not (d / "meta.json").exists():
            continue
        meta = json.loads((d / "meta.json").read_text())
        summary = json.loads((d / "summary.json").read_text()) if (d / "summary.json").exists() else {}
        eps = [json.loads(x) for x in (d / "episodes.jsonl").read_text().splitlines() if x.strip()] \
            if (d / "episodes.jsonl").exists() else []
        notes = json.loads((d / "notes.json").read_text()) if (d / "notes.json").exists() else {}
        meta["_notes"] = notes
        runs.append((d, meta, summary, eps))

    out = ["<!doctype html><html><head><meta charset='utf-8'>",
           "<meta name='viewport' content='width=device-width, initial-scale=1'>",
           "<title>Hades agent runs</title><style>", CSS, "</style></head><body><main>",
           "<h1>Hades agent runs</h1>",
           "<p class='muted'>Every run in runs/, oldest first. Metrics come from the bridge's reward-only data; "
           "clips are screen recordings of each combat episode.</p>",
           ]
    cycles_path = RUNS / "cycles.json"
    if cycles_path.exists():
        cycles = json.loads(cycles_path.read_text())
        out.append("<h2>Policies compared (combat rooms, opening room excluded)</h2>"
                   "<p class='muted'>From scripts/compare_cycles.py; invalid runs and excluded episodes removed. "
                   "Small samples: differences of a few rooms are noise.</p><div class='wrap'><table><tr>"
                   "<th>Group</th><th>Speed</th><th>Rooms</th><th>Clear rate</th><th>Dmg taken/room</th>"
                   "<th>Dmg dealt/room</th><th>Kills/room</th><th>Deaths at depth</th></tr>")
        for g, c in cycles.items():
            out.append(f"<tr><td>{html.escape(g)}</td><td>{html.escape(','.join(map(str, c['speeds'])))}</td>"
                       f"<td>{c['combat_rooms']}</td><td>{fmt(c['clear_rate'])}</td><td>{fmt(c['damage_taken_per_room'])}</td>"
                       f"<td>{fmt(c['damage_dealt_per_room'])}</td><td>{fmt(c['kills_per_room'])}</td>"
                       f"<td>{html.escape(str(c['death_depths']))}</td></tr>")
        out.append("</table></div>")
    out += ["<h2>All runs</h2><div class='wrap'><table><tr><th>Run</th><th>Policy</th><th>Speed</th>"]
    out += [f"<th>{h}</th>" for _, h in SUMMARY_COLS] + ["</tr>"]
    for d, meta, summary, _ in runs:
        args = meta.get("args", {})
        flag = " (invalid)" if meta.get("_notes", {}).get("valid") is False else ""
        out.append(f"<tr><td><a href='#{html.escape(d.name)}'>{html.escape(d.name)}</a>{flag}</td>"
                   f"<td>{html.escape(str(args.get('policy', '?')))}</td><td>{fmt(args.get('speed'))}</td>")
        out += [f"<td>{fmt(summary.get(k))}</td>" for k, _ in SUMMARY_COLS] + ["</tr>"]
    out.append("</table></div>")

    for d, meta, summary, eps in runs:
        out.append(f"<h2 id='{html.escape(d.name)}'>{html.escape(d.name)}</h2>")
        git = meta.get("git", {})
        if meta.get("_notes"):
            out.append(f"<p><strong>Note:</strong> {html.escape(str(meta['_notes'].get('reason', '')))}</p>")
        out.append(f"<p class='muted'>started {html.escape(meta.get('started', ''))} · git {git.get('sha') or 'no commit'}"
                   f"{' (dirty)' if git.get('dirty') else ''} · seed {meta.get('seed')} · "
                   f"mod {str(meta.get('mod_sha256'))[:12]}</p>")
        out.append("<div class='wrap'><table><tr>" + "".join(f"<th>{c}</th>" for c in EP_COLS) + "</tr>")
        for e in eps:
            cls = e.get("outcome") if e.get("outcome") in ("cleared", "dead") else ""
            cells = []
            for c in EP_COLS:
                v = html.escape(fmt(e.get(c)))
                cells.append(f"<td class='{cls}'>{v}</td>" if c == "outcome" else f"<td>{v}</td>")
            out.append("<tr>" + "".join(cells) + "</tr>")
        out.append("</table></div><div class='clips'>")
        for e in eps:
            if e.get("clip"):
                src = html.escape(f"{d.name}/{e['clip']}")
                out.append(f"<div class='clip'><video controls preload='metadata' src='{src}'></video>"
                           f"<div class='muted'>ep {e.get('episode')} · {html.escape(str(e.get('room')))} · "
                           f"{html.escape(str(e.get('outcome')))}</div></div>")
        out.append("</div><details><summary class='muted'>Parameters</summary><pre>"
                   + html.escape(json.dumps({k: meta.get(k) for k in ("command", "args", "configs", "hardware", "game_build")}, indent=1))
                   + "</pre></details>")
    out.append("</main></body></html>")
    (RUNS / "report.html").write_text("\n".join(out))
    print(RUNS / "report.html")


if __name__ == "__main__":
    main()
