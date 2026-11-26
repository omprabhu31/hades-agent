# Plan: an agent that beats Hades

Target: defeat Hades at the end of the Styx, Heat 0, no God Mode, in the training save (slot 2), playing through keyboard and mouse with only on-screen information. Milestones are judged at game speed 1.0.

## Scope and roadmap (user instruction, 2026-11-26)

Hades has much more than combat: talking to characters, gifting Nectar and Ambrosia, side quests (the Fated List of Minor Prophecies), unlocking weapons and their aspects, permanent boosts from the Mirror of Night and other sources (keepsakes, companions, House Contractor upgrades), fishing, the Codex, the Pact of Punishment, and the story after the first escape. The agent should eventually do all of it autonomously. The order:

**Stage A: beat the game end to end (current focus).** Combat, boons, doors, the House route, and the permanent boosts that make escapes winnable:
- **Mirror of Night** (Darkness, every run): buy survivability first. Death Defiance ranks, Thick Skin (max HP), Chthonic Vitality (heal on entering a chamber), Greater Reflex (extra dash), Infernal Soul (cast ammo); then damage (Shadow Presence, Boiling Blood). Exact costs and unlock order come from the game's `MetaUpgradeData.lua` when this is built.
- **Keepsakes** that are cheap to earn and help directly, e.g. Cerberus's Old Spiked Collar (+max HP) from one Nectar gift. This needs the first NPC interaction (walking to a character and gifting).
- **Weapon choice** once Chthonic Keys unlock other Infernal Arms; pick the one the policy does best with, by measurement.
- Pact/Heat stays at 0 for the goal run.

**Stage B: the rest of the game.** Character conversations and gifting until relationships max out; Fated List prophecies; all weapons and aspects (Titan Blood); remaining Mirror ranks and alternates; House Contractor purchases; fishing; Codex completion; companions; the epilogue (repeated escapes); Heat and Pact challenges. Each becomes a macro skill with a check in the bridge (visible information only) and its own recorded runs.

Design implication: the macro layer will grow from a fixed script into a goal planner (what to do this visit to the House, this run, this room), with each activity as a separately tested skill. Combat stays a learned policy.

## Architecture

```
 Hades (one instance, launched by scripts/run_game.py)
   |  mod/AgentBridge.lua  -- read-only; "AGB1 <json>" lines on stdout
   v
 runtime/logs/<session>.jsonl  <-- scripts/run_game.py logs every message
   |                                  runtime/cmd.lua --> mod (speed, ping)
   v
 agent/bridge  (parse, latest obs, send commands)
 agent/input   (Quartz keyboard + mouse, safety stops)
 agent/env     (planned: Gymnasium env, one episode = one combat room)
 agent/macro   (planned: scripted doors, boons, shops, House, dialogue)
 agent/policy  (planned: heuristic baseline -> imitation -> RL)
```

Split of responsibilities: combat (movement, dodging, attacking) is learned; between-room decisions start as hand-written rules and can be learned later.

## Phases

1. **Bridge** (in progress). Done: mod loading, stdout and command channels, hero/enemy/room observation, run/room/kill/death events, speed command, input driver, live movement test.
   Remaining: projectiles, traps and hazards; door reward icons and door positions; menu screens (boon, hammer, shop, Mirror, dialogue) with their options; world-to-screen mapping for aiming; filter non-enemies (Breakable pots) out of `enemies`; automated game start/quit and menu navigation; check whether input can be posted to the game in the background (`CGEventPostToPid`) and whether the game keeps updating unfocused.
2. **Environment.** Fixed decision rate in game time; observation vector (hero, nearest enemies, projectiles, hazards, cooldowns visible on HUD); discrete actions (8 directions or none x attack/special/cast/dash/none x aim sector); reward from damage dealt, damage taken, room cleared, death (hidden values allowed in reward only).
3. **Macro scripts.** Run start from the House, door choice, boon/hammer/pom choice from a priority table, Charon shop, wells, fountains, dialogue skipping, Mirror of Night and other permanent upgrades between runs.
4. **Combat policy.** Heuristic baseline first (kite and attack nearest) to measure the environment and collect data; optionally behaviour cloning from the user's own play; then RL (PPO on `mps`) with game speed raised as far as stays stable.
5. **Curriculum and evaluation.** Milestones: clear a Tartarus room; beat Megaera (God Mode allowed as a labelled milestone); clear Tartarus without God Mode; Asphodel (Bone Hydra); Elysium (Theseus and Asterius); Styx; Hades. Every milestone attempt is logged with git SHA, config, seed and date.

## Known gaps (2026-11-26)

- **Room geometry.** The first live fight got stuck walking straight at enemies behind an obstacle. No script exposes a walkability map; `IsLocationBlocked` takes an object id, not a point. A `HasLineOfSight` probe per enemy is in the mod but unverified. Options: learn from positions, a downsampled screen image as an extra observation channel, or path-following along recorded positions.
- **Projectiles.** No positions after spawn (`OnWeaponFired`/`OnProjectileDeath` only). Options: track fire events as "enemy just attacked"; screen pixels.
- **Telegraphs.** Not stored as a flag; same options.

## Constraints that shape the design

- One game instance; real time unless sped up; no parallel environments.
- Synthetic input needs Hades frontmost unless background posting works, so training sessions take over the Mac.
- Hard kills of the game are only safe at the main menu or between runs (saves are written during runs).

## Status and next steps (2026-11-26)

Done: bridge v2 (hero/enemies/traps/doors/pickups/boon menu/House), input driver, calibration, Gymnasium combat env, heuristic + unstick baseline, macro layer (boons, dialogue, pickups, doors, House route), clean quit, run recorder with clips and `runs/report.html`. The agent plays full escape attempts unattended at speed 1.0 and restarts from the House.

Next, in order:
1. **Baseline evaluation.** N runs of the heuristic at speed 1.0 to get a stable reference (rooms cleared per run, depth reached, damage taken per room), recorded as a named run.
2. **Speed for training.** Use speed 3.0 (about 2.3x measured) for training runs; check the heuristic behaves the same at 3.0 (evaluation stays at 1.0).
3. **Learning.** Behaviour cloning of the heuristic as a warm start for a PPO policy on the env (MPS), then PPO fine-tuning room by room; each training cycle followed by a recorded evaluation run so improvement is measurable in the report.
3a. **Observation history (done 2026-11-26, task 009).** The single-frame BC model reached ~44% movement / 29% button / 27% aim held-out accuracy. `HistoryEncoder` (agent/env/observations.py) adds visible context: facing, hero velocity, travel over 6 decisions, recency of the last HP drop, the last 2 actions, and per-slot enemy velocity (117 -> 183 floats). Same data and seed (agent3+agent4 logs): 79% / 86% / 82%. But "repeat the last action" scores 84% / 10% / 92% on that split, so the movement/aim gain was mostly persistence. With 5x more data (adding the eval1 session log, 13.8k samples, best-epoch weights): 81% / 93% / 94% overall, and on steps where the teacher *changes* its action 24% movement, 94% button, 62% aim (repeat-last is 0% there by definition). Movement changes remain the weak spot (they come from the unstick wrapper and distance-band rules). Next: live evaluation of `runs/*-bc-history-v4` vs the heuristic, then PPO from it; more data via DAgger-style relabelling of policy-played frames.
4. **Perception gaps.** Projectiles and telegraphs (see Known gaps); try a small downsampled screen channel if the vector policy plateaus.
5. **Meta-progression.** Mirror of Night purchases between runs (Darkness), keepsakes, weapon choice once unlocked; bosses (Megaera first).
