# 005: Gymnasium combat environment and a heuristic baseline policy
Status: DONE
Owner: Codex

## Goal
A Gymnasium environment in which one episode is one combat room of the real game, plus a scripted baseline policy, both fully testable offline, so that the lead can run them live and later train RL on the same interface.

## Context (read first)
- `AGENTS.md` (hard rules 5 visible-only, 6 speed, 7 single instance), `collab/STATUS.md` (calibration facts), `docs/plan.md`, `docs/game_state_reference.md` (what each observation field means).
- Bridge: `agent/bridge/game.py`. `GameBridge.launch()` starts the one game instance and a reader thread; `policy_obs()` returns only the on-screen observation; `latest_obs.data["info"]` holds hidden values that may be used for reward only; `latest_obs.frame` increases by 1 per 0.05 s of game time; `GameBridge.command("speed", value=...)` sets game speed. Message format: see `mod/AgentBridge.lua` (`Sections.*`) and `tests/test_bridge_mod.py`. A real recorded log of a quiet room: `runtime/logs/calib1.jsonl` (each line `{"t","k","f","d"}`).
- Input: `agent/input` (`Controller`, `Action(movement, aim, buttons)`), already live-verified.
- Aim calibration: world angles equal screen angles (0 = right, counter-clockwise, world y grows downwards). To aim at a target, place the cursor at the window centre plus radius 0.25 x window height in direction theta = atan2(-(ty-hy), tx-hx); window-normalised aim (u, v) = (0.5 + r cos(theta)/W, 0.5 - r sin(theta)/H).

## Scope
May create/edit: `agent/env/**`, `agent/policy/**`, `tests/test_env*.py`, `tests/test_policy*.py`, `scripts/run_baseline.py`, append to `collab/LOG.md`. Must not edit `agent/bridge/**`, `agent/input/**`, `mod/**`, `AGENTS.md`, `collab/STATUS.md`. **Do not launch the game, do not post real input events.** Use fakes for the bridge and the controller.

## Requirements
1. `HadesCombatEnv(gymnasium.Env)` taking injected `bridge` and `controller` objects (duck-typed: the bridge needs `policy_obs()`, `latest_obs`, `command()`; the controller needs `apply(Action)` and `release_all()`).
   - Decision step: apply the action, then wait until a new observation at least `frames_per_step` (default 2, i.e. 0.1 s game time) bridge frames later; time out cleanly if the game stalls.
   - Observation: fixed-size float vector built only from `policy_obs()`: hero (hp/maxHp, cast ammo, last stands, call pips), up to K=8 nearest enemies sorted by distance (dx, dy scaled, distance, hpFrac/armorFrac/shields, boss, elite, present flag), up to 4 nearest traps (dx, dy, disabled, present), up to 8 breakables optional, combat flag. Document scaling constants. Also expose the raw dict in `info`.
   - Action space: `MultiDiscrete([9, 5, 8])`: movement (none + 8 directions), button (none, attack, special, cast, dash), aim sector (8 directions around the hero, using the calibration above).
   - Reward (hidden info allowed here): + damage dealt (decrease of `info.enemyHealth` summed, normalised), - damage taken (hero `info.heroHealth` decrease / maxHp, weighted), + kill bonus, + room-clear bonus, - death penalty, small time penalty. Constants in one config dataclass.
   - Episode: `reset()` waits until a combat room is active (`obs.room.combat` true) or times out; `terminated` when combat ends (cleared) or the hero is dead; `truncated` on a step limit. `close()` releases all inputs.
   - Never pass hidden `info` fields into the observation vector (add a test that perturbs `info` and checks the observation is unchanged).
2. `agent/policy/heuristic.py`: a scripted baseline: target the nearest enemy, keep a preferred distance band, attack when in range and roughly facing, dash away when an enemy is very close and the hero recently lost HP, cast when ammo is available and a target is in a range band. Output in the env's action format.
3. `scripts/run_baseline.py`: wires `GameBridge` + real `Controller` + env + heuristic for the lead to run live (don't run it): episodes, per-episode return, rooms cleared, deaths, appended to `runtime/runs/<timestamp>/episodes.jsonl` with git SHA, config and seed.
4. Readable code; comments explain why.

## Acceptance criteria
- `/opt/miniconda3/bin/conda run -n hades python -m pytest -q tests` passes (existing 42 tests plus yours).
- Tests cover: observation vector shape and padding, hidden-info isolation, reward signs, termination on clear and on death, step timing with a fake bridge whose frames advance, action decoding (incl. aim geometry), heuristic policy decisions on synthetic scenes, and `gymnasium.utils.env_checker.check_env` on a fake-backed env if practical.
- No real events posted, game not launched.

## Report

- `agent/env/` implements the injected Gymnasium environment, the 117-element observation encoder and the eight-sector action decoder. The environment pairs `policy_obs()` with a stable bridge frame and starts its decision interval after the controller applies the action. It releases held inputs on episode end, timeout and `close()`.
- `agent/policy/heuristic.py` targets the nearest enemy, keeps sword distance, turns to attack, casts in range and dashes after a visible HP drop. Repeated buttons get a release decision so the existing controller emits a fresh press.
- `scripts/run_baseline.py` checks the active training slot and backs up the save folder before launching via `GameBridge`. The operator enters combat and handles between-room choices. Logs record return, outcome, cumulative clears/deaths, config, Gymnasium seed and Git metadata. `git log --oneline -10` found no commits, so runs from this checkout will record a null SHA and a dirty flag until an initial commit exists.
- `/opt/miniconda3/bin/conda run -n hades python -m pytest -q tests` passed all 83 tests. The three added test files contributed 29 cases, including Gymnasium `check_env`, fake-clock timing, hidden-info perturbation, reward and terminal states, launcher guards and an episode using the real controller with `FakeBackend`. `python -m scripts.run_baseline --help` printed the CLI help inside the `hades` environment. Read-only checks of recorded JSONL encoded 6,449 `calib1` and 3,327 `combat1` observations, with valid heuristic actions on all 2,612 active `combat1` frames.
- Position offsets use 1,000 world units per normalised unit and are clipped. Counts use `n / (1 + n)` so the feature range is bounded. Breakables use eight padded slots. The raw bridge policy view is copied into `info['raw_obs']`. The vector and heuristic skip HUD numbers when the HUD is explicitly hidden. Exact bridge health is confined to reward calculation. Enemy removals in the same room approximate kills, so a despawn can award the same bonus.
- Live verification remains with the lead. The distance thresholds are initial sword defaults. The environment treats a same-room transition of `room.combat` to false as a clear, so timed room scripts that clear the flag temporarily may need extra handling. The heuristic can get stuck on obstacles. No other disagreements with the brief. No live game launch, real input, save changes or commits were made for this handoff.
