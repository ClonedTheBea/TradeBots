"""OCR reader for visible Trade Bots HUD values."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def read_ocr_text(image: Any, debug: bool = False, debug_dir: str | Path = "debug_screenshots") -> str:
    pytesseract = _load_pytesseract()
    texts: list[tuple[str, str]] = []

    for name, crop in _hud_regions(image).items():
        prepared = _prepare_standard_ocr_image(crop)
        if debug:
            _save_debug_image(prepared, debug_dir, name)
        texts.append((name, pytesseract.image_to_string(prepared, config="--psm 7")))

    for name, crop in _red_hud_regions(image).items():
        prepared = _prepare_red_text_image(crop)
        if debug:
            _save_debug_image(prepared, debug_dir, name)
        texts.append(
            (
                name,
                pytesseract.image_to_string(
                    prepared,
                    config="--psm 7 -c tessedit_char_whitelist=Price:$0123456789.,-()% ",
                ),
            )
        )

    return "\n".join(f"[{name}]\n{text.strip()}" for name, text in texts if text.strip())


def _load_pytesseract() -> Any:
    try:
        import pytesseract
    except ImportError as exc:
        raise RuntimeError(
            "OCR requires pytesseract. Install it with "
            "`python -m pip install -r requirements.txt`. You also need the Tesseract OCR app installed."
        ) from exc
    return pytesseract


def _hud_regions(image: Any) -> dict[str, Any]:
    width, height = image.size
    top = image.crop((0, 0, width, max(1, int(height * 0.10))))
    price_area = image.crop((int(width * 0.10), 0, int(width * 0.48), max(1, int(height * 0.10))))
    return {
        "top-hud": top,
        "top-price-area": price_area,
    }


def _red_hud_regions(image: Any) -> dict[str, Any]:
    width, height = image.size
    return {
        "top-red-price": image.crop((int(width * 0.12), 0, int(width * 0.48), max(1, int(height * 0.10)))),
        "top-red-hud": image.crop((0, 0, width, max(1, int(height * 0.10)))),
    }


def _prepare_standard_ocr_image(image: Any) -> Any:
    from PIL import ImageEnhance, ImageOps

    scale = 4
    resized = image.resize((image.width * scale, image.height * scale))
    grayscale = ImageOps.grayscale(resized)
    high_contrast = ImageEnhance.Contrast(grayscale).enhance(2.5)
    return high_contrast.point(lambda pixel: 255 if pixel > 115 else 0)


def _prepare_red_text_image(image: Any) -> Any:
    from PIL import Image

    scale = 5
    resized = image.convert("RGB").resize((image.width * scale, image.height * scale))
    output = Image.new("L", resized.size, 255)
    source = resized.load()
    target = output.load()

    for y in range(resized.height):
        for x in range(resized.width):
            red, green, blue = source[x, y]
            if red > 120 and red > (green * 1.35) and red > (blue * 1.35):
                target[x, y] = 0

    return output


def _save_debug_image(image: Any, debug_dir: str | Path, name: str) -> Path:
    path = Path(debug_dir)
    path.mkdir(parents=True, exist_ok=True)
    output_path = path / f"{name}.png"
    image.save(output_path)
    return output_path

