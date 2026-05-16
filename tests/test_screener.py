import pytest
from unittest.mock import patch
from tests.conftest import make_candle
from src.core.screener import _score_from_data


def _candle(open_p, high, low, close, volume=300_000):
    return make_candle(open_p, high, low, close, volume=volume)


def _flat_days(n, price=100.0, volume=300_000):
    """n days with tiny body — baseline for comparison."""
    return [_candle(price, price + 0.5, price - 0.5, price + 0.05, volume) for _ in range(n)]


class TestScoreFromData:
    def test_strong_momentum_scores_higher(self):
        # Strong candle: body=4, range=4 → body_ratio=1.0
        strong = _candle(100, 104, 100, 104)
        # Weak candle: body=0.5, range=4 → body_ratio=0.125
        weak   = _candle(100, 104, 100, 100.5)
        days   = _flat_days(5)
        s_strong = _score_from_data(strong, 300_000, 0.025, days)
        s_weak   = _score_from_data(weak,   300_000, 0.025, days)
        assert s_strong > s_weak

    def test_high_volume_scores_higher(self):
        candle   = _candle(100, 103, 99, 103)
        days     = _flat_days(5)
        s_high   = _score_from_data(candle, 300_000, 0.025, days, )
        # same candle, avg_volume doubled → vol_ratio halved
        s_low    = _score_from_data(candle, 600_000, 0.025, days)
        assert s_high > s_low

    def test_higher_atr_scores_higher(self):
        candle = _candle(100, 103, 99, 103)
        days   = _flat_days(5)
        s_high_atr = _score_from_data(candle, 300_000, 0.035, days)
        s_low_atr  = _score_from_data(candle, 300_000, 0.018, days)
        assert s_high_atr > s_low_atr

    def test_gap_tendency_increases_score(self):
        candle = _candle(100, 103, 99, 103)
        # 5 days with gaps > 0.3%
        gapping = [_candle(100, 103, 99, 102)] + \
                  [_candle(102 * 1.005, 106, 101, 105)] * 4 + \
                  [_candle(105 * 1.005, 109, 104, 108)]
        # 5 days with no gaps
        flat = [_candle(100, 103, 99, 100)] * 6
        s_gap  = _score_from_data(candle, 300_000, 0.025, gapping)
        s_flat = _score_from_data(candle, 300_000, 0.025, flat)
        assert s_gap > s_flat

    def test_volume_surge_capped_at_1(self):
        # vol_ratio = 300_000 / 10_000 = 30x → capped at 1.0 (3x cap)
        candle = _candle(100, 104, 100, 104, volume=300_000)
        score  = _score_from_data(candle, 10_000, 0.025, _flat_days(5))
        assert 0.0 <= score <= 1.0

    def test_zero_candle_range_does_not_crash(self):
        # High == Low → range = 0
        candle = _candle(100, 100, 100, 100)
        score  = _score_from_data(candle, 300_000, 0.025, _flat_days(5))
        assert score >= 0.0

    def test_atr_below_range_clamps_to_zero(self):
        candle = _candle(100, 103, 99, 103)
        score  = _score_from_data(candle, 300_000, 0.005, _flat_days(5))  # below 1.5%
        # atr_norm clamped to 0 → atr contributes 0
        score_zero_atr = _score_from_data(candle, 300_000, 0.015, _flat_days(5))  # exactly at floor
        assert score == score_zero_atr

    def test_atr_above_range_clamps_to_one(self):
        candle = _candle(100, 103, 99, 103)
        s_at_cap  = _score_from_data(candle, 300_000, 0.04,  _flat_days(5))
        s_over_cap = _score_from_data(candle, 300_000, 0.06, _flat_days(5))
        assert s_at_cap == s_over_cap

    def test_score_range_is_zero_to_one(self):
        # Perfect score: full body, 3x volume, max ATR, 5/5 gap days
        perfect_candle = _candle(100, 104, 100, 104, volume=900_000)
        gapping = [_candle(100 + i, 104 + i, 100 + i, 104 + i) for i in range(6)]
        score = _score_from_data(perfect_candle, 300_000, 0.04, gapping)
        assert 0.0 <= score <= 1.0

    def test_insufficient_candles_for_gap(self):
        # Only 1 candle → can't compute gap tendency → gap_tendency = 0
        candle = _candle(100, 103, 99, 103)
        score_1  = _score_from_data(candle, 300_000, 0.025, [candle])
        score_6  = _score_from_data(candle, 300_000, 0.025, _flat_days(6))
        # Score with gaps = 0 should be <= score with some gap potential
        assert score_1 <= score_6


def _make_candle_list(n, price=100.0):
    return [make_candle(price, price + 1, price - 1, price, volume=500_000, minute_offset=i) for i in range(n)]


class TestPassesHardFilters:
    def _call(self, symbol="TSLA", avg_volume=500_000, price=200.0, atr=6.0, beta=1.2):
        from src.core.screener import passes_hard_filters
        daily = _make_candle_list(1, price=price)
        with patch("src.core.screener.get_avg_volume_30d", return_value=avg_volume), \
             patch("src.core.screener.get_daily_candles", return_value=daily), \
             patch("src.core.screener.calculate_atr14", return_value=atr), \
             patch("src.core.screener.get_beta", return_value=beta):
            return passes_hard_filters(symbol, "2026-05-08")

    def test_passes_all_filters(self):
        ok, meta = self._call()
        assert ok is True
        assert meta["symbol"] == "TSLA"

    def test_fails_iex_volume_threshold(self):
        # Below SCREENER_MIN_IEX_VOLUME (200_000)
        ok, meta = self._call(avg_volume=50_000)
        assert ok is False
        assert meta == {}

    def test_passes_iex_volume_at_threshold(self):
        ok, meta = self._call(avg_volume=200_000)
        assert ok is True

    def test_fails_price_below_minimum(self):
        ok, meta = self._call(price=15.0, atr=0.5)
        assert ok is False

    def test_fails_atr_pct_too_low(self):
        # atr=1.0, price=200 → atr_pct=0.5% < 1.5%
        ok, meta = self._call(atr=1.0, price=200.0)
        assert ok is False

    def test_fails_atr_pct_too_high(self):
        # atr=10.0, price=200 → atr_pct=5% > 4%
        ok, meta = self._call(atr=10.0, price=200.0)
        assert ok is False

    def test_fails_beta_out_of_range(self):
        ok, meta = self._call(beta=2.5)
        assert ok is False

    def test_exception_returns_false(self):
        from src.core.screener import passes_hard_filters
        with patch("src.core.screener.get_avg_volume_30d", side_effect=Exception("API error")):
            ok, meta = passes_hard_filters("TSLA", "2026-05-08")
        assert ok is False
