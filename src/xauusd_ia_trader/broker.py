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


def _pick_filling_mode(info: dict[str, Any]) -> int | None:
    if mt5 is None:
        return None
    mode = int(info.get("filling_mode") or 0)
    if mode == getattr(mt5, "SYMBOL_FILLING_FOK", -1):
        return getattr(mt5, "ORDER_FILLING_FOK", None)
    if mode == getattr(mt5, "SYMBOL_FILLING_IOC", -1):
        return getattr(mt5, "ORDER_FILLING_IOC", None)
    if mode == getattr(mt5, "SYMBOL_FILLING_RETURN", -1):
        return getattr(mt5, "ORDER_FILLING_RETURN", None)
    return getattr(mt5, "ORDER_FILLING_RETURN", None)


def _candidate_filling_modes(info: dict[str, Any]) -> list[int | None]:
    if mt5 is None:
        return [None]
    preferred = _pick_filling_mode(info)
    candidates: list[int | None] = []
    for candidate in [preferred, getattr(mt5, "ORDER_FILLING_FOK", None), getattr(mt5, "ORDER_FILLING_IOC", None), getattr(mt5, "ORDER_FILLING_RETURN", None), None]:
        if candidate not in candidates:
            candidates.append(candidate)
    return candidates


def _sanitize_comment(text: str, limit: int = 24) -> str:
    allowed = []
    for char in str(text):
        if char.isalnum() or char in {" ", "_", "-", "."}:
            allowed.append(char)
    cleaned = "".join(allowed).strip()
    if not cleaned:
        cleaned = "xauusd"
    return cleaned[:limit]


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

    def positions_get(self, symbol: str | None = None, magic: int | None = None) -> list[dict[str, Any]]:
        if mt5 is None:
            return []
        try:
            positions = mt5.positions_get(symbol=symbol) if symbol else mt5.positions_get()
        except Exception:
            return []
        if not positions:
            return []
        payload = [position._asdict() for position in positions]
        if magic is not None:
            payload = [item for item in payload if int(item.get("magic") or 0) == int(magic)]
        return payload

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

    def _normalize_price(self, symbol: str, value: float) -> float:
        info = self.symbol_info(symbol)
        digits = int(info.get("digits") or 2)
        return round(float(value), digits)

    def _prepare_trade_request(self, symbol: str, request: dict[str, Any]) -> dict[str, Any]:
        info = self.symbol_info(symbol)
        filling_mode = _pick_filling_mode(info)
        if filling_mode is not None:
            request["type_filling"] = filling_mode
        check = mt5.order_check(request) if mt5 is not None else None
        if check is not None:
            request["check"] = check._asdict()
        return request

    def _send_with_fallbacks(self, symbol: str, request: dict[str, Any]) -> dict[str, Any]:
        if mt5 is None:
            return {"success": False, "message": "MetaTrader5 not installed", "attempts": []}

        info = self.symbol_info(symbol)
        attempts: list[dict[str, Any]] = []
        base_request = dict(request)
        for filling_mode in _candidate_filling_modes(info):
            trial = dict(base_request)
            if filling_mode is not None:
                trial["type_filling"] = filling_mode
            else:
                trial.pop("type_filling", None)

            check = mt5.order_check(trial)
            check_payload = check._asdict() if check is not None else None
            attempts.append(
                {
                    "type_filling": filling_mode,
                    "check_retcode": check_payload.get("retcode") if check_payload else None,
                    "check_comment": check_payload.get("comment") if check_payload else None,
                }
            )

            if check_payload and check_payload.get("retcode") not in {mt5.TRADE_RETCODE_DONE, 10009, 10008, 10025, 10030}:
                # Still try order_send on some brokers, but keep the attempt log.
                pass

            result = mt5.order_send(trial)
            if result is None:
                attempts[-1]["send_error"] = str(mt5.last_error())
                continue

            payload = result._asdict()
            payload["attempts"] = attempts
            payload["request"] = trial
            payload["success"] = payload.get("retcode") in {
                mt5.TRADE_RETCODE_DONE,
                getattr(mt5, "TRADE_RETCODE_DONE_PARTIAL", -1),
                getattr(mt5, "TRADE_RETCODE_PLACED", -1),
            }
            return payload

        return {"success": False, "message": "all filling modes rejected", "attempts": attempts, "request": base_request}

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
        price = self._normalize_price(symbol, float(tick.ask if side.lower() == "buy" else tick.bid))
        sl = self._normalize_price(symbol, sl)
        tp = self._normalize_price(symbol, tp)
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": float(lots),
            "type": order_type,
            "price": price,
            "sl": sl,
            "tp": tp,
            "deviation": int(deviation),
            "magic": int(magic),
            "comment": _sanitize_comment(comment),
            "type_time": mt5.ORDER_TIME_GTC,
        }
        return self._send_with_fallbacks(symbol, request)

    def modify_position(
        self,
        *,
        ticket: int,
        symbol: str,
        sl: float,
        tp: float,
    ) -> dict[str, Any]:
        if mt5 is None:
            return {"success": False, "message": "MetaTrader5 not installed"}
        if not self.ensure_symbol(symbol):
            return {"success": False, "message": "symbol not available"}
        sl = self._normalize_price(symbol, sl)
        tp = self._normalize_price(symbol, tp)
        request = {
            "action": mt5.TRADE_ACTION_SLTP,
            "position": int(ticket),
            "symbol": symbol,
            "sl": sl,
            "tp": tp,
        }
        return self._send_with_fallbacks(symbol, request)

    def close_position(
        self,
        *,
        ticket: int,
        symbol: str,
        side: str,
        volume: float,
        magic: int = 0,
        deviation: int = 20,
    ) -> dict[str, Any]:
        if mt5 is None:
            return {"success": False, "message": "MetaTrader5 not installed"}
        if not self.ensure_symbol(symbol):
            return {"success": False, "message": "symbol not available"}
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            return {"success": False, "message": "no tick data"}
        side = side.lower()
        order_type = mt5.ORDER_TYPE_SELL if side == "buy" else mt5.ORDER_TYPE_BUY
        price = self._normalize_price(symbol, float(tick.bid if side == "buy" else tick.ask))
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "position": int(ticket),
            "symbol": symbol,
            "volume": float(volume),
            "type": order_type,
            "price": price,
            "deviation": int(deviation),
            "magic": int(magic),
            "comment": "close",
            "type_time": mt5.ORDER_TIME_GTC,
        }
        request = self._prepare_trade_request(symbol, request)
        result = mt5.order_send(request)
        if result is None:
            return {"success": False, "message": str(mt5.last_error()), "request": request}
        payload = result._asdict()
        payload["success"] = payload.get("retcode") in {
            mt5.TRADE_RETCODE_DONE,
            getattr(mt5, "TRADE_RETCODE_DONE_PARTIAL", -1),
        }
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
        entry = self._normalize_price(symbol, entry)
        sl = self._normalize_price(symbol, sl)
        tp = self._normalize_price(symbol, tp)
        request = {
            "action": mt5.TRADE_ACTION_PENDING,
            "symbol": symbol,
            "volume": float(lots),
            "type": order_type,
            "price": entry,
            "sl": sl,
            "tp": tp,
            "deviation": int(deviation),
            "magic": int(magic),
            "comment": _sanitize_comment(comment),
            "type_time": mt5.ORDER_TIME_GTC,
        }
        return self._send_with_fallbacks(symbol, request)
