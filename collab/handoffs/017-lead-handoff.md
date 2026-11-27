# 017: Lead handoff (Claude to Grok if Claude runs out of usage)
Status: STANDBY (used only if Claude stops mid-session)
Owner: Grok (fallback lead)

## Goal
Finish the live session in task 015 without breaking the hard rules, then leave the machine clean: game quit through its menus, mod uninstalled, no scripts running, status files current.

## Context
- Read `AGENTS.md` (hard rules 1-9), `collab/STATUS.md` (task board, "How to resume"), the last entries of `collab/LOG.md`, then `git log --oneline -15`.
- The user granted the live window on 2026-11-26 around 21:05 GMT ("Do it now"). The agent drives the keyboard and mouse while it plays.
- Live progress is logged step by step in `collab/LOG.md` under "Live session 015". The last line there is where to pick up.
- Push to GitHub only after the live checks (Mirror, gifting, keepsake equip) pass (user answer, 2026-11-26). Local commits ahead of origin: see `git log origin/main..main`.

## Scope
- May run the scripts in `scripts/` and edit `collab/STATUS.md`, `collab/LOG.md`, `docs/plan.md`, `README.md` (status only).
- Must not touch `Profile1*`, must not launch a second Hades (`pgrep -x Game.macOS` first), must not hard-kill the game during play (`python -m scripts.quit_game`).

## Acceptance criteria
- `pgrep -x Game.macOS` empty at hand-back, `mod/uninstall.sh` run, `grep -c AgentBridge <game>/Scripts/RoomManager.lua` prints 0.
- `collab/STATUS.md` results table and task board updated from logged outputs only (`runs/cycles.json`).
- Tests and pyflakes clean (AGENTS.md "Verification").

## Report
(Grok fills in if used.)
