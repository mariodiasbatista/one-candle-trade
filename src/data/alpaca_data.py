import logging
import numpy as np
from datetime import datetime, timedelta
from typing import Optional
import pytz

from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest, StockLatestBarRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

from src.config import ALPACA_API_KEY, ALPACA_SECRET_KEY
from src.models import Candle

logger = logging.getLogger(__name__)
ET = pytz.timezone("America/New_York")

_client: Optional[StockHistoricalDataClient] = None


def get_client() -> StockHistoricalDataClient:
    global _client
    if _client is None:
        _client = StockHistoricalDataClient(ALPACA_API_KEY, ALPACA_SECRET_KEY)
    return _client


def _bars_to_candles(bars) -> list[Candle]:
    candles = []
    for bar in bars:
        ts = bar.timestamp
        if ts.tzinfo is None:
            ts = pytz.utc.localize(ts)
        ts = ts.astimezone(ET)
        candles.append(Candle(
            timestamp=ts,
            open=float(bar.open),
            high=float(bar.high),
            low=float(bar.low),
            close=float(bar.close),
            volume=int(bar.volume),
        ))
    return candles


def get_bars(symbol: str, timeframe: TimeFrame, start: datetime, end: datetime) -> list[Candle]:
    if start.tzinfo is None:
        start = ET.localize(start)
    if end.tzinfo is None:
        end = ET.localize(end)
    request = StockBarsRequest(
        symbol_or_symbols=symbol,
        timeframe=timeframe,
        start=start,
        end=end,
        feed="iex",
    )
    bars = get_client().get_stock_bars(request)
    try:
        raw = bars[symbol]
    except KeyError:
        raw = []
    return _bars_to_candles(raw)


def get_first_5min_candle(symbol: str, date: str) -> Optional[Candle]:
    d = datetime.strptime(date, "%Y-%m-%d")
    start = ET.localize(d.replace(hour=9, minute=30))
    end = ET.localize(d.replace(hour=9, minute=36))
    candles = get_bars(symbol, TimeFrame(5, TimeFrameUnit.Minute), start, end)
    return candles[0] if candles else None


def get_1min_candles(symbol: str, date: str, from_time: str = "09:35", to_time: str = "10:31") -> list[Candle]:
    d = datetime.strptime(date, "%Y-%m-%d")
    fh, fm = map(int, from_time.split(":"))
    th, tm = map(int, to_time.split(":"))
    start = ET.localize(d.replace(hour=fh, minute=fm))
    end = ET.localize(d.replace(hour=th, minute=tm))
    return get_bars(symbol, TimeFrame(1, TimeFrameUnit.Minute), start, end)


def get_daily_candles(symbol: str, lookback_days: int = 20) -> list[Candle]:
    end = datetime.now(ET)
    start = end - timedelta(days=lookback_days + 10)
    candles = get_bars(symbol, TimeFrame(1, TimeFrameUnit.Day), start, end)
    return candles[-lookback_days:] if len(candles) >= lookback_days else candles


def calculate_atr14(symbol: str) -> float:
    candles = get_daily_candles(symbol, lookback_days=20)
    if len(candles) < 14:
        return 0.0
    highs = [c.high for c in candles]
    lows = [c.low for c in candles]
    closes = [c.close for c in candles]
    trs = []
    for i in range(1, len(candles)):
        tr = max(highs[i] - lows[i], abs(highs[i] - closes[i-1]), abs(lows[i] - closes[i-1]))
        trs.append(tr)
    return float(np.mean(trs[-14:]))


def get_premarket_data(symbol: str, date: str) -> dict:
    d = datetime.strptime(date, "%Y-%m-%d")
    start = ET.localize(d.replace(hour=4, minute=0))
    end = ET.localize(d.replace(hour=9, minute=30))
    candles = get_bars(symbol, TimeFrame(5, TimeFrameUnit.Minute), start, end)
    prev_close = get_prev_close(symbol, date)
    if not candles:
        return {"high": 0.0, "low": 0.0, "open": prev_close, "range_pct": 0.0, "prev_close": prev_close}
    high = max(c.high for c in candles)
    low = min(c.low for c in candles)
    open_price = candles[0].open
    range_pct = (high - low) / prev_close if prev_close > 0 else 0.0
    return {"high": high, "low": low, "open": open_price, "range_pct": range_pct, "prev_close": prev_close}


def get_prev_close(symbol: str, date: str) -> float:
    d = datetime.strptime(date, "%Y-%m-%d")
    start = d - timedelta(days=7)
    end = ET.localize(d.replace(hour=16, minute=0)) - timedelta(days=1)
    candles = get_daily_candles(symbol, lookback_days=5)
    target = d.date()
    past = [c for c in candles if c.timestamp.date() < target]
    return past[-1].close if past else 0.0


def get_avg_volume_30d(symbol: str) -> float:
    candles = get_daily_candles(symbol, lookback_days=30)
    return float(np.mean([c.volume for c in candles])) if candles else 0.0


def get_beta(symbol: str, benchmark: str = "SPY") -> float:
    candles_sym = get_daily_candles(symbol, lookback_days=60)
    candles_spy = get_daily_candles(benchmark, lookback_days=60)
    if len(candles_sym) < 30 or len(candles_spy) < 30:
        return 1.0
    min_len = min(len(candles_sym), len(candles_spy))
    sym_ret = np.diff([c.close for c in candles_sym[-min_len:]])
    spy_ret = np.diff([c.close for c in candles_spy[-min_len:]])
    cov = np.cov(sym_ret, spy_ret)[0][1]
    var = np.var(spy_ret)
    return float(cov / var) if var != 0 else 1.0
