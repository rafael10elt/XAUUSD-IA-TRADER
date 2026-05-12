from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

import pandas as pd

try:
    import MetaTrader5 as mt5
except Exception:  # pragma: no cover - optional dependency
    mt5 = None


TIMEFRAME_MAP = {
    "M1": getattr(mt5, "TIMEFRAME_M1", 1) if mt5 else 1,
    "M5": getattr(mt5, "TIMEFRAME_M5", 5) if mt5 else 5,
    "M15": getattr(mt5, "TIMEFRAME_M15", 15) if mt5 else 15,
    "M30": getattr(mt5, "TIMEFRAME_M30", 30) if mt5 else 30,
    "H1": getattr(mt5, "TIMEFRAME_H1", 60) if mt5 else 60,
}


@dataclass
class MT5Broker:
    config: dict[str, Any]
    connected: bool = False
    last_error: str = ""

    def available(self) -> bool:
        return mt5 is not None

    def connect(self) -> bool:
        if not self.available():
            self.last_error = "MetaTrader5 package not installed"
            return False

        terminal_path = (self.config.get("terminal_path") or "").strip()
        login = self.config.get("login") or 0
        password = self.config.get("password") or ""
        server = self.config.get("server") or ""

        try:
            mt5.shutdown()
            if terminal_path:
                ok = mt5.initialize(path=terminal_path, login=login, password=password, server=server)
            else:
                ok = mt5.initialize(login=login, password=password, server=server)
            self.connected = bool(ok)
            if not ok:
                self.last_error = str(mt5.last_error())
            return self.connected
        except Exception as exc:
            self.last_error = str(exc)
            self.connected = False
            return False

    def ensure_symbol(self, symbol: str) -> bool:
        if not self.connected and not self.connect():
            return False
        if mt5 is None:
            return False
        try:
            return bool(mt5.symbol_select(symbol, True))
        except Exception:
            return False

    def symbol_info(self, symbol: str) -> dict[str, Any]:
        if mt5 is None:
            return {}
        info = mt5.symbol_info(symbol)
        return info._asdict() if info else {}

    def account_info(self) -> dict[str, Any]:
        if mt5 is None:
            return {}
        info = mt5.account_info()
        return info._asdict() if info else {}

    def get_rates(self, symbol: str, timeframe: str, count: int = 300) -> pd.DataFrame:
        if not self.ensure_symbol(symbol):
            return pd.DataFrame()
        tf_value = TIMEFRAME_MAP.get(timeframe, TIMEFRAME_MAP["M5"])
        rates = mt5.copy_rates_from_pos(symbol, tf_value, 0, count)
        if rates is None:
            return pd.DataFrame()
        df = pd.DataFrame(rates)
        if df.empty:
            return df
        df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
        df = df.rename(
            columns={
                "open": "open",
                "high": "high",
                "low": "low",
                "close": "close",
                "tick_volume": "tick_volume",
                "spread": "spread",
                "real_volume": "real_volume",
            }
        )
        return df.set_index("time")

    def current_spread_points(self, symbol: str) -> float:
        if mt5 is None:
            return 0.0
        tick = mt5.symbol_info_tick(symbol)
        info = mt5.symbol_info(symbol)
        if not tick or not info:
            return 0.0
        point = float(getattr(info, "point", 0.01) or 0.01)
        return abs(float(tick.ask) - float(tick.bid)) / point

    def send_market_order(
        self,
        *,
        symbol: str,
        side: str,
        lots: float,
        sl: float,
        tp: float,
        magic: int,
        deviation: int = 20,
        comment: str = "",
    ) -> dict[str, Any]:
        if mt5 is None:
            return {"success": False, "message": "MetaTrader5 not installed"}
        if not self.ensure_symbol(symbol):
            return {"success": False, "message": "symbol not available"}

        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            return {"success": False, "message": "no tick data"}

        order_type = mt5.ORDER_TYPE_BUY if side.lower() == "buy" else mt5.ORDER_TYPE_SELL
        price = float(tick.ask if side.lower() == "buy" else tick.bid)
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": float(lots),
            "type": order_type,
            "price": price,
            "sl": float(sl),
            "tp": float(tp),
            "deviation": int(deviation),
            "magic": int(magic),
            "comment": comment[:31],
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_FOK,
        }
        result = mt5.order_send(request)
        if result is None:
            return {"success": False, "message": str(mt5.last_error()), "request": request}
        payload = result._asdict()
        payload["success"] = payload.get("retcode") == mt5.TRADE_RETCODE_DONE
        payload["request"] = request
        return payload

    def send_pending_order(
        self,
        *,
        symbol: str,
        side: str,
        lots: float,
        entry: float,
        sl: float,
        tp: float,
        magic: int,
        deviation: int = 20,
        comment: str = "",
    ) -> dict[str, Any]:
        if mt5 is None:
            return {"success": False, "message": "MetaTrader5 not installed"}
        if not self.ensure_symbol(symbol):
            return {"success": False, "message": "symbol not available"}

        side = side.lower()
        if side == "buy":
            order_type = mt5.ORDER_TYPE_BUY_STOP
        else:
            order_type = mt5.ORDER_TYPE_SELL_STOP
        request = {
            "action": mt5.TRADE_ACTION_PENDING,
            "symbol": symbol,
            "volume": float(lots),
            "type": order_type,
            "price": float(entry),
            "sl": float(sl),
            "tp": float(tp),
            "deviation": int(deviation),
            "magic": int(magic),
            "comment": comment[:31],
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_FOK,
        }
        result = mt5.order_send(request)
        if result is None:
            return {"success": False, "message": str(mt5.last_error()), "request": request}
        payload = result._asdict()
        payload["success"] = payload.get("retcode") == mt5.TRADE_RETCODE_DONE
        payload["request"] = request
        return payload

