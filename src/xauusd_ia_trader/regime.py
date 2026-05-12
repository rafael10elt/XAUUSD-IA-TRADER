from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd


@dataclass(slots=True)
class RegimeResult:
    regime: str
    confidence: float
    reason: str


def classify_regime(df: pd.DataFrame, *, config: dict[str, Any]) -> RegimeResult:
    if df.empty:
        return RegimeResult("no_trade", 0.0, "empty dataframe")

    latest = df.iloc[-1]
    price = float(latest.get("close", 0) or 0)
    ema_fast = float(latest.get("ema_20", price) or price)
    ema_slow = float(latest.get("ema_50", price) or price)
    adx = float(latest.get("adx_14", 0) or 0)
    rsi = float(latest.get("rsi_14", 50) or 50)
    atr = float(latest.get("atr_14", 0) or 0)
    range_20 = float(latest.get("range_20", 0) or 0)
    rolling_high = float(latest.get("rolling_high_20", price) or price)
    rolling_low = float(latest.get("rolling_low_20", price) or price)
    middle = (rolling_high + rolling_low) / 2.0 if rolling_high and rolling_low else price

    if adx >= 22 and ema_fast > ema_slow and price >= ema_fast:
        return RegimeResult("trend_up", 0.82, "adx and ema alignment support trend continuation")
    if adx >= 22 and ema_fast < ema_slow and price <= ema_fast:
        return RegimeResult("trend_down", 0.82, "adx and ema alignment support trend continuation")

    if adx < 18 and abs(price - middle) <= max(atr * 0.8, range_20 * 0.15):
        return RegimeResult("range", 0.73, "weak adx and mean reversion around midrange")

    if range_20 and atr and range_20 < atr * 1.8 and adx < 22:
        return RegimeResult("compression", 0.68, "compression suggests possible breakout setup")

    if rsi > 72 and ema_fast >= ema_slow:
        return RegimeResult("trend_up", 0.62, "overheated but trend structure remains bullish")
    if rsi < 28 and ema_fast <= ema_slow:
        return RegimeResult("trend_down", 0.62, "oversold but trend structure remains bearish")

    return RegimeResult("no_trade", 0.51, "market conditions are not clean enough")

