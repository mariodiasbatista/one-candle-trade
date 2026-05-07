import pytest
from src.agents.analyst import Analyst
from src.models import MarketContext, FVGResult, TradeSignal
from tests.conftest import make_candle, make_flat_candles

analyst = Analyst()


def _short_context():
    """A valid bearish context where entry (~94.2) is below the stop (96.82)."""
    candles = make_flat_candles(7, price=97.0) + [
        make_candle(95.5, 95.4, 94.0, 94.2, volume=200_000, minute_offset=7)
    ]
    first_candle = make_candle(97.0, 97.5, 95.5, 97.0)  # range=2.0
    bearish_fvg = FVGResult(
        "BEARISH_FVG_BREAK_LOW", gap_high=96.8, gap_low=95.4, gap_size=1.4, body_ratio=2.5
    )
    return MarketContext(
        symbol="SPY", date="2026-05-07", trade_allowed=True, skip_reason=None,
        premarket_gap_pct=0.003, atr_14_daily=5.0, first_candle=first_candle,
        key_high=97.5, key_low=95.5, candle_range=2.0, candle_range_valid=True,
        candles_1min=candles, fvg=bearish_fvg, volume_ratio=2.0, volume_confirmed=True,
    )


def _base_context(**overrides):
    candles = make_flat_candles(7) + [make_candle(101.0, 102.0, 100.5, 101.5, volume=200_000, minute_offset=7)]
    first_candle = make_candle(99.0, 100.5, 98.5, 99.8)  # range=2.0
    defaults = dict(
        symbol="SPY", date="2026-05-07",
        trade_allowed=True, skip_reason=None,
        premarket_gap_pct=0.003, atr_14_daily=5.0,
        first_candle=first_candle,
        key_high=100.5, key_low=98.5,
        candle_range=2.0, candle_range_valid=True,
        candles_1min=candles,
        fvg=FVGResult("BULLISH_FVG_BREAK_HIGH", gap_high=100.6, gap_low=100.5, gap_size=0.1, body_ratio=2.5),
        volume_ratio=2.0, volume_confirmed=True,
    )
    defaults.update(overrides)
    return MarketContext(**defaults)


class TestAnalystAnalyze:
    def test_trade_not_allowed_returns_none(self):
        ctx = _base_context(trade_allowed=False, skip_reason="Gap too large")
        assert analyst.analyze(ctx) is None

    def test_candle_range_invalid_returns_none(self):
        ctx = _base_context(candle_range_valid=False)
        assert analyst.analyze(ctx) is None

    def test_no_fvg_returns_none(self):
        ctx = _base_context(fvg=None)
        assert analyst.analyze(ctx) is None

    def test_volume_not_confirmed_returns_none(self):
        ctx = _base_context(volume_confirmed=False, volume_ratio=1.2)
        assert analyst.analyze(ctx) is None

    def test_valid_long_signal_returned(self):
        ctx = _base_context()
        signal = analyst.analyze(ctx)
        assert signal is not None
        assert isinstance(signal, TradeSignal)
        assert signal.signal == "LONG"

    def test_long_entry_is_last_candle_close(self):
        ctx = _base_context()
        signal = analyst.analyze(ctx)
        assert signal.entry == ctx.candles_1min[-1].close

    def test_long_stop_loss_below_entry(self):
        ctx = _base_context()
        signal = analyst.analyze(ctx)
        assert signal.stop_loss < signal.entry

    def test_long_take_profit_above_entry(self):
        ctx = _base_context()
        signal = analyst.analyze(ctx)
        assert signal.take_profit > signal.entry

    def test_reward_risk_ratio_is_2_to_1(self):
        ctx = _base_context()
        signal = analyst.analyze(ctx)
        assert round(signal.reward / signal.risk, 1) == 2.0

    def test_valid_short_signal_returned(self):
        ctx = _short_context()
        signal = analyst.analyze(ctx)
        assert signal is not None
        assert signal.signal == "SHORT"

    def test_short_stop_loss_above_entry(self):
        # Entry ~94.2, stop via Option A = gap_high+0.02 = 96.82 > 94.2 ✓
        ctx = _short_context()
        signal = analyst.analyze(ctx)
        assert signal.stop_loss > signal.entry

    def test_short_take_profit_below_entry(self):
        ctx = _short_context()
        signal = analyst.analyze(ctx)
        assert signal.take_profit < signal.entry

    def test_signal_has_all_filters_passed(self):
        ctx = _base_context()
        signal = analyst.analyze(ctx)
        assert "fvg_ok" in signal.filters_passed
        assert "volume_ok" in signal.filters_passed

    def test_signal_confidence_is_high(self):
        ctx = _base_context()
        signal = analyst.analyze(ctx)
        assert signal.confidence == "HIGH"

    def test_signal_contains_fvg_and_volume_ratios(self):
        ctx = _base_context()
        signal = analyst.analyze(ctx)
        assert signal.fvg_body_ratio == ctx.fvg.body_ratio
        assert signal.volume_ratio == ctx.volume_ratio
