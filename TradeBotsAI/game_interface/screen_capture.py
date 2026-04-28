"""Screenshot capture for Trade Bots screen assistant."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any


DEBUG_SCREENSHOT_DIR = Path("debug_screenshots")


def capture_screen(debug: bool = False, debug_dir: str | Path = DEBUG_SCREENSHOT_DIR) -> Any:
    image = _capture_with_imagegrab()
    if debug:
        save_debug_screenshot(image, debug_dir)
    return image


def save_debug_screenshot(image: Any, debug_dir: str | Path = DEBUG_SCREENSHOT_DIR) -> Path:
    path = Path(debug_dir)
    path.mkdir(parents=True, exist_ok=True)
    filename = f"tradebots_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
    output_path = path / filename
    image.save(output_path)
    return output_path


def _capture_with_imagegrab() -> Any:
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

