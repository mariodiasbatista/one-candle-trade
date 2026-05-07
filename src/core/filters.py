from src.config import (
    GAP_THRESHOLD, PREMARKET_VOLATILITY_THRESHOLD,
    ATR_MIN_RATIO, ATR_MAX_RATIO,
)
from src.data.calendar import is_high_impact_day
from src.models import Candle


def news_filter(trade_date: str) -> tuple[bool, str]:
    """Returns (can_trade, reason). False means skip today."""
    blocked, reason = is_high_impact_day(trade_date)
    if blocked:
        return False, reason
    return True, ""


def gap_filter(prev_close: float, today_open: float, premarket_range_pct: float) -> tuple[bool, str]:
    """Returns (can_trade, reason)."""
    if prev_close <= 0:
        return True, ""
    gap_pct = abs(prev_close - today_open) / prev_close
    if gap_pct > GAP_THRESHOLD:
        return False, f"Gap too large ({gap_pct:.2%} > {GAP_THRESHOLD:.2%})"
    if premarket_range_pct > PREMARKET_VOLATILITY_THRESHOLD:
        return False, f"Pre-market too volatile ({premarket_range_pct:.2%} > {PREMARKET_VOLATILITY_THRESHOLD:.2%})"
    return True, ""


def atr_filter(first_candle: Candle, atr_14: float) -> tuple[bool, str]:
    """Returns (can_trade, reason). Checks first candle range vs ATR band."""
    if atr_14 <= 0:
        return True, ""
    candle_range = first_candle.range
    min_range = ATR_MIN_RATIO * atr_14
    max_range = ATR_MAX_RATIO * atr_14
    if candle_range < min_range:
        return False, f"Candle too small (${candle_range:.2f} < ${min_range:.2f} ATR floor)"
    if candle_range > max_range:
        return False, f"Candle too wide (${candle_range:.2f} > ${max_range:.2f} ATR cap)"
    return True, ""


def run_all_filters(trade_date: str, prev_close: float, today_open: float,
                    premarket_range_pct: float, first_candle: Candle,
                    atr_14: float) -> tuple[bool, str, list[str]]:
    """
    Run all pre-trade filters in sequence.
    Returns (can_trade, skip_reason, passed_filter_names).
    """
    passed = []

    ok, reason = news_filter(trade_date)
    if not ok:
        return False, reason, passed
    passed.append("news_ok")

    ok, reason = gap_filter(prev_close, today_open, premarket_range_pct)
    if not ok:
        return False, reason, passed
    passed.append("gap_ok")

    ok, reason = atr_filter(first_candle, atr_14)
    if not ok:
        return False, reason, passed
    passed.append("atr_ok")

    return True, "", passed
