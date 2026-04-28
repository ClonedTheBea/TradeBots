"""Capture-once OCR flow for Trade Bots HUD data."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import re
from typing import Any

from app.recorder import append_close_price
from data.csv_loader import load_candles_from_csv
from strategy.signals import SignalEngine


DEFAULT_LIVE_CSV = Path("data/tradebots_live.csv")
DEFAULT_DEBUG_SCREENSHOT = Path("data/debug_capture.png")


@dataclass(frozen=True)
class HudSnapshot:
    timestamp: str
    price: float
    cash: float | None
    holdings: float | None
    raw_text: str


def run_capture_once(
    signal_engine: SignalEngine,
    symbol: str,
    csv_path: str | Path = DEFAULT_LIVE_CSV,
    debug: bool = False,
    debug_screenshot_path: str | Path = DEFAULT_DEBUG_SCREENSHOT,
) -> int:
    image = capture_full_screen()
    if debug:
        debug_path = Path(debug_screenshot_path)
        debug_path.parent.mkdir(parents=True, exist_ok=True)
        image.save(debug_path)
        print(f"Saved debug screenshot to: {debug_path.resolve()}")

    raw_text = ocr_image(image)
    if debug:
        print("Raw OCR text:")
        print(raw_text)

    snapshot = parse_tradebots_hud(raw_text)
    append_close_price(csv_path, snapshot.timestamp, snapshot.price)

    print(f"Captured timestamp: {snapshot.timestamp}")
    print(f"Captured price: {snapshot.price:.4f}")
    if snapshot.cash is not None:
        print(f"Captured cash: {snapshot.cash:.2f}")
    if snapshot.holdings is not None:
        print(f"Captured holdings: {snapshot.holdings:g}")
    print(f"Appended price to: {Path(csv_path).resolve()}")

    try:
        candles = load_candles_from_csv(csv_path)
    except ValueError as exc:
        message = str(exc)
        if "At least 35 candles" in message:
            print(f"Need more captured prices before advisory is available. {message}")
            return 0
        raise

    signal = signal_engine.latest_signal(candles, symbol=symbol)
    print(f"Decision: {signal.action}")
    print(f"Confidence: {signal.confidence:.2f}")
    print(f"Score: {signal.score:.2f}")
    print(f"Reason: {signal.reason}")
    return 0


def capture_full_screen() -> Any:
    try:
        from PIL import Image, ImageGrab
    except ImportError as exc:
        raise RuntimeError(
            "Screen capture requires Pillow. Install it with "
            "`python -m pip install -r requirements.txt`."
        ) from exc

    try:
        return ImageGrab.grab()
    except Exception:
        try:
            import mss
        except ImportError as exc:
            raise RuntimeError(
                "PIL ImageGrab failed and mss is not installed. Install dependencies with "
                "`python -m pip install -r requirements.txt`."
            ) from exc

        with mss.mss() as screen_capture:
            monitor = screen_capture.monitors[0]
            screenshot = screen_capture.grab(monitor)
            return Image.frombytes("RGB", screenshot.size, screenshot.rgb)


def ocr_image(image: Any) -> str:
    try:
        import pytesseract
    except ImportError as exc:
        raise RuntimeError(
            "OCR requires pytesseract. Install it with "
            "`python -m pip install -r requirements.txt`. You also need the Tesseract OCR app installed."
        ) from exc

    return pytesseract.image_to_string(image)


def parse_tradebots_hud(raw_text: str) -> HudSnapshot:
    timestamp = _parse_labeled_text(
        raw_text,
        labels=("date", "day", "time"),
    ) or _parse_date_like_text(raw_text)
    price = _parse_labeled_number(
        raw_text,
        labels=("current price", "stock price", "asset price", "price"),
    )
    cash = _parse_labeled_number(
        raw_text,
        labels=("cash", "balance", "money"),
    )
    holdings = _parse_labeled_number(
        raw_text,
        labels=("holdings", "shares", "owned", "position"),
    )

    if price is None:
        raise ValueError("Could not parse current price from OCR text")

    if timestamp is None:
        timestamp = datetime.now().isoformat(timespec="seconds")

    return HudSnapshot(
        timestamp=timestamp,
        price=price,
        cash=cash,
        holdings=holdings,
        raw_text=raw_text,
    )


def _parse_labeled_text(raw_text: str, labels: tuple[str, ...]) -> str | None:
    for line in raw_text.splitlines():
        normalized = line.strip()
        for label in labels:
            match = re.search(rf"\b{re.escape(label)}\b\s*[:#-]?\s*(.+)$", normalized, re.I)
            if match:
                value = match.group(1).strip()
                if value:
                    return value
    return None


def _parse_date_like_text(raw_text: str) -> str | None:
    match = re.search(r"\b\d{4}[-/]\d{1,2}[-/]\d{1,2}\b", raw_text)
    return match.group(0) if match else None


def _parse_labeled_number(raw_text: str, labels: tuple[str, ...]) -> float | None:
    for label in labels:
        pattern = rf"\b{re.escape(label)}\b\s*[:#-]?\s*\$?\s*(-?\d[\d,]*(?:\.\d+)?)"
        match = re.search(pattern, raw_text, re.I)
        if match:
            return float(match.group(1).replace(",", ""))
    return None
