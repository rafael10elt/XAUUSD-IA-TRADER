from xauusd_ia_trader.risk import RiskManager
from xauusd_ia_trader.models import TradeIdea


def test_risk_rejects_invalid_rr():
    risk = RiskManager({"risk_per_trade": 0.01, "min_rr": 1.5, "max_trades_per_day": 5, "max_open_positions": 1, "max_spread_points": 100, "session_start": "00:00", "session_end": "23:59"})
    idea = TradeIdea("XAUUSD", "buy", "market", 2300.0, 2295.0, 2301.0, 0.0, 0.8, "trend_up", "test")
    decision = risk.validate(idea, equity=10000, spread_points=10, symbol_info={"point": 0.01, "trade_tick_size": 0.01, "trade_tick_value": 1.0, "volume_step": 0.01, "volume_min": 0.01, "volume_max": 10})
    assert not decision.approved


def test_risk_locks_after_consecutive_losses():
    risk = RiskManager({
        "risk_per_trade": 0.01,
        "min_rr": 1.2,
        "max_consecutive_losses": 2,
        "max_trades_per_day": 5,
        "max_open_positions": 1,
        "max_spread_points": 100,
        "session_start": "00:00",
        "session_end": "23:59",
    })
    risk.state.consecutive_losses = 2
    idea = TradeIdea("XAUUSD", "buy", "market", 2300.0, 2298.0, 2304.0, 0.0, 0.8, "trend_up", "test")
    decision = risk.validate(
        idea,
        equity=10000,
        spread_points=10,
        symbol_info={"point": 0.01, "trade_tick_size": 0.01, "trade_tick_value": 1.0, "volume_step": 0.01, "volume_min": 0.01, "volume_max": 10},
    )
    assert not decision.approved
    assert decision.daily_locked


def test_risk_locks_after_daily_loss_limit():
    risk = RiskManager({
        "risk_per_trade": 0.01,
        "daily_loss_limit": 0.02,
        "min_rr": 1.2,
        "max_trades_per_day": 5,
        "max_open_positions": 1,
        "max_spread_points": 100,
        "session_start": "00:00",
        "session_end": "23:59",
    })
    risk.state.highest_equity = 10000
    risk.register_exit(-250)
    assert risk.state.locked
    assert risk.state.last_lock_reason == "daily loss limit reached"
