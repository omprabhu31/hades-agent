# hades-agent

An agent that learns to play [Hades](https://www.supergiantgames.com/games/hades/) (Supergiant Games) on macOS. The aim is to beat the final boss at Heat 0, without God Mode, playing through the keyboard and mouse with only the information a human player can see on screen.

This is a hobby project. It is not affiliated with or endorsed by Supergiant Games, and it needs your own copy of the game.

## Status (26 November 2026)

**The agent can play full escape attempts on its own, but it does not get far yet.** It fights, picks boons and hammers, clicks through dialogue, collects rewards, chooses doors, and after a death walks back through the House of Hades to start a new attempt. Every attempt so far has died in Tartarus, the first region, at chamber depth 2 to 5. Reinforcement learning has started but has not yet produced a measurable improvement over the hand-written policy.

| Milestone | State |
|---|---|
| Read the game state (visible information only) | Done |
| Drive the game with synthetic keyboard and mouse | Done |
| Play rooms, boons, doors, dialogue, the House, unattended | Done |
| Record every run (parameters, metrics, clips) | Done |
| Learning pipeline (behaviour cloning, then PPO) | Running; no reliable gain yet |
| Clear Tartarus, beat Megaera | Not yet |
| Beat Hades at Heat 0 | Not yet |

### Latest results

Combat chambers only (the easy opening chamber is excluded). Speed is game speed during the episodes measured.

| Policy | Speed | Chambers | Cleared | Damage taken per chamber | Kills per chamber | Died at depth |
|---|---|---|---|---|---|---|
| Hand-written baseline | 1x | 10 | 60% | 21.3 | 3.9 | 3, 3, 3, 4 |
| PPO cycle 1 (evaluation) | 1x | 7 | 71% | 14.3 | 5.6 | 5, 4 |
| PPO cycle 2 (evaluation) | 1x | 7 | 57% | 21.0 | 8.3 | 2, 5, 3 |

With 7 to 10 chambers per policy, these differences are within noise: chamber types and boons vary between attempts. The next evaluations will use at least 30 chambers per policy before any improvement is claimed.

### What is being worked on next

1. **Observation history.** The learned policy copies the hand-written one poorly: about 40% agreement on movement and 30% on aim in held-out chambers. That policy's choices depend on recent movement and button presses, which the current observation does not include. Next is adding previous actions, velocity and recent positions, and collecting more data.
2. **Larger evaluations**, so changes can be measured with confidence.
3. **Perception gaps.** There is no game data for projectile positions or attack warnings. Options are tracking attack events, or adding a small downscaled screen image to the observation.
4. **Permanent boosts.** Spend Darkness at the Mirror of Night between runs (Death Defiance and max-HP upgrades first), then the first boss.

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

Learned policies: `scripts/train_bc.py`, `scripts/train_ppo.py` and `scripts/eval_policy.py`. Checks: `python -m pytest -q tests` (108 tests) and `python -m pyflakes scripts agent`.

Use a spare save slot. The mod never changes gameplay, and `mod/uninstall.sh` restores the original game script.

## Notes

- `docs/plan.md` has the plan and known gaps. `collab/STATUS.md` has the detailed status and how to resume.
- `docs/game_state_reference.md` documents where each piece of on-screen state lives in the game's Lua scripts. It quotes short excerpts for reference. The game and its scripts are © Supergiant Games.
- Built with several AI coding agents working together: Claude Code leads, Codex and Grok implement and review. Briefs and reviews are in `collab/`.
