"""Parsed Trade Bots HUD state."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import re


@dataclass(frozen=True)
class ScreenState:
    raw_text: str
    game_date: str | None
    price: float | None
    gain_percent: float | None
    cash: float | None
    holdings: float | None
    captured_at: str


def parse_money(text: str) -> float | None:
    match = re.search(r"[S$]\s*(-?\d[\d,]*(?:\.\d+)?)", text)
    if not match:
        return None
    return float(match.group(1).replace(",", ""))


def parse_percent(text: str) -> float | None:
    match = re.search(r"(-?\d[\d,]*(?:\.\d+)?)\s*%", text)
    if not match:
        return None
    return float(match.group(1).replace(",", ""))


def parse_game_date(text: str) -> str | None:
    match = re.search(
        r"\b((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*)\s*"
        r"(\d{1,2})\s*Yr\s*(\d+)\b",
        text,
        re.I,
    )
    if not match:
        return None
    month, day, year = match.groups()
    return f"{month.title()} {day} Yr {year}"


def parse_screen_state(ocr_text: str) -> ScreenState:
    price = _parse_labeled_money(
        ocr_text,
        ("price", "current price", "stock price"),
    ) or _parse_unlabeled_price_money(ocr_text)
    return ScreenState(
        raw_text=ocr_text,
        game_date=parse_game_date(ocr_text),
        price=price,
        gain_percent=_parse_price_gain_percent(ocr_text),
        cash=_parse_labeled_money(ocr_text, ("cash", "balance", "money")),
        holdings=_parse_labeled_money(ocr_text, ("holdings", "holding", "position")),
        captured_at=datetime.now().isoformat(timespec="seconds"),
    )


def _parse_labeled_money(text: str, labels: tuple[str, ...]) -> float | None:
    for label in labels:
        pattern = rf"\b{re.escape(label)}\b\s*[:#-]?\s*([S$]\s*-?\d[\d,]*(?:\.\d+)?)"
        match = re.search(pattern, text, re.I)
        if match:
            return parse_money(match.group(1))
    return None


def _parse_price_gain_percent(text: str) -> float | None:
    for line in text.splitlines():
        if "price" not in line.lower():
            continue
        price_segment = re.split(r"\b(?:cash|holding|holdings|balance)\b", line, flags=re.I)[0]
        percent = parse_percent(price_segment)
        if percent is not None:
            return percent

    for line in text.splitlines():
        lower = line.lower()
        if "cash" in lower or "holding" in lower or "fee" in lower or "balance" in lower:
            continue
        if parse_money(line) is not None:
            percent = parse_percent(line)
            if percent is not None:
                return percent
    return None


def _parse_unlabeled_price_money(text: str) -> float | None:
    for line in text.splitlines():
        lower = line.lower()
        if "cash" in lower or "holding" in lower or "fee" in lower or "balance" in lower:
            continue
        value = parse_money(line)
        if value is not None:
            return value
    return None
