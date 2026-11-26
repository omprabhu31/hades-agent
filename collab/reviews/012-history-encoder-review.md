# 012 Review: observation history and the House mirror hook (8097d0d)

**Verdict — Changes needed.** No hidden value is written into the new history features. The action one-hot has no off-by-one, BC replay uses the same encode-then-record order as a successful env step, and best-epoch restore matches the saved v4 checkpoint. The repeat-last numbers in `docs/plan.md` 3a are right. Two major gaps remain: hero and enemy velocity are raw displacement per `encode` call, so the live decision gap and the BC grid of 2 bridge frames disagree, and a failed bedroom Mirror visit is marked done and not retried.

Read-only. Game not launched, no input sent. Line numbers below are the current files; the history and mirror logic is the 8097d0d code (later commits added the attack block and the gift/keepsake calls around it).

## Major

### M1. Velocity and travel scale with the decision gap, and BC always uses 2 frames

[agent/env/observations.py:176](/Users/om-prabhu/projects/hades-agent/agent/env/observations.py:176), [agent/env/combat.py:251](/Users/om-prabhu/projects/hades-agent/agent/env/combat.py:251), [agent/learn/dataset.py:90](/Users/om-prabhu/projects/hades-agent/agent/learn/dataset.py:90)

`HistoryEncoder` stores hero velocity, enemy velocity and trail travel as the world-unit delta since the previous `encode` call, divided by `VELOCITY_SCALE` (100). It does not divide by the number of bridge frames in between. `build_dataset` calls `encode` on a fixed grid: the next kept row is the first with `frame >= last_decision + frames_per_step` (default 2). The logs used for BC (`runtime/logs/agent3.jsonl`, `agent4.jsonl`, `eval1.jsonl`) are one observation per bridge frame, so every training delta is 2 frames, 0.1 s of game time.

`HadesCombatEnv.step` encodes once per decision. The frame it waits for is `start_frame + frames_per_step`, and `start_frame` is read after `policy.decide` and `apply`. Frames that pass while the policy thinks are extra displacement in the same feature. Recorded episodes, `game_seconds / steps / 0.05`:

| run | speed | episodes | median frames per decision |
| --- | --- | --- | --- |
| heuristic runs and speed-1 evals (9 runs) | 1.0 | 54 | 2.03 to 2.81 |
| `ppo-cycle1` | 3.0 | 10 | 5.76 |
| `ppo-cycle2` | 3.0 | 9 | 6.04 |

On the 13,835 BC rows the hero speed feature has median 0.215 and 95th percentile 0.654, and 0.35% of rows already sit on the ±1 clip. A speed-3 decision of about 6 frames is three times the training interval, so ordinary movement lands near or on that clip, and the 6-decision travel feature covers about three times as much game time as the teacher saw. Enemy velocities use the same scale. Hit recency counts `encode` calls, so "hit last step" is 0.1 s in the dataset and about 0.3 s in a speed-3 episode.

Failure: `runs/*-bc-history-v4`, trained on the 2-frame grid, is evaluated and then used as the PPO warm start at speed 3. The motion features it learned are a different physical quantity live, which is the part of the observation this commit added. Movement changes are already the weak head (below).

Fix: make velocity world units per bridge frame (or per second). In the dataset divide by `frame - last_decision`. In the env divide by `after.frame - before.frame` (the snapshot the previous `encode` used, not the post-apply `start_frame`). Keep the clip. Travel can stay a distance; divide it by the same elapsed frames if it is meant to mean speed over the window.

### M2. A failed Mirror visit is consumed, so that House stay never buys

[scripts/run_agent.py:192](/Users/om-prabhu/projects/hades-agent/scripts/run_agent.py:192), [agent/macro/mirror.py:81](/Users/om-prabhu/projects/hades-agent/agent/macro/mirror.py:81)

`mirror_visit = runs_started` runs before `spend_darkness`. `runs_started` advances only after a new run actually starts. `spend_darkness` returns `[]` with no purchase when the bedroom observation has no mirror point yet, a screen is open, the walk fails, or the menu does not appear within 5 s. The loop still logs the empty list and `continue`s, and the guard will not call the mirror again until the next run has started and the hero is back in the bedroom.

Failure: the first bedroom frame often lacks `house.mirror` (`GetIdsByType` missed, or the prop is not placed yet). That attempt buys nothing, the route walks on to the courtyard, and the run starts with the Darkness unspent. The same happens if the walk to the mirror times out.

Fix: set `mirror_visit` only after a call that opened the menu (purchases, including a deliberate empty buy when nothing is affordable). If the return is an early give-up, leave the guard clear and try on a later bedroom frame, with a small attempt cap so a missing prop cannot spin. The gift and keepsake hooks added after this commit use the same "mark visited first" pattern and will skip the same way.

## Minor

### m1. A step timeout re-encodes the pre-step frame after recording the action

[agent/env/combat.py:251](/Users/om-prabhu/projects/hades-agent/agent/env/combat.py:251), [agent/env/combat.py:266](/Users/om-prabhu/projects/hades-agent/agent/env/combat.py:266)

On the success path the order is right: `record_action`, wait, `encode`. That matches the dataset, which appends `encode(visible)` and then `record_action(teacher.act(visible))`, so the vector stored with an action does not yet contain that action. Checked on the v4 dataset: the most-recent action one-hot equals the previous teacher action on all 13,768 within-episode pairs, and all 67 episode-start rows have zero velocity, travel, hit recency, action one-hots and enemy velocity.

On a timeout, `after` is replaced with `before` and `encode` runs again on the frame that was already encoded. If the action was applied first, that second encode also sees the new action. The trail gains a duplicate point, velocity collapses to about 0, and hit recency advances one step.

Failure: the bridge stalls for `step_timeout` (3 s). The truncated transition's next observation is a corrupted second visit of the pre-step frame. The episode ends, so only the bootstrap value sees it.

Fix: record the action and encode only after the post-apply wait returns a snapshot. On timeout, return the observation the policy already acted on, without a second `encode`.

### m2. `house.jsonl` stores the darkness from before the menu

[scripts/run_agent.py:197](/Users/om-prabhu/projects/hades-agent/scripts/run_agent.py:197), [mod/AgentBridge.lua:380](/Users/om-prabhu/projects/hades-agent/mod/AgentBridge.lua:380)

The log line is written from `o`, the observation captured before `spend_darkness`. The bridge fills `house.darkness` only while the resource text is on screen. The mirror's own darkness readout is copied onto `house.darkness` only once the menu is open, which is after `o` was taken. Purchases (name, new rank, cost) are logged and are the useful part.

Failure: the `darkness` field is missing or is the pre-visit balance, so the line cannot be reconciled with the purchases.

Fix: read `policy_obs()` after `spend_darkness` returns and log that `house.darkness`, or omit the field.

### m3. The stuck-travel window is one decision longer than the teacher's once both are full

[agent/env/observations.py:181](/Users/om-prabhu/projects/hades-agent/agent/env/observations.py:181), [agent/policy/unstick.py:51](/Users/om-prabhu/projects/hades-agent/agent/policy/unstick.py:51)

Travel is measured against the oldest trail point and the current point is appended afterwards. With `TRAIL_STEPS` 6 that is six decision gaps once the deque is full. `UnstickPolicy` appends the current point first, so its window of 6 is five gaps, and it only treats the hero as stuck when every sample in the window was a move command and the distance is under 40. The history feature is ungated distance divided by `POSITION_SCALE` (1000), so 40 units is 0.04.

Failure: the feature the comment calls the "am I stuck?" signal is a longer, unconditional distance. The teacher's sidestep, which is where movement labels change, is not a threshold on this column.

Fix: append first, then measure, and use the same window and "all steps were moves" condition as `UnstickPolicy`, or drop the claim and keep it as a plain travel scalar.

### m4. Plan 3a change-step movement accuracy is 22%, not 24%

[docs/plan.md:66](/Users/om-prabhu/projects/hades-agent/docs/plan.md:66)

Recomputed with `build_dataset` and `split_dataset(..., 0.2, seed=1)` on the archived 8097d0d code (observation width 183), then the saved `runs/20261126T182838Z-bc-history-v4/checkpoints/bc.pt` weights. Checkpoint metadata says best epoch 48, and held-out accuracy reproduces the logged epoch exactly: movement 0.8059, button 0.9315, aim 0.9416. That rounds to the plan's 81% / 93% / 94%.

Repeat-last on the agent3+agent4 held-out split (640 steps that have a previous decision in the episode, 2 episode starts left out): movement 0.8375, button 0.0984, aim 0.9219. That rounds to the stated 84% / 10% / 92%. The small-split best epoch (v1, epoch 23) is 0.791 / 0.855 / 0.821, which rounds to 79% / 86% / 82%. "Repeat-last is 0% on change steps" is true by construction when a change means that head differs from the previous teacher action.

Per-head change-step accuracy of the v4 checkpoint on that same held-out split: movement 120/543 = 22.1%, button 1696/1810 = 93.7%, aim 205/332 = 61.7%. Button and aim round to 94% and 62%. Movement does not round to 24%. The train split is 32.0% (618/1933), not 24% either.

Fix: put 22% / 94% / 62% in the plan, with the denominator (held-out steps whose teacher action changed on that head).

## Nit

### n1. Action-head widths are copied by hand

[agent/env/observations.py:29](/Users/om-prabhu/projects/hades-agent/agent/env/observations.py:29) sets `ACTION_SIZES = (9, 5, 8)`. That matches `len(MOVEMENTS)`, `len(BUTTONS)` and `AIM_SECTORS` today. The one-hot packs movement, then button, then aim, most recent action first, and rejects an index outside `0 <= value < size`. A later edit to `agent/env/actions.py` would silently mis-pack the history. Import the three lengths.

### n2. The dataset test no longer looks at the history columns

[tests/test_learn_bc.py](/Users/om-prabhu/projects/hades-agent/tests/test_learn_bc.py) compares `observations[:, :BASE_SIZE]` to `encode_observation`. `tests/test_history_encoder.py` covers the encoder on its own. A swap of `encode` and `record_action` in `build_dataset` would still pass. One assertion that the second row's action block equals the first teacher action would lock M1's ordering.

## Checked, no finding

Rule 5. The new columns are sin/cos of the visible facing (degrees, same conversion the heuristic uses), deltas of positions already in the policy observation, a decayed "visible HP fell" bit, and the agent's own last two actions. Enemy `id` is only the correspondence key for those deltas. `visible_hud` leaves the hit timer unchanged when `hud` is false, so a hidden bar does not register a hit. Exact HP is not written into the vector. `encode` reads `obs` only; reward still uses `info` on the side.

Best-epoch restore. `train_bc` clones `state_dict` when held-out loss improves and loads that clone before returning. The v4 checkpoint's `best_epoch`, loss and per-head accuracy are epoch 48, the minimum in `train.jsonl`, and a forward pass of those weights reproduces that accuracy. Ties keep the earlier epoch (`<`, not `<=`), which is reasonable.

## Verification

Game not launched. Repeat-last, change-step and the checkpoint forward pass used `/opt/miniconda3/bin/conda run -n hades python` against a `git archive` of 8097d0d (current `observations.py` is 219 floats after the attack block, so the v4 checkpoint will not load there). Frame spacing of the three logs and the episode frame gaps were read from `runtime/logs/*.jsonl` and `runs/*/episodes.jsonl`. The pytest suite was not re-run.

## Lead disposition (Claude, 2026-11-26)
- Major (velocity per decision): fixed. `HistoryEncoder.encode(obs, frame)` measures hero/enemy velocity per bridge frame (game time; 50 units/frame per unit, so a 2-frame BC step gives the old values), the stuck-travel feature over a 12-frame window, and hit recency in frames. The env passes `snapshot.frame`/`after.frame`, the BC dataset passes the log frame. Tests: same speed at 2- vs 6-frame decision spacing gives equal velocity; game-time travel window.
- Major (Mirror visit latched before the result): already fixed by `HouseVisits` (commit 62261ad): an empty purchase list is retried once in the same visit.
- Minor (plan figure): corrected to 22% (120/543) in docs/plan.md 3a.
- Minor (step timeout re-encodes the pre-step frame): the encoder returns its cached vector for a repeated frame, so no zero-motion step is added.
- Minor (darkness logged before the menu): `house.jsonl` now records `darkness_before` and `darkness_after`.
- Retrained after the fix (`runs/*-bc-history-v5`, best epoch 48): held-out 80% / 94% / 95% (movement / button / aim); change steps 27% / 93% / 67.5%.
