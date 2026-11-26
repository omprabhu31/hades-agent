# 003: Review the bridge mod and Python bridge
Status: DONE
Owner: Codex (reviewer); author: Claude

## Goal
An independent, severity-ranked review of the game bridge before more features are built on it.

## Context
- Read `AGENTS.md` (hard rules 4, 5, 7 matter most) and `collab/STATUS.md`.
- Files under review: `mod/AgentBridge.lua` (runs inside the game, Lua 5.2, no `io`/`os`; `print` goes to stdout; `loadfile` works on absolute paths), `mod/install.sh`, `mod/uninstall.sh`, `agent/bridge/game.py`, `scripts/run_game.py`, `tests/test_bridge_mod.py`, and the lead's edits to `agent/input/quartz.py` (`_find_game_window(on_screen_only=...)` and the `osascript` fallback in `focus_game`, needed because the window was on another Space and macOS ignored activation from a background process).
- Verified live on 2026-11-26: hello/obs/event messages arrive (~19 Hz at Interval 0.05), speed command is acked, hero moves under synthetic input. Sample log: `runtime/logs/live1.jsonl`.
- Game function signatures can be checked in `~/Library/Application Support/Steam/steamapps/common/Hades/Game.macOS.app/Contents/Resources/Content/Scripts/*.lua` (read-only).

## Scope
Read-only review. You may create `collab/reviews/003-bridge-review.md` and append to `collab/LOG.md`. Do not edit code, do not launch the game, do not send input, do not touch the game folder, do not commit.

## What to check
1. Can the mod ever change game state or break the game (errors escaping pcall, hooks altering arguments/returns, coroutine/thread misuse, performance cost of loadfile + JSON every 0.05 s)?
2. Does anything hidden leak into `obs` (hard rule 5)? E.g. is an enemy health fraction always visible on screen? Are "Breakable" pots and other non-enemies correctly classed?
3. Command channel: atomicity, replay after game restart, sandboxing of `runtime/cmd.lua` (is `debug.setupvalue(chunk, 1, {})` correct for Lua 5.2 `_ENV`?).
4. Python side: stdout pipe handling (what happens to the game if the reader dies — SIGPIPE?), single-instance enforcement, log growth.
5. Test gaps.

## Acceptance criteria
- `collab/reviews/003-bridge-review.md` lists findings ranked by severity (critical / major / minor / nit), each with file:line, the concrete failure scenario, and a suggested fix.
- `/opt/miniconda3/bin/conda run -n hades python -m pytest -q tests` result reported.

## Report
Codex completed the independent review in [003-bridge-review.md](/Users/om-prabhu/projects/hades-agent/collab/reviews/003-bridge-review.md). Verdict is request changes. The two critical findings are hidden observations during loading and a race in the single-instance guard. The remaining findings cover stdout failure, unsafe hard shutdown, install reversibility, command isolation and session handling, logging, focus and hooks.

`/opt/miniconda3/bin/conda run -n hades python -m pytest -q tests` passed all 27 tests with repository caches disabled. Both shell scripts passed `bash -n`. Additional checks used a pre-existing capture, temporary files, a dummy child, Lua 5.2 stubs and Python mocks. Native Hades loader and signal behaviour, game function signatures, UI rendering and map timing, live Quartz behaviour and frame-time overhead remain unverified.
