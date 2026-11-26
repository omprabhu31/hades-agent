-- AgentBridge: read-only bridge between Hades and the Python agent.
--
-- Game -> Python: one line per message on stdout, "AGB1 <json>". The game's
-- Lua has no io library, but print() reaches the process's stdout when the
-- game binary is launched directly.
-- Python -> game: the Python side atomically writes runtime/cmd.lua, which
-- returns a table { seq = N, cmd = "...", ... }; loadfile() works on absolute
-- paths even without io. Only non-gameplay commands are accepted.
--
-- Hard rule (AGENTS.md 5): "obs" holds only what a human can see on screen.
-- Anything hidden goes in "info" and may be used for reward/logging only.
-- This file must never change game state other than the simulation speed.

AgentBridge = AgentBridge or {}
local AB = AgentBridge
-- Save() serialises every global table with luabins (Main.lua:1020-1035),
-- and a table holding functions makes the save fail: the game then reports
-- "Corrupted Save Data" (seen live 2026-11-26). Keep the bridge out of saves.
if SaveIgnores ~= nil then SaveIgnores["AgentBridge"] = true end
AB.Version = 2
-- install.sh replaces the placeholder with this checkout's runtime/ folder.
AB.CmdPath = "@@AGENT_RUNTIME@@/cmd.lua"
AB.Interval = 0.05      -- seconds of game time between observations
AB.LastCmdSeq = -1
AB.Frame = 0
AB.Speed = 1.0
AB.Gen = AB.Gen or 0

-- Minimal JSON encoder: tables with only 1..n keys become arrays.
local function encode(v, out)
  local t = type(v)
  if t == "nil" then out[#out + 1] = "null"
  elseif t == "boolean" then out[#out + 1] = v and "true" or "false"
  elseif t == "number" then
    if v ~= v or v == math.huge or v == -math.huge then out[#out + 1] = "null"
    elseif v == math.floor(v) and math.abs(v) < 1e15 then out[#out + 1] = string.format("%d", v)
    else out[#out + 1] = string.format("%.4f", v) end
  elseif t == "string" then
    out[#out + 1] = '"' .. v:gsub('[%c"\\]', function(c)
      if c == '"' then return '\\"' elseif c == "\\" then return "\\\\" end
      return string.format("\\u%04x", c:byte())
    end) .. '"'
  elseif t == "table" then
    local n = #v
    local isArray = true
    for k in pairs(v) do
      if type(k) ~= "number" or k < 1 or k > n or k ~= math.floor(k) then isArray = false break end
    end
    if isArray then
      out[#out + 1] = "["
      for i = 1, n do
        if i > 1 then out[#out + 1] = "," end
        encode(v[i], out)
      end
      out[#out + 1] = "]"
    else
      out[#out + 1] = "{"
      local first = true
      for k, val in pairs(v) do
        if type(val) ~= "function" and type(val) ~= "userdata" then
          if not first then out[#out + 1] = "," end
          first = false
          encode(tostring(k), out)
          out[#out + 1] = ":"
          encode(val, out)
        end
      end
      out[#out + 1] = "}"
    end
  else
    out[#out + 1] = "null"
  end
end

local function emitRaw(kind, payload)
  local out = {}
  encode({ k = kind, f = AB.Frame, d = payload }, out)
  print("AGB1 " .. table.concat(out))
end

-- Never lets an error escape into the game; the fallback uses the same
-- encoder so it is valid JSON too.
function AB.Emit(kind, payload)
  local ok, err = pcall(emitRaw, kind, payload)
  if not ok then pcall(emitRaw, "error", { where = "emit", kind = kind, msg = tostring(err) }) end
end

local function loc(id)
  local ok, l = pcall(GetLocation, { Id = id })
  if ok and l ~= nil then return l.X, l.Y end
  return nil, nil
end

local function round1(x) if x == nil then return nil end return math.floor(x * 10 + 0.5) / 10 end

local function ceil(x) if x == nil then return nil end return math.ceil(x) end
local function frac2(a, b)
  if a == nil or b == nil or b <= 0 then return nil end
  return math.floor(a / b * 100 + 0.5) / 100
end
local function angle(id)
  local ok, a = pcall(GetAngle, { Id = id })
  if ok and type(a) == "number" then return round1(a) end
  return nil
end

-- Each section reads one part of the screen. Sections run under pcall, so a
-- failure in one (an engine call with an unexpected shape) only drops that
-- section and is reported in obs.errors.
-- Citations: docs/game_state_reference.md (task 002).
local Sections = {}

-- Hero: everything here is printed or drawn on the HUD (section 1 of the ref).
function Sections.hero(obs, info, run)
  local hero = run.Hero
  local hx, hy = loc(hero.ObjectId)
  local h = { x = round1(hx), y = round1(hy), angle = angle(hero.ObjectId),
              hp = ceil(hero.Health), maxHp = ceil(hero.MaxHealth),
              dead = hero.IsDead == true, money = run.Money }
  if hero.LastStands ~= nil then h.lastStands = TableLength(hero.LastStands) end
  local okA, ammo = pcall(GetWeaponProperty, { Id = hero.ObjectId, WeaponName = "RangedWeapon", Property = "Ammo" })
  local okM, maxAmmo = pcall(GetWeaponMaxAmmo, { Id = hero.ObjectId, WeaponName = "RangedWeapon" })
  if okA then h.castAmmo = ammo end
  if okM then h.castAmmoMax = maxAmmo end
  -- The call gauge is drawn as pips; raw points are hidden.
  if hero.SuperCost ~= nil and hero.SuperCost > 0 and hero.SuperMeter ~= nil and IsSuperValid ~= nil and IsSuperValid() then
    h.callPips = math.floor(hero.SuperMeter / hero.SuperCost)
    h.callPipPartial = frac2(hero.SuperMeter % hero.SuperCost, hero.SuperCost)
    info.superMeter = hero.SuperMeter
  end
  h.onLava = hero.OnLava == true
  if GetEquippedWeapon ~= nil then h.weapon = GetEquippedWeapon() end
  local traits = {}
  for _, t in ipairs(hero.Traits or {}) do
    if not t.Hidden then  -- hidden traits never appear on the tray
      traits[#traits + 1] = { name = t.Name, rarity = t.Rarity, slot = t.Slot, god = t.God }
    end
  end
  h.traits = traits
  obs.hud = ShowingCombatUI == true
  if not obs.hud then
    -- HUD auto-hidden: its numbers and the boon tray are not on screen.
    for _, k in ipairs({ "hp", "maxHp", "money", "lastStands", "castAmmo", "castAmmoMax",
                         "callPips", "callPipPartial", "traits" }) do h[k] = nil end
  end
  obs.hero = h
  info.heroHealth = hero.Health
end

-- Room: name and biome are shown on doors/the boon list; combat state is
-- visible as live enemies and dark doors (section 4).
function Sections.room(obs, info, run)
  local room = run.CurrentRoom
  if room == nil then return end
  local r = { name = room.Name, biome = room.RoomSetName, exitsUnlocked = room.ExitsUnlocked == true }
  if GetRunDepth ~= nil then r.depth = GetRunDepth(run) end
  if IsCombatEncounterActive ~= nil then r.combat = IsCombatEncounterActive(run) == true end
  obs.room = r
  -- Hidden: future spawns.
  if room.Encounter ~= nil then info.remainingSpawns = room.Encounter.RemainingSpawns end
end

-- Enemies and traps (section 2). Health is exported the way the bar draws it.
function Sections.units(obs, info, run)
  local enemies, traps, breakables = {}, {}, {}
  local allied = HeroData and HeroData.DefaultHero and HeroData.DefaultHero.HeroAlliedUnits or {}
  local exact = {}
  for id, e in pairs(ActiveEnemies or {}) do
    if e ~= nil and not e.IsDead then
      local ex, ey = loc(id)
      if ex ~= nil then
        local name = tostring(e.Name)
        if e.ToggleTrap then
          traps[#traps + 1] = { id = id, name = name, x = round1(ex), y = round1(ey),
                                disabled = (e.AIDisabled or e.DisableAIWhenReady) == true,
                                firedAgo = AB.FiredAgo(id) }
        elseif e.HideHealthBar or name:sub(1, 9) == "Breakable" then
          breakables[#breakables + 1] = { id = id, x = round1(ex), y = round1(ey) }
        elseif not e.Charmed and not allied[name] then
          local u = { id = id, name = name, x = round1(ex), y = round1(ey), angle = angle(id),
                      boss = (e.IsBoss or e.UseBossHealthBar) == true }
          -- Walls and pits are visible on screen; HasLineOfSight is an engine
          -- call no script uses, so its shape is unverified: keep the field
          -- only if it returns a boolean.
          if HasLineOfSight ~= nil then
            local okL, los = pcall(HasLineOfSight, { Id = run.Hero.ObjectId, DestinationId = id })
            if okL and type(los) == "boolean" then u.los = los end
          end
          if u.boss then
            u.hpFrac = frac2(e.Health, e.MaxHealth)
            u.phase = e.CurrentPhase
          elseif e.HitShields ~= nil and e.HitShields > 0 then
            u.hpFrac = 1
            u.shields = e.HitShields
          elseif e.HealthBuffer ~= nil and e.HealthBuffer > 0 then
            u.armorFrac = frac2(e.HealthBuffer, e.MaxHealthBuffer)
          else
            u.hpFrac = frac2(e.Health, e.MaxHealth)
          end
          if e.IsElite then
            u.elite = true
            local attrs = {}
            for _, a in ipairs(e.EliteAttributes or {}) do attrs[#attrs + 1] = a end
            u.eliteAttrs = attrs
          end
          u.firedAgo = AB.FiredAgo(id)
          enemies[#enemies + 1] = u
          exact[#exact + 1] = { id = id, hp = e.Health, armor = e.HealthBuffer }
        end
      end
    end
  end
  obs.enemies, obs.traps, obs.breakables = enemies, traps, breakables
  obs.shots = AB.RecentShots()
  info.enemyHealth = exact  -- hidden exact values, reward only
end

-- Exit doors: position always; the reward only once the icon is lit (section 4).
function Sections.doors(obs, info, run)
  local doors = {}
  for id, door in pairs(OfferedExitDoors or {}) do
    local dx, dy = loc(id)
    if dx ~= nil then
      local d = { id = id, x = round1(dx), y = round1(dy), lit = door.ReadyToUse == true }
      if d.lit and door.Room ~= nil then
        local room = door.Room
        if room.NextRoomSet ~= nil then d.reward = "BiomeExit"
        elseif HasHeroTraitValue ~= nil and HasHeroTraitValue("HiddenRoomReward") then d.reward = "Hidden"
        elseif room.ChosenRewardType == nil then d.reward = "Story"
        else
          d.reward = room.ChosenRewardType
          d.god = room.ForceLootName
          if room.ChosenRewardType == "Devotion" then d.gods = { room.LootAName, room.LootBName } end
        end
        -- The reroll prompt is drawn only when rerolls remain (UIScripts.lua:2039).
        d.reroll = door.CanBeRerolled == true and (run.NumRerolls or 0) > 0
      end
      doors[#doors + 1] = d
    end
  end
  obs.doors = doors
end

-- Pickups lying in the room: boon/hammer/pom orbs (LootObjects,
-- RoomManager.lua:2873) and consumables such as coins and hearts (group
-- "ConsumableItems", Interactables.lua:952). Both are drawn with a label or
-- icon. "blocking" means the exit stays shut until it is collected, which the
-- game shows with the locked-door text.
function Sections.pickups(obs, info, run)
  local items = {}
  for id, loot in pairs(LootObjects or {}) do
    local x, y = loc(id)
    if x ~= nil then
      items[#items + 1] = { id = id, kind = "loot", name = loot.Name, x = round1(x), y = round1(y),
                            blocking = ActivatedObjects ~= nil and ActivatedObjects[id] ~= nil }
    end
  end
  local okIds, ids = pcall(GetIds, { Name = "ConsumableItems" })
  if okIds and type(ids) == "table" then
    for _, id in ipairs(ids) do
      local x, y = loc(id)
      if x ~= nil then
        items[#items + 1] = { id = id, kind = "consumable", x = round1(x), y = round1(y),
                              blocking = ActivatedObjects ~= nil and ActivatedObjects[id] ~= nil }
      end
    end
  end
  obs.pickups = items
end

-- Open screens (section 5): Lua overlays in ActiveScreens, plus the boon menu
-- buttons that are actually displayed.
function Sections.screens(obs, info, run)
  local open = {}
  for flag, v in pairs(ActiveScreens or {}) do
    if v then open[#open + 1] = tostring(flag) end
  end
  table.sort(open)
  obs.screens = open
  if ActiveScreens ~= nil and ActiveScreens.BoonMenu and ScreenAnchors ~= nil and ScreenAnchors.ChoiceScreen ~= nil then
    local screen = ScreenAnchors.ChoiceScreen
    local comps = screen.Components or {}
    local options = {}
    for i = 1, 6 do
      local b = comps["PurchaseButton" .. i]
      if b ~= nil then
        local bx, by = loc(b.Id)
        local trait = b.Data and (b.Data.Name or b.Data.ItemName) or b.UpgradeName
        local opt = b.LootData and b.LootData.UpgradeOptions and b.LootData.UpgradeOptions[i]
        local locked = opt ~= nil and opt.Blocked == true  -- drawn greyed out (UpgradeChoice.lua:290)
        options[#options + 1] = { index = i, name = trait, god = b.UpgradeName, type = b.Type,
                                  rarity = b.Data and b.Data.Rarity, locked = locked, x = round1(bx), y = round1(by) }
      end
    end
    obs.boonMenu = { subject = screen.SubjectName, options = options }
  end
end

-- The House between runs (DeathArea*, RoomPreRun). CurrentRun.CurrentRoom
-- still names the room the hero died in, so report the loaded map instead,
-- plus the exits a player walks through: the courtyard door
-- (DeathAreaSwitchRoom, DeathLoopData.lua:3951) and the new-run door
-- (UseEscapeDoor / type NewRunDoor, DeathLoopData.lua:6200, PlayerAIData.lua:184).
local function isHouseMap(map)
  return type(map) == "string" and (map == "RoomPreRun" or map:sub(1, 9) == "DeathArea")
end

function Sections.house(obs, info, run)
  local okMap, map = pcall(GetMapName, {})
  if not okMap or not isHouseMap(map) then return end
  obs.room = { name = map, house = true, combat = false }
  obs.doors, obs.enemies, obs.pickups = {}, {}, {}
  local exits, seen = {}, {}
  for id, o in pairs(MapState and MapState.ActiveObstacles or {}) do
    local fn = o.OnUsedFunctionName
    if fn == "DeathAreaSwitchRoom" or fn == "UseEscapeDoor" then
      local x, y = loc(id)
      if x ~= nil then
        seen[id] = true
        exits[#exits + 1] = { id = id, x = round1(x), y = round1(y),
                              kind = fn == "UseEscapeDoor" and "run" or "room",
                              to = o.OnUsedFunctionArgs and o.OnUsedFunctionArgs.Name }
      end
    end
  end
  -- House rooms declare their doors per object id in the room's ObstacleData
  -- (DeathLoopData.lua), which is not always mirrored in ActiveObstacles.
  local houseRoom = CurrentDeathAreaRoom
  for id, data in pairs(houseRoom and houseRoom.ObstacleData or {}) do
    local fn = type(data) == "table" and data.OnUsedFunctionName or nil
    if (fn == "DeathAreaSwitchRoom" or fn == "UseEscapeDoor") and not seen[id] then
      local x, y = loc(id)
      if x ~= nil then
        seen[id] = true
        exits[#exits + 1] = { id = id, x = round1(x), y = round1(y),
                              kind = fn == "UseEscapeDoor" and "run" or "room",
                              to = data.OnUsedFunctionArgs and data.OnUsedFunctionArgs.Name }
      end
    end
  end
  local okIds, ids = pcall(GetIdsByType, { Name = "NewRunDoor" })
  if okIds and type(ids) == "table" then
    for _, id in ipairs(ids) do
      local x, y = loc(id)
      if x ~= nil and not seen[id] then
        exits[#exits + 1] = { id = id, x = round1(x), y = round1(y), kind = "run" }
      end
    end
  end
  obs.house = { map = map, exits = exits }
end

function Sections.mirror(obs, info, run)
  if obs.screen == "PauseScreen" then return end
  local house = obs.house
  local anchors = ScreenAnchors or {}
  local resources = GameState and GameState.Resources or {}
  if house ~= nil then
    if house.map == "DeathAreaBedroom" then
      -- The bedroom's usable map object is MetaUpgradeScreen
      -- (PlayerAIData.lua:215-225, ObstacleData.lua:674-677, MetaUpgrades.lua:92-106).
      local okIds, ids = pcall(GetIdsByType, { Name = "MetaUpgradeScreen" })
      if okIds and type(ids) == "table" then
        for _, id in ipairs(ids) do
          local x, y = loc(id)
          if x ~= nil and y ~= nil then
            house.mirror = { id = id, x = round1(x), y = round1(y) }
            break
          end
        end
      end
    end
    -- Darkness is only readable while its resource text is shown
    -- (UIScripts.lua:585-665, 668-681).
    if obs.hud and anchors.ResourceShowing and anchors.ResourceShowing.MetaPoints
      and anchors.ResourceAnchorIds and anchors.ResourceAnchorIds.MetaPoints then
      house.darkness = resources.MetaPoints
    end
  end

  -- The active flag is set before construction and cleared on close
  -- (MetaUpgrades.lua:124-155, 185-186, 363-371, 1736-1754).
  local screen = anchors.LevelUpScreen
  if not (ActiveScreens and ActiveScreens.MetaUpgrade and screen and screen.KeepOpen) then return end
  local comps = screen.Components
  local menu = { upgrades = {} }
  if comps.SubTitle then
    -- MetaUpgrades.lua:216-221, 1133-1139.
    menu.darkness = resources.MetaPoints or 0
    if house then house.darkness = menu.darkness end
  end
  if comps.CloseButton then
    -- MetaUpgrades.lua:267-272.
    local x, y = loc(comps.CloseButton.Id)
    if x ~= nil and y ~= nil then menu.close = { x = round1(x), y = round1(y) } end
  end
  -- Follow the displayed rows, including sealed rows with disabled plus
  -- buttons. Covered panels have no UpgradeValueTotal component
  -- (MetaUpgrades.lua:278-359, 762-872, 2088-2106).
  local index = 1
  while comps["Backing" .. index] do
    local button = comps["RightArrowButton" .. index]
    local rankButton = button and button.HandleType == "Add"
    local name = rankButton and button.Data.Name
    if screen.ReadOnly and comps["UpgradeValueTotal" .. index] then
      -- The read-only viewer draws the row with no buy button (MetaUpgrades.lua:281-308, 866-930).
      name = GameState.MetaUpgradesSelected[index]
    end
    if name then
      local locked = comps["LockIcon" .. index] ~= nil
      local nextCost
      if rankButton and not locked then nextCost = button.Data.NextCost end
      -- A final-rank animation can yield before the visible row updates
      -- (MetaUpgrades.lua:1530-1535, 1593-1607; UIPresentation.lua:736-755).
      if not rankButton or locked or nextCost == GetMetaUpgradePurchasePrice(button.Data) then
        local rank = GetNumMetaUpgrades(name)
        local row = { name = name, rank = rank, locked = locked, nextCost = nextCost,
                      canBuy = rankButton == true and not locked and nextCost ~= nil and button.LastEnabled == true }
        if rankButton then
          local x, y = loc(button.Id)
          row.x, row.y = round1(x), round1(y)
          -- The cost label reveals the cap when it reads Maxed (MetaUpgrades.lua:1359-1386).
          if not locked and nextCost == nil then row.maxRank = rank end
        end
        if comps["Backing" .. index .. "Swap"] then
          -- The current side is visible via the swap control and row colour
          -- (MetaUpgrades.lua:841-845, 877-912; MetaUpgradeData.lua:882-896).
          row.selected = name
        end
        menu.upgrades[#menu.upgrades + 1] = row
      end
    end
    index = index + 1
  end
  obs.mirror = menu
end

-- GetUseData is called as the active use prompt is drawn (UIScripts.lua:2008-2022,
-- 2120-2162, 2214-2238). Keep just the labels it put on screen, keyed by the
-- live unit so a new room cannot inherit an old prompt for a reused object id.
local houseUseLabels = setmetatable({}, { __mode = "k" })
local getUseData = GetUseData
if type(getUseData) == "function" then
  GetUseData = function(unit, ...)
    local data = getUseData(unit, ...)
    -- Recording must never disturb the game's UI path, so it runs under pcall.
    pcall(function()
      if unit ~= nil and unit.CanReceiveGift and data ~= nil then
        houseUseLabels[unit] = { talk = data.BaseUseText ~= nil and data.BaseUseText ~= "Blank",
                                 gift = data.GiftAvailable, amount = data.GiftResourceAmount }
      end
    end)
    return data
  end
end

local function houseObject(id)
  if id == nil then return nil end
  local x, y = loc(id)
  if x ~= nil and y ~= nil then return { id = id, x = round1(x), y = round1(y) } end
end

local function giftPrompt(unit)
  local label = houseUseLabels[unit]
  if label == nil or label.amount == nil or label.gift == nil then return nil end
  -- Classify the rendered gift icon/text, including Cerberus's shared Gift/Pet
  -- prompt (GiftData.lua:48-71, NPCData.lua:5367-5374). A custom label shared
  -- across currencies does not reveal which resource it would spend.
  local matched
  for _, resource in ipairs({ "GiftPoints", "SuperGiftPoints" }) do
    local custom = unit.GiftText
    local customText = type(custom) == "table" and custom[resource] or custom
    local icon = GiftIconData and GiftIconData[resource]
    if label.gift == customText or (icon and label.gift == icon.GiftText) then
      if matched then return nil end
      matched = resource
    end
  end
  if matched then return { resource = matched, amount = label.amount } end
end

function Sections.houseGifts(obs, info, run)
  local house = obs.house
  if house == nil or obs.screen == "PauseScreen" then return end
  local anchors = ScreenAnchors or {}
  if #obs.screens == 0 then
    -- An NPC must be a live, activated member of the game's NPC use group
    -- (RoomEvents.lua:162-197, RoomManager.lua:4041-4046, 4198-4199,
    -- Interactables.lua:230).
    local characters = {}
    local prompts = anchors.UsePrompts or {}
    local onlyPrompt = next(prompts)
    if onlyPrompt ~= nil and next(prompts, onlyPrompt) ~= nil then onlyPrompt = nil end
    for id, unit in pairs(ActiveEnemies or {}) do
      if unit.Groups and Contains(unit.Groups, "NPCs") and IsAlive({ Id = id }) then
        local row = houseObject(id)
        if row then
          row.name = GetGenusName(unit)
          row.usePrompt = prompts[id] ~= nil
          row.promptTarget = onlyPrompt == id
          if row.usePrompt then
            row.giftPrompt = giftPrompt(unit)
            local label = houseUseLabels[unit]
            row.talkPrompt = label ~= nil and label.talk
          end
          characters[#characters + 1] = row
        end
      end
    end
    table.sort(characters, function(a, b) return a.id < b.id end)
    house.characters = characters

    if house.map == "RoomPreRun" then
      -- The courtyard runs UpdateGiftRackShineStatus, which locates this type
      -- (DeathLoopData.lua:5839, 5850, 6014-6016, AwardMenuScripts.lua:1-19).
      local okIds, ids = pcall(GetIdsByType, { Name = "GiftRack" })
      if okIds and type(ids) == "table" then
        house.keepsakeRack = houseObject(ids[1])
        if house.keepsakeRack then
          house.keepsakeRack.usePrompt = prompts[ids[1]] ~= nil
          house.keepsakeRack.promptTarget = onlyPrompt == ids[1]
        end
      end
    end
  end

  -- Resource count and equipped icon only while their HUD anchors are drawn
  -- (UIScripts.lua:585-681, 1265-1339, 1558-1604).
  if obs.hud and anchors.ResourceShowing and anchors.ResourceShowing.GiftPoints
    and anchors.ResourceAnchorIds and anchors.ResourceAnchorIds.GiftPoints then
    house.nectar = GameState.Resources.GiftPoints
  end
  if obs.hud and #obs.screens == 0 and anchors.TraitBacking then
    for _, trait in pairs(run.Hero.Traits or {}) do
      if trait.Slot == "Keepsake" and not trait.Hidden and trait.AnchorId and IdExists({ Id = trait.AnchorId }) then
        house.equippedKeepsake = trait.Name
        break
      end
    end
  end

  local screen = anchors.AwardMenuScreen
  if #obs.screens ~= 1 or obs.screens[1] ~= "AwardMenu" or not (screen and screen.KeepOpen) then return end
  local comps = screen.Components
  local menu = { keepsakes = {}, close = comps.CloseButton and houseObject(comps.CloseButton.Id) }
  local index = 1
  -- Numbered UpgradeToggle buttons are keepsakes; companions have a
  -- Legendary suffix. The unknown slots have no name (AwardMenuScripts.lua:
  -- 250-281, 359-424, 560-574). The selected frame follows the new choice,
  -- while LastTrait is the selection when the menu opened (236, 669-681, 742-766).
  while comps["UpgradeToggle" .. index] do
    local button = comps["UpgradeToggle" .. index]
    local unlocked = button.Data.Unlocked == true
    local selected = unlocked and screen.SelectedFrame ~= nil and button.Data.Gift == GameState.LastAwardTrait
    local row = houseObject(button.Id) or {}
    row.index = index
    row.locked = not unlocked or button.Blocked == true
    row.available = not row.locked
    row.equipped = selected
    if unlocked then row.name = button.Data.Gift end
    if selected then menu.equipped = row.name end
    menu.keepsakes[#menu.keepsakes + 1] = row
    index = index + 1
  end
  obs.awardMenu = menu
end

local SectionOrder = { "hero", "room", "units", "doors", "pickups", "screens", "house", "mirror", "houseGifts" }

-- Builds the observation. Everything in obs is on screen for a human;
-- hidden values go in info (reward and logging only, AGENTS.md rule 5).
function AB.Snapshot()
  local obs = { screen = nil }
  local info = {}
  local okScreen, screen = pcall(GetTopScreenName, {})
  if okScreen then obs.screen = screen end
  -- Nothing of the world is drawn behind these screens.
  if obs.screen == "LoadScreen" then
    obs.inRun = false
    obs.loading = true
    return obs, info
  end
  local run = CurrentRun
  if run == nil or run.Hero == nil or run.Hero.ObjectId == nil then
    obs.inRun = false
    return obs, info
  end
  obs.inRun = true
  for _, name in ipairs(SectionOrder) do
    local ok, err = pcall(Sections[name], obs, info, run)
    if not ok then
      obs.errors = obs.errors or {}
      obs.errors[#obs.errors + 1] = name .. ": " .. tostring(err)
    end
  end
  info.depth = run.RunDepthCache
  return obs, info
end

-- Training speed. The game sets its own hit-pauses with AddSimSpeedChange and
-- resets to 1.0 when they end (CombatPresentation.lua:2124-2136). We never
-- touch its bookkeeping; we re-assert our speed only while no game speed
-- change is active, i.e. on load and after each hit-pause ends.
function AB.MaintainSpeed()
  local busy = MapState ~= nil and MapState.SimSpeedChanges ~= nil and not IsEmpty(MapState.SimSpeedChanges)
  -- Hit-pauses can be shorter than one poll, so with a training speed set,
  -- re-assert every tick outside a pause rather than only on its end.
  if not busy and (AB.SpeedDirty or AB.WasBusy or AB.Speed ~= 1.0) then
    AdjustSimulationSpeed({ Fraction = AB.Speed, LerpTime = 0 })
    AB.SpeedDirty = false
  end
  AB.WasBusy = busy
end

-- Commands accepted from Python. None of them changes gameplay.
local Commands = {
  ping = function(c)
    -- probe reports whether the command file ran in an empty environment
    AB.Emit("pong", { seq = c.seq, probe = c.probe })
  end,
  speed = function(c)
    local v = tonumber(c.value) or 1.0
    if v ~= v then v = 1.0 end
    if v < 0.1 then v = 0.1 elseif v > 10 then v = 10 end
    AB.Speed = v
    AB.SpeedDirty = true
    AB.MaintainSpeed()
    AB.Emit("ack", { seq = c.seq, cmd = "speed", value = v })
  end,
  interval = function(c)
    local v = tonumber(c.value) or 0.05
    if v ~= v or v > 1 then v = 0.05 end
    if v < 0.01 then v = 0.01 end
    AB.Interval = v
    AB.Emit("ack", { seq = c.seq, cmd = "interval", value = v })
  end,
}

function AB.PollCommand()
  -- The command file is data from our own Python side. Lua 5.2's loadfile
  -- takes an environment: an empty one means the file can only build a
  -- table, never call game functions. Text mode only (no bytecode).
  local okLoad, chunk = pcall(loadfile, AB.CmdPath, "t", {})
  if not okLoad or type(chunk) ~= "function" then return end
  local okRun, c = pcall(chunk)
  if not okRun or type(c) ~= "table" or type(c.seq) ~= "number" or c.seq ~= c.seq then return end
  if c.seq <= AB.LastCmdSeq then return end
  AB.LastCmdSeq = c.seq
  local handler = Commands[c.cmd]
  if handler == nil then
    AB.Emit("ack", { seq = c.seq, error = "unknown command" })
    return
  end
  local ok, err = pcall(handler, c)
  if not ok then AB.Emit("ack", { seq = c.seq, error = tostring(err) }) end
end

-- Each map load starts a new loop; a generation number makes any loop left
-- over from the previous map exit instead of emitting duplicates.
function AB.Loop(gen)
  while AB.Gen == gen do
    AB.Frame = AB.Frame + 1
    -- Commands are rare; polling every 5th frame keeps file loads cheap.
    if AB.Frame % 5 == 0 then pcall(AB.PollCommand) end
    if AB.Speed ~= 1.0 or AB.SpeedDirty then pcall(AB.MaintainSpeed) end
    local ok, obs, info = pcall(AB.Snapshot)
    if ok then
      AB.Emit("obs", { obs = obs, info = info, speed = AB.Speed })
    else
      AB.Emit("error", { where = "snapshot", msg = tostring(obs) })
    end
    wait(AB.Interval)
  end
end

-- Wrap a game function to emit an event first; the original always runs
-- with the same arguments and its results are returned unchanged.
local function hook(name, kind, describe)
  local base = _G[name]
  if type(base) ~= "function" or AB["hooked_" .. name] then return end
  AB["hooked_" .. name] = true
  _G[name] = function(...)
    local args = { ... }
    pcall(function() AB.Emit("event", { type = kind, detail = describe and describe((table.unpack or unpack)(args)) or nil }) end)
    return base(...)
  end
end

hook("StartNewRun", "run_start")
hook("StartRoom", "room_start", function(run, room) return { room = room and room.Name } end)
hook("DoUnlockRoomExits", "room_cleared", function(run, room) return { room = room and room.Name } end)
hook("KillEnemy", "enemy_killed", function(victim) return { name = victim and victim.Name, boss = victim and victim.IsBoss == true } end)
hook("KillHero", "hero_died")
hook("RecordRunCleared", "run_cleared")
hook("LeaveRoom", "leave_room")

-- Enemy attacks (task 014). The swing or projectile is drawn the moment a
-- weapon fires, so "this unit just attacked" and where a shot left from is
-- visible. The game itself registers several OnWeaponFired handlers
-- (Combat.lua:70, 2259; Powers.lua:7, ...); this one only records, never
-- waits and never writes triggerArgs or game state. Projectile positions
-- after launch are not readable (docs/game_state_reference.md section 3),
-- so a shot is exported as origin + direction + age; the policy can learn
-- each projectile's travel from its name.
AB.Fired = AB.Fired or {}
AB.Shots = AB.Shots or {}
AB.AttackMemory = 40  -- frames (2 s of game time at the default interval)

function AB.FiredAgo(id)
  local f = AB.Fired[id]
  if f == nil then return nil end
  local age = AB.Frame - f
  if age > AB.AttackMemory then return nil end
  return math.floor(age * AB.Interval * 100 + 0.5) / 100  -- seconds of game time
end

function AB.RecentShots()
  local out, keep = {}, {}
  for _, shot in ipairs(AB.Shots) do
    local age = AB.Frame - shot.frame
    if age <= AB.AttackMemory then
      keep[#keep + 1] = shot
      out[#out + 1] = { owner = shot.owner, name = shot.name, x = shot.x, y = shot.y, angle = shot.angle,
                        age = math.floor(age * AB.Interval * 100 + 0.5) / 100 }
    end
  end
  AB.Shots = keep
  return out
end

OnWeaponFired{ function(triggerArgs)
  pcall(function()
    local owner = triggerArgs.OwnerTable
    if owner == nil or owner.ObjectId == nil or CurrentRun == nil or CurrentRun.Hero == nil
      or owner.ObjectId == CurrentRun.Hero.ObjectId then return end
    AB.Fired[owner.ObjectId] = AB.Frame
    if triggerArgs.ProjectileName ~= nil then
      local x, y = loc(owner.ObjectId)
      if x ~= nil then
        AB.Shots[#AB.Shots + 1] = { owner = owner.ObjectId, name = tostring(triggerArgs.ProjectileName),
                                    x = round1(x), y = round1(y), angle = angle(owner.ObjectId), frame = AB.Frame }
        if #AB.Shots > 32 then table.remove(AB.Shots, 1) end
      end
    end
  end)
end }

OnAnyLoad{ function(triggerArgs)
  AB.Gen = AB.Gen + 1
  AB.Fired, AB.Shots = {}, {}  -- ids are per map
  AB.SpeedDirty = AB.Speed ~= 1.0  -- re-apply after every map load
  thread(AB.Loop, AB.Gen)
end }

AB.Emit("hello", { version = AB.Version })
