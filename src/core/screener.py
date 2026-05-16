import logging
from datetime import datetime
import pytz

from src.data.alpaca_data import (
    get_avg_volume_30d, calculate_atr14, get_beta, get_daily_candles,
)
from src.config import SCREENER_MIN_IEX_VOLUME

logger = logging.getLogger(__name__)
ET = pytz.timezone("America/New_York")

# S&P 500 large-cap + major ETF universe for screener
SCREENER_UNIVERSE = [
    "SPY", "QQQ", "IWM", "DIA",
    "AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "META", "GOOGL",
    "AVGO", "JPM", "V", "MA", "UNH", "XOM", "WMT", "HD",
    "BAC", "PG", "JNJ", "COST", "ABBV", "MRK", "CVX", "LLY",
    "AMD", "NFLX", "ORCL", "CRM", "ADBE", "INTC", "QCOM",
    "XLF", "XLE", "XLK", "XLV", "XLP",
]


def passes_hard_filters(symbol: str, date: str) -> tuple[bool, dict]:
    """Returns (passes, metadata_dict) for hard screening criteria."""
    try:
        avg_volume = get_avg_volume_30d(symbol)
        if avg_volume < SCREENER_MIN_IEX_VOLUME:
            return False, {}

        price = get_daily_candles(symbol, lookback_days=1)
        if not price:
            return False, {}
        current_price = price[-1].close
        if current_price < 20:
            return False, {}

        atr = calculate_atr14(symbol)
        if atr <= 0:
            return False, {}
        atr_pct = atr / current_price
        if not (0.015 <= atr_pct <= 0.04):
            return False, {}

        beta = get_beta(symbol)
        if not (0.8 <= beta <= 2.0):
            return False, {}

        return True, {
            "symbol": symbol,
            "avg_volume": avg_volume,
            "atr_pct": round(atr_pct, 4),
            "beta": round(beta, 2),
        }
    except Exception as e:
        logger.warning(f"Screener hard filter error for {symbol}: {e}")
        return False, {}


def _score_from_data(
    yesterday,
    avg_volume: float,
    atr_pct: float,
    recent_candles: list,
) -> float:
    """
    Pure scoring function — no external calls, fully testable.

    Components (weights):
      0.35 — Momentum:      body ratio of yesterday's candle (strong move = likely gap)
      0.35 — Volume surge:  yesterday's volume vs 30-day avg (institutional interest)
      0.20 — ATR%:          intraday range potential, normalised to [0.015, 0.04]
      0.10 — Gap tendency:  fraction of last 5 sessions that opened with a gap > 0.3%
    """
    # 1. Momentum
    candle_range = yesterday.high - yesterday.low
    body = abs(yesterday.close - yesterday.open)
    momentum = min(body / candle_range, 1.0) if candle_range > 0 else 0.0

    # 2. Volume surge — capped at 3× average
    vol_ratio = (yesterday.volume / avg_volume) if avg_volume > 0 else 0.0
    volume_surge = min(vol_ratio / 3.0, 1.0)

    # 3. ATR% — normalise from [1.5%, 4%] to [0, 1]
    atr_norm = (atr_pct - 0.015) / (0.04 - 0.015)
    atr_norm = max(0.0, min(atr_norm, 1.0))

    # 4. Gap tendency — fraction of last 5 sessions with gap > 0.3%
    gap_days = 0
    for i in range(1, min(6, len(recent_candles))):
        prev_close = recent_candles[i - 1].close
        curr_open  = recent_candles[i].open
        if prev_close > 0 and abs(curr_open - prev_close) / prev_close >= 0.003:
            gap_days += 1
    gap_tendency = gap_days / 5.0

    return round(
        0.35 * momentum +
        0.35 * volume_surge +
        0.20 * atr_norm +
        0.10 * gap_tendency,
        3,
    )


def compute_daily_score(symbol: str, atr_pct: float) -> float:
    """Score a symbol using daily candle data — IEX-compatible, no intraday required."""
    try:
        candles = get_daily_candles(symbol, lookback_days=10)
        if len(candles) < 2:
            return 0.0
        avg_volume = get_avg_volume_30d(symbol)
        return _score_from_data(candles[-1], avg_volume, atr_pct, candles)
    except Exception as e:
        logger.debug(f"Score error {symbol}: {e}")
        return 0.0


def run_nightly_screener(date: str, top_n: int = 10) -> list[dict]:
    """
    Runs the full nightly screener. Returns top_n symbols ranked by FVG quality score.
    """
    logger.info(f"Starting nightly screener for {date} over {len(SCREENER_UNIVERSE)} symbols")
    candidates = []

    for symbol in SCREENER_UNIVERSE:
        passes, meta = passes_hard_filters(symbol, date)
        if not passes:
            continue
        score = compute_daily_score(symbol, meta.get("atr_pct", 0.0))
        meta["fvg_score"] = score
        candidates.append(meta)
        logger.info(f"  {symbol}: score={score:.3f}, ATR%={meta.get('atr_pct'):.3f}")

    candidates.sort(key=lambda x: x["fvg_score"], reverse=True)
    top = candidates[:top_n]
    logger.info(f"Screener complete. Top {len(top)}: {[c['symbol'] for c in top]}")
    return top
