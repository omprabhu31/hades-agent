"""Quit Hades cleanly through its menus (a hard kill can corrupt the save).

From gameplay: Esc -> Quit -> OK (returns to the main menu after saving),
then main menu Quit, which exits at once. Coordinates are window-normalised
and were read from screenshots on 2026-11-26 (1512x982 window).
Usage: python -m scripts.quit_game [--from-menu]
"""
import argparse
import sys
import time

from agent.bridge import running_game_pids
from agent.input import Action, Controller
from agent.input.quartz import QuartzBackend, focus_game

PAUSE_QUIT = (0.5, 0.643)
CONFIRM_OK = (0.38, 0.522)
MAIN_QUIT = (0.089, 0.635)


def click(c, uv, wait):
    c.apply(Action(aim=uv))
    time.sleep(0.15)
    c.tap("attack", hold_s=0.06)
    time.sleep(wait)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--from-menu", action="store_true", help="game is already at the main menu")
    a = p.parse_args()
    if not running_game_pids():
        print("Hades is not running")
        return 0
    wid, _ = focus_game()
    time.sleep(0.3)
    with Controller(QuartzBackend(wid)) as c:
        if not a.from_menu:
            c.tap("escape")
            time.sleep(1.2)
            click(c, PAUSE_QUIT, 1.2)
            click(c, CONFIRM_OK, 5.0)  # saves, then loads the main menu
        click(c, MAIN_QUIT, 0.5)
    for _ in range(40):
        if not running_game_pids():
            print("Hades quit cleanly")
            return 0
        time.sleep(0.25)
    print("Hades still running; check the screen (python -m scripts.shot)", file=sys.stderr)
    return 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:  # the window vanishing mid-click means the game exited
        time.sleep(2.0)
        if not running_game_pids():
            print("Hades quit cleanly")
            raise SystemExit(0)
        raise
