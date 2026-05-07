import logging
from typing import Optional

from src.models import MarketContext, TradeSignal
from src.core.fvg import detect_fvg, check_volume_confirmation
from src.core.risk import calculate_stop_loss, calculate_take_profit

logger = logging.getLogger(__name__)


class Analyst:
    """Agent 2 — applies all filters, detects FVG, generates TradeSignal."""

    def analyze(self, ctx: MarketContext) -> Optional[TradeSignal]:
        """
        Evaluates a MarketContext. Returns TradeSignal if all conditions pass,
        or None if the setup is invalid or incomplete.
        """
        if not ctx.trade_allowed:
            logger.info(f"Agent 2: {ctx.symbol} — trade not allowed: {ctx.skip_reason}")
            return None

        if not ctx.candle_range_valid:
            logger.info(f"Agent 2: {ctx.symbol} — candle range invalid")
            return None

        if not ctx.fvg:
            return None

        if not ctx.volume_confirmed:
            logger.info(f"Agent 2: {ctx.symbol} — FVG found but volume not confirmed (ratio={ctx.volume_ratio})")
            return None

        fvg = ctx.fvg
        first_candle = ctx.first_candle

        # Determine direction
        if "BULLISH" in fvg.direction:
            signal = "LONG"
            entry = round(ctx.candles_1min[-1].close, 2)
        else:
            signal = "SHORT"
            entry = round(ctx.candles_1min[-1].close, 2)

        stop_loss, stop_type = calculate_stop_loss(signal, first_candle, fvg)
        take_profit = calculate_take_profit(signal, entry, stop_loss)
        risk = round(abs(entry - stop_loss), 2)
        reward = round(abs(take_profit - entry), 2)

        filters_passed = ["news_ok", "gap_ok", "atr_ok", "fvg_ok", "volume_ok"]

        trade_signal = TradeSignal(
            symbol=ctx.symbol,
            date=ctx.date,
            signal=signal,
            entry=entry,
            stop_loss=stop_loss,
            take_profit=take_profit,
            risk=risk,
            reward=reward,
            stop_type=stop_type,
            fvg_body_ratio=fvg.body_ratio,
            volume_ratio=ctx.volume_ratio,
            filters_passed=filters_passed,
            confidence="HIGH",
        )

        logger.info(
            f"Agent 2: SIGNAL {signal} {ctx.symbol} @ {entry} | "
            f"SL={stop_loss} | TP={take_profit} | RR=2:1 | "
            f"FVG={fvg.body_ratio}x | Vol={ctx.volume_ratio}x | {stop_type}"
        )
        return trade_signal
