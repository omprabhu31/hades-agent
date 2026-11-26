"""Map combat action indices to the existing keyboard and mouse controller."""

import math
from collections.abc import Sequence

from agent.input import Action

# Movement indices 1-8 share the aim order, with 0 reserved for no movement.
# Both start at right and turn anticlockwise, matching the calibration.
MOVEMENTS = (None, "right", "up_right", "up", "up_left", "left", "down_left", "down", "down_right")
IDLE, ATTACK, SPECIAL, CAST, DASH = range(5)
BUTTONS = (None, "attack", "special", "cast", "dash")
AIM_SECTORS = 8
SECTOR_ANGLE = math.tau / AIM_SECTORS
AIM_RADIUS_FRACTION = 0.25  # fraction of window height


def aim_sector(angle: float) -> int:
    """Quantise an anticlockwise world angle in radians to the nearest sector."""
    return math.floor(angle / SECTOR_ANGLE + 0.5) % AIM_SECTORS


def decode_action(indices: Sequence[int], window_size: tuple[float, float]) -> Action:
    movement, button, sector = indices
    width, height = window_size
    radius = AIM_RADIUS_FRACTION * height
    angle = sector * SECTOR_ANGLE
    aim = (0.5 + radius * math.cos(angle) / width, 0.5 - radius * math.sin(angle) / height)
    control = BUTTONS[button]
    buttons = frozenset() if control is None else frozenset({control})
    return Action(movement=MOVEMENTS[movement], aim=aim, buttons=buttons)
