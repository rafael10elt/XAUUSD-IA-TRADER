from xauusd_ia_trader.execution import ExecutionEngine
from xauusd_ia_trader.models import PositionLifecycle
from xauusd_ia_trader.risk import RiskManager
from xauusd_ia_trader.state_store import PositionStateStore


class DummyNotifier:
    def __init__(self):
        self.events = []

    def info(self, title, message, *, symbol=None, priority=1):
        self.events.append(("info", title, message, symbol, priority))

    def warn(self, title, message, *, symbol=None, priority=2):
        self.events.append(("warn", title, message, symbol, priority))

    def error(self, title, message, *, symbol=None, priority=0):
        self.events.append(("error", title, message, symbol, priority))


class DummyBroker:
    def symbol_info(self, symbol):
        return {"volume_step": 0.01, "volume_min": 0.01, "point": 0.01, "trade_stops_level": 5}

    def positions_get(self, symbol=None, magic=None):
        return []


def test_manage_positions_moves_breakeven(tmp_path):
    store = PositionStateStore(tmp_path / "positions.json")
    store.upsert(
        PositionLifecycle(
            ticket=7,
            symbol="XAUUSD",
            side="buy",
            initial_volume=0.10,
            remaining_volume=0.10,
            price_open=100.0,
            stop_loss=95.0,
            take_profit=110.0,
            created_at="2026-01-01T00:00:00Z",
            updated_at="2026-01-01T00:00:00Z",
            regime="trend_up",
            reason="test",
        )
    )
    engine = ExecutionEngine(
        broker=DummyBroker(),
        risk=RiskManager({
            "risk_per_trade": 0.01,
            "max_consecutive_losses": 3,
            "max_trades_per_day": 5,
            "max_open_positions": 1,
            "max_spread_points": 100,
            "breakeven_trigger_r": 0.9,
            "partial_take_profit_r": 1.0,
            "trailing_start_r": 1.2,
            "trailing_atr_mult": 1.2,
            "trailing_step_points": 10.0,
            "session_start": "00:00",
            "session_end": "23:59",
        }),
        notifier=DummyNotifier(),
        magic=2401001,
        state_store=store,
        paper_mode=True,
    )

    actions = engine.manage_positions(symbol="XAUUSD", current_price=105.0, atr=2.0, spread_points=5.0)
    assert any(action["action"] == "breakeven" for action in actions)
