# 011: Mirror of Night - read the screen and spend Darkness
Status: DONE
Owner: Codex

## Goal
On each visit to the House, the agent can open the Mirror of Night in Zagreus's bedroom and buy permanent upgrades with Darkness, survivability first, using only what the mirror screen shows.

## Context (read first)
- `AGENTS.md` (hard rules 2, 4, 5, 7, 8, 9), `collab/STATUS.md`, `docs/plan.md` ("Scope and roadmap", Stage A), `docs/game_state_reference.md` section 5 (the `"MetaUpgrade"` screen, `OpenMetaUpgradeMenu` in `MetaUpgrades.lua`).
- Game scripts, read-only: `~/Library/Application Support/Steam/steamapps/common/Hades/Game.macOS.app/Contents/Resources/Content/Scripts/*.lua` (`MetaUpgrades.lua`, `MetaUpgradeData.lua`, `DeathLoopData.lua` for the bedroom mirror object, `UIData.lua`).
- Bridge mod: `mod/AgentBridge.lua` (sections pattern: `Sections.<name>(obs, info, run)` run under pcall; `SectionOrder`; existing `house` section; `SaveIgnores` rule). Offline Lua 5.2 tests: `tests/test_bridge_mod.py` (lupa stubs).
- Macro layer: `agent/macro/rules.py` (pure decisions, unit-tested), `agent/macro/driver.py` (`Macro`: `walk_to`, `interact`, `click_ui(x, y)` in 1920x1080 UI coordinates, verified live for boon cards).
- House route used by `scripts/run_agent.py`: DeathArea -> DeathAreaBedroom -> RoomPreRun -> new-run door. The mirror is in DeathAreaBedroom.
- Darkness on the HUD/resource display and on the mirror screen is visible; mirror ranks and costs are visible only while the mirror screen is open.

## Scope
May edit: `mod/AgentBridge.lua` (new section(s) only, plus `SectionOrder`), `agent/macro/mirror.py` (new), `agent/macro/__init__.py`, `tests/test_bridge_mod.py` (append tests), `tests/test_mirror*.py` (new), append to `collab/LOG.md`. Must not edit `scripts/run_agent.py` (the lead integrates), `agent/env/**`, `agent/learn/**`, `agent/policy/**`, `agent/bridge/**`, `agent/input/**`, `AGENTS.md`, `collab/STATUS.md`. Do not launch the game, do not post real input, do not install the mod, do not commit.

## Requirements
1. Bridge: while the House is loaded, export the mirror object's id and position (in `obs.house`, e.g. `mirror: {id, x, y}`), and the visible Darkness count. While the `"MetaUpgrade"` screen is open, export `obs.mirror`: each displayed upgrade with its name, current rank, max rank, next-rank cost (as shown), whether it can be bought now, whether it is locked, which of the paired alternatives is selected (if the screen shows that), and the screen position of the button that buys it (1920x1080 UI coordinates via `GetLocation` on the component, like the boon cards). Also the close/back button position. Cite `File.lua:line` in comments. Nothing hidden (no data for upgrades not on screen).
2. Pure rules (`agent/macro/mirror.py`): given `obs.mirror`, pick the next purchase from a priority list (survivability first: Death Defiance, Thick Skin, Chthonic Vitality, Greater Reflex, Infernal Soul, then Shadow Presence, Boiling Blood, then the rest), or None when nothing affordable is worth buying. Use the internal names the game uses (find them in `MetaUpgradeData.lua`). Unit tests.
3. Driver helper (`agent/macro/mirror.py`): `spend_darkness(macro, bridge, max_purchases=10)` that walks to the mirror in the bedroom, interacts, waits for the screen, buys per the rules (clicking the buy button, verifying the rank went up before continuing), closes the screen, and returns a list of purchases. Robust to the screen not opening (returns []), with timeouts.
4. Tests for the new mod section(s) with stubs, including hidden-info isolation (no upgrade data when the screen is closed).

## Acceptance criteria
- `/opt/miniconda3/bin/conda run -n hades python -m pytest -q tests` passes (108 existing + yours); `/opt/miniconda3/bin/conda run -n hades python -m pyflakes scripts agent` clean.
- Report lists: the screen/component structure you relied on (with citations), anything unverified that must be checked live (e.g. whether `GetLocation` works on these components, how purchase confirmation works), and the exact call the lead should add to the House route.

## Report

- `mod/AgentBridge.lua` finds the bedroom's `MetaUpgradeScreen` map object by type and exports its location under `obs.house.mirror` (DeathLoopData.lua:2964-2984, PlayerAIData.lua:215-225, ObstacleData.lua:674-677, MetaUpgrades.lua:92-106). The Darkness total follows the visible HUD resource anchor or Mirror subtitle (UIScripts.lua:585-681, MetaUpgrades.lua:216-221, 1133-1139).
- `obs.mirror` reads the active `MetaUpgrade` screen through `ScreenAnchors.LevelUpScreen` after construction (MetaUpgrades.lua:124-155, 185-186, 363-371, 1736-1754). It reads displayed `BackingN` rows, `RightArrowButtonN` purchase controls, `LockIconN`, the visible swap controls, and `CloseButton` (MetaUpgrades.lua:267-319, 762-929, 972-1015, 1359-1386). The next cost is the one used for the row label. `maxRank` appears when the label shows Maxed. Covered panels and the inactive side's rank and cost are excluded. The new section uses locals and the existing save-ignored bridge table.
- `agent/macro/mirror.py` ranks enabled Darkness purchases in the requested order using the game IDs in MetaUpgradeData.lua:882-896. It asks for one purchase at a time and confirms the same row's increased rank before continuing. The Lua purchase handler directly spends Darkness and applies the rank, then updates the row (MetaUpgrades.lua:1479-1549, 1593-1607). The final-rank presentation can yield before the row updates (UIPresentation.lua:736-755), so the bridge waits for the next-cost data to catch up.
- House-route integration in `scripts/run_agent.py`: import `spend_darkness` from `agent.macro`, then call `purchases = spend_darkness(macro, bridge)` once per `DeathAreaBedroom` entry before walking to the `RoomPreRun` exit. Each confirmed result has `name`, `rank` (new rank) and `cost`. Check that the `MetaUpgrade` flag cleared before resuming movement.
- Verified offline with `/opt/miniconda3/bin/conda run -n hades python -m pytest -q tests` (128 passed, including 13 Mirror tests and the parallel history work), `/opt/miniconda3/bin/conda run -n hades python -m pyflakes scripts agent` (clean), and `git diff --check` (clean).
- Live verification remains with the lead. Check that the bedroom lookup resolves the usable mirror and that walking within 90 world units reaches the interact prompt. Confirm that `GetLocation` on the attached plus and close components returns usable UI coordinates, that a click updates both the displayed rank and Darkness, and that the screen closes and returns control. The implementation was tested without launching the game, posting input, installing the mod, or committing.
