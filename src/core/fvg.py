from typing import Optional
import numpy as np

from src.config import FVG_BODY_RATIO_MIN, VOLUME_RATIO_MIN
from src.models import Candle, FVGResult


def detect_fvg(candles_1min: list[Candle], key_high: float, key_low: float) -> Optional[FVGResult]:
    """
    4-condition FVG detector (V3 spec).

    Condition 1: Three-candle pattern (A, B, C)
    Condition 2: Candle B body >= FVG_BODY_RATIO_MIN x avg of last 5 bodies
    Condition 3: Gap between A and C (C.low > A.high for bullish, C.high < A.low for bearish)
    Condition 4: Direction aligns with first-candle level break
    """
    if len(candles_1min) < 8:
        return None

    A = candles_1min[-3]
    B = candles_1min[-2]
    C = candles_1min[-1]

    # Condition 2: impulse body threshold
    recent_bodies = [abs(c.close - c.open) for c in candles_1min[-8:-3]]
    avg_body = float(np.mean(recent_bodies)) if recent_bodies else 0.0
    B_body = B.body
    if avg_body == 0 or B_body < FVG_BODY_RATIO_MIN * avg_body:
        return None
    body_ratio = round(B_body / avg_body, 2)

    # Condition 3 + 4: bullish FVG breaking the high
    if C.low > A.high and C.high > key_high:
        gap_low = A.high
        gap_high = C.low
        return FVGResult(
            direction="BULLISH_FVG_BREAK_HIGH",
            gap_high=gap_high,
            gap_low=gap_low,
            gap_size=round(gap_high - gap_low, 4),
            body_ratio=body_ratio,
        )

    # Condition 3 + 4: bearish FVG breaking the low
    if C.high < A.low and C.low < key_low:
        gap_low = C.high
        gap_high = A.low
        return FVGResult(
            direction="BEARISH_FVG_BREAK_LOW",
            gap_high=gap_high,
            gap_low=gap_low,
            gap_size=round(gap_high - gap_low, 4),
            body_ratio=body_ratio,
        )

    return None


def check_volume_confirmation(candles_1min: list[Candle]) -> tuple[bool, float]:
    """
    Breakout candle (last candle) must have volume >= VOLUME_RATIO_MIN x 5-period avg.
    Returns (confirmed, ratio).
    """
    if len(candles_1min) < 6:
        return False, 0.0
    C = candles_1min[-1]
    avg_vol = float(np.mean([c.volume for c in candles_1min[-6:-1]]))
    if avg_vol == 0:
        return False, 0.0
    ratio = round(C.volume / avg_vol, 2)
    return ratio >= VOLUME_RATIO_MIN, ratio
