import pytest
from unittest.mock import patch
from tests.conftest import make_candle


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
