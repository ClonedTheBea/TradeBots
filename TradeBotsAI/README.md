# TradeBots AI Assistant

Advisory analysis engine for "Trade Bots: A Technical Analysis Simulation".

Version 1 focuses on offline CSV data, technical indicators, simple backtesting,
SQLite logging, OCR-assisted screen reading, and Buy/Sell/Hold recommendations.
It does not do real-money trading, broker integration, machine learning,
auto-clicking, or automated buying/selling.

## Quick Start

```powershell
cd TradeBotsAI
python -m app.main --csv data/sample_ohlcv.csv --db tradebots_ai.sqlite
```

Run tests:

```powershell
cd TradeBotsAI
python -m unittest discover -s tests
```

## CSV Format

CSV files can include full OHLCV data:

```csv
timestamp,open,high,low,close,volume
2024-01-01,100,105,99,104,1200
```

Or close-only Trade Bots STEP prices:

```csv
timestamp,close
step-001,104
step-002,102
```

For close-only data, the assistant sets `open`, `high`, and `low` equal to
`close`, sets `volume` to `0`, and marks the candle as synthetic. SMA, RSI,
MACD, and Bollinger Bands all work from close prices, but the CLI will warn
that indicators or future strategies needing true OHLCV may be less reliable.

Aliases such as `date`, `time`, `datetime`, `vol`, or capitalized column names
are accepted.

## Manual Trade Bots Price Recording

After each in-game STEP, record the visible current price:

```powershell
python -m app.main --csv data/manual_prices.csv --record-step --symbol GAME
```

The command prompts for a timestamp/date and current price, then appends a
`timestamp,close` row to the CSV. Once at least 35 prices exist, it also prints
the latest advisory signal.

You can run advisory mode against the recorded file at any time:

```powershell
python -m app.main --csv data/manual_prices.csv --symbol GAME
```

## Capture Once OCR Mode

To capture the screen once, OCR the Trade Bots HUD, append the parsed current
price to `data/tradebots_live.csv`, and run advisory when enough prices exist:

```powershell
python -m app.main capture-once
```

Debug mode saves a screenshot and prints raw OCR text:

```powershell
python -m app.main capture-once --debug
```

This mode requires Pillow, pytesseract, mss, and the Tesseract OCR application
installed on your machine. It does not click, type into, or control the game.

## Watch Screen Mode

Watch mode waits for a hotkey. Each time you press F8, it captures the current
screen, OCRs the visible top HUD, appends the parsed price to
`data/tradebots_live.csv`, and runs the advisory engine.

```powershell
python -m app.main watch-screen --debug
```

Use the default F8 capture:

```text
Press F8 while the Trade Bots screen is visible.
```

Optional flags:

```powershell
python -m app.main watch-screen --csv data/tradebots_live.csv --symbol GAME --hotkey f8 --debug
```

Debug mode saves screenshots and OCR crop images to `debug_screenshots/`, prints
the raw OCR text, and prints parsed fields. Watch mode does not click anything,
does not press STEP, and does not automate buying or selling.

## Auto-Step Mode

Auto-step mode repeatedly clicks only the configured STEP coordinate, waits for
the screen to update, OCRs the top HUD, appends the parsed price to
`data/tradebots_live.csv`, and prints the advisory result.

Safety boundaries:
- It does not click BUY.
- It does not click SELL.
- It does not click PROCESS TRADE.
- It does not execute trades.
- Stop with `ESC` or `Ctrl+C`.

First calibrate the STEP button coordinate:

```powershell
python -m app.main mouse-pos
```

Hover over the STEP button and copy the printed `x` and `y` values into:

```text
game_interface/config.py
```

Update:

```python
STEP_BUTTON_X = 350
STEP_BUTTON_Y = 980
STEP_DELAY_SECONDS = 0.75
```

Run auto-step:

```powershell
python -m app.main auto-step --debug
```

Run a limited session:

```powershell
python -m app.main auto-step --max-steps 50 --debug
```

By default, if OCR returns the same game date as the last row in the live CSV,
the price is not appended again. To override that:

```powershell
python -m app.main auto-step --allow-duplicates --debug
```

## Windows OCR Setup

Install Python dependencies:

```powershell
python -m pip install -r requirements.txt
```

Install the Tesseract OCR application for Windows, then make sure
`tesseract.exe` is on your PATH. The Tesseract project points Windows users to
the UB Mannheim Windows installer; the official docs also note that the OCR
engine and trained language data are separate install pieces.

Useful links:
- [Tesseract OCR](https://tesseractocr.org/)
- [Tesseract install docs](https://tesseract-ocr.github.io/tessdoc/Installation.html)
- [UB Mannheim Windows installer](https://github.com/UB-Mannheim/tesseract/wiki)

Typical Windows PATH entry:

```text
C:\Program Files\Tesseract-OCR
```

Restart PowerShell after changing PATH, then check:

```powershell
tesseract --version
```

## Project Layout

- `app/`: command line entry point and orchestration
- `data/`: CSV ingestion and candle model
- `strategy/`: indicators, signals, and backtesting
- `decision/`: advisory decision output
- `storage/`: SQLite persistence
- `tests/`: unit tests
