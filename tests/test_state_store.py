from xauusd_ia_trader.models import PositionLifecycle
from xauusd_ia_trader.state_store import PositionStateStore


def test_state_store_persists_positions(tmp_path):
    path = tmp_path / "position_state.json"
    store = PositionStateStore(path)
    store.upsert(
        PositionLifecycle(
            ticket=1001,
            symbol="XAUUSD",
            side="buy",
            initial_volume=0.1,
            remaining_volume=0.1,
            price_open=2300.0,
            stop_loss=2295.0,
            take_profit=2310.0,
            created_at="2026-01-01T00:00:00Z",
            updated_at="2026-01-01T00:00:00Z",
            regime="trend_up",
            reason="test",
        )
    )

    reloaded = PositionStateStore(path)
    item = reloaded.get(1001)
    assert item is not None
    assert item.symbol == "XAUUSD"
    assert item.remaining_volume == 0.1
