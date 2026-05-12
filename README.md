# XAUUSD IA Trader

Scaffolding for an autonomous XAUUSD scalper on MetaTrader 5.

## What this repo contains

- Python trading engine with regime detection, risk control, execution and notifications.
- Optional Hugging Face intelligence layer for slower contextual analysis.
- MT5 bridge helper for push notifications.
- Configuration templates and a growing backlog for implementation.

## Main idea

This project is designed for prop-firm style constraints:

- one trade at a time
- strict daily loss limits
- mandatory stop loss
- no martingale, no grid, no averaging down
- dynamic SL/TP based on regime and volatility
- push notifications for every meaningful state change

## Current layout

- `src/xauusd_ia_trader/` - Python engine
- `mql5/` - MetaTrader 5 helper EA
- `configs/` - default configuration
- `tests/` - basic checks
- `XAUUSD_MT5_Autonomous_Scalper_Spec.md` - project spec and backlog

## Quick start

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
python -m xauusd_ia_trader.cli --config configs/default.yaml --once
```

To run in live mode later:

1. Fill `MT5_TERMINAL_PATH`, `MT5_LOGIN`, `MT5_PASSWORD` and `MT5_SERVER` in `.env`.
2. Set `XAUUSD_MODE=live`.
3. Keep `MT5_COMMON_FILES_DIR` pointed to the MT5 common files directory if the automatic detection is not correct.
4. Start with demo first and confirm the bridge EA is receiving push messages.

## MT5 push notifications

MetaTrader 5 push alerts should be sent by an EA running inside the terminal.
This repo includes a simple bridge EA that reads a queue file and calls `SendNotification()`.

Before using it:

1. Enable push notifications in MT5.
2. Set your MetaQuotes ID in MT5 options.
3. Place the EA in the terminal and attach it to an XAUUSD chart.
4. Configure the Python side to write to the same common files queue.
5. Compile and attach `mql5/XAUUSD_PushBridge.mq5` to the same terminal.

## Implementation order

1. Start with paper trading only.
2. Validate risk limits and notifications.
3. Forward test on demo.
4. Tune the regime logic.
5. Only then consider live deployment.
