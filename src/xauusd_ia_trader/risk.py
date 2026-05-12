from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, time
from typing import Any

from .models import RiskDecision, TradeIdea


@dataclass(slots=True)
class RiskState:
    day_key: str = ""
    day_start_equity: float = 0.0
    daily_pnl: float = 0.0
    trades_today: int = 0
    consecutive_losses: int = 0
    locked: bool = False
    last_lock_reason: str = ""
    highest_equity: float = 0.0
    open_positions: int = 0
    last_update: datetime | None = None


@dataclass
class RiskManager:
    config: dict[str, Any]
    state: RiskState = field(default_factory=RiskState)

    def _today_key(self) -> str:
        return datetime.now(UTC).strftime("%Y-%m-%d")

    def reset_if_new_day(self) -> None:
        today = self._today_key()
        if self.state.day_key != today:
            self.state.day_key = today
            self.state.day_start_equity = 0.0
            self.state.daily_pnl = 0.0
            self.state.trades_today = 0
            self.state.consecutive_losses = 0
            self.state.locked = False
            self.state.last_lock_reason = ""

    def sync_equity(self, equity: float) -> None:
        self.reset_if_new_day()
        if self.state.day_start_equity <= 0:
            self.state.day_start_equity = float(equity)
        self.state.highest_equity = max(self.state.highest_equity, float(equity))

    def daily_pnl_from_equity(self, equity: float) -> float:
        self.reset_if_new_day()
        if self.state.day_start_equity <= 0:
            return 0.0
        return float(equity) - float(self.state.day_start_equity)

    def session_allowed(self, now: datetime | None = None) -> bool:
        now = now or datetime.now(UTC)
        start = self.config.get("session_start", "07:00")
        end = self.config.get("session_end", "20:30")
        start_h, start_m = [int(x) for x in start.split(":")]
        end_h, end_m = [int(x) for x in end.split(":")]
        current = time(now.hour, now.minute)
        return time(start_h, start_m) <= current <= time(end_h, end_m)

    def calculate_risk_amount(self, equity: float) -> float:
        return max(0.0, equity * float(self.config.get("risk_per_trade", 0.005)))

    def calculate_lots(
        self,
        *,
        equity: float,
        entry_price: float,
        stop_loss: float,
        symbol_info: dict[str, Any] | None = None,
        manual_lots: float | None = None,
    ) -> float:
        info = symbol_info or {}
        risk_amount = self.calculate_risk_amount(equity)
        tick_size = float(info.get("trade_tick_size") or info.get("point") or 0.01)
        tick_value = float(info.get("trade_tick_value") or 1.0)
        volume_step = float(info.get("volume_step") or 0.01)
        volume_min = float(info.get("volume_min") or 0.01)
        volume_max = float(info.get("volume_max") or 100.0)

        if manual_lots is not None and float(manual_lots) > 0:
            lots = float(manual_lots)
            lots = max(volume_min, min(lots, volume_max))
            steps = round(lots / volume_step)
            lots = max(volume_min, steps * volume_step)
            return round(lots, 2)

        distance = abs(entry_price - stop_loss)
        if distance <= 0 or tick_size <= 0 or tick_value <= 0:
            return volume_min

        ticks_to_stop = distance / tick_size
        money_per_lot = ticks_to_stop * tick_value
        if money_per_lot <= 0:
            return volume_min

        lots = risk_amount / money_per_lot
        lots = max(volume_min, min(lots, volume_max))
        steps = round(lots / volume_step)
        lots = max(volume_min, steps * volume_step)
        return round(lots, 2)

    def validate(
        self,
        idea: TradeIdea,
        *,
        equity: float,
        spread_points: float,
        symbol_info: dict[str, Any] | None = None,
    ) -> RiskDecision:
        self.sync_equity(equity)

        if self.state.locked:
            return RiskDecision(False, self.state.last_lock_reason or "locked", 0.0, 0.0, daily_locked=True)

        if not self.session_allowed():
            return RiskDecision(False, "outside allowed session", 0.0, 0.0)

        if self.state.consecutive_losses >= int(self.config.get("max_consecutive_losses", 3)):
            self.state.locked = True
            self.state.last_lock_reason = "consecutive loss limit reached"
            return RiskDecision(False, self.state.last_lock_reason, 0.0, 0.0, daily_locked=True)

        if self.state.trades_today >= int(self.config.get("max_trades_per_day", 5)):
            self.state.locked = True
            self.state.last_lock_reason = "daily trade limit reached"
            return RiskDecision(False, self.state.last_lock_reason, 0.0, 0.0, daily_locked=True)

        if self.state.open_positions >= int(self.config.get("max_open_positions", 1)):
            return RiskDecision(False, "max open positions reached", 0.0, 0.0)

        if spread_points > float(self.config.get("max_spread_points", 80)):
            return RiskDecision(False, "spread too wide", 0.0, 0.0, spread_blocked=True)

        if idea.entry_price <= 0 or idea.stop_loss <= 0 or idea.take_profit <= 0:
            return RiskDecision(False, "invalid trade geometry", 0.0, 0.0)

        risk_amount = self.calculate_risk_amount(equity)
        if risk_amount <= 0:
            return RiskDecision(False, "risk amount too small", 0.0, 0.0)

        manual_lots = float(getattr(idea, "lots", 0.0) or 0.0)
        lots = self.calculate_lots(
            equity=equity,
            entry_price=idea.entry_price,
            stop_loss=idea.stop_loss,
            symbol_info=symbol_info,
            manual_lots=manual_lots if manual_lots > 0 else None,
        )

        rr = abs(idea.take_profit - idea.entry_price) / max(abs(idea.entry_price - idea.stop_loss), 1e-9)
        if rr < float(self.config.get("min_rr", 1.2)):
            return RiskDecision(False, "risk reward too low", risk_amount, 0.0)

        if lots <= 0:
            return RiskDecision(False, "lot size computed as zero", risk_amount, 0.0)

        return RiskDecision(True, "approved", risk_amount, lots)

    def register_entry(self) -> None:
        self.state.trades_today += 1
        self.state.open_positions += 1

    def register_exit(self, pnl: float) -> None:
        self.state.open_positions = max(0, self.state.open_positions - 1)
        self.state.daily_pnl += pnl
        if pnl < 0:
            self.state.consecutive_losses += 1
        else:
            self.state.consecutive_losses = 0
        self.state.highest_equity = max(self.state.highest_equity, self.state.day_start_equity + self.state.daily_pnl)

        daily_loss_limit = abs(float(self.config.get("daily_loss_limit", 0.02)))
        if self.state.daily_pnl <= -daily_loss_limit * max(self.state.highest_equity, 0.0):
            self.state.locked = True
            self.state.last_lock_reason = "daily loss limit reached"
