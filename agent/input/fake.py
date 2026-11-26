"""In-memory backend for tests and dry runs."""

from .controller import Bounds, MouseButton, Point


class FakeBackend:
    def __init__(self, bounds: Bounds, cursor: Point | None = None) -> None:
        self.bounds = bounds
        self.cursor = cursor if cursor is not None else bounds.aim_point((0.5, 0.5))
        self.events: list[tuple] = []

    def window_bounds(self) -> Bounds:
        return self.bounds

    def cursor_position(self) -> Point:
        return self.cursor

    def key(self, code: int, pressed: bool) -> None:
        self.events.append(("key_down" if pressed else "key_up", code))

    def move_cursor(self, point: Point, dragging: MouseButton | None) -> None:
        self.cursor = point
        self.events.append(("move", point, dragging))

    def mouse_button(self, button: MouseButton, pressed: bool, point: Point | None) -> None:
        point = self.cursor if point is None else point
        self.events.append(("mouse_down" if pressed else "mouse_up", button, point))
