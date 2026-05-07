from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime


@dataclass
class Candle:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int

    @property
    def body(self) -> float:
        return abs(self.close - self.open)

    @property
    def range(self) -> float:
        return self.high - self.low


@dataclass
class FVGResult:
    direction: str          # "BULLISH_FVG_BREAK_HIGH" or "BEARISH_FVG_BREAK_LOW"
    gap_high: float
    gap_low: float
    gap_size: float
    body_ratio: float       # impulse candle body / avg body


@dataclass
class MarketContext:
    symbol: str
    date: str
    trade_allowed: bool
    skip_reason: Optional[str]
    premarket_gap_pct: float
    atr_14_daily: float
    first_candle: Optional[Candle]
    key_high: float
    key_low: float
    candle_range: float
    candle_range_valid: bool
    candles_1min: list = field(default_factory=list)
    fvg: Optional[FVGResult] = None
    volume_ratio: float = 0.0
    volume_confirmed: bool = False


@dataclass
class TradeSignal:
    symbol: str
    date: str
    signal: str             # "LONG" or "SHORT"
    entry: float
    stop_loss: float
    take_profit: float
    risk: float
    reward: float
    stop_type: str          # "Option A (FVG-based)" or "Option B (First Candle)"
    fvg_body_ratio: float
    volume_ratio: float
    filters_passed: list = field(default_factory=list)
    confidence: str = "HIGH"


@dataclass
class TradeResult:
    trade_id: str
    symbol: str
    date: str
    signal: str
    entry: float
    stop_loss: float
    take_profit: float
    exit_price: float
    result: str             # "WIN", "LOSS", "SKIP", "FORCED_CLOSE"
    pnl_dollars: float
    pnl_percent: float
    qty: int
    stop_type: str
    fvg_body_ratio: float
    volume_ratio: float
    filters_passed: list
    skip_reason: Optional[str] = None
    alpaca_order_id: Optional[str] = None
