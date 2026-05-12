from __future__ import annotations

import copy
import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

DEFAULT_CONFIG: dict[str, Any] = {
    "app": {
        "symbol": "XAUUSD",
        "timeframes": ["M1", "M5", "M15"],
        "mode": "paper",
        "cycle_seconds": 30,
        "position_state_path": "runtime/position_state.json",
    },
    "broker": {
        "terminal_path": "",
        "login": 0,
        "password": "",
        "server": "",
        "deviation": 20,
        "magic": 2401001,
    },
    "risk": {
        "risk_per_trade": 0.005,
        "daily_loss_limit": 0.02,
        "max_consecutive_losses": 3,
        "max_trades_per_day": 5,
        "max_open_positions": 1,
        "max_spread_points": 80,
        "breakeven_trigger_r": 0.9,
        "partial_take_profit_r": 1.0,
        "final_take_profit_r": 2.0,
        "partial_close_ratio": 0.5,
        "trailing_start_r": 1.2,
        "trailing_atr_mult": 1.2,
        "trailing_step_points": 10.0,
        "min_rr": 1.2,
        "session_start": "07:00",
        "session_end": "20:30",
    },
    "strategy": {
        "atr_period": 14,
        "ema_fast": 20,
        "ema_slow": 50,
        "rsi_period": 14,
        "adx_period": 14,
        "breakout_lookback": 20,
        "range_lookback": 30,
        "confirmation_bars": 2,
        "max_hold_bars": 20,
    },
    "ai": {
        "enabled": False,
        "hf_model": "",
        "timeout_seconds": 12,
    },
    "notifications": {
        "enabled": True,
        "queue_file": "xauusd_push_queue.txt",
        "min_priority": 1,
    },
}


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(base)
    for key, value in override.items():
        if (
            key in result
            and isinstance(result[key], dict)
            and isinstance(value, dict)
        ):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_yaml_file(path: str | Path | None) -> dict[str, Any]:
    if not path:
        return {}
    file_path = Path(path)
    if not file_path.exists():
        return {}
    with file_path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    return data if isinstance(data, dict) else {}


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    load_dotenv()
    config = deep_merge(DEFAULT_CONFIG, load_yaml_file(path))

    env_overrides = {
        "app": {
            "symbol": os.getenv("XAUUSD_SYMBOL", "").strip() or None,
            "mode": os.getenv("XAUUSD_MODE", "").strip() or None,
            "position_state_path": os.getenv("XAUUSD_POSITION_STATE_PATH", "").strip() or None,
        },
        "broker": {
            "terminal_path": os.getenv("MT5_TERMINAL_PATH", "").strip() or None,
            "login": os.getenv("MT5_LOGIN", "").strip() or None,
            "password": os.getenv("MT5_PASSWORD", "").strip() or None,
            "server": os.getenv("MT5_SERVER", "").strip() or None,
            "deviation": os.getenv("MT5_DEVIATION", "").strip() or None,
            "magic": os.getenv("MT5_MAGIC", "").strip() or None,
        },
        "notifications": {
            "queue_file": os.getenv("MT5_QUEUE_FILE", "").strip() or None,
        },
    }
    for section, values in env_overrides.items():
        for key, value in values.items():
            if value is None:
                continue
            if key in {"login", "deviation", "magic"}:
                try:
                    config[section][key] = int(value)
                except ValueError:
                    pass
            else:
                config[section][key] = value

    config["ai"]["enabled"] = bool(
        config.get("ai", {}).get("enabled", False)
        and os.getenv("HF_API_KEY", "").strip()
    )
    return config
