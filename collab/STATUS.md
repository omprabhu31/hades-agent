# Status

Phase 3 started: learning pipeline (BC + PPO) runs live; no measurable improvement over the heuristic yet. Session ended 2026-11-26 ~16:00 with Hades quit cleanly, no agents or scripts running, nothing committed. Updated 2026-11-26 14:05 by Claude (lead). Repo renamed to `hades-agent` 2026-11-26 (user request).

## Decisions
- Perception through a read-only Lua mod (user approved 2026-11-26), limited to on-screen information.
- Mod loading: copy `mod/AgentBridge*.lua` into the game's Scripts folder and append one `Import` line to `RoomManager.lua` (`mod/install.sh`, reversed by `mod/uninstall.sh`, original in `backups/game-originals/`).
- Lua -> Python: the game's Lua has no `io`/`os`, but `print` reaches the process's stdout when the game binary is launched directly (not via Steam). Lines are prefixed so they can be filtered.
- Python -> Lua: `loadfile` works on absolute paths outside the game, so the mod polls `runtime/cmd.lua` (verified: spike returned "hello from python 42").
- Engine C functions available to Lua are listed in `docs/engine_cfuncs.txt` (416), including `AdjustSimulationSpeed`, `GetLocation`, `GetVelocity`, `GetTopScreenName`, `GetIds*`, `ProjectileExists`.
- Rosetta 2 was missing and has been installed (user approved, 2026-11-26). Steam Cloud stays on (user choice).
- Input: synthetic keyboard + mouse via Quartz CGEvent (Accessibility granted). Verified live 2026-11-26: menu clicks work; WASD moves the hero. `focus_game()` needs the `osascript` System Events fallback because macOS ignores activation requests from background processes.
- Only one Hades instance at a time (user hard rule). The game ignores SIGTERM/SIGINT; `GameBridge.launch` refuses if one is running.
- Game audio muted via Options > Settings > Master Volume = 0 (user request; stored in `Profile1.sjson` as `MasterVolume`).
- Training save: slot 2 (Profile2), created 2026-11-26, Hell Mode off. The first run started in `RoomOpening`.
- The game keeps simulating when not frontmost (obs keep arriving at ~20 Hz).
- Background input via `CGEventPostToPid` is unreliable: occasional key-downs moved the hero while Finder was frontmost, most did nothing. Treat training as needing Hades frontmost (Mac taken over). Possible later options: virtual gamepad, separate macOS user session.
- Bridge v2 (from `docs/game_state_reference.md`) live-verified 2026-11-26: hero HUD fields, room (name/biome/depth/combat), lit door rewards; enemies, traps, boon menu not yet seen live.
- Calibration `runtime/calib/20261126-140046.json` (git-ignored; numbers copied here): cursor at screen angle theta around the window centre gives hero facing theta minus 2-7 degrees (8 angles), so world angles match screen angles: aim at a target with theta = atan2(-(ty-hy), tx-hx), world y grows downwards. Speed 3.0 gives 46.5 bridge frames per wall second vs 19.6-20.0 at 1.0, i.e. about 2.3x real speed-up (frames are per 0.05 s of game time).
- Possible leak to check: door `reroll` (CanBeRerolled) was true on a brand-new save with no Fated Persuasion; the sparkle may not be drawn. Drop or gate it before training.

- 2026-11-26 save corruption root cause: the mod's global `AgentBridge` table (contains functions) was serialised by `Save()` (Main.lua:1020-1035) and luabins failed, so every slot-2 save was a ~160-byte stub and the game showed "Corrupted Save Data". Fixed with `SaveIgnores["AgentBridge"] = true` (+ test). Corrupt slot-2 files moved to `backups/corrupt-profile2-*`; slot 2 restarted. Profile1 was never loaded with the mod; its files match the backup.
- Clean shutdown: `python -m scripts.quit_game` (Esc > Quit > OK > main-menu Quit). Never hard-kill during play.
- Dialogue advances with a left click on the text box; boon cards are clicked at their UI coordinates mapped with `agent.macro.ui_to_window` (verified live).
- House: bridge `house` section (map + exits). Route: DeathArea -> courtyard (RoomPreRun) -> NewRunDoor. Hero `dead` stays true in the House.
- Runs: every run gets `runs/<stamp>-<name>/` (meta.json with command/configs/seed/git/hardware/game build/mod hash, code.tar.gz, episodes.jsonl, summary.json, clips/ep_NNNN.mp4). Compare with `python -m scripts.compare_runs` (user instruction 2026-11-26: record clips of each iteration; save every training run with its results and parameters).
- First agent results (heuristic, speed 1.0, Stygian Blade): cleared RoomSimple01 (10 kills, 25 HP lost), A_Combat04, A_Combat24 (after adding the unstick wrapper), A_Combat15; died at depth 6. See runs/.

## Results so far (combat rooms, opening room excluded; `python -m scripts.compare_cycles`)
| group | speed | rooms | clear rate | dmg taken/room | kills/room | deaths at depth |
|---|---|---|---|---|---|---|
| baseline-heuristic-eval | 1.0 | 10 | 0.60 | 21.3 | 3.9 | [3, 3, 3, 4] |
| ppo-cycle1 | 3.0 | 7 | 0.71 | 22.1 | 6.3 | [4, 4] |
| eval-ppo-cycle1 | 1.0 | 7 | 0.71 | 14.3 | 5.6 | [5, 4] |
| ppo-cycle2 | 3.0 | 6 | 0.50 | 21.3 | 3.7 | [3, 3, 3] |
| eval-ppo-cycle2 | 1.0 | 7 | 0.57 | 21.0 | 8.3 | [2, 5, 3] |

Reading: samples are 6-10 rooms per group, so these differences are within noise. PPO cycle 1 looked better than baseline at evaluation, cycle 2 did not; treat both as "no reliable change". BC accuracy was low (see docs/plan.md 3a).

## Task board
| # | Task | Owner | Status |
|---|------|-------|--------|
| 001 | Input driver (`agent/input`) | Codex | DONE (live-verified; lead patched focus) |
| 003 | Bridge mod + Python reader (`mod/AgentBridge.lua`, `agent/bridge`, `scripts/run_game.py`) | Claude | DONE v1, in review by Codex |
| 004 | Bridge v2 from 002 (HUD, enemy bars, traps, doors, screens, speed upkeep) | Claude | DONE (live partly verified) |
| 002 | (Grok) state reference | Grok | DONE |
| 005 | Gymnasium env + heuristic combat baseline (`agent/env`, `agent/policy`) | Codex | DONE (lead-reviewed; lead added UnstickPolicy, screen gating) |
| 006 | Macro layer + `scripts/run_agent.py` (combat, boons, dialogue, pickups, doors, House) + run recorder | Claude | DONE (live-verified) |
| 007 | Review of bridge v2 + macro | Grok | DONE (fixes applied) |
| 008 | Learning pipeline (BC + PPO + eval) | Codex | DONE (lead-reviewed; 2 PPO cycles run live) |
| 009 | Observation history (`HistoryEncoder`, 183 floats) + more BC data + best-epoch BC | Claude | DONE offline (results in docs/plan.md 3a); live eval pending |
| 010 | Larger evaluations (>=30 combat rooms per policy) before claiming improvement | open | NEXT |
| 011 | Mirror of Night: bridge `obs.house.mirror`/`obs.mirror` + `agent/macro/mirror.py` (`spend_darkness`), called once per bedroom visit in run_agent | Codex (impl), Claude (review, integration) | DONE offline; live check pending |
| 012 | Stage B skills (NPC talk/gifting, Fated List, weapons, Contractor, fishing, Codex, ...) | open | LATER |
| -- | Projectile perception (no API; consider OnWeaponFired tracking or vision) | open | LATER |

## Blockers
- None.

## How to resume (keep this current)
1. Read `AGENTS.md`, this file, `docs/plan.md` (esp. "Status and next steps"), the last entries of `collab/LOG.md`, `runs/report.html`.
2. The mod is uninstalled between sessions (game is stock); run `mod/install.sh` first. `pgrep -x Game.macOS` must be empty. `pkill -x "Problem Reporter"` if a crash report is open. Install the mod (`mod/install.sh`), then launch in the background: `/opt/miniconda3/bin/conda run --no-capture-output -n hades python -m scripts.run_game --session <name> --obs-every 1`.
3. Ask the user (interactive question tool) before any input session unless they have granted a time window. Load the training save: `python -m scripts.menu_click 0.089 0.481` (Play) then `python -m scripts.menu_click 0.437 0.45` (slot 2, one click when it has a save). Screenshots: `python -m scripts.shot`.
4. Play: `python -m scripts.run_agent --runs N --rooms 80 --max-minutes M --name <run-name>` (heuristic+unstick, records to `runs/`). Learned policies: `python -m scripts.train_bc LOGS...`, `python -m scripts.train_ppo <ckpt> --episodes N --speed 3`, `python -m scripts.eval_policy <ckpt> --episodes N` (speed 1.0). Report: `python -m scripts.make_report` then open `runs/report.html`; table: `python -m scripts.compare_runs`.
5. Stop the game only with `python -m scripts.quit_game` (from play or House) or `--from-menu`.
6. Checks: see AGENTS.md "Verification".
