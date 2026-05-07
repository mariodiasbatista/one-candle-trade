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
