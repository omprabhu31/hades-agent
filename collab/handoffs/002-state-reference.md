# 002: Reference for reading the visible game state from Hades's Lua scripts
Status: DONE
Owner: Grok

## Goal
A written reference that tells the bridge-mod author exactly how to read each piece of *on-screen* game state from Lua inside the running game, with file:line citations into the game's own scripts.

## Context
- Read `AGENTS.md` first, especially hard rule 5 (visible information only).
- Game scripts (read-only): `~/Library/Application Support/Steam/steamapps/common/Hades/Game.macOS.app/Contents/Resources/Content/Scripts/*.lua` (Lua 5.2). Engine C functions callable from Lua are listed in `docs/engine_cfuncs.txt`; their behaviour is only knowable from how the scripts call them.
- Established facts: `CurrentRun.Hero` has `ObjectId`, `Health`, `MaxHealth`; `GetLocation({ Id = id })` returns a table with `X`, `Y`; `ActiveEnemies` is a table keyed by object id; `thread(fn)` and `wait(seconds)` run code each game tick; `OnAnyLoad{...}` hooks room loads; `GetTopScreenName()` exists.
- The bridge mod will be read-only. It must never change game state.

## Scope
May create: `docs/game_state_reference.md`, append to `collab/LOG.md`. Must not edit any other file, must not touch the game folder, must not launch the game or send any input.

## What to document (for each: how to read it, where the scripts do it, caveats, and whether it is VISIBLE on screen to a human or HIDDEN)
1. Hero: position, facing/aim, velocity, HP and max HP, death-defiance charges, cast ammo (bloodstones) count, call (god gauge) meter, dash availability if shown, active status effects shown on the HUD, money/obols, current weapon and aspect, equipped boons (trait list) and keepsake.
2. Enemies: how to enumerate live enemies in the room; per enemy: name/type, position, velocity, health and armour as the health bar shows them (fraction), elite/shield modifiers that are drawn, boss phases; how to tell an attack telegraph is being drawn (e.g. warning decals/animations), if feasible.
3. Projectiles and hazards (traps, spikes, magma, enemy AoE indicators): any way to enumerate their ids, positions, velocities, owner (enemy or hero). Say clearly if there is no enumeration API and what hooks (e.g. `OnProjectileDeath`, spawn functions) could track them.
4. Room and run: current room name, biome, depth/room number, encounter state (combat active, cleared), exit doors and their visible reward icons (boon god, pom, hammer, coin, etc.), whether doors are unlocked, Charon shop, wells, fountains, chaos gates, wall/breakable pots, interactable objects with positions and type (`Use` prompts).
5. Menus and screens: how to know which screen is open (`GetTopScreenName`, `ScreenAnchors`, etc.); boon choice screen contents (offered boons with name, rarity, and the god), Daedalus hammer choices, shop items and prices, Mirror of Night/Contractor/House screens, dialogue boxes and choice prompts, run-end/death screens, pause menu. For each, how a script detects that it opened and closed.
6. Events useful for reward only (may be HIDDEN): hero damaged (amount), enemy killed, room cleared, run started, death, boss killed, run escaped (beat Hades).
7. Game speed: what `AdjustSimulationSpeed` does (it is called in `CombatPresentation.lua` around line 2129) and whether anything in the scripts resets it (room transitions, menus).
8. Coordinate system: world units vs screen; camera position/zoom functions, so world positions can be mapped to the cursor position on screen for aiming.

## Acceptance criteria
- `docs/game_state_reference.md` exists, organised by the sections above, each item with a code snippet, `File.lua:line` citations, and a VISIBLE/HIDDEN label.
- Anything you could not determine is listed under "Unknowns" rather than guessed.

## Report

Covered, in [docs/game_state_reference.md](docs/game_state_reference.md), all eight sections. Each item has a Lua snippet or a cited call site, a `File.lua:line` citation into the game scripts, and a VISIBLE or HIDDEN label. The game folder was not edited and the game was not launched.

1. Hero. `GetLocation` (`.X`, `.Y`), `GetAngle` (facing degrees), `GetVelocity` used as a scalar speed. HUD HP is `math.ceil` of `Health` and `MaxHealth` (`UIScripts.lua:499-518`); rally is the white segment. Death Defiance is `LastStands` drawn by `UpdateLifePips` (`UIScripts.lua:392`); heal amounts on a charge are HIDDEN. Cast ammo is `GetWeaponProperty` `"Ammo"` and `GetWeaponMaxAmmo` on `RangedWeapon`, plus the rail magazine on `GunWeapon`. The God Gauge is pips (`SuperMeterLimit` / `SuperCost`); the numeric textbox is commented out, so raw `SuperMeter` is HIDDEN. No dash meter is drawn. Status icons that are actually drawn are listed; `ActiveEffects` must not be exported wholesale. Obols are `CurrentRun.Money`. Weapon is `GetEquippedWeapon` over `HeroMeleeWeapons` (the six weapons at `WeaponSets.lua:39-47`). Aspect is `GetWeaponUpgradeTrait`; index 1 often has no trait name. Boons and the keepsake are `CurrentRun.Hero.Traits` as the tray draws them (`Slot`, icon, rarity, stack). Trait numbers are HIDDEN unless the tooltip is open.

2. Enemies. `ActiveEnemies[objectId]` (`RoomManager.lua:4198`, cleared `Combat.lua:3310`, replaced on `OnAnyLoad` at `Combat.lua:3868`). Foes are `RequiredKill` and not dead, charmed, a trap, or an allied summon. Bar fraction: hit shields fill the bar and hide HP; armour shows `HealthBuffer/MaxHealthBuffer`; otherwise `Health/MaxHealth`. Boss bars show the fraction and a name, not a number. Elite badges and shield icons are VISIBLE. `CurrentPhase` matches the Hades phase presentation (`CombatPresentation.lua:2678-2710`); Theseus and Asterius use `currentRoom.CurrentPhase`. Telegraphs are drawn inside the AI thread (`EnemyAI.lua:100-123`) and are not stored as a flag.

3. Projectiles and hazards. No enumeration API, no projectile id, no live position or velocity after spawn. Track spawns with `OnWeaponFired` and deaths with `OnProjectileDeath`. Do not call `ExpireProjectiles`. Traps are enemies with `ToggleTrap`. Pots are `MapState.ActiveObstacles` with `HideHealthBar`; their HP is HIDDEN.

4. Room and run. `CurrentRun.CurrentRoom.Name` and `RoomSetName`, `GetRunDepth`, `GetBiomeDepth`. Combat over is `Encounter.Completed` and not `IsCombatEncounterActive`, plus `door.ReadyToUse` for the lit door. Door reward icons are VISIBLE only after `CreateDoorRewardPreview` (`ReadyToUse` at `RoomManager.lua:4932`). Reading `ChosenRewardType` before that leaks an unrevealed reward. `HiddenRoomReward` draws `ChaosPreview`; export `"hidden"`. Charon wares, wells, fountains, and the Chaos gate are documented. The gate does not draw its destination reward.

5. Screens. Lua overlays are `ActiveScreens` (`OnScreenOpened` / `OnScreenClosed`). The pause menu is the engine screen `"PauseScreen"` via `GetTopScreenName`, not `ActiveScreens`. Boon, hammer, Chaos, shop, sell, mirror, pact, contractor, keepsake, dialogue, and run-clear open and close paths are cited, including which fields on the open buttons are VISIBLE.

6. Reward-only events, all HIDDEN as policy input: `DamageHero`, `KillEnemy` then `Kill`, encounter completion, `StartNewRun`, `KillHero` / `HandleDeath` (`Hero.IsDead`, `HandlingDeath`; there is no Lua `OnPlayerDeath` block), boss kill (`IsBoss`), `RecordRunCleared` (`CurrentRun.Cleared`).

7. Speed. `AddSimSpeedChange` (`CombatPresentation.lua:2124`) calls `AdjustSimulationSpeed` and ignores a non-priority add while any change is active. `RemoveSimSpeedChange` sets `Fraction = 1.0` only when the table is empty. `OnAnyLoad` sets `MapState = {}` at `Combat.lua:3875` and `MapState.SimSpeedChanges = {}` at `Combat.lua:3876`, and does not call `AdjustSimulationSpeed`. Menus do not reset it in Lua.

8. Coordinates. World `X`/`Y` from `GetLocation`. UI layout is 1920 by 1080 (`UIData.lua:2496-2500`), which is not a camera mapping. Camera lock, `ZoomFraction`, `FocusCamera`, `AdjustZoom`, and `GetCameraZoom` are cited. No world-to-screen function and no mouse world position.

Could not determine (listed under Unknowns, not guessed): a live telegraph bit; projectile ids and positions after spawn; return shapes of `GetMapThings`, `GetMapThingsByType`, `GetEffectTimeRemaining`, `GetWeaponChargeFraction`, `GetUnitProperty`, and `GetThingDataValue`; dash cooldown remaining and any cooldown ring; whether `GetVelocity` can return a table; the world-to-screen scale; mouse world position; whether the engine resets `AdjustSimulationSpeed` on `LoadMap` or pause; `GetTopScreenName` during a Lua overlay; rolled boon options dropped by `blockedIndexes`; exact enemy HP under a bar that prints no number; future spawns, unrevealed rewards, Chaos gate contents, and unspawned shop items; `InvulnerableFlags`; mirror ranks while the mirror is closed. Trap names, effect names, and pot names were sampled, not fully enumerated.

Bridge design. Poll `CurrentRun`, `ActiveEnemies`, `RequiredKillEnemies`, `MapState.ActiveObstacles`, and `OfferedExitDoors` on a `thread` / `wait` loop. Subscribe to `OnAnyLoad`, `OnWeaponFired`, `OnProjectileDeath`, `OnEffectApply`, and `OnEffectCleared` only for lists a poll cannot see. Do not wrap `Damage`, `Kill`, or `AddSimSpeedChange`, and do not write those tables. Export ceiled hero HP, the bar fraction and shield or armour mode, positions, facings, speeds, door icons after `ReadyToUse`, and the open screen's buttons. Keep exact enemy HP, spawn queues, AI timers, unrevealed rewards, and raw `SuperMeter` in the reward log only. Re-apply a training speed after each load and whenever `SimSpeedChanges` becomes empty, and leave speed at `1.0` while that table is non-empty. Evaluation stays at `1.0`. Do not read `ChosenRewardType` before `door.ReadyToUse`. Do not export `ActiveEffects` wholesale. Aim from hero facing; do not invent a pixel mapping. `AgentBridge.lua` already in the Scripts folder was not used as a source and was not edited.
