"""Manual live smoke test. Run with ``python -m scripts.input_smoke``."""

import time

from agent.input import Action, Controller, InputStopped, QuartzBackend, focus_game


def main() -> None:
    window_id, _ = focus_game()
    with Controller(QuartzBackend(window_id)) as controller:
        for movement in ("up", "right", "down", "left"):
            controller.apply(Action(movement=movement))
            time.sleep(0.25)
        controller.apply(Action())
        controller.tap("dash")

        # The camera usually keeps the hero near the centre of the window.
        for aim in ((0.5, 0.35), (0.65, 0.5), (0.5, 0.65), (0.35, 0.5)):
            controller.apply(Action(aim=aim))
            time.sleep(0.15)


if __name__ == "__main__":
    try:
        main()
    except InputStopped as exc:
        raise SystemExit(str(exc)) from None
    except KeyboardInterrupt:
        raise SystemExit(130) from None
