import pytest
from unittest.mock import patch, MagicMock
from src.agents.data_retriever import DataRetriever
from src.models import MarketContext
from tests.conftest import make_candle, make_flat_candles


def _make_retriever():
    return DataRetriever()


class TestRunNightlyScreener:
    def test_updates_watchlist_with_screener_results(self):
        retriever = _make_retriever()
        top = [{"symbol": "AAPL", "fvg_score": 0.8, "avg_volume": 1e8, "atr_pct": 0.02, "beta": 1.0}]
        with patch("src.agents.data_retriever.run_nightly_screener", return_value=top), \
             patch("src.agents.data_retriever.update_watchlist") as mock_update:
            retriever.run_nightly_screener()
        mock_update.assert_called_once_with(top)
        assert retriever._watchlist == ["AAPL"]

    def test_fallback_to_default_when_screener_empty(self):
        retriever = _make_retriever()
        with patch("src.agents.data_retriever.run_nightly_screener", return_value=[]), \
             patch("src.agents.data_retriever.update_watchlist"):
            retriever.run_nightly_screener()
        assert "SPY" in retriever._watchlist


class TestRunPremarketChecks:
    def _premarket_data(self, gap=0.003):
        return {"high": 101.0, "low": 99.0, "open": 100.3, "range_pct": gap, "prev_close": 100.0}

    def test_all_pass_creates_allowed_context(self):
        retriever = _make_retriever()
        retriever._watchlist = ["SPY"]
        with patch("src.agents.data_retriever.news_filter", return_value=(True, "")), \
             patch("src.agents.data_retriever.get_premarket_data", return_value=self._premarket_data()), \
             patch("src.agents.data_retriever.gap_filter", return_value=(True, "")), \
             patch("src.agents.data_retriever.get_active_watchlist", return_value=["SPY"]):
            contexts = retriever.run_premarket_checks()
        assert "SPY" in contexts
        assert contexts["SPY"].trade_allowed is True

    def test_news_filter_blocks_symbol(self):
        retriever = _make_retriever()
        retriever._watchlist = ["SPY"]
        with patch("src.agents.data_retriever.news_filter", return_value=(False, "FOMC day")), \
             patch("src.agents.data_retriever.get_active_watchlist", return_value=["SPY"]):
            contexts = retriever.run_premarket_checks()
        assert contexts["SPY"].trade_allowed is False
        assert contexts["SPY"].skip_reason == "FOMC day"

    def test_gap_filter_blocks_symbol(self):
        retriever = _make_retriever()
        retriever._watchlist = ["SPY"]
        with patch("src.agents.data_retriever.news_filter", return_value=(True, "")), \
             patch("src.agents.data_retriever.get_premarket_data", return_value=self._premarket_data(gap=0.05)), \
             patch("src.agents.data_retriever.gap_filter", return_value=(False, "Gap too large")), \
             patch("src.agents.data_retriever.get_active_watchlist", return_value=["SPY"]):
            contexts = retriever.run_premarket_checks()
        assert contexts["SPY"].trade_allowed is False

    def test_premarket_data_exception_continues(self):
        retriever = _make_retriever()
        retriever._watchlist = ["SPY"]
        with patch("src.agents.data_retriever.news_filter", return_value=(True, "")), \
             patch("src.agents.data_retriever.get_premarket_data", side_effect=Exception("API error")), \
             patch("src.agents.data_retriever.get_active_watchlist", return_value=["SPY"]):
            contexts = retriever.run_premarket_checks()
        assert "SPY" in contexts
        assert contexts["SPY"].trade_allowed is True  # continues past data error


class TestMarkFirstCandleLevels:
    def _setup_retriever_with_context(self, trade_allowed=True):
        retriever = _make_retriever()
        from src.models import MarketContext
        ctx = MarketContext(
            symbol="SPY", date="2026-05-07", trade_allowed=trade_allowed, skip_reason=None,
            premarket_gap_pct=0.003, atr_14_daily=0.0, first_candle=None,
            key_high=0.0, key_low=0.0, candle_range=0.0, candle_range_valid=False,
        )
        retriever._contexts = {"SPY": ctx}
        return retriever

    def test_marks_levels_on_valid_candle(self):
        retriever = self._setup_retriever_with_context()
        first_candle = make_candle(99, 100.5, 98.5, 100, minute_offset=0)
        with patch("src.agents.data_retriever.calculate_atr14", return_value=5.0), \
             patch("src.agents.data_retriever.get_first_5min_candle", return_value=first_candle), \
             patch("src.agents.data_retriever.atr_filter", return_value=(True, "")):
            retriever.mark_first_candle_levels()
        ctx = retriever._contexts["SPY"]
        assert ctx.first_candle is first_candle
        assert ctx.key_high == 100.5
        assert ctx.key_low == 98.5
        assert ctx.candle_range_valid is True

    def test_no_first_candle_disables_trade(self):
        retriever = self._setup_retriever_with_context()
        with patch("src.agents.data_retriever.calculate_atr14", return_value=5.0), \
             patch("src.agents.data_retriever.get_first_5min_candle", return_value=None):
            retriever.mark_first_candle_levels()
        ctx = retriever._contexts["SPY"]
        assert ctx.trade_allowed is False
        assert ctx.skip_reason == "No first candle data"

    def test_atr_filter_fail_disables_trade(self):
        retriever = self._setup_retriever_with_context()
        first_candle = make_candle(99, 100.5, 98.5, 100)
        with patch("src.agents.data_retriever.calculate_atr14", return_value=5.0), \
             patch("src.agents.data_retriever.get_first_5min_candle", return_value=first_candle), \
             patch("src.agents.data_retriever.atr_filter", return_value=(False, "Candle too small")):
            retriever.mark_first_candle_levels()
        assert retriever._contexts["SPY"].trade_allowed is False

    def test_skips_symbols_with_trade_not_allowed(self):
        retriever = self._setup_retriever_with_context(trade_allowed=False)
        with patch("src.agents.data_retriever.get_first_5min_candle") as mock_candle:
            retriever.mark_first_candle_levels()
        mock_candle.assert_not_called()


class TestUpdate1MinCandles:
    def test_updates_context_with_candles(self):
        retriever = _make_retriever()
        first_candle = make_candle(99, 100.5, 98.5, 100)
        from src.models import MarketContext
        ctx = MarketContext(
            symbol="SPY", date="2026-05-07", trade_allowed=True, skip_reason=None,
            premarket_gap_pct=0.0, atr_14_daily=5.0, first_candle=first_candle,
            key_high=100.5, key_low=98.5, candle_range=2.0, candle_range_valid=True,
        )
        retriever._contexts = {"SPY": ctx}
        candles = make_flat_candles(10)
        with patch("src.agents.data_retriever.get_1min_candles", return_value=candles), \
             patch("src.agents.data_retriever.detect_fvg", return_value=None):
            retriever.update_1min_candles()
        assert ctx.candles_1min == candles

    def test_skips_fvg_scan_when_first_candle_is_none(self):
        retriever = _make_retriever()
        from src.models import MarketContext
        ctx = MarketContext(
            symbol="SPY", date="2026-05-07", trade_allowed=True, skip_reason=None,
            premarket_gap_pct=0.0, atr_14_daily=5.0, first_candle=None,
            key_high=0.0, key_low=0.0, candle_range=0.0, candle_range_valid=False,
        )
        retriever._contexts = {"SPY": ctx}
        with patch("src.agents.data_retriever.get_1min_candles") as mock_get:
            retriever.update_1min_candles()
        mock_get.assert_not_called()

    def test_exception_in_update_continues_when_first_candle_set(self):
        retriever = _make_retriever()
        first_candle = make_candle(99, 100.5, 98.5, 100)
        from src.models import MarketContext
        ctx = MarketContext(
            symbol="SPY", date="2026-05-07", trade_allowed=True, skip_reason=None,
            premarket_gap_pct=0.0, atr_14_daily=5.0, first_candle=first_candle,
            key_high=100.5, key_low=98.5, candle_range=2.0, candle_range_valid=True,
        )
        retriever._contexts = {"SPY": ctx}
        with patch("src.agents.data_retriever.get_1min_candles", side_effect=Exception("timeout")):
            retriever.update_1min_candles()  # should not raise


class TestGetContexts:
    def test_returns_current_contexts(self):
        retriever = _make_retriever()
        assert retriever.get_contexts() == {}
        retriever._contexts = {"SPY": MagicMock()}
        assert "SPY" in retriever.get_contexts()
