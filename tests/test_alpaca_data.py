import pytest
from datetime import datetime
from unittest.mock import MagicMock, patch
import pytz

from src.data.alpaca_data import get_bars
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

ET = pytz.timezone("America/New_York")


def _make_bar(open_p=100.0, high=101.0, low=99.0, close=100.5, volume=50000):
    bar = MagicMock()
    bar.timestamp = datetime(2026, 5, 6, 13, 30, tzinfo=pytz.utc)  # 9:30 ET
    bar.open = open_p
    bar.high = high
    bar.low = low
    bar.close = close
    bar.volume = volume
    return bar


def _barset(symbol, bars):
    """Return a mock BarSet where bars[symbol] returns bars."""
    bs = MagicMock()
    bs.__getitem__ = MagicMock(return_value=bars)
    return bs


def _barset_missing(symbol):
    """Return a mock BarSet where bars[symbol] raises KeyError."""
    bs = MagicMock()
    bs.__getitem__ = MagicMock(side_effect=KeyError(symbol))
    return bs


class TestGetBars:
    def _call(self, barset):
        start = ET.localize(datetime(2026, 5, 6, 9, 30))
        end = ET.localize(datetime(2026, 5, 6, 9, 36))
        tf = TimeFrame(5, TimeFrameUnit.Minute)
        with patch("src.data.alpaca_data.get_client") as mock_client:
            mock_client.return_value.get_stock_bars.return_value = barset
            return get_bars("SPY", tf, start, end)

    def test_returns_candles_when_symbol_present(self):
        bar = _make_bar()
        candles = self._call(_barset("SPY", [bar]))
        assert len(candles) == 1
        assert candles[0].open == 100.0
        assert candles[0].high == 101.0
        assert candles[0].close == 100.5

    def test_returns_empty_list_when_symbol_missing(self):
        candles = self._call(_barset_missing("SPY"))
        assert candles == []

    def test_timestamp_converted_to_et(self):
        bar = _make_bar()
        candles = self._call(_barset("SPY", [bar]))
        assert candles[0].timestamp.tzinfo is not None
        assert candles[0].timestamp.hour == 9
        assert candles[0].timestamp.minute == 30

    def test_returns_multiple_candles(self):
        bars = [_make_bar(close=100.0 + i) for i in range(5)]
        candles = self._call(_barset("SPY", bars))
        assert len(candles) == 5

    def test_returns_empty_when_no_bars(self):
        candles = self._call(_barset("SPY", []))
        assert candles == []


class TestGetFirst5MinCandle:
    """Tests for the retry logic added to get_first_5min_candle."""

    def _barset_with(self, bars):
        return _barset("SPY", bars)

    def _call(self, side_effects, retries=4, retry_delay=0):
        from src.data.alpaca_data import get_first_5min_candle
        with patch("src.data.alpaca_data.get_client") as mock_client, \
             patch("src.data.alpaca_data.time.sleep") as mock_sleep:
            mock_client.return_value.get_stock_bars.side_effect = side_effects
            result = get_first_5min_candle("SPY", "2026-05-06", retries=retries, retry_delay=retry_delay)
            return result, mock_sleep

    def test_returns_candle_on_first_attempt(self):
        bar = _make_bar()
        result, mock_sleep = self._call([self._barset_with([bar])])
        assert result is not None
        assert result.open == 100.0
        mock_sleep.assert_not_called()

    def test_returns_candle_on_second_attempt(self):
        bar = _make_bar()
        result, mock_sleep = self._call([
            self._barset_with([]),   # first attempt: empty
            self._barset_with([bar]), # second attempt: data available
        ], retries=4, retry_delay=30)
        assert result is not None
        assert result.open == 100.0
        mock_sleep.assert_called_once_with(30)

    def test_returns_none_after_all_retries_exhausted(self):
        empty = self._barset_with([])
        result, mock_sleep = self._call([empty] * 3, retries=3, retry_delay=30)
        assert result is None
        assert mock_sleep.call_count == 2  # sleeps between attempts, not after last

    def test_no_sleep_after_final_failed_attempt(self):
        empty = self._barset_with([])
        result, mock_sleep = self._call([empty] * 2, retries=2, retry_delay=30)
        assert result is None
        mock_sleep.assert_called_once_with(30)  # only 1 sleep for 2 retries
