from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional


@dataclass(slots=True)
class MarketSnapshot:
    symbol: str
    timeframe: str
    as_of: datetime
    regime: str
    spread_points: float
    features: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class TradeIdea:
    symbol: str
    side: str
    entry_mode: str
    entry_price: float
    stop_loss: float
    take_profit: float
    lots: float
    confidence: float
    regime: str
    reason: str
    partial_take_profit: Optional[float] = None
    trailing_start_r: Optional[float] = None
    max_hold_bars: int = 0


@dataclass(slots=True)
class RiskDecision:
    approved: bool
    reason: str
    risk_amount: float
    lots: float
    daily_locked: bool = False
    spread_blocked: bool = False


@dataclass(slots=True)
class OrderResult:
    success: bool
    message: str
    ticket: Optional[int] = None
    raw: dict[str, Any] = field(default_factory=dict)

