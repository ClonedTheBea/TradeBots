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

CSV files should include:

```csv
timestamp,open,high,low,close,volume
2024-01-01,100,105,99,104,1200
```

Aliases such as `date`, `time`, `datetime`, `vol`, or capitalized column names
are accepted.

## Project Layout

- `app/`: command line entry point and orchestration
- `data/`: CSV ingestion and candle model
- `strategy/`: indicators, signals, and backtesting
- `decision/`: advisory decision output
- `storage/`: SQLite persistence
- `tests/`: unit tests

