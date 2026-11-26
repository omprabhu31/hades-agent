# 008: Learning pipeline (behaviour cloning warm start + PPO) for the combat env
Status: DONE
Owner: Codex

## Goal
Code that trains a neural combat policy on `HadesCombatEnv` and logs each training cycle as a recorded run, so improvement over the heuristic baseline can be measured. Fully testable offline; the lead runs it live.

## Context (read first)
- `AGENTS.md` (rules 5 visible-only, 6 speed: training may use speed > 1, milestone evaluation at 1.0; 7 single instance; user instructions: clip + full record for every training run), `collab/STATUS.md`, `docs/plan.md` ("Status and next steps").
- Env: `agent/env/combat.py` (`HadesCombatEnv`, 117-float observation, `MultiDiscrete([9, 5, 8])`), `agent/env/observations.py`, `agent/env/actions.py`.
- Baseline policy: `agent/policy/heuristic.py` wrapped by `agent/policy/unstick.py` (`UnstickPolicy`).
- Live runner: `scripts/run_agent.py` (combat episodes via the env; macro layer handles everything else; `RunRecorder` in `agent/runs.py` writes `runs/<stamp>-<name>/` with meta.json, code snapshot, episodes.jsonl, summary.json, clips/).
- Real data: `runtime/logs/agent*.jsonl` bridge logs (one JSON per line: `{"t","k","f","d"}`; `d.obs` is the policy view, `d.info` hidden reward data) from heuristic play, ~11 combat episodes; useful for offline BC tests and as a first dataset.
- Machine: Apple M5, 16 GB, no CUDA. PyTorch 2.15 with `mps` (fall back to CPU). One game instance, real time (speed 3.0 is about 2.3x).

## Scope
May create/edit: `agent/learn/**`, `scripts/train_bc.py`, `scripts/train_ppo.py`, `scripts/eval_policy.py`, `tests/test_learn*.py`, append to `collab/LOG.md`; add pinned dependencies to `environment.yml` only if unavoidable (say why). Must not edit `agent/bridge/**`, `agent/input/**`, `agent/env/**`, `agent/macro/**`, `mod/**`, `scripts/run_agent.py`, `AGENTS.md`, `collab/STATUS.md`. **Do not launch the game, do not post real input events.** Do not commit.

## Requirements
1. Policy network: small MLP actor-critic over the 117-float observation with three categorical heads (movement 9, button 5, aim 8). Deterministic seeding. Save/load checkpoints with config and observation-size checks.
2. Behaviour cloning: build a dataset of (observation vector, heuristic action) pairs, either from recorded bridge logs (re-encode `d.obs` with `agent.env.observations.encode_observation` and label with the heuristic+unstick policy) or collected live; train with cross-entropy, report held-out accuracy per head; deterministic train/validation split.
3. PPO: online PPO on the real env (single environment, so small rollouts; GAE; clipped objective; entropy bonus; value loss), initialised from the BC checkpoint. It must tolerate episode truncation/timeouts, keep the controller released between episodes, and checkpoint every K updates. Expect the macro layer to move between rooms: expose a `train_step(env, ...)`/callback structure that `scripts/run_agent.py`-style loops can call per combat episode (so the lead can integrate it with the macro loop), rather than owning the whole game loop.
4. `scripts/eval_policy.py`: run a saved policy in place of the heuristic for N episodes via the same macro loop and RunRecorder (clips + metrics), with `--speed` (default 1.0) and the checkpoint path recorded in meta.
5. Training records: each training cycle writes into its own `runs/<stamp>-<name>/` (reuse `agent.runs.RunRecorder`): hyperparameters, seeds, dataset description, losses per update (`train.jsonl`), checkpoints (`checkpoints/`), and per-episode metrics/clips.
6. Readable code with comments explaining why; no hidden `info` values in the policy input (test it).

## Acceptance criteria
- `/opt/miniconda3/bin/conda run -n hades python -m pytest -q tests` passes (91 existing + yours).
- Tests: network shapes and masking-free sampling; BC on a synthetic dataset reaches high accuracy; BC dataset builder on a small slice of a real `runtime/logs/agent3.jsonl` file; PPO update on a fake env improves a toy objective or at least runs end to end with fakes; checkpoint round trip; hidden-info isolation.
- No live game, no real input.

## Report

### Implementation

- `agent/learn/` contains the 117-input actor-critic, seeded action sampling, versioned checkpoint IO, bridge-log dataset builder, behaviour cloning and PPO. It uses the existing PyTorch and Gymnasium dependencies.
- `scripts/train_bc.py` labels active combat at the env's default two-frame decision stride. It resets the heuristic and unstick state per observed combat episode, holds out whole episodes when possible, and uses a final time block for a single episode. Run metadata records the input paths, SHA-256 of the consumed byte prefixes, sample counts, split, seed and hyperparameters. It writes `train.jsonl` and `checkpoints/bc.pt`. Offline BC uses existing observations and produces no new game footage.
- `scripts/train_ppo.py` and `scripts/eval_policy.py` use the lead's existing `run_agent.main` hook. They require a running instance and the selected training slot, back up the save folder, and record combat metrics and clips through `RunRecorder`. The checkpoint path and SHA-256 are in run metadata. PPO writes losses to `train.jsonl`, saves numbered checkpoints every `--checkpoint-every` updates and writes `final.pt` on a normal exit after at least one update.
- `tests/test_learn*.py` cover unmasked action sampling, checkpoint compatibility, a captured log slice, cloning accuracy, hidden-info isolation, PPO improvements and truncation, input cleanup, and both live entry points through the macro loop with fakes. A missing or empty clip stops a learned-policy run and surfaces the recording failure.

### Verification

- `/opt/miniconda3/bin/conda run -n hades python -m pytest -q tests` passed all 108 tests, including the `runtime/logs/agent3.jsonl` test. `--help` succeeded for all three CLIs.
- Offline MPS BC with `runtime/logs/agent3.jsonl runtime/logs/agent4.jsonl --device mps --seed 7 --name bc-grouped-smoke` used 2,471 training samples and 265 validation samples across 12 observed episodes. After 15 epochs, held-out movement, button and aim accuracy were 34.3%, 66.8% and 40.4%. The corresponding training-set majority predictions were 11.7%, 66.8% and 18.9% on that split. The run used a temporary output directory.
- A second MPS smoke loaded the checkpoint from a 180-sample `agent3` BC run and completed a 16-step fake PPO episode ending at `step_limit`, with finite loss and released input. The CPU toy test's probability of selecting the rewarded move rose from 11.8% to 99.2% after four updates.
- The game was neither launched nor controlled for these checks. No commits were made.

### Integration

- Run `python -m scripts.train_bc runtime/logs/agent3.jsonl runtime/logs/agent4.jsonl` in the `hades` env to generate a BC checkpoint. With Hades already running in the training slot under `scripts.run_game --obs-every 1`, use `python -m scripts.train_ppo <bc.pt> --episodes N --speed S`. Evaluate with `python -m scripts.eval_policy <checkpoint.pt> --episodes N` at the default speed of 1.0. Evaluation uses seeded categorical samples by default and accepts `--greedy` for per-head argmax.
- The PPO `episode_fn` calls `PPOTrainer.collect_episode(env, obs, after_step)` after the macro runner resets the env. `on_episode_end` calls `trainer.update(rollout)` after the inputs are released and the clip is closed. `PPOTrainer.train_step(env, obs, after_step)` combines the same operations for callers with an already reset env. PPO computes GAE in bounded segments while gathering one room per update so optimisation happens between rooms. It bootstraps valid step-limit observations and uses zero continuation value on death, clear, stale-frame timeout or room change.
- Live verification and comparison with the heuristic are open. The BC labels depend on visible facing and recent motion and button history, which the fixed 117-float vector does not preserve. The captured-data button result matched the majority baseline, so the checkpoint is a warm start whose combat performance still needs evaluation. Checkpoints preserve policy weights and configuration for evaluation or warm starting.
