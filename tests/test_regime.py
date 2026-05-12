import pandas as pd

from xauusd_ia_trader.indicators import add_features
from xauusd_ia_trader.regime import classify_regime


def test_regime_classification_runs():
    df = pd.DataFrame(
        {
            "open": [2300, 2302, 2304, 2306, 2308, 2310, 2312, 2314, 2316, 2318],
            "high": [2301, 2303, 2305, 2307, 2309, 2311, 2313, 2315, 2317, 2319],
            "low": [2299, 2301, 2303, 2305, 2307, 2309, 2311, 2313, 2315, 2317],
            "close": [2300.5, 2302.5, 2304.5, 2306.5, 2308.5, 2310.5, 2312.5, 2314.5, 2316.5, 2318.5],
            "tick_volume": [100, 120, 140, 160, 180, 200, 220, 240, 260, 280],
        }
    )
    features = add_features(df)
    result = classify_regime(features, config={})
    assert result.regime in {"trend_up", "trend_down", "range", "compression", "no_trade"}

