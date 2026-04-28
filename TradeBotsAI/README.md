# TradeBots AI Assistant

Advisory analysis engine for "Trade Bots: A Technical Analysis Simulation".

Version 1 focuses on offline CSV data, technical indicators, simple backtesting,
SQLite logging, and Buy/Sell/Hold recommendations. It does not do real-money
trading, broker integration, machine learning, OCR, screenshots, or UI automation.

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

## Project Layout

- `app/`: command line entry point and orchestration
- `data/`: CSV ingestion and candle model
- `strategy/`: indicators, signals, and backtesting
- `decision/`: advisory decision output
- `storage/`: SQLite persistence
- `tests/`: unit tests
