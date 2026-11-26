# 003 Bridge review

**Verdict — Request changes.** The bridge exposes room data during the loading screen and allows two launchers to start a game concurrently. Fix both hard-rule violations before training. The Python reader and command channel also need failure handling before unattended runs.

## Critical

### C1. Observations include data that is hidden or wrongly classified

[AgentBridge.lua:87](/Users/om-prabhu/projects/hades-agent/mod/AgentBridge.lua:87), [AgentBridge.lua:109](/Users/om-prabhu/projects/hades-agent/mod/AgentBridge.lua:109), [game.py:123](/Users/om-prabhu/projects/hades-agent/agent/bridge/game.py:123)

The first observation in the existing capture reports `LoadScreen` and already includes the positions, internal IDs and health fractions of 21 `Breakable` objects. The subsequent `InGameUI` observations in the sampled prefix contain the same class of object in `enemies`. The collector admits every living entry in `ActiveEnemies`, even when location lookup fails, so it also has no way to establish that a unit or its health bar is drawn. In Lua 5.2 with a stubbed pause screen and failed location lookup, it still emitted the unit's 0.25 health fraction. Hero HP, room name and completion also come straight from run state. The Python `latest_obs` object contains the full payload, including `info.depth`.

Gate each field on what the current screen actually renders. Omit actors outside the camera or obscured by the current screen, classify visible breakables separately, and emit fractions only for rendered health bars and at their visible precision. Omit engine IDs and internal names from the policy data. Give policy callers a dedicated observation accessor that excludes reward and logging fields. [Existing capture, first observation](/Users/om-prabhu/projects/hades-agent/runtime/logs/live1.jsonl:5)

### C2. The process check can admit two game instances

[game.py:83](/Users/om-prabhu/projects/hades-agent/agent/bridge/game.py:83)

The process check and `Popen` are independent. Two launchers can both observe no Hades process, then both start one. An offline barrier forced that ordering and both reached mock `Popen`. The lookup also interprets a failed `pgrep` with empty stdout as no running game.

Serialize cooperating launchers with a machine-local interprocess lock and repeat the process check under that lock immediately before spawning. Keep the lock through startup confirmation and fail closed on unexpected `pgrep` status. Manual Steam launches bypass the Python lock, so verify the operational rule with the lead as well.

## Major

### M1. Game output depends on the reader staying alive and keeping up

[game.py:95](/Users/om-prabhu/projects/hades-agent/agent/bridge/game.py:95), [game.py:113](/Users/om-prabhu/projects/hades-agent/agent/bridge/game.py:113), [run_game.py:27](/Users/om-prabhu/projects/hades-agent/scripts/run_game.py:27), [bridge_check.py:44](/Users/om-prabhu/projects/hades-agent/scripts/bridge_check.py:44)

If the launcher exits during play, as the diagnostic script intentionally does, closing the final pipe reader can send SIGPIPE to the game. A dummy shell child launched with the same pipe options exited with status `-13` when its read end closed. Hades' native signal handling remains unverified. If the reader thread instead dies while its parent retains the read end, for example on log open or write failure, the undrained pipe can fill and block game writes, including synchronous writes from a hook.

Decouple the game's output sink from the policy and log parser. Use a supervised drainer with an explicit drain-on-error path, or a file-backed sink that the parser tails independently. Define how the sink handles disk exhaustion and how the supervisor reports loss of observations. [Python subprocess signal defaults](https://docs.python.org/3.11/library/subprocess.html#subprocess.Popen), [macOS pipe semantics](https://developer.apple.com/library/archive/documentation/System/Conceptual/ManPages_iPhoneOS/man2/pipe.2.html)

### M2. Closing a live process sends an unconditional hard kill

[game.py:103](/Users/om-prabhu/projects/hades-agent/agent/bridge/game.py:103)

`close()` calls `kill()` whenever its child is alive. The main-menu restriction exists only in a comment. A caller that cleans up in a `finally` block can interrupt a room transition or a save write. An offline mock confirmed the unconditional kill.

Use the in-game Quit flow for controlled shutdown. Require a verified main-menu state for a distinct emergency kill operation, and refuse if that state is unknown or stale.

### M3. The installer accepts game-file changes the uninstaller cannot reverse

[install.sh:5](/Users/om-prabhu/projects/hades-agent/mod/install.sh:5), [install.sh:10](/Users/om-prabhu/projects/hades-agent/mod/install.sh:10), [uninstall.sh:7](/Users/om-prabhu/projects/hades-agent/mod/uninstall.sh:7)

The provided basename can overwrite any script in the target directory, while uninstall removes a wildcard and restores only `RoomManager.lua`. In a temporary fake installation, the stock script remained overwritten after uninstall. A second case removed the backup before uninstall. The script printed success, deleted the bridge and left its import behind. Reusing a backup across Steam updates can also replace a newer stock room manager with the old one. The direct copy and append expose partially completed installs.

Restrict install to the explicitly approved repository bridge files. Verify the current base and back up every destination before changing it. Track exact files and hashes in an install receipt, refuse unexpected drift or a missing backup before deleting anything, and stage replacements with rollback on partial failure. Serialize install and uninstall.

### M4. Command loading fails open when the debug library is absent

[AgentBridge.lua:149](/Users/om-prabhu/projects/hades-agent/mod/AgentBridge.lua:149), [test_bridge_mod.py:93](/Users/om-prabhu/projects/hades-agent/tests/test_bridge_mod.py:93)

For a Lua 5.2 text main chunk the first upvalue is `_ENV`, so `debug.setupvalue(chunk, 1, {})` works in the tested stock runtime. If Hades omits `debug.setupvalue`, the code still runs the chunk in its default global environment before the allowlist can check the returned command. Even with an empty environment, executing a chunk gives it control of execution time and memory in the game's Lua scheduler. `pcall` catches exceptions and provides no resource budget.

Prefer a bounded, non-executable command format. If the embedded API requires Lua loading as an interim transport, verify that the engine honours `loadfile(path, "t", {})`, fail closed when that guarantee is unavailable, and enforce strict field and size limits. Environment isolation alone leaves the resource-exhaustion risk in place. [Lua 5.2 loading and environment semantics](https://www.lua.org/manual/5.2/manual.html#pdf-loadfile)

### M5. Commands can be lost, collide or replay across sessions

[game.py:72](/Users/om-prabhu/projects/hades-agent/agent/bridge/game.py:72), [game.py:132](/Users/om-prabhu/projects/hades-agent/agent/bridge/game.py:132), [AgentBridge.lua:17](/Users/om-prabhu/projects/hades-agent/mod/AgentBridge.lua:17), [AgentBridge.lua:157](/Users/om-prabhu/projects/hades-agent/mod/AgentBridge.lua:157)

`os.replace` publishes a complete file for one writer, but the mailbox holds one command. An offline ping and speed command written before a poll produced only the speed acknowledgement. Two concurrent writers can use the same temporary path. One reproduced interleaving raised `FileNotFoundError`. Each writer seeds its counter to the current whole second, so same-second writers can emit duplicate sequences. `GameBridge.launch()` clears the default command file on its own path, but a fresh game VM started another way will consume the old command. A fresh Lua VM replayed the previous 2.0 speed in the offline check. Overriding Python's `cmd_path` also makes Python clean or write a file that the installed Lua code does not read.

Give each bridge session an identifier, configure one agreed mailbox path, and centralise sequence allocation and acknowledgement handling. Use a unique temporary file for each publish and allow only one outstanding command per mailbox, or queue commands explicitly. Require a fresh-session handshake before accepting side effects. Validate allowed command fields, especially finite speed, interval and sequence values. Treat the reported speed as the last acknowledged request until actual normal-speed evaluation can be verified.

## Minor

### m1. A rejected launch changes where clients look for the active session

[run_game.py:20](/Users/om-prabhu/projects/hades-agent/scripts/run_game.py:20)

The runner creates two logs and changes `CURRENT` before the single-instance check. With a mocked active instance, a rejected launch still redirected `CURRENT` to two empty files. An existing log client can therefore lose the live feed. Publish `CURRENT` atomically only after a successful launch and use validated, unique session names.

### m2. Emission failures can exit the Lua loop or kill the Python reader

[AgentBridge.lua:70](/Users/om-prabhu/projects/hades-agent/mod/AgentBridge.lua:70), [AgentBridge.lua:172](/Users/om-prabhu/projects/hades-agent/mod/AgentBridge.lua:172), [game.py:35](/Users/om-prabhu/projects/hades-agent/agent/bridge/game.py:35)

If the primary print raises, the fallback print is outside `pcall`. In an offline stub, a second print failure escaped `Emit`. A multiline error made fallback output invalid JSON because Lua `%q` follows Lua quoting rules. Python handles JSON syntax errors, but valid arrays or `null` raise `AttributeError` on `.get()`, terminating the reader. The prefix search anywhere on the line makes this reachable from unrelated output containing the marker.

Keep emission and fallback inside a bounded error path and use the same JSON encoder for the fallback. Validate the protocol envelope before dispatch and handle malformed input without ending the drain loop. Match the actual output framing and report the reader's EOF or error to consumers.

### m3. Per-tick work and accumulated output are unbounded

[AgentBridge.lua:18](/Users/om-prabhu/projects/hades-agent/mod/AgentBridge.lua:18), [AgentBridge.lua:149](/Users/om-prabhu/projects/hades-agent/mod/AgentBridge.lua:149), [game.py:77](/Users/om-prabhu/projects/hades-agent/agent/bridge/game.py:77), [run_game.py:29](/Users/om-prabhu/projects/hades-agent/scripts/run_game.py:29)

At the default interval the loop requests a command-file load and a full snapshot every 0.05 game seconds. It recompiles an unchanged command while the file remains in place, queries each enemy location, and encodes the full observation. The sampled prefix contained 6,566,618 JSONL bytes and 6,026,897 raw stdout bytes over about 194 seconds of captured timestamps. Both files append indefinitely, and the unbounded event queue retains messages if a client reads only `latest_obs`. Long sessions can exhaust disk or memory. Synchronous logging also increases pipe backpressure.

Cap log retention and queue growth, with an explicit policy for retaining acknowledgements. Poll commands independently at a bounded cadence, avoid rereading consumed commands, and measure in-game frame pacing at the observation rates and simulation speeds used for training. The capture measures output size, with CPU and frame-time overhead still unmeasured.

### m4. The focus fallback runs even when AppKit has succeeded

[quartz.py:54](/Users/om-prabhu/projects/hades-agent/agent/input/quartz.py:54)

After the AppKit activation request, the function always invokes System Events before checking the frontmost app or window. In the mock, an already-frontmost Hades window still caused a raw `TimeoutExpired` when AppleScript timed out. A failure can block input initialisation on a system where AppKit was sufficient. Check for a visible window owned by the selected PID after AppKit activation, use System Events only if still needed, and translate a failed fallback into an actionable `InputStopped` or `GameWindowNotFound`.

### m5. Hook coverage depends on import order

[AgentBridge.lua:188](/Users/om-prabhu/projects/hades-agent/mod/AgentBridge.lua:188), [AgentBridge.lua:207](/Users/om-prabhu/projects/hades-agent/mod/AgentBridge.lua:207)

Hooks are installed once by looking up globals. A function defined after import is skipped, as reproduced with a late-defined `KillEnemy` stub. A later reassignment can also replace a wrapper. Events are emitted before the original runs, so a failed or aborted original can still leave an event that appears to record success. The offline wrapper check preserved the original's arguments and multiple returns, including nil positions.

Verify hook registration at the point when game functions and callers are in place, and define each event as a pre-call signal or a confirmed transition. Add map reload coverage for one active loop, including a prior coroutine resuming after a generation change. Actual hook signatures, engine scheduler cancellation and pause behaviour remain unverified.

## Verification and test gaps

- `/opt/miniconda3/bin/conda run -n hades python -m pytest -q tests` with bytecode and pytest's repository cache disabled: **27 passed in 0.03s**.
- `bash -n mod/install.sh` and `bash -n mod/uninstall.sh` both passed. Reversibility checks ran against synthetic files under a temporary home.
- Offline checks used stock Lua 5.2, mocks and a dummy shell child. The existing Hades capture was read for evidence. The review did not enter the game installation or save directories, so the native Lua loader, engine function signatures, actual health-bar rendering, scheduler and wait behaviour, native SIGPIPE disposition, live Quartz behaviour and frame-time overhead remain unverified.
- Add regression fixtures for load screens, off-camera actors, breakable classification and absent bars. The current observation test uses a single visible-by-assumption dummy enemy and checks only that depth is under `info`. [test_bridge_mod.py:64](/Users/om-prabhu/projects/hades-agent/tests/test_bridge_mod.py:64)
- Add command cases for missing debug, malformed and non-finite values, competing writers, stale sessions, and commands acknowledged in order. Cover launcher rejection side effects, concurrent launches, logger failure and shutdown with a dummy child. Also exercise installer rollback and Quartz fallback ordering offline, and ask the lead to verify the real map, pause and focus transitions.

## Lead disposition (Claude, 2026-11-26)

- C1 partly fixed: no world data on `LoadScreen`; `Breakable*` moved to `obs.breakables` (no health); units without a readable location dropped; `GameBridge.policy_obs()` returns only `obs`. Kept deliberately: object ids (identity tracking a human does by eye) and enemy type names (the sprite shows the type). Open: off-camera gating needs the camera/world-to-screen mapping from task 002; health-bar visibility per enemy type unverified.
- C2 fixed: `fcntl` launch lock held for the game's lifetime, process check under the lock, `pgrep` errors fail closed. Manual Steam launches remain covered only by the AGENTS.md rule.
- M1 fixed: `scripts/bridge_check.py` (the early-exiting reader) deleted; readers always drain stdout and treat log failures as non-fatal.
- M2 fixed: `close()` refuses to kill without `force=True`.
- M3 fixed (simplified): install only installs `mod/AgentBridge.lua`, refuses while Hades runs, refreshes the backup whenever the live file has no bridge Import (handles Steam updates), stages then swaps; uninstall refuses if the backup is missing.
- M4 fixed: `loadfile(path, "t", {})` (text only, empty environment); tests cover the empty env and bytecode rejection. Resource exhaustion by our own command file accepted as a risk.
- M5 partly fixed: unique temp files, ms-resolution sequence numbers, non-finite values rejected on both sides, launch clears the mailbox. One outstanding command at a time is the documented protocol (`GameBridge.command` waits for the ack).
- m1 fixed (CURRENT written after a successful launch, session names validated). m2 fixed (emit fallback in pcall with the same encoder; envelope validated; prefix must start the line). m3 partly fixed (commands polled every 5th frame; `run_game.py --obs-every`, default 4; bounded message deque). Frame-time overhead still to measure. m4 fixed. m5 accepted: events are pre-call signals; documented.
- Tests: 38 pass (`python -m pytest -q tests`). Live re-verification of the updated mod is pending the next input window.
