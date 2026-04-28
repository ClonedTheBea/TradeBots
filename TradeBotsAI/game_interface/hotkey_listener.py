"""Hotkey listener for semi-automated Trade Bots capture."""

from __future__ import annotations

from typing import Callable


def listen_for_hotkey(
    on_capture: Callable[[], None],
    hotkey: str = "f8",
) -> None:
    keyboard = _load_keyboard()
    print(f"Watching screen. Press {hotkey.upper()} to capture, or Ctrl+C to stop.")
    keyboard.add_hotkey(hotkey, on_capture)
    keyboard.wait()


def _load_keyboard():
    try:
        import keyboard
    except ImportError as exc:
        raise RuntimeError(
            "watch-screen requires the keyboard package. Install it with "
            "`python -m pip install -r requirements.txt`."
        ) from exc
    return keyboard
