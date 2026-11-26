import signal
from types import SimpleNamespace

import pytest

from agent.input import Action, Bounds, Controller, FakeBackend, InputStopped
from agent.input import controller as controller_module


@pytest.fixture
def setup_input(tmp_path):
    stop_file = tmp_path / "STOP"
    backend = FakeBackend(Bounds(x=-100, y=50, width=301, height=201))
    return Controller(backend, stop_file=stop_file, override_threshold=20), backend, stop_file


def test_apply_diffs_inputs_and_aim(setup_input):
    controller, backend, _ = setup_input
    action = Action("up_right", (0.25, 0.75), frozenset({"attack", "cast"}))
    controller.apply(action)
    controller.apply(action)
    controller.apply(Action("right", (0.5, 0.5), frozenset({"attack", "special"})))
    controller.apply(Action())
    controller.release_all()

    assert backend.events == [
        ("move", (-25, 200), None),
        ("key_down", 0x0D),
        ("key_down", 0x02),
        ("mouse_down", "left", (-25, 200)),
        ("key_down", 0x0C),
        ("key_up", 0x0D),
        ("key_up", 0x0C),
        ("move", (50, 150), "left"),
        ("mouse_down", "right", (50, 150)),
        ("key_up", 0x02),
        ("mouse_up", "left", (50, 150)),
        ("mouse_up", "right", (50, 150)),
    ]


@pytest.mark.parametrize(("direction", "keys"), [
    (None, []),
    ("up", [0x0D]),
    ("up_right", [0x0D, 0x02]),
    ("right", [0x02]),
    ("down_right", [0x01, 0x02]),
    ("down", [0x01]),
    ("down_left", [0x01, 0x00]),
    ("left", [0x00]),
    ("up_left", [0x0D, 0x00]),
])
def test_movement_directions(setup_input, direction, keys):
    controller, backend, _ = setup_input
    with controller:
        controller.apply(Action(movement=direction))
    assert backend.events == [
        *(("key_down", key) for key in keys),
        *(("key_up", key) for key in reversed(keys)),
    ]


def test_release_on_exception(setup_input):
    controller, backend, _ = setup_input
    with pytest.raises(RuntimeError, match="test failure"), controller:
        controller.apply(Action("left", buttons=frozenset({"attack"})))
        raise RuntimeError("test failure")

    assert backend.events[-2:] == [("mouse_up", "left", (50, 150)), ("key_up", 0x00)]


def test_sigint_releases_immediately_and_restores_handler(setup_input):
    controller, backend, _ = setup_input
    original_handler = signal.getsignal(signal.SIGINT)
    with controller:
        controller.apply(Action("down", buttons=frozenset({"special"})))
        with pytest.raises(KeyboardInterrupt, match="SIGINT"):
            signal.raise_signal(signal.SIGINT)
        assert backend.events[-2:] == [("mouse_up", "right", (50, 150)), ("key_up", 0x01)]
        with pytest.raises(InputStopped, match="SIGINT"):
            controller.apply(Action("up"))
    assert signal.getsignal(signal.SIGINT) is original_handler
    assert len(backend.events) == 4


def test_stop_file_releases_held_inputs_and_blocks_new_actions(setup_input):
    controller, backend, stop_file = setup_input
    with controller:
        controller.apply(Action("down_left"))
        stop_file.touch()
        with pytest.raises(InputStopped, match="Stop file present"):
            controller.apply(Action("up", (0, 0)))
        stop_file.unlink()
        with pytest.raises(InputStopped, match="Stop file present"):
            controller.tap("enter", hold_s=0)

    assert backend.events == [("key_down", 0x01), ("key_down", 0x00), ("key_up", 0x00), ("key_up", 0x01)]


def test_aim_is_clamped_inside_window(setup_input):
    controller, backend, _ = setup_input
    with controller:
        controller.apply(Action(aim=(-2, 4), buttons=frozenset({"attack"})))
        controller.apply(Action(aim=(1, 0)))

    assert backend.events == [
        ("move", (-100, 250), None),
        ("mouse_down", "left", (-100, 250)),
        ("mouse_up", "left", (-100, 250)),
        ("move", (200, 50), None),
    ]


def test_human_override_releases_without_moving_cursor_back(setup_input):
    controller, backend, _ = setup_input
    with controller:
        controller.apply(Action("up", (0.5, 0.5), frozenset({"attack"})))
        backend.cursor = (62, 166)  # Exactly 20 points away is still within tolerance.
        controller.apply(Action("up", (0.5, 0.5), frozenset({"attack"})))
        backend.cursor = (62, 167)
        with pytest.raises(InputStopped, match="Mouse override"):
            controller.apply(Action(aim=(0.25, 0.25)))

    assert backend.cursor == (62, 167)
    assert backend.events[3:] == [("mouse_up", "left", (62, 167)), ("key_up", 0x0D)]


def test_human_override_before_first_aim(setup_input):
    controller, backend, _ = setup_input
    with controller:
        controller.apply(Action("up"))
        backend.cursor = (80, 150)
        with pytest.raises(InputStopped, match="Mouse override"):
            controller.apply(Action("right"))
    assert backend.events == [("key_down", 0x0D), ("key_up", 0x0D)]


def test_tap_and_configurable_bindings(setup_input):
    _, backend, stop_file = setup_input
    with Controller(backend, stop_file=stop_file, bindings={"up": 0x7E}) as controller:
        controller.apply(Action("up"))
        controller.tap("enter", hold_s=0)
        controller.apply(Action("up"))
    assert backend.events == [("key_down", 0x7E), ("key_down", 0x24), ("key_up", 0x24), ("key_up", 0x7E)]


def test_stop_file_during_tap_releases_tapped_and_held_keys(setup_input, monkeypatch):
    controller, backend, stop_file = setup_input
    clock = SimpleNamespace(monotonic=lambda: 0.0, sleep=lambda _: stop_file.touch())
    monkeypatch.setattr(controller_module, "time", clock)
    with controller:
        controller.apply(Action("up"))
        with pytest.raises(InputStopped, match="Stop file present"):
            controller.tap("dash")
    assert backend.events == [("key_down", 0x0D), ("key_down", 0x31), ("key_up", 0x31), ("key_up", 0x0D)]


def test_mouse_down_is_blocked_when_cursor_is_outside_window(setup_input):
    controller, backend, _ = setup_input
    backend.cursor = (250, 150)
    with controller:
        with pytest.raises(InputStopped, match="cursor outside the Hades window"):
            controller.apply(Action(buttons=frozenset({"attack"})))
    assert backend.events == []


def test_binding_shared_by_two_held_controls(setup_input):
    _, backend, stop_file = setup_input
    with Controller(backend, stop_file=stop_file, bindings={"dash": 0x0D}) as controller:
        controller.apply(Action("up", buttons=frozenset({"dash"})))
        controller.apply(Action(buttons=frozenset({"dash"})))
    assert backend.events == [("key_down", 0x0D), ("key_up", 0x0D)]


def test_cleanup_attempts_all_releases_after_a_failure(setup_input, monkeypatch):
    controller, backend, _ = setup_input
    original_key = backend.key

    def fail_one_release(code, pressed):
        if not pressed and code == 0x02:
            raise RuntimeError("release failed")
        original_key(code, pressed)

    controller.apply(Action("up_right"))
    with monkeypatch.context() as patch:
        patch.setattr(backend, "key", fail_one_release)
        with pytest.raises(RuntimeError, match="release failed"):
            controller.release_all()
    controller.release_all()
    assert backend.events == [("key_down", 0x0D), ("key_down", 0x02), ("key_up", 0x0D), ("key_up", 0x02)]
