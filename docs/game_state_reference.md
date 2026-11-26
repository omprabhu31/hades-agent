# Reading on-screen game state from Hades Lua

Read-only reference for the bridge mod. Every item is labelled **VISIBLE** (a human can see it, so it may reach the policy) or **HIDDEN** (reward and logging only). Where a stored number is finer than the drawing, the visible form is the one to export.

Scripts are Lua 5.2 under `Game.macOS.app/Contents/Resources/Content/Scripts/`. Engine calls are the names in `docs/engine_cfuncs.txt`. Their behaviour below is only what the scripts do with them. This file does not change the game.

## How a bridge should read

Poll. Do not wrap or replace `Damage`, `Kill`, `AddSimSpeedChange`, or any other game function. The game already registers several subscribers for the same engine event (`OnWeaponFired` in `Combat.lua` and `ShoutScripts.lua`, `OnAnyLoad` in `Combat.lua` and `DeathLoop.lua`), so an extra subscriber in the mod is the pattern the scripts use. A poller is still the safe default, because a subscriber that waits or mutates `triggerArgs` would change gameplay.

```lua
thread(function()
    while CurrentRun ~= nil and CurrentRun.Hero ~= nil do
        -- read only; never write CurrentRun, ActiveEnemies, MapState, or call Fire/Damage/Teleport
        wait(0.05)
    end
end)
```

`thread` and `wait` are the engine calls the scripts use for per-tick work (`RoomManager.lua` passes `RoomThreadName` as the second argument to `wait` so the wait dies with the room). `OnAnyLoad` fires on every map load and wipes the per-room tables (`Combat.lua:3864`).

Globals the poller needs:

| Name | What it is |
| --- | --- |
| `CurrentRun.Hero` | The player unit. `ObjectId`, `Health`, `MaxHealth`, `Traits`, `Weapons`, `LastStands`, `SuperMeter`, `ActiveEffects`. |
| `CurrentRun.CurrentRoom` | Room data, encounter, money is on the run not the room. |
| `CurrentRun.Money` | Obols. |
| `ActiveEnemies` | Live units keyed by object id. Cleared on every load (`Combat.lua:3868`). |
| `RequiredKillEnemies` | Subset that must die to clear the room. |
| `MapState.ActiveObstacles` | Doors, pots, wells, fountains, keyed by object id. |
| `OfferedExitDoors` | Exit doors keyed by object id. |
| `ScreenAnchors` | HUD widget ids. Presence means that widget was built. |
| `ActiveScreens` | Lua overlay screens, keyed by flag name. |
| `ShowingCombatUI` | `true` while the combat HUD is on screen (`UIScripts.lua:163`). `nil` while it is hidden (`UIScripts.lua:284`). |

`GetLocation({ Id = id })` returns a table with `X` and `Y` (`TraitTrayScripts.lua:548`, `RoomEvents.lua:218`). `GetAngle({ Id = id })` returns degrees (`Combat.lua:2373`, then `math.rad` at `Powers.lua:1634`). `GetVelocity({ Id = id })` is used as a number, a speed, not a vector (`EventPresentation.lua:3103`). `IsAlive({ Id = id })` is the engine liveness check (`CombatPresentation.lua:2239`).

While `ShowingCombatUI` is nil, HUD numbers are not on screen. World objects and enemy bars can still be visible. Do not export HUD fields as VISIBLE in that case, unless the open screen shows the same information (a boon menu or a shop).

---

## 1. Hero

### Position — VISIBLE

```lua
local loc = GetLocation({ Id = CurrentRun.Hero.ObjectId })
-- loc.X, loc.Y
```

`RoomManager.lua:4811` stores this as the hero location at exit unlock. Same call works for any id. Units are top-down; `GetZLocation` exists in the engine list and is not used for the hero in these scripts. Whether `Z` matters for pits is unknown (see Unknowns).

### Facing / aim — VISIBLE as body facing

```lua
function GetPlayerAngle()
    local playerAngleDegrees = GetAngle({ Id = CurrentRun.Hero.ObjectId })
    return playerAngleDegrees
end
```

`Combat.lua:2372`. The scripts treat this as the direction the body (and therefore the aim) faces. Attacks are fired with `FireWeaponFromUnit` at a destination id, and the engine turns the unit. There is no second "mouse aim" angle in Lua. `SetGoalAngle` writes a facing (`RoomPresentation.lua:2716`); do not call it.

No script reads the cursor's world position. `ZeroMouseTether` (`UIScripts.lua:2513`) only toggles the config option `ZeroMouseTether`, which recentres the camera tether while a screen is open. It is not a mouse-position API.

### Velocity — VISIBLE as motion, the number is the engine speed

```lua
local speed = GetVelocity({ Id = CurrentRun.Hero.ObjectId })
local moving = IsMoving({ Id = CurrentRun.Hero.ObjectId })
```

`GetVelocity` is a scalar in the only call site that consumes it (`EventPresentation.lua:3103`, `ApplyForce` `Speed = GetVelocity(...) * multiplier`). Pair it with `GetAngle` for a direction. `IsMoving` is an engine call (`docs/engine_cfuncs.txt`) and is not given a Lua wrapper. `EnemyAI.lua:210` uses the same `GetVelocity` on other ids. There is no `VX`/`VY` field.

### HP and max HP — VISIBLE (the HUD text and the bar)

```lua
local currentHealth = unit.Health
local maxHealth = unit.MaxHealth
ModifyTextBox({ Id = ScreenAnchors.HealthBack, Text = "UI_PlayerHealth",
    LuaKey = "TempTextData",
    LuaValue = { Current = math.ceil(currentHealth), Maximum = math.ceil(maxHealth) } })
SetAnimationFrameTarget({ Name = "HealthBarFill",
    Fraction = 1 - (currentHealth) / maxHealth, DestinationId = ScreenAnchors.HealthFill })
```

`UIScripts.lua:499-518`. The number on the bar is `math.ceil`. The fill fraction is `1 - Health/MaxHealth` (0 means full). Export `math.ceil(Health)`, `math.ceil(MaxHealth)`, and `Health/MaxHealth`.

The white rally segment is also drawn (`UIScripts.lua:511`, `UpdateRallyHealthUI` at `527`). It shows `Health + RallyHealth.Store` over `MaxHealth`. That segment is VISIBLE. `RallyHealth.Store` is the source of that segment. The decay timer (`RallyDecayRateSeconds` in `HeroData.lua:22`) is HIDDEN.

`ScreenAnchors.HealthBack == nil` means the bar is not on screen.

Low-health red shroud uses `GetLowHealthUIThreshold` (`UIScripts.lua:380`). The shroud is VISIBLE. The threshold formula is not shown as a number.

### Death Defiance charges — VISIBLE as pips

```lua
function GetNumLastStands( unit )
    return TableLength( unit.LastStands )
end
```

`Combat.lua:1510`. `UpdateLifePips` (`UIScripts.lua:392`) draws one pip per entry of `unit.LastStands`, using `lastStandData.Icon`, and `ExtraLifeEmpty` for spent slots up to `MaxLastStands` (`RecreateLifePips`, `UIScripts.lua:417`).

VISIBLE: the count of filled pips, `TableLength(CurrentRun.Hero.LastStands)`, and the empty-pip count `MaxLastStands - filled` when `MaxLastStands` is set. The icon distinguishes Skelly's tooth (`ExtraLifeSkelly` in `KeepsakeScripts.lua:98`) from a normal pip.

HIDDEN: `HealAmount` and `HealFraction` on each last-stand entry (`Combat.lua:1456`). The player sees a pip, not how much the next one heals. `LastStandsUsed` is a counter, not a pip.

`HasLastStand` (`Combat.lua:1506`) is `not IsEmpty(unit.LastStands)`.

### Cast ammo (bloodstones) — VISIBLE

```lua
Current = triggerArgs.Ammo or GetWeaponProperty({ Id = CurrentRun.Hero.ObjectId, WeaponName = "RangedWeapon", Property = "Ammo" }),
Maximum = triggerArgs.MaxAmmo or GetWeaponMaxAmmo({ Id = CurrentRun.Hero.ObjectId, WeaponName = "RangedWeapon" })
```

`UIScripts.lua:931-932`. The HUD text is `UI_AmmoText` with those two numbers. `ScreenAnchors.AmmoIndicatorUI` is the icon (`UIScripts.lua:912`).

Bloodstones stuck in an enemy or in Zagreus are separate icons: `ScreenAnchors.StoredAmmo` on the player (`Combat.lua:2937`) and `EnemyHealthDisplayAnchors[id.."storedAmmo"]` on a unit (`Combat.lua:2921`). Each icon is VISIBLE. The reload clock is a second obstacle, `AmmoReloadTimer`, while `ScreenAnchors.AmmoIndicatorUIReloads` is non-empty (`CombatPresentation.lua:3008`). The weapon name for the cast is always `"RangedWeapon"`.

The rail's magazine is a different widget, `ShowGunUI` / `UpdateGunUI`, property `Ammo` on `"GunWeapon"` (`UIScripts.lua:1005`). Export it when `ScreenAnchors.GunUI ~= nil`.

`IsWeaponAmmoFull({ Id = CurrentRun.Hero.ObjectId, WeaponName = "RangedWeapon" })` is what the use-prompt uses (`UIScripts.lua:2033`).

### Call (God Gauge) — VISIBLE as pips, the raw points are not printed

`IsSuperValid` (`ShoutScripts.lua:1`) is true only when a boon added a shout (`GetHeroTraitValues("AddShout")` non-empty). Otherwise `ShowSuperMeter` returns immediately and there is no gauge (`UIScripts.lua:1061`).

```lua
local superMeterPoints = CurrentRun.Hero.SuperMeter
local fillPercent = math.min(1, (superMeterPoints - (i - 1) * CurrentRun.Hero.SuperCost) / CurrentRun.Hero.SuperCost)
```

`UIScripts.lua:1080-1109` and `UpdateSuperMeterUIReal` at `1199`. One pip per `SuperCost` chunk of `SuperMeterLimit`. A pip is empty, partial, or full. `IsSuperAvailable` (`ShoutScripts.lua:98`) is `SuperMeter >= SuperCost`. The full-bar flash is `SuperMeter == SuperMeterLimit` (`UIScripts.lua:1085`).

VISIBLE: number of full pips `math.floor(SuperMeter / SuperCost)`, the partial fill of the current pip, and whether the bar is maxed. HIDDEN: the raw `SuperMeter` points, because the text box that would print them is commented out (`UIScripts.lua:1089-1094`). `SuperMeterLimit` and `SuperCost` are only visible as pip count and pip width.

`CanCommenceSuper` (`ShoutScripts.lua:65`) also requires combat to be running. That gate is not drawn. Do not export it as "the gauge is locked"; the player sees the pips either way. A failed press plays `ShoutFailedPresentation` and is VISIBLE as feedback, but only after the press.

`CurrentRun.Hero.SuperActive` is true during the call (`ShoutScripts.lua:112`). The call's effect is VISIBLE. The flag itself matches that.

### Dash availability — not drawn as a meter

There is no dash widget in `UIScripts.lua`. The dash weapons are `WeaponSets.HeroRushWeapons` = `"RushWeapon"` and `"RamWeapon"` (`WeaponSets.lua:10`).

The scripts disable dash with the effects `RushWeaponDisable` and `RushWeaponDisableCancelable` (`WeaponData.lua:1499`, cleared at `RoomPresentation.lua:1352`). `HasEffect({ Id = CurrentRun.Hero.ObjectId, EffectName = "RushWeaponDisable" })` and the same for `RushWeaponDisableCancelable` tell you the script has blocked the dash.

HIDDEN as a number: the normal dash cooldown. No script reads a cooldown property for `RushWeapon`. `GetWeaponChargeFraction` is in the engine list and is never called. Whether the engine draws a cooldown ring is not in these scripts. See Unknowns. Do not invent a cooldown query.

`OnWeaponFired` with `triggerArgs.name` in `HeroRushWeapons` is the moment a dash happens (HIDDEN timing, useful as a reward event only if you need "a dash occurred"). The afterimage is VISIBLE but not queryable from Lua.

### Status effects on the HUD — mixed

The full set is `unit.ActiveEffects[effectName] = stacks`, written by the engine callback:

```lua
OnEffectApply{
    function( triggerArgs )
        victim.ActiveEffects = victim.ActiveEffects or {}
        victim.ActiveEffects[triggerArgs.EffectName] = triggerArgs.Stacks
    end
}
```

`Combat.lua:3466`. Cleared in `OnEffectCleared` (`Combat.lua:3530`). `HasEffect({ Id = id, EffectName = name })` is the engine check (`RunManager.lua:3129`).

`ActiveEffects` contains modifiers that have no icon (damage multipliers, `SPEED`, `INVULNERABLE`). Exporting the whole table would leak HIDDEN stats. Export only effects that have a drawn presentation:

| What is drawn | Where | Label |
| --- | --- | --- |
| Hangover stack icon and number | `UpdatePoisonEffectStacks`, `CombatPresentation.lua:264`. Icon `PoisonSmall`, text is the stack count. | VISIBLE |
| Chill stack icon and number | `UpdateChillEffectStacks`, `CombatPresentation.lua:323`. Icon `ChillSmall`. | VISIBLE |
| Rupture stack icon | `UpdateRuptureEffectStacks`, `CombatPresentation.lua:214`. | VISIBLE |
| Weak/exposed stack marker | `AddVulnerabilityIndicator`, `CombatPresentation.lua:418`, only if the Privileged Status mirror rank is at least 1. | VISIBLE when drawn |
| Styx poison vignette | `StartStyxPoisonPresentation`, `CombatPresentation.lua:2928`. `ScreenAnchors.PoisonVignette ~= nil`. | VISIBLE |
| Magma vignette | `StartLavaPresentation`, `CombatPresentation.lua:2972`. `CurrentRun.Hero.OnLava` is set in `LavaSlowApply` (`Powers.lua:456`). | VISIBLE |
| Boon icon pulse | `TraitUIActivateTrait` / `TraitUIDeactivateTrait` (`UIScripts.lua:1543`). | VISIBLE |

`GetEffectTimeRemaining` is in the engine list and is never called. Do not query it; the remaining duration is HIDDEN (the icons do not show a timer, except the cast reload clock above).

Hero `ActiveEffects` is cleared on room exit: `ClearEffect({ Id = currentRun.Hero.ObjectId, All = true })` in `LeaveRoom` (`RoomManager.lua:4996`).

### Obols — VISIBLE

```lua
CreateTextBox({ Id = ScreenAnchors.MoneyIcon, Text = CurrentRun.Money, ... })
```

`UIScripts.lua:753` and `UpdateMoneyUI` at `810`. The integer `CurrentRun.Money` is the number printed, while `ShowingCombatUI` is true and `ScreenAnchors.MoneyIcon ~= nil`. `AddMoney` (`RoomManager.lua:3307`) and the spend path (`RoomManager.lua:3267`) both call `UpdateMoneyUI`.

Other resources (darkness, keys, nectar, gemstones) use `GameState.Resources[name]` and `ShowResourceUI` (`UIScripts.lua:585`). They are VISIBLE when `ScreenAnchors.ResourceShowing[name]` is true. House-only resources are not on the combat HUD.

`CurrentRun.MoneySpent` and `CurrentRun.MoneyRecord` are HIDDEN ledgers.

### Weapon and aspect — VISIBLE

```lua
function GetEquippedWeapon()
    for k, weaponName in ipairs( WeaponSets.HeroMeleeWeapons ) do
        if CurrentRun.Hero.Weapons[weaponName] then
            return weaponName
        end
    end
end
```

`WeaponUpgradeScripts.lua:762`. `HeroMeleeWeapons` is the six weapons (`WeaponSets.lua:39`). The name (`SwordWeapon`, `BowWeapon`, `ShieldWeapon`, `SpearWeapon`, `GunWeapon`, `FistWeapon`) is the equipped weapon.

The aspect is the equipped upgrade trait:

```lua
function GetWeaponUpgradeTrait( weapon, index )
    if WeaponUpgradeData[weapon][index].TraitName then
        return WeaponUpgradeData[weapon][index].TraitName
    end
    -- ...
end
```

`WeaponUpgradeScripts.lua:770`. The index is `GameState.LastWeaponUpgradeData[weaponName].Index` (`WeaponUpgradeScripts.lua:785`). `EquipWeaponUpgrade` (`814`) adds that trait if it is not already on the hero. The aspect is also whichever trait on `CurrentRun.Hero.Traits` has that name. Zagreus (index 1) often has no trait (`GetWeaponUpgradeTrait` returns nil when the entry has no `TraitName`). The weapon is still VISIBLE; "no aspect trait" means the default aspect.

`GameState.LastWeaponUpgradeData` is persistent meta state. The player can see the aspect on the weapon and, once the trait is on the tray, as an icon. Export the weapon name and the aspect trait name. Do not export upgrade levels that are not shown (`GetWeaponUpgradeLevel` is a rank, and the tray shows it only if `UpdateTraitNumber` drew it).

### Boons and keepsake — VISIBLE as the tray

Traits live in `CurrentRun.Hero.Traits` (a list, inserted in `AddTraitData`, `TraitScripts.lua:864`). Fields the tray uses:

- `Name` — internal id. The icon is `trait.Icon` or `TraitData[name].Icon` (`GetTraitIcon`, `UIScripts.lua:1607`).
- `Rarity` — `"Common"`, `"Rare"`, `"Epic"`, `"Heroic"`, `"Legendary"`. Frame from `GetTraitFrame` (`UIScripts.lua:1639`).
- `Slot` — `"Melee"`, `"Secondary"`, `"Ranged"`, `"Rush"`, `"Shout"`, `"Keepsake"`, `"Assist"`. Slot order is in `UpgradeChoice.lua:121`.
- `God` — set on god boons, for example `God = "Zeus"` (`TraitData.lua:502`). Absent on many non-god traits.
- Stack level, when `UpdateTraitNumber` has drawn it (`UIScripts.lua:1422`).

The keepsake is the trait with `Slot == "Keepsake"` (`RunManager.lua:1926` reads it that way for the end-of-run card). It is equipped from `GameState.LastAwardTrait` in `EquipKeepsake` (`KeepsakeScripts.lua:80`, called at run start `RunManager.lua:251`). The companion is `Slot == "Assist"`, from `GameState.LastAssistTrait` (`KeepsakeScripts.lua:117`).

VISIBLE: name, icon, rarity frame, slot, god (when the icon or the god symbol is the one on the tray), stack number if the tray shows one, keepsake, companion. HIDDEN: numeric effect values inside the trait (`ExtractValues` results such as damage multipliers), except where the tray tooltip is open. The tooltip is a screen (`TraitTrayScreen`, see section 5), and its text is VISIBLE only while that screen is open.

`HeroHasTrait(traitName)` is `TraitScripts.lua:624`.

---

## 2. Enemies

### Enumerating live enemies — VISIBLE bodies

```lua
ActiveEnemies[newEnemy.ObjectId] = newEnemy
AttachLua({ Id = newEnemy.ObjectId, Table = newEnemy })
```

`RoomManager.lua:4198`, inside `SetupEnemyObject`. Removed in `Kill` at `Combat.lua:3310`. The table is replaced with `{}` on every `OnAnyLoad` (`Combat.lua:3868`).

This table is not "foes only". It holds traps (`ToggleTrap`), friendly NPCs, summons, and charmed units. For units the player is fighting:

```lua
for id, enemy in pairs(ActiveEnemies) do
    if enemy.RequiredKill and not enemy.IsDead and not enemy.Charmed
        and not enemy.ToggleTrap
        and not HeroData.DefaultHero.HeroAlliedUnits[enemy.Name] then
        -- a live foe
    end
end
```

`RequiredKill` is what puts a unit in `RequiredKillEnemies` (`RoomManager.lua:4154`). `GetActiveEnemyCount` (`RoomEvents.lua:865`) counts that table, plus `MapState.PlaceholderEnemyCount` (spawns that have not appeared yet). The placeholder count is HIDDEN: the player has not seen those units. Do not export it.

`IsAlive({ Id = id })` is the engine check. `enemy.IsDead` is set in `KillEnemy` (`Combat.lua:1762`) before the id is removed. Skip `IsDead` entries if you ever see one still in the table.

`GetIds({ Name = "RequiredKillEnemies" })` and `GetIdsByType({ Name = enemyType })` return ids (`Combat.lua:1826`). Prefer `ActiveEnemies`, which already has the Lua table.

### Name / type — VISIBLE as the body and the boss nameplate

`enemy.Name` is the type key (`EnemyData` key). `enemy.GenusName` is the codex family, used when the name differs (`Combat.lua:1898`). Boss nameplates use `boss.HealthBarTextId or boss.Name` (`UIScripts.lua:2750`). Export `Name` as the type. For a boss, the nameplate text id is what is printed; the string is a localisation key, which matches the portrait the player sees.

HIDDEN: `GeneratorData.DifficultyRating`, AI weapon lists, shrine multipliers applied in `SetupEnemyObject` (`RoomManager.lua:4063`).

### Position, facing, velocity — VISIBLE

Same calls as the hero, with `enemy.ObjectId`:

```lua
local loc = GetLocation({ Id = enemy.ObjectId })
local angle = GetAngle({ Id = enemy.ObjectId })
local speed = GetVelocity({ Id = enemy.ObjectId })
```

`GetAngle` on an enemy is used at `EnemyAI.lua:73` and `EnemyAI.lua:3095`.

### Health and armour, as the bar draws them — VISIBLE fraction

`CreateHealthBar` (`CombatPresentation.lua:65`) skips `HideHealthBar`. Bosses (`UseBossHealthBar`, set on `BaseBossEnemy` at `EnemyData.lua:100`) get `CreateBossHealthBar` (`UIScripts.lua:2720`), which prints a name and a bar, not a number.

For a normal foe, `UpdateHealthBarReal` (`CombatPresentation.lua:578`) sets `enemy.DisplayedHealthFraction` and the fill to `1 - fraction`:

```lua
if enemy.HitShields ~= nil and enemy.HitShields > 0 then
    displayedHealthPercent = 1
elseif enemy.HealthBuffer ~= nil and enemy.HealthBuffer > 0 then
    displayedHealthPercent = enemy.HealthBuffer / enemy.MaxHealthBuffer
else
    displayedHealthPercent = currentHealth / maxHealth
end
enemy.DisplayedHealthFraction = displayedHealthPercent
```

`CombatPresentation.lua:635-648`.

Export, and only this:

- If `HitShields > 0`: bar reads as full, plus one shield icon per shield (`UpdateHealthBarIcons`, `CombatPresentation.lua:482`, obstacle `EnemyShieldIcon`). The count of icons equals `HitShields`, so the count is VISIBLE. The HP underneath is HIDDEN until the shields are gone.
- Else if `HealthBuffer > 0`: the bar is the armour fraction `HealthBuffer / MaxHealthBuffer`, coloured `Color.HealthBuffer`, with an `EnemyArmorIcon` (`CombatPresentation.lua:509`). Exact buffer points are HIDDEN. The armour-break flash is `ArmorBreakPresentation` (`CombatPresentation.lua:781`).
- Else: the red fraction `Health / MaxHealth`. Exact points are HIDDEN. The fraction is VISIBLE.

Boss bars do not use that three-way split. `UpdateHealthBarReal` (`CombatPresentation.lua:598`) always fills `Health / MaxHealth`, and only recolours the bar while `HitShields > 0`. Export the boss fraction, not the points. `DisplayedHealthFraction` is not updated on the boss path; compute `Health / MaxHealth` and then drop the raw values.

Bar width (`BarXScale`, `CombatPresentation.lua:127`) is chosen from `MaxHealth` thresholds or from `HealthBarType`. The width is VISIBLE. The exact `MaxHealth` is still HIDDEN; do not export it. Do not export `Health` either, except the hero's, which is printed.

`HideHealthBar` units (pots inherit this from `BaseDestructible`, `ObstacleData.lua:67`) have no bar. Their HP is HIDDEN. Export only that they exist and where they are, if they are drawn.

### Elite and shield modifiers that are drawn — VISIBLE icons

Elites inherit `Elite` (`EnemyData.lua:120`): `IsElite = true`, `EliteIcon = true`. `SetupEnemyObject` copies `currentRoom.EliteAttributes[name]` onto the unit and calls `ApplyEliteAttribute` (`RoomManager.lua:4021`, `3888`).

The bar draws one badge per entry of `enemy.EliteAttributes`, animation `"EliteAttribute"..attributeName`, or a plain skull if the list is empty (`CombatPresentation.lua:157-180`). Export `IsElite` and the attribute names, because each name is a drawn icon. Do not export the attribute's AI data (blink intervals, extra weapons). Those timers are HIDDEN. `currentRoom.EliteAttributes` before spawn is the roll; once the unit exists, read it off the unit.

Shields are the `HitShields` icons above, including Pact shields applied at `RoomManager.lua:4102` (`EnemyShieldShrineUpgrade`).

### Boss phases — VISIBLE when the phase change is shown

`SetupEnemyObject` sets `CurrentPhase = 1` when `enemy.Phases ~= nil` (`RoomManager.lua:4099`). The Hades phase change increments it after the knockdown, the refill, and the new phase VFX:

```lua
boss.Health = boss.MaxHealth
BossHealthBarPresentation( boss )
-- ...
boss.CurrentPhase = boss.CurrentPhase + 1
```

`CombatPresentation.lua:2678-2710`. During the transition `boss.InTransition` is set (cleared at `2713`). The refill animation is VISIBLE. `CurrentPhase` matches the phase the player is in after that presentation.

Theseus and Asterius use a room-level `currentRoom.CurrentPhase` (`RoomPresentation.lua:5219`), not only the unit field. Read both: `ActiveEnemies[CurrentRun.CurrentRoom.BossId].CurrentPhase` (the boss id is read this way at `RunManager.lua:4371`) and `CurrentRun.CurrentRoom.CurrentPhase` when it is set.

The next phase's weapon list and `SetHealthPercent` are HIDDEN until the bar actually refills.

### Attack telegraphs — drawn, but not stored as a flag

The wind-up in `EnemyAI.lua:100-123` is the drawn tell:

```lua
if aiData.PreAttackAnimation ~= nil then
    SetAnimation({ Name = aiData.PreAttackAnimation, DestinationId = enemy.ObjectId })
end
if enemy.AttackWarningAnimation ~= nil then
    CreateAnimation({ Name = aiData.AttackWarningAnimation, DestinationId = enemy.ObjectId,
        ScaleRadius = aiData.AttackWarningAnimationRadius })
end
wait( CalcEnemyWait( enemy, aiData.PreAttackDuration), enemy.AIThreadName )
if aiData.AttackWarningAnimation ~= nil then
    StopAnimation({ Name = aiData.AttackWarningAnimation, DestinationId = enemy.ObjectId })
end
```

There is no `enemy.IsTelegraphing` field. `GetAnimationName` is in the engine list and is never called, so it is not safe to assume it returns the warning decal. The warning is a `CreateAnimation` on the unit, removed by `StopAnimation` with the same name. `AttackWarningAnimation` on the enemy data is the decal's name, not a live "it is showing" bit. `PreAttackDuration` is HIDDEN (an AI timer). The decal and the pre-attack pose, while they are on screen, are VISIBLE, but these scripts do not record that interval anywhere a poller can read.

What a poller can use without guessing:

- `enemy.AINotifyName` is a wait name, not a telegraph (`EnemyAI.lua:80`). HIDDEN.
- `OnWeaponFired` for a non-hero owner is the attack itself, which is after the tell. Useful as "this unit just fired", which is VISIBLE as the attack, late as a tell.
- Fuse warnings: `victim.FuseWarningAnimation` is stopped on death (`Combat.lua:3245`). The fuse radius is read with `GetProjectileProperty({ Id = enemy.ObjectId, WeaponName = enemy.FuseWarningWeapon, Property = "DamageRadius" })` (`CombatPresentation.lua:3643`). The weapon name on the unit is data, not "the fuse is active".

See Unknowns for a live telegraph bit.

---

## 3. Projectiles and hazards

### There is no projectile list

The engine list has `ProjectileExists`, `GetProjectileProperty`, `ExpireProjectiles`, `OnProjectileDeath`, and `OnWeaponFired`. It has no "get all projectile ids". No Lua table stores live projectiles. `MapState` does not have one.

`ProjectileExists` is called with names, not ids (`Powers.lua:1492`, `ProjectileExists({ Names = { "SpearWeaponThrow" }})`). `GetProjectileProperty` is called with the owner's id and a weapon name (`CombatPresentation.lua:3643`), not with a projectile id.

`OnWeaponFired` (`Combat.lua:2259`) gives, on `triggerArgs`:

- `name` — weapon name
- `OwnerTable` — the shooter (compare `ObjectId` to the hero)
- `ProjectileName` — set when the weapon spawns a projectile (`Combat.lua:2285`)
- `Ammo` — remaining ammo after the shot (`Combat.lua:2338`)
- `IsPerfectCharge`

It does not give a projectile id or a velocity. Location at fire time is not read in this handler.

`OnProjectileDeath` (`Combat.lua:2807`) gives `name` (projectile name), `LocationX`, `LocationY`, `Angle`, `WeaponName`, `AttackerTable`, `triggeredById` (the victim, not the projectile), `IsDeflected`, `FireIndex`.

A bridge that needs live shots has to remember them: subscribe to `OnWeaponFired` and `OnProjectileDeath`, and keep its own list. Positions after the shot are not readable from these scripts. Do not call `ExpireProjectiles`. That deletes shots.

Owner: `triggerArgs.OwnerTable` on fire, `triggerArgs.AttackerTable` on death. Hero shots are `OwnerTable.ObjectId == CurrentRun.Hero.ObjectId`.

### Traps — VISIBLE, they are enemies

Traps are `ActiveEnemies` with `ToggleTrap = true` (spike trap at `EnemyData.lua:26280`, `ToggleTrap` at `26300`). `DisableTrap` (`RoomManager.lua:5931`) sets `DisableAIWhenReady` and plays `DisabledAnimation`. `DisableRoomTraps` (`5956`) does that to every trap when the encounter ends.

VISIBLE: position, `Name`, whether it is disabled (`AIDisabled` or `DisableAIWhenReady`, and the disabled animation). The pre-attack animation (`SpikeTrapPreFire`, `AxeTrapActivated`) is the tell, with the same caveat as section 2: it is not stored as a flag.

HIDDEN: `PreAttackDuration`, `PostAttackCooldown`.

### Magma, poison puddles, smoke

When the room's required kills are dead, `CheckForAllEnemiesDead` expires named hazard projectiles (`RoomEvents.lua:895`): `PoisonPuddle`, `PoisonPuddleSmall`, `RatPoisonShake`, `RatDeathPuddle`, `LavaPuddleLarge`, `LavaSplash`, `PoisonTrapWeapon`, `ArcherTrapWeapon`. It also kills units of type `LavaSplash`.

While they exist they are projectiles or trap units, not a queryable list. The hero standing in magma is VISIBLE: `CurrentRun.Hero.OnLava` (`Powers.lua:459`) and the lava vignette. Styx poison on the hero is the poison vignette (`ScreenAnchors.PoisonVignette`).

### Pots and rubble — VISIBLE objects, HP hidden

`MapState.ActiveObstacles[id] = obstacle` in `SetupObstacle` (`RunManager.lua:2455`), from `OnSpawn` when `ObstacleData[name]` exists (`RunManager.lua:2390`).

Destructibles inherit `BaseDestructible` (`ObstacleData.lua:67`): `HideHealthBar = true`, so no bar. Examples: `TartarusRubble02` (`ObstacleData.lua:1358`, `MaxHealth = 1`). They are drawn. Their remaining HP is HIDDEN. Export id, `Name`, and `GetLocation`. `obstacle.Health` starts at `MaxHealth` (`RunManager.lua:2465`) and is not shown.

`GetIdsByType({ Name = "..." })` finds map objects by type name. `GetMapThings` and `GetMapThingsByType` are engine calls with no Lua wrapper in these scripts; do not depend on their return shape.

---

## 4. Room and run

### Room name, biome, depth — the name is shown on the map, the counters are not a HUD element

```lua
CurrentRun.CurrentRoom.Name
CurrentRun.CurrentRoom.RoomSetName   -- "Tartarus", "Asphodel", "Elysium", "Styx", or a secrets set
GetMapName({})                       -- the loaded map, used by HasUsed (Interactables.lua:480)
```

`ChooseStartingRoom` uses `RoomSetName` (`RunManager.lua:325`). `GetMapName` is the engine map id.

Depth:

```lua
function GetRunDepth( currentRun )   -- rooms this escape, RunManager.lua:1779
function GetBiomeDepth( currentRun ) -- rooms since the last biome change, RunManager.lua:1798
```

`CurrentRun.RunDepthCache` and `BiomeDepthCache` are updated in `UpdateRunHistoryCache` (`RunManager.lua:1749`). The chamber counter the player sees at a door or on the boon list is this depth. Export `GetRunDepth(CurrentRun)` and `CurrentRun.CurrentRoom.RoomSetName` as VISIBLE once the room has presented (the player is standing in it). Do not export `RoomHistory` entries the player cannot see any more, beyond the count.

`CurrentRun.CurrentRoom.GenusName` is the logical room when several maps share a reward (`RunManager.lua:384`). Prefer `GenusName or Name` when matching reward rules. The displayed chamber is the one the player is in.

### Encounter state — VISIBLE as "things are still attacking" vs "the room is clear"

```lua
currentEncounter.InProgress = true
currentEncounter.Completed = false
-- ... RunEvents ...
currentEncounter.Completed = true
```

`StartEncounter`, `RoomManager.lua:2526` and `2557`. `CheckForAllEnemiesDead` sets `InProgress = false` when the `RequiredKillEnemies` group is empty (`RoomEvents.lua:877`).

`IsCombatEncounterActive` (`RoomManager.lua:3699`) is the game's own "combat is happening" check: not dead, no blocking timer, encounter exists, not `NonCombat`, `InProgress`, and not `Completed`. A challenge encounter counts too (`3717`).

VISIBLE: enemies still alive, doors still dark. The flags match that. HIDDEN: `RemainingSpawns`, `SpawnWaves`, `DifficultyRating` (`RoomManager.lua:2509` and `GetRemainingSpawns` at `3762`). Those are future spawns. `MapState.PlaceholderEnemyCount` is the same leak. Do not export them.

`CurrentRun.CurrentRoom.ExitsUnlocked` is set at the start of `UnlockRoomExits` (`RoomManager.lua:4801`), before the door lights. The lights themselves are `door.ReadyToUse` after `CreateDoorRewardPreview` (`RoomManager.lua:4932`). Prefer `ReadyToUse` as "the door is lit".

`Encounter.EncounterType == "Boss"` is used for boss-room boons (`RoomManager.lua:3550`). Combined with a live `IsBoss` unit, the boss bar is VISIBLE.

### Exit doors and reward icons — VISIBLE once the preview is created

Doors with `IsDefaultDoor` are registered in `SetupObstacle` (`RunManager.lua:2467`):

```lua
if obstacle.IsDefaultDoor and not IsDoorClosedForRun(CurrentRun, obstacle) then
    OfferedExitDoors[obstacle.ObjectId] = obstacle
end
```

`ExitDoor` is the template (`ObstacleData.lua:76`). While the room is in combat, `UseText` is `"UseExitDoorWhileLocked"`. After unlock, `DoUnlockRoomExits` (`RoomManager.lua:4853`) assigns `door.Room`, calls `CreateDoorRewardPreview` (`RoomPresentation.lua:1570`), plays `ExitDoorUnlockedPresentation`, and sets `door.ReadyToUse = true`.

The icon is chosen in `CreateDoorRewardPreview` (`RoomPresentation.lua:1602`):

| Condition | Animation on `door.DoorIconId` |
| --- | --- |
| `room.NextRoomSet` | `ExitPreview` (biome exit) |
| Hero has `HiddenRoomReward` | `ChaosPreview` (the reward is hidden on purpose) |
| `ChosenRewardType == nil` | `StoryPreview` |
| `"Boon"` and `room.ForceLootName` | `LootData[ForceLootName].DoorIcon` or `.Icon` |
| `"Devotion"` | two icons, `LootData[LootAName].DoorIcon` and `LootBName` |
| anything else | `ChosenRewardType.."Preview"` |

`CreateDoorPreviewIcon` (`1660`) adds the elite skull when `RewardPreviewIcon` is set (the `Devotion` and elite-darkness entries set `RoomElitePreview` in `LootData.lua:20957` and `20631`).

`ChosenRewardType` values in `RewardStoreData.RunProgress` (`LootData.lua:20855`): `RoomRewardMaxHealthDrop`, `RoomRewardMoneyDrop`, `Boon`, `StackUpgrade` (pom), `WeaponUpgrade` (Daedalus hammer), `HermesUpgrade`, `Devotion`. Meta rewards include `RoomRewardMetaPointDrop`. A shop room uses `ChosenRewardType == "Shop"` (the reroll check at `RoomManager.lua:4984`).

Before `ReadyToUse`, `door.Room.ChosenRewardType` may already be filled. The icon is not on screen yet. Export the reward only when `door.ReadyToUse` is true, or when `door.DoorIconId` is set. `HiddenRoomReward` means the player sees Chaos's question mark: export "hidden", not the real reward. The real type is HIDDEN in that case.

`CurrentRun.CurrentRoom.OfferedRewards[doorId] = { Type, ForceLootName }` (`RoomManager.lua:4980`) is written at the same time as the preview. `ForceLootName` is the god (`ZeusUpgrade`, and so on; `LootData.ZeusUpgrade` at `LootData.lua:21`, `DoorIcon` at line 29).

`door.CanBeRerolled` is the Fate reroll sparkle (`RoomManager.lua:4984`). VISIBLE when the sparkle is up.

### Charon, wells, fountains, Chaos gates

Charon's wares are world objects from `SpawnStoreItemsInWorld` (`StoreScripts.lua:396`), placed on `LootPoint` ids. Each item is in `CurrentRun.CurrentRoom.Store.SpawnedStoreItems`. The price is `item.Cost` (or `HealthCost`). `UpdateCostText` refreshes when money changes (`UIScripts.lua:804`). The price tag is VISIBLE. Items not yet spawned are HIDDEN.

Wells are the obstacle `WellShop` (`ObstacleData.lua:2329`). `UseWellShop` (`Interactables.lua:436`) calls `StartUpStore` (`StoreScripts.lua:791`), which opens the Store screen. `CurrentRun.CurrentRoom.WellShop.ReadyToUse` is set with the doors (`RoomManager.lua:4955`). Until then the well plays `WellShopBlocked` / locked text.

The pool of Purging is `SellTraitShop` (`ObstacleData.lua:2348`), opened by `OpenSellTraitMenu`.

Fountains are `HealthFountain`, `HealthFountainAsphodel`, `HealthFountainElysium`, `HealthFountainStyx` (`ObstacleData.lua:679` and following). They are obstacles in `MapState.ActiveObstacles`. A spent fountain uses `HealingSpentAnimation` (for example `HealthFountainEmpty`). The heal amount is in the use text; read the obstacle's processed heal fields only if that text is showing. Styx cure fountains are type `PoisonCureFountainStyx` (`CombatPresentation.lua:2954`).

Chaos gates are `SecretDoor` (`ObstacleData.lua:2366`). `HideRewardPreview = true`, so there is no reward icon. The gate shows locked text until it is usable (`UnlockedUseText = "UseSecretDoor_Unlocked"`). `ReadyToUse` is the lit state, same as other exits. The destination reward is HIDDEN until a later room shows it. `RewardStoreData.Secrets` is `TrialUpgrade` (`LootData.lua:20574`), which is the Chaos boon, and it is not drawn on the gate.

### Interactables and the Use prompt — VISIBLE when the prompt is up

`ShowUseButton` (`UIScripts.lua:2182`) draws the prompt. The string comes from `GetUseText` (`UIScripts.lua:2026`): `UseText`, or `UnlockedUseText` once `CheckRoomExitsReady` passes, or `LockedUseText` when a special requirement fails.

`IsUseable({ Id = id })` is the engine call (used for the fishing point at `RoomManager.lua:4935`). `ActivatedObjects` holds things that block the exit until used (`RunManager.lua:2471`, `BlockExitUntilUsed`).

Export, for each obstacle in `MapState.ActiveObstacles` that is drawn: `Name`, `GetLocation`, `UseText` / the unlocked variant if `ReadyToUse`, and `IsUseable`. Skip ids that `SetupObstacle` destroyed.

---

## 5. Menus and screens

Two stacks:

1. Lua overlays. `OnScreenOpened({ Flag = name })` sets `ActiveScreens[flag]` (`UIScripts.lua:2422`). `OnScreenClosed` clears it (`2448`). `IsScreenOpen(flag)` and `AreScreensActive()` read that table (`2444`, `2535`).
2. Engine menus. `GetTopScreenName({})` returns the engine menu name. `DebugScripts.lua:71` compares it to a screen name and calls `ExitMenu`. The pause screen is the engine menu `"PauseScreen"` (`UIScripts.lua:84`, `OnMenuOpened`). Lua overlays are not in that name. Read both.

`ShowingCombatUI` tells you whether the HUD is also up. Screens opened with `PersistCombatUI = true` leave it up.

| Screen | Open flag | How you know it opened | How you know it closed | What to read |
| --- | --- | --- | --- | --- |
| Boon / hammer / Chaos choice | `"BoonMenu"` | `OpenUpgradeChoiceMenu` (`UpgradeChoice.lua:2`) calls `OnScreenOpened`. `ScreenAnchors.ChoiceScreen` is the screen. | `CloseUpgradeChoiceScreen` (`UpgradeChoice.lua:947`) calls `OnScreenClosed({Flag = "BoonMenu"})` at line 975. | VISIBLE. See below. |
| Well / shop menu | `"Store"` | `ShowStoreScreen` sets `screen.Name = "Store"` (`StoreScripts.lua:500`) and `OnScreenOpened` at 507. | `CloseStoreScreen` (`StoreScripts.lua:802`) calls `OnScreenClosed({Flag = "Store"})` at 821. | VISIBLE. `Store.StoreOptions[i]` after `CreateStoreButtons` (`561`): `Name`, `Type` (`"Trait"`, `"Consumable"`, `"Cosmetic"`), `Icon`, `Cost` or `HealthCost`. |
| Charon, in the room | no menu until you walk up | Items spawned by `SpawnStoreItemsInWorld`. | n/a | VISIBLE price tags. |
| Sell boons | `"SellTraitMenu"` | `OpenSellTraitMenu` (`SellTraitScripts.lua:24`). | `OnScreenClosed` for that flag. | VISIBLE list of traits offered for sale. |
| Mirror of Night | `"MetaUpgrade"` | `OpenMetaUpgradeMenu` (`MetaUpgrades.lua:124`). `ScreenAnchors.LevelUpScreen`. | `OnScreenClosed` with that flag. | VISIBLE ranks and costs on the buttons. `GameState.MetaUpgrades[name]` is the rank. Costs are on the button data the screen builds. |
| Pact | `"ShrineUpgrade"` | Same file, `screen.Name = "ShrineUpgrade"` (`MetaUpgrades.lua:402`). | same | VISIBLE. Heat pips are the shrine ranks. |
| Contractor | `"GhostAdmin"` | `OpenGhostAdminScreen` (`GhostAdminScreen.lua:308`), `screen.Name = "GhostAdmin"` at 312. | `OnScreenClosed`. | VISIBLE contractor list and prices. |
| Keepsake rack | `"AwardMenu"` | `ShowAwardMenu` (`AwardMenuScripts.lua:133`). | `OnScreenClosed`. | VISIBLE. `UIData.AwardMenu.AvailableKeepsakeTraits` and `AvailableAssistTraits` (`AwardMenuScripts.lua:123`). Equipped is `GameState.LastAwardTrait` / `LastAssistTrait`. |
| Dialogue | `"Dialog"` | `PlayTextLines` (`Narrative.lua:47`). `PlayingTextLines` is true for the whole set. | `OnScreenClosed({Flag = "Dialog"})` at `Narrative.lua:61`. | VISIBLE. Choices: `line.Choices[].ChoiceText` and `ChoiceDescription`, drawn at `Narrative.lua:612-670`. `GameState.WaitingForChoice` is true while the cursor is on a choice (`714`). |
| Victory | `"RunClear"` | `ShowRunClearScreen` (`RunClearScreen.lua:1`) calls `RecordRunCleared` then `OnScreenOpened`. | `OnScreenClosed`. | VISIBLE. `CurrentRun.Cleared == true` (`RunManager.lua:1937`). |
| Pause | engine `"PauseScreen"` | `OnMenuOpened{ "PauseScreen" }` (`UIScripts.lua:84`). `GetTopScreenName({}) == "PauseScreen"`. | `OnMenuCloseFinished{ "PauseScreen" }` (`UIScripts.lua:97`). | VISIBLE. No Lua copy of the pause buttons. |
| Codex, quest log, music, market, run history, stats, seed | flags in `IsPauseBlocked` (`UIScripts.lua:2485`): `Codex`, `QuestLog`, `MusicPlayer`, `Market`, `RunHistory`, `GameStats`, `SeedControl`, `TraitTrayScreen` | each screen calls `OnScreenOpened` with its `screen.Name` | matching `OnScreenClosed` | VISIBLE while open. The tray tooltip is `TraitTrayScreen`. |

Boon buttons. `lootData.UpgradeOptions` is the list (`UpgradeChoice.lua:88`). Each entry has `ItemName`, `Type` (`"Trait"`, `"Consumable"`, `"TransformingTrait"`), and `Rarity`. The god is the loot: `lootData.Name` (`ZeusUpgrade`, `WeaponUpgrade` for the hammer, `TrialUpgrade` for Chaos). `OpenUpgradeChoiceMenu` stores it as `screen.SubjectName` (`UpgradeChoice.lua:23`). Hammer choices are the same screen with a weapon-upgrade loot, so `ItemName` is the hammer boon. Chaos uses `Type == "TransformingTrait"` with `ItemName` (blessing) and `SecondaryItemName` (curse) (`UpgradeChoice.lua:238`).

Rarity is VISIBLE (the card frame and the word). The god symbol on the card is `LootData[lootName].Icon` (`UpgradeChoice.lua:37`). Export `ItemName`, `Rarity`, `Type`, and `screen.SubjectName`. Description numbers are VISIBLE because they are printed on the card (`GetTraitTooltip` at `UpgradeChoice.lua:203`). They are not hidden stats at that point. Do not export options that were not put on a button: `blockedIndexes` (`UpgradeChoice.lua:111`) drops some rolled options before display, and `CalcNumLootChoices` limits the count. Read the buttons that exist (`components["PurchaseButton"..i]`), not the raw `UpgradeOptions` list if it is longer.

`ScreenAnchors.ChoiceScreen.KeepOpen` is true while the menu waits (`UpgradeChoice.lua:77`).

---

## 6. Events for reward only

These may be HIDDEN. Do not feed them to the policy as observations. They are the right hooks for a reward.

| Event | Hook | Payload |
| --- | --- | --- |
| Hero damaged | `DamageHero(victim, triggerArgs)` (`Combat.lua:1143`). The engine path is `OnHit` (`Combat.lua:2614`) then `Damage` (`723`). | `triggerArgs.DamageAmount` is the amount about to be applied. `AttackerName`, `SourceWeapon`, `EffectName`. The HUD then shows the new HP, which is VISIBLE. The amount itself is not printed (floating damage numbers are a presentation, `HeroDamagePresentation` at `1230`, and they are VISIBLE if you only need "a hit landed"). The numeric amount is the reward signal and is HIDDEN as a policy input. |
| Enemy killed | `KillEnemy` (`Combat.lua:1757`) then `Kill` (`3043`). `ActiveEnemies[id]` becomes nil at `3310`. `RequiredKillEnemies[id]` becomes nil at `3311`. | `victim.Name`, `victim.RequiredKill`, `triggerArgs.SourceWeapon`, `AttackerTable`. `victim.IsBoss` (from `BaseBossEnemy`, `EnemyData.lua:102`). |
| Room cleared | `CheckForAllEnemiesDead` sets `Encounter.InProgress = false` (`RoomEvents.lua:884`). `StartEncounter` sets `Encounter.Completed = true` (`RoomManager.lua:2557`) after spawns finish. Doors light in `UnlockRoomExits`. | Use `Completed` and `not IsCombatEncounterActive(CurrentRun)`. |
| Run started | `StartNewRun` (`RunManager.lua:217`) builds a fresh `CurrentRun`, equips keepsake, weapon aspect, and `CurrentRun.Money`. | The next `OnAnyLoad` is the first chamber. |
| Death | `KillHero` (`DeathLoop.lua:2`) calls `HandleDeath` (`47`). Sets `CurrentRun.Hero.IsDead = true` and `HandlingDeath = true` (`DeathLoop.lua:61-62`), then loads `"DeathArea"`. | `LastKilledByUnitName` (`DeathLoop.lua:31`). |
| Boss killed | `KillEnemy` on a victim with `IsBoss` or `UseBossHealthBar`. The boss bar hits empty. | `victim.Name`. Phase transitions also call `Kill`-like refills without a final kill; a final kill is `IsDead` and removal from `ActiveEnemies`, not a phase increment. |
| Escaped (beat Hades) | `ShowRunClearScreen` calls `RecordRunCleared` (`RunClearScreen.lua:5`), which sets `CurrentRun.Cleared = true` (`RunManager.lua:1937`). | The clear screen flag `"RunClear"`. `EndRun` (`RunManager.lua:1722`) archives the run and nils `CurrentRun`. |

`OnPlayerDeath` is an engine callback name in `docs/engine_cfuncs.txt`. The script entry the game uses for the hero's death is `KillHero`, not a Lua `OnPlayerDeath{` block. Subscribe to the hero's health hitting 0 or wrap nothing: poll `CurrentRun.Hero.IsDead` and `HandlingDeath`.

---

## 7. Game speed

`AdjustSimulationSpeed({ Fraction = ..., LerpTime = ... })` is only called from `AddSimSpeedChange` and `RemoveSimSpeedChange`:

```lua
function AddSimSpeedChange( name, args )
    if not args.Priority and not IsEmpty( MapState.SimSpeedChanges ) then
        return
    end
    MapState.SimSpeedChanges[name] = args
    AdjustSimulationSpeed({ Fraction = args.Fraction, LerpTime = args.LerpTime })
end

function RemoveSimSpeedChange( name, args )
    MapState.SimSpeedChanges[name] = nil
    if IsEmpty( MapState.SimSpeedChanges ) then
        AdjustSimulationSpeed({ Fraction = 1.0, LerpTime = args.LerpTime })
    end
end
```

`CombatPresentation.lua:2124-2136`. `Fraction` is the simulation speed. `1.0` is normal. Hit-pauses use values such as `0.005` (`LastStand` at `847`) and `0.35` (`LastKill` at `2180`). A dash boon can pass `args.SimulationSlowSpeed` (`Powers.lua:763`).

Callers that add a change: weapon fire (`2048`, name `"WeaponFire"`), weapon cancel (`2065`), weapon hit (`2116`, `"WeaponHit"`), last stand, last kill, chill kill, assists, dash, death presentation (`RoomPresentation.lua:2448`), a Harpy map transition (`RoomPresentation.lua:5183`).

What resets it to 1.0: only `RemoveSimSpeedChange`, and only when the table is empty. A non-priority add is ignored while any change is active (`2125`), so a training speed set by calling `AdjustSimulationSpeed` directly will be overwritten the next time the game adds a hit-pause, and set back to `1.0` when that pause ends.

`OnAnyLoad` replaces `MapState` (`Combat.lua:3875`) and then sets `MapState.SimSpeedChanges = {}` (`Combat.lua:3876`) without calling `AdjustSimulationSpeed`. The Lua bookkeeping is cleared on every room load. Whether the engine speed survives the load is not in these scripts (see Unknowns). Menu open (`OnScreenOpened`, `OnMenuOpened` for `"PauseScreen"`) does not call `AdjustSimulationSpeed`. The pause menu does not reset it in Lua. `PauseGame` is an engine call and these scripts do not use it for the pause screen.

`LeaveRoom` does not touch simulation speed. It does clear every effect on the hero (`RoomManager.lua:4996`).

For training, re-apply the wanted fraction after each `OnAnyLoad` and whenever `MapState.SimSpeedChanges` becomes empty, and do not apply it while that table is non-empty (the game is in a hit-pause). Evaluation runs must use `1.0` (`AGENTS.md` rule 6). Do not wrap `AddSimSpeedChange`; a poller that re-asserts afterwards keeps gameplay intact.

---

## 8. Coordinate system

World positions are `GetLocation` `X` and `Y`, in the same units `GetDistance` and `NotifyWithinDistance` use. `RoomEvents.lua:219` feeds `location.X` and `location.Y` straight into `Teleport` `OffsetX` / `OffsetY`.

The UI is laid out in a 1920 by 1080 space (`UIData.lua:2496-2500`):

```lua
ScreenCenterX = 1920/2
ScreenCenterY = 1080/2
ScreenWidth = 1920
ScreenHeight = 1080
```

Screen-space obstacles pass `UseScreenLocation = true` (`UIScripts.lua:2357`). World HUD (enemy bars) is attached to a unit with `Attach`, group `Combat_UI_World`.

The camera follows the hero:

```lua
LockCamera({ Id = CurrentRun.Hero.ObjectId, Duration = 1.25 })
```

`RoomManager.lua:5496` (end of a pan). Room intro uses `PanCamera` and `FocusCamera`. Zoom is a fraction of the default:

- `CurrentRun.CurrentRoom.ZoomFraction` (per-room, for example `0.75` at `RoomData.lua:134`, `1.0` at `RoomDataTartarus.lua:109`).
- `FocusCamera({ Fraction = ..., Duration = ..., ZoomType = "Ease" })` (`CombatPresentation.lua:844`).
- `AdjustZoom({ Fraction = ..., LerpTime = ... })` (`CombatPresentation.lua:3196`).
- `GetCameraZoom({})` returns a number. `StyxFountainPresentation` multiplies it by `1.05` and passes it back to `FocusCamera` (`EventPresentation.lua:2274-2285`).

There is no world-to-screen function in the engine list or in these scripts. No script reads the mouse position in world units. Aiming is the hero's facing (`GetAngle`), which the engine drives from the cursor while the player is in control. `IsInputAllowed` and `CurrentRun.Hero.FreezeInputKeys` (`UIScripts.lua:2417`) tell you whether that control is live. `AreScreensActive()` and `GetTopScreenName({}) == "PauseScreen"` mean it is not.

A bridge that aims by moving the cursor should treat hero facing as the aim, and treat `GetLocation` deltas as world units. Converting a world point to a pixel is not possible from these scripts alone. See Unknowns.

---

## Unknowns

Not guessed:

1. Live attack-telegraph bit. The decal is created and stopped inside the AI thread (`EnemyAI.lua:104-123`). Nothing stores "the decal is up". `GetAnimationName` is never called. Do not treat it as a telegraph query until someone checks its return value in a running game.
2. Projectile positions after spawn, and projectile ids. No enumeration API. `OnProjectileDeath` has a location only at death.
3. Return shape of `GetMapThings`, `GetMapThingsByType`, `GetEffectTimeRemaining`, `GetWeaponChargeFraction`, `GetUnitProperty`, `GetThingDataValue`. They are engine calls with no script call site that shows the return value.
4. Dash cooldown remaining, and whether any cooldown ring is drawn. No script reads it. `HasEffect` for `RushWeaponDisable` only covers the scripted lock, not the normal cooldown.
5. Whether `GetVelocity` can return a table. Every consumer uses it as a number.
6. World-to-screen scale. `GetCameraZoom` returns a number used as a `FocusCamera` fraction. The scripts never multiply it by a world delta to get pixels. The 1920 by 1080 values are the UI layout, not a measured window size. Retina or fullscreen scaling is not in these scripts.
7. Mouse world position. No API in the script call sites.
8. Whether `AdjustSimulationSpeed` is reset by the engine on `LoadMap` or on the pause menu. Lua clears `MapState.SimSpeedChanges` on load and does not call `AdjustSimulationSpeed` there. Pause does not call it either.
9. `GetTopScreenName` during a Lua overlay (boon menu, dialogue). Those use `ActiveScreens`, not `OpenMenu`. It is unknown whether `GetTopScreenName` stays on the gameplay view or changes. Read `ActiveScreens` for Lua screens.
10. Exact boon options that were rolled but not displayed (`blockedIndexes` in `UpgradeChoice.lua:111`). Read the buttons, not the full roll.
11. Enemy `MaxHealth` and exact `Health` for anyone whose bar does not print a number. Export `DisplayedHealthFraction` (or `Health/MaxHealth` for bosses) only.
12. Future spawns, elite rolls before the unit is set up, unrevealed door rewards (`not door.ReadyToUse`, or `HiddenRoomReward`), Chaos gate contents, shop items before `SpawnStoreItemsInWorld`.
13. `CurrentRun.Hero.InvulnerableFlags` and invulnerability frames (`Combat.lua:1257`). The brief i-frames are not a HUD element. The visual flash exists (`InvulnerabilityFramePresentationStart`) but the flag set is finer than what is drawn. Treat the flags as HIDDEN.
14. `GameState.MetaUpgrades` ranks while the mirror is closed. The player cannot see them mid-run except through effects that are already on the tray or the HUD (extra pips, and so on). Export the ranks only while `"MetaUpgrade"` or `"ShrineUpgrade"` is open, or when the effect is already visible (life pip count, and so on).

## Notes for the bridge

Poll `CurrentRun`, `ActiveEnemies`, `RequiredKillEnemies`, `MapState.ActiveObstacles`, and `OfferedExitDoors` on a `thread` / `wait` loop. Subscribe to `OnAnyLoad`, `OnWeaponFired`, `OnProjectileDeath`, `OnEffectApply`, and `OnEffectCleared` only to maintain lists the poll cannot see (projectiles, effect start times for logging). Do not write those tables.

Export the hero's ceiled HP, the enemy bar fraction (and shield or armour mode), positions, facings, speeds, door icons after `ReadyToUse`, and the open screen's buttons. Keep exact enemy HP, spawn queues, AI timers, unrevealed rewards, and raw `SuperMeter` points in the reward log only.

Re-apply a training `AdjustSimulationSpeed` after loads and after hit-pauses, and leave it at `1.0` whenever `MapState.SimSpeedChanges` is non-empty so the game's own hit-pause still runs. Do not wrap `AddSimSpeedChange`.
