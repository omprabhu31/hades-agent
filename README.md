# hades-agent

An agent that learns to play [Hades](https://www.supergiantgames.com/games/hades/) (Supergiant Games) on macOS. The aim is to beat the final boss at Heat 0, without God Mode, playing through the keyboard and mouse with only the information a human player can see on screen.

This is a hobby project. It is not affiliated with or endorsed by Supergiant Games, and it needs your own copy of the game.

## Status (27 November 2026)

**The agent plays full escape attempts on its own and now builds up permanent upgrades between them, but it has not yet cleared Tartarus.** It fights, picks boons and hammers, clicks through dialogue, collects rewards and chooses doors. After a death it walks through the House of Hades, where it:

- buys Mirror of Night upgrades;
- gives Nectar to Cerberus, and equips the keepsake he gives back;
- starts the next attempt.

The furthest it has got is chamber depth 7, where it reached the first mini-boss. Reinforcement learning runs but has not yet produced a measurable improvement over the hand-written policy.

| Milestone | State |
|---|---|
| Read the game state (visible information only) | Done |
| Drive the game with synthetic keyboard and mouse | Done |
| Play rooms, boons, doors, dialogue, the House, unattended | Done |
| Permanent upgrades: Mirror of Night, Nectar gifts, keepsakes | Done (verified in the game) |
| Record every run (parameters, metrics, clips) | Done |
| Learning pipeline (behaviour cloning, then PPO) | Running; no reliable gain yet |
| Clear Tartarus, beat Megaera | Not yet |
| Beat Hades at Heat 0 | Not yet |

### Latest results

Combat chambers only (the easy opening chamber is excluded), all at normal game speed.

| Policy | Permanent upgrades | Chambers | Cleared | Damage taken per chamber | Kills per chamber | Died at depth |
|---|---|---|---|---|---|---|
| Hand-written baseline | none | 10 | 60% | 21.3 | 3.9 | 3, 3, 3, 4 |
| PPO cycle 1 (evaluation) | none | 7 | 71% | 14.3 | 5.6 | 5, 4 |
| PPO cycle 2 (evaluation) | none | 7 | 57% | 21.0 | 8.3 | 2, 5, 3 |
| Hand-written, with upgrades | Death Defiance, Chthonic Vitality, Shadow Presence, Old Spiked Collar | 19 | 84% | 19.6 | 7.5 | 6, 7, 7 |

The last row reached deeper chambers mainly because of the permanent upgrades, not a better policy. With 7 to 19 chambers per row, the differences are within noise. Policies will be compared with at least 30 chambers each, under the same upgrades, before any improvement is claimed.

### What is being worked on next

1. **Cloned policy against the hand-written one.** The cloned policy now sees recent actions, its own and enemies' movement, recent hits, and which visible enemies just attacked. On held-out chambers it agrees with the hand-written policy 85% of the time on movement, 92% on buttons and 94% on aim. Next is a live comparison over at least 30 chambers each, then PPO starting from it.
2. **Wasted attacks.** The hand-written policy swings whenever an enemy is roughly in range. The reward has no direct cost for a swing that hits nothing, so an optional penalty for that will be tested in its own PPO cycle.
3. **Getting around obstacles.** Movement between points is a straight line with sidesteps. A door behind an obstacle once held the agent for 14 minutes; it now tries detours, and stops itself if it still can't reach the door.
4. **The first bosses**, starting with Megaera.

## Scope

The first goal is to beat the game end to end. That includes the permanent boosts a player builds up between runs, such as Mirror of Night upgrades, because they make escapes far more winnable. Eventually the agent should do everything a player can do: talk to characters and give gifts, complete side quests (the Fated List), unlock every weapon and aspect, fish, fill the Codex, raise the Heat, and see the story through. `docs/plan.md` has the staged roadmap.

## How it works

```
Hades (macOS build, one instance)
  │  mod/AgentBridge.lua: read-only Lua mod, ~20 observations per second of game time
  │     game → Python: JSON lines on the game's stdout
  │     Python → game: a small command file the mod polls (only "speed" and "ping")
  ▼
agent/bridge   parse the stream, attach to the running game, send commands
agent/input    Quartz keyboard and mouse events, with safety stops (STOP file, human mouse movement)
agent/env      Gymnasium environment: one episode is one combat chamber
agent/policy   hand-written baseline (+ an "unstick" wrapper for walls and pots)
agent/macro    everything outside combat: boons, dialogue, pickups, doors, the House route
agent/learn    behaviour cloning and PPO (PyTorch, Apple Silicon MPS)
agent/runs.py  per-run records: parameters, code snapshot, metrics, screen-recorded clips
```

**Visible information only.** The mod passes the policy only what a human can see:

- positions;
- health bars as fractions;
- the HUD numbers, and only while the HUD is shown;
- door reward icons, and only once the doors are lit;
- the boon cards on screen.

Exact enemy health, unrevealed rewards and similar hidden values are used only to compute rewards and metrics, never as policy input. This is tested.

**Game speed.** Training runs use a faster game speed: 3.0 gives about 2.3x real time. Evaluations always run at 1.0.

## Running it

Requirements: macOS on Apple Silicon with Rosetta 2, your own copy of Hades (Steam), conda, ffmpeg, and Accessibility and Screen Recording permission for the terminal. The agent takes over the keyboard and mouse while it plays.

```bash
conda env create -f environment.yml          # env "hades"
mod/install.sh                                # install the bridge (reversible: mod/uninstall.sh)
python -m scripts.run_game --session s1 --obs-every 1 &   # launch the single game instance
# load a spare save slot in the game, then:
python -m scripts.run_agent --runs 3 --rooms 80 --max-minutes 20 --name my-run
python -m scripts.make_report                 # runs/report.html: comparison table and clips
python -m scripts.quit_game                   # always quit through the game menus
```

Learned policies: `scripts/train_bc.py`, `scripts/train_ppo.py` and `scripts/eval_policy.py`. Checks: `python -m pytest -q tests` (163 tests) and `python -m pyflakes scripts agent`.

Use a spare save slot. The mod never changes gameplay, and `mod/uninstall.sh` restores the original game script.

## Notes

- `docs/plan.md` has the plan and known gaps. `collab/STATUS.md` has the detailed status and how to resume.
- `docs/game_state_reference.md` documents where each piece of on-screen state lives in the game's Lua scripts. It quotes short excerpts for reference. The game and its scripts are © Supergiant Games.
- Built with several AI coding agents working together: Claude Code leads, Codex and Grok implement and review. Briefs and reviews are in `collab/`.
