import logging
from datetime import datetime
import pytz

from src.data.alpaca_data import (
    get_avg_volume_30d, calculate_atr14, get_beta,
    get_first_5min_candle, get_1min_candles, get_daily_candles,
)
from src.core.filters import atr_filter
from src.core.fvg import detect_fvg, check_volume_confirmation

logger = logging.getLogger(__name__)
ET = pytz.timezone("America/New_York")

# S&P 500 large-cap + major ETF universe for screener
SCREENER_UNIVERSE = [
    "SPY", "QQQ", "IWM", "DIA",
    "AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "META", "GOOGL", "GOOG",
    "AVGO", "JPM", "V", "MA", "UNH", "XOM", "WMT", "HD",
    "BAC", "PG", "JNJ", "COST", "ABBV", "MRK", "CVX", "LLY",
    "AMD", "NFLX", "ORCL", "CRM", "ADBE", "INTC", "QCOM",
    "XLF", "XLE", "XLK", "XLV", "XLP",
]


def passes_hard_filters(symbol: str, date: str) -> tuple[bool, dict]:
    """Returns (passes, metadata_dict) for hard screening criteria."""
    try:
        avg_volume = get_avg_volume_30d(symbol)
        if avg_volume < 5_000_000:
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


def get_fvg_quality_score(symbol: str, lookback_days: int = 30) -> float:
    """
    Score = fraction of tradeable days (last 30) where a clean, volume-confirmed
    FVG appeared that broke the first-candle HIGH or LOW.
    """
    from src.data.alpaca_data import get_daily_candles as get_days
    tradeable = 0
    valid = 0

    trading_days = get_days(symbol, lookback_days=lookback_days + 5)
    if not trading_days:
        return 0.0

    for candle_day in trading_days[-lookback_days:]:
        day_str = candle_day.timestamp.strftime("%Y-%m-%d")
        try:
            first_candle = get_first_5min_candle(symbol, day_str)
            if not first_candle:
                continue
            atr = calculate_atr14(symbol)
            ok, _ = atr_filter(first_candle, atr)
            if not ok:
                continue
            tradeable += 1
            candles_1min = get_1min_candles(symbol, day_str)
            if len(candles_1min) < 8:
                continue
            fvg = detect_fvg(candles_1min, first_candle.high, first_candle.low)
            if fvg:
                confirmed, _ = check_volume_confirmation(candles_1min)
                if confirmed:
                    valid += 1
        except Exception as e:
            logger.debug(f"FVG score error {symbol} {day_str}: {e}")
            continue

    return round(valid / tradeable, 3) if tradeable > 0 else 0.0


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
        score = get_fvg_quality_score(symbol)
        meta["fvg_score"] = score
        candidates.append(meta)
        logger.info(f"  {symbol}: FVG score={score:.3f}, ATR%={meta.get('atr_pct'):.3f}")

    candidates.sort(key=lambda x: x["fvg_score"], reverse=True)
    top = candidates[:top_n]
    logger.info(f"Screener complete. Top {len(top)}: {[c['symbol'] for c in top]}")
    return top
