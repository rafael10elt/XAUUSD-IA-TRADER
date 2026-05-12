from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .broker import MT5Broker
from .models import OrderResult, RiskDecision, TradeIdea
from .notifier import NotificationBus
from .risk import RiskManager


@dataclass
class ExecutionEngine:
    broker: MT5Broker
    risk: RiskManager
    notifier: NotificationBus
    magic: int
    deviation: int = 20
    paper_mode: bool = True

    def place_trade(
        self,
        idea: TradeIdea,
        *,
        equity: float,
        spread_points: float,
    ) -> tuple[RiskDecision, OrderResult | None]:
        info = self.broker.symbol_info(idea.symbol)
        decision = self.risk.validate(
            idea,
            equity=equity,
            spread_points=spread_points,
            symbol_info=info,
        )
        if not decision.approved:
            self.notifier.warn("Trade blocked", f"{idea.symbol} | {decision.reason}", symbol=idea.symbol, priority=2)
            return decision, None

        self.notifier.info(
            "Trade approved",
            f"{idea.symbol} {idea.side.upper()} | lot={decision.lots:.2f} | SL={idea.stop_loss:.2f} | TP={idea.take_profit:.2f}",
            symbol=idea.symbol,
            priority=1,
        )

        if self.paper_mode:
            return decision, OrderResult(
                success=True,
                message="paper trade simulated",
                ticket=None,
                raw={
                    "symbol": idea.symbol,
                    "side": idea.side,
                    "lots": decision.lots,
                    "entry": idea.entry_price,
                },
            )

        if idea.entry_mode == "pending":
            result = self.broker.send_pending_order(
                symbol=idea.symbol,
                side=idea.side,
                lots=decision.lots,
                entry=idea.entry_price,
                sl=idea.stop_loss,
                tp=idea.take_profit,
                magic=self.magic,
                deviation=self.deviation,
                comment=idea.reason,
            )
        else:
            result = self.broker.send_market_order(
                symbol=idea.symbol,
                side=idea.side,
                lots=decision.lots,
                sl=idea.stop_loss,
                tp=idea.take_profit,
                magic=self.magic,
                deviation=self.deviation,
                comment=idea.reason,
            )

        ok = bool(result.get("success"))
        ticket = result.get("order") or result.get("ticket")
        self.notifier.info(
            "Order sent" if ok else "Order rejected",
            f"{idea.symbol} | {result.get('retcode') or result.get('message') or ''}",
            symbol=idea.symbol,
            priority=1 if ok else 0,
        )
        return decision, OrderResult(success=ok, message=str(result.get("comment") or result.get("message") or ""), ticket=ticket, raw=result)

