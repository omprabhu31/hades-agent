# 016: Attack observations and House route review

**Request changes.** Keep the new attack features out of policy observations until visibility is established. The House route also needs to handle menus and distinguish visits from runs.

Scope covers the attack subscriber and encoder in `ad5b6c8`, and the lead's `GetUseData` wrapper and House integration in `3b30983`. Game references are relative to Hades's installed `Content` directory.

## Critical

### 1. Weapon-fire events reach the policy without evidence of an on-screen cue

**Where** `mod/AgentBridge.lua:731-743`, `:176`, `:206-214`, `agent/env/observations.py:141-152`.

**Failure** After rejecting the hero, the subscriber records every owner. The shot export is independent of enemy and trap filtering, so it can expose off-screen or invisible owners, allies, charmed units and auxiliary weapon owners. Even a visible owner can fire a weapon with no cue. The game sets up lava tiles with `FireAndQuit`, which calls `FireWeaponFromUnit`. The lava weapon has no fire sound or effect, and its projectile has no graphic. The visible terrain does not convey when that attached damage volume was fired. A stubbed event from an invisible owner produced both non-zero attack recency and a shot. See `Scripts/EnemyData.lua:27541-27572`, `Scripts/EnemyAI.lua:186-188`, `Game/Weapons/EnemyWeapons.sjson:4370-4379` and `Game/Projectiles/EnemyProjectiles.sjson:8730-8771`.

**Fix** Remove `firedAgo` and `shots` from policy-facing `obs` until the bridge can establish a drawn cue at the time and place reported. Keep raw events in `info` if needed for logging. For a future structured feature, require positive evidence of an on-screen cue for each supported attack. Test unseen, auxiliary and allied owners as well as a visible attack. Rule 5 requires this even if the callback has no gameplay side effects.

## Major

### 2. Shot rows encode the owner's pose as the projectile's trajectory

**Where** `mod/AgentBridge.lua:737-742`, `agent/env/observations.py:146-152`, `tests/test_history_encoder.py:75-85`.

**Failure** The recorded coordinates and heading come from the owner. For example, the Elite Wretched Thug's `HeavyMeleeEliteShockwave` config has a barrel length of 300 and three projectiles with angle offsets. An owner pose cannot specify the individual launch origins and directions. The encoder also turns a missing angle into a rightward shot with its presence bit set, which the offline probe reproduced. `ProjectileName` is a valid field of the event, but the stock handler uses it as a projectile type key and provides no evidence that the owner pose is a launch pose. See `Game/Weapons/EnemyWeapons.sjson:287-309` and `Scripts/Combat.lua:2259-2296`.

**Fix** Report shot origin and direction only when verified for a visible projectile. If the available cue is the visible shooter's pose, label it accordingly. Omit unsupported or missing directions or mask them explicitly. Use 90° and 270° fixtures to exercise the vertical sign that the existing 180° test misses.

### 3. Attack age and retention depend on the current polling interval

**Where** `mod/AgentBridge.lua:630-635`, `:660-672`, `:705-725`, `:736-741`, `agent/env/observations.py:44`.

**Failure** The mod multiplies the number of observation ticks since the fire by the latest interval. Changing the interval from 0.05 s to 0.20 s made a four-tick-old event jump from 0.20 s to 0.80 s with no time advancing. A steady 0.01 s interval expires events after about 0.4 s of nominal waits, while 0.20 s retains them for about 8 s of nominal waits. Python still normalises to two seconds. Changing speed alone requires no speed multiplier because Lua's `wait` uses the world clock. The scheduler resumes on updates after the deadline, so nominal waits can nonetheless undercount game time, particularly when the update step grows relative to the polling period. See `Scripts/Main.lua:19-34`, `:428-438`, `:611-635` and the recorded calibration in `collab/STATUS.md:19`.

**Fix** Stamp admitted events with `_worldTime`, subtract from the same clock at snapshot time, and apply the two-second cutoff to the measured difference. Keep the map-load reset. Test an interval change, uneven world-clock steps and expiry at a fixed world age.

### 4. An already-open keepsake or Mirror menu bypasses its House handler

**Where** `scripts/run_agent.py:168-199`, `:274-283`.

**Failure** If the runner attaches with the rack open, or the rack stays open after a menu or close timeout, the generic overlay path takes over. It taps Interact repeatedly and never calls the rack handler, so the survey and run can stall. A fake bridge returning a persistent `AwardMenu` produced only repeated Interact calls. The rack binds its close control to Cancel. An already-open Mirror follows the same generic branch even though its macro can resume from that menu. See `Scripts/AwardMenuScripts.lua:138-158`, `agent/macro/house.py:163-194` and `agent/macro/mirror.py:63-84`.

**Fix** Route an open `AwardMenu` or `MetaUpgrade` to its owning House handler before the generic overlay branch. Allow one normal selection or spending attempt per visit. If an action may already have happened, recover by closing and observing the menu, with no second gift or purchase attempt. Keep dialogue handling separate.

### 5. The House latches use a run counter and consume a visit before input is possible

**Where** `scripts/run_agent.py:152-156`, `:168-199`, `:215-223`, `mod/AgentBridge.lua:308-312`, `:575-586`.

**Failure** The same `runs_started` value spans every entry to a House map until the next counted run. The game provides return doors from the courtyard to the bedroom and the bedroom to the Hall. A room re-entry before a new run therefore skips its action. The guard is also set before the macro sees a stable frame. A transient pause, incomplete room setup or failed walk can consume the whole visit. A fake rack failure was followed immediately by departure. At the other end, a LoadScreen frame can satisfy the existing run-start test, even though it has no `room` field. A fake courtyard-to-loading-to-courtyard sequence used up a one-run budget with no confirmed run. See `Scripts/DeathLoopData.lua:3949-3958`, `:6250-6256` and the transition input block in `Scripts/DeathLoop.lua:230-242`, `:272-282`.

**Fix** Track a stable House map entry or map-load generation separately from the run budget. Wait for a usable observation before reserving the action. Allow bounded retries for outcomes that prove no action occurred, and retain a latch after any possible gift or purchase. Count a run on a confirmed new-run transition and a valid non-House observation. Test an ordinary cycle, a same-count re-entry, a transient setup failure and a loading-only transition.

## Minor

### 6. Unseeded Hall-first sessions defer gifting

**Where** `scripts/run_agent.py:154-156`, `:171-189`, `agent/macro/house.py:97-111`, `collab/handoffs/013-gifts-and-keepsakes.md:34`.

**Failure** This is the documented fail-closed path. A Hall-first invocation starts with unknown ownership and the next Hall visit is reached only after a rack survey. With `--runs 1`, it stops at that next Hall visit before gifting. Repeating one-run invocations started in the Hall repeats the deferral. The offline route probe confirmed that a successful rack survey reaches the next Hall gift call when the run budget allows it.

**Fix** If a Hall-first session must be able to gift before its first run, seed from a fresh visible rack survey for the active profile or survey the rack and return through the House. Keep the unknown-ownership guard.

## Checks

- The attack registration matches the game's unfiltered subscriber form. `OwnerTable.ObjectId` and `ProjectileName` have stock precedents. The callback uses protected reads, writes only its own tables, and neither yields nor invokes a weapon or RNG operation. Static review found no gameplay mutation. `OnAnyLoad` clears both collections and `AgentBridge` is already in `SaveIgnores`. See `mod/AgentBridge.lua:14-19`, `:731-753`, `Scripts/Combat.lua:2259-2287` and `Scripts/Main.lua:1019-1035`.
- The vertical sign is correct for a valid world angle. The game uses the same cosine and negative sine in `CalcOffset`, and the offline probe gave up for 90° and down for 270°. Attack recency uses the same ordering as the corresponding base enemy and trap slots. See `Scripts/UtilityScripts.lua:962-969`, `agent/env/observations.py:59-71`, `:111-121`, `:137-153`.
- The stock `GetUseData` has one return value and a single call site in the use-prompt path. The wrapper calls it once, forwards extra arguments, isolates observer errors, and returns the same object. The cache is local. An offline Lua probe forced the observer to error and verified the original result still came back. See `mod/AgentBridge.lua:438-455` and `Scripts/UIScripts.lua:2120-2178`, `:2214-2238`.
- The ordinary uninterrupted route latches each helper once, passes owned keepsakes from a completed survey to the next eligible Hall visit, and invalidates the cache after a possible Nectar press. No repeated purchase or gift was found on that path. `_house_log` appends one result per invocation, including failed attempts. See `scripts/run_agent.py:139-143`, `:176-199` and `agent/macro/house.py:134-160`.
- `/opt/miniconda3/bin/conda run -n hades python -m pytest -q -p no:cacheprovider tests` passed all 149 tests. `/opt/miniconda3/bin/conda run -n hades python -m pyflakes scripts agent` was clean. Focused probes used Lua and fake bridges only. Live engine event payloads, rendering, menu timing and input remain unverified.

## Lead disposition (Claude, 2026-11-26)

1. Critical, fixed: an attack is recorded only for owners listed as enemies or traps in the latest snapshot (`AB.VisibleAttackers`), so lava tiles, allies, charmed units and auxiliary owners never set `firedAgo`. Shot rows moved from `obs` to `info` (logging only); the encoder's shot block was removed (attack block 12 floats, observation 195). Tests cover a listed attacker, an unlisted owner with a position, and the hero. Residual risk: a listed enemy firing a weapon with no drawn cue; to be checked in clips during the live session.
2. Major, resolved by 1: no shot direction or origin reaches the policy.
3. Major, fixed: events are stamped with `_worldTime` and aged/expired against it (2 s); a test changes `AB.Interval` mid-flight.
4. Major, fixed: an open `AwardMenu` or `MetaUpgrade` is routed to `equip_keepsake` / `spend_darkness` (both resume from an open menu) while that visit's action is pending, otherwise closed with Cancel.
5. Major, fixed: `agent/macro/house_route.py` (`HouseVisits`) starts a visit on every House map change, so re-entered rooms act again; actions wait for `ready_for_action` (HUD drawn, no overlay, no engine menu); retryable "nothing happened" outcomes get one retry, possible gifts/purchases latch. A run is counted only when a non-House room with a name appears (never a loading frame). Tests in `tests/test_house_route.py`.
6. Minor, accepted: Hall-first sessions defer gifting until after a rack survey (fail-closed). Documented here.
