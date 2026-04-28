"""Semi-automated STEP-only capture loop."""

from __future__ import annotations

import csv
import json
from pathlib import Path
import time
from typing import Any

from app.capture import DEFAULT_LIVE_CSV
from app.recorder import append_close_price
from data.csv_loader import load_candles_from_csv
from game_interface.config import (
    RUNTIME_CONFIG_PATH,
    STEP_BUTTON_X,
    STEP_BUTTON_Y,
    STEP_DELAY_SECONDS,
)
from game_interface.ocr_reader import read_ocr_text
from game_interface.screen_capture import capture_screen
from game_interface.screen_state import ScreenState, parse_screen_state
from strategy.signals import SignalConfig, SignalEngine


def run_auto_step(
    csv_path: str | Path = DEFAULT_LIVE_CSV,
    symbol: str = "GAME",
    max_steps: int | None = None,
    allow_duplicates: bool = False,
    debug: bool = False,
) -> int:
    if max_steps is not None and max_steps <= 0:
        raise ValueError("max_steps must be positive when provided")

    pyautogui = _load_pyautogui()
    keyboard = _load_keyboard_optional()
    signal_engine = SignalEngine(SignalConfig())
    step_config = load_step_config()

    print("WARNING: auto-step mode only presses the configured STEP coordinate.")
    print("It does not click BUY, SELL, or PROCESS TRADE, and it does not execute trades.")
    print(
        "Using STEP coordinate "
        f"x={step_config['x']}, y={step_config['y']} "
        f"with delay={step_config['delay_seconds']:.2f}s."
    )
    print("Emergency stop: press ESC or Ctrl+C.")
    print("Focus the Trade Bots game window now. Starting in 3 seconds...")
    time.sleep(3)

    steps_clicked = 0
    try:
        while max_steps is None or steps_clicked < max_steps:
            if _esc_pressed(keyboard):
                print("ESC pressed. Stopping auto-step mode.")
                break

            pyautogui.click(step_config["x"], step_config["y"])
            steps_clicked += 1
            time.sleep(step_config["delay_seconds"])

            state = capture_parse_and_record(
                csv_path=csv_path,
                signal_engine=signal_engine,
                symbol=symbol,
                allow_duplicates=allow_duplicates,
                debug=debug,
            )
            if state and _esc_pressed(keyboard):
                print("ESC pressed. Stopping auto-step mode.")
                break
    except KeyboardInterrupt:
        print("Ctrl+C received. Stopping auto-step mode.")

    print(f"Auto-step stopped after {steps_clicked} STEP clicks.")
    return 0


def capture_parse_and_record(
    csv_path: str | Path,
    signal_engine: SignalEngine,
    symbol: str,
    allow_duplicates: bool = False,
    debug: bool = False,
) -> ScreenState | None:
    image = capture_screen(debug=debug)
    raw_text = read_ocr_text(image, debug=debug)
    state = parse_screen_state(raw_text)

    if debug:
        print("Raw OCR text:")
        print(raw_text)
        print("Parsed fields:")
        print(f"  date={state.game_date}")
        print(f"  price={state.price}")
        print(f"  gain_percent={state.gain_percent}")
        print(f"  cash={state.cash}")
        print(f"  holdings={state.holdings}")

    if state.price is None:
        print("Could not parse current price from OCR text")
        return None

    timestamp = state.game_date or state.captured_at
    appended = append_price_if_new(
        csv_path,
        timestamp,
        state.price,
        allow_duplicates=allow_duplicates,
    )
    if appended:
        print(f"Recorded {timestamp}: close={state.price:.4f}")
    else:
        print(f"Duplicate date {timestamp}; not appending. Use --allow-duplicates to override.")

    print_advisory_from_csv(csv_path, signal_engine, symbol, timestamp, state.price)
    return state


def append_price_if_new(
    csv_path: str | Path,
    timestamp: str,
    close: float,
    allow_duplicates: bool = False,
) -> bool:
    if not allow_duplicates and last_recorded_timestamp(csv_path) == timestamp:
        return False
    append_close_price(csv_path, timestamp, close)
    return True


def last_recorded_timestamp(csv_path: str | Path) -> str | None:
    path = Path(csv_path)
    if not path.exists() or path.stat().st_size == 0:
        return None

    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        return None
    return rows[-1].get("timestamp") or rows[-1].get("date")


def print_advisory_from_csv(
    csv_path: str | Path,
    signal_engine: SignalEngine,
    symbol: str,
    timestamp: str,
    price: float,
) -> None:
    try:
        candles = load_candles_from_csv(csv_path)
    except ValueError as exc:
        message = str(exc)
        if "At least 35 candles" in message:
            print(f"{timestamp} price={price:.4f}: need more captured prices before advisory is available.")
            return
        raise

    signal = signal_engine.latest_signal(candles, symbol=symbol)
    print(
        f"{timestamp} price={price:.4f} action={signal.action} "
        f"confidence={signal.confidence:.2f}"
    )
    print(f"Reasons: {signal.reason}")


def run_mouse_position_printer(save: bool = True) -> int:
    pyautogui = _load_pyautogui()
    last_position: tuple[int, int] | None = None
    print("Move the mouse over the STEP button. Press Ctrl+C to stop.")
    if save:
        print(f"The last displayed position will be saved to {RUNTIME_CONFIG_PATH}.")
    try:
        while True:
            position = pyautogui.position()
            last_position = (int(position.x), int(position.y))
            print(f"x={position.x}, y={position.y}")
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("Stopped mouse position helper.")
        if save and last_position is not None:
            save_step_config(last_position[0], last_position[1])
            print(
                "Saved STEP coordinate "
                f"x={last_position[0]}, y={last_position[1]} to {RUNTIME_CONFIG_PATH}."
            )
    return 0


def load_step_config(config_path: str | Path = RUNTIME_CONFIG_PATH) -> dict[str, float | int]:
    config = {
        "x": STEP_BUTTON_X,
        "y": STEP_BUTTON_Y,
        "delay_seconds": STEP_DELAY_SECONDS,
    }
    path = Path(config_path)
    if not path.exists():
        return config

    payload = json.loads(path.read_text(encoding="utf-8"))
    if "step_button_x" in payload:
        config["x"] = int(payload["step_button_x"])
    if "step_button_y" in payload:
        config["y"] = int(payload["step_button_y"])
    if "step_delay_seconds" in payload:
        config["delay_seconds"] = float(payload["step_delay_seconds"])
    return config


def save_step_config(
    x: int,
    y: int,
    delay_seconds: float = STEP_DELAY_SECONDS,
    config_path: str | Path = RUNTIME_CONFIG_PATH,
) -> Path:
    path = Path(config_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "step_button_x": int(x),
        "step_button_y": int(y),
        "step_delay_seconds": float(delay_seconds),
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def _load_pyautogui() -> Any:
    try:
        import pyautogui
    except ImportError as exc:
        raise RuntimeError(
            "auto-step requires pyautogui. Install it with "
            "`python -m pip install -r requirements.txt`."
        ) from exc
    return pyautogui


def _load_keyboard_optional() -> Any:
    try:
        import keyboard
    except ImportError:
        return None
    return keyboard


def _esc_pressed(keyboard: Any) -> bool:
    if keyboard is None:
        return False
    try:
        return bool(keyboard.is_pressed("esc"))
    except Exception:
        return False
