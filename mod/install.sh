#!/bin/bash
# Installs the bridge: copies mod/AgentBridge.lua into the game's Scripts
# folder and appends one Import line to RoomManager.lua. Only this file can be
# installed. Reversed by mod/uninstall.sh.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
S="$HOME/Library/Application Support/Steam/steamapps/common/Hades/Game.macOS.app/Contents/Resources/Content/Scripts"
B="$ROOT/backups/game-originals"
NAME="AgentBridge.lua"
LINE="Import \"$NAME\""
mkdir -p "$B" "$ROOT/runtime"
if pgrep -x Game.macOS >/dev/null; then echo "refusing: Hades is running" >&2; exit 1; fi
# If the live RoomManager.lua has none of our Import lines it is the stock
# file (possibly updated by Steam), so it becomes the backup.
if ! grep -q '^Import "AgentBridge' "$S/RoomManager.lua"; then
  cp -p "$S/RoomManager.lua" "$B/RoomManager.lua.tmp" && mv "$B/RoomManager.lua.tmp" "$B/RoomManager.lua"
fi
[ -f "$B/RoomManager.lua" ] || { echo "no pristine RoomManager.lua backup" >&2; exit 1; }
# Stage both files, then swap them in.
# Point the mod's command mailbox at this checkout's runtime/ folder.
sed "s#@@AGENT_RUNTIME@@#$ROOT/runtime#" "$ROOT/mod/$NAME" > "$S/.$NAME.tmp"
{ cat "$B/RoomManager.lua"; printf '\n%s\n' "$LINE"; } > "$S/.RoomManager.lua.tmp"
mv "$S/.$NAME.tmp" "$S/$NAME"
mv "$S/.RoomManager.lua.tmp" "$S/RoomManager.lua"
echo "installed $NAME"
