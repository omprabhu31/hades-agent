# 001: Keyboard and mouse input driver for Hades (macOS)
Status: DONE
Owner: Codex

## Goal
A Python module that lets the agent press the game's controls the way a human does with keyboard and mouse, reliably, with no stuck keys, sending events to the Hades window on macOS.

## Context
- Read `AGENTS.md` first. The project trains an agent to play Hades (macOS build, x86_64 under Rosetta) using only inputs a human could make.
- Conda env `hades` (Python 3.11) already exists with `pyobjc-framework-Quartz`, `pyobjc-framework-ApplicationServices`, `numpy`, `pytest`. Run things with `/opt/miniconda3/bin/conda run -n hades ...`. Don't install anything else without saying why in your report; if you must, pin the version in `environment.yml`.
- The terminal already has macOS Accessibility and Screen Recording permission.
- Hades keyboard/mouse controls (defaults, make them configurable in one data structure or a small TOML/JSON file): move W/A/S/D; Attack = left mouse; Special = right mouse; Cast = Q; Dash (Rush) = Space; Interact (Use) = E; Call (Shout) = F; Reload = R; Gift = G; Codex = C; Boon info/advanced tooltip = B; menus also use Esc and Enter. With the mouse enabled, attacks aim towards the cursor, so aiming = moving the cursor relative to the hero.
- The game window is named after the process `Game.macOS` / title `Hades`; it is a normal window, roughly 1512x982 points, position varies.
- The lead (Claude) is driving the running game during this task. **Do not launch the game, and do not post real input events** (no running code that calls `CGEventPost` against the live system). Everything must be testable with a fake backend.

## Scope
May create/edit: `agent/__init__.py`, `agent/input/**`, `tests/test_input*.py`, `scripts/input_smoke.py`, `collab/LOG.md` (append only).
Must not touch: `AGENTS.md`, `collab/STATUS.md`, `mod/**`, `environment.yml` (unless a dependency is unavoidable), anything outside the repo.

## Requirements
1. `find_game_window()` -> window id, bounds (points) via `CGWindowListCopyWindowInfo`; `focus_game()` brings it to front (e.g. via `NSRunningApplication` / AppKit if available in the installed pyobjc, else `osascript`). Handle "window not found" cleanly.
2. A low-level backend that posts key down/up (macOS virtual key codes) and mouse move/button down/up via Quartz `CGEvent`s, plus a fake backend that records events for tests.
3. A stateful `Controller` with `apply(action)` where an action describes: movement direction (none or one of 8 directions), aim target in window-normalised coordinates (0..1, 0..1) or none, and a set of held buttons (attack, special, cast, dash, interact, call, reload). It only sends changes since the previous action (key-down on press, key-up on release), and moves the cursor only when the aim changes. Also `tap(button, hold_s=...)` for menus, and `release_all()`.
4. Safety: `Controller` is a context manager that always calls `release_all()` on exit, exceptions and SIGINT. It stops (releases all and raises a clear exception) if a file `runtime/STOP` exists, or if the cursor is found somewhere it did not put it by more than a threshold (the human grabbed the mouse). Cursor is clamped inside the game window.
5. Keep it simple and readable; comments explain *why*. No global state beyond the controller.
6. `scripts/input_smoke.py`: a manual script the lead will run against the live game later. It focuses the window, walks in a small square, dashes once, moves the aim around the hero, then releases everything. Don't run it.

## Acceptance criteria
- `/opt/miniconda3/bin/conda run -n hades python -m pytest -q tests` passes, with tests covering: diffing (no repeated key-downs), release on exception, STOP file, aim clamping, 8-direction movement mapping, the human-override check.
- `/opt/miniconda3/bin/conda run -n hades python -c "import agent.input"` works.
- No real events are posted during tests (the fake backend is injected; the real backend is never constructed in tests).

## Report

- Added `agent/__init__.py` and `agent/input/` with Quartz window discovery and focus, a configurable controller, and a fake backend. The controller releases held inputs on exceptions, SIGINT, a `runtime/STOP` file, mouse override, or loss of game focus. A safety stop requires a new controller.
- Added `tests/test_input_controller.py` and the manual `scripts/input_smoke.py`. The smoke script uses the centre of the game window as an approximation of the hero's screen position.
- `/opt/miniconda3/bin/conda run -n hades python -m pytest -q tests` passed all 21 tests using the fake backend. `/opt/miniconda3/bin/conda run -n hades python -c "import agent.input"` succeeded. `python -m py_compile` in the same environment succeeded for the driver, tests and smoke script.
- Verified every default virtual key code against Apple's installed HIToolbox `Events.h`. Confirmed Quartz and AppKit imports in the existing environment. `git log --oneline -10` reported that `main` has no commits yet.
- Live focus, Quartz event delivery and Hades' response remain unverified. The lead can run `/opt/miniconda3/bin/conda run --no-capture-output -n hades python -m scripts.input_smoke` when ready. The game was not launched, the real backend was never constructed, and no live input events were posted during this task.
- No disagreement with the brief. No dependencies added and no commit made.
