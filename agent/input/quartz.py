"""Discover the Hades window and send macOS keyboard and mouse events."""

import math
import time

from .controller import Bounds, InputStopped, MouseButton, Point


class GameWindowNotFound(InputStopped):
    """There is no visible Hades window to control."""


def _bounds(info) -> Bounds:
    rect = info["kCGWindowBounds"]
    return Bounds(rect["X"], rect["Y"], rect["Width"], rect["Height"])


def _find_game_window(on_screen_only: bool = True):
    import Quartz as q

    # Off-screen search lets focus_game() find Hades on another Space or
    # behind other apps; input is only ever sent once it is on screen.
    if on_screen_only:
        options = q.kCGWindowListOptionOnScreenOnly | q.kCGWindowListExcludeDesktopElements
    else:
        options = q.kCGWindowListOptionAll
    windows = q.CGWindowListCopyWindowInfo(options, q.kCGNullWindowID) or ()
    game_windows = [
        info for info in windows
        if info.get("kCGWindowLayer") == 0
        and (info.get("kCGWindowOwnerName") or "").casefold() in {"game.macos", "hades"}
    ]
    if not game_windows:
        raise GameWindowNotFound("No visible Hades window found. Open or restore the game window first.")

    def window_priority(info):
        bounds = _bounds(info)
        title = info.get("kCGWindowName") or ""
        return title.casefold() == "hades", bounds.width * bounds.height

    return max(game_windows, key=window_priority)


def find_game_window() -> tuple[int, Bounds]:
    """Return the visible Hades window ID and its bounds in screen points."""
    info = _find_game_window()
    return info["kCGWindowNumber"], _bounds(info)


def focus_game() -> tuple[int, Bounds]:
    """Activate Hades and wait for macOS to report it as frontmost."""
    from AppKit import NSApplicationActivateIgnoringOtherApps, NSRunningApplication, NSWorkspace

    pid = _find_game_window(on_screen_only=False)["kCGWindowOwnerPID"]
    app = NSRunningApplication.runningApplicationWithProcessIdentifier_(pid)
    if app is None:
        raise GameWindowNotFound("Hades closed while being focused.")
    workspace = NSWorkspace.sharedWorkspace()

    def is_front():
        front = workspace.frontmostApplication()
        return front is not None and front.processIdentifier() == pid

    if not is_front():
        app.activateWithOptions_(NSApplicationActivateIgnoringOtherApps)
        time.sleep(0.2)
    if not is_front():
        # Recent macOS ignores activation requests from background processes;
        # System Events (Accessibility) can still raise the game.
        import subprocess
        try:
            subprocess.run(
                ["osascript", "-e",
                 f'tell application "System Events" to set frontmost of '
                 f'(first process whose unix id is {int(pid)}) to true'],
                capture_output=True, timeout=5,
            )
        except subprocess.TimeoutExpired as e:
            raise InputStopped("System Events did not respond while raising Hades.") from e
    # Switching Spaces takes longer than a plain activation.
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline:
        frontmost = workspace.frontmostApplication()
        if frontmost is not None and frontmost.processIdentifier() == pid:
            try:
                info = _find_game_window()
            except GameWindowNotFound:
                time.sleep(0.05)
                continue
            return info["kCGWindowNumber"], _bounds(info)
        time.sleep(0.02)
    raise InputStopped("Could not bring Hades to the foreground.")


class QuartzBackend:
    """Post events to the macOS HID stream for a foreground Hades window."""

    def __init__(self, window_id: int) -> None:
        import Quartz as q
        from AppKit import NSWorkspace

        self._q = q
        self._workspace = NSWorkspace.sharedWorkspace()
        self._window_id = window_id
        self._pid = self._window_info()["kCGWindowOwnerPID"]
        if not q.CGPreflightPostEventAccess():
            raise InputStopped("macOS Accessibility permission is required to post input events.")

    def _window_info(self):
        q = self._q
        windows = q.CGWindowListCopyWindowInfo(q.kCGWindowListOptionIncludingWindow, self._window_id)
        if not windows or not windows[0].get("kCGWindowIsOnscreen"):
            raise GameWindowNotFound("The Hades window is no longer visible.")
        return windows[0]

    def window_bounds(self) -> Bounds:
        frontmost = self._workspace.frontmostApplication()
        if frontmost is None or frontmost.processIdentifier() != self._pid:
            raise InputStopped("Hades is no longer the foreground application.")
        return _bounds(self._window_info())

    def cursor_position(self) -> Point:
        q = self._q
        event = q.CGEventCreate(None)
        if event is None:
            raise InputStopped("Quartz could not read the current cursor position.")
        point = q.CGEventGetLocation(event)
        return point.x, point.y

    def key(self, code: int, pressed: bool) -> None:
        self._post(self._q.CGEventCreateKeyboardEvent(None, code, pressed))

    def move_cursor(self, point: Point, dragging: MouseButton | None) -> None:
        q = self._q
        event_type = q.kCGEventMouseMoved
        if dragging == "left":
            event_type = q.kCGEventLeftMouseDragged
        elif dragging == "right":
            event_type = q.kCGEventRightMouseDragged
        button = q.kCGMouseButtonRight if dragging == "right" else q.kCGMouseButtonLeft
        self._post(q.CGEventCreateMouseEvent(None, event_type, point, button))

        # Wait for the window server to apply the move before checking for override.
        deadline = time.monotonic() + 0.05
        while math.dist(self.cursor_position(), point) > 2.0:
            if time.monotonic() >= deadline:
                raise InputStopped("Cursor did not reach the requested point in the Hades window.")
            time.sleep(0.002)

    def mouse_button(self, button: MouseButton, pressed: bool, point: Point | None) -> None:
        q = self._q
        if button == "left":
            event_type = q.kCGEventLeftMouseDown if pressed else q.kCGEventLeftMouseUp
            quartz_button = q.kCGMouseButtonLeft
        else:
            event_type = q.kCGEventRightMouseDown if pressed else q.kCGEventRightMouseUp
            quartz_button = q.kCGMouseButtonRight
        # Release at the current position so an override does not move the cursor back.
        point = self.cursor_position() if point is None else point
        event = q.CGEventCreateMouseEvent(None, event_type, point, quartz_button)
        if event is not None:
            q.CGEventSetIntegerValueField(event, q.kCGMouseEventClickState, 1)
        self._post(event)

    def _post(self, event) -> None:
        if event is None:
            raise InputStopped("Quartz could not create an input event.")
        self._q.CGEventPost(self._q.kCGHIDEventTap, event)
