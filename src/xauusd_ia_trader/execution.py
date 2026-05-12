from __future__ import annotations

from datetime import UTC, datetime
from dataclasses import dataclass
from typing import Any

from .broker import MT5Broker
from .models import OrderResult, PositionLifecycle, PositionView, RiskDecision, TradeIdea
from .notifier import NotificationBus
from .state_store import PositionStateStore
from .risk import RiskManager


@dataclass
class ExecutionEngine:
    broker: MT5Broker
    risk: RiskManager
    notifier: NotificationBus
    magic: int
    state_store: PositionStateStore | None = None
    deviation: int = 20
    paper_mode: bool = True

    def __post_init__(self) -> None:
        if self.state_store is None:
            self.state_store = PositionStateStore()

    def _now(self) -> str:
        return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")

    def _make_lifecycle(
        self,
        *,
        ticket: int,
        idea: TradeIdea,
        volume: float,
    ) -> PositionLifecycle:
        timestamp = self._now()
        return PositionLifecycle(
            ticket=int(ticket),
            symbol=idea.symbol,
            side=idea.side,
            initial_volume=float(volume),
            remaining_volume=float(volume),
            price_open=float(idea.entry_price),
            stop_loss=float(idea.stop_loss),
            take_profit=float(idea.take_profit),
            created_at=timestamp,
            updated_at=timestamp,
            regime=idea.regime,
            reason=idea.reason,
        )

    def _position_from_payload(self, payload: dict[str, Any]) -> PositionView | None:
        try:
            ticket = int(payload.get("ticket") or payload.get("identifier") or 0)
            side = "buy" if int(payload.get("type", 0)) == 0 else "sell"
            symbol = str(payload.get("symbol") or "")
            volume = float(payload.get("volume") or 0.0)
            price_open = float(payload.get("price_open") or payload.get("price") or 0.0)
            stop_loss = float(payload.get("sl") or 0.0)
            take_profit = float(payload.get("tp") or 0.0)
            current_price = float(payload.get("price_current") or payload.get("price_open") or 0.0)
            profit = float(payload.get("profit") or 0.0)
            magic = int(payload.get("magic") or 0)
            comment = str(payload.get("comment") or "")
        except Exception:
            return None
        return PositionView(
            ticket=ticket,
            symbol=symbol,
            side=side,
            volume=volume,
            price_open=price_open,
            stop_loss=stop_loss,
            take_profit=take_profit,
            current_price=current_price,
            profit=profit,
            magic=magic,
            comment=comment,
        )

    def _paper_ticket(self) -> int:
        return int(datetime.now(UTC).timestamp() * 1000)

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
            ticket = self._paper_ticket()
            lifecycle = self._make_lifecycle(ticket=ticket, idea=idea, volume=decision.lots)
            self.state_store.upsert(lifecycle)
            self.notifier.info(
                "Paper trade created",
                f"{idea.symbol} {idea.side.upper()} | ticket={ticket}",
                symbol=idea.symbol,
                priority=1,
            )
            return decision, OrderResult(
                success=True,
                message="paper trade simulated",
                ticket=ticket,
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
        if ok and ticket is not None:
            lifecycle = self._make_lifecycle(ticket=int(ticket), idea=idea, volume=decision.lots)
            self.state_store.upsert(lifecycle)
        self.notifier.info(
            "Order sent" if ok else "Order rejected",
            f"{idea.symbol} | retcode={result.get('retcode')} | message={result.get('comment') or result.get('message') or ''} | attempts={result.get('attempts')}",
            symbol=idea.symbol,
            priority=1 if ok else 0,
        )
        return decision, OrderResult(success=ok, message=str(result.get("comment") or result.get("message") or ""), ticket=ticket, raw=result)

    def _query_positions(self, symbol: str) -> list[PositionView]:
        if self.paper_mode:
            return [
                PositionView(
                    ticket=item.ticket,
                    symbol=item.symbol,
                    side=item.side,
                    volume=item.remaining_volume,
                    price_open=item.price_open,
                    stop_loss=item.stop_loss,
                    take_profit=item.take_profit,
                    current_price=item.price_open,
                    profit=0.0,
                    magic=self.magic,
                    comment=item.reason,
                )
                for item in self.state_store.active_items(symbol)
            ]
        payloads = self.broker.positions_get(symbol=symbol, magic=self.magic)
        positions: list[PositionView] = []
        for payload in payloads:
            view = self._position_from_payload(payload)
            if view is not None:
                positions.append(view)
        return positions

    def manage_positions(
        self,
        *,
        symbol: str,
        current_price: float,
        atr: float,
        spread_points: float,
    ) -> list[dict[str, Any]]:
        actions: list[dict[str, Any]] = []
        if spread_points > float(self.risk.config.get("max_spread_points", 80)):
            return actions

        positions = self._query_positions(symbol)
        if not positions:
            return actions

        breakeven_trigger = float(self.risk.config.get("breakeven_trigger_r", 0.9))
        partial_trigger = float(self.risk.config.get("partial_take_profit_r", 1.0))
        trailing_atr_mult = float(self.risk.config.get("trailing_atr_mult", 1.2))
        trailing_step_points = float(self.risk.config.get("trailing_step_points", 10.0))
        partial_ratio = float(self.risk.config.get("partial_close_ratio", 0.5))

        symbol_info = self.broker.symbol_info(symbol)
        volume_step = float(symbol_info.get("volume_step") or 0.01)
        volume_min = float(symbol_info.get("volume_min") or 0.01)
        point = float(symbol_info.get("point") or 0.01)
        min_stop = float(symbol_info.get("trade_stops_level") or 0.0) * point

        for position in positions:
            state = self.state_store.get(position.ticket) if self.state_store else None
            if state is None:
                state = PositionLifecycle(
                    ticket=position.ticket,
                    symbol=position.symbol,
                    side=position.side,
                    initial_volume=position.volume,
                    remaining_volume=position.volume,
                    price_open=position.price_open,
                    stop_loss=position.stop_loss,
                    take_profit=position.take_profit,
                    created_at=self._now(),
                    updated_at=self._now(),
                    regime="unknown",
                    reason="recovered from broker",
                )
                self.state_store.upsert(state)

            risk_per_unit = max(abs(state.price_open - state.stop_loss), point)
            profit_r = (current_price - state.price_open) / risk_per_unit if position.side == "buy" else (state.price_open - current_price) / risk_per_unit

            if not state.breakeven_done and profit_r >= breakeven_trigger:
                if position.side == "buy":
                    new_sl = max(state.stop_loss, state.price_open)
                    if min_stop:
                        new_sl = max(new_sl, current_price - min_stop)
                else:
                    new_sl = min(state.stop_loss, state.price_open)
                    if min_stop:
                        new_sl = min(new_sl, current_price + min_stop)
                if self.paper_mode:
                    self.state_store.mark_action(position.ticket, breakeven_done=True, stop_loss=new_sl)
                    self.notifier.info("Breakeven moved", f"{symbol} | ticket={position.ticket} | SL={new_sl:.2f}", symbol=symbol, priority=1)
                    actions.append({"ticket": position.ticket, "action": "breakeven", "stop_loss": new_sl})
                else:
                    result = self.broker.modify_position(ticket=position.ticket, symbol=symbol, sl=new_sl, tp=state.take_profit)
                    if result.get("success"):
                        self.state_store.mark_action(position.ticket, breakeven_done=True, stop_loss=new_sl)
                        self.notifier.info("Breakeven moved", f"{symbol} | ticket={position.ticket} | SL={new_sl:.2f}", symbol=symbol, priority=1)
                        actions.append({"ticket": position.ticket, "action": "breakeven", "stop_loss": new_sl, "result": result})

            if not state.partial_done and profit_r >= partial_trigger and position.volume > volume_min:
                close_volume = max(volume_min, round(position.volume * partial_ratio / volume_step) * volume_step)
                close_volume = min(close_volume, position.volume - volume_min) if position.volume > volume_min else position.volume
                if close_volume >= volume_min:
                    if self.paper_mode:
                        remaining = max(0.0, position.volume - close_volume)
                        self.state_store.mark_action(position.ticket, partial_done=True, remaining_volume=remaining)
                        self.notifier.info("Partial taken", f"{symbol} | ticket={position.ticket} | close={close_volume:.2f}", symbol=symbol, priority=1)
                        actions.append({"ticket": position.ticket, "action": "partial", "close_volume": close_volume})
                    else:
                        result = self.broker.close_position(
                            ticket=position.ticket,
                            symbol=symbol,
                            side=position.side,
                            volume=close_volume,
                            magic=self.magic,
                            deviation=self.deviation,
                        )
                        if result.get("success"):
                            remaining = max(0.0, position.volume - close_volume)
                            self.state_store.mark_action(position.ticket, partial_done=True, remaining_volume=remaining)
                            self.notifier.info("Partial taken", f"{symbol} | ticket={position.ticket} | close={close_volume:.2f}", symbol=symbol, priority=1)
                            actions.append({"ticket": position.ticket, "action": "partial", "close_volume": close_volume, "result": result})

            if profit_r >= float(self.risk.config.get("trailing_start_r", 1.2)):
                if position.side == "buy":
                    trail_sl = max(state.stop_loss, current_price - max(atr * trailing_atr_mult, trailing_step_points * point))
                    if trail_sl > state.stop_loss:
                        if self.paper_mode:
                            self.state_store.mark_action(position.ticket, trailing_done=True, stop_loss=trail_sl)
                            self.notifier.info("Trailing stop", f"{symbol} | ticket={position.ticket} | SL={trail_sl:.2f}", symbol=symbol, priority=1)
                            actions.append({"ticket": position.ticket, "action": "trail", "stop_loss": trail_sl})
                        else:
                            result = self.broker.modify_position(ticket=position.ticket, symbol=symbol, sl=trail_sl, tp=state.take_profit)
                            if result.get("success"):
                                self.state_store.mark_action(position.ticket, trailing_done=True, stop_loss=trail_sl)
                                self.notifier.info("Trailing stop", f"{symbol} | ticket={position.ticket} | SL={trail_sl:.2f}", symbol=symbol, priority=1)
                                actions.append({"ticket": position.ticket, "action": "trail", "stop_loss": trail_sl, "result": result})
                else:
                    trail_sl = min(state.stop_loss, current_price + max(atr * trailing_atr_mult, trailing_step_points * point))
                    if trail_sl < state.stop_loss:
                        if self.paper_mode:
                            self.state_store.mark_action(position.ticket, trailing_done=True, stop_loss=trail_sl)
                            self.notifier.info("Trailing stop", f"{symbol} | ticket={position.ticket} | SL={trail_sl:.2f}", symbol=symbol, priority=1)
                            actions.append({"ticket": position.ticket, "action": "trail", "stop_loss": trail_sl})
                        else:
                            result = self.broker.modify_position(ticket=position.ticket, symbol=symbol, sl=trail_sl, tp=state.take_profit)
                            if result.get("success"):
                                self.state_store.mark_action(position.ticket, trailing_done=True, stop_loss=trail_sl)
                                self.notifier.info("Trailing stop", f"{symbol} | ticket={position.ticket} | SL={trail_sl:.2f}", symbol=symbol, priority=1)
                                actions.append({"ticket": position.ticket, "action": "trail", "stop_loss": trail_sl, "result": result})

        return actions
