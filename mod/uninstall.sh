#!/bin/bash
# Restores the stock RoomManager.lua and removes the bridge files.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
S="$HOME/Library/Application Support/Steam/steamapps/common/Hades/Game.macOS.app/Contents/Resources/Content/Scripts"
B="$ROOT/backups/game-originals"
if pgrep -x Game.macOS >/dev/null; then echo "refusing: Hades is running" >&2; exit 1; fi
if grep -q '^Import "AgentBridge' "$S/RoomManager.lua"; then
  [ -f "$B/RoomManager.lua" ] || { echo "refusing: backup missing; use Steam 'Verify integrity'" >&2; exit 1; }
  cp -p "$B/RoomManager.lua" "$S/RoomManager.lua"
fi
rm -f "$S/AgentBridge.lua" "$S/AgentBridgeSpike.lua"
echo "uninstalled"
