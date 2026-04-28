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

Hover over the STEP button, then press `Ctrl+C`. The last displayed position is
saved to:

```text
data/automation_config.json
```

`auto-step` loads that saved coordinate automatically. To only print mouse
coordinates without saving:

```powershell
python -m app.main mouse-pos --no-save
```

Fallback defaults still live in:

```text
game_interface/config.py
```

The values are:

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

## Simulation Auto-Trade Mode

Auto-trade mode is for the Trade Bots game only. It does not support real-money
trading or brokerage integration.

It captures/OCRs the screen, appends the current price, runs the advisory
engine, optionally clicks BUY or SELL, moves the slider to the configured
far-right point, clicks PROCESS TRADE, then clicks STEP.

By default, it is a dry run and will not click BUY, SELL, or PROCESS TRADE:

```powershell
python -m app.main auto-trade --max-steps 50 --debug
```

To calibrate all required UI points, hover over each button/slider position and
run the matching command:

```powershell
python -m app.main set-buy-button
python -m app.main set-sell-button
python -m app.main set-process-trade-button
python -m app.main set-slider-handle
python -m app.main set-slider-right
python -m app.main set-step-button
```

The coordinates are saved to:

```text
data/automation_config.json
```

Actual simulation trade clicks require both:
- `AUTO_TRADE_ENABLED = True` in `game_interface/config.py`, or `"auto_trade_enabled": true` in `data/automation_config.json`
- the CLI flag `--confirm-auto-trade`

Example enabled command:

```powershell
python -m app.main auto-trade --max-steps 50 --debug --confirm-auto-trade
```

Safety rules:
- BUY is skipped if holdings are already greater than zero.
- SELL is skipped if holdings are zero.
- HOLD never clicks trade controls.
- The bot samples the PROCESS TRADE button color before toggling action:
  green is treated as BUY-ready, red is treated as SELL-ready.
- If the PROCESS TRADE color cannot be detected, the trade is skipped.
- Before processing a BUY or SELL, the bot drags from the calibrated slider
  handle/start point to the calibrated slider far-right point.
- The bot never shorts.
- Stop with `ESC` or `Ctrl+C`.

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

## Alpaca Paper Trading

Alpaca support is paper-only. Live trading is intentionally unsupported.

Install dependencies:

```powershell
python -m pip install -r requirements.txt
```

Create `.env` in the `TradeBotsAI` folder:

```text
ALPACA_API_KEY=your_key
ALPACA_SECRET_KEY=your_secret
ALPACA_PAPER=true
```

If `ALPACA_PAPER` is not exactly `true`, Alpaca commands refuse to run.

Fetch market bars and get advice:

```powershell
python -m app.main alpaca-advice --symbol AAPL --timeframe 1Day --lookback 180
```

Submit a paper order only when the advisory signal is BUY or SELL and position
rules allow it:

```powershell
python -m app.main alpaca-paper-trade --symbol AAPL --qty 1 --confirm-paper
```

Safety rules:
- Uses `TradingClient(..., paper=True)` only.
- No live trading mode.
- No shorting.
- SELL only runs when a paper position exists.
- BUY only runs when no paper position exists.
- Orders require `--confirm-paper`.
- Signals, orders, and positions are logged to SQLite.

## Project Layout

- `app/`: command line entry point and orchestration
- `data/`: CSV ingestion and candle model
- `strategy/`: indicators, signals, and backtesting
- `decision/`: advisory decision output
- `storage/`: SQLite persistence
- `tests/`: unit tests
