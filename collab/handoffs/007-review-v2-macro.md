# 007: Review bridge v2, pickups and the macro layer
Status: DONE
Owner: Grok (reviewer); author: Claude

## Goal
A severity-ranked review of the lead's latest code, checked against the game's scripts and `docs/game_state_reference.md` (which you wrote).

## Context
- Read `AGENTS.md` (rules 5 visible-only, 7 single instance) and `collab/STATUS.md`.
- Under review: `mod/AgentBridge.lua` (sections `hero`, `room`, `units`, `doors`, `pickups`, `screens`, and `AB.MaintainSpeed`), `agent/bridge/tail.py`, `agent/macro/rules.py`, `agent/macro/driver.py`, tests `tests/test_bridge_mod.py`, `tests/test_macro_rules.py`.
- Game scripts (read-only): `~/Library/Application Support/Steam/steamapps/common/Hades/Game.macOS.app/Contents/Resources/Content/Scripts/*.lua`.
- Live facts: bridge v2 verified in the opening room (hero HUD fields, room, lit door); calibration says world angles equal screen angles, world y grows downwards.

## Scope
Read-only. Create only `collab/reviews/007-review-v2-macro.md`; append to `collab/LOG.md`. Do not edit code, do not launch the game (one instance is running, only one is allowed), do not send input, do not touch the game folder, do not commit.

## Check especially
1. Hidden-information leaks in each section versus your reference (e.g. `room.combat`, `exitsUnlocked`, `depth`, `traits` fields, consumables, `blocking`).
2. Wrong field names or engine-call shapes (e.g. `GetIds({ Name = "ConsumableItems" })`, `GetWeaponMaxAmmo`, `IsSuperValid()`, `ScreenAnchors.ChoiceScreen` persisting after the menu closes, `ActiveScreens` values).
3. `AB.MaintainSpeed`: correct against `AddSimSpeedChange` / `RemoveSimSpeedChange`? Any way it fights a hit-pause or leaves the game sped up at evaluation time?
4. Macro: is `ui_to_window` right for the boon buttons' `GetLocation` coordinates (are screen components located in 1920x1080 UI space)? Door/pickup interaction ranges; anything in the game flow (dialogue, boon pickup, door use) the driver will trip on.
5. Test gaps.

## Acceptance criteria
`collab/reviews/007-review-v2-macro.md` with findings ranked critical/major/minor/nit, each with file:line, failure scenario and suggested fix; unknowns listed separately.

## Report
Changes needed. Review: `collab/reviews/007-review-v2-macro.md`. Critical: door rewards use `HeroHasTrait("HiddenRoomReward")` instead of `HasHeroTraitValue`, so the Chaos curse's question-mark doors export the real reward. Major: HUD and hidden traits exported while the tray is hidden; boon `name` is the loot id (`ZeusUpgrade`) so the slot heuristic never sees the trait; locked Approval Process cards are clickable; training speed falls to 1.0 after a short hit-pause while the payload still reports the training speed (evaluation set to 1.0 is not left sped up); dialogue, fountains and a single interact stall or report a false door take; the boon click lands during the menu's 0.5s ignore window. 28 unit tests passed; they stub the wrong button field. Game not launched.
