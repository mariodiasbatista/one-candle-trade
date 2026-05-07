import pytest
from unittest.mock import MagicMock, patch
from src.agents.investor import Investor
from alpaca.trading.enums import OrderStatus


def _make_investor():
    with patch("src.agents.investor.TradingClient") as mock_cls:
        mock_client = MagicMock()
        mock_cls.return_value = mock_client
        mock_telegram = MagicMock()
        investor = Investor(mock_telegram)
        return investor, mock_client, mock_telegram


def _make_db_trade(symbol="SPY", signal="LONG", entry=500.0, stop_loss=498.0,
                   take_profit=504.0, qty=10, order_id="order-123", trade_id="trade-abc"):
    trade = MagicMock()
    trade.id = trade_id
    trade.symbol = symbol
    trade.date = "2026-05-07"
    trade.signal = signal
    trade.entry = entry
    trade.stop_loss = stop_loss
    trade.take_profit = take_profit
    trade.stop_type = "Option B (First Candle)"
    trade.qty = qty
    trade.alpaca_order_id = order_id
    trade.fvg_body_ratio = 2.0
    trade.volume_ratio = 1.8
    trade.filters_passed = []
    return trade


class TestRecoverOpenTrades:

    def test_no_pending_trades_does_nothing(self):
        investor, client, telegram = _make_investor()
        with patch("src.agents.investor.get_pending_trades", return_value=[]):
            investor.recover_open_trades()
        client.get_all_positions.assert_not_called()

    def test_position_still_open_rebuilds_open_trades(self):
        investor, client, telegram = _make_investor()
        trade = _make_db_trade()
        position = MagicMock()
        position.symbol = "SPY"
        client.get_all_positions.return_value = [position]
        with patch("src.agents.investor.get_pending_trades", return_value=[trade]):
            investor.recover_open_trades()
        assert "SPY" in investor._open_trades
        assert investor._open_trades["SPY"]["trade_id"] == "trade-abc"
        assert investor._open_trades["SPY"]["order_id"] == "order-123"
        assert investor._open_trades["SPY"]["qty"] == 10

    def test_position_closed_during_downtime_records_result(self):
        investor, client, telegram = _make_investor()
        trade = _make_db_trade(entry=500.0, take_profit=504.0)
        client.get_all_positions.return_value = []
        mock_order = MagicMock()
        mock_order.filled_avg_price = "504.0"
        client.get_order_by_id.return_value = mock_order
        with patch("src.agents.investor.get_pending_trades", return_value=[trade]), \
             patch("src.agents.investor.close_trade") as mock_close:
            investor.recover_open_trades()
        assert "SPY" not in investor._open_trades
        mock_close.assert_called_once()
        args = mock_close.call_args[0]
        assert args[0] == "trade-abc"   # trade_id
        assert args[1] == 504.0          # exit_price
        assert args[2] == "WIN"          # result

    def test_position_closed_as_loss_during_downtime(self):
        investor, client, telegram = _make_investor()
        trade = _make_db_trade(entry=500.0, take_profit=504.0, stop_loss=498.0)
        client.get_all_positions.return_value = []
        mock_order = MagicMock()
        mock_order.filled_avg_price = "497.0"
        client.get_order_by_id.return_value = mock_order
        with patch("src.agents.investor.get_pending_trades", return_value=[trade]), \
             patch("src.agents.investor.close_trade") as mock_close:
            investor.recover_open_trades()
        args = mock_close.call_args[0]
        assert args[2] == "LOSS"

    def test_order_fetch_error_falls_back_to_entry_price(self):
        investor, client, telegram = _make_investor()
        trade = _make_db_trade(entry=500.0)
        client.get_all_positions.return_value = []
        client.get_order_by_id.side_effect = Exception("API error")
        with patch("src.agents.investor.get_pending_trades", return_value=[trade]), \
             patch("src.agents.investor.close_trade") as mock_close:
            investor.recover_open_trades()
        args = mock_close.call_args[0]
        assert args[1] == 500.0  # falls back to entry

    def test_recovery_error_does_not_crash(self):
        investor, client, telegram = _make_investor()
        trade = _make_db_trade()
        client.get_all_positions.side_effect = Exception("connection error")
        with patch("src.agents.investor.get_pending_trades", return_value=[trade]):
            investor.recover_open_trades()  # should not raise

    def test_multiple_pending_trades_all_recovered(self):
        investor, client, telegram = _make_investor()
        trade1 = _make_db_trade(symbol="SPY", trade_id="t1", order_id="o1")
        trade2 = _make_db_trade(symbol="AAPL", trade_id="t2", order_id="o2")
        pos1 = MagicMock(); pos1.symbol = "SPY"
        pos2 = MagicMock(); pos2.symbol = "AAPL"
        client.get_all_positions.return_value = [pos1, pos2]
        with patch("src.agents.investor.get_pending_trades", return_value=[trade1, trade2]):
            investor.recover_open_trades()
        assert "SPY" in investor._open_trades
        assert "AAPL" in investor._open_trades

    def test_telegram_notified_on_open_recovery(self):
        investor, client, telegram = _make_investor()
        trade = _make_db_trade()
        pos = MagicMock(); pos.symbol = "SPY"
        client.get_all_positions.return_value = [pos]
        with patch("src.agents.investor.get_pending_trades", return_value=[trade]):
            investor.recover_open_trades()
        telegram.log_info.assert_called()

    def test_telegram_notified_on_closed_during_downtime(self):
        investor, client, telegram = _make_investor()
        trade = _make_db_trade()
        client.get_all_positions.return_value = []
        mock_order = MagicMock()
        mock_order.filled_avg_price = "504.0"
        client.get_order_by_id.return_value = mock_order
        with patch("src.agents.investor.get_pending_trades", return_value=[trade]), \
             patch("src.agents.investor.close_trade"):
            investor.recover_open_trades()
        telegram.log_info.assert_called()


class TestSignalFromTrade:

    def test_reconstructs_signal_correctly(self):
        investor, _, _ = _make_investor()
        trade = _make_db_trade(symbol="SPY", signal="LONG", entry=500.0,
                               stop_loss=498.0, take_profit=504.0)
        signal = investor._signal_from_trade(trade)
        assert signal.symbol == "SPY"
        assert signal.signal == "LONG"
        assert signal.entry == 500.0
        assert signal.stop_loss == 498.0
        assert signal.take_profit == 504.0
        assert signal.risk == 2.0
        assert signal.reward == 4.0

    def test_handles_none_fields_gracefully(self):
        investor, _, _ = _make_investor()
        trade = _make_db_trade()
        trade.entry = None
        trade.stop_loss = None
        trade.take_profit = None
        signal = investor._signal_from_trade(trade)
        assert signal.entry == 0.0
        assert signal.stop_loss == 0.0
        assert signal.take_profit == 0.0
