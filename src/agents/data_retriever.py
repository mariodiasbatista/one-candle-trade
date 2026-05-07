import logging
from datetime import datetime
from typing import Optional
import pytz

from src.models import MarketContext, Candle
from src.data.alpaca_data import (
    get_first_5min_candle, get_1min_candles, calculate_atr14, get_premarket_data,
)
from src.core.filters import news_filter, gap_filter, atr_filter
from src.core.fvg import detect_fvg, check_volume_confirmation
from src.core.screener import run_nightly_screener
from src.db.repository import update_watchlist, get_active_watchlist
from src.config import DEFAULT_WATCHLIST

logger = logging.getLogger(__name__)
ET = pytz.timezone("America/New_York")


class DataRetriever:
    """Agent 1 — fetches market data, runs pre-market checks, monitors 1-min FVGs."""

    def __init__(self):
        self._contexts: dict[str, MarketContext] = {}
        self._watchlist: list[str] = list(DEFAULT_WATCHLIST)

    # ------------------------------------------------------------------
    # Nightly screener — runs at 8 PM EST
    # ------------------------------------------------------------------
    def run_nightly_screener(self):
        today = datetime.now(ET).strftime("%Y-%m-%d")
        logger.info("Agent 1: Running nightly screener")
        top = run_nightly_screener(today)
        if top:
            update_watchlist(top)
            self._watchlist = [t["symbol"] for t in top]
        else:
            # Fallback to defaults if screener returns empty
            self._watchlist = list(DEFAULT_WATCHLIST)
        logger.info(f"Agent 1: Watchlist updated → {self._watchlist}")

    # ------------------------------------------------------------------
    # Pre-market check — runs at 9:00 AM EST
    # ------------------------------------------------------------------
    def run_premarket_checks(self) -> dict[str, MarketContext]:
        today = datetime.now(ET).strftime("%Y-%m-%d")
        watchlist = get_active_watchlist() or self._watchlist
        self._contexts = {}

        for symbol in watchlist:
            ctx = MarketContext(
                symbol=symbol,
                date=today,
                trade_allowed=True,
                skip_reason=None,
                premarket_gap_pct=0.0,
                atr_14_daily=0.0,
                first_candle=None,
                key_high=0.0,
                key_low=0.0,
                candle_range=0.0,
                candle_range_valid=False,
            )

            # News filter
            ok, reason = news_filter(today)
            if not ok:
                ctx.trade_allowed = False
                ctx.skip_reason = reason
                self._contexts[symbol] = ctx
                logger.info(f"Agent 1: {symbol} SKIP — {reason}")
                continue

            # Gap filter
            try:
                pm = get_premarket_data(symbol, today)
                ctx.premarket_gap_pct = pm.get("range_pct", 0.0)
                ok, reason = gap_filter(pm.get("prev_close", 0.0), pm.get("open", 0.0), ctx.premarket_gap_pct)
                if not ok:
                    ctx.trade_allowed = False
                    ctx.skip_reason = reason
                    self._contexts[symbol] = ctx
                    logger.info(f"Agent 1: {symbol} SKIP — {reason}")
                    continue
            except Exception as e:
                logger.warning(f"Agent 1: Pre-market data error for {symbol}: {e}")

            self._contexts[symbol] = ctx
            logger.info(f"Agent 1: {symbol} pre-market check PASSED")

        return self._contexts

    # ------------------------------------------------------------------
    # First candle levels — runs at 9:35 AM EST
    # ------------------------------------------------------------------
    def mark_first_candle_levels(self):
        today = datetime.now(ET).strftime("%Y-%m-%d")
        for symbol, ctx in self._contexts.items():
            if not ctx.trade_allowed:
                continue
            try:
                atr = calculate_atr14(symbol)
                ctx.atr_14_daily = atr
                first_candle = get_first_5min_candle(symbol, today)
                if not first_candle:
                    ctx.trade_allowed = False
                    ctx.skip_reason = "No first candle data"
                    continue
                ctx.first_candle = first_candle
                ctx.key_high = first_candle.high
                ctx.key_low = first_candle.low
                ctx.candle_range = first_candle.range

                ok, reason = atr_filter(first_candle, atr)
                ctx.candle_range_valid = ok
                if not ok:
                    ctx.trade_allowed = False
                    ctx.skip_reason = reason
                    logger.info(f"Agent 1: {symbol} SKIP — {reason}")
                else:
                    logger.info(f"Agent 1: {symbol} levels marked — HIGH={ctx.key_high} LOW={ctx.key_low} ATR={atr:.2f}")
            except Exception as e:
                logger.warning(f"Agent 1: First candle error for {symbol}: {e}")
                ctx.trade_allowed = False
                ctx.skip_reason = str(e)

    # ------------------------------------------------------------------
    # 1-min FVG monitoring — called every 60s from 9:35 to 10:30 AM
    # ------------------------------------------------------------------
    def update_1min_candles(self) -> dict[str, MarketContext]:
        today = datetime.now(ET).strftime("%Y-%m-%d")
        for symbol, ctx in self._contexts.items():
            if not ctx.trade_allowed:
                continue
            try:
                candles = get_1min_candles(symbol, today)
                ctx.candles_1min = candles
                fvg = detect_fvg(candles, ctx.key_high, ctx.key_low)
                if fvg:
                    confirmed, ratio = check_volume_confirmation(candles)
                    ctx.fvg = fvg
                    ctx.volume_ratio = ratio
                    ctx.volume_confirmed = confirmed
                    logger.info(f"Agent 1: {symbol} FVG detected — {fvg.direction} | vol_ratio={ratio}")
            except Exception as e:
                logger.warning(f"Agent 1: 1-min update error for {symbol}: {e}")
        return self._contexts

    def get_contexts(self) -> dict[str, MarketContext]:
        return self._contexts
