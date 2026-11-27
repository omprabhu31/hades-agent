# AGENTS.md: hades-agent (Hades player agent)

Project-specific instructions for every agent in this repo. The global defaults live in `~/projects/agent-collab-setup/global/AGENTS.md` and load automatically. This file adds to them, and wins where the two disagree.

## Project

Hobby project, public on GitHub at `github.com/omprabhu31/hades-agent` (user instruction, 2026-11-26): train an agent that plays the user's own Steam copy of Hades (macOS build, runs under Rosetta) and beats it, meaning it defeats Hades at the end of the Styx at Heat 0, without God Mode. No deadline.

## Hard rules

1. Train only in an empty save slot (Profile2-4). Never write to or delete `Profile1*` in `~/Library/Application Support/Supergiant Games/Hades/`. Back up the save folder to `backups/` before any run that touches saves.
2. The agent plays under the same conditions as a human: it may earn and use every temporary and permanent upgrade a normal player can (Mirror of Night, keepsakes, weapons, Pact, etc.), and nothing a human can't.
3. God Mode is allowed only as a labelled early milestone. The final target and any "beat the game" claim must be without God Mode, at Heat 0.
4. Game-file changes are limited to loading our read-only state mod (approved 2026-11-26). Every change must be reversible by `mod/uninstall.sh`, and the original files must be backed up to `backups/game-originals/` first. The mod must not change gameplay, damage, drops, RNG or difficulty.
5. **Visible information only.** The mod may pass the agent only what a human can see on screen: positions of the hero, enemies, projectiles and obstacles; health bars (as shown, e.g. a fraction, not hidden exact values the UI does not display); attack telegraphs that are drawn; door reward icons; menu and dialogue contents; resources shown in the HUD. Never hidden values: RNG state, unrevealed rewards, AI timers or intentions not telegraphed, enemy stats the UI does not show. Hidden values may be used only for reward computation and logging, never as policy input. When unsure, treat a value as hidden and ask the lead.
6. Game speed may be changed for training. Any evaluation that counts towards a milestone runs at normal speed (1.0).
7. **Only one Hades instance at a time** (user instruction, 2026-11-26). Before launching, check `pgrep -x Game.macOS` and stop any running copy first. The game ignores SIGTERM and SIGINT; stop it with the in-game Quit or, at the main menu, `kill -9`. Code that launches the game must enforce this.
8. Stop the game only through its menus (`scripts/quit_game.py`); a hard kill during play can corrupt the save. Any global table a mod adds must be listed in `SaveIgnores`.
9. Never commit save files, game files, game assets, clips or run logs (`backups/`, `runs/`, `runtime/` are git-ignored). The repo is public: no absolute home paths, secrets or personal details in committed files; quote game scripts only as short cited excerpts.

## Environment

- Game: `~/Library/Application Support/Steam/steamapps/common/Hades/Game.macOS.app` (x86_64). Scripts in `Contents/Resources/Content/Scripts/*.lua`.
- Saves and log: `~/Library/Application Support/Supergiant Games/Hades/` (`Hades.log` is the game's log).
- Conda env: `hades` (Python 3.11), defined in `environment.yml`. Use `/opt/miniconda3/bin/conda run -n hades ...` (the shell `conda` function is broken in agent shells).
- PyTorch on `mps` when available, else CPU.

## Verification

Before handing back: `/opt/miniconda3/bin/conda run -n hades python -m pytest -q tests` and `/opt/miniconda3/bin/conda run -n hades python -m pyflakes scripts agent` (both must be clean).

## Roles

Global default: Claude leads; Codex, Cursor and Antigravity are subagents; Grok is fallback lead. Briefs go in `collab/handoffs/`. Work by one provider is reviewed by another before it counts as done.

Only one agent may drive the game (launch it, send input, install the mod) at a time, because there is one copy, one screen and one keyboard. The lead assigns that; a subagent touches the running game only if its brief says so.

## Collaboration files

- `collab/STATUS.md`: phase, task board, blockers, decisions (lead maintains)
- `collab/LOG.md`: append-only dated log (all agents append)
- `collab/handoffs/NNN-name.md`: one per delegated task

## Questions to the user

The lead asks the user through the host's interactive question tool, not in plain chat text (user instruction, 2026-11-26).

## User instructions

- Target: beat Hades at Heat 0; God Mode only as an early milestone, not the goal (user instruction, 2026-11-26).
- Train in an empty save slot; the agent may earn every upgrade a normal player would and should be affected by everything a human player is (user instruction, 2026-11-26).
- Hobby project; originally local only, then published as a public GitHub repo with a status README (user instruction, 2026-11-26).
- Mod limited to on-screen information only, never hidden values (user instruction, 2026-11-26).
- Game speed may be changed as the lead sees fit (user instruction, 2026-11-26).
- Use the global multi-agent setup to collaborate (user instruction, 2026-11-26).
- Scope: first pass focuses on beating the game end to end (permanent buffs such as the Mirror of Night are in scope where they help); the long-term goal is for the agent to do everything a player can do in the game autonomously (talking to characters, side quests, unlocking weapons and permanent boosts, and the rest). See `docs/plan.md` "Scope and roadmap" (user instruction, 2026-11-26).
- Only one Hades instance may run at a time (user instruction, 2026-11-26).
- Record a video clip of each training iteration/episode as visible, measurable evidence of improvement (user instruction, 2026-11-26).
- If Claude is about to run out of usage, it hands the lead to Grok first, with `collab/STATUS.md` and a lead handoff in `collab/handoffs/` current enough to resume from (user instruction, 2026-11-26).
- Save every training run separately with its results, parameters and everything associated with it (user instruction, 2026-11-26).
