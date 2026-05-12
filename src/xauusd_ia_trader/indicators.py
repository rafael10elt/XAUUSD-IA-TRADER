from __future__ import annotations

import numpy as np
import pandas as pd


def _ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high = df["high"]
    low = df["low"]
    close = df["close"]
    prev_close = close.shift(1)
    tr = pd.concat(
        [(high - low), (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    return tr.rolling(period).mean()


def _rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def _adx(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    high = df["high"]
    low = df["low"]
    close = df["close"]
    up_move = high.diff()
    down_move = -low.diff()

    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    tr = _atr(df, period)
    plus_di = 100 * pd.Series(plus_dm, index=df.index).rolling(period).sum() / tr
    minus_di = 100 * pd.Series(minus_dm, index=df.index).rolling(period).sum() / tr
    dx = (100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan))
    adx = dx.rolling(period).mean()
    return pd.DataFrame({"adx": adx, "plus_di": plus_di, "minus_di": minus_di})


def add_features(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df.copy()

    data = df.copy()
    if "close" not in data.columns:
        raise ValueError("DataFrame must contain OHLC columns")

    data["ema_20"] = _ema(data["close"], 20)
    data["ema_50"] = _ema(data["close"], 50)
    data["ema_200"] = _ema(data["close"], 200)
    data["atr_14"] = _atr(data, 14)
    data["rsi_14"] = _rsi(data["close"], 14)
    adx = _adx(data, 14)
    data["adx_14"] = adx["adx"]
    data["plus_di_14"] = adx["plus_di"]
    data["minus_di_14"] = adx["minus_di"]
    data["rolling_high_20"] = data["high"].rolling(20).max()
    data["rolling_low_20"] = data["low"].rolling(20).min()
    data["range_20"] = data["high"].rolling(20).max() - data["low"].rolling(20).min()
    data["body"] = (data["close"] - data["open"]).abs()
    data["wick_up"] = data["high"] - data[["open", "close"]].max(axis=1)
    data["wick_down"] = data[["open", "close"]].min(axis=1) - data["low"]
    data["mid_price"] = (data["high"] + data["low"]) / 2.0
    data["volatility_ratio"] = data["atr_14"] / data["close"].replace(0, np.nan)

    if "tick_volume" in data.columns:
        vol = data["tick_volume"].replace(0, np.nan)
        data["volume_z"] = (vol - vol.rolling(20).mean()) / vol.rolling(20).std()
    else:
        data["volume_z"] = np.nan

    return data

