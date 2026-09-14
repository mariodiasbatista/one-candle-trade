import logging

from src.config import RISK_PER_TRADE_PCT, MAX_POSITION_PCT, REWARD_RISK_RATIO
from src.models import Candle, FVGResult

logger = logging.getLogger(__name__)

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
    """Size a position, then cap it at MAX_POSITION_PCT of account value.

    Note which constraint actually binds. The risk rule only produces a smaller
    size than the cap when

        risk_per_share > entry * RISK_PER_TRADE_PCT / MAX_POSITION_PCT

    which at the current 1% / 5% settings means a stop more than **20% of the
    entry price** away. Intraday FVG stops here sit around 0.23% of entry, so
    in practice the position cap binds on every trade and the "risk 1% per
    trade" rule never applies: size is fixed notional and the dollars actually
    at risk are just whatever the stop distance happens to be (observed range
    $3.92 to $29.70, against an intended $976).

    This is logged rather than corrected. Making the risk rule bind would scale
    risk per trade by roughly 87x, and the strategy has not yet demonstrated an
    edge — see the 200-clean-trade decision point. The danger to watch for is
    the reverse: widening stops or changing either percentage can silently move
    the binding constraint and jump real risk by orders of magnitude, so the
    binding constraint is logged on every trade.
    """
    if entry <= 0:
        return 0
    risk_dollars = account_value * RISK_PER_TRADE_PCT
    risk_per_share = abs(entry - stop_loss)
    if risk_per_share <= 0:
        return 0
    size_by_risk = int(risk_dollars / risk_per_share)
    max_size = int((account_value * MAX_POSITION_PCT) / entry)
    size = max(min(size_by_risk, max_size), 1)

    bound_by = "position cap" if max_size < size_by_risk else "risk rule"
    actual_risk = size * risk_per_share
    logger.info(
        f"Sizing: {size} shares, bound by {bound_by} | "
        f"risk ${actual_risk:.2f} = {actual_risk / account_value:.4%} of account "
        f"(intended {RISK_PER_TRADE_PCT:.2%})"
    )
    return size
