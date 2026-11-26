-- Spike 2: which loaders exist, whether loadfile can read a file outside the
-- game (that would give a Python -> Lua command channel), and the engine's
-- C functions. Read-only: changes no game state.
local CMD = "/Users/om-prabhu/projects/hades-agent/runtime/cmd.lua"
local function p(s) print("AGENTBRIDGE_SPIKE " .. s) end
p("types loadfile=" .. type(loadfile) .. " dofile=" .. type(dofile) .. " load=" .. type(load) ..
  " require=" .. type(require) .. " debug=" .. type(debug) .. " string=" .. type(string) ..
  " coroutine=" .. type(coroutine))
if loadfile then
  local ok, f, err = pcall(loadfile, CMD)
  p("loadfile ok=" .. tostring(ok) .. " f=" .. type(f) .. " err=" .. tostring(err))
  if ok and type(f) == "function" then
    local ok2, r = pcall(f)
    p("cmd result ok=" .. tostring(ok2) .. " r=" .. tostring(r))
  end
end
if debug and debug.getinfo then
  local names = {}
  for k, v in pairs(_G) do
    if type(v) == "function" and debug.getinfo(v, "S").what == "C" then names[#names + 1] = k end
  end
  table.sort(names)
  p("cfuncs n=" .. #names)
  for i = 1, #names, 40 do p("cfuncs " .. table.concat(names, " ", i, math.min(i + 39, #names))) end
end

local tick = 0
thread(function()
  while true do
    wait(0.5)
    tick = tick + 1
    if CurrentRun ~= nil and CurrentRun.Hero ~= nil and CurrentRun.Hero.ObjectId ~= nil then
      local ok, loc = pcall(GetLocation, { Id = CurrentRun.Hero.ObjectId })
      p(string.format("hero ok=%s x=%s y=%s hp=%s/%s room=%s", tostring(ok),
        tostring(ok and loc and loc.X), tostring(ok and loc and loc.Y),
        tostring(CurrentRun.Hero.Health), tostring(CurrentRun.Hero.MaxHealth),
        tostring(CurrentRun.CurrentRoom and CurrentRun.CurrentRoom.Name)))
    elseif tick % 10 == 0 then
      p("tick " .. tick .. " no hero")
    end
  end
end)
