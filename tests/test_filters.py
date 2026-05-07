import pytest
from src.core.filters import news_filter, gap_filter, atr_filter, run_all_filters
from tests.conftest import make_candle


class TestNewsFilter:
    def test_fomc_day_blocked(self):
        ok, reason = news_filter("2026-03-18")
        assert ok is False
        assert "FOMC" in reason

    def test_cpi_day_blocked(self):
        ok, reason = news_filter("2026-05-13")
        assert ok is False
        assert "CPI" in reason

    def test_nfp_friday_blocked(self):
        ok, reason = news_filter("2026-05-01")
        assert ok is False
        assert "NFP" in reason

    def test_normal_day_passes(self):
        ok, reason = news_filter("2026-05-07")
        assert ok is True
        assert reason == ""


class TestGapFilter:
    def test_gap_too_large(self):
        # gap = abs(100 - 101) / 100 = 1% > 0.8%
        ok, reason = gap_filter(prev_close=100.0, today_open=101.0, premarket_range_pct=0.005)
        assert ok is False
        assert "Gap too large" in reason

    def test_premarket_too_volatile(self):
        # gap ok but range > 1.5%
        ok, reason = gap_filter(prev_close=100.0, today_open=100.5, premarket_range_pct=0.02)
        assert ok is False
        assert "volatile" in reason

    def test_clean_premarket_passes(self):
        # gap = 0.3% < 0.8%, range = 0.5% < 1.5%
        ok, reason = gap_filter(prev_close=100.0, today_open=100.3, premarket_range_pct=0.005)
        assert ok is True
        assert reason == ""

    def test_zero_prev_close_skips_check(self):
        # prev_close=0 → skip gap check
        ok, reason = gap_filter(prev_close=0.0, today_open=500.0, premarket_range_pct=0.99)
        assert ok is True

    def test_gap_exactly_at_threshold_passes(self):
        # gap_filter uses > (strictly greater), so 0.8% exactly should PASS
        ok, _ = gap_filter(prev_close=100.0, today_open=100.8, premarket_range_pct=0.005)
        assert ok is True

    def test_gap_just_above_threshold_fails(self):
        # gap = 0.81% > 0.8% → should FAIL
        ok, reason = gap_filter(prev_close=100.0, today_open=100.81, premarket_range_pct=0.005)
        assert ok is False
        assert "Gap too large" in reason


class TestAtrFilter:
    def test_candle_too_small(self):
        # range=0.5, ATR=5 → min=1.5, 0.5 < 1.5
        candle = make_candle(100, 100.25, 99.75, 100)  # range = 0.5
        ok, reason = atr_filter(candle, atr_14=5.0)
        assert ok is False
        assert "too small" in reason

    def test_candle_too_large(self):
        # range=8, ATR=5 → max=6, 8 > 6
        candle = make_candle(100, 104, 96, 100)  # range = 8
        ok, reason = atr_filter(candle, atr_14=5.0)
        assert ok is False
        assert "too wide" in reason

    def test_candle_in_range(self):
        # range=2.5, ATR=5 → [1.5, 6] → 2.5 in range
        candle = make_candle(100, 101.25, 98.75, 100)  # range = 2.5
        ok, reason = atr_filter(candle, atr_14=5.0)
        assert ok is True
        assert reason == ""

    def test_zero_atr_skips_check(self):
        candle = make_candle(100, 100.1, 99.9, 100)  # tiny range
        ok, reason = atr_filter(candle, atr_14=0.0)
        assert ok is True

    def test_candle_at_atr_min_boundary(self):
        # range = exactly ATR_MIN_RATIO * atr = 0.3 * 5 = 1.5
        candle = make_candle(100, 100.75, 99.25, 100)  # range = 1.5
        ok, reason = atr_filter(candle, atr_14=5.0)
        assert ok is True  # range >= min (not strictly greater)

    def test_candle_at_atr_max_boundary(self):
        # range = ATR_MAX_RATIO * atr = 1.2 * 5 = 6.0
        candle = make_candle(100, 103, 97, 100)  # range = 6.0
        ok, reason = atr_filter(candle, atr_14=5.0)
        assert ok is True  # range <= max (not strictly less)


class TestRunAllFilters:
    def _valid_candle(self):
        return make_candle(100, 101.25, 98.75, 100)  # range=2.5

    def test_all_filters_pass(self):
        ok, reason, passed = run_all_filters(
            trade_date="2026-05-07",
            prev_close=100.0, today_open=100.3,
            premarket_range_pct=0.005,
            first_candle=self._valid_candle(),
            atr_14=5.0,
        )
        assert ok is True
        assert "news_ok" in passed
        assert "gap_ok" in passed
        assert "atr_ok" in passed

    def test_news_filter_stops_chain(self):
        ok, reason, passed = run_all_filters(
            trade_date="2026-03-18",
            prev_close=100.0, today_open=100.3,
            premarket_range_pct=0.005,
            first_candle=self._valid_candle(),
            atr_14=5.0,
        )
        assert ok is False
        assert "news_ok" not in passed

    def test_gap_filter_stops_chain(self):
        ok, reason, passed = run_all_filters(
            trade_date="2026-05-07",
            prev_close=100.0, today_open=101.5,  # 1.5% gap
            premarket_range_pct=0.005,
            first_candle=self._valid_candle(),
            atr_14=5.0,
        )
        assert ok is False
        assert "news_ok" in passed
        assert "gap_ok" not in passed

    def test_atr_filter_stops_chain(self):
        tiny_candle = make_candle(100, 100.1, 99.9, 100)  # range=0.2, too small for ATR=5
        ok, reason, passed = run_all_filters(
            trade_date="2026-05-07",
            prev_close=100.0, today_open=100.3,
            premarket_range_pct=0.005,
            first_candle=tiny_candle,
            atr_14=5.0,
        )
        assert ok is False
        assert "news_ok" in passed
        assert "gap_ok" in passed
        assert "atr_ok" not in passed
