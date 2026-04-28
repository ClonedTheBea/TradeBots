"""Semi-automated STEP-only capture loop."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
import time
from typing import Any

from app.capture import DEFAULT_LIVE_CSV
from app.recorder import append_close_price
from data.csv_loader import load_candles_from_csv
from game_interface.config import (
    ACTION_CLICK_DELAY_SECONDS,
    AUTO_TRADE_ENABLED,
    BUY_BUTTON_X,
    BUY_BUTTON_Y,
    PROCESS_TRADE_X,
    PROCESS_TRADE_Y,
    RUNTIME_CONFIG_PATH,
    SELL_BUTTON_X,
    SELL_BUTTON_Y,
    SLIDER_DRAG_DURATION_SECONDS,
    SLIDER_RIGHT_X,
    SLIDER_RIGHT_Y,
    STEP_BUTTON_X,
    STEP_BUTTON_Y,
    STEP_DELAY_SECONDS,
    TRADE_COOLDOWN_SECONDS,
)
from game_interface.ocr_reader import read_ocr_text
from game_interface.screen_capture import capture_screen
from game_interface.screen_state import ScreenState, parse_screen_state
from strategy.signals import SignalConfig, SignalEngine


HOLDINGS_EPSILON = 0.0001


@dataclass(frozen=True)
class TradeExecutionResult:
    requested_action: str
    executed: bool
    skipped_reason: str | None
    clicked_buy: bool
    clicked_sell: bool
    moved_slider: bool
    clicked_process_trade: bool


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
        f"x={step_config['step_button_x']}, y={step_config['step_button_y']} "
        f"with delay={step_config['step_delay_seconds']:.2f}s."
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

            pyautogui.click(step_config["step_button_x"], step_config["step_button_y"])
            steps_clicked += 1
            time.sleep(step_config["step_delay_seconds"])

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


def run_auto_trade(
    csv_path: str | Path = DEFAULT_LIVE_CSV,
    symbol: str = "GAME",
    max_steps: int | None = None,
    allow_duplicates: bool = False,
    debug: bool = False,
    confirm_auto_trade: bool = False,
) -> int:
    if max_steps is not None and max_steps <= 0:
        raise ValueError("max_steps must be positive when provided")

    pyautogui = _load_pyautogui()
    keyboard = _load_keyboard_optional()
    signal_engine = SignalEngine(SignalConfig())
    automation_config = load_step_config()
    dry_run = not (confirm_auto_trade and bool(automation_config["auto_trade_enabled"]))

    print("WARNING: auto-trade is for the Trade Bots simulation only.")
    print("It does not support real-money trading or brokerage integration.")
    print("It will never short sell. Stop with ESC or Ctrl+C.")
    print_calibration(automation_config)
    if dry_run:
        print(
            "DRY RUN: BUY/SELL/PROCESS TRADE clicks are disabled. "
            "Set AUTO_TRADE_ENABLED/config and pass --confirm-auto-trade to click trades."
        )
    else:
        print("LIVE SIMULATION CLICKS ENABLED: BUY/SELL/PROCESS TRADE may be clicked.")
    print("Focus the Trade Bots game window now. Starting in 3 seconds...")
    time.sleep(3)

    steps_clicked = 0
    try:
        while max_steps is None or steps_clicked < max_steps:
            if _esc_pressed(keyboard):
                print("ESC pressed. Stopping auto-trade mode.")
                break

            state, signal = capture_parse_record_and_signal(
                csv_path=csv_path,
                signal_engine=signal_engine,
                symbol=symbol,
                allow_duplicates=allow_duplicates,
                debug=debug,
            )
            if signal is not None and state is not None:
                result = execute_trade(
                    signal.action,
                    state,
                    dry_run=dry_run,
                    pyautogui_module=pyautogui,
                    config=automation_config,
                    debug=debug,
                )
                log_trade_execution(result)
                if result.executed:
                    time.sleep(TRADE_COOLDOWN_SECONDS)
                    if debug:
                        capture_screen(debug=True)

            if _esc_pressed(keyboard):
                print("ESC pressed. Stopping auto-trade mode.")
                break

            pyautogui.click(automation_config["step_button_x"], automation_config["step_button_y"])
            print(
                "Clicked STEP at "
                f"x={automation_config['step_button_x']}, y={automation_config['step_button_y']}"
            )
            steps_clicked += 1
            time.sleep(automation_config["step_delay_seconds"])
    except KeyboardInterrupt:
        print("Ctrl+C received. Stopping auto-trade mode.")

    print(f"Auto-trade stopped after {steps_clicked} STEP clicks.")
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
        print(f"  selected_trade_action={state.selected_trade_action}")
        print(f"  slider_state={state.slider_state}")

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


def capture_parse_record_and_signal(
    csv_path: str | Path,
    signal_engine: SignalEngine,
    symbol: str,
    allow_duplicates: bool = False,
    debug: bool = False,
):
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
        print(f"  selected_trade_action={state.selected_trade_action}")
        print(f"  slider_state={state.slider_state}")

    if state.price is None:
        print("Could not parse current price from OCR text")
        return state, None

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

    signal = signal_from_csv(csv_path, signal_engine, symbol)
    if signal is None:
        print(f"{timestamp} price={state.price:.4f}: need more captured prices before advisory is available.")
        return state, None

    print(
        f"{timestamp} price={state.price:.4f} action={signal.action} "
        f"confidence={signal.confidence:.2f}"
    )
    print(f"Reasons: {signal.reason}")
    return state, signal


def execute_trade(
    action: str,
    screen_state: ScreenState,
    dry_run: bool,
    pyautogui_module: Any | None = None,
    config: dict[str, float | int | bool] | None = None,
    debug: bool = False,
) -> TradeExecutionResult:
    normalized_action = action.upper()
    holdings = screen_state.holdings or 0.0
    automation_config = config or load_step_config()

    if normalized_action == "HOLD":
        return _skipped_trade(normalized_action, "HOLD signal: no trade.")
    if normalized_action == "BUY" and holdings > HOLDINGS_EPSILON:
        return _skipped_trade(normalized_action, "BUY skipped: already holding stock.")
    if normalized_action == "SELL" and holdings <= HOLDINGS_EPSILON:
        return _skipped_trade(normalized_action, "SELL skipped: no holdings.")
    if normalized_action not in {"BUY", "SELL"}:
        return _skipped_trade(normalized_action, f"Unsupported action: {action}")

    if dry_run:
        return TradeExecutionResult(
            requested_action=normalized_action,
            executed=False,
            skipped_reason=f"DRY RUN: would execute {normalized_action}.",
            clicked_buy=False,
            clicked_sell=False,
            moved_slider=False,
            clicked_process_trade=False,
        )

    pyautogui = pyautogui_module or _load_pyautogui()
    clicked_buy = False
    clicked_sell = False

    if debug:
        capture_screen(debug=True)

    if normalized_action == "BUY":
        pyautogui.click(automation_config["buy_button_x"], automation_config["buy_button_y"])
        clicked_buy = True
        print(f"Clicked BUY at x={automation_config['buy_button_x']}, y={automation_config['buy_button_y']}")
    else:
        pyautogui.click(automation_config["sell_button_x"], automation_config["sell_button_y"])
        clicked_sell = True
        print(f"Clicked SELL at x={automation_config['sell_button_x']}, y={automation_config['sell_button_y']}")

    time.sleep(ACTION_CLICK_DELAY_SECONDS)
    pyautogui.moveTo(automation_config["slider_right_x"], automation_config["slider_right_y"])
    pyautogui.dragTo(
        automation_config["slider_right_x"],
        automation_config["slider_right_y"],
        duration=automation_config["slider_drag_duration_seconds"],
    )
    pyautogui.click(automation_config["slider_right_x"], automation_config["slider_right_y"])
    print(
        "Moved slider to right at "
        f"x={automation_config['slider_right_x']}, y={automation_config['slider_right_y']}"
    )
    pyautogui.click(automation_config["process_trade_x"], automation_config["process_trade_y"])
    print(
        "Clicked PROCESS TRADE at "
        f"x={automation_config['process_trade_x']}, y={automation_config['process_trade_y']}"
    )

    if debug:
        capture_screen(debug=True)

    return TradeExecutionResult(
        requested_action=normalized_action,
        executed=True,
        skipped_reason=None,
        clicked_buy=clicked_buy,
        clicked_sell=clicked_sell,
        moved_slider=True,
        clicked_process_trade=True,
    )


def _skipped_trade(action: str, reason: str) -> TradeExecutionResult:
    return TradeExecutionResult(
        requested_action=action,
        executed=False,
        skipped_reason=reason,
        clicked_buy=False,
        clicked_sell=False,
        moved_slider=False,
        clicked_process_trade=False,
    )


def log_trade_execution(result: TradeExecutionResult) -> None:
    if result.executed:
        print(f"{result.requested_action} executed in simulation.")
    else:
        print(result.skipped_reason)


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
    signal = signal_from_csv(csv_path, signal_engine, symbol)
    if signal is None:
        print(f"{timestamp} price={price:.4f}: need more captured prices before advisory is available.")
        return
    print(
        f"{timestamp} price={price:.4f} action={signal.action} "
        f"confidence={signal.confidence:.2f}"
    )
    print(f"Reasons: {signal.reason}")


def signal_from_csv(csv_path: str | Path, signal_engine: SignalEngine, symbol: str):
    try:
        candles = load_candles_from_csv(csv_path)
    except ValueError as exc:
        message = str(exc)
        if "At least 35 candles" in message:
            return None
        raise
    return signal_engine.latest_signal(candles, symbol=symbol)


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


def save_current_mouse_position(name: str) -> int:
    pyautogui = _load_pyautogui()
    position = pyautogui.position()
    save_coordinate(name, int(position.x), int(position.y))
    print(f"Saved {name} coordinate: x={position.x}, y={position.y}")
    print_calibration()
    return 0


def print_calibration(config: dict[str, float | int | bool] | None = None) -> None:
    automation_config = config or load_step_config()
    print("Loaded calibration:")
    print(f"  BUY: x={automation_config['buy_button_x']}, y={automation_config['buy_button_y']}")
    print(f"  SELL: x={automation_config['sell_button_x']}, y={automation_config['sell_button_y']}")
    print(
        "  PROCESS TRADE: "
        f"x={automation_config['process_trade_x']}, y={automation_config['process_trade_y']}"
    )
    print(f"  SLIDER RIGHT: x={automation_config['slider_right_x']}, y={automation_config['slider_right_y']}")
    print(f"  STEP: x={automation_config['step_button_x']}, y={automation_config['step_button_y']}")
    print(f"  AUTO_TRADE_ENABLED: {automation_config['auto_trade_enabled']}")


def run_show_calibration() -> int:
    print_calibration()
    return 0


def click_calibrated_target(name: str) -> int:
    pyautogui = _load_pyautogui()
    config = load_step_config()
    key_map = {
        "buy_button": ("buy_button_x", "buy_button_y", "BUY"),
        "sell_button": ("sell_button_x", "sell_button_y", "SELL"),
        "process_trade": ("process_trade_x", "process_trade_y", "PROCESS TRADE"),
        "slider_right": ("slider_right_x", "slider_right_y", "SLIDER RIGHT"),
        "step_button": ("step_button_x", "step_button_y", "STEP"),
    }
    x_key, y_key, label = key_map[name]
    x = config[x_key]
    y = config[y_key]
    print(f"Clicking calibrated {label} coordinate at x={x}, y={y}.")
    pyautogui.click(x, y)
    return 0


def load_step_config(config_path: str | Path = RUNTIME_CONFIG_PATH) -> dict[str, float | int | bool]:
    config = {
        "auto_trade_enabled": AUTO_TRADE_ENABLED,
        "step_button_x": STEP_BUTTON_X,
        "step_button_y": STEP_BUTTON_Y,
        "buy_button_x": BUY_BUTTON_X,
        "buy_button_y": BUY_BUTTON_Y,
        "sell_button_x": SELL_BUTTON_X,
        "sell_button_y": SELL_BUTTON_Y,
        "process_trade_x": PROCESS_TRADE_X,
        "process_trade_y": PROCESS_TRADE_Y,
        "slider_right_x": SLIDER_RIGHT_X,
        "slider_right_y": SLIDER_RIGHT_Y,
        "step_delay_seconds": STEP_DELAY_SECONDS,
        "slider_drag_duration_seconds": SLIDER_DRAG_DURATION_SECONDS,
    }
    path = Path(config_path)
    if not path.exists():
        return config

    payload = json.loads(path.read_text(encoding="utf-8"))
    for key in (
        "auto_trade_enabled",
        "step_button_x",
        "step_button_y",
        "buy_button_x",
        "buy_button_y",
        "sell_button_x",
        "sell_button_y",
        "process_trade_x",
        "process_trade_y",
        "slider_right_x",
        "slider_right_y",
        "step_delay_seconds",
        "slider_drag_duration_seconds",
    ):
        if key in payload:
            config[key] = payload[key]
    return config


def save_step_config(
    x: int,
    y: int,
    delay_seconds: float = STEP_DELAY_SECONDS,
    config_path: str | Path = RUNTIME_CONFIG_PATH,
) -> Path:
    path = Path(config_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    return save_coordinate(
        "step_button",
        x,
        y,
        config_path=config_path,
        extra={"step_delay_seconds": float(delay_seconds)},
    )


def save_coordinate(
    name: str,
    x: int,
    y: int,
    config_path: str | Path = RUNTIME_CONFIG_PATH,
    extra: dict[str, float | int | bool] | None = None,
) -> Path:
    path = Path(config_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, float | int | bool] = {}
    if path.exists():
        payload.update(json.loads(path.read_text(encoding="utf-8")))
    payload[f"{name}_x"] = int(x)
    payload[f"{name}_y"] = int(y)
    if extra:
        payload.update(extra)
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
