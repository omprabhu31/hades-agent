"""Live macro actions: walking, interacting, menus. Uses the bridge + Controller."""
from __future__ import annotations

import math
import time

from agent.input import Action

from .rules import choose_boon_option, choose_door, ui_to_window, world_dir_to_movement


class MacroError(RuntimeError):
    pass


class Macro:
    def __init__(self, bridge, controller, window_bounds) -> None:
        self.bridge = bridge
        self.c = controller
        self.bounds = window_bounds  # agent.input.controller.Bounds of the game window

    def obs(self) -> dict:
        o = self.bridge.policy_obs()
        if o is None:
            raise MacroError("no observation")
        return o

    def hero_xy(self) -> tuple[float, float]:
        h = self.obs().get("hero") or {}
        return h.get("x"), h.get("y")

    def walk_to(self, x: float, y: float, radius: float = 90.0, timeout: float = 10.0) -> bool:
        """Walk in a straight line (8 directions) until within radius.

        If progress stalls (a wall), sidestep with the neighbouring direction
        for a moment. Returns True when arrived.
        """
        deadline = time.monotonic() + timeout
        last_d, stall_t, stalls = None, time.monotonic(), 0
        try:
            while time.monotonic() < deadline:
                hx, hy = self.hero_xy()
                if hx is None:
                    return False
                dist = math.hypot(x - hx, y - hy)
                if dist <= radius:
                    return True
                if last_d is not None and last_d - dist < 5:
                    if time.monotonic() - stall_t > 0.4:
                        # Stuck. Pots (breakables) often block doorways, so
                        # first swing towards the target, then sidestep 90
                        # degrees, alternating sides on repeated stalls.
                        self.c.apply(Action(aim=self._aim_towards(hx, hy, x, y)))
                        self.c.tap("attack", hold_s=0.06)
                        time.sleep(0.25)
                        sign = 1 if (stalls % 2 == 0) else -1
                        side = world_dir_to_movement(-sign * (y - hy), sign * (x - hx))
                        self.c.apply(Action(movement=side))
                        time.sleep(0.3)
                        stalls += 1
                        stall_t = time.monotonic()
                else:
                    stall_t = time.monotonic()
                last_d = dist
                self.c.apply(Action(movement=world_dir_to_movement(x - hx, y - hy)))
                time.sleep(0.05)
            return False
        finally:
            self.c.apply(Action())

    def _aim_towards(self, hx, hy, tx, ty) -> tuple[float, float]:
        theta = math.atan2(-(ty - hy), tx - hx)
        r = 0.25 * self.bounds.height
        return (0.5 + r * math.cos(theta) / self.bounds.width,
                0.5 - r * math.sin(theta) / self.bounds.height)

    def interact(self) -> None:
        self.c.tap("interact", hold_s=0.08)

    def click_ui(self, x: float, y: float) -> None:
        u, v = ui_to_window(x, y, self.bounds.width, self.bounds.height)
        self.c.apply(Action(aim=(u, v)))
        time.sleep(0.15)
        self.c.tap("attack", hold_s=0.06)

    # -- composite steps ------------------------------------------------------
    def pick_boon(self) -> dict | None:
        menu = self.obs().get("boonMenu")
        choice = choose_boon_option(menu)
        if choice is None:
            return None
        self.click_ui(choice["x"], choice["y"])
        return choice

    def collect_pickups(self) -> int:
        """Walk to and use every pickup; returns how many were attempted."""
        n = 0
        for p in sorted(self.obs().get("pickups") or [], key=lambda p: not p.get("blocking")):
            if self.walk_to(p["x"], p["y"], radius=60):
                self.interact()
                n += 1
                time.sleep(0.8)
                if (self.obs().get("screens") or []):
                    break  # a menu opened (boon choice); caller handles it
        return n

    def take_door(self) -> dict | None:
        door = choose_door(self.obs())
        if door is None:
            return None
        self.walk_to(door["x"], door["y"], radius=120, timeout=15)
        hx, hy = self.hero_xy()
        # Doors in alcoves cannot always be reached to 120 units, but the use
        # prompt works from further away; try whenever reasonably close.
        if hx is not None and math.hypot(door["x"] - hx, door["y"] - hy) < 260:
            self.interact()
            return door
        return None
