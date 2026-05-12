from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import pandas as pd

from .ai import HuggingFaceAdvisor
from .broker import MT5Broker
from .execution import ExecutionEngine
from .indicators import add_features
from .models import MarketSnapshot, TradeIdea
from .notifier import ConsoleSink, MT5QueueSink, NotificationBus
from .regime import classify_regime
from .risk import RiskManager
from .state_store import PositionStateStore


@dataclass
class XAUUSDAutonomousTrader:
    config: dict[str, Any]

    def __post_init__(self) -> None:
        self.symbol = self.config["app"]["symbol"]
        self.paper_mode = self.config["app"].get("mode", "paper") != "live"
        self.broker = MT5Broker(self.config["broker"])
        self.risk = RiskManager(self.config["risk"])
        sinks = [ConsoleSink()]
        if self.config["notifications"].get("enabled", True):
            sinks.append(MT5QueueSink(self.config["notifications"].get("queue_file", "xauusd_push_queue.txt")))
        self.notifier = NotificationBus(sinks, min_priority=int(self.config["notifications"].get("min_priority", 1)))
        self.ai = HuggingFaceAdvisor(
            enabled=bool(self.config["ai"].get("enabled", False)),
            model=self.config["ai"].get("hf_model", ""),
            timeout_seconds=int(self.config["ai"].get("timeout_seconds", 12)),
        )
        self.engine = ExecutionEngine(
            broker=self.broker,
            risk=self.risk,
            notifier=self.notifier,
            magic=int(self.config["broker"].get("magic", 2401001)),
            state_store=PositionStateStore(self.config["app"].get("position_state_path", "runtime/position_state.json")),
            deviation=int(self.config["broker"].get("deviation", 20)),
            paper_mode=self.paper_mode,
        )

    def _pick_idea(self, df: pd.DataFrame, regime: str, ai_hint: dict[str, Any], symbol_info: dict[str, Any]) -> TradeIdea | None:
        latest = df.iloc[-1]
        price = float(latest["close"])
        atr = float(latest.get("atr_14", 0.0) or 0.0)
        ema_fast = float(latest.get("ema_20", price) or price)
        ema_slow = float(latest.get("ema_50", price) or price)
        adx = float(latest.get("adx_14", 0.0) or 0.0)
        rsi = float(latest.get("rsi_14", 50.0) or 50.0)
        high_20 = float(latest.get("rolling_high_20", price) or price)
        low_20 = float(latest.get("rolling_low_20", price) or price)
        spread_points = float(latest.get("spread_points", 0.0) or 0.0)
        point = float(symbol_info.get("point") or 0.01)
        min_stop_points = float(symbol_info.get("trade_stops_level") or 0.0)

        buffer = max(atr * 0.15, price * 0.0001, point * 10)
        min_stop_distance = max(atr * 0.7, buffer * 2, min_stop_points * point, spread_points * point * 2)

        if regime == "trend_up":
            side = "buy"
            entry_mode = "market"
            entry = price
            stop = min(low_20, ema_fast, entry - min_stop_distance)
            if stop >= entry:
                stop = entry - min_stop_distance
            risk = max(entry - stop, min_stop_distance)
            tp = entry + risk * float(self.config["risk"].get("final_take_profit_r", 2.0))
            confidence = min(0.95, 0.65 + (adx / 100.0) + max((ema_fast - ema_slow) / max(price, 1.0), 0))
            reason = "trend continuation scalp"
        elif regime == "trend_down":
            side = "sell"
            entry_mode = "market"
            entry = price
            stop = max(high_20, ema_fast, entry + min_stop_distance)
            if stop <= entry:
                stop = entry + min_stop_distance
            risk = max(stop - entry, min_stop_distance)
            tp = entry - risk * float(self.config["risk"].get("final_take_profit_r", 2.0))
            confidence = min(0.95, 0.65 + (adx / 100.0) + max((ema_slow - ema_fast) / max(price, 1.0), 0))
            reason = "trend continuation scalp"
        elif regime in {"range", "compression"}:
            if price <= low_20 + atr * 0.35 and rsi <= 45:
                side = "buy"
                entry_mode = "market"
                entry = price
                stop = min(low_20, entry - min_stop_distance)
                if stop >= entry:
                    stop = entry - min_stop_distance
                risk = max(entry - stop, min_stop_distance)
                tp = entry + risk * 1.4
                confidence = 0.66
                reason = "range fade long"
            elif price >= high_20 - atr * 0.35 and rsi >= 55:
                side = "sell"
                entry_mode = "market"
                entry = price
                stop = max(high_20, entry + min_stop_distance)
                if stop <= entry:
                    stop = entry + min_stop_distance
                risk = max(stop - entry, min_stop_distance)
                tp = entry - risk * 1.4
                confidence = 0.66
                reason = "range fade short"
            else:
                return None
        else:
            return None

        if risk <= 0:
            return None

        partial = entry + (risk if side == "buy" else -risk)
        trailing_start = 0.9
        return TradeIdea(
            symbol=self.symbol,
            side=side,
            entry_mode=entry_mode,
            entry_price=float(entry),
            stop_loss=float(stop),
            take_profit=float(tp),
            lots=0.0,
            confidence=float(min(confidence, 0.98)),
            regime=regime,
            reason=f"{reason} ai{ai_hint.get('score', 0.5):.2f}",
            partial_take_profit=float(partial),
            trailing_start_r=trailing_start,
            max_hold_bars=int(self.config["strategy"].get("max_hold_bars", 20)),
        )

    def run_once(self) -> dict[str, Any]:
        if not self.broker.connect():
            self.notifier.error("MT5 connection failed", self.broker.last_error or "unknown error", symbol=self.symbol, priority=0)
            return {"success": False, "reason": self.broker.last_error}

        symbol_info = self.broker.symbol_info(self.symbol)
        account = self.broker.account_info()
        equity = float(account.get("equity") or account.get("balance") or 0.0)
        spread_points = self.broker.current_spread_points(self.symbol)

        if self.paper_mode:
            self.risk.state.open_positions = len(self.engine.state_store.active_items(self.symbol))
        else:
            self.risk.state.open_positions = len(self.broker.positions_get(symbol=self.symbol, magic=int(self.config["broker"].get("magic", 2401001))))

        frames = {}
        for tf in self.config["app"].get("timeframes", ["M1", "M5", "M15"]):
            frames[tf] = self.broker.get_rates(self.symbol, tf, 300)
        df = pd.DataFrame()
        for candidate in ("M5", "M1", "M15"):
            frame = frames.get(candidate)
            if frame is not None and not frame.empty:
                df = frame
                break
        if df.empty:
            self.notifier.warn("No market data", "could not load rates", symbol=self.symbol, priority=1)
            return {"success": False, "reason": "no data"}

        df = add_features(df)
        df["spread_points"] = spread_points
        regime = classify_regime(df, config=self.config["strategy"])
        ai_hint = self.ai.score_context(
            f"symbol={self.symbol}\nregime={regime.regime}\nreason={regime.reason}\nspread={spread_points:.2f}"
        )
        snapshot = MarketSnapshot(
            symbol=self.symbol,
            timeframe="M5",
            as_of=datetime.now(UTC),
            regime=regime.regime,
            spread_points=spread_points,
            features={"regime_reason": regime.reason, **ai_hint},
        )

        self.notifier.info(
            "Regime detected",
            f"{snapshot.symbol} | {snapshot.regime} | spread={snapshot.spread_points:.1f}",
            symbol=self.symbol,
            priority=2,
        )

        live_price = float(df.iloc[-1]["close"])
        live_atr = float(df.iloc[-1].get("atr_14", 0.0) or 0.0)
        lifecycle_actions = self.engine.manage_positions(
            symbol=self.symbol,
            current_price=live_price,
            atr=live_atr,
            spread_points=spread_points,
        )
        if lifecycle_actions:
            self.notifier.info(
                "Position management",
                f"{self.symbol} | actions={len(lifecycle_actions)}",
                symbol=self.symbol,
                priority=1,
            )

        idea = self._pick_idea(df, regime.regime, ai_hint, symbol_info)
        if idea is None:
            self.notifier.info("No trade", f"{self.symbol} | {regime.reason}", symbol=self.symbol, priority=2)
            return {"success": True, "action": "flat", "regime": regime.regime, "reason": regime.reason, "management": lifecycle_actions}

        decision, order = self.engine.place_trade(idea, equity=equity, spread_points=spread_points)
        if decision.approved and order and order.success:
            self.risk.register_entry()
            self.notifier.info("Trade submitted", f"{idea.symbol} {idea.side.upper()} | paper={self.paper_mode}", symbol=self.symbol, priority=1)
            return {
                "success": True,
                "regime": regime.regime,
                "decision": decision.reason,
                "order": order.raw,
                "paper_mode": self.paper_mode,
                "management": lifecycle_actions,
            }

        return {
            "success": False,
            "regime": regime.regime,
            "decision": decision.reason,
            "order": order.raw if order else None,
            "management": lifecycle_actions,
        }
