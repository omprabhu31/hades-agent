"""Translate complete action snapshots into changes to held inputs."""

import math
import signal
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Literal, Protocol

Point = tuple[float, float]
MouseButton = Literal["left", "right"]
Binding = int | MouseButton

DEFAULT_BINDINGS: Mapping[str, Binding] = MappingProxyType({
    "up": 0x0D,          # W
    "left": 0x00,        # A
    "down": 0x01,        # S
    "right": 0x02,       # D
    "attack": "left",
    "special": "right",
    "cast": 0x0C,        # Q
    "dash": 0x31,        # Space
    "interact": 0x0E,    # E
    "call": 0x03,        # F
    "reload": 0x0F,      # R
    "gift": 0x05,        # G
    "codex": 0x08,       # C
    "boon_info": 0x0B,   # B
    "escape": 0x35,      # Esc
    "enter": 0x24,       # Return
})

DIRECTIONS = MappingProxyType({
    None: (),
    "up": ("up",),
    "up_right": ("up", "right"),
    "right": ("right",),
    "down_right": ("down", "right"),
    "down": ("down",),
    "down_left": ("down", "left"),
    "left": ("left",),
    "up_left": ("up", "left"),
})
HELD_BUTTONS = ("attack", "special", "cast", "dash", "interact", "call", "reload")


@dataclass(frozen=True)
class Bounds:
    """Game window rectangle in Quartz screen points."""

    x: float
    y: float
    width: float
    height: float

    def aim_point(self, aim: Point) -> Point:
        u, v = aim
        if not math.isfinite(u) or not math.isfinite(v):
            raise ValueError("Aim coordinates must be finite")
        u = min(max(u, 0.0), 1.0)
        v = min(max(v, 0.0), 1.0)
        # The right and bottom edges belong to the area outside the window.
        return self.x + u * (self.width - 1), self.y + v * (self.height - 1)

    def contains(self, point: Point) -> bool:
        x, y = point
        return self.x <= x < self.x + self.width and self.y <= y < self.y + self.height


@dataclass(frozen=True)
class Action:
    """One of the eight directions, top-left-origin aim, and all held buttons."""

    movement: str | None = None
    aim: Point | None = None
    buttons: frozenset[str] = frozenset()


class InputStopped(RuntimeError):
    """Input stopped because the game or the user took control away."""


class Backend(Protocol):
    def window_bounds(self) -> Bounds: ...
    def cursor_position(self) -> Point: ...
    def key(self, code: int, pressed: bool) -> None: ...
    def move_cursor(self, point: Point, dragging: MouseButton | None) -> None: ...
    def mouse_button(self, button: MouseButton, pressed: bool, point: Point | None) -> None: ...


class Controller:
    """Own one input session in a main-thread context to handle Ctrl-C."""

    def __init__(
        self,
        backend: Backend,
        *,
        bindings: Mapping[str, Binding] | None = None,
        stop_file: str | Path = Path(__file__).resolve().parents[2] / "runtime" / "STOP",
        override_threshold: float = 32.0,
    ) -> None:
        if not math.isfinite(override_threshold) or override_threshold < 0:
            raise ValueError("Cursor override threshold must be finite and non-negative")
        self._backend = backend
        self._bindings = dict(DEFAULT_BINDINGS)
        if bindings is not None:
            for control, binding in bindings.items():
                if binding not in ("left", "right") and not (
                    type(binding) is int and 0 <= binding <= 0xFFFF
                ):
                    raise ValueError(f"Invalid binding for {control!r}: {binding!r}")
            self._bindings.update(bindings)
        self._stop_file = Path(stop_file)
        self._override_threshold = override_threshold
        self._held: dict[Binding, None] = {}
        self._expected_cursor: Point | None = None
        self._last_aim: Point | None = None
        self._stop_reason: str | None = None
        self._in_context = False

    def __enter__(self) -> "Controller":
        if self._in_context:
            raise RuntimeError("This controller is already in use")
        try:
            self._check_safety()
            self._previous_sigint = signal.signal(signal.SIGINT, self._interrupt)
        except BaseException as exc:
            self._release_after_error(exc)
            raise
        self._in_context = True
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        try:
            if exc is None:
                self.release_all()
            else:
                self._release_after_error(exc)
        finally:
            signal.signal(signal.SIGINT, self._previous_sigint)
            self._in_context = False

    def apply(self, action: Action) -> None:
        """Release obsolete bindings, aim, then press newly held bindings."""
        try:
            bounds, cursor = self._check_safety()
            if action.movement not in DIRECTIONS:
                raise ValueError(f"Unknown movement direction: {action.movement!r}")
            unknown_buttons = set(action.buttons).difference(HELD_BUTTONS)
            if unknown_buttons:
                raise ValueError(f"Unknown held buttons: {sorted(unknown_buttons)}")
            movement = DIRECTIONS[action.movement]
            buttons = tuple(button for button in HELD_BUTTONS if button in action.buttons)
            wanted = dict.fromkeys(self._bindings[control] for control in (*movement, *buttons))
            point = bounds.aim_point(action.aim) if action.aim is not None else None

            for binding in tuple(self._held):
                if binding not in wanted:
                    self._release(binding)
            if point is not None and point != self._last_aim:
                # Moving a held mouse button sends a drag, like a physical mouse.
                dragging = next((key for key in reversed(self._held) if isinstance(key, str)), None)
                self._backend.move_cursor(point, dragging)
                self._expected_cursor = self._last_aim = point
                cursor = point
            for binding in wanted:
                if binding not in self._held:
                    self._press(binding, bounds, cursor)
        except BaseException as exc:
            self._release_after_error(exc)
            raise

    def tap(self, button: str, hold_s: float = 0.08) -> None:
        """Press and release one control while preserving other held inputs."""
        try:
            bounds, cursor = self._check_safety()
            if not math.isfinite(hold_s) or hold_s < 0:
                raise ValueError("Tap duration must be finite and non-negative")
            if button not in self._bindings:
                raise ValueError(f"Unknown button: {button!r}")
            binding = self._bindings[button]
            if binding in self._held:
                raise ValueError(f"Cannot tap an already held button: {button!r}")

            self._press(binding, bounds, cursor)
            deadline = time.monotonic() + hold_s
            while (remaining := deadline - time.monotonic()) > 0:
                time.sleep(min(remaining, 0.025))
                self._check_safety()
            self._release(binding)
        except BaseException as exc:
            self._release_after_error(exc)
            raise

    def release_all(self) -> None:
        """Attempt every release, retaining any failed releases for a retry."""
        first_error = None
        for binding in reversed(tuple(self._held)):
            if binding not in self._held:
                continue  # A SIGINT handler may have released it already.
            try:
                self._release(binding)
            except BaseException as exc:
                if first_error is None:
                    first_error = exc
                else:
                    first_error.add_note(f"Another input release failed: {exc!r}")
        if first_error is not None:
            raise first_error

    def _check_safety(self) -> tuple[Bounds, Point]:
        if self._stop_reason is not None:
            raise InputStopped(self._stop_reason)
        if self._stop_file.exists():
            raise InputStopped(f"Stop file present: {self._stop_file}")
        cursor = self._backend.cursor_position()
        if self._expected_cursor is None:
            self._expected_cursor = cursor
        elif math.dist(cursor, self._expected_cursor) > self._override_threshold:
            raise InputStopped("Mouse override: the cursor moved away from the controller position")
        return self._backend.window_bounds(), cursor

    def _press(self, binding: Binding, bounds: Bounds, cursor: Point) -> None:
        if isinstance(binding, str) and not bounds.contains(cursor):
            raise InputStopped("Cannot press a mouse button with the cursor outside the Hades window")
        # Record first in case an interrupt arrives after posting the down event.
        self._held[binding] = None
        if isinstance(binding, int):
            self._backend.key(binding, True)
        else:
            self._backend.mouse_button(binding, True, cursor)

    def _release(self, binding: Binding) -> None:
        if isinstance(binding, int):
            self._backend.key(binding, False)
        else:
            self._backend.mouse_button(binding, False, None)
        self._held.pop(binding, None)

    def _interrupt(self, signum, frame) -> None:
        self._stop_reason = "Input interrupted by SIGINT"
        error = KeyboardInterrupt(self._stop_reason)
        self._release_after_error(error)
        raise error

    def _release_after_error(self, error: BaseException) -> None:
        if isinstance(error, InputStopped):
            self._stop_reason = str(error)
        try:
            self.release_all()
        except BaseException as exc:
            error.add_note(f"Input cleanup failed: {exc!r}")
