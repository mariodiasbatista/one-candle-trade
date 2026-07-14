from src.config import RISK_PER_TRADE_PCT, MAX_POSITION_PCT, REWARD_RISK_RATIO
from src.models import Candle, FVGResult

TICK_SIZE = 0.01


def calculate_stop_loss(signal: str, first_candle: Candle, fvg: FVGResult) -> tuple[float, str]:
    """
    Option A (FVG-based) SL: place stop just outside the FVG gap.
    For LONG: stop = gap_low - 2 ticks (price re-entering gap invalidates setup).
    For SHORT: stop = gap_high + 2 ticks.
    Returns (stop_price, stop_type_label).
    """
    stop_type = "Option A (FVG-based)"
    if signal == "LONG":
        return round(fvg.gap_low - (2 * TICK_SIZE), 2), stop_type
    else:
        return round(fvg.gap_high + (2 * TICK_SIZE), 2), stop_type


def calculate_take_profit(signal: str, entry: float, stop_loss: float) -> float:
    risk = abs(entry - stop_loss)
    if signal == "LONG":
        return round(entry + risk * REWARD_RISK_RATIO, 2)
    else:
        return round(entry - risk * REWARD_RISK_RATIO, 2)


def calculate_position_size(account_value: float, entry: float, stop_loss: float) -> int:
    """
    Risk 1% of account. Cap at 5% of account in position value.
    Returns number of whole shares (minimum 1).
    """
    if entry <= 0:
        return 0
    risk_dollars = account_value * RISK_PER_TRADE_PCT
    risk_per_share = abs(entry - stop_loss)
    if risk_per_share <= 0:
        return 0
    size = int(risk_dollars / risk_per_share)
    max_size = int((account_value * MAX_POSITION_PCT) / entry)
    size = min(size, max_size)
    return max(size, 1)
