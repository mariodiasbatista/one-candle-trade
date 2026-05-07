from datetime import datetime
import pytz
from src.models import Candle, FVGResult, MarketContext, TradeSignal, TradeResult

ET = pytz.timezone("America/New_York")
DT = datetime(2026, 5, 7, 9, 35, tzinfo=ET)


class TestCandle:
    def test_body_bullish(self):
        c = Candle(DT, open=100.0, high=102.0, low=99.0, close=101.5, volume=1000)
        assert c.body == 1.5

    def test_body_bearish(self):
        c = Candle(DT, open=101.5, high=102.0, low=99.0, close=100.0, volume=1000)
        assert c.body == 1.5

    def test_body_doji(self):
        c = Candle(DT, open=100.0, high=100.5, low=99.5, close=100.0, volume=1000)
        assert c.body == 0.0

    def test_range(self):
        c = Candle(DT, open=100.0, high=103.0, low=98.0, close=101.0, volume=1000)
        assert c.range == 5.0

    def test_range_tight(self):
        c = Candle(DT, open=100.0, high=100.1, low=99.9, close=100.0, volume=1000)
        assert round(c.range, 2) == 0.2


class TestFVGResult:
    def test_bullish_creation(self):
        fvg = FVGResult(
            direction="BULLISH_FVG_BREAK_HIGH",
            gap_high=101.0, gap_low=100.5, gap_size=0.5, body_ratio=2.0,
        )
        assert fvg.direction == "BULLISH_FVG_BREAK_HIGH"
        assert fvg.gap_size == 0.5
        assert fvg.body_ratio == 2.0

    def test_bearish_creation(self):
        fvg = FVGResult(
            direction="BEARISH_FVG_BREAK_LOW",
            gap_high=98.0, gap_low=97.0, gap_size=1.0, body_ratio=3.0,
        )
        assert fvg.direction == "BEARISH_FVG_BREAK_LOW"
        assert fvg.gap_size == 1.0


class TestMarketContext:
    def test_defaults(self):
        ctx = MarketContext(
            symbol="SPY", date="2026-05-07", trade_allowed=True, skip_reason=None,
            premarket_gap_pct=0.0, atr_14_daily=0.0, first_candle=None,
            key_high=0.0, key_low=0.0, candle_range=0.0, candle_range_valid=False,
        )
        assert ctx.candles_1min == []
        assert ctx.fvg is None
        assert ctx.volume_ratio == 0.0
        assert ctx.volume_confirmed is False

    def test_with_values(self):
        candle = Candle(DT, 100, 101, 99, 100.5, 50000)
        ctx = MarketContext(
            symbol="AAPL", date="2026-05-07", trade_allowed=True, skip_reason=None,
            premarket_gap_pct=0.005, atr_14_daily=2.5, first_candle=candle,
            key_high=101.0, key_low=99.0, candle_range=2.0, candle_range_valid=True,
        )
        assert ctx.symbol == "AAPL"
        assert ctx.first_candle is candle
        assert ctx.candle_range_valid is True


class TestTradeSignal:
    def test_long_signal(self):
        sig = TradeSignal(
            symbol="SPY", date="2026-05-07", signal="LONG",
            entry=500.0, stop_loss=498.0, take_profit=504.0,
            risk=2.0, reward=4.0, stop_type="Option B (First Candle)",
            fvg_body_ratio=2.0, volume_ratio=1.8,
        )
        assert sig.signal == "LONG"
        assert sig.confidence == "HIGH"
        assert sig.filters_passed == []
        assert sig.reward / sig.risk == 2.0

    def test_short_signal(self):
        sig = TradeSignal(
            symbol="QQQ", date="2026-05-07", signal="SHORT",
            entry=450.0, stop_loss=452.0, take_profit=446.0,
            risk=2.0, reward=4.0, stop_type="Option A (FVG-based)",
            fvg_body_ratio=3.0, volume_ratio=2.1,
            filters_passed=["news_ok", "gap_ok"],
        )
        assert sig.signal == "SHORT"
        assert len(sig.filters_passed) == 2


class TestTradeResult:
    def test_win_result(self):
        r = TradeResult(
            trade_id="abc", symbol="SPY", date="2026-05-07", signal="LONG",
            entry=500.0, stop_loss=498.0, take_profit=504.0, exit_price=504.0,
            result="WIN", pnl_dollars=40.0, pnl_percent=0.008, qty=10,
            stop_type="Option B (First Candle)", fvg_body_ratio=2.0,
            volume_ratio=1.8, filters_passed=["news_ok"],
        )
        assert r.result == "WIN"
        assert r.pnl_dollars == 40.0
        assert r.skip_reason is None
