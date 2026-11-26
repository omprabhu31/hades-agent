# 007 Review: bridge v2, pickups, macro

**Verdict — Changes needed.** One critical hidden-reward leak, and several major observation and macro failures. The speed helper does not cancel a hit-pause, and it does not put the simulation back above 1.0 after an evaluation has set speed to 1.0. It does drop a training speed back to 1.0 after the first short hit-pause while still reporting the training value.

Read-only. Game not launched, no input sent, game folder not modified. `conda run -n hades python -m pytest tests/test_bridge_mod.py tests/test_macro_rules.py -q` — 28 passed. Those tests stub the shapes below, so a pass does not cover them.

## Critical

### C1. Chaos's hidden door reward is exported as the real reward

[mod/AgentBridge.lua:206](/Users/om-prabhu/projects/hades-agent/mod/AgentBridge.lua:206)

The preview uses `HasHeroTraitValue("HiddenRoomReward")` ([RoomPresentation.lua:1604](/Users/om-prabhu/Library/Application Support/Steam/steamapps/common/Hades/Game.macOS.app/Contents/Resources/Content/Scripts/RoomPresentation.lua:1604)). That is true when a trait has the property, which is the curse `ChaosCurseHiddenRoomReward` (`HiddenRoomReward = true` in TraitData.lua:42496). The bridge calls `HeroHasTrait("HiddenRoomReward")`, which looks up a trait **named** `HiddenRoomReward` ([TraitScripts.lua:624](/Users/om-prabhu/Library/Application Support/Steam/steamapps/common/Hades/Game.macOS.app/Contents/Resources/Content/Scripts/TraitScripts.lua:624)). No trait has that name, so the check is false, `DebugAssert` runs on a missing `TraitData` key (TraitScripts.lua:628), and the section continues.

Failure: with that curse active the door icon is `ChaosPreview` (a question mark) and the policy still receives `reward` = `ChosenRewardType` and `god` = `ForceLootName`. It can walk to the best reward the player is not allowed to see. A fresh save never has the curse, which is why the live door check did not catch this.

Fix: call `HasHeroTraitValue("HiddenRoomReward")`. Export `reward = "Hidden"` and omit `god` and `gods`.

## Major

### M1. HUD numbers and hidden traits are exported while they are not drawn

[mod/AgentBridge.lua:112](/Users/om-prabhu/projects/hades-agent/mod/AgentBridge.lua:112)

`obs.hud` records `ShowingCombatUI`, and the hero table is filled either way. The combat HUD hides itself after the player stands still (`ShowingCombatUI = nil` at UIScripts.lua:284, `HideAfterDelay` at UIScripts.lua:259). HP, max HP, obols, cast ammo, call pips and the weapon name are then not on screen. The reference says not to export HUD fields in that case.

`hero.traits` lists every entry, including `Hidden = true` traits such as `RoomRewardMaxHealthTrait` (TraitData.lua:5574). The tray skips those (TraitTrayScripts.lua:80). Traits that do not fit are drawn as a `+N` count (`GetNumHiddenTraits`, TraitTrayScripts.lua:1154), not by name.

Failure: standing still, the policy still reads exact ceiled HP and the full build, including traits a human cannot name. Opening the boon menu is fine for the HUD (`PersistCombatUI = true` at UpgradeChoice.lua:9). Auto-hide is the common case.

Fix: export HP, money, ammo, call pips and weapon only while `ShowingCombatUI` is true, or while a screen that shows those widgets is open. Export a trait only when it is drawn (not `Hidden`, and on the tray or in `RecentTraits`). Export the `+N` count for the rest. Keep numeric trait values out.

### M2. Boon `name` is the god, repeated on every card

[mod/AgentBridge.lua:266](/Users/om-prabhu/projects/hades-agent/mod/AgentBridge.lua:266), [agent/macro/rules.py:68](/Users/om-prabhu/projects/hades-agent/agent/macro/rules.py:68)

`PurchaseButton.UpgradeName` is set to `lootData.Name` (UpgradeChoice.lua:86 and UpgradeChoice.lua:368), for example `ZeusUpgrade` or `WeaponUpgrade`. The trait id is `button.Data.Name`. The card's visible title comes from `upgradeTitle`, not from `UpgradeName`.

`choose_boon_option` looks for `Weapon`, `Secondary` and `Rush` inside `name`. Every Zeus card is `ZeusUpgrade`, so the slot hint is 0 and the pick is rarity only. Every hammer card is `WeaponUpgrade`, so the hint is 3 on all of them and still does not separate hammers.

Failure: the stated "attack, then special, then dash" order never sees an attack boon. The unit test stubs `UpgradeName = "ZeusWeaponTrait"` ([tests/test_bridge_mod.py:236](/Users/om-prabhu/projects/hades-agent/tests/test_bridge_mod.py:236)), so it locks the wrong field in.

Fix: export `name = b.Data and b.Data.Name`, `slot = b.Data and b.Data.Slot`, and for `Type == "TransformingTrait"` the blessing name on `b.Data.OnExpire.TraitData`. Keep exporting `rarity` from `b.Data.Rarity`. Do not export the rest of `Data` (processed numbers). Point the test at that shape.

### M3. Withheld boon cards are offered to the picker

[mod/AgentBridge.lua:262](/Users/om-prabhu/projects/hades-agent/mod/AgentBridge.lua:262), [agent/macro/driver.py:74](/Users/om-prabhu/projects/hades-agent/agent/macro/driver.py:74)

`blockedIndexes` still get a `PurchaseButton` (UpgradeChoice.lua:290). The game calls `UseableOff` and, 0.25s later, plays `BoonSlotLocked` (EventPresentation.lua:1169). At Heat 0, `CalcNumLootChoices` is 3 (TraitScripts.lua:1538), so this happens when more than three options were rolled. Each rank of Approval Process (`ReducedLootChoicesShrineUpgrade`) locks another card. The bridge exports every button that exists, including `Data.Rarity`. `choose_boon_option` can return the locked card. `click_ui` clicks it. The press does nothing and the menu stays open. `pick_boon` still returns that choice.

Fix: skip a button when `comps["PurchaseButton"..i.."Lock"]` exists. Until the lock object is spawned (the 0.25s presentation wait), do not treat the menu as ready (see M6).

### M4. Training speed falls to 1.0 after a hit-pause and the report stays at the training value

[mod/AgentBridge.lua:310](/Users/om-prabhu/projects/hades-agent/mod/AgentBridge.lua:310), [mod/AgentBridge.lua:369](/Users/om-prabhu/projects/hades-agent/mod/AgentBridge.lua:369)

`AddSimSpeedChange` / `RemoveSimSpeedChange` (CombatPresentation.lua:2124-2136) match the reference. The bridge writes only when the table is empty and (`SpeedDirty` or `WasBusy`). It does not write while `MapState.SimSpeedChanges` is non-empty, so it does not overwrite the pause fraction.

Weapon hit-pauses are shorter than the poll. The sword's hold is `ScreenPreWait = 0.02` then a remove (WeaponData.lua:76-77). `RemoveSimSpeedChange` sets the engine to 1.0 when the table empties. A pause that starts and ends between two `wait(0.05)` wakes never sets `WasBusy`, so the training fraction is not put back. `obs` still carries `speed = AB.Speed` (AgentBridge.lua:372).

Evaluation: once a `speed` command has set `AB.Speed` to 1.0 and the apply has run, `SpeedDirty` is clear and the loop stops calling `MaintainSpeed`. Later pauses return the engine to 1.0 on their own. That path does not leave the game sped up. A milestone that never sends `speed` 1.0 stays at the training fraction until the first missed pause, then sits at 1.0 while the log says otherwise.

Fix: while `AB.Speed ~= 1` and the table is empty, re-apply on each poll, not only on the empty transition. Keep the "do not write while the table is non-empty" guard so a pause that is actually observed still runs.

### M5. Dialogue, fountains and a single interact stall or fake a room change

[agent/macro/driver.py:82](/Users/om-prabhu/projects/hades-agent/agent/macro/driver.py:82), [agent/macro/driver.py:94](/Users/om-prabhu/projects/hades-agent/agent/macro/driver.py:94)

`PlayTextLines` freezes the unit and disables `Use` and `Move` (UIScripts.lua:2558, Narrative.lua:36). Lines advance on `Confirm`, `Select` or `ContinueText` (Narrative.lua:700), not on the Use control `interact` taps. Choices are `ButtonDialogueChoice` obstacles (Narrative.lua:656) and are not in `obs.screens` or `boonMenu`. `walk_to` holds a direction against a frozen body until the timeout. One `interact` does not finish the conversation.

Fountains set `BlockExitUntilUsed` (ObstacleData.lua:683) and are stored on `ActivatedObjects` from `SetupObstacle` (RunManager.lua:2471). They are not in `LootObjects` or the `ConsumableItems` group, so `collect_pickups` never walks to them. Exits stay unlit. `take_door` returns None. A reprieve room is a dead end.

`take_door` returns the door after `walk_to` and one `interact`, with no check that the room changed or that a use prompt was up. A press eaten by dialogue, or a stop outside the prompt, is reported as a taken door.

`collect_pickups` interacts with every pickup. Charon's world stock is in those tables and has a price (StoreScripts.lua:418, Interactables.lua:728). Cost is not in the observation, so the driver buys it.

Fix: if `Dialog` is in `screens`, stop walking and drive the advance controls; export choice button positions while `GameState.WaitingForChoice` is set. Treat fountains, wells and other `BlockExitUntilUsed` obstacles as interactables once they are drawn. Have `take_door` succeed only after `room.name` changes or the load screen appears. Export `cost` when `UpdateCostText` has drawn it, and skip a purchase the agent cannot see a price for.

### M6. The boon click lands before the menu is listening

[agent/macro/driver.py:74](/Users/om-prabhu/projects/hades-agent/agent/macro/driver.py:74)

`OpenUpgradeChoiceMenu` sets `ActiveScreens.BoonMenu` immediately (UpgradeChoice.lua:9), builds buttons, then `wait(0.5)` before `HandleScreenInput` (UpgradeChoice.lua:73-79). That wait is there to ignore accidental input. `HandleScreenInput` selects with `NotifyOnInteract` (UIScripts.lua:2627). `pick_boon` calls `click_ui` on the first observation that has button coordinates, which exists during that wait. The click is dropped, the function returns the choice, and the menu is still open.

`collect_pickups` sleeps 0.8s of wall time after interact and then returns. At speed 1.0 the game's 0.25s plus 0.5s waits consume most of that, so the caller's `pick_boon` is still inside the ignore window or only just out of it.

Fix: click only once `boonMenu` options have been stable and `screen.KeepOpen` would be true. The bridge can export `ready` from `ScreenAnchors.ChoiceScreen.KeepOpen` (set at UpgradeChoice.lua:77, after the wait). Retry until `BoonMenu` leaves `screens` or the timeout fires. Do not report success on the click alone.

## Minor

### m1. `exitsUnlocked` flips before the doors light

[mod/AgentBridge.lua:143](/Users/om-prabhu/projects/hades-agent/mod/AgentBridge.lua:143)

`CurrentRoom.ExitsUnlocked = true` at the start of `UnlockRoomExits` (RoomManager.lua:4801), then `wait(0.4)` and only later `CreateDoorRewardPreview` and `ReadyToUse` (RoomManager.lua:4930-4932). For that stretch `obs.room.exitsUnlocked` is true while every `door.lit` is still false. The reward is not included. Drop `exitsUnlocked` and use `door.lit`.

### m2. `room.combat` goes false while enemies are still on screen

[mod/AgentBridge.lua:145](/Users/om-prabhu/projects/hades-agent/mod/AgentBridge.lua:145)

`IsCombatEncounterActive` returns false when any timer block is set, except `ThanatosEncounter` and `SurvivalEncounter` (RoomManager.lua:3705-3714, EncounterData.lua:12). Opening a menu or dialogue clears the flag. Enemies remain in `obs.enemies`. `AlwaysInCombat` is only on test rooms (RoomData.lua:488). Treat the flag as a hint, and treat live enemies and `door.lit` as the visible state. It does not reveal future spawns; `info.remainingSpawns` is the right place for that and is already outside `obs`.

### m3. Devotion gods are read off the wrong table

[mod/AgentBridge.lua:211](/Users/om-prabhu/projects/hades-agent/mod/AgentBridge.lua:211)

The two icons are `room.Encounter.LootAName` and `room.Encounter.LootBName` (RoomPresentation.lua:1614, assigned at RunManager.lua:505-511). `room.LootAName` is never set, so `gods` is `[null, null]` on a door whose icons are visible. The reward string `"Devotion"` is still right.

### m4. Consumables are positions without a type

[mod/AgentBridge.lua:241](/Users/om-prabhu/projects/hades-agent/mod/AgentBridge.lua:241)

`GetIds({ Name = "ConsumableItems" })` matches `AddToGroup` (Interactables.lua:952). The sprite is drawn. `HideWorldText` only suppresses the floating label (ConsumableData.lua:48, Interactables.lua:958). The observation has no name, so a heart, a coin and darkness are the same kind of point. Export the consumable `Name` (the icon id). Leave `HealFraction` and similar numbers out until the use prompt is up.

`blocking` is `ActivatedObjects[id] ~= nil`. That is set when the pickup is spawned (RoomManager.lua:2871), before the player has walked to the door and seen `ExitBlockedByBoon` or the direction hint (EventPresentation.lua:1197). A floor boon is visibly the thing that gates the exit, so this is a small early tell, not a second reward. Export it only for objects whose block text is the one the door would show.

### m5. `GetIds` is walked with `ipairs`

[mod/AgentBridge.lua:238](/Users/om-prabhu/projects/hades-agent/mod/AgentBridge.lua:238)

Every script call site uses `pairs(GetIds(...))`. A non-sequence return yields an empty consumable list and no `obs.errors`. Use `pairs`.

### m6. A few drawn values are missing

Not leaks. The rally segment (`RallyHealth.Store`, UIScripts.lua:511), rail ammo when `ScreenAnchors.GunUI` is set (UIScripts.lua:1005), the elite skull from `RewardPreviewIcon` (RoomPresentation.lua:1680), the boon card's description text, and the trait stack number when `UpdateTraitNumber` has drawn it. Charmed units are omitted (AgentBridge.lua:166) even though they are on screen.

## Nit

### n1. A short log drops its first line

[agent/bridge/tail.py:27](/Users/om-prabhu/projects/hades-agent/agent/bridge/tail.py:27)

Seeking back 200KB and then `readline()` discards a complete first line when the file is shorter than that. The next poll only sees later lines. At 20 Hz this only bites a brand-new log. Sequence numbers are epoch milliseconds (`send_command` in game.py:96), so an old ack in the backfill will not match a new command.

### n2. The sidestep is replaced on the same iteration

[agent/macro/driver.py:51](/Users/om-prabhu/projects/hades-agent/agent/macro/driver.py:51)

After 0.25s of the rotated heading, the loop applies the straight heading before the next position sample. Corners get a short nudge and then the same wall push. Apply the sidestep for the burst and skip the direct heading until the next sample.

### n3. `god` is copied for rewards that have no god icon

[mod/AgentBridge.lua:210](/Users/om-prabhu/projects/hades-agent/mod/AgentBridge.lua:210)

`ForceLootName` is assigned for boons (RunManager.lua:473). Set `god` only when `reward == "Boon"`.

## Test gaps

The 28 passing tests never load the game scripts.

- `test_door_reward_only_when_lit` does not include a hero trait with `HiddenRoomReward = true`, and it would not call `HasHeroTraitValue`.
- `test_boon_menu_lists_displayed_buttons` sets `UpgradeName` to the trait id. The game sets it to the loot id.
- No case with `ShowingCombatUI` nil, a `Hidden` trait, a `PurchaseButton` lock, or devotion `Encounter.LootAName`.
- `test_speed_reasserted_after_hit_pause` only checks a pause the helper is called during. It does not check a pause that ends between polls, or that `speed` in the payload matches the engine.
- No test calls `Macro.walk_to`, `pick_boon`, `collect_pickups` or `take_door`.

## Unknowns

1. Whether `BoonSlotLocked` covers the card title or only the icon. The title text box is created for locked indexes anyway (UpgradeChoice.lua:427). If the overlay hides the words, M3 is also a hidden-info leak of that card's rarity and, once M2 is fixed, its name. If the words stay readable, M3 is a dead click only.
2. Whether `GetLocation` on a `UseScreenLocation` id equals the X,Y passed to `CreateScreenComponent`. Those components are spawned in the 1920 by 1080 layout (UIScripts.lua:2357, UpgradeChoice.lua:279). The game orders dialogue buttons by `GetLocation().Y` (TraitTrayScripts.lua:548) and never prints both the creation coordinates and the readback. `ui_to_window` letterboxes that layout into the window; the 1512 by 982 bars in STATUS match the formula, and `test_ui_to_window_letterbox` checks the centre. No boon menu has been captured live, so a constant offset would send every click wrong.
3. The engine's default interact distance when `InteractDistance` is nil (RunManager.lua:2495 sets it only if present). Door radius 120 succeeded once in a Tartarus room (collab/LOG.md). Radius 60 for pickups, and Asphodel boats (`ExitThroughCenter` is not set on `AsphodelBoat01b`), are unmeasured.
4. Whether `AdjustSimulationSpeed` survives `LoadMap` (reference unknown 8). `OnAnyLoad` sets `SpeedDirty` only when `AB.Speed ~= 1` (AgentBridge.lua:403). An evaluation already at 1.0 will not correct an engine that stayed fast across the load.
5. Whether a left click (`attack` in controller.py:21) fires `NotifyOnInteract` on a boon button. Main-menu clicks worked (STATUS). The boon menu was not tried. Any WASD press during the menu sets `UseMouse` false (MetaUpgrades.lua:382) and the menu never sets it back. `walk_to` releases movement before it returns; a press that arrives after `HandleWASDInput` is listening would disable the mouse for the rest of the menu.
6. `GetIds` return shape (m5).
7. Whether `CurrentPhase` changes before the phase banner is visible. Not traced past the field write.

## Checked, no defect found

- Unrevealed rewards stay off unlit doors (`ReadyToUse`). `info.remainingSpawns`, `info.superMeter`, `info.enemyHealth` and `info.heroHealth` stay out of `obs`. `policy_obs` returns `d.obs` only (tail.py:60, game.py:190).
- `GetWeaponMaxAmmo({ Id, WeaponName = "RangedWeapon" })` matches UIScripts.lua:931. `IsSuperValid()` is the zero-argument function in ShoutScripts.lua:1, and raw `SuperMeter` stays in `info`.
- `ScreenAnchors.ChoiceScreen` is cleared at UpgradeChoice.lua:998, after `OnScreenClosed` has already removed `BoonMenu` (line 975). The death early-return at line 980 leaves the anchor and still clears the flag. The bridge requires both, so a stale anchor is not exported. `ActiveScreens[flag]` is a table while open and `nil` when closed (UIScripts.lua:2431, 2454).
- Reroll: `CanBeRerolled` is set only when Fated Authority is selected (RoomManager.lua:4984). The bridge also requires `NumRerolls > 0`, which matches the use-text gate (UIScripts.lua:2039). The fresh-save sparkle noted in STATUS is closed by those two conditions.
- `DisableTrap` sets `DisableAIWhenReady` and `DisabledAnimation` together (RoomManager.lua:5931). The trap `disabled` flag matches the retracted sprite.
- `GetRunDepth` is the chamber count the reference marks visible once the player is in the room. Left as exported.
- `ui_to_window` uses the 1920 by 1080 UI space those screen components are created in, letterboxed into the window. World movement uses `atan2(-dy, dx)`, which matches the calibration (y down, angles equal screen angles).

## Lead disposition (Claude, 2026-11-26)
- Critical (HiddenRoomReward): fixed, uses `HasHeroTraitValue("HiddenRoomReward")`; test added.
- HUD auto-hide: HUD numbers and the trait tray are dropped from `obs.hero` while `ShowingCombatUI` is false; `Hidden` traits are never exported; test added.
- Boon names: fixed before this review landed (`b.Data.Name`, loot kept as `god`); verified live ("AthenaSecondaryTrait").
- Approval Process: options carry `locked` (from `UpgradeOptions[i].Blocked`); the picker skips locked cards; test added. Live check pending (needs the mirror upgrade).
- Speed: with a training speed set, re-asserted every tick outside a hit-pause; never written during a pause; a return to 1.0 is applied once; tests updated.
- Dialogue: advanced with a left click (verified live). Exit-blocking fountains and other non-pickup blockers: open. `take_door`: the runner already checks the room changed before counting it.
- Boon click timing: runner waits 0.8 s after the menu opens.
