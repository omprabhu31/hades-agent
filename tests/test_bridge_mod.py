"""Run mod/AgentBridge.lua in a stock Lua (lupa) with stubbed game functions."""
import json
from pathlib import Path

import pytest

lupa52 = pytest.importorskip("lupa.lua52")  # the game runs Lua 5.2
from agent.bridge import lua_literal, parse_line

MOD = Path(__file__).resolve().parents[1] / "mod" / "AgentBridge.lua"

STUBS = r"""
printed = {}
SaveIgnores = {}
function print(s) printed[#printed + 1] = s end
threads = {}
function thread(fn, ...) threads[#threads + 1] = { fn = fn, args = { ... } } end
function wait() coroutine.yield() end
loadHooks = {}
function OnAnyLoad(t) loadHooks[#loadHooks + 1] = t[1] end
firedHooks = {}
function OnWeaponFired(t) firedHooks[#firedHooks + 1] = t[1] end
locs = { [1] = { X = 10.04, Y = -5 }, [7] = { X = 1, Y = 2 } }
function GetLocation(a) return locs[a.Id] end
speeds = {}
function AdjustSimulationSpeed(a) speeds[#speeds + 1] = a.Fraction end
calls = {}
function StartRoom(run, room) calls[#calls + 1] = "StartRoom:" .. room.Name; return "orig" end
function KillEnemy(v) calls[#calls + 1] = "KillEnemy" end
secret = 0
function DangerousGameFn() secret = secret + 1 end
CurrentRun = { Hero = { ObjectId = 1, Health = 39.2, MaxHealth = 50, LastStands = { {}, {} },
                        Traits = { { Name = "SwordBaseUpgrade", Rarity = "Common", Slot = "Melee", God = "Zeus", Secret = 1 } } },
               Money = 12,
               CurrentRoom = { Name = "A_Combat01" }, RunDepthCache = 3 }
ActiveEnemies = { [7] = { Name = "Skelly \"q\"", Health = 25, MaxHealth = 100 },
                  [8] = { Name = "BreakableAsphodel", Health = 1, MaxHealth = 1 },
                  [9] = { Name = "Ghost", Health = 5, MaxHealth = 10 } }  -- no location
locs[8] = { X = 3, Y = 4 }
function TableLength(t) local n = 0 for _ in pairs(t) do n = n + 1 end return n end
function IsEmpty(t) return next(t) == nil end
function GetAngle(a) return 90 end
function GetWeaponProperty(a) return 2 end
function GetWeaponMaxAmmo(a) return 3 end
function GetEquippedWeapon() return "SwordWeapon" end
function GetRunDepth(run) return 4 end
function IsCombatEncounterActive(run) return true end
ShowingCombatUI = true
MapState = { SimSpeedChanges = {} }
OfferedExitDoors = {}
ActiveScreens = {}
HeroData = { DefaultHero = { HeroAlliedUnits = { Dusa = true } } }
topScreen = "Hud"
function GetTopScreenName() return topScreen end
"""


@pytest.fixture
def lua(tmp_path):
    class Rt(lupa52.LuaRuntime):
        cmd_path = None
    rt = Rt(unpack_returned_tuples=True)
    rt.execute(STUBS)
    src = MOD.read_text().replace(
        '"@@AGENT_RUNTIME@@/cmd.lua"', json.dumps(str(tmp_path / "cmd.lua")))
    rt.execute(src)
    rt.cmd_path = tmp_path / "cmd.lua"
    return rt


def messages(rt):
    out = []
    for s in rt.globals().printed.values():
        m = parse_line(s)
        assert m is not None and m.kind != "bad_json", s
        out.append(m)
    return out


def run_one_tick(rt):
    """Fire OnAnyLoad and step the started loop once."""
    rt.execute("for _, h in ipairs(loadHooks) do h({}) end")
    rt.execute("co = coroutine.create(threads[#threads].fn); assert(coroutine.resume(co, table.unpack(threads[#threads].args)))")


def test_hello_and_observation_are_valid_json(lua):
    run_one_tick(lua)
    msgs = messages(lua)
    assert msgs[0].kind == "hello"
    obs = [m for m in msgs if m.kind == "obs"][-1].data
    assert "errors" not in obs["obs"], obs["obs"].get("errors")
    assert obs["obs"]["hero"] == {
        "x": 10.0, "y": -5, "angle": 90, "hp": 40, "maxHp": 50, "dead": False, "money": 12,
        "lastStands": 2, "castAmmo": 2, "castAmmoMax": 3, "onLava": False, "weapon": "SwordWeapon",
        "traits": [{"name": "SwordBaseUpgrade", "rarity": "Common", "slot": "Melee", "god": "Zeus"}]}
    assert obs["obs"]["enemies"] == [
        {"id": 7, "name": 'Skelly "q"', "x": 1, "y": 2, "angle": 90, "hpFrac": 0.25, "boss": False}]
    assert obs["obs"]["room"] == {"name": "A_Combat01", "exitsUnlocked": False, "depth": 4, "combat": True}
    assert obs["obs"]["breakables"] == [{"id": 8, "x": 3, "y": 4}]
    assert obs["obs"]["screen"] == "Hud"
    # Hidden values stay out of obs.
    assert obs["info"]["depth"] == 3 and obs["info"]["heroHealth"] == 39.2
    assert obs["info"]["enemyHealth"] == [{"id": 7, "hp": 25}]
    assert "39.2" not in json.dumps(obs["obs"])
    assert all("hp" not in e for e in obs["obs"]["enemies"])


def test_hooks_emit_event_and_call_original(lua):
    assert lua.eval('StartRoom(nil, { Name = "R1" })') == "orig"
    assert list(lua.globals().calls.values()) == ["StartRoom:R1"]
    ev = [m for m in messages(lua) if m.kind == "event"][-1]
    assert ev.data == {"type": "room_start", "detail": {"room": "R1"}}


def test_speed_command_applied_once(lua):
    lua.cmd_path.write_text("return " + lua_literal({"seq": 5, "cmd": "speed", "value": 3.0}))
    poll(lua)
    lua.execute("AgentBridge.PollCommand()")  # same seq again: ignored
    speeds = list(lua.globals().speeds.values())
    assert speeds and set(speeds) == {3}  # applied (and re-asserted each tick), never anything else
    acks = [m for m in messages(lua) if m.kind == "ack"]
    assert len(acks) == 1 and acks[0].data["value"] == 3


def test_command_file_cannot_call_game_functions(lua):
    lua.cmd_path.write_text('DangerousGameFn(); return { seq = 1, cmd = "ping" }')
    lua.execute("AgentBridge.PollCommand()")
    assert lua.globals().secret == 0
    assert not [m for m in messages(lua) if m.kind == "pong"]


def test_unknown_command_is_rejected(lua):
    lua.cmd_path.write_text('return { seq = 2, cmd = "teleport" }')
    lua.execute("AgentBridge.PollCommand()")
    ack = [m for m in messages(lua) if m.kind == "ack"][-1]
    assert ack.data["error"] == "unknown command"


def test_lua_literal_round_trip(lua):
    lit = lua_literal({"seq": 1, "cmd": "x\"y\n", "value": 2.5, "flags": [True, None]})
    t = lua.execute("return " + lit)
    assert t.seq == 1 and t.cmd == 'x"y\n' and t.value == 2.5


def test_load_screen_hides_world(lua):
    lua.execute('topScreen = "LoadScreen"')
    run_one_tick(lua)
    obs = [m for m in messages(lua) if m.kind == "obs"][-1].data["obs"]
    assert obs == {"screen": "LoadScreen", "inRun": False, "loading": True}


def poll(lua):
    lua.execute("AgentBridge.Frame = 4")
    run_one_tick(lua)  # frame 5 polls commands


def test_command_env_is_empty(lua):
    # In an empty environment even print is nil.
    lua.cmd_path.write_text('return { seq = 3, cmd = "ping", probe = (print == nil) }')
    lua.execute("AgentBridge.PollCommand()")
    pong = [m for m in messages(lua) if m.kind == "pong"][-1]
    assert pong.data == {"seq": 3, "probe": True}


def test_non_finite_speed_falls_back_to_normal(lua):
    lua.cmd_path.write_text('return { seq = 4, cmd = "speed", value = 0/0 }')
    lua.execute("AgentBridge.PollCommand()")
    assert list(lua.globals().speeds.values()) == [1.0]


def test_bytecode_command_rejected(lua):
    lua.execute('local f = io.open(%s, "wb"); f:write(string.dump(load("return { seq = 9, cmd = \'ping\' }"))); f:close()'
                % json.dumps(str(lua.cmd_path)))
    lua.execute("AgentBridge.PollCommand()")
    assert not [m for m in messages(lua) if m.kind == "pong"]


def test_emit_failure_does_not_escape(lua):
    lua.execute("""
      local calls = 0
      local real = print
      function print(s) calls = calls + 1; if calls == 1 then error("boom") end; real(s) end
      AgentBridge.Emit("x", {})
      print = real
    """)
    err = [m for m in messages(lua) if m.kind == "error"][-1]
    assert err.data["where"] == "emit" and "boom" in err.data["msg"]


def test_parse_line_rejects_non_object():
    assert parse_line("AGB1 [1,2]").kind == "bad_json"
    assert parse_line("AGB1 null").kind == "bad_json"
    assert parse_line("noise AGB1 {}") is None


def test_enemy_kinds_and_bar_modes(lua):
    lua.execute("""
      locs[20] = { X = 0, Y = 0 }; locs[21] = { X = 0, Y = 0 }; locs[22] = { X = 0, Y = 0 }
      locs[23] = { X = 0, Y = 0 }; locs[24] = { X = 0, Y = 0 }
      ActiveEnemies = {
        [20] = { Name = "SpikeTrap", ToggleTrap = true, Health = 1, MaxHealth = 1 },
        [21] = { Name = "Dusa", Health = 1, MaxHealth = 1 },
        [22] = { Name = "Shielded", HitShields = 2, Health = 5, MaxHealth = 10 },
        [23] = { Name = "Armored", HealthBuffer = 30, MaxHealthBuffer = 40, Health = 10, MaxHealth = 10,
                 IsElite = true, EliteAttributes = { "Blink" } },
        [24] = { Name = "Meg", IsBoss = true, Health = 50, MaxHealth = 200, CurrentPhase = 1 },
      }
    """)
    run_one_tick(lua)
    obs = [m for m in messages(lua) if m.kind == "obs"][-1].data["obs"]
    by = {e["name"]: e for e in obs["enemies"]}
    assert set(by) == {"Shielded", "Armored", "Meg"}
    assert by["Shielded"]["hpFrac"] == 1 and by["Shielded"]["shields"] == 2
    assert by["Armored"]["armorFrac"] == 0.75 and "hpFrac" not in by["Armored"]
    assert by["Armored"]["eliteAttrs"] == ["Blink"]
    assert by["Meg"]["boss"] is True and by["Meg"]["hpFrac"] == 0.25
    assert obs["traps"] == [{"id": 20, "name": "SpikeTrap", "x": 0, "y": 0, "disabled": False}]


def test_door_reward_only_when_lit(lua):
    lua.execute("""
      locs[30] = { X = 5, Y = 6 }; locs[31] = { X = 7, Y = 8 }
      OfferedExitDoors = {
        [30] = { ReadyToUse = false, Room = { ChosenRewardType = "Boon", ForceLootName = "ZeusUpgrade" } },
        [31] = { ReadyToUse = true, CanBeRerolled = true, Room = { ChosenRewardType = "Boon", ForceLootName = "AresUpgrade" } },
      }
    """)
    run_one_tick(lua)
    doors = {d["id"]: d for d in [m for m in messages(lua) if m.kind == "obs"][-1].data["obs"]["doors"]}
    assert doors[30] == {"id": 30, "x": 5, "y": 6, "lit": False}
    assert doors[31]["reward"] == "Boon" and doors[31]["god"] == "AresUpgrade"
    assert doors[31]["reroll"] is False  # no rerolls left: the sparkle is not drawn


def test_boon_menu_lists_displayed_buttons(lua):
    lua.execute("""
      locs[40] = { X = 900, Y = 370 }
      ActiveScreens = { BoonMenu = true }
      ScreenAnchors = { ChoiceScreen = { SubjectName = "ZeusUpgrade", Components = {
        PurchaseButton1 = { Id = 40, UpgradeName = "ZeusUpgrade", Type = "Trait", Data = { Name = "ZeusWeaponTrait", Rarity = "Rare" } } } } }
    """)
    run_one_tick(lua)
    obs = [m for m in messages(lua) if m.kind == "obs"][-1].data["obs"]
    assert obs["screens"] == ["BoonMenu"]
    assert obs["boonMenu"] == {"subject": "ZeusUpgrade", "options": [
        {"index": 1, "name": "ZeusWeaponTrait", "god": "ZeusUpgrade", "type": "Trait", "rarity": "Rare",
         "locked": False, "x": 900, "y": 370}]}


def test_speed_reasserted_after_hit_pause(lua):
    lua.cmd_path.write_text('return { seq = 6, cmd = "speed", value = 2 }')
    poll(lua)
    def n():
        return len(list(lua.globals().speeds.values()))
    assert n() >= 1 and set(lua.globals().speeds.values()) == {2}
    # game starts a hit-pause: we must not touch speed while it runs
    before = n()
    lua.execute('MapState.SimSpeedChanges = { WeaponHit = {} }; AgentBridge.MaintainSpeed(); AgentBridge.MaintainSpeed()')
    assert n() == before
    # pause over (game set 1.0): we re-apply 2, and keep re-asserting every tick
    lua.execute('MapState.SimSpeedChanges = {}; AgentBridge.MaintainSpeed(); AgentBridge.MaintainSpeed()')
    assert n() == before + 2 and set(lua.globals().speeds.values()) == {2}
    # back to normal speed for evaluation: applied once, then left alone
    lua.execute('AgentBridge.Speed = 1.0; AgentBridge.SpeedDirty = true; AgentBridge.MaintainSpeed(); AgentBridge.MaintainSpeed()')
    assert list(lua.globals().speeds.values())[-1] == 1.0 and n() == before + 3


def test_pickups(lua):
    lua.execute("""
      locs[50] = { X = 1, Y = 1 }; locs[51] = { X = 2, Y = 2 }
      LootObjects = { [50] = { Name = "ZeusUpgrade" } }
      ActivatedObjects = { [50] = {} }
      function GetIds(a) if a.Name == "ConsumableItems" then return { 51 } end return {} end
    """)
    run_one_tick(lua)
    obs = [m for m in messages(lua) if m.kind == "obs"][-1].data["obs"]
    assert obs["pickups"] == [
        {"id": 50, "kind": "loot", "name": "ZeusUpgrade", "x": 1, "y": 1, "blocking": True},
        {"id": 51, "kind": "consumable", "x": 2, "y": 2, "blocking": False}]


def test_house_overrides_stale_room(lua):
    lua.execute("""
      function GetMapName() return "DeathArea" end
      locs[60] = { X = 10, Y = 20 }; locs[61] = { X = 30, Y = 40 }
      MapState.ActiveObstacles = {
        [60] = { OnUsedFunctionName = "DeathAreaSwitchRoom", OnUsedFunctionArgs = { Name = "RoomPreRun" } } }
      function GetIdsByType(a) if a.Name == "NewRunDoor" then return { 61 } end return {} end
    """)
    run_one_tick(lua)
    obs = [m for m in messages(lua) if m.kind == "obs"][-1].data["obs"]
    assert obs["room"] == {"name": "DeathArea", "house": True, "combat": False}
    assert obs["enemies"] == [] and obs["doors"] == []
    assert obs["house"]["exits"] == [
        {"id": 60, "x": 10, "y": 20, "kind": "room", "to": "RoomPreRun"},
        {"id": 61, "x": 30, "y": 40, "kind": "run"}]


def test_bridge_is_excluded_from_game_saves(lua):
    # Hades pickles every global not in SaveIgnores; functions inside a table break the save.
    assert lua.eval('SaveIgnores["AgentBridge"]') is True
    bad = lua.eval("""(function()
      for k, v in pairs(_G) do
        if type(v) == "table" and not SaveIgnores[k] and k ~= "_G" and k:sub(1, 1) ~= "_" then
          for _, x in pairs(v) do if type(x) == "function" and k == "AgentBridge" then return k end end
        end
      end
      return nil end)()""")
    assert bad is None


def test_hud_hidden_drops_hud_fields_and_hidden_traits(lua):
    lua.execute("""ShowingCombatUI = nil
      CurrentRun.Hero.Traits[2] = { Name = "Secret", Hidden = true }""")
    run_one_tick(lua)
    h = [m for m in messages(lua) if m.kind == "obs"][-1].data["obs"]["hero"]
    assert "hp" not in h and "money" not in h and "traits" not in h and "x" in h
    lua.execute("ShowingCombatUI = true")
    run_one_tick(lua)
    h = [m for m in messages(lua) if m.kind == "obs"][-1].data["obs"]["hero"]
    assert [t["name"] for t in h["traits"]] == ["SwordBaseUpgrade"]


def test_hidden_room_reward_masks_door(lua):
    lua.execute("""locs[70] = { X = 1, Y = 1 }
      function HasHeroTraitValue(k) return k == "HiddenRoomReward" end
      OfferedExitDoors = { [70] = { ReadyToUse = true, Room = { ChosenRewardType = "Boon", ForceLootName = "ZeusUpgrade" } } }""")
    run_one_tick(lua)
    d = [m for m in messages(lua) if m.kind == "obs"][-1].data["obs"]["doors"][0]
    assert d["reward"] == "Hidden" and "god" not in d


MIRROR_STUBS = """
mapName = "DeathAreaBedroom"
function GetMapName() return mapName end
function GetIdsByType(a)
  if a.Name == "MetaUpgradeScreen" then return { 80 } end
  return {}
end
locs[80] = { X = 480, Y = 190 }
locs[81] = { X = 954, Y = 996 }
locs[82] = { X = 1155, Y = 372 }
locs[83] = { X = 1155, Y = 417 }
locs[84] = { X = 1155, Y = 462 }
locs[85] = { X = 1155, Y = 507 }
GameState = {
  Resources = { MetaPoints = 62, LockKeys = 15 },
  MetaUpgrades = { StaminaMetaUpgrade = 1, UnseenMetaUpgrade = 4 },
  MetaUpgradesSelected = { "DoorHealMetaUpgrade", "HealthMetaUpgrade",
                           "StaminaMetaUpgrade", "FirstStrikeMetaUpgrade", "UnseenMetaUpgrade" },
}
function GetNumMetaUpgrades(name) return GameState.MetaUpgrades[name] or 0 end
function GetMetaUpgradePurchasePrice(data) return data.CostTable[GetNumMetaUpgrades(data.Name) + 1] end
ScreenAnchors = {
  ResourceShowing = { MetaPoints = true },
  ResourceAnchorIds = { MetaPoints = 86 },
  LevelUpScreen = {
    KeepOpen = true,
    Components = {
      CloseButton = { Id = 81 }, SubTitle = { Id = 87 },
      Backing1 = {}, Backing2 = {}, Backing3 = {}, Backing4 = {},
      RightArrowButton1 = { Id = 82, HandleType = "Add", LastEnabled = true,
                           Data = { Name = "DoorHealMetaUpgrade", NextCost = 10, CostTable = { 10, 20, 40 } } },
      RightArrowButton2 = { Id = 83, HandleType = "Add", LastEnabled = true,
                           Data = { Name = "HealthMetaUpgrade", NextCost = 40, CostTable = { 40, 45 } } },
      LockIcon2 = {},
      RightArrowButton3 = { Id = 84, HandleType = "Add", LastEnabled = false,
                           Data = { Name = "StaminaMetaUpgrade", CostTable = { 50 } } },
      RightArrowButton4 = { Id = 85, HandleType = "Add", LastEnabled = false,
                           Data = { Name = "FirstStrikeMetaUpgrade", NextCost = 70, CostTable = { 70, 90 } } },
      Backing4Swap = { Name = "FirstStrikeMetaUpgrade" },
      LockBacking5 = {},
    }
  }
}
"""


def test_mirror_is_located_in_bedroom_and_only_visible_darkness_is_exported(lua):
    lua.execute(MIRROR_STUBS)
    obs, _ = lua.eval("AgentBridge.Snapshot()")
    assert obs.house.mirror.id == 80 and obs.house.mirror.x == 480 and obs.house.mirror.y == 190
    assert obs.house.darkness == 62
    assert obs.mirror is None  # Even if the screen anchor and saved ranks still exist.

    lua.execute('ScreenAnchors.ResourceShowing.MetaPoints = false')
    obs, _ = lua.eval("AgentBridge.Snapshot()")
    assert obs.house.darkness is None and obs.mirror is None

    lua.execute('mapName = "RoomPreRun"; ScreenAnchors.ResourceShowing.MetaPoints = true')
    obs, _ = lua.eval("AgentBridge.Snapshot()")
    assert obs.house.mirror is None and obs.house.darkness == 62


def test_mirror_menu_projects_only_visible_rows_and_controls(lua):
    lua.execute(MIRROR_STUBS)
    lua.execute('ActiveScreens.MetaUpgrade = {}; ShowingCombatUI = false')
    run_one_tick(lua)
    obs = [m for m in messages(lua) if m.kind == "obs"][-1].data["obs"]
    assert "errors" not in obs
    assert obs["house"]["darkness"] == 62
    assert obs["mirror"] == {
        "darkness": 62,
        "close": {"x": 954, "y": 996},
        "upgrades": [
            {"name": "DoorHealMetaUpgrade", "rank": 0, "nextCost": 10, "canBuy": True,
             "locked": False, "x": 1155, "y": 372},
            {"name": "HealthMetaUpgrade", "rank": 0, "canBuy": False, "locked": True, "x": 1155, "y": 417},
            {"name": "StaminaMetaUpgrade", "rank": 1, "maxRank": 1, "canBuy": False,
             "locked": False, "x": 1155, "y": 462},
            {"name": "FirstStrikeMetaUpgrade", "rank": 0, "nextCost": 70, "canBuy": False,
             "locked": False, "selected": "FirstStrikeMetaUpgrade", "x": 1155, "y": 507},
        ],
    }


def test_mirror_waits_for_opening_and_purchase_redraw(lua):
    lua.execute(MIRROR_STUBS)
    lua.execute("ActiveScreens.MetaUpgrade = {}; ScreenAnchors.LevelUpScreen.KeepOpen = nil")
    obs, _ = lua.eval("AgentBridge.Snapshot()")
    assert obs.mirror is None

    lua.execute("ScreenAnchors.LevelUpScreen.KeepOpen = true; GameState.MetaUpgrades.DoorHealMetaUpgrade = 1")
    obs, _ = lua.eval("AgentBridge.Snapshot()")
    assert all(row.name != "DoorHealMetaUpgrade" for row in obs.mirror.upgrades.values())

    lua.execute("ScreenAnchors.LevelUpScreen.Components.RightArrowButton1.Data.NextCost = 20")
    obs, _ = lua.eval("AgentBridge.Snapshot()")
    assert obs.mirror.upgrades[1].rank == 1 and obs.mirror.upgrades[1].nextCost == 20

    lua.execute('ActiveScreens.MetaUpgrade = nil; ShowingCombatUI = false')
    obs, _ = lua.eval("AgentBridge.Snapshot()")
    assert obs.mirror is None and obs.house.darkness is None


def test_read_only_mirror_has_no_purchase_controls(lua):
    lua.execute(MIRROR_STUBS)
    lua.execute("""
      ActiveScreens.MetaUpgrade = {}
      ShowingCombatUI = false
      local screen = ScreenAnchors.LevelUpScreen
      screen.ReadOnly = true
      screen.Components = { CloseButton = { Id = 81 }, Backing1 = {}, UpgradeValueTotal1 = {} }
    """)
    obs, _ = lua.eval("AgentBridge.Snapshot()")
    assert obs.house.darkness is None and obs.mirror.darkness is None
    assert [dict(row) for row in obs.mirror.upgrades.values()] == [
        {"name": "DoorHealMetaUpgrade", "rank": 0, "canBuy": False, "locked": False},
    ]


HOUSE_GIFT_STUBS = """
mapName = "DeathArea"
function GetMapName() return mapName end
function GetIdsByType(a)
  if a.Name == "GiftRack" then return { 90 } end
  return {}
end
function Contains(t, wanted)
  for _, v in ipairs(t) do if v == wanted then return true end end
  return false
end
function IsAlive(a) return a.Id ~= 92 end
function IdExists(a) return a.Id == 98 end
function GetGenusName(unit) return unit.GenusName or unit.Name end
function GetUseData(unit) return unit.DrawnUseData end
function CanReceiveGift() error("The bridge must not recompute gift eligibility") end
function GetNextGiftResource() error("The bridge must not query hidden gift data") end
GiftIconData = { GiftPoints = { GiftText = "GiftUseText" },
                 SuperGiftPoints = { GiftText = "SuperGiftUseText" } }
locs[90] = { X = 480, Y = 190 }
locs[91] = { X = 34.07, Y = 180.23 }
locs[92] = { X = 41, Y = 195 }
locs[93] = { X = 60, Y = 211 }
locs[94] = { X = 205, Y = 280 }
locs[95] = { X = 323, Y = 280 }
locs[96] = { X = 441, Y = 280 }
locs[97] = { X = 960, Y = 1030 }
ActiveEnemies[91] = {
  Name = "NPC_Cerberus_01", Groups = { "NPCs", "EnemyTeam" }, CanReceiveGift = true,
  GiftText = { GiftPoints = "CerberusGiftAndPetText", SuperGiftPoints = "CerberusSuperGiftAndPetText" },
  DrawnUseData = { BaseUseText = "UseTalkToCerberus", GiftAvailable = "CerberusGiftAndPetText",
                   GiftResourceAmount = 1 },
}
ActiveEnemies[92] = { Name = "DeadNPC", Groups = { "NPCs" } }
ActiveEnemies[93] = { Name = "NonNPC", Groups = { "EnemyTeam" } }
GameState = {
  Gift = { NPC_Cerberus_01 = { Value = 5 }, HiddenNPC = { Value = 4 } },
  Resources = { GiftPoints = 3, SuperGiftPoints = 50 },
  LastAwardTrait = "MaxHealthKeepsakeTrait",
}
CurrentRun.Hero.Traits[2] = { Name = "MaxHealthKeepsakeTrait", Slot = "Keepsake", AnchorId = 98 }
ScreenAnchors = {
  UsePrompts = {},
  ResourceShowing = { GiftPoints = true },
  ResourceAnchorIds = { GiftPoints = 100 },
  AwardMenuScreen = {
    KeepOpen = true, LastTrait = "OldSelection", SelectedFrame = 99,
    Components = {
      UpgradeToggle1 = { Id = 94, Data = { Gift = "MaxHealthKeepsakeTrait", Unlocked = true } },
      UpgradeToggle2 = { Id = 95, Data = { Gift = "HiddenKeepsake", Unlocked = false } },
      UpgradeToggle3 = { Id = 96, Data = { Gift = "ReincarnationTrait", Unlocked = true }, Blocked = true },
      UpgradeToggle1Legendary = { Id = 93, Data = { Gift = "HiddenCompanion", Unlocked = true } },
      CloseButton = { Id = 97 },
    }
  },
}
"""


@pytest.fixture
def house_lua():
    rt = lupa52.LuaRuntime(unpack_returned_tuples=True)
    rt.execute(STUBS + HOUSE_GIFT_STUBS)
    rt.execute(MOD.read_text())
    return rt


def test_house_gift_uses_drawn_prompt_and_visible_nectar_only(house_lua):
    obs, _ = house_lua.eval("AgentBridge.Snapshot()")
    npc = obs.house.characters[1]
    assert len(obs.house.characters) == 1 and npc.name == "NPC_Cerberus_01"
    assert (npc.id, npc.x, npc.y) == (91, 34.1, 180.2)
    assert npc.giftPrompt is None and npc.usePrompt is False
    assert obs.house.nectar == 3 and obs.house.keepsakeRack is None
    assert obs.house.equippedKeepsake is None and obs.awardMenu is None

    house_lua.execute("""
      local npc = ActiveEnemies[91]
      assert(GetUseData(npc) == npc.DrawnUseData)
      ScreenAnchors.UsePrompts[91] = 101
      GameState.Gift.NPC_Cerberus_01.Value = 8
      npc.DrawnUseData.GiftAvailable = "CerberusSuperGiftAndPetText"
      npc.DrawnUseData.GiftResourceAmount = 2
      ScreenAnchors.ResourceShowing.GiftPoints = false
    """)
    obs, _ = house_lua.eval("AgentBridge.Snapshot()")
    npc = obs.house.characters[1]
    assert obs.house.nectar is None and npc.talkPrompt is True
    assert npc.usePrompt is True and npc.promptTarget is True
    assert dict(npc.giftPrompt) == {"resource": "GiftPoints", "amount": 1}

    house_lua.execute("GetUseData(ActiveEnemies[91]); ScreenAnchors.UsePrompts[90] = 102")
    obs, _ = house_lua.eval("AgentBridge.Snapshot()")
    npc = obs.house.characters[1]
    assert npc.usePrompt is True and npc.promptTarget is False
    assert dict(npc.giftPrompt) == {"resource": "SuperGiftPoints", "amount": 2}

    house_lua.execute('ActiveScreens.Dialog = {}')
    obs, _ = house_lua.eval("AgentBridge.Snapshot()")
    assert obs.house.characters is None and obs.awardMenu is None
    house_lua.execute('ActiveScreens.Dialog = nil; ActiveEnemies[91] = nil')
    obs, _ = house_lua.eval("AgentBridge.Snapshot()")
    assert len(obs.house.characters) == 0


def test_house_rack_names_and_selection_follow_drawn_icons(house_lua):
    house_lua.execute('mapName = "RoomPreRun"; ScreenAnchors.UsePrompts[90] = 102')
    obs, _ = house_lua.eval("AgentBridge.Snapshot()")
    assert dict(obs.house.keepsakeRack) == {"id": 90, "x": 480, "y": 190, "usePrompt": True, "promptTarget": True}
    assert obs.awardMenu is None and obs.house.equippedKeepsake is None

    house_lua.execute("ShowingCombatUI = false; ActiveScreens.AwardMenu = {}")
    run_one_tick(house_lua)
    obs = [m for m in messages(house_lua) if m.kind == "obs"][-1].data["obs"]
    assert "errors" not in obs
    assert "nectar" not in obs["house"] and "keepsakeRack" not in obs["house"]
    assert obs["awardMenu"] == {
        "close": {"id": 97, "x": 960, "y": 1030},
        "equipped": "MaxHealthKeepsakeTrait",
        "keepsakes": [
            {"id": 94, "index": 1, "name": "MaxHealthKeepsakeTrait", "x": 205, "y": 280,
             "available": True, "locked": False, "equipped": True},
            {"id": 95, "index": 2, "x": 323, "y": 280, "available": False, "locked": True, "equipped": False},
            {"id": 96, "index": 3, "name": "ReincarnationTrait", "x": 441, "y": 280,
             "available": False, "locked": True, "equipped": False},
        ],
    }
    house_lua.execute("ScreenAnchors.AwardMenuScreen.SelectedFrame = nil")
    obs, _ = house_lua.eval("AgentBridge.Snapshot()")
    assert obs.awardMenu.equipped is None

    house_lua.execute('ActiveScreens.MetaUpgrade = {}; ShowingCombatUI = true')
    obs, _ = house_lua.eval("AgentBridge.Snapshot()")
    assert obs.awardMenu is None
    house_lua.execute('ActiveScreens = {}; ScreenAnchors.TraitBacking = 103')
    obs, _ = house_lua.eval("AgentBridge.Snapshot()")
    assert obs.awardMenu is None and obs.house.equippedKeepsake == "MaxHealthKeepsakeTrait"
    house_lua.execute('topScreen = "PauseScreen"')
    obs, _ = house_lua.eval("AgentBridge.Snapshot()")
    assert obs.house.equippedKeepsake is None and obs.awardMenu is None


def fire(lua, owner, projectile=None):
    proj = 'nil' if projectile is None else '"%s"' % projectile
    lua.execute("for _, h in ipairs(firedHooks) do h({ OwnerTable = { ObjectId = %d }, name = 'W', ProjectileName = %s }) end"
                % (owner, proj))


def test_only_visible_attackers_count_and_ages_use_world_time(lua):
    lua.execute("_worldTime = 10; locs[99] = { X = 5, Y = 5 }")  # 99 has a position but is not listed
    run_one_tick(lua)                      # enemy 7 is listed: a visible attacker
    fire(lua, 7, "BoneShot")
    fire(lua, 99, "LavaSplash")            # not listed (e.g. a lava tile): ignored
    fire(lua, 1, "Slash")                  # the hero: ignored
    lua.execute("_worldTime = 10.4; AgentBridge.Interval = 0.2")  # interval change must not matter
    fired, nshots, shot_owner, shot_age, has_obs_shots = lua.eval("""(function()
      local o, i = AgentBridge.Snapshot()
      return o.enemies[1].firedAgo, #i.shots, i.shots[1].owner, i.shots[1].age, o.shots ~= nil end)()""")
    assert fired == 0.4 and nshots == 2 and shot_owner == 7 and shot_age == 0.4
    assert has_obs_shots is False          # shots are logging-only
    assert lua.eval("AgentBridge.Fired[99]") is None


def test_attack_memory_expires_and_reload_clears(lua):
    lua.execute("_worldTime = 0")
    run_one_tick(lua)
    fire(lua, 7, "P")
    lua.execute("_worldTime = 2.1")
    assert lua.eval("AgentBridge.Snapshot().enemies[1].firedAgo") is None
    assert lua.eval("#select(2, AgentBridge.Snapshot()).shots") == 0
    fire(lua, 7)
    lua.execute("for _, h in ipairs(loadHooks) do h({}) end")
    assert lua.eval("next(AgentBridge.Fired)") is None and lua.eval("next(AgentBridge.VisibleAttackers)") is None
